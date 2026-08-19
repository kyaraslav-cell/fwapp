from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Lake(Base):
    __tablename__ = "lake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lon: Mapped[float] = mapped_column(Float, nullable=False)
    area_ha: Mapped[float | None] = mapped_column(Float)
    mean_depth_m: Mapped[float | None] = mapped_column(Float)
    max_depth_m: Mapped[float | None] = mapped_column(Float)
    outline_geojson: Mapped[str | None] = mapped_column(Text)
    outline_source: Mapped[str | None] = mapped_column(String)  # osm|circle_fallback
    # Where this water came from, and who put it there. `discovered` waters are
    # the ones the add-a-water flow created; `seed` is Pomocnia, which predates
    # it and keeps its committed outline.
    origin: Mapped[str] = mapped_column(String, nullable=False, default="seed")
    osm_type: Mapped[str | None] = mapped_column(String)  # node|way|relation
    osm_id: Mapped[int | None] = mapped_column(Integer)
    added_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))
    # Grid resolution actually used for this water. Stored because it depends on
    # the water's area: a cached grid and a live one must never disagree about
    # how big a cell is.
    grid_cell_m: Mapped[float | None] = mapped_column(Float)
    # pzw | commercial. NOT cosmetic: it is the segmentation key for every
    # CPUE aggregate. A stocked commercial water and a PZW lake produce fish
    # per hour on completely different scales, so pooling them into one
    # statistic would corrupt the only measurement the project exists to make
    # (law 3). See app/notebook/water_type.py.
    water_type: Mapped[str | None] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Europe/Warsaw")
    metar_station: Mapped[str | None] = mapped_column(String)
    metar_distance_km: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class Zone(Base):
    __tablename__ = "zone"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int] = mapped_column(Integer, ForeignKey("lake.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    polygon_geojson: Mapped[str | None] = mapped_column(Text)
    mean_depth_m: Mapped[float | None] = mapped_column(Float)
    bottom_type: Mapped[str | None] = mapped_column(String)
    weed_density: Mapped[int | None] = mapped_column(Integer)
    bank_aspect_deg: Mapped[float | None] = mapped_column(Float)
    tree_line_height_m: Mapped[float | None] = mapped_column(Float)
    access_notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WeatherHourly(Base):
    __tablename__ = "weather_hourly"
    __table_args__ = (UniqueConstraint("lake_id", "source", "ts_utc", "is_forecast"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int] = mapped_column(Integer, ForeignKey("lake.id"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    ts_utc: Mapped[str] = mapped_column(String, nullable=False)
    is_forecast: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    temperature_2m: Mapped[float | None] = mapped_column(Float)
    dewpoint_2m: Mapped[float | None] = mapped_column(Float)
    relative_humidity_2m: Mapped[float | None] = mapped_column(Float)
    pressure_msl: Mapped[float | None] = mapped_column(Float)
    wind_speed_10m: Mapped[float | None] = mapped_column(Float)
    wind_direction_10m: Mapped[float | None] = mapped_column(Float)
    wind_gusts_10m: Mapped[float | None] = mapped_column(Float)
    cloud_cover: Mapped[float | None] = mapped_column(Float)
    shortwave_radiation: Mapped[float | None] = mapped_column(Float)
    precipitation: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[str] = mapped_column(String, nullable=False)


class IngestGap(Base):
    __tablename__ = "ingest_gap"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    from_utc: Mapped[str] = mapped_column(String, nullable=False)
    to_utc: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Ruleset(Base):
    __tablename__ = "ruleset"

    version: Mapped[str] = mapped_column(String, primary_key=True)
    yaml: Mapped[str] = mapped_column(Text, nullable=False)
    parent: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class Prediction(Base):
    __tablename__ = "prediction"
    __table_args__ = (
        UniqueConstraint(
            "lake_id", "target_date", "horizon_days", "ruleset_version", "generated_at"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_date: Mapped[str] = mapped_column(String, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[str] = mapped_column(String, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(
        String, ForeignKey("ruleset.version"), nullable=False
    )
    features_version: Mapped[str] = mapped_column(String, nullable=False)
    inputs_hash: Mapped[str] = mapped_column(String, nullable=False)
    day_score: Mapped[float | None] = mapped_column(Float)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class FishSession(Base):
    __tablename__ = "session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int] = mapped_column(Integer, ForeignKey("lake.id"), nullable=False)
    # Who fished it. Nullable because every session logged before accounts
    # existed has no owner; the first account created claims them (see
    # app/auth/service.py). CPUE is never pooled across anglers for the same
    # reason it is never pooled across water types - skill is a larger source
    # of variance than the weather, so the average would be a different
    # measurement wearing the same name (law 3, ADR 0004).
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))
    zone_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("zone.id"))
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String)
    effort_minutes: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str | None] = mapped_column(String)
    rod_count: Mapped[int | None] = mapped_column(Integer)
    grid_cell: Mapped[str | None] = mapped_column(String)  # 'r12c34'
    grid_lat: Mapped[float | None] = mapped_column(Float)
    grid_lon: Mapped[float | None] = mapped_column(Float)
    is_mobile: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prediction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("prediction.id"))
    conditions_snapshot: Mapped[str | None] = mapped_column(Text)
    water_temp_measured_c: Mapped[float | None] = mapped_column(Float)
    water_clarity_cm: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    reflection: Mapped[str | None] = mapped_column(Text)
    is_blank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class SessionLeg(Base):
    __tablename__ = "session_leg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("session.id"), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("zone.id"))
    from_ts: Mapped[str] = mapped_column(String, nullable=False)
    to_ts: Mapped[str | None] = mapped_column(String)


class Catch(Base):
    __tablename__ = "catch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("session.id"), nullable=False)
    leg_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("session_leg.id"))
    species: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    weight_g: Mapped[int | None] = mapped_column(Integer)
    length_cm: Mapped[float | None] = mapped_column(Float)
    caught_at: Mapped[str | None] = mapped_column(String)
    bait: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String)


class Species(Base):
    __tablename__ = "species"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String, nullable=False)
    name_pl: Mapped[str] = mapped_column(String, nullable=False)
    scientific: Mapped[str | None] = mapped_column(String)
    family: Mapped[str | None] = mapped_column(String)
    scoring: Mapped[str] = mapped_column(String, nullable=False)  # primary|secondary|logged_only
    is_favourite: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shape: Mapped[str | None] = mapped_column(String)  # icon silhouette group
    color: Mapped[str | None] = mapped_column(String)  # icon tint, keeps shared shapes distinct
    typical_g: Mapped[int | None] = mapped_column(Integer)
    min_g: Mapped[int | None] = mapped_column(Integer)
    max_g: Mapped[int | None] = mapped_column(Integer)
    typical_cm: Mapped[float | None] = mapped_column(Float)
    min_cm: Mapped[float | None] = mapped_column(Float)
    max_cm: Mapped[float | None] = mapped_column(Float)


