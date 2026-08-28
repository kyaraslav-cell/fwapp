# 20 — The Cosy tackle design system

Supersedes `docs/17-DESIGN-SYSTEM.md` (Waterline) entirely, on the owner's
instruction of 2026-08-28. The brief and what it released are in
[`docs/19-COSY-TACKLE-BRIEF.md`](19-COSY-TACKLE-BRIEF.md); the pre-redesign
audit is [`docs/19b`](19b-PRE-REDESIGN-AUDIT.md).

Owner's pick: **direction A, "Tackle box"**, with **direction B's ring** on the
conditions card, in A's colours.

Look at it, do not take my word for it:

- [`design/cosy-tackle-phone-before-after.png`](design/cosy-tackle-phone-before-after.png)
- [`design/cosy-tackle-desktop-before-after.png`](design/cosy-tackle-desktop-before-after.png)
- [`design/cosy-tackle-home-detail.png`](design/cosy-tackle-home-detail.png)
- [`design/cosy-tackle-ambient-filmstrip.png`](design/cosy-tackle-ambient-filmstrip.png)
- [`design/cosy-tackle-ambient-species.png`](design/cosy-tackle-ambient-species.png)
- [`design/cosy-tackle-ring.png`](design/cosy-tackle-ring.png)

---

## 1. Colour

Kraft khaki ground, deep bark ink, one burnt-amber accent.

| Token | Value | Role |
|---|---|---|
| `--canvas` | `#efe7d6` | the ground |
| `--canvas-deep` | `#eae1cd` | recessed ground |
| `--surface` | `#fbf7ef` | raised tray |
| `--surface-sunk` | `#f4eee0` | inset surface |
| `--line` / `--line-strong` | `#ded2b8` / `#c9bb9c` | rims |
| `--ink` | `#2e2a20` | primary text · 13.4:1 on surface |
| `--ink-soft` | `#5a5242` | secondary |
| `--ink-faint` | `#6b6250` | least emphasis, still AA |
| `--accent` | `#a04a14` | links, the one primary action |
| `--accent-soft` / `--accent-wash` | `#e9c9a3` / `#f7eadb` | fills, tinted grounds |
| `--accent-deep` | `#7a3a10` | emphasis text |
| `--water` / `--water-deep` | `#8fb3a4` / `#5b8574` | lake shapes only |

The accent was darkened from the mockup's `#b2541c` because
`tools/palette_check.py` said it cleared only 4.09:1 on `--canvas-deep`. It now
clears 4.64:1 on the worst ground. **The checker moved this value, not taste.**

### The reserved marks — the sharpest thing in this design

The brief asks for green, yellow and orange. Day quality is *also* green → red.
So an orange ornament beside an orange warning stops the warning reading as a
warning.

The resolution: **the band tint carries text, the band mark carries the signal,
and the four marks are reserved.** Nothing decorative may use a mark hue at mark
saturation.

In practice decoration ended up avoiding the band hues altogether - the ambient
fish were moved off the tints too (§5), and the conditions ring's interior was
moved off them at the owner's request (§4). What is left is the cleaner rule:
**a band hue appears only where a day is being reported.**

| | Tint (text sits on this) | Mark (reserved) | mark-on-tint |
|---|---|---|---|
| good | `--band-green` `#d6e9d2` | `--mark-green` `#2f7d4f` | 3.95:1 |
| fair | `--band-yellow` `#e6ebcb` | `--mark-yellow` `#6b7f2c` | 3.64:1 |
| poor | `--band-orange` `#f7e2c0` | `--mark-orange` `#9e6712` | 3.77:1 |
| bad | `--band-red` `#f3d2cb` | `--mark-red` `#b03d24` | 4.21:1 |

`mark-yellow` and `mark-orange` were darkened from the mockup because the gate
put them at 2.77 and 2.79 against the WCAG 2.1 non-text minimum of 3.0. Again:
the checker moved them.

### The alias block now holds no literal colour

`docs/19b §3b` found five colours written as hex **inside the alias block**,
where `tools/palette_check.py` — which walks the palette layer — could not see
them. They rendered on screen and had never been contrast-tested.

