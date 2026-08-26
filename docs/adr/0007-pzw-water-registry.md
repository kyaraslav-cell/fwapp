# 0007 — The PZW water registry as a committed data file

**Status:** accepted, 2026-08-26
**Supersedes:** nothing. **Relates to:** ADR 0005 (adding waters), law 3.

## The problem

`water_type` was never set by anything. The add-a-water pipeline wrote `NULL`
for every water it created, and only Pomocnia — seeded from a YAML file that
predates the pipeline — carried a value. So the places list showed three of
four real waters with no type at all, and the PZW/commercial filter could not
see them.

This is not cosmetic. `app/notebook/water_type.py` exists because a stocked
commercial fishery and a wild PZW water produce fish-per-hour on completely
different scales, so law 3's CPUE is **not comparable across the two**.
`assert_comparable` refuses to aggregate when a type is unset — correctly — so
an unset type is a quiet time bomb: every water added so far would have been
excluded from the calibration loop the moment it had sessions to contribute.

The owner also reported that OSM names are not what the permit calls these
waters, and that search returned villages and streets alongside lakes.

## The decision

**Import the okręg's own published water list, offline, and commit the
result.** Ask the angler when the list has no answer.

Three parts:

1. `tools/pzw_extract.py` parses the PDF that Okręg Mazowiecki publishes
   ("Wykaz wód udostępnionych do wędkowania") into
   `config/pzw/mazowiecki.yaml`. Run by hand, once a season.
2. `app/discover/pzw.py` matches a water's name against that file at add time.
   Pure, no I/O beyond reading the committed YAML once.
3. The add form asks PZW-or-commercial **only** when the registry has no
   answer, so a listed water is still one tap.

### Why the okręg's own list

It is the authority on the question being asked. "Is this water on the PZW
permit" is answered definitionally by the document that *is* the permit's
schedule of waters — not inferred, not crowdsourced.

### Why committed, and not fetched at runtime

Same reasoning as the OSM shoreline (`docs/10 §1`). The list changes once a
season; a runtime dependency on a club website would add a failure mode to
adding a water in exchange for freshness measured in months. It would also
fail closed at the worst possible moment — on the bank, adding a water,
with one bar of signal.

### Why `pypdf` is not in `requirements.txt`

It is needed once a season by one person running one tool, and never by the
running app. Adding it to the dependency set of a container that restarts
daily, to support an annual authoring task, is the wrong trade. The tool's
docstring says how to install it out of tree. `docs/05-ARCHITECTURE.md`'s rule
is about dependencies the *app* acquires; this is not one.

### Why the angler's answer beats the registry

The match is a fuzzy string comparison against a list with **no coordinates**
in it. The person standing in front of the water knows which it is. So an
explicit answer on the form always wins and is recorded as such —
`water_type_source` is `angler` or `pzw_registry`, because the two are not
equally trustworthy and a later correction needs to know which it overrides.

### Why an ambiguous match is treated as no match

Poland has a great many lakes called Czarne, Białe and Głęboczek, and the list
carries nothing to tell them apart. When more than one entry matches equally
well, `lookup()` returns `None` and the angler is asked. Picking one would put
a wrong value into the CPUE segmentation key with nobody watching — precisely
the silent corruption law 3 exists to prevent.

### Naming: the permit's spelling wins, OSM's is kept

`Lake.name` becomes the okręg's spelling, because that is what is printed on
the permit and signposted at the water. `Lake.name_osm` keeps OpenStreetMap's,
because it is what the water is *findable* by — and because keeping it is what
makes a wrong match visible rather than a silent rename of somebody's lake. The
lake page carries it in a `title` attribute; dedupe checks both.

That last point was not theoretical: renaming broke `find_existing`'s
name-and-proximity path on the first run, and would have created a duplicate
row for any water reached through a second OSM object — splitting the notebook
for that lake in two. Pinned by
`test_the_same_water_is_still_deduped_after_being_renamed`.

## Scope

**Okręg Mazowiecki only**, deliberately, per rule 15 (MVP-first). All four
waters currently in the database are in it. There is **no national
machine-readable PZW registry**: each of ~45 okręgi publishes separately, in
its own format — PDF, Google My Maps, bespoke map viewers, several with no
downloadable list at all. Covering them all is roughly one parser per okręg
plus permanent maintenance as each redesigns.

The design does not need redoing to add more: `registry()` reads every
`config/pzw/*.yaml`, so a second okręg is a second file and, if its format
differs, a second extractor.

## What this does NOT do

- **It does not encode closed seasons or size limits.** Those are per-okręg,
  vary by species, and change annually. `is_regulated()` still only marks the
  hook. Presenting a stale legal limit as current is worse than presenting
  none.
- **It does not touch scoring.** Nothing the registry supplies reaches a
  prediction. The one existing water-type effect on scoring —
  `water_type_weights` in the ruleset — is unchanged and still lives in YAML
  (law 1).
- **It does not verify that a matched water is the same physical water.**
  A name match is a name match. This is why ambiguity refuses, why the angler
  overrules, and why the OSM name is kept where a human can see it.

## Costs accepted

- The extracted list is a **derived copy** and will drift from the okręg's
  when they republish. Mitigated by the tool being committed and re-runnable,
  and by the file's header saying it is generated.
- Extraction from a PDF is inherently brittle. Two layout facts are load
  bearing and both are documented in the tool: records are delimited by the
  phrase every district description opens with, and a new water's name is
  signalled by the water-kind word it starts with (indentation was tried
  first and is *not* reliable — the Zegrzyński record puts four consecutive
  name lines at indent zero).
- Coverage is partial: 109 waters extracted, against the ~416 the okręg's own
  map claims. The sections parsed are the three water tables; river districts
  contribute a name each rather than every beat. A water that is genuinely
  PZW but missing from the extract falls through to the angler's answer, which
  is the safe direction to fail in.
