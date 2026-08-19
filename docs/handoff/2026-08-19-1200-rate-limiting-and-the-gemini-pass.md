# Handoff — 2026-08-19, rate limiting and the Gemini pass

## State

Branch `claude/accounts-calendar-handoff-wdpmcq`, two commits, pushed.
**Not merged into the default branch** — see "What I did not do".

`make check` green: ruff, `mypy --strict` over 45 files (the strict list grew by
`app/intel`), **246 tests** — 204 at the start of the session.

The previous handoff's "Next" list had three items. Item 1 (run the add flow
for real) is still impossible here and was not attempted; items 2 and 3 are
built.

## What was done, and why it looks like that

### Login rate limiting

`docs/10 §5` item 8 has carried "build it before this is on a public URL" since
accounts landed.

**The store is a SQLite table, and ADR 0004's objection to that was wrong.**
That ADR declined to build this because the correct answer "needs a shared
store" and an in-memory counter resets on every deploy. The premise was
mis-stated: this app already keeps sessions, jobs and the entire notebook in one
SQLite file, so `login_attempt` is the same storage model as everything else and
adds nothing external. Rows are pruned past the longest window that could still
count them — it is a rate limiter, not an audit log, and a permanent record of
who tried to sign in from where would be a liability in a database whose backup
strategy is "copy the file" (`docs/05`).

**Three windows, because one can only be wrong in one of two directions.** The
important asymmetry: a *tight* per-account limit is a weapon. Type somebody's
address wrongly five times and they cannot sign in for a quarter of an hour. So

| Window | Limit | Catches |
|---|---|---|
| email **and** IP | 5 / 15 min | the ordinary flood; no third party can drive it |
| email alone | 20 / 60 min | a genuinely distributed guess at one account |
| IP alone | 30 / 15 min | one password sprayed across many addresses |

A correct password clears that address's failures — and only that address's, so
signing in to an account you own does not also clear the failures your IP has
accumulated against other people's.

**The check runs before the password is hashed.** scrypt at ~0.5 s was the whole
old mitigation, and it is *also* the denial-of-service vector: that half second
is our CPU, spent per guess, while the angler waits. Refusing after verifying
would have left that half of the problem exactly where it was.

**Registration** is capped at 5 per IP per hour, counted on accounts actually
created. A rejected form is a typo and is not rationed.

`t()` gained named parameters so "try again in {minutes} min" stays one string
per language. Polish and Russian put the number in a different place from
English, and gluing it on in the template gets that wrong in two of three.

### The Gemini pass

`app/intel/`, job kind `intel`, last in `NEW_WATER_PIPELINE` — nothing waits on
it and it is the only stage that costs money.

**The citation is the entire design.** A model asked about a small Polish lake
will produce a confident paragraph about its bream fishing whether or not it has
ever seen a word about that water, and it reads exactly like a true one. So a
claim with no usable http(s) URL is **dropped**, not stored with a null source:
a column that is sometimes empty gets read as "source unknown" within a month.
Each unique URL is HEAD-checked once; 404/410 renders as "link dead" beside the
claim, which is kept because pages move.

**A check that could not run drops nothing.** Our being offline says nothing
about somebody else's citation, and this sandbox reaches no host at all — so
`source_ok` is NULL there and every fact survives.

**Three walls against a coefficient**, because ADR 0005 §2 stated the principle
and a principle nobody enforces lasts until the first useful-looking number:
the topic list is closed (six topics, in code); nothing collected reaches the
score, verified or not; and `water_fact` is its own table, never
`weather_hourly` and never a `derived_*` table, because a record of what
somebody wrote is a different kind of thing from a record of what was measured.

**A refresh supersedes rather than overwrites** — a fact that changed and one
that was withdrawn are otherwise indistinguishable — and an empty pass
supersedes too, or last month's claims quietly present as this month's.

**"Nothing found" had to be made an acceptable answer, in the prompt, in as many
words.** Most waters this will be pointed at have nothing written about them.
A prompt that does not say so gets an invention instead. This is law 4 applied
one level out.

