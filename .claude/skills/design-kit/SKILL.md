---
name: design-kit
description: Design or redesign a complete visual system for this app - palette, typography, adaptive layout, motion and assets - without breaking a working feature. Use when asked to redesign, restyle, re-skin, "make it look better", change the palette or typeface, build a design system, produce icons or images for the UI, or when a new surface needs to look like the rest of the app. Runs a gated workflow: audit, direction, tokens, adaptive skeleton, assets, implementation, verification. Not for a one-off CSS tweak.
---

# design-kit

A workflow for designing this application. Not a style. The style is decided in
phase 2 by the owner; everything before it exists to make that decision cheap,
and everything after it exists to stop the decision being silently broken.

## Why this exists

Three failures have already cost this project real rework, and all three are
process failures rather than taste failures:

1. **The fish pin shipped diving tail-first three times.** Motion cannot be
   checked by reading your own keyframes.
2. **The species icons were declared "redrawn" three times** and still read as
   one recoloured shape. Visual design cannot be checked from your own diff.
3. **The first reveal pass blanked the top of the home page** — content already
   on screen was hidden waiting for an observer that had not arrived.

Every one was caught by *rendering the thing and looking at it*, and none by a
green test suite. That is the spine of this workflow.

A fourth failure mode is specific to redesigns: **a redesign that quietly breaks
a feature is worse than no redesign.** Phase 1 and phase 7 exist for that.

## The rule that outranks the rest

> **The agent that made a change may not be the only one that says it landed.**

Phase 7 dispatches a `design-verifier` subagent that has not seen your reasoning
and cannot see your diff. If it cannot find the change in a rendered artefact, the
change did not land — regardless of how certain you are.

---

## Phase 0 — Ground

Read, in this order. Do not skip on the belief that you remember them.

| | |
|---|---|
| `CLAUDE.md` | the five laws; the icon rules; the two verification rules |
| `docs/17-DESIGN-SYSTEM.md` | the system as built, including the §2 correction |
| `docs/18-DESIGN-TOOLING-RESEARCH.md` | why the tools are the tools |
| `docs/18b-DECISIONS.md` | the owner's live decisions — **these supersede `docs/17` where they conflict** |
| `references/01-constraints.md` | the non-negotiables distilled, and what breaks if you ignore them |

Then inventory the real surface — routes, templates, and the token graph:

```bash
ls app/web/templates/
grep -c ';' app/web/static/style.css
grep -n '^\s*--' app/web/static/style.css | head -60
```

State the surface you are designing before you design it. "The app" is not a
surface. `docs/18b` D2 splits this into two: the **landing page** (`/welcome`)
and the **in-app screens**. They get one palette and one typeface, and different
densities, asset budgets and motion budgets. Never treat them as one job.

## Phase 1 — Audit what exists · subagent

Dispatch the **`design-auditor`** subagent. It is read-only on product source and
returns findings plus a written inventory. Do not audit and redesign in the same
head; you will rationalise what you were already going to do.

It runs the installed `improve-ui` and `web-design-guidelines` skills, and reads
`reports/site_audit/` for what the nightly sweep already knows.

Output required before phase 2:

- every route and template in the surface, and which are reachable in the five-screen flow
- the token graph: palette layer, alias layer, and which declarations consume which
- the current findings, most severe first
- **the feature inventory** — every control, form and interactive behaviour that must still work afterwards. This is the checklist phase 7 tests against.

## Phase 2 — Direction · the gate

**No CSS is touched in this phase.** This is where redesigns are cheap to change
and where the last one spent its rework.

Read `references/02-direction.md`. Produce **three** directions as mockups via the
`design` canvas skill — artboards, not prose, not a description of a mockup. Each
direction states its palette, its type pairing, its density and its one signature
element.

Put them in front of the owner and **stop**. Do not proceed on your own reading
of which is best. If the owner picks nothing, that is an answer: ask what is
wrong with all three rather than producing a fourth unprompted.

Record the choice in `docs/18b-DECISIONS.md` before continuing.

## Phase 3 — Tokens

Read `references/03-palette.md` and `references/04-typography.md`.

Palette first, because typography choices depend on ground contrast. Both end at
a hard gate:

```bash
.venv/Scripts/python.exe tools/palette_check.py
.venv/Scripts/pytest.exe -q tests/test_palette.py
```

**A palette that does not pass is not a palette.** Do not proceed with "we will
fix contrast later" — the two contrast failures the nightly audit reported for
weeks were exactly that promise.

## Phase 4 — Adaptive skeleton

Read `references/05-adaptive.md`. Layout before decoration: breakpoints, the
thumb zone, the five flow screens, one primary action each. A design that is
beautiful at 1440px and unusable at 390px in one hand has failed at the only
place this app is used.

## Phase 5 — Assets · subagent

Read `references/06-assets.md`. Dispatch the **`design-assets`** subagent.

The tier ladder is not a menu, it is an order. Each tier must be exhausted before
the next is opened, because every tier costs bytes the previous one did not:

0. CSS and inline SVG — 0 bytes
1. one icon sprite — one request, cached forever
2. Recraft — bespoke vector, only for glyphs no library has
3. kie.ai raster — only where a photograph is genuinely the content

## Phase 6 — Implement

