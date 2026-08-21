"""Catch photos: oriented, shrunk, stripped of metadata, re-encoded.

ADR 0006. One rule decides the shape of everything here: **the bytes an angler
uploaded are never the bytes we store.** They are decoded, re-drawn onto a
clean canvas, and encoded again. That is what makes "the EXIF is gone" a fact
about the file rather than a hope about an encoder flag.

Order matters more than it looks:

    decode → apply EXIF orientation → THEN discard EXIF → resize → encode

Strip first and every portrait phone photo is stored on its side, because the
sensor recorded it landscape and wrote "rotate 90°" in the metadata that was
just thrown away. This is the single most common way this function is written
wrong, and the test for it uses a deliberately non-square image so that a
rotation that did not happen cannot hide.

Pure: bytes in, bytes out. No filesystem, no request, no clock.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# Above any phone screen and well above anything this app renders. The photo's
# job is identifying a fish, not printing it. Image-engineering numbers, not
# fishing thresholds - law 1 does not reach them.
MAX_EDGE_PX = 1600
JPEG_QUALITY = 82

# Pillow refuses absurd dimensions by default (~178 Mpx) as a decompression
# bomb. Named here so nobody "helpfully" raises it: a 50 000 x 50 000 PNG is
# 30 KB on the wire and gigabytes in memory, and this decode runs inside a
# request.
DECOMPRESSION_BOMB_LIMIT = Image.MAX_IMAGE_PIXELS

OUTPUT_SUFFIX = ".jpg"
OUTPUT_MIME = "image/jpeg"


class NotAnImageError(ValueError):
    """The upload did not decode. The filename said otherwise; it was wrong."""


class UnsupportedImageError(ValueError):
    """It is an image, in a format this build cannot read - HEIC, in practice."""


def _decode(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        # `open` is lazy: without this the file is not actually parsed and a
        # truncated or hostile file fails much later, somewhere less helpful.
        image.load()
        return image
    except UnidentifiedImageError as exc:
        # HEIC lands here when `pillow-heif` is not installed, and so does a
        # renamed PDF. The two need different messages, so the caller is told
        # which by a different exception type - see `process`.
        raise NotAnImageError(str(exc)) from exc
    except Image.DecompressionBombError as exc:
        raise NotAnImageError(f"image dimensions refused: {exc}") from exc
    except OSError as exc:
        raise NotAnImageError(f"image could not be read: {exc}") from exc


def _looks_like_heic(data: bytes) -> bool:
    """HEIC/HEIF magic: an ISO-BMFF `ftyp` box with a heic-family brand.

    Sniffed from the bytes rather than trusted from the filename, because the
    point is to give an iPhone user a message they can act on even when the
    file arrived named `.jpg`.
    """
    header = data[:32]
    if b"ftyp" not in header:
        return False
    return any(brand in header for brand in (b"heic", b"heix", b"hevc", b"mif1", b"heim"))


def process(
    data: bytes, *, max_edge: int = MAX_EDGE_PX, quality: int = JPEG_QUALITY
) -> bytes:
    """One upload -> the JPEG to store. Raises rather than storing anything odd.

    Never upscales. A 400 px photo from an old phone stays 400 px: enlarging it
    invents detail and costs storage to do it.
    """
    if _looks_like_heic(data):
        try:
            Image.open(io.BytesIO(data)).load()
        except Exception as exc:  # noqa: BLE001 - any failure means "cannot read"
            raise UnsupportedImageError(
                "HEIC photos cannot be read by this server"
            ) from exc

    image = _decode(data)

    # 1. Honour the orientation tag while it is still there.
    oriented = ImageOps.exif_transpose(image) or image

    # 2. Re-draw onto a clean canvas. This - not a save() flag - is what
    #    removes EXIF, ICC profiles, XMP and anything else riding along.
    #    RGB because the output is JPEG, which has no alpha channel; a
    #    transparent PNG flattens onto white rather than onto black, which is
    #    what a screenshot pasted into a catch note expects.
    if oriented.mode in ("RGBA", "LA", "P"):
        oriented = oriented.convert("RGBA")
        clean = Image.new("RGB", oriented.size, (255, 255, 255))
        clean.paste(oriented, mask=oriented.split()[-1])
    else:
        clean = Image.new("RGB", oriented.size)
        clean.paste(oriented.convert("RGB"))

    # 3. Shrink to fit, preserving aspect ratio. `thumbnail` is in-place and
    #    never enlarges, which is exactly the wanted behaviour.
    clean.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    clean.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def has_metadata(data: bytes) -> bool:
    """True if a stored file still carries EXIF. For tests and for `tools/`.

    Asserting on the *output bytes* rather than on our intention is the whole
    point: "we passed no exif= argument" is not a property anyone can verify a
    year later.
    """
    try:
        image = Image.open(io.BytesIO(data))
    except Exception:  # noqa: BLE001 - not an image, so no metadata either
        return False
    if image.getexif():
        return True
    return any(key in image.info for key in ("exif", "icc_profile", "XML:com.adobe.xmp"))
