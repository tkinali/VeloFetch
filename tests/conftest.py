"""Fixtures shared by the whole test suite.

Config takes its paths from Path.home(), and Config.load() mints an API token
and save()s it whenever the stored one is empty. Merely constructing Config
therefore rewrites — and chmods — the config file of whatever home it finds, so
every test runs against a throw-away home. The session guard below fails the
run if the user's real file was touched anyway.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from vf.core.config import Config

#: The user's real config file, resolved before any patching happens.
#: The suite must never create or modify it.
REAL_CONFIG_FILE = Path.home() / ".config" / "velofetch" / "config.json"


def reset_config_singleton():
    """Drop the Config singleton so the next Config() re-reads its paths."""
    Config._instance = None
    Config._config_data = {}


def config_snapshot(path):
    """Return the file's (bytes, mode), or None when it does not exist."""
    try:
        return path.read_bytes(), path.stat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None


@pytest.fixture(scope="session", autouse=True)
def real_config_snapshot():
    """Record the real config file before the first test, verify it at the end.

    The value is handed out so a test can compare against the pre-session state
    instead of a snapshot taken after earlier tests have already written to the
    file — that later snapshot hides exactly the clobbering it should catch.
    """
    before = config_snapshot(REAL_CONFIG_FILE)
    yield before
    assert config_snapshot(REAL_CONFIG_FILE) == before, (
        f"the test suite created or modified {REAL_CONFIG_FILE}"
    )


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point Config at a throw-away home directory for every test.

    Config derives its paths from Path.home(), which resolves $HOME on POSIX,
    so redirecting the environment is what moves it. Path.home itself is
    deliberately left alone: replacing the attribute here would pin every test
    to this directory and silently defeat the modules that set up a home of
    their own (tests/test_server_token.py). DEFAULT_DOWNLOAD_DIR is baked in at
    import time from the real home, so it is redirected as well. The singleton
    is reset on the way in and on the way out so no state leaks between tests.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setattr(Config, "DEFAULT_DOWNLOAD_DIR", str(home / "Downloads"))
    reset_config_singleton()
    yield home
    reset_config_singleton()