Re-point the **alias** layer; never redefine a colour inside it. 268 declarations
depend on those names, which is what let the last re-skin land without touching
markup or breaking `tests/test_template_element_ids.py`.

Work one template at a time. After each, run the feature inventory from phase 1
against it. A control that no longer works is a stop, not a note for later.

## Phase 7 — Verify · subagent · the gate with teeth

Read `references/07-verify.md`. Dispatch the **`design-verifier`** subagent.

It renders artefacts and compares them. It has not seen your diff and does not
receive your reasoning — deliberately. Give it the phase 1 feature inventory and
the phase 2 direction, nothing else.

It must produce, and you must look at:

- `tools/design_sheet.py` — before beside after, every page, both widths
- `tools/waterline_filmstrip.py` / `animation_filmstrip.py` — any motion touched
- `tools/icon_sheet.py --compare` — any icon touched
- `tools/site_audit.py` — zero new serious or critical violations
- the five flow screens at 390px, one primary action each in the thumb zone

Then put the comparison **in front of the owner**, not a description of it.
`CLAUDE.md`: *"produce the artefact and look at it."*

**Still open after this passes:** nothing here is a real phone. `docs/17 §9`
already admits it. Say so; do not claim a device check you did not do.

## Phase 8 — Ship

```bash
.venv/Scripts/ruff.exe check app tests
.venv/Scripts/mypy.exe --strict app/core app/rules app/features app/auth app/jobs app/discover app/geo app/intel app/media
.venv/Scripts/pytest.exe -q
```

Green, then merge to the default branch (standing rule 13), then — **because the
image holds a frozen copy of `app/` and `config/`, so editing a file changes
nothing the public URL serves** — rebuild:

```bash
docker compose up -d --build
```

Confirm the container is genuinely new (`docker ps` uptime) and `/health` answers.
Standing rule 20. Do this while there is still budget to confirm it worked.

Then update `docs/17-DESIGN-SYSTEM.md` to describe what now exists, and record in
`docs/18b-DECISIONS.md` what was decided and what was left open.

---

## Installed tools this workflow uses

| Skill | Phase | What it is for |
|---|---|---|
| `improve-ui` | 1 | evidence-gated audit, read-only on source, writes plans |
| `web-design-guidelines` | 1, 7 | ~100 interface rules — **pinned locally**, see below |
| `create-design-md` | 1 (optional) | reconstruct a design language from evidence |
| `ui-ux-pro-max` | 3 | lookup only: palettes, ~74 font pairings, Google Fonts data |
| `fixing-accessibility` | 7 | ARIA, keyboard, focus, contrast |
| `fixing-motion-performance` | 7 | compositor properties, layout thrash |
| `baseline-ui` | 6 | fast spacing and hierarchy cleanup |
| `design` (built-in canvas) | 2 | the three directions as artboards |
| `brand` | 2, 3 | voice, visual identity, palette and type specs, asset rules |
| `uiux-design` | 5 | logo generation (55 styles), icon design (15 styles, SVG), CIP mockups |
| `design-system` | 3 | three-layer token architecture: primitive to semantic to component |
| `banner-design` | 5 | `/welcome` hero and OG images only - **not** an in-app surface |
| `slides` | - | not part of this workflow; kept for pitching the SME automation concept |
| `ui-styling` | - | **shadcn + Tailwind. Wrong stack. See the caution below.** |

**Four cautions, all load-bearing:**

- `web-design-guidelines` upstream **fetches its rules from the network on every
  run and then follows them**. It has been pinned to a local dated copy. Do not
  restore the live fetch; update by diffing and re-pinning.
- **`ui-styling` is installed and must not be followed for this app.** It builds
  shadcn/ui on Radix + Tailwind, which requires a build step — forbidden by
  ADR 0001 and standing rule 1, a decision the owner made after considering
  React. It is on disk because the pack ships as a set and its sibling skills are
  useful; it triggers on phrases this workflow uses ("design system",
  "responsive layout", "accessible components"), so it will offer itself.
  **When it does: take the accessibility reasoning and the component anatomy,
  discard every line of implementation.** If a suggestion names Tailwind, shadcn,
  Radix, a `className`, or a `npx shadcn add`, it is out of scope — not a
  recommendation to weigh. It also advocates dark mode, which `docs/17 §9`
  refused on daylight-legibility grounds.
- `uiux-design` was installed under that name rather than its own (`design`),
  because it would otherwise **collide with the built-in `design` canvas skill**
  that phase 2 depends on. Do not rename it back.
- `banner-design` declares dependencies on `frontend-design`, `ai-artist` and
  `ai-multimodal`, none of which are installed. It will degrade rather than fail;
  do not install `frontend-design` to satisfy it — `docs/18 §1a` explains why
  that skill fights an existing design system.

## What this workflow will not do

- Substitute the stack. Jinja2 + HTMX, no build step, no SPA. ADR 0001.
- Build dark mode. `docs/17 §9` — a light ground is what reads in sunlight.
- Put a fishing threshold in CSS or Python. Law 1: it belongs in the YAML.
- Show a raw score, or a number the data cannot support. Standing rules 2 and 16.
- Give two species the same body or tail geometry. `CLAUDE.md` icon rules.
- Claim a change landed on the strength of a diff.
