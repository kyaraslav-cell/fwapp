from __future__ import annotations

import math


def wind_exposure(zone_bank_aspect_deg: float, wind_direction_from_deg: float) -> float:
    """Pure geometry, not a fishing rule: +1 = wind blowing straight into this
    bank, -1 = fully sheltered. See docs/02-DOMAIN.md Layer 4. This is NOT
    FORMULA_WIND_ZONE (that converts exposure into a scored preference, and
    is still pending from the project owner) - this is just the cosine."""
    diff = math.radians(wind_direction_from_deg - zone_bank_aspect_deg)
    return round(math.cos(diff), 3)
