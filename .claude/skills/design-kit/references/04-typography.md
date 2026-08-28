# 04 — Typography: a custom face that costs 30KB, not 240KB

`docs/18b` D3 reverses `docs/17 §2`. The app takes a real typeface. This file is
how to do that without giving back the load time it was traded for.

## The correction that made this affordable

`docs/17 §2` justified the system stack by saying a face "could not be subsetted,
because this UI ships Polish and Russian". **That is wrong**, and the error made
the no-webfont decision look cheaper than it was.

`unicode-range` splits a family into separate files and the browser downloads
**only the ranges the page actually uses**:

```css
@font-face {
  font-family: "Fishlog";
  src: url("/static/fonts/fishlog-latin.woff2") format("woff2");
  unicode-range: U+0000-00FF, U+2000-206F, U+2190-21BB;
  font-weight: 300 700;   /* variable: one file, every weight */
  font-display: swap;
}
@font-face {
  font-family: "Fishlog";
  src: url("/static/fonts/fishlog-latin-ext.woff2") format("woff2");
  unicode-range: U+0100-024F, U+1E00-1EFF;   /* ą ć ę ł ń ó ś ź ż live here */
  font-weight: 300 700;
  font-display: swap;
}
@font-face {
  font-family: "Fishlog";
  src: url("/static/fonts/fishlog-cyrillic.woff2") format("woff2");
  unicode-range: U+0400-045F, U+0490-0491;
  font-weight: 300 700;
  font-display: swap;
}
```

A Polish reader fetches latin + latin-ext and **never** touches the Cyrillic
file. A Russian reader fetches latin + cyrillic. Nobody pays for all three.

Combined with a **variable** face — one file carrying the whole weight axis
instead of one file per weight — the realistic bill is **~25–35KB for the script
in use**, against the ~240KB that four static weights across three scripts would
have cost.

## Requirements for the face

1. **Variable.** A static family multiplies by every weight you use.
2. **Real Latin Extended.** `ą ć ę ł ń ó ś ź ż` must be *drawn*. A face that
   synthesises them by stacking a generic ogonek will look wrong to a Polish
   reader and right to you.
3. **Cyrillic**, in its own `unicode-range` block.
4. **Self-hosted from `/static/fonts/`.** Not Google Fonts, not any CDN.
   `tests/test_hardening.py::test_no_third_party_font_origin_is_admitted` pins
   the CSP against third-party font origins and **that test stays**. `docs/17 §2`
   is right that an origin the app no longer uses is a standing permission nobody
   is watching — the answer is to serve the file yourself, not to re-open the CSP.
5. **`font-display: swap`**, with the system stack as the fallback so text paints
   immediately on bad signal. On a riverbank, invisible text is a worse failure
   than a font swap.
6. **Preload only the one file the first screen needs**:
   `<link rel="preload" as="font" type="font/woff2" crossorigin>`. Preloading all
   three undoes the subsetting.

## Finding candidates

The installed `ui-ux-pro-max` skill carries `data/google-fonts.csv` (749KB) and
`data/typography.csv` with ~74 pairings. Filter for variable axes and for
Cyrillic + Latin Extended coverage — the intersection is much smaller than the
full catalogue, and that is the real shortlist.

Verify coverage rather than trusting the metadata:

```bash
.venv/Scripts/python.exe -c "from fontTools.ttLib import TTFont; f=TTFont('path.ttf'); cm=set(f.getBestCmap()); print([hex(c) for c in (0x105,0x107,0x119,0x142,0x144,0x15B,0x17A,0x17C) if c not in cm] or 'PL ok'); print('CYR ok' if 0x430 in cm else 'CYR missing'); print('axes', [a.axisTag for a in f['fvar'].axes] if 'fvar' in f else 'STATIC')"
```

## Budget

`tests/test_palette.py` already enforces a size budget on the two images. **Extend
it to cover `app/web/static/fonts/`**, per-file, so a later "just add a weight"
fails the suite instead of quietly costing 60KB.

Suggested ceilings — set them from the real files, do not invent generous ones:

| File | Ceiling |
|---|---|
| latin (variable) | 30KB |
| latin-ext (variable) | 20KB |
| cyrillic (variable) | 25KB |

## Setting the type, once it is chosen

Carried over from `docs/17 §2`, all still true:

- **Tracking tightens as size grows.** A heading at display size with body
  tracking reads loose. Use a `--track-tight` token on headings.
- **More space above a heading than below it.** The gap belongs to the section
  boundary, not to the heading-and-body pair.
- **`font-variant-numeric: tabular-nums`** on anything that counts or tabulates,
  so a column of weights does not jitter.
- **`text-wrap: balance`** on headings to prevent widows.

## Checklist before phase 5

- [ ] variable, self-hosted, three `unicode-range` blocks
- [ ] Polish diacritics verified present in the actual file, not assumed
- [ ] `font-display: swap`, system stack fallback
- [ ] exactly one preload, for the first screen
- [ ] no new CSP origin; `test_no_third_party_font_origin_is_admitted` still green
- [ ] font size budget added to `tests/test_palette.py`
- [ ] licence permits self-hosting, and the licence file is committed
