"""
Integration tests for segmented (multi-connection) downloads.
Uses a local HTTP server that honors Range requests.
"""

import http.server
import os
import sys
import threading
import time

import pytest

from vf.core.config import Config
from vf.core.database import Database
from vf.core.downloader import DownloadEngine

RANGE_CAPABLE = http.server.SimpleHTTPRequestHandler


class RangeHandler(RANGE_CAPABLE):
    def end_headers(self):
        # Advertise range support
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def send_head(self):
        # Let SimpleHTTPRequestHandler handle normal/HEAD requests, but
        # patch in Range support for GET.
        if self.command == "GET" and "Range" in self.headers:
            return self._send_range()
        return super().send_head()

    def _send_range(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(404)
            return None
        size = os.path.getsize(path)
        rng = self.headers["Range"]
        start_s, end_s = rng.replace("bytes=", "").split("-", 1)
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)
        length = end - start + 1

        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return f


class NoRangeHandler(RANGE_CAPABLE):
    """Plain handler that never advertises or honors Range — forces single stream."""

    def end_headers(self):
        self.send_header("Accept-Ranges", "none")
        super().end_headers()

    def log_message(self, *args):
        pass


class ProbeOnlyRangeHandler(http.server.BaseHTTPRequestHandler):
    """Advertises Range and answers the 1-byte probe with 206 — then lies.

    A real segment request is answered with 200 and the whole body, which is
    exactly the server the segmented downloader has to survive.
    """

    payload = b""

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self.payload)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        if self.headers.get("Range") == "bytes=0-0":
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Range", f"bytes 0-0/{len(self.payload)}")
            self.send_header("Content-Length", "1")
            self.end_headers()
            self.wfile.write(self.payload[:1])
            return
        # Range ignored: full body with a plain 200
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self.payload)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(self.payload)


class _SlowFile:
    """File wrapper that trickles bytes out, standing in for a slow mirror."""

    def __init__(self, fileobj, per_read, delay):
        self._file, self._per_read, self._delay = fileobj, per_read, delay

    def read(self, size=-1):
        time.sleep(self._delay)
        want = self._per_read if size is None or size < 0 else min(size, self._per_read)
        return self._file.read(want)

    def close(self):
        self._file.close()


class UnevenRangeHandler(RangeHandler):
    """Range server that serves the first half of the file slowly.

    Segment 0 then stays below the per-segment speed limit and never sleeps in
    _throttle(), while the other segment is capped and does — the asymmetry
    that lets two progress snapshots be in flight at the same time.
    """

    def _send_range(self):
        fileobj = super()._send_range()
        start = int(self.headers["Range"].replace("bytes=", "").split("-", 1)[0])
        if fileobj is not None and start == 0:
            return _SlowFile(fileobj, 4096, 0.5)  # ~8 KB/s
        return fileobj


