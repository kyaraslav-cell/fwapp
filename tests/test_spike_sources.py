"""The Pyodide spike ships module *sources*, so its imports must stay shippable.

`tools/build_spike.py` copies a fixed list of files into the browser and imports
them there. Nothing in the normal test run or in `make check` notices when that
list goes stale: adding an import to `app/geo/grid.py`, or splitting a helper
out of `app/rules/zone_score.py`, breaks only the published page, and only for
whoever opens it next.

So this walks the shipped sources and insists that every import they make is
either the standard library, a package Pyodide actually distributes, or another
file on the ship list.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

from tools.build_spike import SOURCE_FILES

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Third-party packages the browser can get from the Pyodide distribution. Each
# one is in pyodide-lock.json for the pinned version; anything else has to be
# checked there before it goes on this list.
PYODIDE_PROVIDED = {"shapely", "numpy"}


def top_level_imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("relative_path", SOURCE_FILES)
def test_shipped_source_exists(relative_path: str) -> None:
    assert (ROOT / relative_path).is_file(), f"{relative_path} is on the ship list but gone"


@pytest.mark.parametrize("relative_path", SOURCE_FILES)
def test_shipped_source_imports_nothing_the_browser_lacks(relative_path: str) -> None:
    shipped = {p.removesuffix(".py").replace("/", ".") for p in SOURCE_FILES}
    for name in top_level_imports((ROOT / relative_path).read_text(encoding="utf-8")):
        root = name.split(".")[0]
        if root == "app":
            assert name in shipped, (
                f"{relative_path} imports {name}, which build_spike.py does not ship - "
                "add it to SOURCE_FILES or the spike page will fail in the browser"
            )
        elif root not in PYODIDE_PROVIDED:
            assert root in sys.stdlib_module_names, (
                f"{relative_path} imports {root}, which is neither stdlib nor a package "
                "Pyodide distributes - check pyodide-lock.json before shipping it"
            )
