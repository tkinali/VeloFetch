"""Tests for the local HTTP server's hardening: token, Host and CORS rules.

Everything runs against a throwaway HOME, so the real ~/.config/velofetch is
never read or written.
"""

import http.client
import json
import os
import secrets
import stat
import sys
import threading
import types

import pytest

from vf.core.server import VeloFetchHandler, VeloFetchServer

TOKEN = "secret123"
ORIGIN = "chrome-extension://abcdefghijklmnop"


class _FakeEngine:
    """Minimal engine double for the server."""

    def __init__(self, config):
        self.config = config
        self.added = []

    def add_download(self, url, filename=None, cookies_raw=None, use_yt_dlp=False):
        task = types.SimpleNamespace(id=1, filename=filename or "f.bin")
        self.added.append(url)
        return task

    def start_download(self, task):
        pass

    def get_all_tasks(self):
        return []


# -- Fixtures --


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """A Config rooted in a temporary HOME instead of ~/.config/velofetch."""
    from vf.core.config import Config

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    Config._instance = None
    config = Config()
    # Guard: a mistake here would litter the developer's real config dir.
    assert str(config.config_dir).startswith(str(tmp_path))
    yield config
    Config._instance = None


@pytest.fixture
def server(temp_config):
    """A running server on an ephemeral port with a known token."""
    temp_config.set("api_token", TOKEN)
    engine = _FakeEngine(temp_config)
    shown = []
    instance = VeloFetchServer(engine, port=0, on_show=lambda: shown.append(True))
    assert instance.start()
    context = types.SimpleNamespace(
        port=instance._server.server_address[1],
        engine=engine,
        shown=shown,
        config=temp_config,
    )
    yield context
    instance.stop()
    instance._server.server_close()
    VeloFetchHandler.on_show = None


# -- Helpers --


