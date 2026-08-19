"""Password hashing.

`hashlib.scrypt` is in the standard library, is memory-hard, and is what
`docs/adr/0004` chose over adding passlib/bcrypt/argon2 as a dependency for one
function. The cost parameters are stored *inside* the hash string, so raising
them later does not invalidate existing passwords - an old hash still verifies
under the parameters it was written with, and `needs_rehash` says when to
rewrite it on the next successful sign-in.

Format:  scrypt$n$r$p$<salt-b64>$<key-b64>

No I/O, no clock. Pure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

SCHEME = "scrypt"

# OWASP's 2024 floor for scrypt is n=2^17, r=8, p=1. Cost is a security
# parameter, not fishing knowledge - it belongs in code (CLAUDE.md law 1 is
# about angling heuristics).
DEFAULT_N = 1 << 17
DEFAULT_R = 8
DEFAULT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32
# scrypt needs roughly 128 * n * r bytes; the default cost wants ~128 MB and
# CPython refuses past its own maxmem unless told otherwise.
_MAXMEM = 256 * 1024 * 1024


@dataclass(frozen=True)
class Params:
    """Cost, read at construction time.

    `default_factory` rather than a plain default so the module constant is
    read when a Params() is built, not when the class is defined - that is what
    lets the test suite drop the work factor for the whole run instead of
    threading a cost parameter through every call it makes.
    """

    n: int = field(default_factory=lambda: DEFAULT_N)
    r: int = field(default_factory=lambda: DEFAULT_R)
    p: int = field(default_factory=lambda: DEFAULT_P)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive(password: str, salt: bytes, params: Params) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=params.n,
        r=params.r,
        p=params.p,
        dklen=KEY_BYTES,
        maxmem=_MAXMEM,
    )


def hash_password(password: str, params: Params | None = None) -> str:
    """Return a self-describing hash string. A fresh salt every call."""
    params = params or Params()
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, params)
    return f"{SCHEME}${params.n}${params.r}${params.p}${_b64(salt)}${_b64(key)}"


def _parse(stored: str) -> tuple[Params, bytes, bytes] | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return None
    try:
        params = Params(int(parts[1]), int(parts[2]), int(parts[3]))
        return params, _unb64(parts[4]), _unb64(parts[5])
    except (ValueError, TypeError):
        return None


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. A malformed or missing hash is a failure, not a crash.

    `stored` is None for an account that only ever signed in with Google. Such
    an account must not be enterable with a blank password, which is exactly
    what a naive `if not stored: return True` would allow.
    """
    if not stored:
        return False
    parsed = _parse(stored)
    if parsed is None:
        return False
    params, salt, expected = parsed
    return hmac.compare_digest(_derive(password, salt, params), expected)


def needs_rehash(stored: str | None, params: Params | None = None) -> bool:
    """True when a stored hash is weaker than what we now write."""
    if not stored:
        return False
    parsed = _parse(stored)
    if parsed is None:
        return True
    target = params or Params()
    current = parsed[0]
    return (current.n, current.r, current.p) < (target.n, target.r, target.p)
