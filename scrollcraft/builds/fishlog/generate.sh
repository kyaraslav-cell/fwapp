#!/usr/bin/env bash
# Fishlog landing page assets.
#
# The Live surface grammar forbids full-bleed photography, so these are not
# backdrops. They are PLATES: small, framed, captioned figures in a survey
# document, the way a field notebook carries a reference photograph. That is why
# there are three small ones rather than one big one.
#
# ONE style preamble, reused verbatim. Deliberately pushed toward HIGH
# micro-contrast: the previous build's stills came back at a greyscale stddev of
# 24 and read as washed-out mush, which was the owner's complaint and a correct
# one. "Muted" was doing too much work in that prompt.
set -euo pipefail

SK="${SCROLLCRAFT_SKILL:-C:/Users/Inspiron/.claude/skills/scrollcraft}"
OUT="scrollcraft/builds/fishlog/out"

PREAMBLE="Field survey plate photographed on 120 roll film. A single subject, flat-on, even overcast daylight. Deep teal, slate navy and cool grey-green only, no warm cast, no golden light. HIGH micro-contrast and crisp detail: shadows are genuinely dark and hold structure, highlights are bright and controlled, the midtones are separated. Fine visible film grain. Sharp throughout, deep depth of field. Clean margin of empty space around the subject. Documentary and unromantic. No text, no lettering, no numbers, no people, no boats, no logos, no watermark, no border."

node "$SK/scripts/kie.mjs" still \
  "$PREAMBLE

Looking straight down from one metre above the surface of a small lowland lake. Wind ripple crosses the frame diagonally in sharp parallel ridges. The water is very dark, near black-teal, and the ripple troughs catch bright pale sky, so the surface reads as high-contrast light-on-dark corrugation." \
  "$OUT/plate-surface.png" --ar 3:4

node "$SK/scripts/kie.mjs" still \
  "$PREAMBLE

A dense stand of common reed at a lake margin, seen flat-on from out on the water. Strong vertical dark stems against a paler recessed gap behind them, bronze and deep green, sharply defined. The waterline crosses the lower quarter of the frame as a hard dark band with the stems reflected in it." \
  "$OUT/plate-reed.png" --ar 3:4

node "$SK/scripts/kie.mjs" still \
  "$PREAMBLE

The boundary where wind-driven ripple meets sheltered still water, seen low and close to the surface. A hard diagonal seam runs across the frame: rough broken texture on one side, glassy dark mirror on the other. The contrast between the two halves is the whole subject." \
  "$OUT/plate-seam.png" --ar 16:9
