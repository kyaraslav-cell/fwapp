# ADR 0006 — Pillow, and what happens to a catch photo on the way in

**Status:** accepted
**Date:** 2026-08-19
**Prompted by:** `docs/15-PRE-LAUNCH-REVIEW.md` §A2, before the app is on a URL.

---

## Context

`app/web/routes/sessions.py` checked the file extension, capped the upload at
8 MB, and wrote the bytes to disk exactly as they arrived. Three problems, in
the order they will actually bite:

**1. Every catch photo carries the GPS coordinates it was taken at.** Phone
cameras write EXIF `GPSLatitude`/`GPSLongitude`, and nothing stripped it. While
the notebook is private this is contained. The moment anything is shared — and
`docs/15 §B4` proposes exactly that — every shared photo publishes a swim to
the metre. Anglers guard swims; this is the kind of detail that loses trust
once and permanently. It has to be fixed *before* sharing exists, not after.

**2. Storage.** A modern phone photo is 3–5 MB. `docs/05` says the backup
strategy is copying the SQLite file, and photos are not in it — they are a
second thing to remember, on an SD card, growing by a season.

**3. `.heic` was accepted and is not displayable.** It is in the allowed
suffixes, so an iPhone upload is stored — and then most browsers cannot render
it. The angler gets a broken image and no explanation. That is already true
today; it is not a regression this ADR introduces.

## Decision

**Add Pillow, and re-encode every upload rather than storing it.**

The pipeline, in `app/media/images.py`:

1. decode, and refuse anything that is not actually an image — the extension
   check stays, but it is a filename, not evidence;
2. **apply EXIF orientation, then discard EXIF.** Order matters: strip first
   and every portrait phone photo is stored sideways;
3. downscale so the long edge is at most 1600 px, never upscale;
4. flatten transparency onto white and re-encode as JPEG, quality 82;
5. write the result. The original bytes are never stored.

Metadata is removed by **copying the pixels into a new image** rather than by
asking the encoder to omit it. `Image.save()` will happily carry `info["exif"]`
through on some paths, and "we asked it not to" is not a property anyone can
check later. A new canvas has no metadata to carry, and the test asserts the
absence on the bytes actually written.

### Why Pillow rather than doing without

`CLAUDE.md` requires justifying a dependency. Stripping EXIF by hand means
parsing JPEG APPn segments; downscaling by hand means resampling. Both are
solved problems where a mistake is a corrupt photo or a leak that looks fixed.
Pillow is the standard answer, is pure-enough to install on a Pi, and is used
at exactly one call site behind one module — so it is replaceable.

### Why 1600 px and quality 82

The photo's job is identifying a fish and remembering a session, on a phone.
1600 px on the long edge is above any phone screen and above what the app ever
displays; 82 is the point where JPEG artefacts stop being visible on
photographic content. Together they turn 4 MB into roughly 300 KB — the season
fits on the SD card, and the 8 MB cap now bounds *what we accept*, not what we
keep.

Both are constants in one module, not thresholds in a rule file: they are
image-engineering numbers, not fishing knowledge, so law 1 does not apply.

### HEIC: attempt, and refuse honestly

Pillow cannot decode HEIC without `pillow-heif`. Rather than add a second
dependency speculatively, HEIC is decoded if a plugin happens to be installed
and otherwise **refused with a message that tells the angler what to do**.

That is strictly better than today, where it is accepted and then cannot be
displayed. If real iPhone uploads turn out to arrive as HEIC rather than being
converted by iOS on upload — which varies by how the file is picked — the
answer is `pillow-heif`, one line, and this ADR gets an addendum. Deciding it
now would be deciding it without evidence.

## Consequences

- One dependency, one new module, one call site.
- **Existing photos are untouched.** This is a write-path change; anything
  already in `media/` keeps its EXIF. There are none yet in any real
  deployment, so no migration is written. If that stops being true, a one-off
  script over `media/` is the fix, and it belongs in `tools/`.
- Photo paths are now always `.jpg`, whatever was uploaded. `photo_path` is a
  stored string, so nothing needs migrating, but anything that infers a type
  from the extension is now correct rather than lucky.
- An upload that is not a real image is refused rather than stored, which
  closes the other half of the `/media` sniffing problem that `nosniff`
  (`app/web/security.py`) only defends.
- Re-encoding costs CPU per upload — tens of milliseconds for a phone photo,
  on a path that already waits for the network. Not a concern at one angler,
  and not one at a hundred.