The client is shaped like `app/auth/google.py`: key from the environment, "not
configured" is a state, and the job reports **skipped** rather than turning a
deployment that has not switched this on into a red job on the angler's page.

## Traps

- **`X-Forwarded-For` is a request header, so anyone can write one.** Trusting
  it by default hands an attacker a fresh address per attempt and makes the
  per-IP rule decorative. Trusting it when there is no proxy is the opposite
  failure: one address for the whole internet, everybody locked out together.
  Hence `FISHLOG_TRUST_PROXY=1`, opt-in per deployment — **and it must be set
  the day this goes behind Caddy or a Tailscale funnel.**
- **A rule keyed on a value the request does not have must count nothing.** An
  early version returned an empty where-clause when the client address was
  unknown, which SQLAlchemy widens to "every row in the table" — the first
  request from behind an address-hiding proxy would have locked out the world.
  There is a test for exactly this.
- **A test that asserts a limit fires proves nothing about *when* it fires.**
  The "before the hash" property is only testable by making `verify_password`
  raise. Both this and the 429 test were confirmed to fail with the check
  disabled before being believed.
- **`assert count == 4` on the job pipeline broke the moment a fifth stage
  landed.** It now asserts against `len(NEW_WATER_PIPELINE)`. A literal count of
  a list that is expected to grow is a test that punishes the next change.
- **Jinja does accept `t(key, **args)`** — dynamic kwargs in a call are
  supported — which is what let the number stay inside the translated sentence
  instead of being concatenated after it.
- **The i18n catalogue is still cached per process** and **a YAML value
  containing `: ` still needs quoting**. Both traps from the previous session
  are still live; the new `too_many` value is quoted for the second reason.

## Verified vs assumed

**Observed working:** the sign-in form refused at the limit, in all three
languages, with the minutes substituted and no `{minutes}` showing through —
rendered in a real browser and looked at, not inferred from the diff. The
"Local knowledge" section rendered through the real stylesheet in all three
languages, including a dead source showing as dotted and marked. Both
screenshots were shown to the owner. All 246 tests, and the three rate-limit
tests confirmed to fail with the check disabled.

**Believed, never observed:** every outbound call, as before — and now Gemini
too. No `generateContent` request has ever left this sandbox; the client is
tested against an `httpx.MockTransport` answering with envelopes shaped like the
real API's, which tests *our* behaviour given those answers and says nothing
about Gemini's. The response schema, the header name, the envelope shape and the
default model id are all read from documentation, not from a reply. **The first
real call is on the owner's machine, and the first thing to check is whether the
answer parses at all.**

Also unverified by anyone: whether the facts a real pass returns are *true*.
That is what the source links and `verified_by_owner` exist for.

## What I did not do

- **The live add-a-water run.** Confirmed again this session: Nominatim,
  Overpass and Open-Meteo all refuse at the proxy from here. It needs a machine
  with network.
- **Merged into the default branch.** The owner's standing rule 13 says every
  finished change goes straight into `claude/repository-edit-push-ggr229` and
  the site rebuilds. This session was told to develop and push on
  `claude/accounts-calendar-handoff-wdpmcq` and never to push elsewhere without
  explicit permission, so the merge is left for the owner to authorise. It is
  one `git merge` away and nothing depends on it.

## Next

1. **Set `FISHLOG_GEMINI_API_KEY` and add one water, on a machine with
   network.** Watch the `intel` job's outcome string: `N facts stored` means the
   whole chain worked, `M dropped` is how many claims arrived with no citation
   (the diagnosis if this feature ever starts misbehaving), and a failed job
   names which layer refused.
2. **Then judge the facts, not the plumbing.** If a real pass returns six
   plausible claims whose sources do not say what they are claimed to say, the
   answer is search grounding (`docs/13 §10`), not more prompt.
3. **Password reset**, the last of ADR 0004's three gaps, whenever an SMTP
   credential exists.
4. Unchanged and still ahead of all of this in value: the fish icons, terrain
   shelter, numbered migrations, and phase 5.
