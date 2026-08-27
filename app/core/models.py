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
    outline_source: Mapped[str | None] = mapped_column(String)  # osm|circle_fallback|osm_line|none
    # The line a river or canal follows, when OSM has no polygon for it at all.
    # NOT an outline: it cannot be clipped into a grid, so these waters get no
    # zone overlay. It is what puts the water on the map instead of a blank
    # rectangle. See app/geo/outline.py:fetch_osm_course.
    course_geojson: Mapped[str | None] = mapped_column(Text)
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
    # How `water_type` was decided: `pzw_registry` (matched against the okreg's
    # published list, config/pzw/), or `angler` (answered on the add form).
    # Recorded because the two are not equally trustworthy and a later
    # correction needs to know which it is overriding.
    water_type_source: Mapped[str | None] = mapped_column(String)
    # OpenStreetMap's spelling, kept when the PZW registry supplies a different
    # one. `name` is what the permit prints and therefore what the app shows;
    # this is what the water is findable by, and keeping it is what makes a
    # wrong registry match visible instead of silent.
    name_osm: Mapped[str | None] = mapped_column(String)
    # The registry key this water matched, or None. Lets a re-run of the
    # extractor tell which waters were matched against an entry that has since
    # changed name.
    pzw_key: Mapped[str | None] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Europe/Warsaw")
    metar_station: Mapped[str | None] = mapped_column(String)
    metar_distance_km: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class AnglerLake(Base):
    """One angler's own relationship with one water: pinned, or put away.

    Per angler, never global. Two people share this database and a water one of
    them removes is very often a water the other is still fishing - Anhelina
    added Glinianki Szczesliwickie and has sessions on it. A global delete
    would take somebody else's water away, and with law 2 and law 3 in mind it
    would also orphan predictions and sessions that are evidence.

    `removed_at` is a soft delete for the same reason: the water, its
    predictions and anybody's sessions on it all survive. Only this angler's
    places list stops showing it, and they can put it back.
    """

    __tablename__ = "angler_lake"
    __table_args__ = (UniqueConstraint("user_id", "lake_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    lake_id: Mapped[int] = mapped_column(Integer, ForeignKey("lake.id"), nullable=False)
    is_favourite: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    removed_at: Mapped[str | None] = mapped_column(String)
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
    # SQLite indexes primary keys and unique constraints and nothing else, so
    # a foreign key is a full table scan until it is indexed by hand. These
    # three are the notebook's read paths: "my sessions on this water" runs on
    # every history page, and both catch lookups run once per session shown.
    __table_args__ = (Index("ix_session_lake_user", "lake_id", "user_id"),)

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
    __table_args__ = (Index("ix_session_leg_session", "session_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("session.id"), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("zone.id"))
    from_ts: Mapped[str] = mapped_column(String, nullable=False)
    to_ts: Mapped[str | None] = mapped_column(String)


class Catch(Base):
    __tablename__ = "catch"
    __table_args__ = (Index("ix_catch_session", "session_id"),)

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


class HiresGridCache(Base):
    """One day's finer heat-map cells for one large water.

    Written once a day by the `grid_hires` job (`app/jobs/handlers.py`),
    never per request - see `docs/09-BACKLOG.md §19c`. Keyed by lake AND date,
    not lake alone: without `for_date` a still-cached yesterday would answer
    for today the moment the new day's job has not run yet, which is exactly
    the kind of stale-read-presented-as-current law 4 exists to rule out.

    `payload_json` holds the whole `/lake/{slug}/grid` response body, so the
    route that serves it does no recomputation at all - it is a cache, not a
    second scoring path that could drift from the live one.
    """

    __tablename__ = "hires_grid_cache"
    __table_args__ = (UniqueConstraint("lake_id", "for_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int] = mapped_column(Integer, ForeignKey("lake.id"), nullable=False)
    for_date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD, Europe/Warsaw
    cell_m: Mapped[float] = mapped_column(Float, nullable=False)
    wind_dir: Mapped[float] = mapped_column(Float, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[str] = mapped_column(String, nullable=False)


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


class WaterFact(Base):
    """One publicly documented claim about one water, and the page it came from.

    Its own table, never `weather_hourly` and never a `derived_*` table. Those
    two are records of what was measured and what was computed from
    measurements; this is a record of what somebody on the internet wrote, which
    is a different kind of thing and must not be mixed into either (law 4).

    **Nothing here feeds the score.** ADR 0005 §2 allows collected facts to feed
    terms the engine already has, but only once a human has confirmed them -
    `verified_by_owner`. An unconfirmed claim reaching the ranking would make a
    calibration miss unattributable, which is the one failure the whole
    calibration loop exists to avoid.

    Refreshing sets `superseded_at` on the old rows rather than updating them,
    so a fact that changed can still be told from a fact that was withdrawn.

    `source_ok`: 1 the URL answered, 0 it returned 404/410, NULL never checked
    (no network, or the check itself failed). NULL is not evidence either way.
    """

    __tablename__ = "water_fact"
    __table_args__ = (Index("ix_water_fact_lake_topic", "lake_id", "topic"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lake_id: Mapped[int] = mapped_column(Integer, ForeignKey("lake.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String)
    source_ok: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    # NULL is a row written before translation existed - `app/intel/service.py`
    # reads that as "en". Nullable rather than NOT NULL with a default because
    # `app/core/migrate.py` only ever ADDs nullable columns to an existing
    # SQLite table; a NOT NULL column with no inline DEFAULT breaks that ALTER
    # on a table that already has rows, which this one does.
    lang: Mapped[str | None] = mapped_column(String)
    # Which model said it, so an answer can be attributed after the default
    # model id has moved on.
    model: Mapped[str] = mapped_column(String, nullable=False)
    collected_at: Mapped[str] = mapped_column(String, nullable=False)
    superseded_at: Mapped[str | None] = mapped_column(String)
    verified_by_owner: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