All five are palette tokens now (`--accent-deep`, `--positive-ink`,
`--warn-ink`, `--danger`, `--danger-deep`), all are in the checker, and
`tests/test_palette.py::test_the_alias_block_holds_no_literal_colour` fails the
suite if one drifts back.

## 2. Type: Nunito and Baloo 2, self-hosted, split by alphabet

Reverses `docs/17 §2`, whose claim that a webfont "could not be subsetted" was
simply wrong.

`unicode-range` splits each family so a reader downloads only the alphabet they
are reading. Five files, none from a third-party origin —
`tests/test_hardening.py::test_no_third_party_font_origin_is_admitted` still
holds, and `test_no_webfont_is_requested` was rewritten to guard the *origin*
rather than the existence of a face.

| File | Size |
|---|---|
| `nunito-latin.woff2` | 38.2 KB |
| `nunito-latin-ext.woff2` | 34.8 KB |
| `nunito-cyrillic.woff2` | 20.3 KB |
| `baloo2-latin.woff2` | 32.4 KB |
| `baloo2-latin-ext.woff2` | 26.7 KB |

**Correcting my own estimate.** `docs/18b` D3 predicted "~25–35 KB for the
script in use". That was for *one* family. This design uses two, so the real
per-reader cost is:

| Reader | Downloads |
|---|---|
| English | 70.6 KB |
| Polish | 132.1 KB |
| Russian | 90.9 KB |

Polish is the expensive case and it is roughly four times what I told the owner.
`font-display: swap` means none of it blocks text — the system stack paints
immediately and the page reflows when the files land — but it is bandwidth on a
riverbank and the owner should know the true number.

**Baloo 2 ships no Cyrillic**, deliberately, and no sixth file was added for it.
`--font-display` lists Nunito immediately after Baloo, so Russian headings fall
through to Nunito, which does carry Cyrillic. One file saved, one fallback that
costs a Russian reader a slightly less characterful heading.

Sizes are pinned by `tests/test_palette.py::test_the_faces_are_committed_and_within_budget`,
which also asserts each file is real woff2 and is actually referenced.

## 3. Shape

`--radius` went 14px → **20px**, `--radius-sm` 9px → **13px**. The brief asked
for round and the scale is held everywhere; nothing in this app has a sharp
corner.

## 4. The ring — direction B's circle in direction A's colours

The conditions card is a ring: the reserved mark draws its edge, the
temperature sits inside, and **the inside is the design's own recessed ground
(`--canvas-deep`), never the band tint** - the owner's call, and it makes the
rule cleaner than the first cut. The day's colour now lives in the STROKE and
nowhere else, so the card reads as this app rather than as a green card on a
kraft page.

That moved the contrast pair being tested: the mark is now drawn on
`--canvas-deep` rather than on its own tint, so `tools/palette_check.py` checks
that pair too (3.44-4.56:1, all clear of the 3.0 non-text minimum).

**It is a full ring, not an arc that fills further on a better day.** The
direction-B mockup drew a partial arc and that was wrong: a partial arc is a
progress bar, and a progress bar is a score out of ten wearing a hat. Standing
rules 2 and 16 forbid exactly that. The hue is the whole message.

The ring follows the day strip — selecting a forecast day moves it, and a day
with no stored prediction row clears it rather than borrowing a neighbour's
colour (law 4).

## 5. Ambient fish

**Six** species crossing the page, on 22-37s cycles staggered 1-26s, so a
crossing happens every few seconds. (Four, on 34-53s cycles, was the first cut;
the owner asked for more.) Zero bytes: inline SVG and CSS keyframes, no sprite,
no library, no `requestAnimationFrame`.

- `transform` and `opacity` only, so nothing can force layout
- `aria-hidden` and `pointer-events: none` — it can never eat a tap
- **paused when the tab is hidden**, from `visibilitychange` in `waterline.js`
- removed entirely under `prefers-reduced-motion`

Per species, per `CLAUDE.md`, and the **tail alone** identifies each:

| | Tail |
|---|---|
| roach | even, moderate fork, slender body |
| bream | long fork, lower lobe dropped well past the upper, deep slab body |
| crucian | rounded convex fan, no fork at all |
| rudd | even fork on a deeper body, snout turned up |
| carp | broad **shallow** fork - half the notch depth, twice the width |
| ide | the deepest even fork, on a long torpedo body |

