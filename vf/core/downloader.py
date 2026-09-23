"""
Core download engine with resume, retry, and concurrent download support.
Handles HTTP range requests for resumable downloads.
"""

import os
import threading
import time
from collections import deque
from urllib.parse import unquote, urlparse

import requests

from ..i18n import t
from .config import Config
from .database import Database


class RangeNotHonored(Exception):
    """A segment request came back without 206 although the probe promised it.

    Internal signal only: _perform_download() catches it and restarts the
    task as a single stream, so it never reaches the user as an error.
    """


class DownloadTask:
    """Represents a single download task with all its state."""

    def __init__(self, db_record):
        self.id = db_record["id"]
        self.url = db_record["url"]
        self.filename = db_record["filename"]
        self.save_path = db_record["save_path"]
        self.total_size = db_record["total_size"] or 0
        self.downloaded_size = db_record["downloaded_size"] or 0
        self.status = db_record["status"]
        self.supports_resume = bool(db_record["supports_resume"])
        self.error_message = db_record.get("error_message")
        self.retry_count = db_record.get("retry_count", 0)
        self.cookies = db_record.get("cookies")
        self.checksum = db_record.get("checksum")
        self.checksum_ok = None  # None=not checked, True/False after verify
        self.use_yt_dlp = bool(db_record.get("use_yt_dlp"))

        # Runtime state (not persisted)
        self._speed_samples = deque(maxlen=20)
        self._last_speed_check = time.time()
        self._last_bytes_at_speed_check = self.downloaded_size
        self.current_speed = 0.0

    @property
    def progress(self):
        """Download progress as percentage (0-100)."""
        if self.total_size > 0:
            return min(100.0, (self.downloaded_size / self.total_size) * 100)
        return 0.0

    @property
    def eta(self):
        """Estimated time remaining in seconds."""
        if self.current_speed > 0 and self.total_size > 0:
            remaining = self.total_size - self.downloaded_size
            return remaining / self.current_speed
        return None

    def update_speed(self):
        """Calculate current download speed using a sliding window."""
        now = time.time()
        elapsed = now - self._last_speed_check

        if elapsed >= 0.5:  # Update speed every 500ms
            bytes_delta = self.downloaded_size - self._last_bytes_at_speed_check
            if elapsed > 0:
                speed = bytes_delta / elapsed
                self._speed_samples.append(speed)
                if self._speed_samples:
                    self.current_speed = sum(self._speed_samples) / len(self._speed_samples)

            self._last_speed_check = now
            self._last_bytes_at_speed_check = self.downloaded_size


