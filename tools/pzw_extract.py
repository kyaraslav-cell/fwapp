"""Turn Okreg Mazowiecki's published water list into committed YAML.

Run once, by hand, when the okreg publishes a new season's list. Its output,
`config/pzw/mazowiecki.yaml`, is committed and read at runtime; nothing in the
app ever fetches this PDF. Same precedent as the OSM shoreline: derive offline,
commit the result, keep the derivation in the repo so the next person can see
where the data came from and redo it.

    python tools/pzw_extract.py <wykaz.pdf> [-o config/pzw/mazowiecki.yaml]

Needs `pypdf`, which is deliberately NOT in requirements.txt - it is a
once-a-season authoring tool, not a runtime dependency, and adding it to the
app's dependency set to run it annually would be the wrong trade. Install it
somewhere out of tree:

    pip install --target /tmp/pylibs pypdf
    PYTHONPATH=/tmp/pylibs python tools/pzw_extract.py wykaz.pdf

Source: https://ompzw.pl - "Wykaz wod udostepnionych do wedkowania".
The list is the okreg's own published statement of which waters its permit
covers, which is exactly the question the app asks of it.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# The three water sections of the list. Everything after them is regulations.
SECTION_RIVERS = "obwody_rybackie"
SECTION_LAKES = "jeziora"
SECTION_SMALL = "wody_drobne"

RECORD_MARKER = "Obwód rybacki obejmuje wody:"

# Leading water-kind words. Stripped from the matchable name but kept in the
# displayed one - "j. Pomocnia" is how the permit prints it.
KIND_PREFIXES = (
    "jeziora",
    "jezioro",
    "zbiornik",
    "zbiorniki",
    "zalew",
    "staw",
    "stawy",
    "glinianki",
    "rzeki",
    "rzeka",
    "kanal",
    "kanał",
    "j.",
    "rz.",
    "zb.",
)

# The same prefixes as they survive `normalise_name`, which strips the dots
# before the prefix is looked for. Without these "j. Pomocnia" normalises to
# "j pomocnia" and never matches an OSM name of "Jezioro Pomocnia".
KIND_PREFIXES_FOLDED = tuple(p.rstrip(".") for p in KIND_PREFIXES)


@dataclass
class Entry:
    """One water, as the okreg lists it."""

    name: str
    section: str
    place: str = ""
    area_ha: float | None = None
    notes: list[str] = field(default_factory=list)


def _strip_footnotes(text: str) -> str:
    """Drop the superscript index digits the list uses for local rules.

    They arrive glued to the name - "Glinianki Szczęśliwice14", "Zbiornik
    Zegrzyński22" - because the PDF has no superscript in its text layer. A
    digit run immediately after a letter is always a footnote here; a digit run
    after a space may be a real number, so it is left alone.
    """
    text = re.sub(r"(?<=[^\W\d_])\d+(?:\s*,\s*\d+)*\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean(text: str) -> str:
    text = text.replace("­", "").replace("‑", "-")
    # The PDF breaks words across lines with a hyphen: "Zegrzyńskie-\ngo".
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    # ...and sometimes splits a word with a stray space: "odcin ku", "Pias utno".
    return text.strip()


def normalise_name(name: str) -> str:
    """The key two spellings of the same water must agree on.

    Accents folded, kind prefix dropped, case dropped, punctuation dropped.
    Polish adjectival endings are NOT normalised here - "Szczęśliwice" and
    "Szczęśliwickie" stay different keys on purpose, and the fuzzy pass in
    `app/discover/pzw.py` is what bridges them. Doing it here would bake a
    guess into the committed data where nobody could see it.
    """
    folded = unicodedata.normalize("NFKD", name.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.replace("ł", "l")
    folded = re.sub(r"[^a-z0-9 ]+", " ", folded)
    words = folded.split()
    while words and words[0] in KIND_PREFIXES_FOLDED:
        words = words[1:]
    return " ".join(words)


# The list abbreviates the water kind. Expanded for display: the point of
# using the okreg's spelling is that it reads like the permit, and "j.
# Pomocnia" on a page heading is worse than the OSM name it replaces.
ABBREVIATIONS = {
    "j.": "Jezioro",
    "rz.": "Rzeka",
    "zb.": "Zbiornik",
}


def _expand_abbreviation(name: str) -> str:
    head, _, rest = name.partition(" ")
    expanded = ABBREVIATIONS.get(head.lower())
    return f"{expanded} {rest}".strip() if expanded and rest else name


def _tidy_name(raw: str) -> str:
    """A record's name cell, reduced to the water it names."""
    # The table wraps long names with a hyphen mid-word, and layout mode keeps
    # the pieces on separate lines: "j. Przytom-" + "ne". Rejoin before the
    # footnote strip, or the fragment reads as two words.
    name = _strip_footnotes(_clean(re.sub(r"-\s+", "", raw)))
    # "j. Pomocnia w zlewni rzeki Wkra Nr 4" -> "j. Pomocnia"
    name = re.split(r"\s+w zlewni\b", name)[0]
    name = re.split(r"\s+na rzece\b", name)[0]
    # A river district's name cell often runs on into the prose of the row
    # below it - "rz. Bug Nr 5 obwodu rybackiego", or the next water glued on
    # as "rzeki Rakutowka Nr 2 j.Toczylowo". Cut at the first thing that is
    # plainly no longer part of the name.
    name = re.split(r"\s+obwodu", name)[0]
    name = re.split(r"\s+Uwaga", name)[0]
    name = re.split(r"\s+(?=j\.\s*\w)", name)[0] if not name.startswith("j.") else name
    name = re.sub(r"\s*Nr\s*\d+.*$", "", name)
    name = re.sub(r"^[\s\-–—]+", "", name)
    # Layout mode can leave a footnote index detached from the word it hangs
    # off - "rz. Narew    1", "rz. Wisla   23" - which `_strip_footnotes` will
    # not touch, since it only removes digits glued to a letter. A trailing
    # bare number is never part of a water's name in this list.
    # The trailing comma matters: "rz. Narew 1, Nr 8" loses its "Nr 8" above
    # and is left ending in a comma, which a digits-only anchor will not match.
    name = re.sub(r"\s+\d+(?:\s*,\s*\d+)*\s*,?\s*$", "", name)
    return _expand_abbreviation(name.strip(" ,-–—"))


