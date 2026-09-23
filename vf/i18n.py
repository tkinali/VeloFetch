"""
Lightweight, modular internationalization.

Adding a new language:
  1. Create vf/locales/<code>.py defining STRINGS = {...} (copy en.py).
  2. Import it in vf/locales/__init__.py and call register().
Keys missing from a translation fall back to English, then to the key itself.
"""

import locale

_LOCALES = {}       # code -> {"name": str, "strings": dict}
_current_code = None
_strings = {}


def register(code, name, strings):
    """Register a language pack."""
    _LOCALES[code] = {"name": name, "strings": strings}


def _ensure_registered():
    # Keyed on "en", not on emptiness: a caller may register a pack of its own
    # before the built-ins are imported, and English is the fallback everything
    # else leans on.
    if "en" not in _LOCALES:
        from . import locales  # noqa: F401


def _english_strings():
    return _LOCALES.get("en", {}).get("strings", {})


def detect_system_language():
    """Guess the user's language from the system locale."""
    _ensure_registered()
    try:
        lang = locale.getdefaultlocale()[0] or ""
    except Exception:
        lang = ""
    code = lang.replace("-", "_").split("_")[0].lower()
    return code if code in _LOCALES else "en"


def set_language(code):
    """Activate a language. 'auto'/None/'' follows the system locale."""
    global _current_code, _strings
    _ensure_registered()
    if not code or code == "auto":
        code = detect_system_language()
    _current_code = code
    pack = _LOCALES.get(code)
    _strings = pack["strings"] if pack else _english_strings()
    return _current_code


def get_language():
    return _current_code


def t(key, **kwargs):
    """Translate a key, with optional {placeholder} formatting."""
    _ensure_registered()
    text = _strings.get(key)
    if text is None:
        text = _english_strings().get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def available_languages():
    """Return {code: display name} of registered languages."""
    return {code: info["name"] for code, info in _LOCALES.items()}
