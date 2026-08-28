# 02 — Direction: three mockups, then stop

The cheapest place to change a design's mind is before any CSS exists. The last
redesign decided while coding, and paid for it three times over.

## Rules for this phase

1. **No file under `app/web/static/` or `app/web/templates/` is touched.**
2. **Three directions, not one.** One direction is a proposal you will defend;
   three is a choice the owner makes. They must differ in something structural —
   density, ground, type pairing — not in accent colour alone.
3. **Artboards, not prose.** A description of a mockup is not a mockup. Use the
   built-in `design` canvas skill: multi-artboard, pan/zoom, owner can edit by
   hand.
4. **Stop when they are delivered.** Do not pick for the owner. Do not begin
   phase 3 on the strength of your own preference.

## What each direction must state

| | |
|---|---|
| Ground | the canvas colour, and why it survives daylight |
| Ink | the structural anchor outside the pastel band |
| Accent | **one**, locked app-wide. A green app does not grow a blue button on one screen. |
| Type pairing | display face and body face, or one variable face at two optical roles |
| Density | how much sits on one 390px screen |
| Signature | the one element that is this design and nothing else |

## Which screens to draw

Draw the flow, not the prettiest page. Standing rule 5 fixes the order:

1. **Home / places** — the list, favourites, water-type filter
2. **Lake** — day strip, conditions, the registered-catch baseline with its `n`
3. **Map** — the heat overlay, spot selection, the fish pin
4. **Session start** — method, rod count
5. **Catch logging** — species, weight and length sliders, bait, photo

Plus, separately and in the other register (D2), **`/welcome`**.

Six artboards at 390px. If a direction cannot survive 390px it is not a
direction. Draw desktop only after the owner has chosen.

## Reference registers

`docs/18` measured all ten reference sites at 375px. The split that matters:

- **Nine are marketing pages.** craft.do loads 166 images; cal.com loads 8 font
  families. That register belongs to `/welcome` and nowhere else.
- **Excalidraw is the only application** in the set — and has **zero raster
  images**, 32 inline SVG. That is the register for screens 1–5.

Do not import marketing density into the app screens because a reference site had
it. The reference sites are read once, on wifi, at a desk.

## What "pastel" has to mean here

Pastels cluster in a narrow lightness band, so pastel-on-pastel almost never
reaches AA. The workable form, and the only one that will pass phase 3:

- pastels carry **grounds, fills and secondary surfaces**
- a **structural colour outside the band** carries text and anchors the design
- the accent sits far enough from both to be found without hunting

If a direction cannot state which colour is doing the anchoring, it is not
finished.

## Recording the choice

Write the owner's pick into `docs/18b-DECISIONS.md` — the direction, the reason
given, and what was rejected. The rejected two matter: the next session will
otherwise re-propose them.
