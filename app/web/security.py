"""Response headers a browser needs in order to defend this app for us.

None of these existed before `docs/15 §A1`. Each is here for a reason specific
to what this app actually serves, not because a checklist named it.

**`Content-Security-Policy`.** The lake page renders three kinds of text this
app did not write: lake and species names from OpenStreetMap, and - since the
Gemini pass - prose a language model produced while citing arbitrary web pages,
along with the URLs it chose. Jinja autoescapes all of it, and autoescaping is
the defence that works until the day somebody adds one `| safe` in a hurry.
CSP is the one that still holds afterwards.

The policy has to admit what the page genuinely loads, which is worth writing
down because it is also the argument for eventually vendoring these:

- `unpkg.com` - Leaflet's script and stylesheet;
- `*.arcgisonline.com` - Esri satellite tiles, as images;
- Google Fonts: **no longer**. The Waterline design dropped the webfont for a
  system stack (docs/17-DESIGN-SYSTEM.md), so both Google origins came out of
  the policy. A CSP that still admits an origin the app stopped using is a
  standing permission nobody is watching;
- `'unsafe-inline'` for scripts, because the map, the day strip, the fish pin
  and the register form are all inline `<script>` blocks. This is the weakest
  line here and it is honest about being so: removing it means either nonces
  through every template or moving that JS into `/static`. Worth doing; not
  worth blocking the launch on.

`data:` is allowed for images because the heat overlay is drawn to a canvas and
handed to Leaflet as a data URI. `connect-src 'self'` keeps `/grid` working and
stops any injected script from posting the notebook somewhere else.

**`X-Content-Type-Options: nosniff`.** `/media` serves files an angler uploaded,
from this app's own origin - the origin that holds the session cookie. Without
`nosniff` a browser may decide a file is HTML regardless of what we called it,
and run it there. `app/web/routes/sessions.py` checks the extension on upload;
this is the second lock on the same door.

**`X-Frame-Options: DENY`** and `frame-ancestors 'none'`. Nothing here should
ever be framed, and "End session" is a one-tap destructive control - exactly
what clickjacking is for.

The one exception, opt-in and never on by default: a **dev container preview
pane is an iframe**. VS Code's Simple Browser framed the app, the browser
refused, and the page showed "refused to connect" - which reads exactly like a
dead server and is not. `FISHLOG_FRAME_ANCESTORS` replaces `'none'` with an
explicit ancestor list for that case, and drops `X-Frame-Options` while it is
set, because that header has no allowlist worth using: `ALLOW-FROM` is dead in
every current browser, so `SAMEORIGIN` or `DENY` are the only real values and
neither describes "framed by the editor". `frame-ancestors` is the modern
control and the one that can be narrow.

Set it to the editor's origin - `https://*.app.github.dev` - never to `*`. And
it belongs in a dev container's environment, not in a deployment: opening the
forwarded port in a real browser tab needs none of this.

**`Referrer-Policy: strict-origin-when-cross-origin`.** Without it, following a
collected-knowledge source link sends the full URL of the page it was on. Lake
slugs are not secret, but there is no reason to hand every cited site a
referrer trail of which waters this angler reads about.

**HSTS, only over https.** Sending it on plain http would be ignored anyway,
and setting it during local development would pin `localhost` to https in the
developer's browser - a genuinely annoying thing to undo.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

LEAFLET = "https://unpkg.com"
TILES = "https://*.arcgisonline.com https://server.arcgisonline.com"

def frame_ancestors() -> str:
    """`'none'` unless a dev container has explicitly asked to be allowed.

    Read at call time rather than at import, so a test can set it and so the
    value is never baked into a module-level constant that looks like policy.
    """
    allowed = os.environ.get("FISHLOG_FRAME_ANCESTORS", "").strip()
    return allowed or "'none'"


def _csp(ancestors: str) -> str:
    return "; ".join(
    (
        "default-src 'self'",
        # 'unsafe-inline' is the known weak point - see the module docstring.
        f"script-src 'self' 'unsafe-inline' {LEAFLET}",
        f"style-src 'self' 'unsafe-inline' {LEAFLET}",
        # No remote font origin: the app self-hosts nothing and downloads
        # nothing. 'self' covers a future woff2 in /static without reopening
        # the policy to a third party.
        "font-src 'self'",
        # data: for the canvas-rendered heat overlay; blob: for nothing yet,
        # and so deliberately absent.
        f"img-src 'self' data: {TILES} {LEAFLET}",
        "connect-src 'self'",
        "form-action 'self'",
        f"frame-ancestors {ancestors}",
        "base-uri 'self'",
        "object-src 'none'",
    )
)


# The default policy, for tests and for reading. The served value is built per
# request by `headers_for`, because the ancestor list is environment-dependent.
CSP = _csp("'none'")

# Two years, and `preload` is deliberately NOT set: preloading is a one-way
# door enforced by browser vendors, and this app has no domain of its own yet.
HSTS = "max-age=63072000; includeSubDomains"

BASE_HEADERS: Mapping[str, str] = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # This app asks for none of these. Saying so stops an injected script from
    # asking on our behalf and getting a prompt that looks like it came from us.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
}


def headers_for(scheme: str) -> dict[str, str]:
    """The headers to apply, given the scheme this request arrived over."""
    headers = dict(BASE_HEADERS)

    ancestors = frame_ancestors()
    if ancestors != "'none'":
        # An explicit ancestor list only means anything through CSP; leaving
        # `X-Frame-Options: DENY` alongside it would have the legacy header
        # veto the modern one and the preview would still be blank.
        headers["Content-Security-Policy"] = _csp(ancestors)
        headers.pop("X-Frame-Options", None)

    if scheme == "https":
        headers["Strict-Transport-Security"] = HSTS
    return headers
