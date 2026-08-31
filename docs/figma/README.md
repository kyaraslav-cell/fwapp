# Figma handoff — what to give a design agent

Three files. Hand an agent **all three**, in this order:

| File | What it is | Format |
|---|---|---|
| [`tokens.json`](tokens.json) | Every colour, size, radius, shadow and easing | W3C DTCG — Tokens Studio imports it directly as Figma Variables |
| [`screens.json`](screens.json) | Every screen, its elements **in paint order**, and the flow between them | Plain JSON, written to be read by a model |
| This file | The routing map and the rules that are not obvious | Markdown |

## First, the honest part

**There is no `.fig` file here and I cannot make one.** The Figma file format is
a proprietary binary; nothing outside Figma writes it. Anyone who hands you a
"generated .fig" has either used the REST API against a live file or is wrong.

What actually works, in descending order of how well it works:

1. **Tokens Studio plugin** → import `tokens.json` → push to Figma Variables.
   This is the only step that is genuinely automatic and lossless.
2. **A design agent reading `screens.json`** and building frames. It has the
   element order, the token names, the sizes and the constraints.
3. **The Figma REST API**, which can *read* a file and write comments, but
   cannot create layers. Do not plan around it drawing anything.

## Routing map

```
                    ┌─────────────────────────────┐
                    │  /welcome  (signed out only)│
                    │  marketing register — NOT   │
                    │  part of the flow           │
                    └──────────────┬──────────────┘
                                   │ sign in
                                   ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║  THE FIVE-SCREEN FLOW — the order is fixed, not a suggestion  ║
  ╚══════════════════════════════════════════════════════════════╝

   1. /                     home · your waters
        │  tap a water
        ▼
   2. /lake/{slug}          conditions + map          ◄──────────┐
        │  tap the map, or drag the fish pin onto it             │
        ▼                                                        │
   3. /lake/{slug}/spot     method + rod count                   │
        │  Start session                                         │
        ▼                                                        │
   4. /session/active       running session ──────────────────────┤
        │  End session            Conditions / Map (must stay
        ▼                          reachable mid-session)
   5. /session/end          end, incl. a BLANK
        │  Save
        ▼
      /history              sessions, blanks, fish per hour

  Off to the side:
      /places/new           add a water          ← from home
      /session/catch/{id}/edit                   ← from the session
      /auth/login, /auth/register
      404 / 500
```

Two edges matter more than they look:

- **`/lake` does not redirect to a running session.** It shows a banner and
  stays. Conditions and the map are exactly what an angler wants while sitting
  behind a rod.
- **A floating session button** appears on every screen while a session runs,
  except the session screen itself.

## Prompt to give the agent

> Build a Figma design file for a fishing app read one-handed on a phone,
> outdoors, on bad signal.
>
> `tokens.json` is the complete design system. Use only these values; do not
> invent a colour. `screens.json` lists every screen with its children in paint
> order, with token names on each — follow that order exactly.
>
> Draw every screen at 390×844 first. Desktop (1280×900, 960px centred column)
> is an adaptation, not the target.
>
> Read the `rules` array in `screens.json` before you start and treat every
> entry as a hard constraint.

## The five rules an agent will break unless told

These are the ones that look like improvements and are not.

**1. Never draw a score.** Not a percentage, not "7.4/10", not a star rating,
not a progress arc, not a gauge that fills further on a better day. Fishing
quality is a **colour band and a word**. The one ring in this design is a
**full** ring for exactly this reason — a partial arc is a progress bar, and a
progress bar is a score wearing a hat.

**2. Every number carries its `n`.** A zone scored from three sessions and one
scored from ninety must not look alike. If you draw a number with no sample
size beside it, you have drawn a lie.

**3. Green good, red bad — and the four band marks are reserved.** The palette
is green, yellow, orange and khaki, which is three of the four traffic-light
positions. So decoration may never use a band **mark** hue at mark saturation.
A band hue appears **only** where a day is being reported. This is the single
easiest thing to get wrong in this design.

**4. Blank sessions are not errors.** A session with zero fish is data, is
counted in every statistic, and must be as easy to record as a good day. Do not
give it a warning tone, a sad face, or an empty-state illustration that implies
failure.

**5. Every species owns its geometry.** Six ambient fish, and the **tail alone**
must identify each with the body hidden — a crucian's tail is a rounded fan, a
bream's is a long unequal fork, a carp's is broad and shallow. One silhouette
recoloured six times is worth less than no fish at all. Curved bezier outlines
only; no polygon fins, no triangle standing in for a tail. The dorsal is part of
the body outline, never an arc floating above it.

## Things that are decided and not open

- **No dark mode.** Sunlight collapses perceived contrast; a light matte ground
  is what survives it. This is a field constraint, not a preference.
- **No sharp corners.** 20px cards, 13px buttons, 999px pills.
- **48px minimum touch target**, 8px apart, primary action in the bottom third.
- **One primary action per screen.**
- **No fake iOS status bar and no fake keyboard** in any frame.
- **One accent, locked app-wide.** A green app does not grow a blue button on
  one screen.

## Contrast

Every pair in `tokens.json` is measured by `tools/palette_check.py`, and
`tests/test_palette.py` fails the build when one drops below its minimum. Three
values in this palette were darkened at design time **because the checker said
so**, not because anyone preferred them.

If an agent proposes a new colour, it is not part of this system until it has
been through that checker.

## Known gaps in this handoff

- **The species icon set inside the app is not specified here.** Fourteen icons
  exist in `app/web/templates/_fish_icons.html`; eight are still in an older
  flat style. The six *ambient* fish in `screens.json` are a separate, newer set.
- **The app brands itself "Fishlog"**, the repo and the owner call it "fwapp".
  Both are in use. Unresolved on purpose — pick one deliberately, do not let an
  agent silently choose.
- **Nothing here has been checked on a real phone.** Every measurement comes
  from the stylesheet or from headless Chromium at 390px.
- **`today.html` and `zone_start.html` are dead templates** with no route. They
  are excluded from `screens.json` deliberately. Do not design them.

## Keeping this file honest

`screens.json` was extracted from the shipped templates, not written from
memory. When the app changes, it goes stale — and a stale spec is worse than
none, because it is confidently wrong. The stylesheet and the templates are the
source of truth; re-derive from them rather than editing this by hand.
