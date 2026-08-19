"""Session tokens: mint one, store only its hash.

The cookie carries a random 256-bit token. The database stores
`sha256(token)`, so a leaked database backup - the thing this project asks the
owner to copy around as its backup strategy (`docs/05`) - does not hand anyone
a working session. SHA-256 with no salt is right here and wrong for passwords:
the input is already 256 bits of entropy, so there is nothing to brute-force
and nothing a rainbow table can precompute.

Pure. No I/O, no clock - expiry times are passed in.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32
COOKIE_NAME = "fishlog_auth"
# Long enough that the angler is not signed out between trips, short enough
# that a forgotten phone is not a permanent key.
SESSION_DAYS = 30
# Sliding window: a session seen inside its last week gets pushed back out to
# a full term, so regular use never hits the wall.
REFRESH_WITHIN_DAYS = 7


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(token_hash(token), stored_hash)