@pytest.fixture
def file_server(tmp_path):
    """Serve a random 2 MB file with Range support."""
    data = os.urandom(2 * 1024 * 1024)
    src = tmp_path / "bigfile.bin"
    src.write_bytes(data)
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    os.chdir(tmp_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield data, f"http://127.0.0.1:{port}/bigfile.bin", str(downloads)
    server.shutdown()


@pytest.fixture
def no_range_server(tmp_path):
    """Serve the same file without Range support."""
    data = os.urandom(256 * 1024)
    src = tmp_path / "smallfile.bin"
    src.write_bytes(data)
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    os.chdir(tmp_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NoRangeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield data, f"http://127.0.0.1:{port}/smallfile.bin", str(downloads)
    server.shutdown()


@pytest.fixture
def probe_only_range_server(tmp_path):
    """Serve a 2 MB file that honors Range only for the 1-byte probe."""
    data = os.urandom(2 * 1024 * 1024)
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    handler = type("_Payload", (ProbeOnlyRangeHandler,), {"payload": data})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield data, f"http://127.0.0.1:{port}/liar.bin", str(downloads)
    server.shutdown()


@pytest.fixture
def uneven_range_server(tmp_path):
    """Serve a 2 MB file with Range support, the first segment slowly."""
    data = os.urandom(2 * 1024 * 1024)
    src = tmp_path / "uneven.bin"
    src.write_bytes(data)
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    os.chdir(tmp_path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), UnevenRangeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield data, f"http://127.0.0.1:{port}/uneven.bin", str(downloads)
    server.shutdown()


def _wait_for_completion(engine, task, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if task.status in ("completed", "failed"):
            return task.status
        time.sleep(0.1)
    return "timeout"


def test_segmented_download_completes(tmp_path, file_server, monkeypatch):
    data, url, download_dir = file_server
    monkeypatch.setattr("vf.core.downloader.Config", lambda: _test_config(tmp_path, segments=4))

    db_file = tmp_path / "db.sqlite"
    engine = DownloadEngine(config=_test_config(tmp_path, segments=4), db=Database(db_file))
    task = engine.add_download(url, save_dir=download_dir)
    engine.start_download(task)

    assert _wait_for_completion(engine, task) == "completed"
    with open(task.save_path, "rb") as f:
        assert f.read() == data  # exact bytes, correct order


def test_segmented_resume_after_pause(tmp_path, file_server, monkeypatch):
    data, url, download_dir = file_server
    monkeypatch.setattr("vf.core.downloader.Config", lambda: _test_config(tmp_path, segments=2))

    db_file = tmp_path / "db.sqlite"
    engine = DownloadEngine(config=_test_config(tmp_path, segments=2), db=Database(db_file))
    task = engine.add_download(url, save_dir=download_dir)
    engine.start_download(task)

    # Pause mid-download once some bytes arrive
    deadline = time.time() + 10
    while time.time() < deadline and task.downloaded_size == 0:
        time.sleep(0.05)
    engine.pause_download(task)
    time.sleep(0.5)
    paused_bytes = task.downloaded_size
    assert 0 <= paused_bytes <= len(data)

    engine.resume_download(task)
    assert _wait_for_completion(engine, task) == "completed"
    with open(task.save_path, "rb") as f:
        assert f.read() == data

    # Segment state file cleaned up after completion
    assert not os.path.exists(task.save_path + ".part.segments.json")
    assert not os.path.exists(task.save_path + ".part")


def test_single_stream_fallback(tmp_path, no_range_server, monkeypatch):
    """Servers without Range support must still download via single stream."""
    data, url, download_dir = no_range_server
    monkeypatch.setattr("vf.core.downloader.Config", lambda: _test_config(tmp_path, segments=4))

    db_file = tmp_path / "db.sqlite"
    engine = DownloadEngine(config=_test_config(tmp_path, segments=4), db=Database(db_file))
    task = engine.add_download(url, save_dir=download_dir)
    engine.start_download(task)

    assert _wait_for_completion(engine, task) == "completed"
    with open(task.save_path, "rb") as f:
        assert f.read() == data


def _test_config(tmp_path, segments):
    config = Config()
    config._config_data.update({
        "download_dir": str(tmp_path / "downloads"),
        "segmented": True,
        "download_segments": segments,
        "segmented_min_size": 1024 * 1024,  # 1 MB so the 2 MB test file qualifies
        "max_concurrent": 4,
        "retry_count": 1,
        "retry_delay": 0,
        # Config is a singleton, so reset the limit explicitly: otherwise a
        # test that sets one leaks it into every test that runs after it.
        "speed_limit_kbps": 0,
    })
    return config


def test_checksum_verification(tmp_path, file_server, monkeypatch):
    """Completed downloads verify SHA-256 when one is provided."""
    import hashlib
    data, url, download_dir = file_server
    monkeypatch.setattr("vf.core.downloader.Config", lambda: _test_config(tmp_path, segments=2))

    # small file for quick test
    small = tmp_path / "small.bin"
    small.write_bytes(data[:512 * 1024])
    small_url = url.replace("bigfile.bin", "small.bin")

    good = hashlib.sha256(data[:512 * 1024]).hexdigest()
    db_file = tmp_path / "db.sqlite"
    engine = DownloadEngine(config=_test_config(tmp_path, segments=2), db=Database(db_file))

    task_ok = engine.add_download(small_url, save_dir=download_dir, checksum=good)
    engine.start_download(task_ok)
    assert _wait_for_completion(engine, task_ok) == "completed"
    assert task_ok.checksum_ok is True

    task_bad = engine.add_download(small_url, save_dir=download_dir,
                                   filename="bad.bin", checksum="00" * 32)
    engine.start_download(task_bad)
    assert _wait_for_completion(engine, task_bad) == "completed"
    assert task_bad.checksum_ok is False


def test_speed_limit_throttles(tmp_path, file_server, monkeypatch):
    """A 200 KB/s cap must slow the transfer versus unlimited (localhost)."""
    import time as _time
    data, url, download_dir = file_server
    cfg = _test_config(tmp_path, segments=1)
    cfg._config_data["segmented"] = False          # single stream for clean math
    cfg._config_data["speed_limit_kbps"] = 200     # 200 KB/s
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)

    engine = DownloadEngine(config=cfg, db=Database(tmp_path / "db.sqlite"))
    task = engine.add_download(url, save_dir=download_dir)
    t0 = _time.monotonic()
    engine.start_download(task)
    assert _wait_for_completion(engine, task, timeout=60) == "completed"
    elapsed = _time.monotonic() - t0
    # 2 MB at 200 KB/s ≈ 10 s; localhost unlimited finishes < 1 s.
    # Allow generous margin but require real throttling.
    assert elapsed > 3.0, f"download finished too fast ({elapsed:.1f}s) — limit not applied"


def test_ytdlp_progress_parsing():
    """The yt-dlp progress regex must read the standard --newline output."""
    import re
    pct_re = re.compile(
        r"\[download\]\s+([\d.]+)% of\s+~?\s*([\d\.]+)(KiB|MiB|GiB)"
    )
    line = "[download]  42.5% of   10.00MiB at 2.00MiB/s ETA 00:03"
    m = pct_re.search(line)
    assert m and float(m.group(1)) == 42.5
    mult = {"KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}
    assert float(m.group(2)) * mult[m.group(3)] == 10 * 1024 * 1024

    assert pct_re.search("[info] some other line") is None


def test_ytdlp_task_roundtrip(tmp_path):
    """use_yt_dlp persists on the task and is honored by the engine."""
    cfg = _test_config(tmp_path, segments=1)
    from vf.core.database import Database as DB
    engine = DownloadEngine(config=cfg, db=DB(tmp_path / "db.sqlite"))
    task = engine.add_download("https://example.com/v/abc", use_yt_dlp=True)
    assert task.use_yt_dlp is True
    # reloaded from the DB it stays set
    record = engine.db.get_download(task.id)
    assert record["use_yt_dlp"] == 1


# ── Engine regression helpers ───────────────────────────────────


class _TrackingLock:
    """A threading.Lock stand-in that remembers which thread holds it.

    Used to prove that the segment worker does not perform blocking work
    (sleeping in the speed limiter, writing the state file) while it owns the
    shared counter lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._owner = None

    def acquire(self, *args, **kwargs):
        acquired = self._lock.acquire(*args, **kwargs)
        if acquired:
            self._owner = threading.get_ident()
        return acquired

    def release(self):
        self._owner = None
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    def owned_here(self):
        """True when the calling thread is the one currently holding us."""
        return self._owner == threading.get_ident()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc_info):
        self.release()
        return False


class _ThreadingShim:
    """Proxy for the threading module handing out instrumented locks.

    Only the downloader module's view of `threading` is replaced, so the rest
    of the interpreter keeps the real Lock.
    """

    Lock = _TrackingLock

    def __getattr__(self, name):
        return getattr(threading, name)


def _caller_segment_lock():
    """The `lock` object visible in the frame that called the current spy."""
    return sys._getframe(2).f_locals.get("lock")


# ── Regressions ─────────────────────────────────────────────────


def test_i18n_helper_not_shadowed_in_perform_segmented():
    """`t` must stay the i18n helper inside the segment workers.

    A loop variable named `t` in _perform_segmented turns `t` into a local,
    which seg_worker() then captures as a closure cell — so t("...") would
    call a Thread object instead of translating.
    """
    code = DownloadEngine._perform_segmented.__code__
    assert "t" not in code.co_varnames
    assert "t" not in code.co_cellvars

    inner = [c for c in code.co_consts
             if getattr(c, "co_name", None) == "seg_worker"][0]
    assert "t" not in inner.co_freevars, (
        "seg_worker captured a local named 't' — t('...') would call a Thread"
    )


def test_no_engine_method_shadows_the_i18n_helper():
    """No method may bind a local named `t`, comprehension variables included.

    Since PEP 709 an inlined list comprehension's variable is a real local of
    the enclosing function, so `[t for t in ...]` shadows the helper too.
    """
    import inspect

    offenders = []
    for name, attr in vars(DownloadEngine).items():
        func = attr.__func__ if isinstance(attr, (staticmethod, classmethod)) else attr
        if not inspect.isfunction(func):
            continue
        code = func.__code__
        if "t" in code.co_varnames or "t" in code.co_cellvars:
            offenders.append(name)

    assert offenders == [], f"these methods shadow the i18n helper `t`: {offenders}"


def test_worker_returns_the_slot_it_took(tmp_path, monkeypatch):
    """A settings save mid-download must not corrupt the concurrency slots.

    The limit used to live in a semaphore that apply_concurrency_limit()
    replaced, so the worker released a slot into an object it never took one
    from (a ValueError) — or, once it kept the old object, waited on a stale
    limit forever.
    """
    cfg = _test_config(tmp_path, segments=1)
    cfg._config_data["max_concurrent"] = 3
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)

    engine = DownloadEngine(config=cfg, db=Database(tmp_path / "db.sqlite"))
    task = engine.add_download("http://127.0.0.1:1/never.bin", save_dir=str(tmp_path))

    def swap_the_limit(self, *args, **kwargs):
        assert self._active_slots == 1, "the worker did not take a slot"
        cfg._config_data["max_concurrent"] = 1
        self.apply_concurrency_limit()

    monkeypatch.setattr(DownloadEngine, "_do_download_with_retries", swap_the_limit)

    stop_event = threading.Event()
    pause_event = threading.Event()
    pause_event.set()
    engine._download_worker(task, stop_event, pause_event)  # must not raise

    # The slot came back, and the next admission reads the new limit.
    assert engine._active_slots == 0
    assert engine.config.max_concurrent == 1


def test_lowered_concurrency_limit_reaches_queued_downloads(tmp_path, monkeypatch):
    """Lowering max_concurrent must apply to the downloads already queued.

    Not just to ones started afterwards: a user who drops the limit while a
    backlog is waiting expects the backlog to obey the new number.
    """
    cfg = _test_config(tmp_path, segments=1)
    cfg._config_data["max_concurrent"] = 3
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)

    engine = DownloadEngine(config=cfg, db=Database(tmp_path / "db.sqlite"))

    gate = threading.Event()          # holds the first three slots
    state_lock = threading.Lock()
    running = set()
    queued_together = []

    def fake_download(self, task, stop_event, pause_event, config):
        with state_lock:
            running.add(task.filename)
            queued_together.append(
                len([n for n in running if n.startswith("queued")])
            )
        if task.filename.startswith("holder"):
            gate.wait(20)
        else:
            time.sleep(0.3)
        with state_lock:
            running.discard(task.filename)

    monkeypatch.setattr(DownloadEngine, "_do_download_with_retries", fake_download)

    holders = [
        engine.add_download(f"http://127.0.0.1:1/holder{i}.bin",
                            filename=f"holder{i}.bin", save_dir=str(tmp_path))
        for i in range(3)
    ]
    for task in holders:
        engine.start_download(task)

    deadline = time.time() + 15
    while time.time() < deadline:
        with state_lock:
            if len(running) == 3:
                break
        time.sleep(0.02)
    with state_lock:
        assert len(running) == 3, "the three slots were never taken"

    queued = [
        engine.add_download(f"http://127.0.0.1:1/queued{i}.bin",
                            filename=f"queued{i}.bin", save_dir=str(tmp_path))
        for i in range(3)
    ]
    for task in queued:
        engine.start_download(task)
    time.sleep(0.2)  # let them reach the queue

    # The user lowers the limit in Settings, then the running ones finish.
    cfg._config_data["max_concurrent"] = 1
    engine.apply_concurrency_limit()
    gate.set()

    for task in holders + queued:
        engine._threads[task.id].join(timeout=20)
        assert not engine._threads[task.id].is_alive()

    assert max(queued_together) == 1, (
        f"queued downloads ignored the lowered limit: {queued_together}"
    )
    assert engine._active_slots == 0


def test_concurrency_change_during_download_keeps_worker_alive(
        tmp_path, file_server, monkeypatch):
    """A settings save mid-download must not kill the worker thread."""
    data, url, download_dir = file_server
    cfg = _test_config(tmp_path, segments=1)
    cfg._config_data["segmented"] = False        # single stream, slot logic only
    cfg._config_data["speed_limit_kbps"] = 1024  # ~2 s, room to change settings
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)

    thread_errors = []
    monkeypatch.setattr(
        threading, "excepthook", lambda args: thread_errors.append(args.exc_value)
    )

    engine = DownloadEngine(config=cfg, db=Database(tmp_path / "db.sqlite"))
    task = engine.add_download(url, save_dir=download_dir)
    engine.start_download(task)

    # Wait until the worker actually holds a slot, then shrink the limit.
    deadline = time.time() + 15
    while time.time() < deadline and task.downloaded_size == 0:
        time.sleep(0.02)
    assert task.downloaded_size > 0, "download never started"

    cfg._config_data["max_concurrent"] = 1
    engine.apply_concurrency_limit()

    assert _wait_for_completion(engine, task, timeout=60) == "completed"
    engine._threads[task.id].join(timeout=10)

    assert thread_errors == [], f"worker thread died: {thread_errors!r}"
    with open(task.save_path, "rb") as f:
        assert f.read() == data


def test_segment_throttle_and_save_run_outside_the_shared_lock(
        tmp_path, file_server, monkeypatch):
    """One segment must not block the others on the shared counter lock.

    Sleeping in _throttle() or writing the state file while holding that lock
    stalls every other segment's progress accounting — their byte counters,
    speed, ETA and the GUI notification all wait on one segment's sleep or on
    a slow disk. (Aggregate throughput survives it, because a segment blocked
    on the lock still accrues throttle credit: timing cannot show this, so the
    two assertions below are what guards it.)
    """
    data, url, download_dir = file_server

    # 8 MB gives 4 segments (one per MB, capped by download_segments).
    payload = data * 4
    (tmp_path / "parallel.bin").write_bytes(payload)
    seg_url = url.replace("bigfile.bin", "parallel.bin")

    cfg = _test_config(tmp_path, segments=4)
    cfg._config_data["speed_limit_kbps"] = 4096   # 4 MB/s → 1 MB/s per segment
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)
    monkeypatch.setattr("vf.core.downloader.threading", _ThreadingShim())

    throttle_calls, throttle_under_lock = [], []
    save_calls, save_under_lock = [], []

    real_throttle = DownloadEngine._throttle
    real_save = DownloadEngine._save_segment_state

    def spying_throttle(self, last_check, bytes_since, limit_bps):
        seg_lock = _caller_segment_lock()
        throttle_calls.append(limit_bps)
        if seg_lock is not None and seg_lock.owned_here():
            throttle_under_lock.append(limit_bps)
        return real_throttle(self, last_check, bytes_since, limit_bps)

    def spying_save(state_path, seg_done):
        seg_lock = _caller_segment_lock()
        save_calls.append(len(seg_done))
        if seg_lock is not None and seg_lock.owned_here():
            save_under_lock.append(len(seg_done))
        return real_save(state_path, seg_done)

    monkeypatch.setattr(DownloadEngine, "_throttle", spying_throttle)
    monkeypatch.setattr(DownloadEngine, "_save_segment_state", staticmethod(spying_save))

    engine = DownloadEngine(config=cfg, db=Database(tmp_path / "db.sqlite"))
    task = engine.add_download(seg_url, save_dir=download_dir)
    engine.start_download(task)
    assert _wait_for_completion(engine, task, timeout=90) == "completed"

    with open(task.save_path, "rb") as f:
        assert f.read() == payload

    assert throttle_calls, "the speed limiter never ran"
    assert not throttle_under_lock, "_throttle() slept while holding the segment lock"
    assert save_calls, "segment state was never persisted"
    assert not save_under_lock, "the state file was written under the segment lock"


def test_segment_range_refusal_falls_back_to_single_stream(
        tmp_path, probe_only_range_server, monkeypatch):
    """A server that honors the probe but not the segments must still work.

    The segment GET comes back 200 instead of 206. That is not a transport
    error, so retrying the segmented path is pointless: the task has to
    restart as a single stream instead of failing with a message that
    promises a restart.
    """
    data, url, download_dir = probe_only_range_server
    cfg = _test_config(tmp_path, segments=4)
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)

    engine = DownloadEngine(config=cfg, db=Database(tmp_path / "db.sqlite"))
    task = engine.add_download(url, save_dir=download_dir)
    engine.start_download(task)

    assert _wait_for_completion(engine, task, timeout=90) == "completed"
    assert task.error_message is None
    with open(task.save_path, "rb") as f:
        assert f.read() == data

    # No zero-filled leftovers from the abandoned segmented attempt.
    assert not os.path.exists(task.save_path + ".part")
    assert not os.path.exists(task.save_path + ".part.segments.json")


def test_cancel_during_segmented_download_stays_cancelled(
        tmp_path, file_server, monkeypatch):
    """Cancel is not pause: the worker must not overwrite the final status.

    After the segment threads join, the stop path used to save the segment
    state and write "paused" — resurrecting the sidecar cancel_download() had
    just deleted and offering a resume that would restart from zero.
    """
    _, url, download_dir = file_server
    cfg = _test_config(tmp_path, segments=4)
    cfg._config_data["speed_limit_kbps"] = 512  # slow enough to cancel mid-flight
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)

    db = Database(tmp_path / "db.sqlite")
    engine = DownloadEngine(config=cfg, db=db)
    task = engine.add_download(url, save_dir=download_dir)
    engine.start_download(task)

    deadline = time.time() + 20
    while time.time() < deadline and task.downloaded_size == 0:
        time.sleep(0.02)
    assert task.downloaded_size > 0, "download never started"

    engine.cancel_download(task)
    engine._threads[task.id].join(timeout=30)

    assert task.status == "cancelled"
    assert db.get_download(task.id)["status"] == "cancelled"
    assert not os.path.exists(task.save_path + ".part")
    assert not os.path.exists(task.save_path + ".part.segments.json")
    assert not os.path.exists(task.save_path)


def test_persisted_segment_progress_never_goes_backwards(
        tmp_path, uneven_range_server, monkeypatch):
    """Progress written to disk must be monotonic, whatever the segment speeds.

    Snapshots are taken under the counter lock but written outside it, so two
    can be in flight at once: a segment that sleeps in _throttle() must not
    write its stale snapshot over a newer one. A regressed .part.segments.json
    or downloads.downloaded_size makes a resume redo work already on disk.
    """
    _, url, download_dir = uneven_range_server
    cfg = _test_config(tmp_path, segments=2)
    cfg._config_data["speed_limit_kbps"] = 32  # 16 KB/s per segment
    monkeypatch.setattr("vf.core.downloader.Config", lambda: cfg)

    writes_lock = threading.Lock()
    state_writes, db_writes = [], []
    real_save = DownloadEngine._save_segment_state
    real_progress = Database.update_progress

    def spying_save(state_path, seg_done):
        with writes_lock:
            state_writes.append(tuple(seg_done))
        return real_save(state_path, seg_done)

    def spying_progress(self, download_id, downloaded_size):
        with writes_lock:
            db_writes.append(downloaded_size)
        return real_progress(self, download_id, downloaded_size)

    monkeypatch.setattr(DownloadEngine, "_save_segment_state", staticmethod(spying_save))
    monkeypatch.setattr(Database, "update_progress", spying_progress)

    engine = DownloadEngine(config=cfg, db=Database(tmp_path / "db.sqlite"))
    task = engine.add_download(url, save_dir=download_dir)
    engine.start_download(task)

    # The cap makes a full download far too slow: a handful of writes is
    # enough to see whether they are ordered.
    deadline = time.time() + 40
    while time.time() < deadline:
        with writes_lock:
            if len(state_writes) >= 8:
                break
        time.sleep(0.05)
    engine.cancel_download(task)
    engine._threads[task.id].join(timeout=30)

    with writes_lock:
        states, progress = list(state_writes), list(db_writes)

    assert len(states) >= 8, f"too few state writes to judge ordering: {states}"

    totals = [sum(s) for s in states]
    assert totals == sorted(totals), f"segment state went backwards: {totals}"
    for i in range(1, len(states)):
        assert all(new >= old for old, new in zip(states[i - 1], states[i])), (
            f"a segment lost bytes between writes: {states[i - 1]} -> {states[i]}"
        )
    assert progress == sorted(progress), f"stored progress went backwards: {progress}"
