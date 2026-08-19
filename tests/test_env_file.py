"""Reading `.env`, and the one rule that keeps it from causing damage.

Written because the docs told the owner to put a key in `.env` and `make dev`
never read it — `docker compose` does that itself, so the deployment path
worked and the development path silently did not. The symptom is the worst
kind: the key is right, the file is right, and the feature reports itself
"not configured".
"""

from __future__ import annotations

import pathlib

import pytest

from app.core.env import load_env_file, parse_env


def test_the_ordinary_shape() -> None:
    parsed = parse_env("FISHLOG_GEMINI_API_KEY=abc123\nFISHLOG_GEMINI_MODEL=x\n")
    assert parsed == {"FISHLOG_GEMINI_API_KEY": "abc123", "FISHLOG_GEMINI_MODEL": "x"}


def test_comments_and_blank_lines_are_ignored() -> None:
    parsed = parse_env("# a comment\n\n   \nFISHLOG_A=1\n#FISHLOG_B=2\n")
    assert parsed == {"FISHLOG_A": "1"}


def test_a_leading_export_is_tolerated() -> None:
    """Half the world's .env files are written to be `source`d."""
    assert parse_env("export FISHLOG_A=1\n") == {"FISHLOG_A": "1"}


@pytest.mark.parametrize("quoted", ['FISHLOG_A="abc"', "FISHLOG_A='abc'"])
def test_quotes_are_stripped(quoted: str) -> None:
    """A key stored with its quotation marks attached fails authentication in
    a way nothing on the provider's side explains."""
    assert parse_env(quoted) == {"FISHLOG_A": "abc"}


def test_a_value_containing_an_equals_sign_survives() -> None:
    """Base64 and URLs both end in `=` often enough to matter."""
    assert parse_env("FISHLOG_A=abc=def==") == {"FISHLOG_A": "abc=def=="}


def test_a_line_with_no_equals_is_skipped_not_a_crash() -> None:
    assert parse_env("nonsense\nFISHLOG_A=1\n") == {"FISHLOG_A": "1"}


def test_the_real_environment_wins(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single rule that stops this being dangerous.

    Without it, `FISHLOG_GEMINI_API_KEY=... make dev` would be silently
    overridden by a stale line in a file, and every test that sets a variable
    would be overridden by whatever the developer happens to have on disk -
    so the suite would pass or fail depending on the machine.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("FISHLOG_TEST_VALUE=from-the-file\n", encoding="utf-8")

    monkeypatch.setenv("FISHLOG_TEST_VALUE", "from-the-shell")
    assert load_env_file(env_file) == []

    import os

    assert os.environ["FISHLOG_TEST_VALUE"] == "from-the-shell"


def test_an_unset_variable_is_filled_in(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FISHLOG_TEST_VALUE=from-the-file\n", encoding="utf-8")
    monkeypatch.delenv("FISHLOG_TEST_VALUE", raising=False)

    assert load_env_file(env_file) == ["FISHLOG_TEST_VALUE"]

    import os

    assert os.environ["FISHLOG_TEST_VALUE"] == "from-the-file"


def test_an_empty_value_is_not_applied(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.env.example` is all empty values; copying it must configure nothing.

    Setting a variable to "" would make `is_configured()` see a present-but-
    empty key, which is a different and much more confusing state than absent.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("FISHLOG_TEST_VALUE=\n", encoding="utf-8")
    monkeypatch.delenv("FISHLOG_TEST_VALUE", raising=False)
    assert load_env_file(env_file) == []


def test_a_missing_file_is_not_an_error(tmp_path: pathlib.Path) -> None:
    """Most runs have no `.env`, and every feature it configures is optional."""
    assert load_env_file(tmp_path / "nothing-here") == []


def test_a_directory_where_the_file_should_be_is_not_a_crash(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / ".env").mkdir()
    assert load_env_file(tmp_path / ".env") == []
