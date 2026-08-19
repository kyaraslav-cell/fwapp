"""Read `.env` into the environment, with no dependency and no surprises.

`docker compose` reads `.env` by itself, so the deployment path already worked.
`make dev` did not, which meant the documented way to configure this app was
silently a no-op for anyone running it outside docker - you put the key in the
file the docs name, restart, and the feature reports itself "not configured".
That is the worst kind of failure: it looks like the key is wrong.

Not `python-dotenv`. Thirty lines of stdlib against a new dependency and an
ADR to justify it (`CLAUDE.md`, stack rules) is not a close call.

**The real environment always wins.** A variable already set in the process is
never overwritten by the file. Otherwise `FISHLOG_GEMINI_API_KEY=... make dev`
would be silently ignored in favour of a stale line in a file, and a test that
sets a variable would be overridden by whatever the developer happens to have
on disk - which would make the suite pass or fail depending on the machine.
"""

from __future__ import annotations

import os
import pathlib

from app.core.config import REPO_ROOT

ENV_FILE = REPO_ROOT / ".env"


def parse_env(text: str) -> dict[str, str]:
    """`KEY=value` lines. Comments, blanks and a leading `export` are tolerated.

    Quotes around the value are stripped, because every example of a `.env`
    file on the internet has them half the time and a key stored with its
    quotation marks attached fails authentication in a way nothing explains.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if not name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def load_env_file(path: pathlib.Path | None = None) -> list[str]:
    """Apply `.env` to `os.environ`. Returns the names it actually set.

    Missing file is not an error - most runs do not have one, and every feature
    it would configure is optional and says so when it is off.
    """
    path = path or ENV_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    applied: list[str] = []
    for name, value in parse_env(text).items():
        # Already set wins. An empty line in the file is not a value.
        if os.environ.get(name) or not value:
            continue
        os.environ[name] = value
        applied.append(name)
    return applied
