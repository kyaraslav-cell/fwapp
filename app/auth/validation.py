"""What makes an email, a display name and a password acceptable.

Pure: every function takes strings and returns i18n **keys**, never sentences.
The form renders them through `t()`, so one rule produces the same message in
all three languages and the rules can be tested without a browser or a request.

The same functions run on the server for every submission. The client-side
copy in the template is a convenience that shortens the round trip; it is never
the thing that decides.
"""

from __future__ import annotations

import re
import unicodedata

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200
MAX_EMAIL_LENGTH = 254
MAX_NAME_LENGTH = 60

# Deliberately permissive. The full RFC 5322 grammar accepts addresses no
# provider will issue, and a strict-looking regex mostly succeeds at rejecting
# real people - the plus-addressed, the apostrophed, the non-ASCII. One @, a
# dot in the domain, no whitespace: anything past that is decided by whether
# the address actually receives mail, which a regex cannot know.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# The 20 most-used passwords, kept here rather than shipped as a file: it is a
# speed bump for the obvious cases, not a breach corpus. Anything serious needs
# a real k-anonymity check against a breach list, which needs a network call
# this app does not make.
_OBVIOUS = frozenset(
    {
        "password", "password1", "password123", "12345678", "123456789",
        "1234567890", "qwertyuiop", "qwerty123", "iloveyou", "admin123",
        "letmein123", "welcome123", "abc12345", "passw0rd", "football",
        "monkey123", "trustno1", "dragon123", "sunshine1", "princess1",
        "fishing123", "rybalka123",
    }
)


def normalise_email(raw: str) -> str:
    """Trim and lowercase. Storage and lookup both go through this.

    Case-folding the whole address is technically wrong - the local part is
    case-sensitive per RFC 5321 - and is what every mail provider does anyway.
    Being right here would mean Angler@ and angler@ could register twice and
    the owner would never work out why sign-in failed.
    """
    return unicodedata.normalize("NFKC", raw).strip().lower()


def normalise_name(raw: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(raw.split()))


def validate_email(raw: str) -> str | None:
    email = normalise_email(raw)
    if not email:
        return "auth.error.email_required"
    if len(email) > MAX_EMAIL_LENGTH:
        return "auth.error.email_too_long"
    if not _EMAIL.match(email):
        return "auth.error.email_invalid"
    return None


def validate_name(raw: str) -> str | None:
    name = normalise_name(raw)
    if not name:
        return "auth.error.name_required"
    if len(name) > MAX_NAME_LENGTH:
        return "auth.error.name_too_long"
    return None


def validate_password(password: str, email: str = "") -> str | None:
    """Length first, then the two failures that defeat length.

    No "must contain a symbol" rule. Composition rules push people to
    Password1! and are worse than a length floor - NIST SP 800-63B dropped
    them, and so does this.
    """
    if not password:
        return "auth.error.password_required"
    if len(password) < MIN_PASSWORD_LENGTH:
        return "auth.error.password_too_short"
    if len(password) > MAX_PASSWORD_LENGTH:
        return "auth.error.password_too_long"
    if password.lower() in _OBVIOUS:
        return "auth.error.password_obvious"
    # Only for a local part long enough to be a real clue. "a@b.co" would
    # otherwise ban every password containing the letter a.
    local = normalise_email(email).split("@")[0]
    if len(local) >= 4 and local in password.lower():
        return "auth.error.password_is_email"
    if len(set(password)) < 4:
        return "auth.error.password_repetitive"
    return None


def validate_password_confirmation(password: str, confirmation: str) -> str | None:
    if password != confirmation:
        return "auth.error.password_mismatch"
    return None


def validate_registration(
    email: str, name: str, password: str, confirmation: str
) -> dict[str, str]:
    """Every field checked, so the form comes back with all of its errors at once.

    Stopping at the first failure makes a three-field form take three round
    trips, which on a phone on a riverbank is how an account never gets made.
    """
    errors: dict[str, str] = {}
    for field, error in (
        ("email", validate_email(email)),
        ("name", validate_name(name)),
        ("password", validate_password(password, email)),
        ("confirmation", validate_password_confirmation(password, confirmation)),
    ):
        if error is not None:
            errors[field] = error
    return errors
