# 19 — The cosy tackle brief

Branch `claude/design-cosy-tackle`. Owner's brief, 2026-08-28, given after the
Waterline design shipped and was rejected (`docs/18b` D1).

## The brief, in the owner's words

> minimalistick round shapes, custom fonts, pastel colors with green yelow,
> orange and khaki. Use fishing atributes as fishing rodes, reels, floats, lures
> as icons and decore elements, make them interactive, create corelated
> animation, ex. fish splaszes bites ect. at the background and across the web
> page made time to time litle fishes of difirent species jump and dive. Vibes
> shoud be cosy and comfortable.
>
> fill free to use any style and format, for desing on this branch forgot all
> previos desine and style recomendations set on this project BUT NUT THE
> STRUCTURE AN LOGIC of the app

## What that releases — on this branch only

Every one of these is now **void** and must not be reimposed by a later session
citing the document it came from:

| Released | Was |
|---|---|
| The Waterline palette entirely | `docs/17 §1` — navy ink, pale water, reed green |
| The waterline signature element | `docs/17 §3` — the 2px rippling line |
| "Pastel light blue and white" | standing rule 8, `docs/10 §2` |
| The no-webfont decision | `docs/17 §2` — already reversed by `docs/18b` D3 |
| The minimal motion budget | `docs/17 §4` — "deliberately small … a card that flies 40px reads as a website" |
| "Like an instrument, not an app" | standing rule 8. The brief now asks for the opposite: **cosy**. |
| The refusal of decorative imagery in-app | `docs/18b` D2's Excalidraw register |

The brief actively **inverts** two of those. Ambient fish crossing the page and
tackle used as decoration are exactly what the instrument reading forbade. That
is the owner's call, made explicitly, and it is not to be argued back.

## What it does not release

The owner drew the line themselves: **structure and logic**. Concretely:

| Kept | Why it is structure, not style |
|---|---|
| The five laws in `CLAUDE.md` | CPUE not catch count; no fishing knowledge in code; predictions immutable; never fabricate an observation; sample size travels with every number |
| Jinja2 + HTMX, no build step | ADR 0001. The stack, not the skin. |
| The fixed flow order | standing rule 5: home → map → spot → method and rods → catch logging |
| Every feature keeps working | the phase 1 feature inventory is the contract |
| No raw score; colour band only | standing rules 2 and 16 — that is what the engine honestly produces |
| Green good, red bad on day bands | standing rule 3. **The palette must not break this**, and a green/yellow/orange brief makes it easy to. |
| Nothing is ever deleted; soft removal, per angler | standing rule 18 — there is a real second user |
| Per-species fish geometry | `CLAUDE.md` icon rules. Not a style rule — an icon set where every fish is one drawing recoloured teaches the angler nothing. The brief **needs** this: "litle fishes of difirent species" only works if the species read differently. |
| WCAG AA on every pair | `tests/test_palette.py` fails the suite. This is a test, not a preference. |
| 48px targets, thumb zone | the app is used one-handed at a waterside |
| Rebuild the container after code changes | standing rule 20 |

## Three tensions in the brief, and how they resolve

**1. Pastel plus AA contrast.** Pastels sit in a narrow lightness band, so pastel
text on pastel ground cannot reach 4.5:1. Resolution: green, yellow, orange and
khaki carry **grounds, fills, tackle and decoration**; a deep forest or bark ink
outside the band carries **all text**. Nothing changes about the brief's feel —
the pastels are still what you see.

**2. Green, yellow and orange as the palette, versus green-good/red-bad day
bands.** The brief's palette occupies three of the four traffic-light positions.
If the ambient palette is yellow-orange, an orange day band stops reading as a
warning. Resolution: **the day bands are reserved colour.** No decorative element
may use a band hue at band saturation. This needs stating in the token layer, not
remembering.

**3. Ambient fish animation, versus a phone on a riverbank.** An earlier owner
brief asked for no heavy animation because of weak signal and battery. This brief
asks for fish crossing the page. These reconcile if the motion is built right,
and not otherwise:

- inline SVG and CSS only — **zero bytes**, no library, no sprite sheet
- `transform` and `opacity` only, so nothing can force layout
- no `requestAnimationFrame` loop; CSS keyframes the compositor owns
- **paused when the tab is hidden**, via `document.visibilityState`
- `prefers-reduced-motion` removes the crossings and keeps the fades
- ambient motion is decorative, therefore `aria-hidden`, and never carries state

Built that way the fish cost bytes nothing and battery almost nothing. Built with
a JS loop and PNG sprites they would be the heaviest thing in the app. **This is
a constraint on implementation, not a limit on the brief.**

## Surface split

`docs/18b` D2 stands: `/welcome` and the in-app screens are two treatments under
one palette and one typeface. The brief's decorative ambition lands harder on
`/welcome`; the in-app screens keep the cosiness but stay usable in one hand,
in sunlight, mid-session.

## What is being designed

Sixteen templates, five of them the fixed flow:

`base` · `home` · `today` · `lake_detail` · `spot_start` · `zone_start` ·
`session_active` · `session_end` · `catch_edit` · `history` · `place_new` ·
`auth_login` · `auth_register` · `landing` · `error` · `_fish_icons`
