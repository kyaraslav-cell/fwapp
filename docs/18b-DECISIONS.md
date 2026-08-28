# 18b — Design decisions taken 2026-08-28

Taken by the owner directly, after reading `docs/18-DESIGN-TOOLING-RESEARCH.md`.
These supersede where they conflict.

---

## D1. Waterline is replaced, not refined

The navy-ink / pale-water / reed-green scheme shipped this morning
(`docs/17-DESIGN-SYSTEM.md`, commit `6a35999`) is **not kept**. A new scheme is
designed from scratch.

Standing rule 8 is therefore live again in spirit: clean, minimal, pastel.

**What must survive the replacement**, because it is architecture rather than
taste:

| Survives | Why |
|---|---|
| The two-layer token/alias structure (`docs/17 §1`) | 268 declarations reference the alias names. Re-point the aliases; never redefine a colour inside the alias block. |
| `tools/palette_check.py` + `tests/test_palette.py` | The AA gate. It caught three tokens at design time and cleared two audit failures. A pastel scheme needs it more, not less. |
| Traffic-light day bands, green good / red bad | `CLAUDE.md` standing rule 3. |
| No raw score anywhere | Standing rules 2 and 16. |
| A **light** ground | Sunlight collapses perceived contrast at the waterside. This is a field constraint, not a preference, and it is why `docs/17 §9` refused dark mode. Only one of the ten reference sites is dark, and it is a desktop video editor. |
| The waterline element itself is *optional* | It is one element, no image, and does brand mark + tap feedback + HTMX loading state at once. Cheap to keep, no obligation to. |

Open: whether "pastel" means a lighter, bluer ground, or pastel *accents*, or the
original light-blue-and-white. To be settled from mockups, not from prose.

## D2. Two surfaces, two treatments, one palette

- **`/welcome` (landing)** takes the marketing-site treatment — the craft.do /
  hey.com / screen.studio register. Raster assets, generous scale, a signature
  move. It is read once, usually on wifi.
- **The app screens** take the Excalidraw register: the only *application* in the
  reference set, and the only one with **zero raster images**. Dense, quiet, fast,
  vector-only.

One palette and one typeface across both. Two densities, two asset budgets.

## D3. A full custom typeface, body and headings

Reverses `docs/17 §2`, which chose a 0-byte system stack.

### Correction to `docs/17 §2`

That section states the face "could not be subsetted, because this UI ships
Polish and Russian". **That is overstated and it made the decision look more
expensive than it is.**

A font family is split by `unicode-range` into separate files — Latin,
Latin Extended (which is where the Polish diacritics live), Cyrillic — and the
browser downloads **only the ranges the page actually uses**. A Polish reader
never fetches the Cyrillic file. This is exactly how Google Fonts serves
multi-script families, and it works identically self-hosted.

Combined with a **variable** font — one file carrying every weight instead of
one file per weight — the realistic cost is roughly **25–35 KB for the script in
use**, not "60 KB for one weight" and not four files.

Requirements for the face chosen:

1. Variable, so weight range costs nothing extra.
2. Real Latin Extended coverage — `ą ć ę ł ń ó ś ź ż` must be drawn, not
   synthesised.
3. Cyrillic coverage, in its own `unicode-range` file.
4. **Self-hosted.** `tests/test_hardening.py::test_no_third_party_font_origin_is_admitted`
   pins the CSP against third-party font origins and that test stays. Serving
   from `/static/` admits no new origin.
5. `font-display: swap`, with the system stack as the fallback so text paints
   immediately on bad signal.

The size budget in `tests/test_palette.py` must be extended to cover font files,
the way it already covers the two images.

---

## What is *not* decided

- The palette itself.
- The typeface itself.
- Whether the waterline element survives.
- Whether the landing page keeps the scrollcraft build at `/welcome`.

All four come out of mockups, before any CSS is touched.
