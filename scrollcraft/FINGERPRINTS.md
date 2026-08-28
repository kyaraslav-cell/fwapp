# Fingerprints

Every site you build with **scrollcraft** gets one row here, appended after it
ships. The registry exists so your next build can prove it is a different page
rather than a re-skin of one you already made.

This file is **yours**. It starts empty on purpose: the gate is about not
repeating *yourself*, so it has nothing to say until you have built something.

The rules and the gate live in the skill's
`references/uniqueness.md`. Short version:

**A new build must differ from EVERY row below on at least 4 of the 6
dimensions.** Four against each row individually, not four on average across the
table. If a planned build fails, change the plan. Never edit a row to make room
for it.

The six dimensions are: **grammar**, **nav treatment**, **hero device**,
**act-sequence shape**, **close pattern**, **signature move**.

Dimension 6 is free, because a signature move is unique by definition. So the
gate really asks for three more out of the remaining five, and a build that
changes only grammar and world will fail it.

---

## The registry

| Build | Grammar | Nav treatment | Hero device | Act-sequence shape | Close pattern | Signature move | World | Port |
|---|---|---|---|---|---|---|---|---|

*(empty: your first build has nothing to clear, so build whatever the interview
points at. From the second onwards, this table is the constraint.)*

---

## What is taken

Add a bullet here whenever a build claims something a later build should avoid
reusing: a grammar, a nav treatment, a close pattern, a signature move, an
act-count-and-length band. The shared columns are what the next build inherits
as a constraint, so writing them down is the whole point.

Nothing is taken yet.

---

## Appending a row

After shipping, add one line to the table and one bullet to **What is taken** if
the build claimed something new. Fill every column. Say what the build shares
with existing rows.

Rows are append-only. A build that has been superseded stays in the table,
because the space it occupies is still occupied.

---

## Worked example

The skill's author kept a registry of twelve builds across eight page grammars.
If you want to see what a filled-in table looks like, and which shapes tend to
collide, read `EXAMPLES.md` in the scrollcraft repository. Treat it as
illustration only: those rows are somebody else's builds and they do **not**
constrain yours.

---

## 1 · fishlog · 2026-08-28

Front door for Fishlog, a fishing-conditions instrument for one 9 ha Polish lake.

| Dimension | This build |
|---|---|
| **Grammar** | Live surface. The page behaves like the instrument rather than advertising it. |
| **Nav treatment** | App chrome: a fixed status strip carrying water, ruleset version and a reading dot. No wordmark-and-CTA marketing bar. |
| **Hero device** | `flow`, the surface already in a state, and the state is EMPTY. The prediction panel is present and blank: the instrument does not know either. No title card, no entrance animation on the headline. |
| **Act-sequence shape** | 6 acts, ~12.9 vh. flow(1.0) > pin(2.6) > flow(1.4) > **pin(4.2, peak)** > pan(2.6) > pin(1.15). Deliberately outside the 6-to-7 acts at 13.6-13.8 vh band. Zero `scrub` acts. |
| **Close pattern** | A real input. A search field the visitor puts a cursor in, posting to the app's own `/places/new`, with the footer inside the pinned stage. Not a button island. |
| **Signature move** | **The Seal.** The prediction row composes from the numbers on screen, hashes them in the browser, and stamps at p=0.62. Scrolling back does NOT un-stamp it: the seal, the hash and the timestamp persist for the life of the page. Deliberate irreversibility in a medium whose entire premise is reversibility. |

**World:** none generated as a world. Three dark documentary plates (reed
margin, wind ripple from above, the ripple/calm seam) used as framed figures in
a survey document, never full-bleed, because this grammar forbids that.

**Port:** `/welcome` in the Fishlog FastAPI app, as a standalone Jinja template
that deliberately does not extend `base.html`.

**Shares with prior rows:** nothing. First row in this registry, so the gate
was free. The next build has to differ from this one on 4 of 6, which means the
easy repeats to avoid are: app-chrome nav, an empty-state hero, a pinned peak
with the largest span, and closing on an input.

**Notes for next time.** Two things cost a round here and would cost it again:

- A pinned act whose first content is cued shows an **empty stage for a whole
  viewport**, because the stage is fully visible before its progress leaves 0.
  Act 2 opened on a blank screen until the panels were made the act's ground
  and only their values were allowed to arrive.
- The harness identifies a cue by its **text**, so a `data-sc-count` inside a
  cued element mutates that text and produces a phantom "cue never peaks"
  warning. Both warnings here were false positives from exactly that, and
  moving the counters out of the cued wrappers cleared them.
