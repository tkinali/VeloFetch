"""
Guard against re-committing an API token.

A real token was once written into browser/*/background.js by install.sh's
`sed -i` on tracked files and reached git history. install.sh now stages a
private copy of each extension under ~/.local/share/velofetch/ and writes the
token only there, so every file in this repository must stay tokenless.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Anything that assigns a long opaque value to a token-ish name.
SECRET_RE = re.compile(
    r"""(VELFETCH_TOKEN|api_token)          # the name
        \s*[:=]\s*                          # = or :
        ["']([A-Za-z0-9_\-]{16,})["']       # a long opaque literal
    """,
    re.VERBOSE,
)

# Test fixtures deliberately use short, obviously-fake tokens; the 16-char floor
# already excludes them. Only genuine secrets are long and opaque.
ALLOWED_VALUES = {"REPLACE_WITH_YOUR_TOKEN"}

EXTENSION_TOKEN_FILES = [
    "browser/chromium/token.js",
    "browser/firefox/token.js",
]


def _tracked_files():
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


@pytest.mark.parametrize("rel", EXTENSION_TOKEN_FILES)
def test_repo_extension_token_is_empty(rel):
    """The in-repo token.js must never carry a value.

    install.sh writes the real token into the staged copy under
    ~/.local/share/velofetch/browser/<name>/token.js, never into this one.
    """
    path = REPO / rel
    assert path.exists(), f"{rel} is missing; the extensions need it to load"
    source = path.read_text(encoding="utf-8")

    assignments = re.findall(
        r"""self\.VELFETCH_TOKEN\s*=\s*["']([^"']*)["']""", source
    )
    assert assignments, f"{rel} does not assign self.VELFETCH_TOKEN at all"
    for value in assignments:
        assert value == "", (
            f"{rel} carries a token ({value[:6]}…). Never commit one: "
            f"install.sh stages a private copy and writes the token there."
        )


def test_no_git_tracked_file_carries_a_token():
    """No file git knows about may contain a long token literal."""
    offenders = []
    for rel in _tracked_files():
        path = REPO / rel
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary asset or unreadable: cannot hold a pasted token
        for lineno, line in enumerate(source.splitlines(), 1):
            match = SECRET_RE.search(line)
            if not match:
                continue
            value = match.group(2)
            if value in ALLOWED_VALUES:
                continue
            # install.sh writes the staged token through an unexpanded shell
            # variable; "$token" is not a literal secret.
            if "$" in line and "token" in line:
                continue
            offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")

    assert not offenders, "token-looking literals in tracked files:\n" + "\n".join(offenders)