def parse_sections(pages: list[str]) -> dict[str, list[str]]:
    """Split the document into its three water sections."""
    full = "\n".join(pages)
    bounds = [
        (SECTION_RIVERS, r"1\.\s*Rzeki, zbiorniki zaporowe, jeziora w obwodach rybackich"),
        (SECTION_LAKES, r"2\.\s*Jeziora na wodach stojących"),
        (SECTION_SMALL, r"3\.\s*Wody drobne"),
        ("__end__", r"II\.\s*Wody górskie"),
    ]
    positions: list[tuple[str, int]] = []
    for key, pattern in bounds:
        match = re.search(pattern, full)
        if match is None:
            raise SystemExit(f"section not found in the PDF: {key}")
        positions.append((key, match.start()))

    out: dict[str, list[str]] = {}
    for (key, start), (_, end) in zip(positions, positions[1:], strict=False):
        out[key] = full[start:end].splitlines()
    return out


def _name_column_width(lines: list[str]) -> int:
    """Where the second column starts, measured rather than assumed.

    Every record in section 1 opens with the same phrase in the second column,
    so the column boundary is wherever that phrase is left-aligned to. Reading
    it off the page beats hard-coding a character offset that changes the first
    time the okreg re-lays out the document.
    """
    offsets = [line.index(RECORD_MARKER) for line in lines if RECORD_MARKER in line]
    if not offsets:
        raise SystemExit("section 1: the record marker never appears - wrong extraction mode?")
    return min(offsets)


def parse_rivers(lines: list[str]) -> list[Entry]:
    """Section 1: a multi-column table, one record per fishing district.

    The name cell is the first column and wraps across several lines. What
    starts a new water is the water-kind word every entry opens with - "j.",
    "rz.", "Zbiornik", "Zalew", "Kanał" - because the table centres each name
    vertically in its row rather than aligning it to anything.

    Indentation was the first thing tried and is not reliable: the Zegrzynski
    record puts "Zbiornik", "Zegrzynski", "na rzece" and "Narew Nr 7" all at
    indent zero, so an indent rule split one water into four and lost the name
    the permit actually prints.

    Requires layout-mode extraction. Without it the columns interleave and a
    record's name picks up the tail of the previous record's prose: an early
    version of this tool produced the water "Szkwa (Rozoga). Szczytno 49
    j. Pomocnia", which is three different things.
    """
    width = _name_column_width(lines)
    names: list[list[str]] = []
    for raw in lines:
        cell = raw[:width].rstrip()
        if not cell.strip():
            continue
        text = cell.strip()
        if re.fullmatch(r"[\d\s,.]+", text):  # a stray area figure in the wrong column
            continue
        if re.match(r"^\d+\.\s", text) or text.startswith("Nazwa"):  # the table's own heading
            continue
        first = text.split()[0].lower().rstrip(".,")
        starts_a_water = first in {p.rstrip(".") for p in KIND_PREFIXES}
        if starts_a_water or not names:
            names.append([text])
        else:
            names[-1].append(text)

    entries: list[Entry] = []
    for parts in names:
        name = _tidy_name(" ".join(parts))
        if name and normalise_name(name):
            entries.append(Entry(name=name, section=SECTION_RIVERS))
    return entries


