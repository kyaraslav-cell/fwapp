# 19b — Pre-redesign audit, 2026-08-28

Read-only audit of all 16 templates, `style.css` and `waterline.js`, run before
the cosy-tackle redesign touches anything. The full feature inventory is the
contract phase 7 verifies against; this file records the findings and the
structural facts that were not previously written down.

---

## 1. Two templates are dead

Neither is rendered by any route. Both are earlier prototypes, superseded, and
both carry **no `t()` calls** — so they were written before the app became
trilingual and have never been translated.

| Template | Superseded by | Posts to routes that do not exist |
|---|---|---|
| `today.html` | `lake_detail.html` | `/refresh`, `/session/start` |
| `zone_start.html` | `spot_start.html` | `/lake/{slug}/zone/{id}/start` |

**Do not restyle them.** They render fine in isolation, so a redesign sweeping
`templates/` will style them and waste the effort — and worse, a later reader
will take them for live screens. They should be deleted in a separate change.

Consequence for the design work: **the "conditions" screen is
`lake_detail.html`, not `today.html`.** The direction mockups are labelled
"Conditions" for that reason.

## 2. HTMX is not loaded — the app is plain forms

There is no `<script src=".../htmx...">` anywhere in `base.html` or `static/`.
`waterline.js:163-181` listens for `htmx:beforeRequest` / `htmx:afterRequest`
defensively, but **those events never fire**. The app is plain forms, links and
two `fetch()` calls (the lake grid, and the catch-photo upload through a native
multipart form).

Two consequences:

- **There are no `hx-target` / `hx-swap` pairs for a redesign to preserve.** That
  is a genuine simplification and it was not known before this audit.
- `CLAUDE.md` and `docs/05` describe the stack as "Jinja2 + HTMX". The HTMX half
  is aspirational. The loading-indicator half of the waterline effectively only
  runs through its `beforeunload` path.

## 3. Findings, most severe first

### 3a. Deleting a catch is a real hard delete, with no confirmation · HIGH

`app/notebook/sessions.py:122-124` — `delete_catch()` calls `db.delete(catch)`.
This is a true delete. Everything else in the app is soft: removing a place only
sets `removed_at` (`app/notebook/place_prefs.py:88-93`).

The control is `session_active.html:106-108`, a bare `✕` icon button, and it has
**no `onsubmit="return confirm(...)"`** — while the *place removal* form right
next to it in `home.html:118-119` does have one.

Standing rule 18 ("nothing is ever deleted") is why the pinned interface
guidelines' "destructive actions need confirmation" rule was marked as
not-applicable here. **That exemption does not cover this control**, because this
one really does delete, and there is a real second user with live sessions.

A redesign restyling this button carries the risk forward silently. Fix it as
part of the work: either a confirm, or make it soft like everything else.

### 3b. Five literal colours defined inside the alias layer · HIGH for this work

`style.css:92-98`:

```
--primary-text:       #123f31
--accent-green-text:  #0e4d38
--accent-coral-text:  #6b2a1c
--danger:             #b24739
--danger-strong:      #963a2e
```

This is exactly the defect class
`.claude/skills/design-kit/references/01-constraints.md` warns about. Confirmed
invisible to the gate: `tools/palette_check.py:36-52` carries its own hardcoded
`TOKENS` dict of palette-layer values, and none of `primary-text`,
`accent-green-text`, `accent-coral-text` or `danger-strong` appear in it.

So changing any of these five changes rendered colour with **zero contrast
coverage** — `tests/test_palette.py` cannot fail on them. Re-point all five onto
real palette tokens as part of phase 3, and extend `palette_check.py` to cover
them.

### 3c. The nightly audit says FAIL, and contradicts `docs/17`

`reports/site_audit/2026-08-28.md` reports **2 serious `color-contrast`
violations** — `.section-label`, `.place-meta`, `.badge-neutral` on home;
`.section-label` and `th:nth-child(1)` on the lake page.

`docs/17-DESIGN-SYSTEM.md:59-62` states those exact selectors were fixed and
that "the audit reports **zero** serious or critical violations". Both are dated
2026-08-28.

