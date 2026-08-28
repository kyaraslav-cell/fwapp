# 01 — The constraints, and what breaks if you ignore them

Distilled from `CLAUDE.md`, `docs/10-SESSION-HANDOVER.md §2`, `docs/17` and
`docs/18b`. Each row says what happens when the constraint is broken, because a
constraint without a consequence gets argued away.

## Hard — breaking these destroys something

| Constraint | Breaks |
|---|---|
| Server-rendered Jinja2 + HTMX. No build step, no SPA, no npm. | ADR 0001, standing rule 1. The owner considered React and chose against it. |
| Colours are re-pointed in the **alias** layer, never redefined there. | 268 declarations consume the alias names. Redefining inside the alias block forks the palette silently and `tools/palette_check.py` stops describing the real app. |
| Every foreground/ground pair passes WCAG AA. | `tests/test_palette.py` fails the suite. Two contrast failures sat in the nightly audit for weeks before this gate existed. |
| No fishing threshold in code or CSS. | Law 1. It belongs in `config/rules.v*.yaml`. A colour band boundary that encodes "good day" is a fishing threshold. |
| Never a raw score; colour band only. Never a number the data cannot support. | Standing rules 2 and 16. |
| Green good, red bad, everywhere. | Standing rule 3. |
| Sample size travels with every number. | Law 5. A zone from 3 sessions must not look like a zone from 90. |
| Species icons: per-species geometry, tail alone identifies the fish, curved forms only. | `CLAUDE.md` icon rules. `tests/test_species_seed.py` catches the wiring, not the drawing. |
| Blank sessions are data and are never filtered out. | Law 3. |
| Nothing is ever deleted; removal is soft, favourites are per angler. | Standing rule 18 — there is a real second user with open sessions. |
| One sentence under a control, never a paragraph. | Standing rule 14. If it needs more explaining, the control is wrong. |
| Rebuild the container at the end of any change touching code. | Standing rule 20. The image holds a frozen copy of `app/`; editing a file changes nothing the public URL serves. |

## Field constraints — these decide layout, not taste

The app is read at a waterside, on a phone, in daylight, on bad signal, often
one-handed with the other hand on a rod.

| Constraint | Consequence |
|---|---|
| **Light ground.** | Sunlight collapses perceived contrast; a light matte ground is what survives it. `docs/17 §9` refused dark mode for this reason, not aesthetics. Of the ten reference sites only screen.studio is dark, and it is a desktop video editor. |
| **Thumb zone.** | Primary actions in the bottom third, biased toward the holding hand. Destructive actions out of thumb reach. |
| **48px touch targets.** | 44×44 is Apple's floor, 48×48 Google's. Use 48. The running-session float is currently 44. |
| **One primary action per screen.** | Everything else behind a control. This is standing rule 14 applied to layout. |
| **Weight is a feature.** | Every kilobyte is downloaded on a riverbank. This is why `docs/17 §5` crops and cools images at build time rather than in CSS, and why the hero is 4.0KB on phone. |
| **No long scrolling, no video, no heavy animation in-app.** | Owner's brief. Motion is `transform`/`opacity` only, so it can never force layout. |

## The two verification rules

These are the most expensive lines in the project.

1. **Motion cannot be checked from a screenshot or by reading your own
   keyframes.** Use `tools/animation_filmstrip.py` or
   `tools/waterline_filmstrip.py`. Three separate traps have already been hit:
   an opacity curve that made a ripple invisible by 150ms; a filmstrip that
   photographed eight identical frames because a pseudo-element has no node to
   set inline style on; and Playwright's element screenshot following the
   element, cancelling the very translation being filmed.
2. **Visual design cannot be checked from your own diff.** Render it. Compare old
   and new side by side. Put the comparison in front of the owner rather than
   describing it.

## Live decisions — these supersede `docs/17`

From `docs/18b-DECISIONS.md`, taken 2026-08-28:

- **D1.** Waterline (navy / pale water / reed green) is **replaced**, not
  refined. What survives the replacement is architecture, not taste: the
  token/alias two-layer structure, the AA gate, traffic-light bands, a light
  ground. The waterline *element* is optional — cheap to keep, no obligation.
- **D2.** Two surfaces, two treatments, one palette and one typeface. `/welcome`
  takes the marketing register; the app screens take the Excalidraw register —
  the only *application* among the reference sites, and the only one with zero
  raster images.
- **D3.** A full custom variable typeface, body and headings. This reverses
  `docs/17 §2`, whose claim that a webfont "could not be subsetted" was wrong.

## Two owner slots that are still empty

`FORMULA_PRESSURE_DEPTH` and `FORMULA_WIND_ZONE` are **not delivered**. Do not
guess at them, and do not let a design decision depend on their output. If a
visualisation needs them, build the surrounding machinery and leave the evaluator
raising `FormulaNotSuppliedError`.