def _call(port, method, path, body=None, headers=None, host=None):
    """Return (status, headers, body) for one request to the local server."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        sent = dict(headers or {})
        if host is not None:
            sent["Host"] = host
        conn.request(method, path, body=body, headers=sent)
        response = conn.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        conn.close()


def _post_add(port, payload, token=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-VeloFetch-Token"] = token
    if origin is not None:
        headers["Origin"] = origin
    return _call(port, "POST", "/add", json.dumps(payload).encode(), headers)


# -- Token --


def test_add_requires_valid_token(server):
    assert _post_add(server.port, {"url": "https://x.com/a"})[0] == 403
    assert _post_add(server.port, {"url": "https://x.com/a"}, token="wrong")[0] == 403
    assert server.engine.added == []
    assert _post_add(server.port, {"url": "https://x.com/a"}, token=TOKEN)[0] == 200
    assert server.engine.added == ["https://x.com/a"]


def test_rejected_request_gets_no_cors_header(server):
    for token in (None, "wrong"):
        status, headers, _ = _post_add(
            server.port, {"url": "https://x.com/a"}, token=token, origin=ORIGIN
        )
        assert status == 403
        assert "Access-Control-Allow-Origin" not in headers


def test_authenticated_response_echoes_origin(server):
    status, headers, _ = _post_add(
        server.port, {"url": "https://x.com/a"}, token=TOKEN, origin=ORIGIN
    )
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
    assert headers.get("Vary") == "Origin"


def test_list_requires_token(server):
    assert _call(server.port, "GET", "/list")[0] == 403
    status, _, payload = _call(
        server.port, "GET", "/list", headers={"X-VeloFetch-Token": TOKEN}
    )
    assert status == 200
    assert json.loads(payload) == {"tasks": []}


def test_show_requires_token(server):
    status, headers, _ = _call(server.port, "GET", "/show", headers={"Origin": ORIGIN})
    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers
    assert server.shown == []

    status, _, _ = _call(
        server.port, "GET", "/show", headers={"X-VeloFetch-Token": TOKEN}
    )
    assert status == 200
    assert server.shown == [True]


def test_empty_configured_token_denies_everything(server):
    """An empty api_token must mean "closed", never "open to everyone".

    load() makes sure the token is never empty, but a hand-edited config, a
    half-written one or a future regression can still get here, and the answer
    has to be 403 rather than free access to the whole API.
    """
    server.config.set("api_token", "")
    requests = [
        ("POST", "/add", json.dumps({"url": "https://x.com/a"}).encode()),
        ("GET", "/add?url=https%3A%2F%2Fx.com%2Ffile", None),
        ("GET", "/list", None),
        ("GET", "/show", None),
        ("GET", "/integration", None),
    ]
    for method, path, body in requests:
        for headers in ({}, {"X-VeloFetch-Token": ""}, {"X-VeloFetch-Token": TOKEN}):
            sent = dict(headers)
            if body is not None:
                sent["Content-Type"] = "application/json"
            status, _, payload = _call(server.port, method, path, body, sent)
            assert status == 403, f"{method} {path} with {headers} returned {status}"
            assert b"javascript:" not in payload
    assert server.engine.added == []
    assert server.shown == []


def test_ping_stays_open(server):
    """/ping is unauthenticated on purpose (single-instance guard)."""
    status, _, payload = _call(server.port, "GET", "/ping")
    assert status == 200
    assert json.loads(payload)["app"] == "VeloFetch"


# -- Host header --


def test_foreign_host_is_rejected(server):
    status, _, _ = _call(
        server.port,
        "POST",
        "/add",
        json.dumps({"url": "https://x.com/a"}).encode(),
        {"Content-Type": "application/json", "X-VeloFetch-Token": TOKEN},
        host="attacker.example.com",
    )
    assert status == 403
    assert server.engine.added == []


def test_foreign_host_is_rejected_before_ping(server):
    assert _call(server.port, "GET", "/ping", host="attacker.example.com")[0] == 403


def test_loopback_host_names_are_accepted(server):
    for host in (f"localhost:{server.port}", f"127.0.0.1:{server.port}"):
        assert _call(server.port, "GET", "/ping", host=host)[0] == 200


# -- URL validation --


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "javascript:alert(1)", "ftp://x.com/f", "/etc/passwd"]
)
def test_post_add_rejects_non_http_url(server, url):
    assert _post_add(server.port, {"url": url}, token=TOKEN)[0] == 400
    assert server.engine.added == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)"])
def test_beacon_add_rejects_non_http_url(server, url):
    from urllib.parse import quote

    path = f"/add?token={TOKEN}&url={quote(url, safe='')}"
    assert _call(server.port, "GET", path)[0] == 400
    assert server.engine.added == []


def test_get_add_beacon(server):
    """GET /add (image-beacon fallback) adds a download with a valid token."""
    path = f"/add?token={TOKEN}&url=https%3A%2F%2Fx.com%2Ffile"
    status, headers, payload = _call(server.port, "GET", path)
    assert status == 200
    assert headers["Content-Type"] == "image/gif"
    assert payload.startswith(b"GIF89a")
    assert server.engine.added == ["https://x.com/file"]


def test_get_add_beacon_rejects_bad_token(server):
    path = "/add?token=wrong&url=https%3A%2F%2Fx.com%2Ffile"
    assert _call(server.port, "GET", path)[0] == 403
    assert server.engine.added == []


# -- Body size --


def test_oversized_body_is_rejected(server):
    body = json.dumps({"url": "https://x.com/a", "cookies": "x" * (1024 * 1024)})
    status, _, _ = _call(
        server.port,
        "POST",
        "/add",
        body.encode(),
        {"Content-Type": "application/json", "X-VeloFetch-Token": TOKEN},
    )
    assert status == 413
    assert server.engine.added == []


# -- CORS preflight --


def test_preflight_advertises_token_header(server):
    status, headers, _ = _call(
        server.port, "OPTIONS", "/add", headers={"Origin": ORIGIN}
    )
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
    assert headers.get("Vary") == "Origin"
    assert "X-VeloFetch-Token" in headers["Access-Control-Allow-Headers"]


def test_no_endpoint_uses_wildcard_cors(server):
    """Every route, authenticated and not — including the ones that answer
    with something other than JSON (the GET /add beacon's gif, the
    /integration page), which is where the wildcard used to live."""
    body = json.dumps({"url": "https://x.com/a"}).encode()
    beacon = "/add?url=https%3A%2F%2Fx.com%2Ffile"
    authed = {"Origin": ORIGIN, "X-VeloFetch-Token": TOKEN}
    anon = {"Origin": ORIGIN}
    checks = [
        _call(server.port, "GET", "/ping", headers=anon),
        _call(server.port, "OPTIONS", "/add", headers=anon),
        _call(server.port, "GET", "/list", headers=anon),
        _call(server.port, "GET", "/list", headers=authed),
        _call(server.port, "GET", "/show", headers=anon),
        _call(server.port, "GET", "/show", headers=authed),
        _call(server.port, "GET", "/integration", headers=anon),
        _call(server.port, "GET", "/integration", headers=authed),
        _call(server.port, "GET", beacon, headers=anon),
        _call(server.port, "GET", f"{beacon}&token={TOKEN}", headers=anon),
        _call(server.port, "POST", "/add", body, {**anon, "Content-Type": "application/json"}),
        _call(server.port, "POST", "/add", body, {**authed, "Content-Type": "application/json"}),
        _call(server.port, "GET", "/nope", headers=anon),
    ]
    for status, headers, _payload in checks:
        assert status in (200, 403, 404)
        assert headers.get("Access-Control-Allow-Origin") != "*"


# -- Integration page --


def test_integration_page_contains_bookmarklet(server):
    status, _, payload = _call(
        server.port, "GET", "/integration", headers={"X-VeloFetch-Token": TOKEN}
    )
    assert status == 200
    body = payload.decode("utf-8")
    assert "javascript:" in body
    assert "127.0.0.1:9876" in body
    assert "fetch" in body


def test_integration_requires_token(server):
    """The page hands out the token, so it may not be served unauthenticated.

    Any local process that can reach the loopback used to be able to read the
    token here and then drive the whole "protected" API with it.
    """
    for path, headers in (
        ("/integration", {}),
        ("/integration", {"Origin": "https://evil.example"}),
        ("/integration", {"X-VeloFetch-Token": "wrong"}),
        ("/integration?token=wrong", {}),
    ):
        status, response_headers, payload = _call(server.port, "GET", path, headers=headers)
        assert status == 403
        assert TOKEN.encode() not in payload
        assert b"javascript:" not in payload
        assert "Access-Control-Allow-Origin" not in response_headers

    # The query-parameter form is what makes the page openable in a browser
    # (`vf integration` prints exactly this URL).
    status, _, payload = _call(server.port, "GET", f"/integration?token={TOKEN}")
    assert status == 200
    assert TOKEN.encode() in payload


def test_integration_page_escapes_token_for_javascript(server):
    """A quote in the token must not break out of the bookmarklet string."""
    server.config.set("api_token", 'tok"en')
    _, _, payload = _call(
        server.port, "GET", "/integration", headers={"X-VeloFetch-Token": 'tok"en'}
    )
    body = payload.decode("utf-8")
    # json.dumps escaped the quote, html.escape then encoded both quotes.
    assert "T=&quot;tok\\&quot;en&quot;," in body


# -- Config token lifecycle --


def test_config_generates_token_when_missing(tmp_path, monkeypatch):
    from vf.core.config import Config

    monkeypatch.setenv("HOME", str(tmp_path))
    config_dir = tmp_path / ".config" / "velofetch"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"max_concurrent": 7}))

    Config._instance = None
    try:
        config = Config()
        token = config.get("api_token")
        assert token
        assert config.api_token == token
        # Persisted, so the next start reuses the same token.
        assert json.loads(config_file.read_text())["api_token"] == token
        assert config.get("max_concurrent") == 7

        fresh = config.regenerate_api_token()
        assert fresh and fresh != token
        assert config.get("api_token") == fresh
        assert json.loads(config_file.read_text())["api_token"] == fresh
    finally:
        Config._instance = None


def test_config_keeps_existing_token(tmp_path, monkeypatch):
    from vf.core.config import Config

    monkeypatch.setenv("HOME", str(tmp_path))
    config_dir = tmp_path / ".config" / "velofetch"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"api_token": "keepme"}))

    Config._instance = None
    try:
        assert Config().get("api_token") == "keepme"
    finally:
        Config._instance = None


# -- Config file safety --


def _prepare_config(tmp_path, monkeypatch, content, mode=0o644, dir_mode=0o755):
    """Lay out a HOME with a config.json of the given content and modes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    config_dir = tmp_path / ".config" / "velofetch"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    if content is not None:
        config_file.write_text(content)
        config_file.chmod(mode)
    config_dir.chmod(dir_mode)
    return config_dir, config_file


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_config_tightens_world_readable_file_on_load(tmp_path, monkeypatch):
    """An install that already had a token must be hardened too.

    chmod 0600 used to run only from save(), and save() only ran when the
    token was missing — so every existing install kept its world-readable
    token forever, which is exactly the case the hardening is for.
    """
    from vf.core.config import Config

    config_dir, config_file = _prepare_config(
        tmp_path, monkeypatch, json.dumps({"api_token": "keepme", "language": "tr"})
    )
    assert _mode(config_file) == 0o644  # precondition

    Config._instance = None
    try:
        config = Config()
        assert config.get("api_token") == "keepme"
        assert config.get("language") == "tr"
    finally:
        Config._instance = None

    assert _mode(config_file) == 0o600
    assert _mode(config_dir) == 0o700


