# 06 — Assets: a ladder, climbed in order

Every rung costs bytes the one below it did not. **Exhaust each before opening
the next**, and be able to say why the previous rung could not do the job.

The premium feel of the reference sites is mostly *not* photography. It is grain,
gradient, spacing and type. Those are the cheapest things on this list.

---

## Tier 0 — 0 bytes: CSS and inline SVG

No request, no file, nothing to cache, nothing to fail on bad signal.

**Grain.** A flat pastel gradient bands visibly on a phone screen and reads
cheap. SVG `feTurbulence` as a `data:` URI fixes it for nothing:

```css
.ground::before {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  opacity: .035;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
```

Keep opacity ≤ 0.05 or it reads as a dirty screen. Generators if hand-tuning is
slow: `fffuel.co/nnnoise`, `ultimatedesigntools.com/tools/noise-generator/`.

**Also free:** gradients (`linear-`, `radial-`, `conic-`), `mask-image`,
`border-radius` shapes, `box-shadow` depth, CSS-drawn rules and dividers.

**The model to copy is already in the repo.** The waterline (`docs/17 §3`) is one
element and two custom properties, and it is simultaneously the brand mark, the
tap feedback and the HTMX loading indicator. No image. That is what tier 0 looks
like done well.

---

## Tier 1 — one sprite: the interface icon set

One SVG sprite, one request, cached forever, no build step, no npm.

**Pick one set and never mix.** Two sets in one interface is the fastest way to
look assembled rather than designed.

| Set | Count | Character | When it wins |
|---|---|---|---|
| **Phosphor** | 1,200+ | **6 weights** incl. duotone | duotone puts pastel *inside* the glyph, not just around it — the strongest fit for a pastel direction |
| **Tabler** | 5,500+ | outline, 24px grid | **granular weather states** — this is a weather-driven app, and no other set covers them |
| **Lucide** | 1,500+ | one strict refined outline | safest and most uniform; least character |

All three are permissively licensed and self-hostable. Commit the sprite; do not
fetch from a CDN.

```html
<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#thermometer"/></svg>
```

Rules: `aria-hidden="true"` on decorative icons; `aria-label` on any icon-only
button; `currentColor` for the stroke so the icon inherits the token; size in
`em` so it scales with its text.

**The species fish are not in this tier.** `CLAUDE.md` governs them separately:
per-species geometry, the tail alone must identify the fish, curved bezier forms
only, no shared path recoloured. An icon library cannot supply that and must not
be used to.

---

## Tier 2 — Recraft: bespoke vector, only for what no library has

Recraft is the only generator producing **native SVG** rather than a raster to
trace. Brand Style Lock takes 5–10 reference images and learns palette, line
weight and proportion, so a set holds together.

**Use it only for glyphs no library contains** — bivvy, bite alarm, method
feeder, swim, weed edge, rod pod, marker float. Not for generic UI glyphs, where
tier 1 is free and cleaner.

Budget cleanup. Every 2026 review reports the same weakness: output arrives with
excessive anchor points and redundant layers. The honest figure is "four hours of
cleanup becomes thirty minutes", not zero. Run everything through SVGO, then
open the file and look at the path data.

Commit the results. A deployment must never call an image API.

---

## Tier 3 — kie.ai raster: only where a photograph is the content

The method already in the repo is the right one and is already wired:

```bash
bash tools/design_assets.sh && .venv/Scripts/python.exe tools/design_assets_pack.py
```

`seedream/5-pro-text-to-image` through the scrollcraft skill's `kie.mjs`, with
**one style preamble reused verbatim across every generation** — that single
discipline is why two separately generated stills read as one set. Key is
`KIE_AI_API_KEY` in `.env`; needed only to regenerate, since outputs are
committed and build-time only.

If the set outgrows single-prompt consistency:

| | Strength | Weakness |
|---|---|---|
| **Flux 2 Pro** | multi-reference, up to 10 images — best repeat consistency | less characterful |
| **Midjourney `--sref`** | best mood and editorial coherence | poor at repeating one object across frames |
| **Ideogram** | the only one to trust with text inside the image | weaker aesthetics |
| **Recraft brand kit** | vector, and the same lock as tier 2 | raster is not its strength |

**Budget: at most two raster images in the app.** `/welcome` may have more (D2).

---

## The post-process is most of the quality

`tools/design_assets_pack.py` exists because both of its steps were discovered by
looking at output, not by prompting better:

- **Crop at build time.** seedream composed the hero with two thirds empty sky —
  correct for a full frame, useless in a 200px band, where it rendered as a
  featureless rectangle. Cropping in CSS does not fix this; the shipped file is
  cropped.
- **Cool at build time.** Both images returned warmer than the palette, and a
  cream sky against a cool canvas reads as a different design. Done per channel
  at build time because a CSS filter on a large image costs a repaint per scroll
  frame.

Result: 18.8KB desktop, 4.0KB phone. **Any new raster source goes through this
step.** A generator you like is worth less than a pack step you ran.

## Size budget

`tests/test_palette.py` enforces the image budget. Extend it for anything new —
fonts (see `04-typography.md`), the icon sprite, any added still. A budget that is
not a test is a wish.

## Checklist before phase 6

- [ ] tier 0 exhausted — grain and gradient tried before any file was added
- [ ] exactly one icon set, self-hosted as one sprite, committed
- [ ] icons use `currentColor`, decorative ones `aria-hidden`
- [ ] species fish untouched by any library set
- [ ] every generated vector run through SVGO and read
- [ ] every raster through `design_assets_pack.py`
- [ ] no runtime call to any image API
- [ ] size budget extended to cover every new asset
