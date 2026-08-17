"""Drive the Pyodide spike page in a real browser and photograph the verdict.

CLAUDE.md: produce the artefact and look at it. A spike page that has never been
opened proves nothing, and "it should work" is not a result. This serves a built
spike directory, drives headless Chromium at it, waits for the verdict, prints
every step's outcome, and writes a screenshot.

    python tools/build_spike.py --out dist --base ""
    python tools/spike_check.py --site dist

Options that matter when the network is restricted:

    --core DIR    serve a local copy of the Pyodide core files and point the
                  page at them (`?index=`). The core alone - CPython, the
                  stdlib, no third-party wheels - is what the npm `pyodide`
                  package ships, so this verifies boot and the pure-Python
                  scoring path without reaching the CDN.
    --only-core   stop before shapely, for the same situation.

Exit code is 0 only when the page reports no failed step.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import pathlib
import shutil
import socketserver
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent


def chromium_kwargs() -> dict[str, str]:
    """Use the image's pre-installed Chromium when Playwright's own is missing.

    Sandboxes and CI images often ship one Chromium at a fixed path while the
    pip-installed Playwright wants a build number it was never given. Rather
    than fail, point at whatever is actually on disk.
    """
    roots = [pathlib.Path("/opt/pw-browsers"), pathlib.Path.home() / ".cache/ms-playwright"]
    patterns = ["chromium*/chrome-linux*/chrome", "chromium*/chrome-linux*/headless_shell"]
    for root in roots:
        for pattern in patterns:
            for candidate in sorted(root.glob(pattern), reverse=True):
                if candidate.is_file():
                    return {"executable_path": str(candidate)}
    return {}


def serve(directory: pathlib.Path) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(directory)
    )

    class Quiet(socketserver.TCPServer):
        allow_reuse_address = True

        def handle_error(self, request, client_address):  # noqa: ANN001
            pass

    httpd = Quiet(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def reference_run(site: pathlib.Path) -> int:
    """Run the page's own harness in this interpreter, against real shapely.

    This is the control. If a step fails in the browser, the question is
    immediately whether Pyodide is at fault or the check is simply wrong, and
    the only way to answer it is to run the identical code somewhere known
    good. Nothing here touches a browser.
    """
    page = (site / "spike" / "pyodide" / "index.html").read_text(encoding="utf-8")
    start = page.index('<script id="harness"')
    harness = page[page.index(">", start) + 1 : page.index("</script>", start)]
    payload = (site / "spike" / "pyodide" / "payload.json").read_text(encoding="utf-8")

    scope: dict[str, object] = {"PAYLOAD_JSON": payload, "__name__": "spike_harness"}
    sys.path.insert(0, str(ROOT))
    exec(compile(harness, "spike-harness", "exec"), scope)  # noqa: S102

    failed = 0
    print("--- reference run (this interpreter, real shapely) " + "-" * 19)
    for name in ("step_scoring", "step_grid", "step_geometry", "step_end_to_end"):
        result = scope[name]()  # type: ignore[operator]
        state = "pass" if result["ok"] else "fail"
        failed += 0 if result["ok"] else 1
        print(f"  [{state:>7}] {result.get('python_ms', '—'):>8} ms  {name}")
        print(f"            {result['detail']}")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="dist", help="a directory built by build_spike.py")
    parser.add_argument(
        "--reference",
        action="store_true",
        help="run the page's harness in this interpreter instead of a browser",
    )
    parser.add_argument("--core", default="", help="local Pyodide core files to serve")
    parser.add_argument(
        "--prefix",
        default="",
        help='serve --site under this path, e.g. "/fwapp", to test a project-Pages build',
    )
    parser.add_argument("--only-core", action="store_true")
    parser.add_argument("--shot", default="spike-verdict.png")
    parser.add_argument("--timeout", type=int, default=180, help="seconds")
    args = parser.parse_args()

    site = pathlib.Path(args.site).resolve()
    if not (site / "spike" / "pyodide" / "index.html").exists():
        print(f"no spike page under {site} - run tools/build_spike.py first", file=sys.stderr)
        return 2

    if args.reference:
        return reference_run(site)

    prefix = "/" + args.prefix.strip("/") if args.prefix.strip("/") else ""
    if prefix:
        # A project-Pages build has every URL rewritten under /<repo>/, so it
        # only resolves when served from a parent directory of that name. Stage
        # one in a temp dir rather than asking the caller to lay it out by hand.
        staged = pathlib.Path(tempfile.mkdtemp(prefix="spike-")) / prefix.lstrip("/")
        shutil.copytree(site, staged)
        root, site = staged.parent, staged
    else:
        root = site

    query = []
    if args.core:
        core = pathlib.Path(args.core).resolve()
        served = site / "pyodide-core"
        if served.exists():
            shutil.rmtree(served)
        shutil.copytree(core, served)
        query.append(f"index={prefix}/pyodide-core/")
    if args.only_core:
        query.append("only=core")

    from playwright.sync_api import sync_playwright

    httpd, port = serve(root)
    url = f"http://127.0.0.1:{port}{prefix}/spike/pyodide/"
    if query:
        url += "?" + "&".join(query)
    print(f"opening {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**chromium_kwargs())
            page = browser.new_page(viewport={"width": 900, "height": 1400})
            page.on("console", lambda m: print(f"  [console.{m.type}] {m.text}"))
            page.on("pageerror", lambda e: print(f"  [pageerror] {e}"))
            page.goto(url)
            page.wait_for_function(
                "document.getElementById('verdict').className !== 'card'",
                timeout=args.timeout * 1000,
            )
            page.wait_for_timeout(300)

            verdict = page.inner_text("#verdict")
            rows = page.eval_on_selector_all(
                "#steps tr",
                """rows => rows.map(r => ({
                     name: r.querySelector('.n').textContent,
                     detail: r.querySelector('.detail').textContent,
                     state: r.querySelector('.chip').textContent,
                     ms: r.querySelector('.t').textContent,
                   }))""",
            )
            env = page.inner_text("#env")
            cost = page.inner_text("#cost")

            shot = pathlib.Path(args.shot).resolve()
            page.screenshot(path=str(shot), full_page=True)
            browser.close()
    finally:
        httpd.shutdown()

    print("\n--- steps " + "-" * 60)
    for r in rows:
        print(f"  [{r['state']:>7}] {r['ms']:>6} ms  {r['name']}")
        if r["detail"]:
            print(f"            {r['detail']}")
    print("\n--- environment " + "-" * 54)
    print("  " + env.replace("\n", "\n  "))
    print("\n--- cost " + "-" * 61)
    print("  " + cost.replace("\n", "\n  "))
    print("\n--- verdict " + "-" * 58)
    print("  " + verdict.replace("\n", "\n  "))
    print(f"\nscreenshot: {shot}")

    return 0 if not any(r["state"] == "fail" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
