"""Turn an okreg's annual catch report into committed YAML.

    python tools/catch_report_extract.py <raport.pdf> --year 2024 --okreg mazowiecki

Okreg Mazowiecki publishes "Ocena presji i polowow wedkarskich w wodach
uzytkowanych przez Okreg Mazowiecki PZW" every year: for each water, how many
anglers returned a register, how many days each fished, how much they caught
per day and per season, and the species split.

**This is CPUE, measured.** It is the unit law 3 makes the point of the whole
project, for ~80 real waters, and until this landed the project had none - no
logged session, nothing to calibrate against, no way to tell whether the
scoring engine beats guessing. That is what makes this document worth parsing
carefully.

What it is not:

  * It is **kg per angler-day**, not fish per hour. Comparable between waters
    and between years; not the same quantity the notebook computes.
  * It comes from **voluntarily returned registers**, so a small self-selected
    fraction of anglers. Sample sizes are printed with every figure and are
    frequently under thirty - law 5 applies with force here.
  * It is one season. Nothing here should be read as what a water "is".

The figures live in the report's prose, not in its tables: the tables are
images with no text layer. So this parses sentences, and every pattern it
relies on is written down below.

Needs `pypdf`, deliberately not a project dependency - see
`tools/pzw_extract.py` for how to install it out of tree.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Polish name -> the app's species slug, for the six the engine scores plus the
# ones common enough to be worth showing. `karpiowate` is the cyprinid FAMILY
# and is deliberately absent: it means bream-and-roach-and-rudd collectively,
# and reading it as `karp` put a 57% carp share on a water whose real carp
# share is 2.8%.
SPECIES = {
    "karp": "carp",
    "karaś pospolity": "crucian_carp",
    "karaś srebrzysty": "gibel_carp",
    "leszcz": "bream",
    "płoć": "roach",
    "wzdręga": "rudd",
    "jaź": "ide",
    "lin": "tench",
    "szczupak": "pike",
    "sandacz": "zander",
    "okoń": "perch",
    "sum": "catfish",
    "węgorz": "eel",
    "boleń": "asp",
    "amur": "grass_carp",
}

# "II. Lowiska wedkarskie" opens the body. Everything before it is the title
# page and the contents, whose headings look identical to the real ones but are
# followed by dotted leaders and a page number rather than by the figures.
BODY_MARKER = "II. Łowiska"

# Word edges as lookarounds rather than \b. Two reasons: Python word
# boundaries sit awkwardly around Polish diacritics, and writing \b into this
# file through a shell heredoc silently turned it into a literal backspace
# more than once - after which the pattern just stops matching, with no error.
LETTERS = "0-9A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż"
EDGE_L = f"(?<![{LETTERS}])"
EDGE_R = f"(?![{LETTERS}])"

# The report's text layer sometimes splits a decimal: "0, 29 kg", "0,6 2 kg".
# `num` strips spaces, so the pattern only has to allow one.
DEC = r"\d+(?:,\s?\d+)?"

HEAD = re.compile(r"^\s*(\d+(?:\.\d+)*)\.\s+(.{3,90}?)\s*\(Tabela nr\s*(\d+)", re.M)


@dataclass
class WaterStats:
    table: int
    name: str
    anglers: int | None = None
    total_kg: float | None = None
    kg_per_angler_year: float | None = None
    kg_per_angler_day: float | None = None
    days_per_angler: float | None = None
    species_pct: dict[str, float] = field(default_factory=dict)
    species_mean_kg: dict[str, float] = field(default_factory=dict)


def num(value: str) -> float:
    return float(value.replace(" ", "").replace("\xa0", "").replace(",", "."))


def first(pattern: str, body: str) -> str | None:
    match = re.search(pattern, body)
    return match.group(1) if match else None


def _species_share(body: str, polish: str) -> float | None:
    """This species' share of the catch, as a percentage.

    The percentage must follow its species almost immediately. A generous
    window looks reasonable and is not: the report writes lists like

        leszcz, płoć, krąp, wzdręga, jazgarz i ukleja stanowiące
        odpowiednio 57%, 6%, 2,6% i 0,4%

    where the figures come after *all* the names, in order. A 45-character
    window read 57% - which is the bream share - as the share for `wzdręga`,
    rudd, four words later. Only these shapes are accepted:

        karp 2,8%          karpia (1%)          leszcz 15,8%
        szczupak (10,5%)   Karp o średniej wadze 3,90 kg stanowił 5,4%

    Anything looser is dropped rather than guessed at. A missing share is a
    gap; a wrong one is a lie about a water.
    """
    guard = "(?!iowat)" if polish == "karp" else ""
    escaped = re.escape(polish)
    weight_clause = r"(?:\s+o\s+średni\w+\s+(?:masie|wadze)\s*\d+(?:,\d+)?\s*kg)?"
    connector = r"(?:\s*\(|\s+stanowi\w*|\s*[–-]|\s+)"
    pattern = rf"{EDGE_L}{escaped}{guard}\w*{EDGE_R}{weight_clause}{connector}\s*(\d+(?:,\d+)?)\s*%"
    found = first(pattern, body)
    if found is None:
        # One reversed shape, and only one: "udzialem (85%) zaznaczyl sie
        # karp". It names a single species, so it cannot be confused with the
        # "respectively" lists that forced the strict rule above.
        reversed_pattern = (
            rf"udzia[łl]em\s*\(?({DEC})\s*%\)?[^.]{{0,45}}?"
            rf"{EDGE_L}{escaped}{guard}"
        )
        found = first(reversed_pattern, body)
    return num(found) if found else None


def _species_weight(body: str, polish: str) -> float | None:
    """Mean weight of this species, where the report states one.

    Two phrasings: "karp o sredniej masie 2,74 kg" and the adjectival
    "srednio 3,36-kilogramowy karp".
    """
    guard = "(?!iowat)" if polish == "karp" else ""
    escaped = re.escape(polish)
    found = first(
        rf"\b{escaped}{guard}\w*\s+o\s+średni\w+\s+(?:masie|wadze)\s*(\d+(?:,\d+)?)\s*kg", body
    ) or first(rf"średnio\s*(\d+(?:,\d+)?)-?\s*kilogramow\w*\s+{escaped}", body)
    return num(found) if found else None


def parse(pages: list[str]) -> list[WaterStats]:
    body_start = next(i for i, p in enumerate(pages) if p.strip().startswith(BODY_MARKER))
    text = "\n".join(pages[body_start:])
    text = re.sub(r"-\s*\n\s*", "", text)   # words hyphenated across a line break
    text = re.sub(r"[ \t]+", " ", text)

    heads = list(HEAD.finditer(text))
    out: list[WaterStats] = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[head.end():end]

        anglers = first(r"(\d[\d ]{0,7})\s*w[eę]dkarz", body)
        total = first(
            r"(?:Sumaryczny|[CcaŁł]ałkowity|ogólny|Globalny|zarejestrowany)\s+odłow?y?"
            r"[^.]{0,45}?(\d[\d ]{0,7}(?:,\d+)?)\s*kg",
            body,
        ) or first(
            r"odłow?y?\s+(?:wyniósł|wyniosły|osiągnął)[^.]{0,25}?(\d[\d ]{0,7}(?:,\d+)?)\s*kg",
            body,
        )
        per_year = (
            first(rf"({DEC})\s*kg\s+rocznie", body)
            or first(r"roczn\w*\s+odłów[^.]{0,45}?(\d+(?:,\d+)?)\s*kg", body)
            or first(r"rocznie\s*(\d+(?:,\d+)?)\s*kg", body)
            or first(r"(\d+(?:,\d+)?)\s*kg\s+złowionych\s+ryb", body)
            or first(r"odłów\s+na\s+1\s+wędkując\w*\s*(\d+(?:,\d+)?)\s*kg", body)
            or first(rf"({DEC})\s*kg\s+na\s+1\s+wędkarza\s+rocznie", body)
            or first(rf"i\s*({DEC})\s*kg\s+rocznie", body)
        )
        per_day = (
            first(r"dzienn\w*\s+odłow\w*[^.]{0,55}?(\d+(?:,\d+)?)\s*kg", body)
            or first(r"odłów\s+dzienny[^.]{0,45}?(\d+(?:,\d+)?)\s*kg", body)
            or first(r"dzienny\s+odłów[^.]{0,45}?(\d+(?:,\d+)?)\s*kg", body)
            or first(r"łowili\s+średnio\s*(\d+(?:,\d+)?)\s*kg\s+ryb\s+na\s+dzie", body)
            or first(r"dziennie\s+przypadało\s+średnio\s*(\d+(?:,\d+)?)\s*kg", body)
            or first(rf"({DEC})\s*kg\s+w\s+jednym\s+dniu", body)
            or first(rf"({DEC})\s*kg\s+ryb\s+dziennie", body)
            or first(rf"poziomie\s*({DEC})\s*kg\s+ryb\s+dziennie", body)
        )
        days = first(r"(\d+(?:,\d+)?)\s*dni", body) or first(r"(\d+(?:,\d+)?)\s*dnia", body)

        stats = WaterStats(
            table=int(head.group(3)),
            name=re.sub(r"\s+", " ", head.group(2)).strip(),
            anglers=int(num(anglers)) if anglers else None,
            total_kg=num(total) if total else None,
            kg_per_angler_year=num(per_year) if per_year else None,
            kg_per_angler_day=num(per_day) if per_day else None,
            days_per_angler=num(days) if days else None,
        )
        for polish, slug in SPECIES.items():
            share = _species_share(body, polish)
            if share is not None:
                stats.species_pct[slug] = share
            weight = _species_weight(body, polish)
            if weight is not None:
                stats.species_mean_kg[slug] = weight
        out.append(stats)
    return out


def to_yaml(waters: list[WaterStats], year: int, okreg: str, source: str) -> str:
    from app.discover.pzw import normalise

    lines = [
        f"# Registered angling catches, {okreg} okreg, {year} season.",
        "#",
        "# GENERATED by tools/catch_report_extract.py from the okreg's own",
        f"# report: {source}",
        "# Do not hand-edit: re-run the tool against the new season's PDF.",
        "#",
        "# THESE ARE MEASURED FIGURES, and the only real CPUE this project has.",
        "# They are kg per angler-day, not fish per hour, and they come from",
        "# voluntarily returned registers - `anglers` is the sample size and",
        "# must travel with every number shown (law 5).",
        f"year: {year}",
        f"okreg: {okreg}",
        "waters:",
    ]
    for water in sorted(waters, key=lambda w: w.table):
        key = normalise(water.name)
        if not key or water.kg_per_angler_day is None:
            continue
        lines.append(f"  - name: {water.name!r}")
        lines.append(f"    key: {key!r}")
        lines.append(f"    table: {water.table}")
        if water.anglers is not None:
            lines.append(f"    anglers: {water.anglers}")
        if water.days_per_angler is not None:
            lines.append(f"    days_per_angler: {water.days_per_angler}")
        if water.total_kg is not None:
            lines.append(f"    total_kg: {water.total_kg}")
        if water.kg_per_angler_year is not None:
            lines.append(f"    kg_per_angler_year: {water.kg_per_angler_year}")
        lines.append(f"    kg_per_angler_day: {water.kg_per_angler_day}")
        if water.species_pct:
            lines.append("    species_pct:")
            for slug, pct in sorted(water.species_pct.items(), key=lambda kv: -kv[1]):
                lines.append(f"      {slug}: {pct}")
        if water.species_mean_kg:
            lines.append("    species_mean_kg:")
            for slug, kilos in sorted(water.species_mean_kg.items()):
                lines.append(f"      {slug}: {kilos}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--okreg", default="mazowiecki")
    parser.add_argument(
        "--source", default="Okreg Mazowiecki PZW, annual pressure and catch report"
    )
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - authoring tool
        raise SystemExit(
            "pypdf is not installed; it is intentionally not a project dependency. "
            "See tools/pzw_extract.py for how to install it out of tree."
        ) from None

    reader = PdfReader(str(args.pdf))
    pages = [(page.extract_text(extraction_mode="layout") or "") for page in reader.pages]
    waters = parse(pages)

    out = args.out or Path(f"config/catch_reports/{args.okreg}-{args.year}.yaml")
    out.parent.mkdir(parents=True, exist_ok=True)
    open(out, "w", encoding="utf-8").write(to_yaml(waters, args.year, args.okreg, args.source))

    usable = [w for w in waters if w.kg_per_angler_day is not None]
    with_carp = [w for w in usable if "carp" in w.species_pct]
    print(f"{len(waters)} sections parsed -> {len(usable)} with a daily rate -> {out}")
    print(f"  with a carp share: {len(with_carp)}")
    print(f"  with any species split: {sum(1 for w in usable if w.species_pct)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
