"""Every runtime setting the app reads must have a way into the container.

The dead man's switch sat in `.env` for a day pinging nobody, because
`docker-compose.yml` did not list `FISHLOG_HEALTHCHECK_URL` in its `environment`
block. `.env` is not copied into the image - the Dockerfile takes only `app/`
and `config/` - so that block is the *single* path a variable has into the
container. Absent from it, the app read an empty string, concluded monitoring
was switched off, and said nothing, while the same URL pinged by hand from the
host worked perfectly.

That failure is silent by construction and applies to every optional feature
here: a missing passthrough is indistinguishable from "the owner did not
configure it". So this test enumerates what the code actually reads and forces
each name to be either wired up or deliberately exempted with a reason.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]

# Names that legitimately never travel through compose. Each needs a reason -
# an exemption without one is how the next silent failure gets waved through.
EXEMPT = {
    "FISHLOG_DB_PATH": "set in the Dockerfile, pointing at the mounted volume",
    "FISHLOG_MEDIA_DIR": "derived from FISHLOG_DB_PATH when unset",
    "FISHLOG_HOST": "`make dev` only; uvicorn's bind is in the image CMD",
    "FISHLOG_PORT": "`make dev` only; the published port is in compose's ports:",
    "FISHLOG_FRAME_ANCESTORS": "dev-container preview panes only - never on a deployment",
    "FISHLOG_RULESET": "the active ruleset is chosen in the database, not the environment",
}


def _read_by_app() -> set[str]:
    names: set[str] = set()
    for path in (REPO / "app").rglob("*.py"):
        names |= set(re.findall(r"FISHLOG_[A-Z0-9_]+", path.read_text(encoding="utf-8")))
    return names


def _passed_by_compose() -> set[str]:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    env = compose["services"]["fishlog"].get("environment") or {}
    return set(env)


def test_every_setting_the_app_reads_can_reach_the_container() -> None:
    missing = _read_by_app() - _passed_by_compose() - set(EXEMPT)
    assert not missing, (
        "these are read by app/ but cannot reach the container: "
        f"{sorted(missing)}. Add them to docker-compose.yml's environment block, "
        "or to EXEMPT here with the reason they never travel. Setting one in .env "
        "alone does nothing - .env is not copied into the image."
    )


def test_the_healthcheck_url_is_wired() -> None:
    """The specific regression. Named so a failure says what broke."""
    assert "FISHLOG_HEALTHCHECK_URL" in _passed_by_compose()


def test_optional_settings_default_to_empty_rather_than_refusing_to_start() -> None:
    """`${VAR:-}`, not `${VAR}`.

    Without the `:-`, compose refuses to start the whole app whenever one
    optional variable is unset, which turns every optional feature into a hard
    requirement for running at all.
    """
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    env = compose["services"]["fishlog"]["environment"]
    bad = [k for k, v in env.items() if isinstance(v, str) and re.fullmatch(r"\$\{[A-Z0-9_]+\}", v)]
    assert not bad, f"these would block startup when unset: {bad} - use ${{NAME:-}}"


def test_exemptions_carry_a_reason() -> None:
    assert all(reason.strip() for reason in EXEMPT.values())
