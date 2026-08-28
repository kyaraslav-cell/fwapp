# 17 — The Waterline design system

The app's visual language, written down so the next change extends it rather
than starts a third design. Superseded the pastel-blue-and-white scheme on
2026-08-28.

Before and after, every page, both widths:

- [`design/waterline-desktop-before-after.png`](design/waterline-desktop-before-after.png)
- [`design/waterline-phone-before-after.png`](design/waterline-phone-before-after.png)
- [`design/waterline-motion-filmstrip.png`](design/waterline-motion-filmstrip.png)

---

## 0. The brief, in the owner's words

> smart slick minimalistick desing in blu navy green pastel colors … should not
> hight weighted … to load easily on weak interneet because of fishing
> locations … scroll or klick should be folowed with nice animation corelated
> to fishing theme, like fishing splashes, or bites … minimalistic pastel and
> pleased looking for eyes

Two of those are constraints, not preferences, and they decide most of what
follows: **it is read at the waterside on bad signal**, and **it must not
stutter**. A design that is beautiful on a desk and slow on a riverbank has
failed at the only place this app is used.

Standing rule 8 ("pastel light blue and white, minimal … like an instrument,
not an app") is superseded on the hue and kept on the character. The instrument
reading is what stops this becoming a marketing page.

## 1. Colour

Deep navy ink on pale water, one reed-green accent. Six roles, and the accent
is locked for the whole app — a green app does not grow a blue button on one
screen.

| Token | Value | Role |
|---|---|---|
| `--canvas` | `#eef4f4` | the ground |
| `--canvas-deep` | `#e3edee` | recessed ground |
| `--surface` | `#ffffff` | raised surface |
| `--surface-sunk` | `#f4f9f9` | inset surface |
| `--ink` | `#0f2c40` | primary text |
| `--ink-soft` | `#415f72` | secondary text |
| `--ink-faint` | `#526d7d` | least emphasis, still AA |
| `--accent` | `#2a765d` | links, primary action |
| `--accent-soft` | `#8fcdb6` | fills |
| `--accent-wash` | `#dcefe7` | tinted grounds |

Secondary text is **tinted from the navy, never flat grey**: `#888` on a cool
ground reads as dirt.

**Every pair is measured, not eyeballed.** `tools/palette_check.py` computes
WCAG contrast for every foreground against every ground; `tests/test_palette.py`
fails the suite if one drops below AA. Three tokens were darkened by 1–8% at
design time because the checker said so.

This retired the two colour-contrast failures the nightly audit had been
reporting (`reports/site_audit/2026-08-28.md`): `.section-label`,
`.place-meta` and `.badge-neutral` all inherited a `--muted` that was 3.5:1.
After the change the audit reports **zero** serious or critical violations.

The four day bands stay traffic-light — green good, red bad, `CLAUDE.md`
standing rule 3 — retuned to sit in this palette. `--ink` clears 6.4:1 on the
worst of them.

### The two layers

`:root` defines the palette above, then maps the legacy role names (`--bg`,
`--primary`, `--text`, …) onto it. 268 declarations already referenced those,
so re-pointing the aliases re-skinned the whole app without touching markup —
which is what kept the inline JS bindings and
`tests/test_template_element_ids.py` intact. **Never redefine a colour in the
alias block.**

## 2. Type: no webfont, deliberately

The previous design loaded Inter from Google Fonts: two preconnects, a
render-blocking stylesheet, and up to four woff2 files before any text could
paint. It also carried three alphabets, because this UI ships Polish and
Russian, so a display face has to cover Latin Extended **and** Cyrillic — near
60KB for one weight.

> **Corrected 2026-08-28.** This section originally said the face "could not be
> subsetted". That is wrong: `unicode-range` splits a family into Latin,
> Latin Extended and Cyrillic files and the browser fetches only the ranges the
> page uses, so a Polish reader never downloads Cyrillic. With a variable font
> the real cost is ~25-35KB for the script in use, not 60KB per weight. The
> overstatement made the no-webfont decision look cheaper than it was. See
> `docs/18b-DECISIONS.md` D3, which reverses this section.

The system stack is 0 bytes, covers all three alphabets, and renders in the
face the angler's own device already uses. The distinctiveness that gives up is
bought back in scale, weight, colour and the waterline, none of which download.

Consequences worth knowing:

- Both Google origins came **out of the CSP**. A policy that still admits an
  origin the app stopped using is a standing permission nobody is watching.
  `tests/test_hardening.py::test_no_third_party_font_origin_is_admitted` pins it.
- Tracking tightens as size grows (`--track-tight` on headings). A heading set
  at display size with body tracking reads loose.
- More space above a heading than below it. The gap belongs to the section
  boundary, not to the heading-and-body pair.
- Anything that counts or tabulates gets `tabular-nums`, so a column of weights
  does not jitter.

## 3. The waterline — the signature element

One 2px line under the topbar that behaves like a water surface, doing three
jobs with one element:

- it is the brand mark, on every page;
- it **ripples outward from wherever you tap**, so a press has a visible
  consequence before the page has navigated;
- it **swells while an HTMX request is in flight** and settles when it lands,
  which is the loading indicator.

Cost: one element, two custom properties, no image, no library. It animates
`transform` and `opacity` only.

It is `aria-hidden`: it duplicates state the page already states in words.

## 4. Motion

Three behaviours, all `transform`/`opacity` so none can force layout.

| | What | Length |
|---|---|---|
| **Splash** | a ring expanding from the point of contact, anchored to the pointer rather than the element — the water answering the touch | 520ms |
| **Surfacing** | content rises 6px and fades as it enters the viewport, staggered 45ms | 320ms |
| **Bite** | the primary button dips, checks, dips again and settles, the way a float goes under | 480ms |

Deliberately small. A card that flies 40px reads as a website; this is an
instrument.

**Reduced motion means fewer and gentler, not zero.** The opacity that carries
comprehension stays; every position change goes.

### Verified by filming, not by reading keyframes

`CLAUDE.md`'s first verification rule, and it earned its keep three times here:

1. **The ripple was invisible.** It faded linearly while spreading 20-fold, so
   it was gone by 150ms and read as a flash. The keyframes looked fine. Fixed
   by holding opacity and falling late.
2. **The filmstrip itself was measuring nothing.** The ripple lives on
   `::after`, and a pseudo-element has no node to set inline style on — the
   first version photographed eight identical frames of an animation that was
   running correctly. Pinning is now done with an injected stylesheet rule.
3. **The bite appeared not to move.** Playwright's element screenshot follows
   the element, which cancels the very translation being filmed. Fixed by
   measuring a fixed frame once and reusing it.

`tools/waterline_filmstrip.py` is the tool. Run it after touching any of the
three.

## 5. The generated assets

Two raster images, generated through **kie.ai** (`seedream/5-pro-text-to-image`)
with the scrollcraft skill's `kie.mjs`, using **one style preamble reused
verbatim** — which is why two separately generated pictures read as one set.

| File | Where | Desktop | Phone |
|---|---|---|---|
| `water-hero.webp` | home hero band | 18.8KB | 4.0KB |
| `float-rings.webp` | empty state | 9.3KB | 3.5KB |

Everything else in the UI is vector or CSS. `tests/test_palette.py` enforces
the size budget.

**Build-time only.** The outputs are committed, so a deployment never calls
kie.ai and a missing key costs nothing. Regenerate with
`bash tools/design_assets.sh && python tools/design_assets_pack.py`.

Cost: 28 credits for both, against the 28-per-still published rate — the
observed debit ran at about half.

Two things the pack step does, both learned by looking:

- **Crops the hero at build time.** seedream composed it with two thirds empty
  sky, which is right for a full frame and wrong for a 200px band: cropped in
  CSS the hero rendered as a featureless rectangle. The shipped file is the
  reed line, the far bank and the water.
- **Cools both images** by a small per-channel scale. They came back warmer
  than this palette, and a cream sky against a `#eef4f4` canvas reads as a
  different design. Done at build time because a CSS filter on a large image
  costs a repaint per scroll frame.

## 6. Two failures this design caused, and the rules they leave behind

Both were found by rendering the app and looking, and neither would have been
caught by a passing test suite.

**A reveal may never decide whether content is on screen.** The first cut added
`opacity: 0` to every card and waited for an IntersectionObserver. Content that
is *already* visible has nothing to animate into, so the top of the home page
was blank — and on a slow phone that blank is what the app looks like until the
script arrives. Now only elements below the fold are ever hidden, the hidden
class is applied by script and never by markup, and there is a 2s safety net.
`tests/test_palette.py::test_the_reveal_cannot_permanently_hide_content`.

**`fetchpriority="high"` and `decoding="async"` contradict each other.** On the
largest element of the first screen, `async` tells the browser it may paint a
frame late, which is exactly what it must not do. It also made the hero miss the
frame in every screenshot, so the audit diff and the before/after sheet both
showed an empty box that was not empty in a real browser.

## 7. Tools

| | |
|---|---|
| `tools/palette_check.py` | contrast for every pair; run before choosing a colour |
| `tools/design_sheet.py` | shoots 6 pages × 2 widths, tiles before beside after |
| `tools/waterline_filmstrip.py` | pins the three animations and tiles the frames |
| `tools/design_assets.sh` | regenerates the two stills through kie.ai |
| `tools/design_assets_pack.py` | crops, cools, resizes and compresses them |

`tools/design_shots/` is working output and is gitignored; the sheets worth
keeping are copied into `docs/design/`.

## 8. Credentials

`KIE_AI_API_KEY` in `.env` (gitignored), listed in `.env.example`. The name is
not `FISHLOG_*` because the scrollcraft skill's own `kie.mjs` reads that exact
name, and one variable read by both beats two that can disagree.

Needed only to **regenerate** assets. Check a balance with:

```bash
node "$SCROLLCRAFT_SKILL/scripts/kie.mjs" probe
```

## 9. What this design does not do

- **No dark mode.** Offered and not taken; the light ground is what reads in
  sun, which is the real condition.
- **The species icons are untouched.** They are naturalistic on purpose —
  `CLAUDE.md`'s icon rules are about recognition, not palette. Eight of the
  fourteen are still in the old flat style (handover §5.1) and this change did
  not address that.
- **Nothing was verified on a real phone.** Headless Chromium at 390px is not
  an iPhone. Touch feel, and whether the splash reads on a real screen in
  daylight, are open.
