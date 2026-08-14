from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
