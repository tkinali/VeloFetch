"""Tests for configuration module."""

import json

from conftest import REAL_CONFIG_FILE, config_snapshot, reset_config_singleton

from vf.core.config import Config

# The throw-away home every test runs in comes from the autouse isolated_home
# fixture in tests/conftest.py, which covers the whole suite.


class TestConfig:
    def test_isolated_from_real_config(self, isolated_home):
        """The fixture must redirect Config away from the user's own file."""
        config = Config()
        assert config.config_file.is_relative_to(isolated_home)
        assert config.config_file.name == "config.json"
        assert config.config_file != REAL_CONFIG_FILE

    def test_defaults(self):
        config = Config()
        assert config.max_concurrent == 3
        assert config.retry_count == 5
        assert config.retry_delay == 3
        assert config.chunk_size == 8192
        assert config.timeout == 30

    def test_singleton(self):
        c1 = Config()
        c2 = Config()
        assert c1 is c2

    def test_get_set(self):
        config = Config()
        config.set("test_key", "test_value")
        assert config.get("test_key") == "test_value"
        assert config.get("nonexistent", "default") == "default"

    def test_persistence(self):
        config = Config()
        config.set("persist_test", "hello")
        saved = json.loads(config.config_file.read_text())
        assert saved["persist_test"] == "hello"
        # Re-create should load the saved value
        reset_config_singleton()
        config2 = Config()
        assert config2.get("persist_test") == "hello"

    def test_real_config_file_is_never_touched(self, real_config_snapshot):
        """Writing through Config must not reach ~/.config/velofetch.

        The reference snapshot is the session-start one: tests earlier in this
        class write the very same keys, so a snapshot taken here would match a
        clobbered file and pass vacuously.
        """
        config = Config()
        config.set("test_key", "test_value")
        config.set("persist_test", "hello")
        assert config_snapshot(REAL_CONFIG_FILE) == real_config_snapshot