def parse_two_column(lines: list[str], section: str) -> list[Entry]:
    """Sections 2 and 3: `Name | Place | Area`, one water per line.

    Layout mode keeps the columns apart with runs of spaces, so the split is
    the real column boundary rather than a guess at where a name stops being a
    name. Splitting on single spaces produced "Glinianki Szczęśliwice Warszawa
    Ochota" as a water's name, which is a water and its district glued together
    and matches nothing.
    """
    entries: list[Entry] = []
    pending: list[str] = []
    for raw in lines:
        if not raw.strip():
            continue
        cells = [c.strip() for c in re.split(r"\s{2,}", raw.strip()) if c.strip()]
        if not cells or cells[0].startswith("Nazwa akwenu"):
            continue
        if re.match(r"^\d+\.\s", cells[0]) or re.match(r"^[IV]+\.", cells[0]):
            continue
        if len(cells) == 1 and re.fullmatch(r"\d+", cells[0]):  # page number
            continue

        area: float | None = None
        if re.fullmatch(r"\d+[,.]\d{2}", cells[-1]):
            area = float(cells[-1].replace(",", "."))
            cells = cells[:-1]
        if not cells:
            continue

        name = _expand_abbreviation(_strip_footnotes(cells[0]))
        place = _strip_footnotes(cells[1]) if len(cells) > 1 else ""
        # Layout mode sometimes puts a footnote index far enough from the name
        # to look like its own column. A place made only of digits is that.
        if re.fullmatch(r"[\d\s,.]*", place):
            place = _strip_footnotes(cells[2]) if len(cells) > 2 else ""

        # A name that wrapped onto its own line arrives with no area at all;
        # it belongs to the row above rather than being a water of its own.
        if area is None and not place:
            pending.append(name)
            continue
        if pending and entries:
            entries[-1].place = " ".join([entries[-1].place, *pending]).strip()
            pending = []
        if not name:
            continue
        entries.append(Entry(name=name, section=section, place=place, area_ha=area))
    return entries


def extract(pdf_path: Path) -> list[Entry]:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - authoring tool, not runtime
        raise SystemExit(
            "pypdf is not installed. It is intentionally not a project "
            "dependency - see this module's docstring for how to run it."
        ) from None

    reader = PdfReader(str(pdf_path))
    # layout mode: keeps the table columns apart. See parse_rivers.
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    sections = parse_sections(pages)

    entries = parse_rivers(sections[SECTION_RIVERS])
    entries += parse_two_column(sections[SECTION_LAKES], SECTION_LAKES)
    entries += parse_two_column(sections[SECTION_SMALL], SECTION_SMALL)

    # Deduplicate on the normalised key, keeping the first (and richest) spelling.
    seen: set[str] = set()
    unique: list[Entry] = []
    for entry in entries:
        key = normalise_name(entry.name)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def to_yaml(entries: list[Entry], source: str) -> str:
    lines = [
        "# Waters covered by the Okreg Mazowiecki PZW permit.",
        "#",
        "# GENERATED by tools/pzw_extract.py from the okreg's published list.",
        "# Do not hand-edit: re-run the tool against the new season's PDF.",
        f"# source: {source}",
        "#",
        "# `name` is the okreg's own spelling, which is what the permit prints",
        "# and therefore what the app displays. `key` is the normalised form",
        "# used for matching; see app/discover/pzw.py.",
        "okreg: mazowiecki",
        "waters:",
    ]
    for entry in sorted(entries, key=lambda e: normalise_name(e.name)):
        lines.append(f"  - name: {entry.name!r}")
        lines.append(f"    key: {normalise_name(entry.name)!r}")
        lines.append(f"    section: {entry.section}")
        if entry.place:
            lines.append(f"    place: {entry.place!r}")
        if entry.area_ha is not None:
            lines.append(f"    area_ha: {entry.area_ha}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=Path("config/pzw/mazowiecki.yaml"))
    parser.add_argument(
        "--source",
        default="https://ompzw.pl - Wykaz wod udostepnionych do wedkowania",
    )
    args = parser.parse_args(argv)

    entries = extract(args.pdf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    open(args.out, "w", encoding="utf-8").write(to_yaml(entries, args.source))
    print(f"{len(entries)} waters -> {args.out}")
    for section in (SECTION_RIVERS, SECTION_LAKES, SECTION_SMALL):
        count = sum(1 for e in entries if e.section == section)
        print(f"  {section}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
