# 01 — Product specification

## One sentence

A always-on web app that watches the weather over one small lake, works out what that
weather does to the water in each part of that lake, tells the angler where and when
to fish, and then checks itself against what he actually caught.

## Who

A single angler, bank-fishing Jezioro Pomocnia (52.5431 N, 20.6762 E), April to
October, for roach, bream, rudd and ide. Built by the owner, for the owner, with
multi-lake and multi-user structurally possible later but not built now.

## The honest value proposition

This is **not** an oracle. Weather explains a modest fraction of variance in coarse
fishing; season, water temperature, swim choice and bait explain more.

What the app can honestly deliver:

1. **A memory that beats human recall.** Every session, every condition, every
   result, queryable. This alone justifies the build.
2. **A filter.** Stop wasting good days; identify days that are probably not worth
   the drive.
3. **A hypothesis tester.** Turn "I think roach feed better on a falling glass" into
   a number, measured against your own logs, on your own water.

If at any point the design implies more certainty than the data supports, the design
is wrong.

## Goals

- G1 — Collect weather continuously and without supervision, from the day it is
  switched on, plus backfill of historical years.
- G2 — Derive the features that actually matter: pressure trends, modelled water
  temperature, per-zone wind exposure, per-zone sun and shade, oxygen proxy.
- G3 — Produce a daily output: go/no-go with best hours, ranked zones with reasons,
  target depth band and tactics hint.
- G4 — Produce a 7-day outlook so sessions can be planned.
- G5 — Capture sessions in under 60 seconds on a phone, on a bank, in the rain,
  offline.
- G6 — Close the loop: measure predictions against outcomes and propose weight
  changes for human approval.

## Non-goals (v1)

- Machine learning. At 30–60 sessions a year, any model is memorising noise. The
  engine is a transparent rule set with human-approved weight adjustment.
- Ice fishing.
- Boat fishing positions.
- Predator scoring (pike, perch, catfish, eel are logged, not scored).
- Multi-user accounts, social features, sharing.
- Native mobile apps. A PWA covers it.

## Success criteria

The project has succeeded if, after one full season:

- **S1** — Every session is logged, including blanks. If logging compliance drops
  below ~90%, the UI has failed and nothing else matters.
- **S2** — Calibration can answer "did the ranking beat picking a zone at random?"
  with a number and a confidence interval.
- **S3** — At least one rule has been changed or killed on the evidence of the
  owner's own data. That is the loop working.

## Scope boundary: what makes a zone "better"

Explicitly, the ranking answers: *given today's weather and this lake's geometry,
which zones are most likely to hold feeding cyprinids in the next 24 hours.*

It does not attempt to model: fishing pressure from other anglers, stocking events,
spawning behaviour (though close season is flagged), or bait quality.
