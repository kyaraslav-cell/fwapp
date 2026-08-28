# 18 — Design tooling and assets: what is worth using

Research for the owner's question of 2026-08-28: *what tool or workflow produces a
clean, minimal, pastel redesign of an existing app, keeps every feature working,
and stays fast and one-handed at the waterside?*

Reference sites the owner supplied: screen.studio, postmarkapp.com, hey.com,
bear.app, museapp.com, craft.do, are.na, excalidraw.com, cal.com, usefathom.com.

Nothing here has been installed or run. This is the survey; the decisions are in
§7 and are the owner's.

---

## 0. The finding that decides most of the rest

**A design "skill" is a markdown briefing. It cannot see your codebase and it
cannot see the rendered page.** Every published review agrees, including one
written by a vendor selling the alternative. That matters more here than in most
projects, because `CLAUDE.md` already carries the same lesson learned the
expensive way:

> Visual design cannot be checked from your own diff. The species icons were
> declared "redrawn" three times and still looked identical.

So the question is not "which skill has the best taste". A skill supplies taste;
what actually prevents shipping a broken redesign is the render-and-compare loop,
and **this repository already has a better one than anything off the shelf**:

| Already built | Does |
|---|---|
| `tools/design_sheet.py` | 6 pages × 2 widths, before beside after |
| `tools/palette_check.py` + `tests/test_palette.py` | WCAG AA for every pair, fails the suite |
| `tools/waterline_filmstrip.py`, `animation_filmstrip.py` | pins animations to exact progress, tiles frames |
| `tools/icon_sheet.py --compare` | old icon set beside new, through the real stylesheet |
| `tools/site_audit.py` + nightly job | accessibility and console violations, unattended |

The gap is not tooling. The gap named in `docs/17 §9` is that **nothing has been
checked on a real phone.** Headless Chromium at 390px is not an iPhone in
sunlight.

---

## 1. Design skills, category by category

### 1a. Style-preset skills — the wrong shape for this app

Anthropic's own `frontend-design` plugin is the most-installed design plugin in
the official directory (~277k installs by mid-2026). Its SKILL.md prescribes a
two-pass loop: brainstorm a compact token system (4–6 colours, 2+ typefaces, a
layout concept, a signature element), self-critique it against "would I produce
this for any similar brief", then build, then screenshot and critique again.

That is a good loop. But the skill is written for a blank page. It has **no
notion of an existing design system**, and Snyk's independent round-up flags it
directly: *"opinionated toward bold aesthetics; may not suit projects requiring
strict consistency."* Fishlog has a documented system, a locked accent, a token
alias layer that 268 declarations depend on, and a test that fails on a contrast
regression. Pointed at `style.css`, a preset skill argues with all of it.

