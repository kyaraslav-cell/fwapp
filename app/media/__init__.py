"""What happens to an uploaded file before it is stored.

`images.py` is the whole of it: decode, orient, strip, shrink, re-encode.
ADR 0006 for why the bytes an angler uploaded are never the bytes on disk.
"""
