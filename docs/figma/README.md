# Structure handoff for a Figma design agent

One file: [`structure.json`](structure.json).

Screens, their elements in order, and the flow between them. **No styling** — no
colours, no type, no sizes, no spacing, no radii. The design is the agent's to
make; this only says what has to be on each screen and in what order.

Extracted from the shipped templates in `app/web/templates/`, so it describes
what the app actually is rather than what somebody remembers it being.

> There is no `.fig` file and there cannot be one — the format is a proprietary
> binary that nothing outside Figma writes. Hand `structure.json` to the agent
> alongside your own design prompt.

## Routing map

```
                    ┌──────────────────────────────┐
                    │  /welcome   signed out only  │
                    │  marketing — not in the flow │
                    └───────────────┬──────────────┘
                                    │ sign in
                                    ▼
  ╔═══════════════════════════════════════════════════════════════╗
  ║   THE FIVE-SCREEN FLOW — the order is fixed, not a suggestion  ║
  ╚═══════════════════════════════════════════════════════════════╝

   1. /                      home · your waters
        │  tap a water
        ▼
   2. /lake/{slug}           conditions + map        ◄────────────┐
        │  tap the map, or drag the fish pin onto it              │
        ▼                                                         │
   3. /lake/{slug}/spot      method + rod count                   │
        │  Start                                                  │
        ▼                                                         │
   4. /session/active        running session ─────────────────────┤
        │  End session          Conditions / Map — must stay
        ▼                        reachable mid-session
   5. /session/end           end, including a BLANK
        │  Save
        ▼
      /history               sessions, blanks, fish per hour

   Off to the side
      /places/new                     ← from home
      /session/catch/{id}/edit        ← from the session
      /auth/login · /auth/register
      404 / 500
```

Two edges are easy to miss and both matter:

- **`/lake` does not redirect into a running session.** It shows a banner and
  stays put — conditions and the map are exactly what an angler wants while
  sitting behind a rod.
- **A floating session button** sits on every screen while a session runs,
  except the session screen itself.

## What is in `structure.json`

| Key | |
|---|---|
| `shared` | chrome on every screen — topbar, nav, floating button, background layer |
| `screens[]` | each screen: route, purpose, and `elements[]` in paint order |
| `flow` | the fixed five-step order, plus the sideways edges |
| `structuralConstraints` | rules that change *which* elements exist |
| `frames` | 390×844 phone (the target), 1280×900 desktop (the adaptation) |

Element entries name a type (`card`, `list`, `slider`, `disclosure`, `table`,
`primary button`…), the children, and any conditional behaviour. Nothing about
appearance.

## The constraints worth reading before drawing

These are in the JSON too, but they are the ones an agent breaks *because they
look like improvements*:

1. **Fishing quality is a colour and a word — never a number.** No percentage,
   no rating, no gauge, no progress arc. The one ring on the conditions screen
   is a complete ring for exactly this reason: a partial arc reads as a score.
2. **Any figure from data carries its sample size.** Three sessions and ninety
   sessions must not look alike.
3. **A session with no fish is ordinary data.** As easy to record as a good one,
   never styled as failure, never dropped from a total.
4. **Conditions and the map stay reachable mid-session.**
5. **The five-screen order is fixed.** Do not design a one-tap start.
6. **Six fish silhouettes, each with its own outline** — the tail alone should
   tell them apart.

## Gaps, stated rather than hidden

- The **in-app species icon set** is not specified here; fourteen exist in the
  app and eight are older work.
- **`today.html` and `zone_start.html` are dead templates** with no route. They
  are deliberately absent — do not design them.
- The app brands itself **"Fishlog"**; the repo and owner say **"fwapp"**.
  Unresolved. Pick deliberately.

## Keeping it honest

`structure.json` was derived from the templates, not written from memory. When
the app changes it goes stale, and a stale spec is worse than none because it is
confidently wrong. Re-derive from `app/web/templates/` rather than editing by
hand.

*(An earlier version of this handoff carried a full colour and type token set.
It was removed at the owner's request — the design is the agent's to make. It
remains in git history if it is ever wanted.)*
