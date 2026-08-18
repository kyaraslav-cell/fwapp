---
name: session-end
description: Distil the current session into a dated handoff file on disk and update the standing project docs, so nothing important is lost when the context window compacts or the session ends. Use this whenever the user says they are finishing, wrapping up, stopping for now, running low on context, about to compact, switching machines, or asks for a handoff, handover, session summary, or "save the context" - and also proactively suggest it when a long session has produced decisions that are not yet written down anywhere but the transcript.
---

# Ending a session without losing what it learned

A session's transcript is the least durable thing in the project. It vanishes on
compaction, on a new chat, on a closed tab — and it is the only place where the
*reasoning* lives. The code survives; the reason the code looks like that does
not.

This skill moves that reasoning onto disk before it is lost.

## What actually needs saving

Not a diary. Someone reading it cold needs to make good decisions, and almost
none of the transcript helps with that. The parts that do:

- **Decisions and the reasoning behind them.** The single highest-value thing.
  "We use a median, not a mean, because one storm would drag the norm" is worth
  more than any amount of what-happened narration. A decision without its reason
  gets reverted by the next person who finds it inconvenient.
- **What is broken or half-done**, named precisely enough to pick up.
- **The next concrete step**, with the file and the approach — not "continue the
  refactor".
- **Traps and dead ends.** What was tried and failed, and why. This is what
  stops the next session burning an hour rediscovering it.
- **What was verified and how**, versus what is merely believed to work. A test
  suite passing and a thing actually working are different claims.

Leave out: what was said, in what order, how long it took, and anything already
obvious from `git log`.

## Where it goes

**One file per session**, never a shared one:

```
docs/handoff/YYYY-MM-DD-HHMM-<short-slug>.md
```

A single shared handoff file loses every previous session to the last writer.
Dated files accumulate, and the newest one is the one that matters.

Then update the standing docs where this session actually changed them:

- `docs/10-SESSION-HANDOVER.md` — the canonical state of the project. Update §1
  (what exists), §2 (standing rules, if the owner gave a new one), §5 (known
  broken). This file is a *current state*, so edit it in place; do not append a
  changelog to it.
- `docs/09-BACKLOG.md` — mark items done, add what the session discovered was
  needed.

The distinction matters: the handoff file is a snapshot of one session, the
handover is the living state. Do not copy one into the other.

## The file

```markdown
# Handoff — <date>, <one-line what this session was about>

## State
Branch, whether it is merged and deployed, and whether `make check` is green.

## Decisions, and why
The reasoning. This is the part that cannot be recovered from the code.

## Broken / unfinished
What does not work, precisely enough to pick up.

## Traps
What was tried and did not work, so nobody repeats it.

## Verified vs assumed
What was actually observed working, and what is only believed to.

## Next
The concrete next step, with the file and the approach.
```

Keep it tight. A handoff nobody reads because it is long protects nothing.

## Getting the content right

Read back over the session before writing. Look for: places where the user
corrected you (those corrections are standing rules now), numbers that were
measured rather than guessed, bugs whose root cause took effort to find, and
anything you concluded was impossible or blocked.

Be honest about what was not finished. A handoff that overstates progress is
worse than none, because the next session starts by trusting it.

When done, tell the user in one line where the file is and what the next step
is. Then it is safe to compact.
