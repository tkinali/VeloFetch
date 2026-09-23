"""
Lightweight HTTP server for receiving download requests from browser extensions.
Listens on localhost:9876 and accepts POST /add with URL + cookies.

Security model:
  * Every endpoint requires the API token from the user's config, sent as the
    X-VeloFetch-Token header or as ?token= (image-beacon and /integration
    fallback). There are exactly two exceptions, and neither one reveals
    anything: /ping, which answers a fixed "I am VeloFetch" so the
    single-instance guard can run before it knows the token, and the OPTIONS
    preflight, which cannot carry a header and only advertises method names.
  * /integration is token protected like the rest: it embeds the token in the
    bookmarklet it serves, so it is exactly as sensitive as the token itself.
    `vf integration` prints the URL with ?token= already filled in.
  * Only loopback Host headers are served, which blocks DNS rebinding.
  * CORS headers are echoed back to the caller's Origin, never "*", and only
    on responses to requests that authenticated successfully.
"""

import base64
import hmac
import html
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Largest POST body accepted on /add (1 MiB); anything bigger gets 413.
MAX_BODY_BYTES = 1024 * 1024

# Transparent 1x1 GIF returned by the image-beacon fallback.
_BEACON_GIF = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

# Where install.sh stages the browser extensions (token-bearing copies).
_STAGED_EXTENSIONS = Path.home() / ".local" / "share" / "velofetch" / "browser"


