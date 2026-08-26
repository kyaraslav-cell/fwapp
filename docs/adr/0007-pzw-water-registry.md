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

## Scope — corrected 2026-08-26

**This ADR originally said there is no national machine-readable PZW registry.
That was wrong, and the owner corrected it.**

`https://pzw.pl/strefa-wedkarza/lowiska-i-wody-pzw` is PZW's own national
register — every water its okręgi manage, ~1 800 of them across 174 pages,
alphabetical. Each listing card carries the water's name, kind, place,
voivodeship, the okręg that manages it and the koło that hosts it. Each
water's own page additionally carries **coordinates**.

The mistake was reasoning from search results about *per-okręg* pages (PDFs,
Google My Maps, bespoke viewers — all of which are real) and concluding that
nothing central existed, without looking for a central one. The okręg PDF was
a worse source that happened to be the first one found.

`tools/pzw_crawl.py` now reads the national register into
`config/pzw/poland.yaml`. `tools/pzw_extract.py` and its
`config/pzw/mazowiecki.yaml` are kept: the PDF is the okręg's own permit
schedule and is the authority on what a permit *covers*, whereas the register
is the authority on what exists and where. `registry()` reads every
`config/pzw/*.yaml`, so both contribute.

### Why the crawler drives a browser

The register's pagination endpoint answers `200` with an **empty body** to a
plain HTTP request, however faithfully the query string and headers are
reproduced; it answers properly from inside a real page session. Rather than
guess at what else it wants, the tool drives the site's own page and calls the
endpoint the way the site does. Requests are serialised with a delay and the
crawl stops on the first empty page rather than hammering.

### Coordinates change the matching problem

The PDF had no coordinates, which is why `lookup()` refuses an ambiguous name
match — Poland has a great many lakes called Czarne and nothing told them
apart. The register does have them, so proximity can disambiguate: a water
being added already has a lat/lon from Nominatim. **That is not yet wired in**
— `lookup()` is still name-only. It is the obvious next step and would let the
matcher answer confidently in exactly the cases it currently declines.

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
- PDF coverage is partial: 109 waters extracted, against the ~416 the okręg's
  own map claims. The sections parsed are the three water tables; river
  districts contribute a name each rather than every beat. The national
  register supersedes this for coverage. A water missing from both falls
  through to the angler's answer, which is the safe direction to fail in.
- The national register is crawled, not offered as a download. That is a
  standing risk: a markup change breaks the tool. It fails loudly (it stops
  rather than writing a truncated file) and the committed YAML keeps working
  in the meantime, because nothing is fetched at runtime.
