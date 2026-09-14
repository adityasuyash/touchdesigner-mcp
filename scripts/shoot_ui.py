"""Screenshot the control UI, without TouchDesigner in the loop.

Every visual check of the gallery used to go through a Web Render TOP inside
TouchDesigner, because that was the browser we had. It is not a reliable one:
after enough create/destroy cycles its whole CEF subsystem wedges and every Web
Render TOP returns black frames with no error at all -- including one pointed at
`example.com`, which is how it was diagnosed. Only restarting TouchDesigner
clears it, and restarting TouchDesigner to look at a web page is absurd.

So the UI is shot with a real headless browser. It also means a screenshot no
longer depends on TouchDesigner running at all, which matters because the pages
worth looking at are exactly the ones you reach for when something is wrong.

    python scripts/shoot_ui.py out.png
    python scripts/shoot_ui.py out.png --pick monument --scroll 2350
    python scripts/shoot_ui.py out.png --url http://127.0.0.1:8765/ --full

`--pick` chooses a lyric renderer before the shot, which is the only way to see
the beat row's second meaning: with a renderer that cannot carry a backdrop
picked, the row becomes "Or instead of the words".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8765/"

# Wait for every <video> in the gallery to have decoded a frame. Without this
# the shot catches a wall of empty tiles and looks exactly like the bug the
# screenshot was taken to rule out.
READY = """
() => {
  const vs = Array.from(document.querySelectorAll('video'));
  if (!vs.length) return false;
  return vs.every(v => v.readyState >= 2 || v.dataset.failed === '1');
}
"""

# `setPick` is the gallery's own entry point, so this drives the page the way a
# click does rather than reaching into its state.
PICK = """
(slug) => {
  if (typeof setPick !== 'function') return false;
  if (typeof TYPE_SLUG !== 'undefined' && TYPE_SLUG === slug) return true;
  setPick('lyric', slug, '');
  return true;
}
"""


def shoot(url: str, out: Path, pick: str = "", scroll: int = 0,
          width: int = 1280, height: int = 1280, full: bool = False,
          settle: float = 2.0, theme: str = "dark") -> Path:
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # Dark by default because the UI is dark-first; a headless browser
            # reports "light" unless told otherwise, so every shot came back in
            # a theme nobody uses.
            page = browser.new_page(viewport={"width": width, "height": height},
                                    color_scheme=theme, device_scale_factor=1)
            page.goto(url, wait_until="networkidle", timeout=60_000)
            if pick:
                # The gallery is filled by a fetch, so the pick has to wait for
                # the cards rather than for the document.
                page.wait_for_function(
                    "() => document.querySelectorAll('.scard').length > 3",
                    timeout=30_000)
                page.wait_for_function(PICK, arg=pick, timeout=30_000)
            try:
                page.wait_for_function(READY, timeout=30_000)
            except Exception:
                print("warning: not every preview reported a decoded frame",
                      file=sys.stderr)
            if scroll:
                page.evaluate(
                    "(y) => { const m = document.querySelector('#scroll');"
                    " if (m) m.scrollTop = y; else window.scrollTo(0, y); }",
                    scroll)
            page.wait_for_timeout(int(settle * 1000))
            page.screenshot(path=str(out), full_page=full)
        finally:
            browser.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("out", type=Path, help="where to write the PNG")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--pick", default="", metavar="RENDERER",
                    help="slug of a lyric renderer to choose before shooting")
    ap.add_argument("--scroll", type=int, default=0, metavar="PX")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=1280)
    ap.add_argument("--full", action="store_true",
                    help="the whole page rather than the viewport")
    ap.add_argument("--settle", type=float, default=2.0,
                    help="seconds to let the previews play before shooting")
    ap.add_argument("--theme", default="dark", choices=("dark", "light"),
                    help="which colour scheme to report to the page")
    a = ap.parse_args(argv)
    try:
        path = shoot(a.url, a.out, pick=a.pick, scroll=a.scroll,
                     width=a.width, height=a.height, full=a.full,
                     settle=a.settle, theme=a.theme)
    except ImportError:
        print("playwright is not installed: pip install -r requirements-dev.txt"
              " && python -m playwright install chromium", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
