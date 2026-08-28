#!/usr/bin/env bash
# Regenerate the two raster design assets through kie.ai.
#
# Build-time only. The outputs are committed to app/web/static/img/, so a
# deployment never calls kie.ai and a missing key costs nothing.
#
# ONE style preamble, reused verbatim in every prompt. That is the whole reason
# two separately generated images read as one set; paraphrasing it is how a
# design ends up with two unrelated pictures in it.
set -euo pipefail

SK="${SCROLLCRAFT_SKILL:-C:/Users/Inspiron/.claude/plugins/cache/nateherk/nateherk-design/0.2.0/skills/scrollcraft}"
OUT="tools/asset_out"

PREAMBLE="Minimal flat gouache illustration in a soft pastel palette: pale blue-green water, deep navy, muted reed green, warm off-white. Large simple shapes, no outlines, no line art, gentle paper grain, matte finish, soft diffused overcast light, generous negative space. Calm, quiet, restful on the eye. Low contrast, muted, nothing saturated. No text, no lettering, no people, no boats, no logos."

node "$SK/scripts/kie.mjs" still \
  "$PREAMBLE

A wide calm lake surface seen from the bank at eye level. Gentle horizontal ripple bands across the lower third, a soft pale mist band along the far shore, a hint of dark reed silhouette at the far left edge. The upper two thirds is empty pale sky, deliberately clear for text to sit on." \
  "$OUT/water-hero.png" --ar 16:9

node "$SK/scripts/kie.mjs" still \
  "$PREAMBLE

A single small fishing float resting upright on still water, seen from slightly above. Wide concentric rings spread slowly outward from it across an otherwise empty surface. Nothing else in the frame. The float is small and centred with generous calm water all around it." \
  "$OUT/float-rings.png" --ar 16:9