**Treat the doc's "zero" claim as unverified.** The artifact on disk is the
evidence. This is moot for the palette itself, since it is being replaced — but
it is a live warning that a design doc asserted a passing audit that the audit
did not report.

### 3d. Russian species names fall back to English · MEDIUM

`session_active.html` renders species as `sp.name_en if lang != 'pl' else
sp.name_pl`. There is no `name_ru`. A Russian-language angler sees **English**
species names in the quick-log grid. Matches the open backlog item "PL/RU
wording unchecked". Not a design problem, but the redesign touches this exact
row, so it is the cheap moment to fix it — **owner's call whether that is in
scope**.

### 3e. `.build-note-failed` used on a non-failure · MEDIUM

`spot_start.html:13` applies the failed modifier to the "you already have a
session running elsewhere" message, which is an expected state under standing
rule 17, not an error. The class's own comment (`style.css:2001-2002`) says it
should only be coloured "when something actually failed". Drop the modifier.

### 3f. The session float is 44px, against the project's own 48px rule · MEDIUM

`style.css:458-461`. Already named in the constraints doc. If the float survives
the redesign, it ships at 48px, with the offsets and focus ring adjusted to match.

### 3g. `autofocus` on a phone-first search input · LOW

`place_new.html:18`. Pops the keyboard on load on a phone. The pinned guidelines
say desktop only.

### 3h. Literal `...` where the sibling key uses `…` · LOW

`config/i18n/{en,pl,ru}.yaml:115` — `end.reflection_placeholder`. The sibling
`session.search_placeholder` at line 90 of the same three files already uses a
real ellipsis. Also `landing.html:615`.

## 4. Contracts a restyle can break silently

These are the ones with no test and no visible failure.

- **The reveal is bound to class names**, not ids: `.card`, `.place-card`,
  `.dash-tile`, `.catch-card`, `.intel-card`, `.candidate-card`
  (`waterline.js:86-88`). Renaming any of them in the redesign **silently
  orphans the animation** — it fails open, so content still shows and nothing
  errors; the stagger simply never plays again. Nothing will tell you.
- **The "bite" fires on every form containing `.btn-primary`** — login, register,
  search, spot start, catch log, catch edit (`waterline.js:183-198`). `docs/17
  §4` describes it as the primary button on session start. It is much broader.
- **`#fish-{shape}` symbol ids** in `_fish_icons.html` are consumed by
  `session_active.html` and `catch_edit.html` through `<use href>`.
- **`lake_detail.html`'s script block references many ids by
  `getElementById`.** `tests/test_template_element_ids.py` pins them and will
  fail loudly — that test is the safety net, and it is the reason it exists.
- **Fish-pin drag timings are coupled to keyframes**: splash at 705ms,
  `pickSpot()` at 900ms, pinned to the `dive` animation. Retiming one without
  the other breaks the illusion.
- **The heat overlay steps opacity down while the pin is held** (0.58 → 0.15) so
  the angler can see the bank under their thumb.
- **`spot_start.html`'s entire script is wrapped in `{% if not running %}`**,
  because when a session is already running the form is not rendered and one
  missing element would throw and kill every later handler. The template says so
  in a comment. Preserve that guard.

## 5. Standing rule 10, concretely

Two proof points, both must survive:

1. `lake_detail.html:9-14` shows a banner during a live session and
   **deliberately does not redirect** (`places.py:208-210`: "conditions and the
   map are exactly what you want to check while you are sitting there fishing").
2. `session_active.html:19-22` links out to `/lake/{slug}` and `/history`.

## 6. Law 3, concretely

- `session_end.html:7-13` branches on `n_catches == 0` to show
  `end.blank_note` instead of a count — a blank end is a first-class path, not an
  error.
- `history.html:12,29` counts blanks into `n_sessions` and renders
  `history.blank` in the fish column. Never filtered out.
- The `.counter-number` on `session_active.html:14-17` is a raw catch count for
  the *current* session's morale only. CPUE is computed in `history.html`. That
  distinction is deliberate and must not be "fixed".