Decoration uses only `--accent-soft`, `--water` and `--water-deep` - never a
band mark, and no longer the band tints either: on kraft the pale tints were
barely visible, and keeping decoration off the band hues entirely is the safer
reading of the reserved rule.

### Three drawing faults only a render caught

Put six fish in a row at size and they are obvious; in the markup they are
invisible. This is `CLAUDE.md`'s second verification rule doing its job.

1. **Every dorsal fin was a detached eyebrow.** Drawn as a stroked arc above
   the body outline, it never touched the body. The dorsal is now part of the
   body path on all six.
2. **The crucian's fan tail read as a ball trailing the fish - twice.** Both
   fixes pinched the fan to a point where it met the body, so the neck went to
   zero width and vanished at 24 device pixels. It attaches along a tall
   straight edge now.
3. **The carp's barbels crossed its own outline** and read as a drawing error.
   Dropped. `CLAUDE.md` says outright that barbels are garnish and the
   silhouette carries the recognition.

A fourth, from the same render: the rudd and the roach were the same colour and
nearly the same body, so they twinned. The rudd is deeper-bodied and a different
tone now.

### Three things filming caught that reading could not

`tools/ambient_filmstrip.py` exists because of these.

1. **The layer was behind the page.** At `z-index: 0` under the content, the
   fish were invisible on every page with a hero or a full-width card — which is
   most of them. The stylesheet read perfectly well.
2. **`var()` does not resolve in an SVG presentation attribute.** `fill="var(--x)"`
   silently renders as black or nothing in Chrome. It works in `style="fill: var(--x)"`.
3. **An inline `opacity` does not hold against a running animation.** The first
   filmstrip pinned opacity inline, the animation won the cascade, and it
   photographed nine identical frames of an invisible fish — and reported the
   animation dead. An author `!important` rule does beat an animation.

The tool now **asserts its own frames differ** and fails if they do not. A
filmstrip that photographs one frame nine times is worse than no filmstrip: it
reports success for an animation that never moved.

## 6. Two bugs this redesign fixed

- **Deleting a catch now asks.** It is a genuine hard delete
  (`app/notebook/sessions.py:122`) while everything else in the app is soft, and
  it had no confirmation. `session.delete_confirm` in all three languages says
  so plainly.
- **The two contrast violations are gone.** `tools/site_audit.py` reports **0
  serious/critical** on the new palette, against 2 on the old one — which
  `docs/17` had claimed were already fixed.

## 7. What this design does not do

- **No dark mode.** A light ground is what reads in sun. Unchanged.
- **The species icons are untouched.** `_fish_icons.html` still holds the
  existing sprite; eight of the fourteen are still in the old flat style. The
  ambient fish are a separate, new set.
- **The app is still branded "Fishlog" in the topbar.** The owner's brief calls
  it "fwapp". Renaming a product is not a design decision to take unasked.
- **Nothing was checked on a real phone.** Headless Chromium at 390px is not an
  iPhone in daylight. Touch feel and whether the ambient fish read in sun are
  open.
- **Roughly 40 hardcoded hex values remain elsewhere in `style.css`**, outside
  both `:root` and the alias block. Four of them were found and fixed in this
  pass because they were visibly wrong (the badges made "Great" render amber);
  the rest are unaudited.

## 8. Tools

| | |
|---|---|
| `tools/palette_check.py` | contrast for every pair and every mark-on-tint; run before choosing a colour |
| `tools/design_sheet.py` | shoots 6 pages × 2 widths, tiles before beside after |
| `tools/ambient_filmstrip.py` | pins the ambient arc and tiles it; fails if the frames do not differ |
| `tools/design_assets_pack.py` | crops, **warms**, resizes and compresses the stills |
| `tools/site_audit.py` | dead controls, console errors, a11y, visual diffs |

`tools/design_assets_pack.py` warms now; it cooled before. The same two images,
cooled for Waterline's `#eef4f4`, sat on the kraft ground as a blue-green photo
on a warm page — the exact failure the cooling existed to prevent, in reverse.
Found by rendering the home page and looking.
