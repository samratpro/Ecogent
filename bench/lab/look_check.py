"""
Look check for the lab's level 1 (renamed classes / ids): the page must look the same as level 0,
because level 1 is meant as a code-only change. Screenshots of every public lab page at level 0 and 1
(two seeds) are compared pixel by pixel in the browser. Prints "LAB LOOK OK".

    python -m bench.lab.look_check [--out <folder for screenshots>]

Levels 2-4 change the look on purpose (banner, wording, redesign) and are not compared.
"""

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import drift
from .selftest import PUBLIC
from .server import LabServer

MAX_DIFF = 0.001
DIFF = """async ([a, b]) => {
  const load = (src) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.src = src; });
  const [x, y] = await Promise.all([load(a), load(b)]);
  if (x.width !== y.width || x.height !== y.height) return 1;
  const c = document.createElement('canvas'); c.width = x.width; c.height = x.height;
  const g = c.getContext('2d');
  g.drawImage(x, 0, 0); const p = g.getImageData(0, 0, c.width, c.height).data;
  g.clearRect(0, 0, c.width, c.height); g.drawImage(y, 0, 0); const q = g.getImageData(0, 0, c.width, c.height).data;
  let d = 0; for (let i = 0; i < p.length; i += 4) if (Math.abs(p[i]-q[i]) + Math.abs(p[i+1]-q[i+1]) + Math.abs(p[i+2]-q[i+2]) > 24) d++;
  return d / (p.length / 4);
}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--port", type=int, default=8794)
    args = ap.parse_args()
    out = Path(args.out or tempfile.mkdtemp(prefix="lab_look_"))
    out.mkdir(parents=True, exist_ok=True)
    srv = LabServer(port=args.port)
    fails = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            cmp_page = browser.new_page()
            for seed in (1, 2):
                for path in PUBLIC:
                    shots = []
                    for level in (0, 1):
                        srv.set(level, seed)
                        srv.reset()
                        page = browser.new_page(viewport={"width": 1280, "height": 900})
                        page.goto(srv.base + path, wait_until="networkidle")
                        name = f"s{seed}_L{level}_{path.strip('/').replace('/', '_').replace('?', '_') or 'root'}.png"
                        shots.append(page.screenshot(full_page=True, animations="disabled", path=str(out / name)))
                        page.close()
                    ratio = cmp_page.evaluate(DIFF, ["data:image/png;base64," + base64.b64encode(s).decode() for s in shots])
                    ok = ratio <= MAX_DIFF
                    print(f"seed {seed}  {path:<40} level 1 vs 0: {ratio:.4%} {'OK' if ok else 'DIFFERENT'}")
                    if not ok:
                        fails.append(f"{seed} {path}")
            browser.close()
    finally:
        srv.close()
    print(f"screenshots: {out}  (level 1 CSS fix: {drift.LEVEL1_CSS_FIX})")
    print("LAB LOOK OK" if not fails else f"LAB LOOK FAILED ({len(fails)})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
