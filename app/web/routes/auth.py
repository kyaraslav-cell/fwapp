"""Register, sign in, sign out - with a password, or with Google.

Two rules shape everything here.

**The server decides.** The forms validate in the browser to shorten the round
trip, and every submission is validated again by the same pure functions in
`app.auth.validation`. Nothing is accepted because the page said it was fine.

**Wrong email and wrong password are the same answer.** Sign-in failures always
render `auth.error.bad_credentials`, never "no such account". Distinguishing
them turns the login form into an address-enumeration oracle, and the angler
gains nothing from the distinction.

Both forms are rate limited (`app.auth.throttle`), and the limit is consulted
**before** any password is hashed - the scrypt work is the expensive half and
spending it on an attempt we have already decided to refuse would leave the
denial-of-service half of the problem exactly where it was.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import google, throttle
from app.auth.service import (
    AccountDisabledError,
    EmailAlreadyRegisteredError,
    authenticate,
    register,
    sign_out,
    start_auth_session,
    upsert_google_user,
)
from app.auth.tokens import COOKIE_NAME as AUTH_COOKIE
from app.auth.tokens import SESSION_DAYS
from app.auth.validation import (
    MIN_PASSWORD_LENGTH,
    validate_email,
    validate_registration,
)
from app.web.deps import client_ip, get_db, templates

router = APIRouter(prefix="/auth")

SAFE_DEFAULT = "/"


def safe_next(raw: str | None) -> str:
    """Only ever redirect to a path on this app.

    `//evil.example` is a protocol-relative URL that browsers treat as absolute,
    so checking for a leading "/" alone is not enough - that is the classic
    open-redirect hole, and a sign-in page is exactly where it gets exploited.
    """
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return SAFE_DEFAULT
    return raw


def _secure_cookies(request: Request) -> bool:
    """Secure flag off on plain-HTTP localhost, on everywhere else.

    Hard-coding Secure=True would silently break `make dev` over http, and
    hard-coding False would ship a session cookie that a hotspot can read.
    """
    return request.url.scheme == "https"


def set_auth_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE,
        token,
        max_age=60 * 60 * 24 * SESSION_DAYS,
        httponly=True,
        secure=_secure_cookies(request),
        samesite="lax",
        path="/",
    )


def _render(
    request: Request,
    template: str,
    *,
    status_code: int = 200,
    **context: Any,
) -> Response:
    payload: dict[str, Any] = {
        "request": request,
        "active_nav": None,
        "google_enabled": google.is_configured(),
        "min_password_length": MIN_PASSWORD_LENGTH,
        "errors": {},
        # Substituted into the error string by `t()`. Kept separate from
        # `errors` so a key and its numbers stay independent of each other.
        "error_args": {},
        "values": {},
        "next": SAFE_DEFAULT,
    }
    payload.update(context)
    return templates.TemplateResponse(template, payload, status_code=status_code)


def _too_many(
    request: Request,
    template: str,
    decision: throttle.Decision,
    *,
    values: dict[str, str],
    target: str,
) -> Response:
    """One refusal, worded the same on both forms.

    429 rather than 401 on purpose: the credentials were never examined, so
    saying "wrong password" would be a lie the angler acts on by trying to
    remember a different one.
    """
    return _render(
        request,
        template,
        status_code=429,
        errors={"form": "auth.error.too_many"},
        error_args={"minutes": decision.retry_after_minutes},
        values=values,
        next=target,
    )


# --------------------------------------------------------------------------
# Password accounts
# --------------------------------------------------------------------------


@router.get("/register")
def register_form(request: Request, next: str = SAFE_DEFAULT) -> Response:
    return _render(request, "auth_register.html", next=safe_next(next))


@router.post("/register")
def register_submit(
    request: Request,
    email: str = Form(default=""),
    display_name: str = Form(default=""),
    password: str = Form(default=""),
    password_confirm: str = Form(default=""),
    next: str = Form(default=SAFE_DEFAULT),
    db: Session = Depends(get_db),
) -> Response:
    target = safe_next(next)
    values = {"email": email, "display_name": display_name}

    ip = client_ip(request)
    decision = throttle.check(db, throttle.REGISTER_RULES, ip=ip)
    if not decision.allowed:
        return _too_many(
            request, "auth_register.html", decision, values=values, target=target
        )

    errors = validate_registration(email, display_name, password, password_confirm)
    if errors:
        return _render(
            request,
            "auth_register.html",
            status_code=422,
            errors=errors,
            values=values,
            next=target,
        )

    try:
        user = register(db, email=email, display_name=display_name, password=password)
    except EmailAlreadyRegisteredError:
        # Said plainly. A registration form cannot hide which addresses exist -
        # it has to refuse the duplicate - so pretending otherwise would only
        # confuse the person who genuinely forgot they had signed up.
        return _render(
            request,
            "auth_register.html",
            status_code=409,
            errors={"email": "auth.error.email_taken"},
            values=values,
            next=target,
        )

    # Counted on the way out, not the way in: a submission rejected for a short
    # password is a typo, and rationing typos would punish the honest angler
    # while costing a script nothing.
    throttle.record(db, throttle.REGISTER, email=email, ip=ip)

    signed_in = start_auth_session(
        db, user, user_agent=request.headers.get("user-agent")
    )
    response = RedirectResponse(url=target, status_code=303)
    set_auth_cookie(response, request, signed_in.token)
    return response


@router.get("/login")
def login_form(request: Request, next: str = SAFE_DEFAULT) -> Response:
    return _render(request, "auth_login.html", next=safe_next(next))


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(default=""),
    password: str = Form(default=""),
    next: str = Form(default=SAFE_DEFAULT),
    db: Session = Depends(get_db),
) -> Response:
    target = safe_next(next)
    values = {"email": email}

    ip = client_ip(request)
    decision = throttle.check(db, throttle.LOGIN_RULES, email=email, ip=ip)
    if not decision.allowed:
        return _too_many(
            request, "auth_login.html", decision, values=values, target=target
        )

    # Shape only. A wrong-looking address gets the same generic answer as a
    # wrong password, so this check exists to catch the empty form, not to
    # report which field is at fault.
    if validate_email(email) is not None or not password:
        return _render(
            request,
            "auth_login.html",
            status_code=422,
            errors={"form": "auth.error.bad_credentials"},
            values=values,
            next=target,
        )

    try:
        user = authenticate(db, email=email, password=password)
    except AccountDisabledError:
        # Not counted. The password was right; the account is switched off, and
        # the person retrying is its owner wondering why.
        return _render(
            request,
            "auth_login.html",
            status_code=403,
            errors={"form": "auth.error.account_disabled"},
            values=values,
            next=target,
        )
    if user is None:
        throttle.record(db, throttle.LOGIN_FAIL, email=email, ip=ip)
        return _render(
            request,
            "auth_login.html",
            status_code=401,
            errors={"form": "auth.error.bad_credentials"},
            values=values,
            next=target,
        )

    # Four wrong guesses then the right one starts from zero again, so an
    # angler who fumbles a password on the bank is not locked out next week by
    # a counter that never emptied.
    throttle.clear_failures(db, email)

    signed_in = start_auth_session(
        db, user, user_agent=request.headers.get("user-agent")
    )
    response = RedirectResponse(url=target, status_code=303)
    set_auth_cookie(response, request, signed_in.token)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    sign_out(db, request.cookies.get(AUTH_COOKIE))
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(AUTH_COOKIE, path="/")
    return response


# --------------------------------------------------------------------------
# Google
# --------------------------------------------------------------------------


@router.get("/google")
def google_start(request: Request, next: str = SAFE_DEFAULT) -> Response:
    config = google.load_config()
    if config is None:
        return _render(
            request,
            "auth_login.html",
            status_code=503,
            errors={"form": "auth.error.google_unavailable"},
            next=safe_next(next),
        )

    state = google.new_state()
    response = RedirectResponse(
        url=google.authorization_url(config, state), status_code=303
    )
    # State and destination both ride in short-lived cookies rather than in the
    # `state` parameter: Google echoes `state` back verbatim, so anything put
    # in it is attacker-writable on the return leg.
    response.set_cookie(
        google.STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=_secure_cookies(request),
        samesite="lax",
        path="/auth",
    )
    response.set_cookie(
        "fishlog_oauth_next",
        safe_next(next),
        max_age=600,
        httponly=True,
        secure=_secure_cookies(request),
        samesite="lax",
        path="/auth",
    )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
) -> Response:
    target = safe_next(request.cookies.get("fishlog_oauth_next"))
    config = google.load_config()
    expected_state = request.cookies.get(google.STATE_COOKIE)

    def refuse(key: str, status_code: int) -> Response:
        response = _render(
            request,
            "auth_login.html",
            status_code=status_code,
            errors={"form": key},
            next=target,
        )
        response.delete_cookie(google.STATE_COOKIE, path="/auth")
        response.delete_cookie("fishlog_oauth_next", path="/auth")
        return response

    if config is None:
        return refuse("auth.error.google_unavailable", 503)
    if error or not code:
        # The angler pressed cancel on Google's screen, or Google refused.
        return refuse("auth.error.google_cancelled", 400)
    if not expected_state or state != expected_state:
        return refuse("auth.error.google_state", 400)

    try:
        identity = google.exchange_code(config, code)
    except google.GoogleAuthError:
        return refuse("auth.error.google_failed", 502)
    except Exception:
        # Network down, DNS, TLS, a proxy in the way. The sandbox this was
        # written in cannot reach Google at all (docs/10 §6), so this path is
        # the normal one there and must not present as a crash.
        return refuse("auth.error.google_unreachable", 502)

    if not identity.email_verified:
        # An unverified address would let anyone who can create a Google
        # account claiming an address walk into the account holding it.
        return refuse("auth.error.google_unverified", 403)

    try:
        user = upsert_google_user(db, identity)
    except AccountDisabledError:
        return refuse("auth.error.account_disabled", 403)

    signed_in = start_auth_session(
        db, user, user_agent=request.headers.get("user-agent")
    )
    response = RedirectResponse(url=target, status_code=303)
    set_auth_cookie(response, request, signed_in.token)
    response.delete_cookie(google.STATE_COOKIE, path="/auth")
    response.delete_cookie("fishlog_oauth_next", path="/auth")
    return response