def test_config_created_on_first_run_is_private(tmp_path, monkeypatch):
    from vf.core.config import Config

    monkeypatch.setenv("HOME", str(tmp_path))
    Config._instance = None
    try:
        assert Config().get("api_token")
    finally:
        Config._instance = None

    config_dir = tmp_path / ".config" / "velofetch"
    assert _mode(config_dir / "config.json") == 0o600
    assert _mode(config_dir) == 0o700


def test_first_run_adopts_a_config_another_process_just_wrote(tmp_path, monkeypatch):
    """Two first runs have to settle on one token.

    The loser must adopt what is on disk: if it overwrote the file with its
    own token instead, the process that got there first would keep serving a
    token no client can read out of config.json any more.
    """
    from vf.core.config import Config

    monkeypatch.setenv("HOME", str(tmp_path))
    config_file = tmp_path / ".config" / "velofetch" / "config.json"
    winner = json.dumps({"api_token": "winner", "language": "tr"})
    real_token_urlsafe = secrets.token_urlsafe

    def _minting(nbytes=None):
        # Stand-in for the other process: it creates config.json while this
        # one is minting, i.e. after load() looked and found nothing. Asking
        # "does it exist?" at any later point is exactly the losing move.
        if not config_file.exists():
            config_file.write_text(winner)
        return real_token_urlsafe(nbytes)

    monkeypatch.setattr("vf.core.config.secrets.token_urlsafe", _minting)

    Config._instance = None
    try:
        config = Config()
        assert config.get("api_token") == "winner"
        assert config.get("language") == "tr"
    finally:
        Config._instance = None

    assert json.loads(config_file.read_text()) == json.loads(winner)