class DownloadEngine:
    """
    Manages concurrent downloads with pause/resume/retry support.
    Uses HTTP Range headers for resumable downloads.
    """

    def __init__(self, config=None, db=None, on_update=None):
        self.config = config or Config()
        self.db = db or Database(self.config.db_file)
        self.on_update = on_update  # Callback: (task: DownloadTask) -> None

        self._tasks = {}  # id -> DownloadTask
        self._threads = {}  # id -> threading.Thread
        self._stop_events = {}  # id -> threading.Event
        self._pause_events = {}  # id -> threading.Event
        self._active_count = 0
        self._lock = threading.Lock()
        self._cancelled = set()  # ids cancelled by the user, not paused
        # Concurrency slots: a counter guarded by a condition instead of a
        # semaphore, so max_concurrent is re-read on every admission and a
        # changed limit reaches the downloads already waiting in the queue.
        self._slots_cv = threading.Condition()
        self._active_slots = 0

        self._load_existing_downloads()

    def _load_existing_downloads(self):
        """Load pending/paused downloads from database on startup."""
        for record in self.db.get_active_downloads():
            task = DownloadTask(record)
            self._tasks[task.id] = task

    def add_download(self, url, filename=None, save_dir=None, cookies_raw=None,
                     checksum=None, use_yt_dlp=False):
        """
        Add a new download. Returns the DownloadTask.
        If filename is None, it will be extracted from the URL.
        If save_dir is None, uses the configured default.
        cookies_raw: raw cookie string in "name=value; name2=value2" or "name:value\nname2:value2" format.
        checksum: expected hex digest (SHA-256) verified after completion.
        """
        if save_dir is None:
            save_dir = self.config.download_dir

        if filename is None:
            filename = self._extract_filename(url)

        filename = self._safe_filename(filename, save_dir)
        save_path = os.path.join(save_dir, filename)

        # Parse raw cookies into HTTP Cookie header format
        cookies_header = self._parse_cookies(cookies_raw) if cookies_raw else None

        checksum = (checksum or "").strip().lower() or None
        download_id = self.db.add_download(
            url, filename, save_path, total_size=0,
            cookies=cookies_header, checksum=checksum, use_yt_dlp=use_yt_dlp,
        )
        record = self.db.get_download(download_id)
        task = DownloadTask(record)
        self._tasks[task.id] = task

        self._notify_update(task)
        return task

    @staticmethod
    def _parse_cookies(raw):
        """
        Parse raw cookie text into an HTTP Cookie header string.
        Supports:
          - "name1=value1; name2=value2"  (browser copy-paste format)
          - "name1:value1\nname2:value2"  (colon/newline format)
          - Multi-line with = or : separators
          - Netscape cookie file content (starts with "# Netscape")
          - File path to a Netscape cookie .txt file
        Returns: "name1=value1; name2=value2" (standard Cookie header format)
        """
        import re
        if not raw or not raw.strip():
            return None

        raw = raw.strip()

        # If it's a file path, load it
        if os.path.isfile(raw):
            return DownloadEngine._load_netscape_file(raw)

        # If it looks like Netscape cookie file content
        if raw.startswith("# Netscape") or raw.startswith("# HttpOnly"):
            return DownloadEngine._parse_netscape_content(raw)

        # Raw cookie string format
        pairs = []
        parts = re.split(r'[;\n]+', raw)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Split on first = or :
            match = re.match(r'^([^=:]+)\s*[=:]\s*(.+)$', part)
            if match:
                name = match.group(1).strip()
                value = match.group(2).strip()
                if name and value:
                    pairs.append(f"{name}={value}")

        return "; ".join(pairs) if pairs else None

    @staticmethod
    def _load_netscape_file(filepath):
        """Load cookies from a Netscape HTTP Cookie File (.txt)."""
        try:
            with open(filepath, "r") as f:
                content = f.read()
            return DownloadEngine._parse_netscape_content(content)
        except (IOError, OSError):
            return None

    @staticmethod
    def _parse_netscape_content(content):
        """Parse Netscape HTTP Cookie File format content into Cookie header."""
        pairs = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                # domain, flag, path, secure, expires, name, value
                name = parts[5].strip()
                value = parts[6].strip()
                if name and value:
                    pairs.append(f"{name}={value}")
        return "; ".join(pairs) if pairs else None

    @staticmethod
    def _load_netscape_domains(filepath):
        """Extract domain list from a Netscape cookie file for session injection."""
        domains = set()
        try:
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 1:
                        domain = parts[0].strip()
                        if domain:
                            domains.add(domain)
        except (IOError, OSError):
            pass
        return domains

    def start_download(self, task):
        """Start or resume a download task in a background thread."""
        if task.id in self._threads and self._threads[task.id].is_alive():
            return  # Already running

        with self._lock:
            self._cancelled.discard(task.id)  # a fresh run, not a cancelled one

        stop_event = threading.Event()
        pause_event = threading.Event()
        pause_event.set()  # Not paused initially

        self._stop_events[task.id] = stop_event
        self._pause_events[task.id] = pause_event

        thread = threading.Thread(
            target=self._download_worker,
            args=(task, stop_event, pause_event),
            daemon=True,
            name=f"download-{task.id}-{task.filename}",
        )
        self._threads[task.id] = thread

        self.db.update_status(task.id, "downloading")
        task.status = "downloading"
        self._notify_update(task)

        thread.start()

    def pause_download(self, task):
        """Pause an active download."""
        if task.status not in ("downloading", "retrying", "pending"):
            return  # Not pausable (already paused/finished/cancelled)
        if task.id in self._pause_events:
            self._pause_events[task.id].clear()  # Block the worker
        self.db.update_status(task.id, "paused")
        task.status = "paused"
        self._notify_update(task)

    def resume_download(self, task):
        """Resume a paused or failed download."""
        if task.status == "completed":
            return
        if task.status == "paused":
            if task.id in self._threads and self._threads[task.id].is_alive():
                self._pause_events[task.id].set()  # Unblock the worker
                self.db.update_status(task.id, "downloading")
                task.status = "downloading"
                self._notify_update(task)
            else:
                # Worker thread is gone (e.g. app was restarted) — re-enter it
                self.start_download(task)
        elif task.status in ("failed", "pending", "cancelled"):
            # Start a fresh download with resume support
            self.start_download(task)

    def cancel_download(self, task):
        """Cancel a download and clean up."""
        # Mark it cancelled before stopping the worker: the worker uses this
        # to tell a cancel from a pause and must not write "paused" over the
        # status set here, nor save a resume state for a file it just deleted.
        with self._lock:
            self._cancelled.add(task.id)

        if task.id in self._stop_events:
            self._stop_events[task.id].set()
        if task.id in self._pause_events:
            self._pause_events[task.id].set()  # Unblock so thread can exit

        self.db.update_status(task.id, "cancelled")
        task.status = "cancelled"
        self._notify_update(task)

        # Remove the partial file (the worker repeats this once its segment
        # threads have stopped, so nothing can write it back).
        self._discard_partial(task.save_path)

    def _is_cancelled(self, task):
        """True when the user cancelled this task rather than pausing it."""
        with self._lock:
            return task.id in self._cancelled

    @staticmethod
    def _discard_partial(save_path):
        """Delete the .part file and its segment sidecar, ignoring errors."""
        temp_path = save_path + ".part"
        for path in (temp_path, temp_path + ".segments.json"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def remove_download(self, task):
        """Remove a download from the list (cancel first if needed)."""
        if task.status in ("downloading", "paused"):
            self.cancel_download(task)

        # Wait for thread to finish
        if task.id in self._threads:
            self._threads[task.id].join(timeout=3)

        self.db.remove_download(task.id)
        self._tasks.pop(task.id, None)
        self._threads.pop(task.id, None)
        self._stop_events.pop(task.id, None)
        self._pause_events.pop(task.id, None)
        with self._lock:
            self._cancelled.discard(task.id)

    def retry_download(self, task):
        """Reset and retry a failed download."""
        self.db.reset_for_resume(task.id)
        task.downloaded_size = 0
        task.status = "pending"
        task.error_message = None
        self.resume_download(task)

    def get_all_tasks(self):
        """Get all download tasks."""
        return list(self._tasks.values())

    def get_history(self):
        """All completed download records, newest first."""
        return self.db.get_history()

    def archive_download(self, task):
        """Remove a completed task from the main list, keeping it in history."""
        self._tasks.pop(task.id, None)
        self.db.archive_download(task.id)

    def get_active_tasks(self):
        """Get currently downloading tasks."""
        return [task for task in self._tasks.values() if task.status == "downloading"]

    def get_total_speed(self):
        """Get aggregate speed of all active downloads."""
        return sum(task.current_speed for task in self.get_active_tasks())

    def shutdown(self):
        """Gracefully stop all downloads."""
        for task_id in list(self._stop_events.keys()):
            self._stop_events[task_id].set()
        for task_id in list(self._pause_events.keys()):
            self._pause_events[task_id].set()

        for thread in self._threads.values():
            thread.join(timeout=5)

    # ── Private Methods ─────────────────────────────────────────────

    def _download_worker(self, task, stop_event, pause_event):
        """Worker thread that performs the actual download."""
        # Config is a singleton: this is the one shared instance, not a copy.
        # It is read-only here, so sharing it across worker threads is safe.
        config = Config()

        # Respect max_concurrent: wait for a free slot, staying interruptible.
        # The limit is re-read on every attempt, so a download still sitting in
        # the queue honors a value the user changed in Settings meanwhile.
        self.db.update_status(task.id, "pending", t("queued"))
        task.status = "pending"
        task.error_message = None
        self._notify_update(task)
        while True:
            with self._slots_cv:
                # max(1, ...): a hand-edited config of 0 must not stall the
                # queue forever with nothing to show for it.
                if self._active_slots < max(1, self.config.max_concurrent):
                    self._active_slots += 1
                    break
                self._slots_cv.wait(0.5)
            if stop_event.is_set():
                return

        try:
            # Honor a pause requested while the task was queued
            pause_event.wait()
            if stop_event.is_set():
                return
            self.db.update_status(task.id, "downloading")
            task.status = "downloading"
            task.error_message = None
            self._notify_update(task)
            self._do_download_with_retries(task, stop_event, pause_event, config)
        finally:
            with self._slots_cv:
                self._active_slots -= 1
                self._slots_cv.notify()


    def _throttle(self, last_check, bytes_since, limit_bps):
        """Sleep whenever we are ahead of the byte budget, then reset the window."""
        if not limit_bps or limit_bps <= 0:
            return time.time(), 0
        now = time.time()
        elapsed = max(now - last_check, 0.0)
        allowed = limit_bps * elapsed
        if bytes_since > allowed:
            deficit = (bytes_since - allowed) / limit_bps
            time.sleep(min(deficit, 1.0))
            return time.time(), 0
        return last_check, bytes_since


    def _perform_ytdlp(self, task, stop_event, pause_event):
        """Download via the yt-dlp CLI (video/audio sites).

        Progress is parsed from --newline output; the final path comes from
        --print after_move:filepath. Pause stops the process; yt-dlp resumes
        its own .part files on the next run.
        """
        import re
        import shutil
        import subprocess

        if shutil.which("yt-dlp") is None:
            raise RuntimeError(t("ytdlp_missing"))

        cmd = [
            "yt-dlp", "--newline", "--no-playlist", "--no-mtime",
            "--print", "after_move:filepath",
            "-o", os.path.join(os.path.dirname(task.save_path), "%(title)s.%(ext)s"),
            task.url,
        ]
        if task.cookies:
            cmd[1:1] = ["--add-header", f"Cookie: {task.cookies}"]

        env = dict(os.environ)
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env, cwd=os.path.dirname(task.save_path),
        )

        pct_re = re.compile(
            r"\[download\]\s+([\d.]+)% of\s+~?\s*([\d.\.]+)(KiB|MiB|GiB)"
        )
        mult = {"KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}
        final_path = None
        interrupted = False

        for line in proc.stdout:
            if stop_event.is_set() or not pause_event.is_set():
                interrupted = True
                proc.terminate()
                break
            line = line.strip()
            m = pct_re.search(line)
            if m:
                pct = float(m.group(1))
                total = float(m.group(2)) * mult[m.group(3)]
                if task.total_size == 0 and total > 0:
                    task.total_size = int(total)
                    self.db.update_resume_info(
                        task.id, task.downloaded_size, task.total_size, False
                    )
                task.downloaded_size = int(task.total_size * pct / 100)
                task.update_speed()
                self.db.update_progress(task.id, task.downloaded_size)
                self._notify_update(task)
            elif line and not line.startswith(("[download]", "[info]")) and os.path.isabs(line):
                final_path = line

        proc.wait(timeout=30)

        if interrupted:
            if self._is_cancelled(task):
                return  # cancel_download() already set the final status
            self.db.update_progress(task.id, task.downloaded_size)
            self.db.update_status(task.id, "paused")
            task.status = "paused"
            self._notify_update(task)
            return

        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp exited with code {proc.returncode}")

        if not final_path or not os.path.exists(final_path):
            raise RuntimeError("yt-dlp did not report the final file path")

        # Adopt the real filename produced by yt-dlp
        task.save_path = final_path
        task.filename = os.path.basename(final_path)
        task.total_size = os.path.getsize(final_path)
        task.downloaded_size = task.total_size
        self.db.update_task_file(
            task.id, task.filename, task.save_path, task.total_size
        )
        self._mark_completed(task)

    def _do_download_with_retries(self, task, stop_event, pause_event, config):
        retry_count = 0
        max_retries = config.retry_count

        while retry_count <= max_retries:
            if stop_event.is_set():
                return

            try:
                self._perform_download(task, stop_event, pause_event)
                return  # Success

            except requests.exceptions.HTTPError as e:
                if stop_event.is_set():
                    return

                status_code = e.response.status_code if e.response is not None else 0

                # 403/401/410 = permanent failure, don't retry
                if status_code in (401, 403, 410):
                    error_msg = self._explain_http_error(status_code, task.url)
                    self.db.update_status(task.id, "failed", error_msg)
                    task.status = "failed"
                    task.error_message = error_msg
                    self._notify_update(task)
                    return

                # 429 (rate limit) or 5xx = retryable
                retry_count += 1
                self.db.increment_retry(task.id)
                task.retry_count = retry_count

                if retry_count > max_retries:
                    error_msg = t("retries_exceeded_http", code=status_code, max=max_retries)
                    self.db.update_status(task.id, "failed", error_msg)
                    task.status = "failed"
                    task.error_message = error_msg
                    self._notify_update(task)
                    return

                delay = min(config.retry_delay * (2 ** (retry_count - 1)), 30)
                self._wait_with_retry(task, delay, stop_event, retry_count, max_retries)

            except requests.exceptions.ConnectionError as e:
                if stop_event.is_set():
                    return

                retry_count += 1
                self.db.increment_retry(task.id)
                task.retry_count = retry_count

                if retry_count > max_retries:
                    error_msg = t("retries_exceeded_conn", max=max_retries, err=str(e))
                    self.db.update_status(task.id, "failed", error_msg)
                    task.status = "failed"
                    task.error_message = error_msg
                    self._notify_update(task)
                    return

                delay = min(config.retry_delay * (2 ** (retry_count - 1)), 30)
                self._wait_with_retry(task, delay, stop_event, retry_count, max_retries)

            except requests.exceptions.RequestException as e:
                if stop_event.is_set():
                    return

                retry_count += 1
                self.db.increment_retry(task.id)
                task.retry_count = retry_count

                if retry_count > max_retries:
                    error_msg = t("retries_exceeded_generic", max=max_retries, err=str(e))
                    self.db.update_status(task.id, "failed", error_msg)
                    task.status = "failed"
                    task.error_message = error_msg
                    self._notify_update(task)
                    return

                delay = min(config.retry_delay * (2 ** (retry_count - 1)), 30)
                self._wait_with_retry(task, delay, stop_event, retry_count, max_retries)

            except Exception as e:
                if stop_event.is_set():
                    return
                error_msg = t("unexpected_error", err=str(e))
                self.db.update_status(task.id, "failed", error_msg)
                task.status = "failed"
                task.error_message = error_msg
                self._notify_update(task)
                return

    def _wait_with_retry(self, task, delay, stop_event, retry_count, max_retries):
        """Wait with exponential backoff between retries."""
        self.db.update_status(
            task.id, "retrying", t("retrying", cur=retry_count, max=max_retries, delay=delay)
        )
        task.status = "retrying"
        task.error_message = t("retrying_short", cur=retry_count, max=max_retries)
        self._notify_update(task)

        for _ in range(int(delay * 10)):
            if stop_event.is_set():
                return
            time.sleep(0.1)

    @staticmethod
    def _explain_http_error(status_code, url):
        """Generate a user-friendly explanation for HTTP errors."""
        explanations = {
            401: t("http_401"),
            403: t("http_403"),
            404: t("http_404"),
            410: t("http_410"),
            429: t("http_429"),
            500: t("http_500"),
            502: t("http_502"),
            503: t("http_503"),
        }
        return explanations.get(
            status_code, t("http_generic", code=status_code)
        )

    def _perform_download(self, task, stop_event, pause_event):
        """Execute the HTTP download, dispatching to segmented mode when possible."""
        config = Config()
        session = self._build_session(task, config)

        # HEAD request to get file info (non-critical — skip if it fails)
        head_ok = False
        try:
            head_resp = session.head(
                task.url, timeout=config.timeout, allow_redirects=True
            )
            head_resp.raise_for_status()
            head_ok = True

            content_length = int(head_resp.headers.get("Content-Length", 0))
            accept_ranges = head_resp.headers.get("Accept-Ranges", "none")

            if content_length > 0 and task.total_size == 0:
                task.total_size = content_length
                self.db.update_resume_info(
                    task.id, task.downloaded_size, content_length,
                    accept_ranges == "bytes"
                )

            task.supports_resume = accept_ranges == "bytes"

        except requests.exceptions.RequestException:
            # HEAD failed (403, timeout, etc.) — continue with GET anyway
            pass

        if task.use_yt_dlp:
            return self._perform_ytdlp(task, stop_event, pause_event)

        use_segments = (
            config.segmented
            and head_ok
            and task.supports_resume
            and task.total_size >= config.segmented_min_size
        )
        if use_segments:
            # Verify the server actually honors Range with a 1-byte probe
            try:
                probe = session.get(
                    task.url,
                    headers={"Range": "bytes=0-0"},
                    stream=True,
                    timeout=(config.timeout, None),
                    allow_redirects=True,
                )
                honors_range = probe.status_code == 206
                probe.close()
            except requests.exceptions.RequestException:
                honors_range = False

            if honors_range:
                try:
                    return self._perform_segmented(task, stop_event, pause_event, config)
                except RangeNotHonored:
                    # The probe was answered with 206 but a real segment was
                    # not: throw the preallocated .part away and download the
                    # file in one stream instead of failing the task.
                    self._discard_partial(task.save_path)
                    task.supports_resume = False
                    task.downloaded_size = 0
                    self.db.update_resume_info(task.id, 0, task.total_size, False)

        return self._perform_single_stream(task, session, stop_event, pause_event, config)

    def _build_session(self, task, config):
        """Create a requests session with browser-like headers and task cookies."""
        session = requests.Session()

        # Browser-like headers to avoid bot detection
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
                "Gecko/20100101 Firefox/128.0"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "identity",  # No compression for downloads
            "DNT": "1",
            "Connection": "keep-alive",
        })

        # Inject user-provided cookies
        if task.cookies:
            session.headers["Cookie"] = task.cookies
            # Also set cookies on the session's cookie jar for ALL domains
            # This ensures cookies survive cross-domain redirects (e.g. archive.org → ia600106.us.archive.org)
            try:
                from urllib.parse import urlparse
                parsed = urlparse(task.url)
                base_domain = parsed.hostname
                if base_domain:
                    # Set on the original domain
                    for part in task.cookies.split(";"):
                        part = part.strip()
                        if "=" in part:
                            k, v = part.split("=", 1)
                            session.cookies.set(k.strip(), v.strip(), domain=base_domain)
                    # Set on parent domain (e.g. .archive.org)
                    parts = base_domain.split(".")
                    if len(parts) >= 2:
                        parent_domain = "." + ".".join(parts[-2:])
                        for part in task.cookies.split(";"):
                            part = part.strip()
                            if "=" in part:
                                k, v = part.split("=", 1)
                                session.cookies.set(k.strip(), v.strip(), domain=parent_domain)
                    # Also set without domain (matches any host)
                    for part in task.cookies.split(";"):
                        part = part.strip()
                        if "=" in part:
                            k, v = part.split("=", 1)
                            session.cookies.set(k.strip(), v.strip())
            except Exception:
                pass  # Fallback: Cookie header is already set

        return session

    def _perform_single_stream(self, task, session, stop_event, pause_event, config):
        """Execute a single-stream HTTP download with resume support."""
        resume_from = 0

        # Check for existing partial file
        temp_path = task.save_path + ".part"
        if os.path.exists(temp_path):
            resume_from = os.path.getsize(temp_path)

        # Set up Range header for resume
        if resume_from > 0:
            headers = {"Range": f"bytes={resume_from}-"}
            task.downloaded_size = resume_from
        else:
            headers = {}

        # Open file and start streaming GET
        mode = "ab" if resume_from > 0 else "wb"

        response = session.get(
            task.url,
            headers=headers,
            stream=True,
            timeout=(config.timeout, None),  # No read timeout for streaming
            allow_redirects=True,
        )

        # If Range request returned 416 (Range Not Satisfiable), restart
        if response.status_code == 416:
            resume_from = 0
            task.downloaded_size = 0
            mode = "wb"
            response = session.get(
                task.url,
                stream=True,
                timeout=(config.timeout, None),
                allow_redirects=True,
            )

        response.raise_for_status()

        # If we sent Range but server didn't honor it, restart from 0
        if resume_from > 0 and response.status_code == 200:
            task.downloaded_size = 0
            mode = "wb"

        # Update total size from GET response if not set
        if task.total_size == 0:
            content_length = int(response.headers.get("Content-Length", 0))
            if content_length > 0:
                task.total_size = content_length
                self.db.update_resume_info(
                    task.id, task.downloaded_size, content_length,
                    response.headers.get("Accept-Ranges", "none") == "bytes"
                )

        chunk_size = config.chunk_size
        last_db_update = time.time()
        speed_limit = config.speed_limit_bytes
        throttle_t, throttle_bytes = time.time(), 0

        with open(temp_path, mode) as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if stop_event.is_set():
                    response.close()
                    if self._is_cancelled(task):
                        # Cancelled, not paused: keep the status cancel_download()
                        # wrote and leave no resume state behind.
                        self._discard_partial(task.save_path)
                        return
                    # Save state and exit cleanly
                    self.db.update_progress(task.id, task.downloaded_size)
                    self.db.update_status(task.id, "paused")
                    task.status = "paused"
                    self._notify_update(task)
                    return

                # Wait if paused
                pause_event.wait()

                if chunk:
                    f.write(chunk)
                    task.downloaded_size += len(chunk)
                    task.update_speed()
                    throttle_t, throttle_bytes = self._throttle(
                        throttle_t, throttle_bytes + len(chunk), speed_limit
                    )

                    # Update UI periodically (not every chunk)
                    now = time.time()
                    if now - last_db_update >= 0.3:
                        self.db.update_progress(task.id, task.downloaded_size)
                        self._notify_update(task)
                        last_db_update = now

        self._finalize_download(task, temp_path, config)

    def _perform_segmented(self, task, stop_event, pause_event, config):
        """Download a file in parallel byte-range segments into a preallocated .part file."""

        total = task.total_size
        n_segments = min(config.download_segments, max(1, total // (1024 * 1024)))
        part_path = task.save_path + ".part"
        state_path = part_path + ".segments.json"

        # Split the file into contiguous byte ranges
        seg_size = total // n_segments
        bounds = []
        for i in range(n_segments):
            start = i * seg_size
            end = total - 1 if i == n_segments - 1 else (start + seg_size - 1)
            bounds.append((start, end))

        # Preallocate the .part file; reset everything if its size doesn't match
        if not os.path.exists(part_path) or os.path.getsize(part_path) != total:
            with open(part_path, "wb") as f:
                f.truncate(total)
            seg_done = [0] * n_segments
        else:
            seg_done = self._load_segment_state(state_path, n_segments)

        task.downloaded_size = sum(seg_done)
        self.db.update_progress(task.id, task.downloaded_size)

        lock = threading.Lock()       # guards the shared counters only
        save_lock = threading.Lock()  # serialises state-file / database writes
        completed = [False] * n_segments
        errors = []
        threads = []
        last_save = time.time()
        taken_seq = 0    # snapshots handed out, counted under `lock`
        saved_seq = 0    # newest snapshot on disk, counted under `save_lock`

        def save_state(snapshot=None, progress=None, seq=None):
            """Persist segment progress. Must never be called holding `lock`.

            Callers may hand over a snapshot already taken under `lock`;
            otherwise one is taken here. The JSON and database writes then run
            outside `lock`, so a slow write never stalls the other segments.
            `save_lock` keeps two concurrent writers from tearing the file, and
            the sequence number keeps persisted progress monotonic: snapshots
            do not necessarily reach us in the order they were taken.
            """
            nonlocal taken_seq, saved_seq
            if snapshot is None:
                with lock:
                    taken_seq += 1
                    seq = taken_seq
                    snapshot = list(seg_done)
                    progress = task.downloaded_size
            with save_lock:
                if seq < saved_seq:
                    return  # a newer snapshot already went to disk
                saved_seq = seq
                self._save_segment_state(state_path, snapshot)
                self.db.update_progress(task.id, progress)

        def seg_worker(i):
            nonlocal last_save, taken_seq
            start, end = bounds[i]
            pos = start + seg_done[i]
            if pos > end:
                completed[i] = True
                return
            try:
                # Each segment gets its own session (requests.Session is not thread-safe)
                session = self._build_session(task, config)
                headers = {"Range": f"bytes={pos}-{end}"}
                response = session.get(
                    task.url,
                    headers=headers,
                    stream=True,
                    timeout=(config.timeout, None),
                    allow_redirects=True,
                )
                response.raise_for_status()
                if response.status_code != 206:
                    # Not a transport error: _perform_download() turns this
                    # into a single-stream restart of the whole file.
                    response.close()
                    raise RangeNotHonored(t("range_not_supported"))

                speed_limit = config.speed_limit_bytes
                seg_limit = speed_limit // n_segments if speed_limit else 0
                throttle_t, throttle_bytes = time.time(), 0
                with open(part_path, "r+b") as f:
                    f.seek(pos)
                    for chunk in response.iter_content(chunk_size=config.chunk_size):
                        if stop_event.is_set():
                            return
                        pause_event.wait()
                        if not chunk:
                            continue
                        f.write(chunk)

                        # Only the cheap shared-counter mutation runs under the
                        # lock — no sleeping, no disk and no database work.
                        now = time.time()
                        snapshot = None
                        progress = 0
                        seq = 0
                        with lock:
                            seg_done[i] += len(chunk)
                            task.downloaded_size += len(chunk)
                            task.update_speed()
                            if now - last_save >= 0.3:
                                last_save = now
                                taken_seq += 1
                                seq = taken_seq
                                snapshot = list(seg_done)
                                progress = task.downloaded_size

                        # Persist first, then sleep: both run outside the lock,
                        # so one segment's throttle sleep or its disk/database
                        # write never blocks the others' progress accounting.
                        if snapshot is not None:
                            save_state(snapshot, progress, seq)
                            self._notify_update(task)
                        throttle_t, throttle_bytes = self._throttle(
                            throttle_t, throttle_bytes + len(chunk), seg_limit
                        )
                completed[i] = True
            except Exception as e:
                with lock:
                    errors.append(e)

        # NOTE: do not name these `t` — that would shadow the imported i18n
        # helper and turn it into a closure cell of seg_worker(), so every
        # t("...") call inside the worker would blow up on a Thread object.
        for i in range(n_segments):
            th = threading.Thread(
                target=seg_worker, args=(i,), daemon=True,
                name=f"download-{task.id}-seg{i}",
            )
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        if stop_event.is_set():
            if self._is_cancelled(task):
                # cancel_download() already wrote the status and removed the
                # partial file; repeat the cleanup now that the segments have
                # stopped, so a late write cannot resurrect either of them.
                self._discard_partial(task.save_path)
                return
            save_state()
            self.db.update_status(task.id, "paused")
            task.status = "paused"
            self._notify_update(task)
            return

        if errors:
            # A Range refusal wins over transport errors: it has a fallback.
            raise next(
                (e for e in errors if isinstance(e, RangeNotHonored)), errors[0]
            )

        if all(completed):
            try:
                os.remove(state_path)
            except OSError:
                pass
            self._finalize_download(task, part_path, config)

    @staticmethod
    def _load_segment_state(state_path, n_segments):
        """Load per-segment progress from the sidecar state file."""
        import json
        try:
            with open(state_path, "r") as f:
                data = json.load(f)
            seg_done = [int(x) for x in data.get("segments", [])]
            if len(seg_done) == n_segments:
                return seg_done
        except (IOError, OSError, ValueError):
            pass
        return [0] * n_segments

    @staticmethod
    def _save_segment_state(state_path, seg_done):
        """Persist per-segment progress for resume."""
        import json
        try:
            with open(state_path, "w") as f:
                json.dump({"segments": seg_done}, f)
        except (IOError, OSError):
            pass

    def _finalize_download(self, task, temp_path, config):
        """Move the completed .part file into place and mark the task completed."""
        final_path = task.save_path

        # Handle duplicate filenames
        if os.path.exists(final_path) and not config.overwrite_existing:
            final_path = self._unique_path(final_path)

        # Rename temp file to final name
        os.rename(temp_path, final_path)
        task.save_path = final_path
        task.downloaded_size = task.total_size

        self._verify_checksum(task)

        self._mark_completed(task)

    def _mark_completed(self, task):
        """Shared completion path: status, checksum verdict, notification."""
        self.db.update_status(task.id, "completed")
        self.db.update_progress(task.id, task.downloaded_size)
        task.status = "completed"
        self._notify_update(task)

        from ..utils.helpers import send_notification
        title = t("notify_complete_title")
        if task.checksum_ok is False:
            send_notification(title + " — " + t("checksum_bad"), task.filename)
        else:
            send_notification(title, task.filename)

    @staticmethod
    def _verify_checksum(task):
        """Check the downloaded file against the expected SHA-256, if any."""
        if not task.checksum:
            task.checksum_ok = None
            return
        import hashlib
        expected = task.checksum.strip().lower()
        sha = hashlib.sha256()
        try:
            with open(task.save_path, "rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    sha.update(block)
        except OSError:
            task.checksum_ok = False
            return
        task.checksum_ok = sha.hexdigest() == expected

    def apply_concurrency_limit(self):
        """Wake the queued workers after a settings change.

        The limit itself lives in the config and is re-read every time a
        worker asks for a slot, so queued downloads follow the new value at
        once. Running downloads keep their slot until they finish: a raised
        limit takes effect immediately, a lowered one as they drain.
        """
        with self._slots_cv:
            self._slots_cv.notify_all()

    def _notify_update(self, task):
        """Notify the GUI about a task update."""
        if self.on_update:
            try:
                self.on_update(task)
            except Exception:
                pass  # Don't crash if GUI callback fails

    def _extract_filename(self, url):
        """Extract filename from URL."""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path)
        if not filename or "." not in filename:
            filename = "download_" + str(int(time.time()))
        return filename

    def _safe_filename(self, filename, directory):
        """
        Ensure filename is safe and unique within the directory.

        On a collision the behaviour depends on the "auto_rename" setting:
        when it is on (the default) a "_1", "_2", … suffix is appended, and
        when it is off the download is refused with a FileExistsError.
        """
        # Remove problematic characters
        safe = "".join(c for c in filename if c.isalnum() or c in "._- ")
        if not safe:
            safe = "download"

        # Ensure uniqueness
        full_path = os.path.join(directory, safe)
        if os.path.exists(full_path + ".part") or os.path.exists(full_path):
            if not self.config.auto_rename:
                raise FileExistsError(t("error_file_exists", name=safe))
            name, ext = os.path.splitext(safe)
            counter = 1
            while os.path.exists(os.path.join(directory, f"{name}_{counter}{ext}")) or \
                  os.path.exists(os.path.join(directory, f"{name}_{counter}{ext}.part")):
                counter += 1
            safe = f"{name}_{counter}{ext}"

        return safe

    def _unique_path(self, path):
        """Generate a unique file path if the original exists."""
        if not os.path.exists(path):
            return path

        base, ext = os.path.splitext(path)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        return f"{base}_{counter}{ext}"
