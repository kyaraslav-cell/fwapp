---
name: session-start
description: Orient at the beginning of a session by reading the project's standing docs, the newest handoff file, the backlog and the current git and build state, then report a short briefing of where things stand and what to do next. Use this at the start of any new session or fresh context on this project, when the user says "start", "continue", "where were we", "what's the state", "catch up", "pick up where we left off", or opens with work that assumes context you do not have - and use it after a compaction if the reasoning behind the current code is no longer in the window.
---

# Picking up a project cold

The cost of skipping this is not ignorance, it is confident wrongness: rebuilding
something that exists, re-deciding something already settled, or reintroducing a
bug whose fix looked redundant. A few minutes of reading prevents all three.

## Read, in this order

Each layer tells you something the next one assumes.

1. **`CLAUDE.md`** — the laws and the constraints. Non-negotiable, and some of
   them are counterintuitive enough that violating them looks like an
   improvement.
2. **`docs/10-SESSION-HANDOVER.md`** — the living state: what exists, the
   owner's standing rules, what is known broken, the verification rules learned
   the hard way.
3. **The newest file in `docs/handoff/`** — what the last session did, decided
   and left. `ls -t docs/handoff/ | head -3`; read the newest, and skim the one
   before if the newest references it.
4. **`docs/09-BACKLOG.md`** — what the owner has asked for and not received.
5. **The repo's own state** — this is the layer that catches a handoff written
   optimistically:

```bash
git log --oneline -8
git status --short
git branch -a
```

Compare what the docs claim against what the repository shows. When they
disagree, the repository is right, and the disagreement itself is worth
reporting — it usually means the last session ended mid-flight.

## Check it actually runs

A handoff saying "green" is a claim from the past. Verify before building on it:

```bash
make check    # or the project's equivalent
```

If the environment is missing (no venv, no dependencies), rebuild it before
reporting — a briefing that ends "and I could not run anything" is not much of
a briefing.

## Report

Short. The user knows their project; they need the delta, not a tour.

```
State      branch, deployed or not, checks green or not
Last       what the previous session did and decided
Broken     what is known not to work
Next       the most sensible next step, and why that one
```

If the docs and the repository disagree, say so explicitly — that is the single
most useful thing this skill produces.

Then stop and wait. Do not start work off the back of the briefing unless the
user asked for something specific; the point is to give them the state so *they*
can choose.
