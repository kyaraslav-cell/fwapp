"""Finding a water by name, and turning it into a lake row.

    nominatim.py  name -> candidate places (the only new network client)
    service.py    dedupe, quota, create the row, queue the slow work

The shoreline is *not* fetched here: `app/geo/outline.py` already searches
Overpass by location and already excludes rivers, and that call belongs in a
job, not in a request.
"""
