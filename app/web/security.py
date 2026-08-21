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
- Google Fonts, split across `googleapis` (the stylesheet) and `gstatic` (the
  font files), which is the detail everyone gets wrong once;
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

**`Referrer-Policy: strict-origin-when-cross-origin`.** Without it, following a
collected-knowledge source link sends the full URL of the page it was on. Lake
slugs are not secret, but there is no reason to hand every cited site a
referrer trail of which waters this angler reads about.

**HSTS, only over https.** Sending it on plain http would be ignored anyway,
and setting it during local development would pin `localhost` to https in the
developer's browser - a genuinely annoying thing to undo.
"""

from __future__ import annotations

from collections.abc import Mapping

LEAFLET = "https://unpkg.com"
TILES = "https://*.arcgisonline.com https://server.arcgisonline.com"
FONTS_CSS = "https://fonts.googleapis.com"
FONTS_FILES = "https://fonts.gstatic.com"

CSP = "; ".join(
    (
        "default-src 'self'",
        # 'unsafe-inline' is the known weak point - see the module docstring.
        f"script-src 'self' 'unsafe-inline' {LEAFLET}",
        f"style-src 'self' 'unsafe-inline' {LEAFLET} {FONTS_CSS}",
        f"font-src 'self' {FONTS_FILES}",
        # data: for the canvas-rendered heat overlay; blob: for nothing yet,
        # and so deliberately absent.
        f"img-src 'self' data: {TILES} {LEAFLET}",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    )
)

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
    if scheme == "https":
        headers["Strict-Transport-Security"] = HSTS
    return headers
