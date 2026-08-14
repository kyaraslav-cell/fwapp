# 08 — Development workflow for Claude Code

## Starting any session

1. Read `CLAUDE.md`.
2. Read the phase you are working in, in `docs/06-ROADMAP.md`.
3. Check `docs/adr/` for decisions already made. **Do not relitigate settled
   decisions** — if you disagree, write a new ADR superseding the old one.
4. Run `make check` before you start, so you know whether you inherited a green tree.

## Task loop

```
pick task from roadmap
  └─ branch:  phase-N/short-slug
       └─ write the test first, from the acceptance criteria
            └─ implement
                 └─ make check
                      └─ update roadmap checkbox
                           └─ PR
```

One task per branch. Small PRs. If a task turns out to require a decision not covered
by the docs, **stop and write an ADR** rather than deciding silently inside an
implementation.

## `make check`

```
make check   →  ruff · mypy --strict app/core app/rules app/features · pytest · migration check
```

Green before every PR. No exceptions.

## Testing rules

**Golden tests over fixture weather.** `tests/fixtures/weather/` holds real hourly
data pulled from the ERA5 archive for known dates at Pomocnia. Feature computation and
rule evaluation are tested against these, not against live API calls. **No test may
hit the network.**

**Purity tests.** `app/features/` and `app/rules/` must be importable and fully
exercisable with no database and no clock. A test that needs `freezegun` in those
packages indicates a design violation — time should have been a parameter.

**Property tests** (hypothesis) for the geometry: bearings are in 0–360, fetch never
exceeds the lake's maximum dimension, exposure is in −1..+1, a rotated lake produces
rotated bearings.

**The formula slots.** Until the owner supplies them, test against
`tests/fixtures/rules.fake.yaml`. That file's header must state in capitals that its
formulas are fabricated for testing and carry no angling meaning. Do not let a fake
formula leak into `config/`.

## Definition of done

A task is done when:

- [ ] The acceptance criteria in the roadmap are met
- [ ] Tests cover the behaviour, not just the lines
- [ ] `make check` is green
- [ ] No fishing constant has appeared in code (see law 1)
- [ ] Sample size is carried through any new number shown to a user (law 5)
- [ ] The roadmap checkbox is ticked in the same PR

## Migrations

Forward-only, numbered, never edited after merge. Each includes a data migration if
needed. Test that migrating an empty database and a populated one both succeed.

## When you are blocked on the owner

Two formulas are pending (see `docs/04-RULES-ENGINE.md`). If a task needs them:

1. Build the surrounding machinery completely
2. Wire the slot so that it raises `FormulaNotSuppliedError`
3. Test with the fixture formula
4. Note the block in the PR description
5. **Move on to the next task.** Do not guess, and do not silently substitute
   something plausible — a plausible wrong formula is worse than a loud missing one,
   because it will quietly poison a season of calibration data.

## Commit style

```
phase-2: add one-tap blank session logging

Blank sessions were two taps behind a menu; law 3 requires parity with
a productive session. Adds a primary-position control on the End screen.
```

State what changed and which principle or requirement drove it.

## Things that should make you stop and ask

- A requirement that implies overwriting a past prediction
- Any statistic that would exclude blank sessions
- Pressure to add a JS framework, a database server, or a message queue
- A suggestion to "just train a small model on the data"
- A depth recommendation that is not clamped to the zone's actual depth

Each of these breaks something structural. Raise it rather than working around it.
