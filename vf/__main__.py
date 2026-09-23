"""
Entry point for VeloFetch.

- No arguments: launch the GUI.
- `vf add <url>`: send a download to a running VeloFetch instance.
- `vf list`: list downloads of a running instance.
- `vf ping`: check whether the local server is up.
- `vf integration`: print the browser-integration URL, token included.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

from vf import locales  # noqa: F401 (registers language packs)
from vf.i18n import set_language, t

SERVER = "http://127.0.0.1:9876"


def _api_token():
    """Read the local API token (same user's config)."""
    try:
        from vf.core.config import Config
        return (Config().get("api_token") or "").strip()
    except Exception:
        return ""


def _request(path, payload=None):
    """POST/GET the local VeloFetch server; returns (ok, data)."""
    token = _api_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-VeloFetch-Token"] = token
    try:
        if payload is None:
            req = urllib.request.Request(f"{SERVER}{path}", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                return True, json.loads(resp.read().decode("utf-8"))
        req = urllib.request.Request(
            f"{SERVER}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, str(e)


def _fail_not_running():
    print(t("cli_not_running"))
    sys.exit(1)


def cli_main(argv):
    set_language(None)  # follow system locale
    parser = argparse.ArgumentParser(
        prog="vf",
        description=t("cli_desc"),
    )
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help=t("cli_help_add"))
    p_add.add_argument("url", help=t("cli_help_url"))
    p_add.add_argument("--filename", "-f", help=t("cli_help_filename"))
    p_add.add_argument("--cookies", "-c", help=t("cli_help_cookies"))

    sub.add_parser("list", help=t("cli_help_list"))
    sub.add_parser("ping", help=t("cli_help_ping"))
    sub.add_parser("integration", help=t("cli_help_integration"))

    args = parser.parse_args(argv)

    if args.command == "add":
        payload = {"url": args.url}
        if args.cookies:
            payload["cookies"] = args.cookies
        if args.filename:
            payload["filename"] = args.filename
        ok, data = _request("/add", payload)
        if not ok:
            _fail_not_running()
        print(t("cli_added", name=data.get("filename", args.url)))
    elif args.command == "list":
        ok, data = _request("/list")
        if not ok:
            _fail_not_running()
        tasks = data.get("tasks", [])
        if not tasks:
            print(t("cli_no_downloads"))
            return
        for task in tasks:
            print(f"[{task['status']:>11}] {task['progress']:5.1f}%  {task['filename']}")
    elif args.command == "ping":
        ok, data = _request("/ping")
        if ok:
            print(t("cli_running"))
        else:
            print(t("cli_not_running_ping"))
            sys.exit(1)
    elif args.command == "integration":
        # /integration embeds the token in the bookmarklet, so the server only
        # serves it to an authenticated caller. Print the ready-made URL: the
        # token never has to be copied out of config.json by hand.
        token = _api_token()
        if not token:
            print(t("cli_no_token"))
            sys.exit(1)
        ok, _data = _request("/ping")
        if not ok:
            _fail_not_running()
        print(t(
            "cli_integration_url",
            url=f"{SERVER}/integration?token={quote(token, safe='')}",
        ))
    else:
        parser.print_help()


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("add", "list", "ping", "integration"):
        cli_main(sys.argv[1:])
        return

    # Single-instance guard: if VeloFetch already owns the local server,
    # bring its window to the front instead of starting a second copy.
    from vf.core.server import is_running
    if is_running():
        set_language(None)
        # /show is token-protected; _request attaches the configured token.
        # When it fails — token rotated since this process read the config,
        # unreadable config, 403 — no window comes forward, so say that
        # instead of claiming it did.
        ok, detail = _request("/show")
        if ok:
            print(t("cli_already_running"))
        else:
            print(t("cli_show_failed", error=detail))
        return

    try:
        from vf.qtgui.app import run
        run()
    except ImportError as e:
        print(f"Error: Missing dependency: {e}")
        print("Please install required packages: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Ensure the package is importable when run from a source checkout
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
