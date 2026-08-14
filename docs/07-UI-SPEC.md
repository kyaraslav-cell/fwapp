# 07 — UI specification

## The governing constraint

The owner will use this **on a bank, in the rain, in low light, with cold hands, on a
phone, possibly with no signal.**

If logging is awkward, he will not do it. If he does not log, there is no data. If
there is no data, the calibration loop never runs and the whole project degrades into
a weather website with extra steps.

**Logging ergonomics is therefore the highest-risk item in the entire build, not a
cosmetic concern.**

## Non-negotiables

- Offline-first. Log with no signal; sync later. Never lose an entry.
- One-thumb reachable. Primary actions in the bottom third of the screen.
- Minimum 48 px tap targets. Larger for the buttons pressed with wet hands.
- Dark mode default; high contrast; readable in direct sun and at dusk.
- Never make the owner type anything he already knows the app could know.
- **A blank session must be as fast to record as a good one.**

---

## Screens

### 1. Today *(landing)*

The answer, above the fold, without scrolling:

```
┌──────────────────────────────┐
│  POMOCNIA          Thu 13 Aug│
│                              │
│         7.4 / 10             │
│         WORTH GOING          │
│                              │
│  Best hours  05:20 – 08:40   │
│              19:10 – 20:50   │
│                              │
│  1. East weed edge      8.1  │  ← confidence dot: ●●●  n=23
│     W wind into this bank,   │
│     380 m fetch, food pushed │
│  2. North point         6.9  │  ← ●●○  n=8
│  3. South bay           4.2  │  ← ●○○  n=3  thin data
│                              │
│  Depth band   1.2 – 1.8 m    │
│  Phase        summer_stagnation
│                              │
│  [ ▶  START SESSION ]        │
└──────────────────────────────┘
```

Every zone score shows a **confidence indicator and its sample size**. A zone scored
from 3 sessions must not look like one scored from 90. Rules flagged `status:
hypothesis` are visually marked as unproven.

### 2. Session logging

The single most important flow in the app.

**Start** — one large button. Timestamps, captures GPS, pre-selects the nearest swim,
and snapshots all conditions automatically. *The owner never types weather.*

**During** — a species chip row (roach, bream, rudd, ide, carp, crucian, +other), then
a size slider. **Target: ~2 seconds per fish.** Running count and elapsed time always
visible. A "moved swim" button opens a new `session_leg`.

**End** — one button, then an optional 20-second reflection: what worked, what didn't,
free text or voice note. Skippable without guilt.

**Blank** — the End screen offers "Finished, no fish" as a first-class equal option.
Never buried, never apologetic. It counts fully in every statistic.

**Optional but high-value** — a water temperature field. A €5 thermometer reading
logged each session is what converts the water-temperature model from guessed to
fitted. Prompt for it, never require it.

### 3. Map

- Satellite basemap (Esri World Imagery), lake outline, zone polygons, swim pins
- Toggleable layers: zones, swims, today's scores as a heat overlay, wind arrow,
  free-draw annotations filtered by season or month
- **Draw mode** for sketching weed edges, drop-offs, where he fed, where fish topped —
  stored as GeoJSON so it stays queryable, never as a flattened image
- Tap a zone → its attributes, its history, its CPUE, its coverage
- Zone attribute editor, including **bank aspect** and **tree line height/side**

### 4. Outlook

Seven days. Per day: score, headline condition, the top zone, and *why it changes*.
Trend sparklines for pressure, water temperature and wind. Forecast confidence must
visibly decay with horizon — day 7 is not day 1.

### 5. Statistics

- CPUE by zone, by month, by thermal phase, by pressure regime, by wind direction
- **Coverage map** — hours fished per zone, with under-sampled zones highlighted
- Bait and tactic effectiveness
- Prediction vs outcome, per ruleset version
- Every chart states its `n`. No exceptions.

### 6. Calibration *(quiet, occasional)*

Weight proposals with their evidence, and an accept/reject decision. This is where
the owner stays in the loop — and where he learns something a black box would never
teach him.

---

## Design language

Utilitarian, legible, calm. Large type. Generous spacing. No decorative chrome
competing with the numbers. The interface should feel like a good instrument rather
than an app — closer to a depth sounder than a social feed.

Charts follow the project's data-visualisation conventions: one accent colour for the
active series, muted greys for context, no gratuitous gradients, and no colour
carrying meaning that is not also carried by position or label.
