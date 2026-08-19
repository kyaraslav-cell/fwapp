"""No credential may be committed. `make check` is where that gets caught.

This exists because a key in git history is a *leaked* key. Deleting it in a
later commit does not help — the object is still in the history, the history is
on GitHub, and the only real fix is revoking the key at the provider and
issuing a new one. So the check has to run before the commit, not after
somebody notices.

It scans **tracked files only**, which is the whole surface that can reach
GitHub. `.env` is gitignored and is the right place for a real key; this test
never looks at it and would not object if it did.

Deliberately narrow. A regex that flags anything key-shaped fails on hex
digests, base64 fixtures and OSM ids, and a check that cries wolf is a check
people learn to skip. It matches the two literal prefixes Google's own
credentials carry, a PEM block, and an assignment to one of *this app's* own
credential variables with a long value in it.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent

# Provider-issued shapes. These are not guesses: Google API keys begin `AIza`,
# and OAuth client secrets issued since 2021 begin `GOCSPX-`.
SIGNATURES: tuple[tuple[str, str], ...] = (
    (r"AIza[0-9A-Za-z_\-]{30,}", "a Google API key"),
    (r"GOCSPX-[0-9A-Za-z_\-]{10,}", "a Google OAuth client secret"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key"),
)

# One of this app's own credential variables, assigned something long enough to
# be real. `FOO=` and `FOO="k"` in a test are left alone.
# `[ \t]*` and not `\s*`: `\s` eats newlines, so `FISHLOG_GEMINI_API_KEY=` on
# its own line would swallow the blank line after it and match whatever came
# next in the file. That is how this check first failed - against
# `.env.example`, whose values are deliberately empty.
ASSIGNMENT = re.compile(
    r"""FISHLOG_[A-Z_]*(?:KEY|SECRET)[ \t]*[=:][ \t]*["']?([^"'\s,}{)]{15,})""",
)

# Placeholders that are meant to be there.
PLACEHOLDERS = re.compile(
    r"^(\$\{|\.\.\.|<|your|test|fake|example|changeme|xxx)", re.IGNORECASE
)

SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf")


def tracked_files() -> list[pathlib.Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [REPO / name for name in out.split("\0") if name]


def test_no_credential_is_committed() -> None:
    findings: list[str] = []

    for path in tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        # This file names the patterns it looks for; it would flag itself.
        if path.name == pathlib.Path(__file__).name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for pattern, what in SIGNATURES:
            if re.search(pattern, text):
                findings.append(f"{path.relative_to(REPO)}: looks like {what}")

        for match in ASSIGNMENT.finditer(text):
            value = match.group(1)
            if PLACEHOLDERS.match(value):
                continue
            findings.append(
                f"{path.relative_to(REPO)}: a credential variable is assigned "
                f"a {len(value)}-character literal"
            )

    assert not findings, (
        "A credential appears to be committed. Deleting it in a later commit "
        "does NOT undo this - the object stays in the history and the history "
        "is on GitHub. Revoke the key at the provider, issue a new one, and "
        "put it in .env (gitignored) or the shell environment instead. See "
        "docs/10 §8a.\n  " + "\n  ".join(findings)
    )


def test_the_check_would_actually_catch_one() -> None:
    """A guard nobody has seen fire is a guard nobody should trust."""
    sample = 'FISHLOG_GEMINI_API_KEY = "AIzaSyD-000000000000000000000000000000000"'
    assert any(re.search(p, sample) for p, _ in SIGNATURES)
    match = ASSIGNMENT.search(sample)
    assert match is not None and not PLACEHOLDERS.match(match.group(1))


def test_the_example_file_and_the_tests_do_not_trip_it() -> None:
    """The placeholders that are supposed to be there stay allowed."""
    for benign in (
        "FISHLOG_GEMINI_API_KEY=",
        'FISHLOG_GEMINI_API_KEY: "${FISHLOG_GEMINI_API_KEY:-}"',
        'monkeypatch.setenv("FISHLOG_GEMINI_API_KEY", "k")',
        'api_key="test-key"',
    ):
        match = ASSIGNMENT.search(benign)
        assert match is None or PLACEHOLDERS.match(match.group(1)), benign
