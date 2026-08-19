"""Sign in with Google, and the honest behaviour when it is not configured.

Authorization-code flow, server side:

    /auth/google  ->  Google consent screen  ->  /auth/google/callback?code=...
                                                     |
                              exchange the code for tokens at Google's
                              token endpoint, then read the profile from
                              the userinfo endpoint

**Why userinfo rather than decoding the id_token.** Verifying a JWT signature
means fetching and caching Google's rotating JWKS and doing RSA verification -
a dependency (`google-auth` or `pyjwt[crypto]`) for one call. Calling the
userinfo endpoint over TLS with the freshly issued access token gets the same
three fields from the same origin, with the transport doing the authentication.
The cost is one extra HTTPS round trip per sign-in, which happens once a month
per angler. ADR 0004 records this.

**Not configured is a state, not an error to paper over.** With no client id
and secret in the environment the button is not rendered and the routes answer
`GoogleNotConfiguredError`. It never falls back to something that looks like it
worked. Note that no Google endpoint has ever been reached from the build
sandbox - `docs/10 §6` - so this path is written to be exercised against the
fake exchanger in `tests/fixtures/`, and its first real run will be on the
owner's machine.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"
STATE_COOKIE = "fishlog_oauth_state"
TIMEOUT_S = 10.0


class GoogleNotConfiguredError(RuntimeError):
    """No client id/secret in the environment. The button should not be shown."""


class GoogleAuthError(RuntimeError):
    """Google answered, and the answer was not one we can sign anybody in with."""


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class GoogleIdentity:
    """The only three fields this app wants, and what each is for."""

    sub: str          # stable account id; the join key
    email: str        # display and first-time account creation
    name: str         # display name, may be empty
    email_verified: bool


def load_config() -> GoogleConfig | None:
    """Read the environment. None means "not set up", which is not a failure."""
    client_id = os.environ.get("FISHLOG_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("FISHLOG_GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("FISHLOG_GOOGLE_REDIRECT_URI", "").strip()
    if not (client_id and client_secret and redirect_uri):
        return None
    return GoogleConfig(client_id, client_secret, redirect_uri)


def is_configured() -> bool:
    return load_config() is not None


def new_state() -> str:
    """CSRF state. Stored in a cookie and compared on the way back."""
    return secrets.token_urlsafe(24)


def authorization_url(config: GoogleConfig, state: str) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        # No refresh token is requested: this app acts on the angler's behalf
        # exactly once, at sign-in, and holding a long-lived Google credential
        # it never uses would be a liability with no upside.
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _identity_from_userinfo(payload: dict[str, Any]) -> GoogleIdentity:
    sub = str(payload.get("sub") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    if not sub or not email:
        raise GoogleAuthError("userinfo response carried no subject or no email")
    return GoogleIdentity(
        sub=sub,
        email=email,
        name=str(payload.get("name") or "").strip(),
        email_verified=bool(payload.get("email_verified", False)),
    )


def exchange_code(config: GoogleConfig, code: str) -> GoogleIdentity:
    """Swap the one-time code for an access token, then read the profile."""
    with httpx.Client(timeout=TIMEOUT_S) as client:
        token_response = client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code != 200:
            raise GoogleAuthError(f"token endpoint returned {token_response.status_code}")
        access_token = str(token_response.json().get("access_token") or "")
        if not access_token:
            raise GoogleAuthError("token endpoint returned no access token")

        userinfo = client.get(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo.status_code != 200:
            raise GoogleAuthError(f"userinfo returned {userinfo.status_code}")
        payload: dict[str, Any] = userinfo.json()

    return _identity_from_userinfo(payload)
