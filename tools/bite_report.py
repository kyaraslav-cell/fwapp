"""Run the whole three-factor model against this lake's real weather and print it.

CLAUDE.md: produce the artefact and look at it. A model that has only ever been
unit-tested is a model nobody has seen behave. This runs the real modules over
the real ingested series and prints what they say, including which factor is
holding the bite back and how much the answer deserves to be believed.

    python tools/bite_report.py                     # from the database
    python tools/bite_report.py --sweep             # behaviour across water temps
    python tools/bite_report.py --species bream

Exits non-zero when the model refuses to answer, which is a legitimate outcome
and not a crash: too few hours of weather, or a threshold still owed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.core.config import CONFIG_DIR  # noqa: E402
from app.features import oxygen as ox  # noqa: E402
from app.features import stability as stab  # noqa: E402
from app.features import water_temp as wt  # noqa: E402
from app.rules import bite  # noqa: E402

RULESET = yaml.safe_load((CONFIG_DIR / "rules.v0.4.yaml").read_text(encoding="utf-8"))


def load_series(slug: str) -> tuple[list[wt.AirSample], list[stab.Sample], list[stab.Sample]]:
    """Weather out of the database. The only impure function here."""
    from app.core.db import session_scope
    from app.core.models import Lake, WeatherHourly

    air: list[wt.AirSample] = []
    pressure: list[stab.Sample] = []
    air_t: list[stab.Sample] = []
    with session_scope() as db:
        lake = db.query(Lake).filter(Lake.slug == slug).one()
        rows = (
            db.query(WeatherHourly)
            .filter(WeatherHourly.lake_id == lake.id)
            .order_by(WeatherHourly.ts_utc)
            .all()
        )
        for r in rows:
            ts = dt.datetime.fromisoformat(r.ts_utc)
            if r.temperature_2m is not None:
                air.append(
                    wt.AirSample(ts, r.temperature_2m, r.dewpoint_2m,
                                 r.shortwave_radiation, r.wind_speed_10m)
                )
                air_t.append(stab.Sample(ts, r.temperature_2m))
            if r.pressure_msl is not None:
                pressure.append(stab.Sample(ts, r.pressure_msl))
    return air, pressure, air_t


def sweep(species: str) -> int:
    """Behaviour across water temperature, with and without wind on the spot."""
    responses = RULESET["species_response"]
    entry = responses.get(species) or {}
    t_opt = entry.get("t_opt_c")
    if t_opt is None:
        print(f"no sourced optimum for {species}", file=sys.stderr)
        return 2

    print(f"\n  {species}: optimum {t_opt} C, confidence {entry.get('confidence')}")
    print("  T_water   DO mg/L   oxygen   temp    bite   bite+wind(5 m/s)")
    for t in range(8, 33, 2):
        calm = ox.estimate(float(t), 0.0, 0.0, RULESET["oxygen"])
        windy = ox.estimate(float(t), 5.0, 0.6, RULESET["oxygen"])
        f_o2 = ox.oxygen_term(calm.dissolved_mgl, RULESET["oxygen"]["thresholds"]) or 0.0
        f_o2w = ox.oxygen_term(windy.dissolved_mgl, RULESET["oxygen"]["thresholds"]) or 0.0
        f_t, _ = bite.temperature_factor(float(t), species, RULESET)
        f_t = f_t or 0.0
        b = bite.combine(1.0, f_o2, f_t, None, 1.0, RULESET["bite_when"])
        bw = bite.combine(1.0, f_o2w, f_t, None, 1.0, RULESET["bite_when"])
        print(f"   {t:4d}     {calm.dissolved_mgl:6.2f}    {f_o2:5.2f}   {f_t:5.2f}   "
              f"{b:5.2f}      {bw:5.2f}")
    print("\n  (pressure held at 1.0 so the other two are visible)")
    return 0


def report(slug: str, species: str) -> int:
    air, pressure, air_t = load_series(slug)
    if not air:
        print("no weather in the database - run the ingest first", file=sys.stderr)
        return 2

    now = max(s.ts for s in air)
    print(f"\n  Lake {slug}, model v{RULESET['version']}, as of {now:%Y-%m-%d %H:%M} UTC")
    print(f"  {len(air)} hourly rows on record\n")

    # --- the 72-hour window -------------------------------------------------
    scfg = RULESET["stability"]
    hours = int(scfg["lookback_hours"])
    p_stats = stab.summarise(pressure, now, hours)
    t_stats = stab.summarise(air_t, now, hours)
    stability = stab.stability_index(p_stats, t_stats, scfg)
    stable_days = stab.consecutive_stable_days(pressure, air_t, now, scfg)

    print(f"  Previous {hours} h")
    print(f"    pressure   {p_stats.minimum:.1f} - {p_stats.maximum:.1f} hPa "
          f"(range {p_stats.span:.1f}), coverage {p_stats.coverage:.0%}")
    print(f"    air temp   {t_stats.minimum:.1f} - {t_stats.maximum:.1f} C "
          f"(range {t_stats.span:.1f}), coverage {t_stats.coverage:.0%}")
    print(f"    stability  {stability if stability is None else f'{stability:.2f}'}"
          f"   consecutive settled days: {stable_days}"
          f"  (ideal {scfg['ideal_consecutive_stable_days']})")

    # --- water temperature and oxygen --------------------------------------
    wcfg = RULESET["water_temp"]
    est = wt.estimate(air, now, wcfg, float(wcfg["mean_depth_m"]),
                      int(wcfg["spin_up_hours"]), float(wcfg["min_coverage_ratio"]))
    if not est.available or est.celsius is None:
        print(f"\n  Water temperature unavailable (coverage {est.coverage:.0%})")
        return 1
    trend = est.trend_24h_c
    print(f"\n  Water temperature (MODELLED, not measured): {est.celsius:.1f} C"
          f"   24 h trend {trend:+.2f} C" if trend is not None else "")

    wind_now = next((s.wind_ms for s in reversed(air) if s.wind_ms is not None), 0.0) or 0.0
    o2 = ox.estimate(est.celsius, wind_now, 0.5, RULESET["oxygen"])
    print(f"  Oxygen: {o2.dissolved_mgl:.2f} mg/L  "
          f"(ceiling {o2.saturation_mgl:.2f}, demand {o2.respiration_mgl:.2f}, "
          f"wind puts back {o2.reaeration_mgl:.2f})")

    # --- pressure norm ------------------------------------------------------
    p_norm = stab.pressure_norm(pressure, RULESET["pressure_norm"])
    p_now = pressure[-1].value if pressure else None
    day_ago = now - dt.timedelta(hours=24)
    p_24 = next((s.value for s in reversed(pressure) if s.ts <= day_ago), None)
    if p_norm is None:
        print(f"\n  Pressure norm: UNAVAILABLE - only {len(pressure)} h of history, "
              f"{RULESET['pressure_norm']['min_samples_hours']} h required")

    # --- the assessment -----------------------------------------------------
    assessment = bite.assess(
        RULESET, species, est.celsius, o2, p_now, p_norm, p_24,
        stability, stable_days, min(p_stats.coverage, t_stats.coverage),
    )
    print(f"\n  {'-' * 62}")
    for f in assessment.factors:
        shown = "  --  " if f.value is None else f"{f.value:.2f}"
        print(f"    {f.name:<12} {shown}   {f.detail}")
    print(f"  {'-' * 62}")

    if not assessment.available:
        print(f"\n  NO SCORE. Missing: {', '.join(assessment.unavailable)}")
        print("  This is the model refusing rather than guessing - see law 4.\n")
        return 1

    print(f"\n  Bite index {assessment.index:.2f}   limiting factor: {assessment.limiting}")
    print(f"  Confidence {assessment.confidence:.2f}"
          if assessment.confidence is not None else "  Confidence unavailable")
    print()
    return 0



def demo_series() -> tuple[list[wt.AirSample], list[stab.Sample], list[stab.Sample]]:
    """The source video's own scenario, hour by hour, as a fixture.

    Wednesday and Thursday are the heatwave it describes (30-32 C), Friday
    onward is the break it says switched the fish back on (25 day / 14 night),
    and pressure falls toward the norm across the week exactly as the video
    reads it off the forecast. Clearly synthetic - the point is not to invent
    data but to ask whether this model reaches the same conclusion the angler
    did on the water.
    """
    import math
    days = [
        # Three days of prior heatwave so the 72 h spin-up is real rather than
        # an artefact of the fixture starting on Wednesday.
        ("Sun-", 31.0, 19.0, 1026.0),
        ("Mon-", 32.0, 20.0, 1026.0),
        ("Tue-", 32.0, 20.0, 1025.0),
        ("Wed", 32.0, 20.0, 1024.0),
        ("Thu", 31.0, 19.0, 1021.0),
        ("Fri", 25.0, 14.0, 1017.0),
        ("Sat", 24.0, 13.0, 1015.0),
        ("Sun", 24.0, 13.0, 1014.0),
    ]
    start = dt.datetime(2026, 7, 15, 0, 0, tzinfo=dt.UTC)
    air: list[wt.AirSample] = []
    pres: list[stab.Sample] = []
    air_t: list[stab.Sample] = []
    for d, (_, hi, lo, p) in enumerate(days):
        for h in range(24):
            ts = start + dt.timedelta(days=d, hours=h)
            # diurnal sine, coolest at 04:00, warmest at 16:00
            frac = (1 - math.cos((h - 4) / 24 * 2 * math.pi)) / 2
            temp = lo + (hi - lo) * frac
            sun = max(0.0, 850 * math.sin(max(0.0, (h - 5) / 14) * math.pi))
            air.append(wt.AirSample(ts, temp, temp - 7.0, sun, 4.0))
            air_t.append(stab.Sample(ts, temp))
            pres.append(stab.Sample(ts, p + 0.6 * math.sin(h / 24 * 2 * math.pi)))
    return air, pres, air_t


def demo(species: str) -> int:
    """Replay the video's week and print what the model says on each morning."""
    air, pres, air_t = demo_series()
    scfg = RULESET["stability"]
    wcfg = RULESET["water_temp"]
    norm = 1013.0   # stand-in: five days is far too little history for a real norm

    print(f"\n  Replaying the source video's week for {species}")
    print("  (heatwave Wed-Thu 30-32 C, breaking to 25/14 from Friday;")
    print("   pressure falling toward the norm all week)\n")
    print("   day    water C   DO mg/L   press   O2    temp   stab  days  BITE  limiting")

    for offset, label in enumerate(["Wed", "Thu", "Fri", "Sat", "Sun"]):
        d = offset + 3   # skip the three spin-up days
        now = dt.datetime(2026, 7, 15, 6, 0, tzinfo=dt.UTC) + dt.timedelta(days=d)
        est = wt.estimate(air, now, wcfg, float(wcfg["mean_depth_m"]),
                          int(wcfg["spin_up_hours"]), 0.0)
        if est.celsius is None:
            print(f"   {label}    (not enough spin-up yet)")
            continue
        o2 = ox.estimate(est.celsius, 4.0, 0.6, RULESET["oxygen"])
        p_now = next(s.value for s in reversed(pres) if s.ts <= now)
        p24 = next((s.value for s in reversed(pres)
                    if s.ts <= now - dt.timedelta(hours=24)), None)
        st = stab.stability_index(stab.summarise(pres, now, int(scfg["lookback_hours"])),
                                  stab.summarise(air_t, now, int(scfg["lookback_hours"])),
                                  scfg)
        sd = stab.consecutive_stable_days(pres, air_t, now, scfg)
        a = bite.assess(RULESET, species, est.celsius, o2, p_now, norm, p24, st, sd, 1.0)
        vals = {f.name: f.value for f in a.factors}
        idx = "  --  " if a.index is None else f"{a.index:.2f}"
        stx = " -- " if st is None else f"{st:.2f}"
        print(f"   {label}     {est.celsius:5.1f}    {o2.dissolved_mgl:6.2f}   "
              f"{vals['pressure']:.2f}   {vals['oxygen']:.2f}  {vals['temperature']:.2f}  "
              f"{stx}   {sd}   {idx}  {a.limiting or ''}")
    print("\n  The video's angler fished Friday to Sunday and had 17 fish.\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="pomocnia")
    ap.add_argument("--species", default="roach")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="replay the source video's week through the model")
    args = ap.parse_args()
    if args.sweep:
        return sweep(args.species)
    if args.demo:
        return demo(args.species)
    return report(args.slug, args.species)


if __name__ == "__main__":
    raise SystemExit(main())