def is_running(port=9876):
    """Check whether another VeloFetch instance owns the local server."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("app") == "VeloFetch"
    except Exception:
        return False


def _is_http_url(url):
    """Accept only absolute http:// and https:// URLs."""
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class VeloFetchHandler(BaseHTTPRequestHandler):
    """Handle incoming download requests from browser extension."""

    engine = None   # Set by VeloFetchServer before starting
    on_show = None  # Set by VeloFetchServer before starting

    # -- Entry points --

    def do_POST(self):
        self._authenticated = False
        if self._reject_foreign_host():
            return
        path = urlparse(self.path).path
        if path == "/add":
            self._handle_add_download()
        elif path == "/ping":
            # Unauthenticated on purpose, see do_GET's /ping.
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_GET(self):
        self._authenticated = False
        if self._reject_foreign_host():
            return
        path = urlparse(self.path).path

        if path == "/ping":
            # /ping stays unauthenticated ON PURPOSE: vf/__main__.py's
            # single-instance guard calls it before it can know the token,
            # and the reply carries no sensitive data.
            self._send_json(200, {"status": "ok", "app": "VeloFetch"})
        elif path == "/integration":
            self._handle_integration()
        elif path == "/add":
            self._handle_add_beacon()
        elif path == "/show":
            self._handle_show()
        elif path == "/list":
            self._handle_list()
        else:
            self._send_json(404, {"error": "Not found"})

    def do_OPTIONS(self):
        """Handle the CORS preflight for extension requests.

        A preflight cannot carry the token, so it is answered without one.
        It only advertises which headers the real request may send.
        """
        self._authenticated = False
        if self._reject_foreign_host():
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, X-VeloFetch-Token"
        )
        self.end_headers()

    # -- Guards --

    def _allowed_hosts(self):
        """Host header values that address this server over the loopback."""
        port = self.server.server_address[1]
        return (
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            f"[::1]:{port}",
        )

    def _reject_foreign_host(self):
        """Reject non-loopback Host headers (DNS-rebinding defence).

        Returns True when the request has already been answered with 403.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        if host in self._allowed_hosts():
            return False
        self._send_json(403, {"error": "Forbidden host"})
        return True

    def _check_token(self):
        """Verify the API token; returns True when the request was rejected.

        The token is mandatory. It arrives in the X-VeloFetch-Token header or,
        for the bookmarklet's image beacon, as the ?token= query parameter.
        """
        try:
            expected = (self.engine.config.get("api_token") or "").strip()
        except Exception:
            expected = ""
        provided = (self.headers.get("X-VeloFetch-Token") or "").strip()
        if not provided:
            query = parse_qs(urlparse(self.path).query)
            provided = (query.get("token") or [""])[0].strip()

        if not expected or not provided or not hmac.compare_digest(
            provided.encode("utf-8"), expected.encode("utf-8")
        ):
            self._send_json(403, {"error": "Invalid or missing token"})
            return True

        self._authenticated = True
        return False

    # -- Handlers --

    def _handle_show(self):
        """Bring the main window to the front (token protected)."""
        if self._check_token():
            return
        if VeloFetchHandler.on_show:
            try:
                VeloFetchHandler.on_show()
            except Exception:
                pass
        self._send_json(200, {"status": "ok"})

    def _handle_list(self):
        """Return the current download list (token protected)."""
        if self._check_token():
            return
        tasks = []
        for task in self.engine.get_all_tasks():
            tasks.append({
                "id": task.id,
                "filename": task.filename,
                "url": task.url,
                "status": task.status,
                "progress": round(task.progress, 1),
                "total_size": task.total_size,
                "downloaded_size": task.downloaded_size,
                "speed": task.current_speed,
            })
        self._send_json(200, {"tasks": tasks})

    def _handle_add_download(self):
        """Parse request body and add download to engine."""
        if self._check_token():
            return
        try:
            try:
                content_length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                content_length = -1
            if content_length < 0:
                self._send_json(400, {"error": "Invalid Content-Length"})
                return
            if content_length > MAX_BODY_BYTES:
                self._drain_body(content_length)
                self._send_json(413, {"error": "Request body too large"})
                return

            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            url = data.get("url")
            cookies = data.get("cookies", "")
            filename = data.get("filename") or None
            use_yt_dlp = bool(data.get("use_yt_dlp"))

            if not url:
                self._send_json(400, {"error": "URL is required"})
                return
            if not _is_http_url(url):
                self._send_json(400, {"error": "Only http:// and https:// URLs are allowed"})
                return

            # Add download with cookies
            task = self.engine.add_download(
                url,
                filename=filename,
                cookies_raw=cookies if cookies else None,
                use_yt_dlp=use_yt_dlp,
            )

            # Auto-start the download
            self.engine.start_download(task)

            self._send_json(200, {
                "status": "ok",
                "task_id": task.id,
                "filename": task.filename,
            })

        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_add_beacon(self):
        """Image-beacon fallback for the bookmarklet (no CORS response)."""
        if self._check_token():
            return
        query = parse_qs(urlparse(self.path).query)
        url = (query.get("url") or [""])[0]
        if not url:
            self._send_json(400, {"error": "URL is required"})
            return
        if not _is_http_url(url):
            self._send_json(400, {"error": "Only http:// and https:// URLs are allowed"})
            return

        task = self.engine.add_download(url)
        self.engine.start_download(task)

        # 1x1 gif so the beacon "loads"
        payload = base64.b64decode(_BEACON_GIF)
        self.send_response(200)
        self.send_header("Content-Type", "image/gif")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _drain_body(self, content_length, limit=4 * MAX_BODY_BYTES):
        """Discard an oversized body so the client can still read our reply."""
        remaining = min(content_length, limit)
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        self.close_connection = True

    def _handle_integration(self):
        """Serve the browser-integration page (token protected).

        The page hands out the API token inside the bookmarklet, so serving it
        unauthenticated would give every local process that can open a socket
        to the loopback the key to the whole API — and would undo the 0600 on
        config.json, since the same secret would leak over the socket instead.
        The token may arrive as the header or as ?token=, which is what makes
        the page openable from a browser: `vf integration` prints that URL.
        """
        if self._check_token():
            return
        self._send_integration_page()

    def _send_integration_page(self):
        """Browser-integration helper page: draggable bookmarklet with token."""
        from ..i18n import t
        try:
            token = (self.engine.config.get("api_token") or "").strip()
        except Exception:
            token = ""

        # json.dumps produces a safely quoted/escaped JavaScript string literal,
        # so a token containing a quote cannot break out of the bookmarklet.
        js_token = json.dumps(token)
        js_added = json.dumps(t("integration_bm_added"))
        js_error = json.dumps(t("integration_bm_error"))
        js_sent = json.dumps(t("integration_bm_sent"))

        bm = (
            "javascript:(function(){"
            "var u=location.href,c=document.cookie,"
            "T=" + js_token + ","
            "S='http://127.0.0.1:9876';"
            "fetch(S+'/add',{method:'POST',"
            "headers:{'Content-Type':'application/json','X-VeloFetch-Token':T},"
            "body:JSON.stringify({url:u,cookies:c})"
            "}).then(function(r){r.ok?alert(" + js_added + ")"
            ":r.text().then(function(x){alert(" + js_error + "+' '+x)})})"
            ".catch(function(){"
            "new Image().src=S+'/add?token='+encodeURIComponent(T)"
            "+'&url='+encodeURIComponent(u);"
            "alert(" + js_sent + ")})"
            "})()"
        )

        # Locale strings are authored in-tree and may carry markup; only the
        # dynamic values (paths, the bookmarklet href) are escaped.
        chromium_dir = "<code>%s</code>" % html.escape(
            str(_STAGED_EXTENSIONS / "chromium")
        )
        firefox_manifest = "<code>%s</code>" % html.escape(
            str(_STAGED_EXTENSIONS / "firefox" / "manifest.json")
        )
        title = html.escape(t("integration_title"))
        bookmarklet_heading = t("integration_bookmarklet_heading")
        bookmarklet_drag = t("integration_bookmarklet_drag")
        bookmarklet_label = t("integration_bookmarklet_label")
        bookmarklet_usage = t("integration_bookmarklet_usage")
        extension_heading = t("integration_extension_heading")
        chrome_steps = t(
            "integration_chrome_steps",
            page="<code>chrome://extensions</code>",
            path=chromium_dir,
        )
        firefox_steps = t(
            "integration_firefox_steps",
            page="<code>about:debugging#/runtime/this-firefox</code>",
            path=firefox_manifest,
        )
        firefox_note = t("integration_firefox_note")
        cli_heading = t("integration_cli_heading")
        cli_body = t("integration_cli_body", cmd="<code>vf add &lt;url&gt;</code>")
        href = html.escape(bm, quote=True)

        page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<style>
body{{background:#0f0f13;color:#e8e8f2;font-family:sans-serif;max-width:720px;margin:48px auto;padding:0 20px;line-height:1.6}}
h1{{font-size:22px}} code{{background:#22222c;padding:2px 6px;border-radius:4px}}
.bm{{display:inline-block;background:#7aa2f7;color:#10121a;font-weight:bold;padding:12px 22px;border-radius:10px;text-decoration:none;cursor:grab}}
.step{{background:#1a1a22;border:1px solid #2b2b36;border-radius:12px;padding:16px 20px;margin:14px 0}}
.step b{{color:#7aa2f7}}
</style></head><body>
<h1>📥 {title}</h1>

<div class="step">
<b>{bookmarklet_heading}</b><br><br>
{bookmarklet_drag}
<p><a class="bm" href="{href}">⬇ {bookmarklet_label}</a></p>
{bookmarklet_usage}
</div>

<div class="step">
<b>{extension_heading}</b><br><br>
• <b>Chrome/Chromium/Brave:</b> {chrome_steps}<br>
• <b>Firefox:</b> {firefox_steps}<br>
{firefox_note}
</div>

<div class="step">
<b>{cli_heading}</b> {cli_body}
</div>
</body></html>"""
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- Response helpers --

    def _send_cors_headers(self):
        """Echo the caller's Origin — never '*' — plus the Vary hint."""
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")

    def _send_json(self, status, data):
        """Send a JSON response, with CORS only for authenticated callers."""
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if getattr(self, "_authenticated", False):
            self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass  # Silent


class VeloFetchServer:
    """
    Lightweight HTTP server running in a background thread.
    Receives download requests from browser extensions.
    """

    def __init__(self, engine, port=9876, on_show=None):
        self.engine = engine
        self.port = port
        self.on_show = on_show  # Callback: bring the window to front
        self._server = None
        self._thread = None

    def start(self):
        """Start the server in a background thread."""
        VeloFetchHandler.engine = self.engine
        VeloFetchHandler.on_show = self.on_show
        try:
            # Threading: one slow request must not block the whole API.
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), VeloFetchHandler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="velofetch-server",
            )
            self._thread.start()
            return True
        except OSError as e:
            print(f"VeloFetch server could not start on port {self.port}: {e}")
            return False

    def stop(self):
        """Stop the server."""
        if self._server:
            self._server.shutdown()

    @property
    def is_running(self):
        return self._server is not None and self._thread is not None and self._thread.is_alive()
