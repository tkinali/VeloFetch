"""
Guards that keep the language packs from drifting apart.

The Turkish pack once lagged 32 keys behind English, which silently showed raw
English text to Turkish users because t() falls back instead of failing. These
tests turn every kind of drift into a red test:

  * a key added to English but not to every other pack (and vice versa),
  * an empty translation,
  * a {placeholder} dropped or renamed in a translation,
  * a t("key") in vf/ that no pack defines,
  * a key kept in the packs that nothing in vf/ uses any more.
"""

import ast
import re
from pathlib import Path

import pytest

from vf import i18n
from vf import locales as _locales  # noqa: F401  — importing registers the packs

VF_ROOT = Path(__file__).resolve().parent.parent / "vf"
LOCALES_DIR = VF_ROOT / "locales"

# Any {...} group, so a stray {0} or {} is compared too, not just named fields.
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


# -- Fixtures / helpers --

def _registered_strings():
    """Return {code: STRINGS} for every registered language pack.

    i18n exposes only the display names publicly, so the registry itself is
    read directly here.
    """
    return {code: i18n._LOCALES[code]["strings"] for code in i18n.available_languages()}


CODES = sorted(_registered_strings())
TRANSLATIONS = [code for code in CODES if code != "en"]


def _source_files():
    """Every VeloFetch source file that may call t()."""
    for path in sorted(VF_ROOT.rglob("*.py")):
        if path.parent == LOCALES_DIR or path.name == "i18n.py":
            continue
        yield path


def _rel(path):
    return path.relative_to(VF_ROOT.parent).as_posix()


def _literal_t_keys():
    """Collect [(file, line, key)] for every t("literal") call in vf/.

    Calls made through a variable — t(label_key), t(tip_key), t(dict(FILTERS)[key])
    — carry no key here on purpose: their keys live in tables next to the call
    site and are covered by test_no_unused_keys below, which looks for the key
    as a plain string literal anywhere in the source.
    """
    found = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "t":
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((_rel(path), first.lineno, first.value))
    return found


def _source_string_literals():
    """Every string constant in vf/, outside the packs themselves."""
    literals = set()
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
    return literals


def _declared_keys(code):
    """Keys of a pack in file order, read from the source (duplicates kept)."""
    path = LOCALES_DIR / f"{code}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "STRINGS"
            for target in node.targets
        ):
            return [key.value for key in node.value.keys]
    raise AssertionError(f"{_rel(path)} defines no STRINGS dict")


# -- Registration --

def test_every_locale_module_is_registered():
    on_disk = {p.stem for p in LOCALES_DIR.glob("*.py") if p.stem != "__init__"}
    assert on_disk == set(CODES), (
        "vf/locales/__init__.py is out of sync with the files next to it\n"
        f"  on disk but not registered: {sorted(on_disk - set(CODES)) or '-'}\n"
        f"  registered but no module:   {sorted(set(CODES) - on_disk) or '-'}"
    )


def test_english_is_the_reference_pack():
    assert "en" in CODES


# -- Key parity --

@pytest.mark.parametrize("code", TRANSLATIONS)
def test_same_keys_as_english(code):
    packs = _registered_strings()
    english = set(packs["en"])
    keys = set(packs[code])

    missing = sorted(english - keys)
    unknown = sorted(keys - english)
    assert not missing and not unknown, (
        f"vf/locales/{code}.py has drifted from vf/locales/en.py\n"
        f"  missing ({len(missing)}): {', '.join(missing) or '-'}\n"
        f"  unknown ({len(unknown)}): {', '.join(unknown) or '-'}"
    )


@pytest.mark.parametrize("code", CODES)
def test_no_duplicate_keys(code):
    declared = _declared_keys(code)
    duplicates = sorted({k for k in declared if declared.count(k) > 1})
    assert not duplicates, (
        f"vf/locales/{code}.py defines these keys twice (the later value silently "
        f"wins): {', '.join(duplicates)}"
    )


# -- Values --

@pytest.mark.parametrize("code", CODES)
def test_no_empty_values(code):
    strings = _registered_strings()[code]
    empty = sorted(key for key, value in strings.items() if not str(value).strip())
    assert not empty, (
        f"vf/locales/{code}.py leaves these keys blank — the UI would render "
        f"nothing: {', '.join(empty)}"
    )


@pytest.mark.parametrize("code", CODES)
def test_values_are_strings(code):
    strings = _registered_strings()[code]
    bad = sorted(key for key, value in strings.items() if not isinstance(value, str))
    assert not bad, f"vf/locales/{code}.py maps these keys to non-strings: {', '.join(bad)}"


@pytest.mark.parametrize("code", TRANSLATIONS)
def test_placeholders_match_english(code):
    packs = _registered_strings()
    english = packs["en"]
    strings = packs[code]

    problems = []
    for key, text in english.items():
        if key not in strings:
            continue  # reported by test_same_keys_as_english
        expected = set(PLACEHOLDER_RE.findall(text))
        actual = set(PLACEHOLDER_RE.findall(strings[key]))
        if expected != actual:
            problems.append(
                f"  {key}: expected {sorted(expected) or '[]'}, got {sorted(actual) or '[]'}"
            )
    assert not problems, (
        f"vf/locales/{code}.py changes the {{placeholders}} t() fills in; a dropped or "
        "renamed one makes the format() fail silently and shows the raw text:\n"
        + "\n".join(problems)
    )


# -- Source ↔ pack consistency --

def test_every_t_key_exists_in_english():
    english = _registered_strings()["en"]
    unknown = [
        f"  {path}:{line}: t({key!r})"
        for path, line, key in _literal_t_keys()
        if key not in english
    ]
    assert not unknown, (
        "these t() calls use keys that vf/locales/en.py does not define, so the UI "
        "would show the raw key:\n" + "\n".join(unknown)
    )


def test_no_unused_keys():
    """No pack should carry a key the application never asks for.

    A key counts as used when it appears as a string literal anywhere in vf/,
    which also covers the indirect call sites: the FILTERS table in
    main_window.py, the _section(..., "section_x") calls in settings_dialog.py
    and the tooltip table in download_card.py all name their keys as literals.
    """
    literals = _source_string_literals()
    unused = sorted(key for key in _registered_strings()["en"] if key not in literals)
    assert not unused, (
        "these keys are defined in the language packs but never referenced from "
        "vf/ — delete them from every pack, or wire them up:\n  "
        + "\n  ".join(unused)
    )