class SessionTactic(Base):
    __tablename__ = "session_tactic"

    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("session.id"), primary_key=True)
    groundbait: Mapped[str | None] = mapped_column(String)
    hookbaits: Mapped[str | None] = mapped_column(String)
    depth_fished_m: Mapped[float | None] = mapped_column(Float)
    distance_fished_m: Mapped[float | None] = mapped_column(Float)


class User(Base):
    """An account.

    `password_hash` is nullable on purpose: an account created through Google
    has never had a password, and inventing a random one to keep the column
    NOT NULL would make "sign in with a password" silently impossible to
    diagnose. `app.auth.passwords.verify_password` refuses a null hash rather
    than treating it as "no password needed".

    `google_sub` is Google's stable subject id, not the email. Google users can
    change the address on an account; the subject survives it, and matching on
    email would hand a stranger someone's notebook the day a recycled address
    is reissued.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String)
    google_sub: Mapped[str | None] = mapped_column(String, unique=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    last_login_at: Mapped[str | None] = mapped_column(String)
    is_disabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuthSession(Base):
    """One signed-in browser.

    Server-side rather than a signed cookie, because a signed cookie cannot be
    revoked: "sign out everywhere" after a lost phone has to delete something.
    Only the SHA-256 of the token is stored - see `app.auth.tokens`.
    """

    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    last_seen_at: Mapped[str | None] = mapped_column(String)
    revoked_at: Mapped[str | None] = mapped_column(String)
    user_agent: Mapped[str | None] = mapped_column(String)


class Job(Base):
    """One slow piece of work, queued and drained in the background.

    Adding a water means geocoding, a shoreline fetch that can take half a
    minute, a grid build, a year of pressure history and a research pass. None
    of that belongs in a request, and none of it may be lost if it fails - so
    each piece is a row here with a state, an attempt count and its last error.

    Deliberately a table and not a library: `docs/adr/0001` forbids an external
    queue, this app has one writer, and a job that survives a restart because it
    is in the same SQLite file as everything else is worth more here than
    throughput.
    """

    __tablename__ = "job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("lake.id"))
    kind: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When this job may next be picked up. Backoff is a timestamp rather than a
    # sleep: a sleeping worker is a worker that is not doing the other jobs.
    run_after: Mapped[str] = mapped_column(String, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String)
    finished_at: Mapped[str | None] = mapped_column(String)


class LoginAttempt(Base):
    """One sign-in failure, or one account creation, kept only long enough to
    rate-limit the next one.

    Deliberately *not* an audit log. Successful sign-ins are not recorded here
    (`user.last_login_at` already carries that) and rows are pruned past the
    longest rate-limit window, because a table of who tried to sign in from
    where, kept forever, is a liability in a database whose backup strategy is
    "copy the file" (`docs/05`).

    `email` is the address as typed, normalised. It is stored rather than a
    `user_id` because the address that matters most is one that has no account
    behind it - that is what someone enumerating addresses is doing.
    """

    __tablename__ = "login_attempt"
    __table_args__ = (Index("ix_login_attempt_kind_created", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "login_fail" or "register". Failures are cleared by a later success;
    # registrations are not, since the account they made still exists.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String)
    ip: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
