"""Catch photos: the GPS is gone, the fish is the right way up, ADR 0006.

The two that would actually hurt, in order:

1. **EXIF survives.** Every phone photo carries the coordinates it was taken
   at. While the notebook is private that is contained; the day anything is
   shared, each photo publishes a swim to the metre. Asserted on the bytes
   written, never on our intention to omit them.
2. **The photo is stored sideways.** Strip the metadata before honouring the
   orientation tag and every portrait phone photo lands rotated. The fixture
   here is deliberately non-square, so a rotation that did not happen cannot
   hide behind a symmetric image.
"""

from __future__ import annotations

import io
import pathlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.auth import passwords
from app.media import images


def make_photo(
    width: int = 4032,
    height: int = 3024,
    *,
    gps: bool = True,
    orientation: int | None = None,
    fmt: str = "JPEG",
) -> bytes:
    """A photo shaped like one a phone produces, with a phone's metadata."""
    image = Image.new("RGB", (width, height), (40, 90, 140))
    # A recognisable corner, so a rotation is visible in the pixels rather than
    # only in the dimensions.
    for x in range(min(80, width)):
        for y in range(min(40, height)):
            image.putpixel((x, y), (255, 40, 40))

    exif = image.getexif()
    if gps:
        # 0x8825 is the GPS IFD pointer. Pomiechówek, roughly - the point of
        # writing a real one is that a swim is genuinely recoverable from an
        # unstripped file, so the assertion below is about something.
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (52.0, 32.0, 0.0)
        gps_ifd[3] = "E"
        gps_ifd[4] = (20.0, 40.0, 0.0)
        exif[0x010F] = "TestPhone"       # Make
        exif[0x0110] = "TestPhone 15"    # Model
    if orientation is not None:
        exif[0x0112] = orientation

    out = io.BytesIO()
    if fmt == "JPEG":
        image.save(out, format=fmt, exif=exif.tobytes())
    else:
        image.save(out, format=fmt)
    return out.getvalue()


# --------------------------------------------------------------------------
# The two that matter
# --------------------------------------------------------------------------


def test_the_original_carries_gps_so_the_fixture_is_honest() -> None:
    """If this fails, every other assertion here is vacuous."""
    original = make_photo()
    assert images.has_metadata(original)
    assert 0x8825 in Image.open(io.BytesIO(original)).getexif()


def test_the_stored_photo_has_no_metadata_at_all() -> None:
    stored = images.process(make_photo())
    assert not images.has_metadata(stored), "EXIF survived re-encoding"
    exif = Image.open(io.BytesIO(stored)).getexif()
    assert 0x8825 not in exif, "the swim's coordinates are still in the file"
    assert not dict(exif.get_ifd(0x8825)), "the GPS block is still readable"
    assert 0x010F not in exif


def test_a_portrait_photo_is_stored_upright() -> None:
    """Orientation is applied *before* the metadata is discarded.

    Orientation 6 means "rotate 90° clockwise to view". A landscape sensor
    frame of 400x200 must therefore come out taller than it is wide. Strip
    first and it stays 400x200 - the classic sideways-photo bug, and invisible
    unless the fixture is non-square.
    """
    stored = images.process(make_photo(400, 200, orientation=6))
    width, height = Image.open(io.BytesIO(stored)).size
    assert height > width, f"stored {width}x{height} - the rotation was lost"


def test_an_unrotated_photo_is_left_alone() -> None:
    stored = images.process(make_photo(400, 200, orientation=1))
    width, height = Image.open(io.BytesIO(stored)).size
    assert (width, height) == (400, 200)


# --------------------------------------------------------------------------
# Size
# --------------------------------------------------------------------------


def test_a_phone_photo_is_shrunk_to_the_long_edge() -> None:
    stored = images.process(make_photo(4032, 3024))
    width, height = Image.open(io.BytesIO(stored)).size
    assert max(width, height) == images.MAX_EDGE_PX
    # Aspect ratio preserved, to a rounded pixel.
    assert abs((width / height) - (4032 / 3024)) < 0.01


def test_a_small_photo_is_never_enlarged() -> None:
    """Upscaling invents detail and pays storage for the privilege."""
    stored = images.process(make_photo(400, 300, gps=False))
    assert Image.open(io.BytesIO(stored)).size == (400, 300)


def test_the_stored_file_is_much_smaller_than_the_upload() -> None:
    """The season has to fit on an SD card next to the database."""
    original = make_photo(4032, 3024)
    stored = images.process(original)
    assert len(stored) < len(original) / 2


def test_the_output_is_always_jpeg_whatever_arrived() -> None:
    png = make_photo(300, 200, gps=False, fmt="PNG")
    stored = images.process(png)
    assert Image.open(io.BytesIO(stored)).format == "JPEG"
    assert images.OUTPUT_SUFFIX == ".jpg"


def test_transparency_flattens_onto_white_not_black() -> None:
    """A screenshot pasted into a catch note should not come back inverted."""
    rgba = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    stored = images.process(buf.getvalue())
    assert Image.open(io.BytesIO(stored)).convert("RGB").getpixel((5, 5)) == (255, 255, 255)


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_a_file_that_is_not_an_image_is_refused() -> None:
    """The extension is a filename, not evidence. The decode decides."""
    with pytest.raises(images.NotAnImageError):
        images.process(b"%PDF-1.7\nnot a photograph at all")


def test_an_empty_upload_is_refused_rather_than_stored() -> None:
    with pytest.raises(images.NotAnImageError):
        images.process(b"")


def test_heic_is_refused_by_name_so_the_angler_can_act() -> None:
    """Distinct from "not an image": the fix is "send a JPEG", not "try again".

    Sniffed from the bytes, not the filename, so an iPhone file arriving named
    `.jpg` still gets the useful message.
    """
    heic = b"\x00\x00\x00\x20ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 64
    with pytest.raises(images.UnsupportedImageError):
        images.process(heic)


def test_the_decompression_bomb_guard_is_still_in_place() -> None:
    """A 50 000 px square PNG is tiny on the wire and gigabytes decoded, and
    this decode runs inside a request."""
    assert images.DECOMPRESSION_BOMB_LIMIT is not None
    assert images.DECOMPRESSION_BOMB_LIMIT < 500_000_000


# --------------------------------------------------------------------------
# Through the real upload route
# --------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("FISHLOG_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(passwords, "DEFAULT_N", 1 << 12)

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)

    from app.web import app as app_module

    application = app_module.create_app()
    db_module.init_db()
    yield TestClient(application)


def test_the_route_stores_a_stripped_jpeg(
    client: TestClient, tmp_path: pathlib.Path
) -> None:
    """End to end: what lands in `media/` is the processed file, not the upload."""
    from app.web.routes import sessions as sessions_route

    class FakeUpload:
        filename = "IMG_0042.jpg"

        async def read(self) -> bytes:
            return make_photo(2000, 1500)

    import asyncio

    path = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        sessions_route._save_photo(FakeUpload())  # type: ignore[arg-type]
    )
    assert path is not None and path.endswith(".jpg")

    written = (tmp_path / "media" / pathlib.Path(path).name).read_bytes()
    assert not images.has_metadata(written), "the file on disk still carries EXIF"
    assert max(Image.open(io.BytesIO(written)).size) == images.MAX_EDGE_PX