def test_load_never_overwrites_an_unreadable_config(tmp_path, monkeypatch):
    """A config caught mid-write must survive untouched.

    save() used to truncate in place, so a second process reading inside that
    window got a JSONDecodeError, fell back to defaults, minted a token and
    wrote the defaults back — destroying every setting the file held.
    """
    from vf.core.config import Config

    partial = '{\n  "api_to'  # exactly what a truncated save leaves behind
    _, config_file = _prepare_config(tmp_path, monkeypatch, partial)

    Config._instance = None
    try:
        config = Config()
        # Fails closed: no token in memory, so the server denies every request
        # instead of running under a token the file does not know about.
        assert config.get("api_token") == ""
        assert config.get("download_dir")  # defaults are still usable
    finally:
        Config._instance = None

    assert config_file.read_text() == partial


def test_save_leaves_the_previous_file_intact_when_it_fails(tmp_path, monkeypatch):
    """A failed save must not leave a truncated config or a stray temp file."""
    from vf.core.config import Config

    original = json.dumps({"api_token": "keepme", "language": "tr"})
    config_dir, config_file = _prepare_config(tmp_path, monkeypatch, original)

    Config._instance = None
    try:
        config = Config()

        def _boom(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", _boom)
        config.set("language", "en")
    finally:
        Config._instance = None

    assert json.loads(config_file.read_text()) == json.loads(original)
    assert sorted(p.name for p in config_dir.iterdir()) == ["config.json"]


def test_save_is_atomic_for_a_concurrent_reader(tmp_path, monkeypatch):
    """Every read taken while save() runs sees a complete config file."""
    from vf.core.config import Config

    monkeypatch.setenv("HOME", str(tmp_path))
    Config._instance = None
    try:
        config = Config()
        config.set("download_dir", str(tmp_path / "Downloads"))
        config_file = tmp_path / ".config" / "velofetch" / "config.json"

        bad = []
        stop = threading.Event()

        def _read():
            while not stop.is_set():
                try:
                    json.loads(config_file.read_text())
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    bad.append(repr(e))

        reader = threading.Thread(target=_read)
        reader.start()
        try:
            for i in range(100):
                config.set("speed_limit_kbps", i)
        finally:
            stop.set()
            reader.join(timeout=5)

        assert bad == []
        assert json.loads(config_file.read_text())["speed_limit_kbps"] == 99
    finally:
        Config._instance = None


# -- CLI single-instance guard --


def test_guard_brings_the_window_to_the_front(server, monkeypatch, capsys):
    """`vf` with a running instance must actually reach the token-protected
    /show, not just print that it did."""
    import vf.__main__ as cli
    from vf.i18n import t

    monkeypatch.setattr(cli, "SERVER", f"http://127.0.0.1:{server.port}")
    monkeypatch.setattr("vf.core.server.is_running", lambda *a, **kw: True)
    monkeypatch.setattr(sys, "argv", ["vf"])

    cli.main()

    assert server.shown == [True]
    assert t("cli_already_running") in capsys.readouterr().out


def test_guard_reports_a_failed_show(server, monkeypatch, capsys):
    """When /show is rejected, say so instead of claiming a window came up."""
    import vf.__main__ as cli
    from vf.i18n import t

    monkeypatch.setattr(cli, "SERVER", f"http://127.0.0.1:{server.port}")
    monkeypatch.setattr("vf.core.server.is_running", lambda *a, **kw: True)
    monkeypatch.setattr(cli, "_api_token", lambda: "stale-token")
    monkeypatch.setattr(sys, "argv", ["vf"])

    cli.main()

    assert server.shown == []
    out = capsys.readouterr().out
    assert t("cli_already_running") not in out
    assert t("cli_show_failed", error="<>").split("<>")[0].strip() in out


def test_cli_integration_prints_a_usable_url(server, monkeypatch, capsys):
    """`vf integration` prints the URL the token-protected page needs."""
    import vf.__main__ as cli

    monkeypatch.setattr(cli, "SERVER", f"http://127.0.0.1:{server.port}")
    monkeypatch.setattr(sys, "argv", ["vf", "integration"])

    cli.main()

    printed = capsys.readouterr().out
    url = [word for word in printed.split() if word.startswith("http://")][0]
    assert f"token={TOKEN}" in url

    path = url.split(f"127.0.0.1:{server.port}", 1)[1]
    status, _, payload = _call(server.port, "GET", path)
    assert status == 200
    assert b"javascript:" in payload
