# 03 — Palette: pastel that passes

## The problem, stated honestly

Pastels sit in a narrow lightness band — roughly **70–85 in OKLCH**. Two colours
from inside that band have almost no contrast against each other, so pastel text
on a pastel ground essentially never reaches the AA floor of **4.5:1** for body
text (3:1 for large text and for non-text UI components, since WCAG 2.1).

The fix is not to abandon pastel. It is to give pastel a job it can do:

| Role | Lightness | Carried by |
|---|---|---|
| grounds, recessed grounds, inset surfaces | inside the pastel band | pastel |
| fills, tinted washes, band backgrounds | inside the pastel band | pastel |
| body text, headings, icon strokes | **far outside** the band | the structural anchor |
| the single accent | between them, ≥3:1 on every ground it lands on | one locked colour |

The current tokens already do this — `--canvas #eef4f4` is a pastel ground,
`--ink #0f2c40` is the anchor. Whatever replaces them keeps the shape.

## The two-layer structure — do not collapse it

```
:root {
  /* layer 1 — the palette. Real colours live here and only here. */
  --canvas: …;  --surface: …;  --ink: …;  --accent: …;

  /* layer 2 — the aliases. Legacy role names mapped onto layer 1. */
  --bg: var(--canvas);  --text: var(--ink);  --primary: var(--accent);
}
```

**268 declarations consume the layer-2 names.** That is what let the last re-skin
change the whole app without touching one template, and without breaking the
inline JS bindings or `tests/test_template_element_ids.py`.

**Never write a literal colour in layer 2.** A colour defined there is invisible
to `tools/palette_check.py`, which walks the token graph — so it will not be
contrast-tested, and the suite will pass while the app fails.

## Method

1. **Pick the anchor first, not the pastel.** Text legibility is the hard
   constraint; the pretty part has more freedom. Tint the anchor from the hue
   family — a flat grey on a cool ground reads as dirt.
2. **Derive grounds from the anchor's hue**, at pastel lightness. Two or three
   steps: canvas, recessed canvas, raised surface, inset surface.
3. **One accent, locked app-wide.** Check it against every ground it can land on.
4. **Retune the four day bands last**, keeping traffic-light semantics — green
   good, red bad (standing rule 3) — and check `--ink` against the worst of them.
5. **Run the checker before committing to anything.** Not after.

```bash
.venv/Scripts/python.exe tools/palette_check.py
.venv/Scripts/pytest.exe -q tests/test_palette.py
```

Expect to darken two or three tokens by 1–8% because the checker says so. That
happened last time and it is normal. **A palette that does not pass is not a
palette** — do not carry a failure forward on the promise of fixing it later.

## Lookup, not authority

The installed `ui-ux-pro-max` skill carries 192 product palettes with reasoning
profiles. Use it to *find candidates*. It does not know this app's grounds, its
day bands, or its daylight constraint, so every candidate still goes through
`palette_check.py` before it means anything.

## Checklist before phase 4

- [ ] every foreground/ground pair ≥ 4.5:1 (3:1 for large text and UI components)
- [ ] the accent ≥ 3:1 on every ground it appears on
- [ ] `--ink` clears AA on all four day bands
- [ ] day bands still read green-good / red-bad
- [ ] no literal colour anywhere in the alias layer
- [ ] the palette is legible in daylight — a light ground, not a dark one
- [ ] `tests/test_palette.py` green
