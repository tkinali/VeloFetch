"""Tests for the auto_rename setting and the filename-collision policy."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from vf.core.config import Config
from vf.core.downloader import DownloadEngine

# -- Helpers --


def _reset_config_singleton():
    """Drop the Config singleton so the next Config() re-reads its paths."""
    Config._instance = None
    Config._config_data = {}


class _StubConfig:
    """Minimal stand-in exposing only what _safe_filename reads."""

    def __init__(self, auto_rename):
        self.auto_rename = auto_rename


class _StubEngine:
    """Borrow _safe_filename without building a Database-backed engine."""

    _safe_filename = DownloadEngine._safe_filename

    def __init__(self, auto_rename):
        self.config = _StubConfig(auto_rename)


# -- Config properties --


class TestCollisionConfig:
    @pytest.fixture(autouse=True)
    def isolated_home(self, tmp_path, monkeypatch):
        """Point Config at a throw-away home so the real config is untouched."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        _reset_config_singleton()
        yield home
        _reset_config_singleton()

    def test_defaults(self):
        """Renaming is on and overwriting is off unless configured otherwise."""
        config = Config()
        assert config.auto_rename is True
        assert config.overwrite_existing is False

    def test_reads_saved_values(self):
        config = Config()
        config.set("auto_rename", False)
        config.set("overwrite_existing", True)
        assert config.auto_rename is False
        assert config.overwrite_existing is True

    def test_missing_keys_fall_back(self):
        """An older config file without the keys still resolves to the defaults."""
        config = Config()
        config._config_data.pop("auto_rename", None)
        config._config_data.pop("overwrite_existing", None)
        assert config.auto_rename is True
        assert config.overwrite_existing is False


# -- Collision policy --


class TestSafeFilename:
    def test_no_collision_keeps_name(self, tmp_path):
        for auto_rename in (True, False):
            engine = _StubEngine(auto_rename)
            assert engine._safe_filename("a.iso", str(tmp_path)) == "a.iso"

    def test_strips_problematic_characters(self, tmp_path):
        engine = _StubEngine(True)
        assert engine._safe_filename("a/b:c*.iso", str(tmp_path)) == "abc.iso"

    def test_auto_rename_suffixes_collision(self, tmp_path):
        (tmp_path / "a.iso").touch()
        engine = _StubEngine(True)
        assert engine._safe_filename("a.iso", str(tmp_path)) == "a_1.iso"

        (tmp_path / "a_1.iso").touch()
        assert engine._safe_filename("a.iso", str(tmp_path)) == "a_2.iso"

    def test_auto_rename_counts_part_files(self, tmp_path):
        """An in-flight .part file collides just like a finished one."""
        (tmp_path / "b.iso.part").touch()
        engine = _StubEngine(True)
        assert engine._safe_filename("b.iso", str(tmp_path)) == "b_1.iso"

    def test_disabled_auto_rename_refuses_collision(self, tmp_path):
        (tmp_path / "c.iso").touch()
        engine = _StubEngine(False)
        with pytest.raises(FileExistsError) as excinfo:
            engine._safe_filename("c.iso", str(tmp_path))
        assert "c.iso" in str(excinfo.value)

    def test_disabled_auto_rename_refuses_part_collision(self, tmp_path):
        (tmp_path / "d.iso.part").touch()
        engine = _StubEngine(False)
        with pytest.raises(FileExistsError):
            engine._safe_filename("d.iso", str(tmp_path))
