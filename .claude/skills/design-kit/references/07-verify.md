# 07 — Verify: the artefact, or it did not happen

The single most expensive lesson in this project. Three times a change was
declared landed on the strength of a diff, and three times it had not landed.

> A green test suite says nothing about whether a fish is upside down.

## The rule

**The agent that made the change does not get the final word on whether it
landed.** Phase 7 dispatches the `design-verifier` subagent, which starts cold:
it sees the feature inventory and the chosen direction, and **not** your diff or
your reasoning. If it cannot find the change in a rendered artefact, the change
did not land.

This is not ceremony. Each of the three failures below was invisible to the
person who wrote it and obvious in a rendered frame.

## The three traps, so they are not re-entered

**1. The ripple that was invisible.** It faded linearly while spreading twentyfold,
so it was gone by 150ms and read as a flash. *The keyframes looked fine.* Fixed by
holding opacity and falling late.

**2. The filmstrip that measured nothing.** The ripple lives on `::after`, and a
pseudo-element has no node to set inline style on — so the first filmstrip
photographed eight identical frames of an animation that was running perfectly.
Pinning is now done by injecting a stylesheet rule.

**3. The screenshot that cancelled the motion.** Playwright's element screenshot
follows the element, which subtracts exactly the translation being filmed. Fixed
by measuring a fixed frame once and reusing it.

The generalisation: **a verification tool can be broken in the same direction as
the bug.** When a filmstrip shows no change, the first question is whether the
filmstrip works — not whether the animation does.

## What must be produced

| Tool | When | Passes when |
|---|---|---|
| `tools/design_sheet.py` | any visual change | before beside after, 6 pages × 2 widths, and the difference is visible to a stranger |
| `tools/waterline_filmstrip.py` | waterline, splash, surfacing, bite | frames differ across the strip, in the intended direction |
| `tools/animation_filmstrip.py` | any other motion | same |
| `tools/icon_sheet.py --compare` | any icon change | old beside new, and no two species share a tail wedge |
| `tools/site_audit.py` | always | **zero new** serious or critical violations |
| `tools/palette_check.py` | any colour change | every pair AA |

Plus, by hand at 390px, screen by screen: one primary action, in the thumb zone,
at 48px, on each of the five flow screens.

## The feature inventory — the part that stops a pretty regression

Phase 1 produced a list of every control, form and interactive behaviour on the
surface. Walk it. A redesign that breaks a working feature is worse than no
redesign, and CSS breaks features more often than anyone expects: a changed
stacking context, an element moved out of a form, a hit target covered by a
decorative overlay, a `pointer-events` that swallows a tap.

Specifically confirm, because these are the ones with teeth:

- [ ] a session can be started, tracked and **ended**
- [ ] a **blank** session ends as easily as one with catches (law 3)
- [ ] conditions and the map are reachable **during** an active session (rule 10)
- [ ] catch logging: species search in all three languages, weight and length sliders, bait, photo
- [ ] the day strip changes the map's scores
- [ ] favourite and soft-remove still work, per angler
- [ ] the language switcher still switches, and the layout survives the longest string
- [ ] sign-in, sign-out, and the 404/500 pages
- [ ] every number still carries its `n` (law 5)
- [ ] no raw score has appeared anywhere (rules 2 and 16)

## Anti-checks — ways this phase gets faked

Do not accept any of these as verification:

- "the CSS says `transform: translateY(-6px)`, so it animates" — read the diff, not the render
- "the screenshot looks right" — for **motion**, a screenshot is not evidence
- "the tests pass" — no test in this repo can see a colour or a direction of travel
- "it worked at 1440px" — the app is used at 390px
- "headless Chromium at 390px" — that is not a phone, and must not be reported as one

## What remains open even when this passes

**Nothing here is a real device.** Touch feel, whether the splash reads on a real
screen in daylight, and whether the palette survives actual sun are untested.
`docs/17 §9` already says so. Report it as open; do not let a clean filmstrip
imply a device check that did not happen.

## Delivering

Put the comparison **in front of the owner** — the sheet, not a description of
the sheet. The owner cannot download files (standing rule 12), so artefacts go
into the repository under `docs/design/` and are read on GitHub, or are shown
inline. Working output lives in `tools/design_shots/` and is gitignored; copy
across only the sheets worth keeping.

Then answer in the house style: what you did, what you could not do, what is
left. Nothing else.
