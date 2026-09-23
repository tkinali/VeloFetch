"""Tests for the i18n module."""

import subprocess
import sys
from pathlib import Path

import pytest

from vf import i18n
from vf.i18n import available_languages, detect_system_language, get_language, set_language, t


@pytest.fixture
def partial_pack():
    """Register a throwaway pack that only translates one key."""
    code = "zz"
    i18n.register(code, "Test", {"filter_all": "ZZ All"})
    try:
        yield code
    finally:
        i18n._LOCALES.pop(code, None)
        set_language("en")


def test_lazy_registration():
    # t() must work without an explicit set_language call
    assert t("filter_all") == "All"  # falls back to English


def test_english():
    set_language("en")
    assert get_language() == "en"
    assert t("filter_all") == "All"
    assert t("status_counts", active=2, total=5) == "2 active • 5 downloads"


def test_turkish():
    set_language("tr")
    assert get_language() == "tr"
    assert t("filter_all") == "Tümü"
    assert t("status_counts", active=2, total=5) == "2 aktif • 5 indirme"


def test_fallback_to_english_for_missing_key(partial_pack):
    from vf.locales import en

    set_language(partial_pack)
    # The one key the pack does translate wins over English…
    assert t("filter_all") == "ZZ All"
    # …every other key falls back to the English text, not the raw key.
    assert t("btn_save") == en.STRINGS["btn_save"]


def test_fallback_keeps_formatting(partial_pack):
    set_language(partial_pack)
    assert t("status_counts", active=1, total=3) == "1 active • 3 downloads"


def test_custom_pack_registered_before_the_builtins():
    """Registering a pack first must not convince i18n the built-ins are loaded.

    _ensure_registered() used to skip the import whenever _LOCALES held
    anything at all, so the very next set_language() died on _LOCALES["en"].
    Needs a fresh interpreter: once vf.locales is in sys.modules the packs
    cannot be un-registered from inside this process.
    """
    proc = subprocess.run(
        [
            sys.executable, "-c",
            "from vf import i18n\n"
            "i18n.register('zz', 'Test', {'filter_all': 'ZZ All'})\n"
            "i18n.set_language('zz')\n"
            "print(i18n.t('filter_all'))\n"
            "print(i18n.t('btn_save'))\n",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"registering a pack first crashed i18n:\n{proc.stderr}"
    own_key, fallback = proc.stdout.splitlines()[:2]
    assert own_key == "ZZ All"      # the custom pack still wins
    assert fallback == "Save"       # English pack got imported after all


def test_unknown_key_returns_key():
    assert t("no_such_key_anywhere") == "no_such_key_anywhere"


def test_unknown_language_falls_back_to_english():
    set_language("no_such_language")
    assert t("filter_all") == "All"


def test_missing_placeholder_returns_unformatted_text():
    set_language("en")
    # A caller that forgets a field gets the template back instead of a KeyError.
    assert t("status_counts", active=2) == "{active} active • {total} downloads"


def test_extra_placeholder_is_ignored():
    set_language("en")
    assert t("filter_all", unused="x") == "All"


def test_available_languages():
    langs = available_languages()
    assert "en" in langs and "tr" in langs


def test_auto_detect_falls_back_to_english():
    set_language("auto")
    # Whatever the system locale, result must be a registered language
    assert get_language() in available_languages()


def test_detect_system_language_is_registered():
    assert detect_system_language() in available_languages()