Same verdict for `awesome-design-skills` (67 named aesthetics), `Taste` (anti-slop
rules, scoped to landing pages and portfolios), and the `Nothing` skill
(monochrome instrument aesthetic — thematically close to standing rule 8's "like
an instrument, not an app", but the wrong palette and a single fixed look).

`UI/UX Pro Max` is a different architecture — a searchable database (a
1,775-line design database, ~1,924 font pairings, palettes, anti-patterns) rather
than a rulebook. Useful as a **lookup** when choosing a pastel scale or a type
pairing. It ships a Python CLI; Snyk explicitly recommends reviewing its
`search.py` before installing. Treat it as a reference book, not a workflow.

### 1b. Audit skills — the shape that does fit

Two skills work *against an existing UI* rather than replacing it:

- **`vercel-labs/agent-skills` → web design guidelines.** ~100 rules covering
  accessibility, performance and interface behaviour. A read-only quality gate.
  Its sibling skills (React best practices, composition patterns, React Native)
  are irrelevant here — the stack is Jinja2 and HTMX.
- **`ibelick/ui-skills`.** Accessibility, spacing and motion clean-up on UI that
  already exists. Explicitly does not generate new designs.

Both complement `tools/site_audit.py` instead of duplicating it: the nightly
audit catches violations in the rendered page, these catch them in the code.

`accesslint/claude-marketplace` is narrower still (contrast, use-of-colour, link
purpose) and has very low adoption (~8 stars). `tools/palette_check.py` already
does the contrast half better, because it knows the token graph.

### 1c. Design agents that render — the interesting category, with a blocker

**Superdesign** (`superdesigndev/superdesign`, plus a skill install) generates
several UI directions at once on an infinite canvas, extracts an existing app's
design system, designs into it, and renders the result before you commit. That is
architecturally the right answer to §0.

Two blockers for Fishlog:

1. **It hands back React and Tailwind.** ADR 0001 and standing rule 1 say
   server-rendered Jinja2 + HTMX, no build step, and the owner considered React
   and chose against it. Output would have to be transcribed by hand, which
   throws away the part that made it trustworthy.
2. It needs external API access (Gemini/Claude) with its own cost and rate
   limits.

Also worth stating plainly: the most thorough comparison of design skills online
is published on Superdesign's own blog. It discloses the conflict and its
technical claims check out against the other sources, but it is a vendor
document.

**Verdict:** worth an hour's trial for *exploring directions*, not as the
pipeline.

### 1d. The `design` skill already available in this session

Claude Design's canvas — multi-artboard mockups published as an Artifact, which
the owner can pan, zoom and edit by hand, then export. Costs nothing extra and
touches no application code.

This is the cheapest way to **decide the look before `style.css` is opened**,
which is exactly where the last redesign spent its rework. It produces mockups
only; it does not restyle the app.

### 1e. Browser MCPs

`Claude in Chrome` (already available here), Playwright MCP and Chrome DevTools
MCP all give an agent eyes. The published comparisons converge on: Playwright for
structured element data, DevTools MCP for performance and network, Claude in
Chrome for quick visual checks on a logged-in app. Fishlog needs a logged-in app
and already drives Playwright in `tools/site_audit.py`, so there is nothing
missing — except that **this session could not screenshot**, because the browser
pane is not displayed. Worth knowing before planning any visual work in a
non-interactive session.

### 1f. Figma

Figma's Dev Mode MCP is the mature path from a visual design file to code tokens.
It presumes the owner wants to design in Figma. If not, it is a seat and a skill
to learn for no gain here.

---

## 2. What the reference sites actually do — measured, not remembered

Loaded each at a 375px viewport and read the computed styles.

| Site | Ground | Body face | Images | Inline SVG | Video | Webfont families |
|---|---|---|---|---|---|---|
| craft.do | `#fcf9f7` warm off-white | Untitled Sans, serif H1 at -1.92px tracking | **166** | 112 | 0 | 4+ |
| cal.com | `#f4f4f4` | Cal Sans, black buttons, 8px radius | 71 | 78 | 0 | **8** |
| usefathom.com | `#181b19` near-black | custom "sw", H1 weight 460, -1.32px | 42 | 28 | 0 | 3 |
| bear.app | white | bearsans / bearsansheadline | 32 | 21 | **2** | 3 |
| hey.com | white | Moniker; H1 "Really Sans Large" **weight 900**, 35px pill buttons | 15 | 6 | 1 | 4 |
| screen.studio | **black** | system stack (`BlinkMacSystemFont`/SF Pro) | 19 | 0 | **2** | 3 |
| excalidraw.com | white | hand-drawn (Excalifont, Virgil) | **0** | 32 | 0 | 8 |

Three things fall out of that table.

**One of these is an application; the other nine are marketing pages.**
Excalidraw is the only one where you land in the product, and it is the only one
with **zero raster images**. Craft's 166 images are a sales pitch, not an
interface. If the reference set is meant to guide the *in-app* screens, Excalidraw
is the only relevant row; if it is meant to guide `/welcome`, the other nine are.
These are two different jobs and they should not get the same treatment.

**Every one of them loads custom webfonts** — cal.com loads eight families.
`docs/17 §2` deliberately removed webfonts from this app, because the UI ships
Latin, Polish and Cyrillic, so no useful subsetting is possible and a display face
costs ~60KB per weight before any text paints. None of the reference sites carry
that constraint: they are English-only. **This is a real trade, and it is the
single biggest visual difference between Fishlog and the sites the owner likes.**
Their distinctiveness is substantially *the typeface*.

**Only screen.studio is dark**, and it is a video-editing tool used indoors.
`docs/17 §9` refused dark mode because a light ground is what reads in sun. That
still holds.

---

## 3. Making quality assets, cheapest first

Ordered by bytes-on-the-wire, which is the binding constraint at a riverbank.

### 3a. Zero bytes — CSS and inline SVG

The premium feel of most of the reference sites is not photographs. It is grain,
gradient and spacing.

- **SVG `feTurbulence` noise as a `data:` URI.** Five to ten lines, stacked as a
  background layer, no file and no request. It breaks the colour banding that
  makes a flat pastel gradient look cheap, and reads as film grain. Generators:
  `fffuel.co/nnnoise`, `ultimatedesigntools.com`.
- CSS `linear-`/`radial-`/`conic-gradient`, CSS-drawn shapes, `mask-image`.
- The waterline in `docs/17 §3` is already this idea: one element, two custom
  properties, no image, brand mark and loading indicator at once.

This is where "looks expensive, weighs nothing" comes from. Exhaust it before
generating anything.

### 3b. Inline SVG icon sets — pick one, never mix

For **interface** icons (not the species fish, which `CLAUDE.md` governs
separately and forbids sharing geometry):

| Set | Count | Character | Note for this app |
|---|---|---|---|
| **Tabler** | 5,500+ | outline, 24px grid | has **granular weather states** — directly relevant to a weather-driven app, and the reason to prefer it here |
| **Lucide** | 1,500+ | one strict refined outline, 24px grid | shadcn's default; safest, most consistent |
| **Phosphor** | 1,200+ | **6 weights** incl. duotone | duotone is the "visual warmth" look consumer fintech uses; a way to get pastel *into* the icons |

All three are permissively licensed and can be self-hosted as a **single SVG
sprite** — one request, cached forever, no build step, no npm. Mixing two sets is
the fastest way to make an interface look assembled rather than designed.

### 3c. AI vector — Recraft, for the icons no library has

Recraft is the only generator producing **native SVG** rather than a raster to be
traced. Its Brand Style Lock takes 5–10 reference images and learns palette, line
weight, illustrative style and proportion, so a 20-icon set holds together.

The consistent criticism across 2026 reviews is **anchor-point sprawl**: output
arrives as excessive points and redundant layers and needs cleanup before it is
production-ready. Reviewers put it at roughly "4 hours of cleanup becomes 30
minutes", not "zero".

Where it earns its place: things no icon library contains — a bivvy, a bite
alarm, a swim, a method feeder, a weed edge. Not for generic UI glyphs, where
Tabler is free and cleaner.

### 3d. AI raster — the method already in the repo is the right one

`docs/17 §5` generates two stills through kie.ai (`seedream/5-pro-text-to-image`)
using **one style preamble reused verbatim**, which is why they read as a set. That
is the correct technique and it is already wired, already committed, already
build-time-only so a deployment never calls the API.

If a wider set is ever needed, the 2026 alternatives that beat single-prompt
consistency:

- **Flux 2 Pro** — multi-reference mode, up to 10 reference images, currently
  rated ahead of Midjourney for repeat-asset consistency.
- **Midjourney `--sref`** — best aesthetic coherence for mood and editorial
  feel; poor at repeating the same object across many frames.
- **Ideogram** — the leader whenever text must render inside the image.
- **Recraft brand kit** — as above, and the only vector option.

### 3e. The part that actually decides quality

`tools/design_assets_pack.py` crops, cools, resizes and compresses. Both fixes it
performs were found by looking at the output, not by prompting better:

- the hero came back with two thirds empty sky and rendered as a featureless
  rectangle in a 200px band, so it is cropped at build time;
- both images came back warmer than the palette, so they are cooled per channel
  at build time rather than with a CSS filter that would cost a repaint per
  scroll frame.

Result: 18.8KB desktop / 4.0KB phone for the hero. **The generator is a small
part of the outcome; the post-process is most of it.** Any new asset source must
go through this step.

---

## 4. Pastel, and why it is harder than it looks

Pastels cluster in a narrow lightness band — roughly 70–85 in OKLCH — so pastel
foreground on pastel ground almost never reaches the WCAG AA 4.5:1 needed for
body text (3:1 for large text and for non-text UI components since WCAG 2.1). The
published guidance is *not* to abandon pastels but to keep them for **grounds,
fills and secondary surfaces** and anchor the design with structural colours
outside the band.

That is what the current tokens already do: `--canvas #eef4f4` and
`--surface-sunk #f4f9f9` are pastel grounds; `--ink #0f2c40` is the structural
anchor. Three tokens were darkened by 1–8% at design time because
`tools/palette_check.py` said so, and the change cleared the two contrast
failures the nightly audit had been reporting.

So the honest position is: **the app is already pastel — pastel ground with dark
ink.** What the owner may be asking for is either a *lighter, bluer* ground, or
pastel *accents* alongside the single locked green, or simply the earlier
light-blue scheme back. Those are three different changes.

---

## 5. The field constraint, which pushes the same way

Published mobile-UX guidance, and the actual condition of use:

- **Sunlight collapses perceived contrast.** High contrast and a matte, light
  ground are what remain readable outdoors. This is the second reason to refuse
  dark mode, independent of taste.
- **Thumb zone.** The bottom third of the screen, biased toward the holding
  hand, is where a thumb rests on a one-handed grip. Primary actions belong
  there; destructive ones belong out of reach.
- **Touch targets.** 44×44px minimum (Apple), 48×48 (Google). The running-session
  float is already 44px.
- **One primary action per screen.** Everything else hidden behind a control.
  This is standing rule 14 ("one sentence under a control, never a paragraph")
  applied to layout rather than copy.

The fixed flow — home → map → pick a spot → method and rod count → catch
logging (standing rule 5) — is five screens. Each should be checked for exactly
one primary action, in the thumb zone, at 48px.

Nothing in the reference set was designed for this. They are read on a desk.

---

## 6. Two conflicts the owner has to resolve

**6a. Pastel versus Waterline.** Standing rule 8 says "pastel light blue and
white". `docs/17` records that as **superseded today, 2026-08-28**, by navy ink
on pale water with one reed-green accent — quoting the owner's own brief, which
said "blu navy green pastel colors". Today's request says pastel again. Either
the Waterline design has not been seen yet, or it has and it is not light enough.
Not the same fix.

**6b. Typeface versus weight.** Every reference site buys its distinctiveness
with a custom face; `docs/17 §2` sold that distinctiveness for 0 bytes and three
alphabets. Keeping the system stack means the app will never look like hey.com,
because a large part of what makes hey.com look like hey.com is Really Sans Large
at weight 900. A middle path exists — one variable display face, headings only,
Latin subset with a system fallback for Cyrillic — at roughly 15–25KB, self-hosted
so no new CSP origin is admitted.

---

## 7. Recommendation

1. **Do not install a style-preset skill.** It cannot see `style.css`, it will
   fight `docs/17`, and the loop it replaces is already better here.
2. **Write a project skill instead** — `.claude/skills/restyle/` — encoding what
   is specific to this app: read `docs/17` first; propose colours only in the
   token layer, never in the alias block; run `tools/palette_check.py` before
   choosing; run `tools/design_sheet.py` and put the before/after in front of the
   owner rather than describing it; check the five flow screens at 390px for one
   thumb-zone primary action each. Generic skills cannot supply this.
3. **Add `vercel-labs/agent-skills` web design guidelines** as a read-only audit
   pass, after reviewing its contents.
4. **Use the built-in `design` canvas skill to decide the look first**, as
   mockups, before any CSS is touched. That is where the last redesign's rework
   went.
5. **Assets: exhaust §3a and §3b before generating anything.** A sprite from one
   icon set plus SVG grain will carry more of the "clean and expensive" feel than
   any generated picture, at a fraction of the bytes. Reserve Recraft for the
   fishing-specific glyphs no library has, and keep kie.ai for the one or two
   photographic bands.
6. **Verify on a real phone.** It is the one gap the tooling cannot close, and
   `docs/17 §9` already admits it.

---

## Sources

Skills and agents: [Anthropic frontend-design SKILL.md](https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md) ·
[Snyk, Top 8 Claude Skills for UI/UX Engineers](https://snyk.io/articles/top-claude-skills-ui-ux-engineers/) ·
[Superdesign, Design Skills Reviewed 2026 (vendor-authored, disclosed)](https://superdesign.dev/blog/design-skills-reviewed) ·
[superdesigndev/superdesign](https://github.com/superdesigndev/superdesign) ·
[Best Claude Code Plugins for Design, Claude Directory](https://www.claudedirectory.org/plugins/topic/design)

Browser tooling: [Playwright MCP vs Chrome DevTools MCP vs Claude in Chrome](https://stevekinney.com/courses/self-testing-ai-agents/runtime-tools-compared)

CSS and tokens: [Open Props vs Tailwind v4, 2026](https://www.pkgpulse.com/guides/open-props-vs-tailwind-v4-2026) ·
[CSS frameworks and UI libraries 2026](https://www.youngju.dev/blog/culture/2026-05-16-css-frameworks-ui-libraries-2026-tailwind-4-shadcn-radix-mantine-chakra-open-props-unocss-pandacss-deep-dive.en)

Icons: [Lucide vs Heroicons vs Phosphor 2026](https://www.pkgpulse.com/guides/lucide-vs-heroicons-vs-phosphor-react-icon-libraries-2026) ·
[Best open-source icon libraries compared 2026](https://mantlr.com/blog/best-open-source-icon-libraries-compared)

Image and vector generation: [Recraft AI review 2026](https://www.svggenie.com/blog/recraft-ai-review-2026) ·
[Recraft V4 SVG guide](https://ropewalk.ai/blog/recraft-v4-pro-svg-guide-2026) ·
[Midjourney vs Ideogram vs Flux vs Recraft 2026](https://www.pravinkumar.co/blog/ai-generated-images-midjourney-ideogram-flux-recraft-2026)

Assets and texture: [nnnoise SVG noise generator](https://www.fffuel.co/nnnoise/) ·
[CSS noise and grain generator](https://ultimatedesigntools.com/tools/noise-generator/)

Pastel and contrast: [Why pastel palettes fail in production](https://colorarchive.org/notes/april-2026-pastel-palettes-production/) ·
[Colour contrast and WCAG guide 2026](https://ultimatedesigntools.com/blog/color-contrast-wcag-guide/)

Mobile and field use: [Mastering the thumb zone](https://parachutedesign.ca/blog/thumb-zone-ux/) ·
[Designing a mobile UI for bright sunlight](https://www.linkedin.com/advice/3/how-can-you-design-mobile-app-user-t85ue)

Reference sites were measured directly at a 375px viewport on 2026-08-28, not
cited from memory.
