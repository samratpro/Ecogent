"""
Look check for the test shop: markup levels 1-3 must change the code but not the look or the text.

For each page, markup 0..3 (layout 0, copy 0, no interruptions):
  - full-page screenshot, compared pixel by pixel with markup 0   (allowed: 0.1% of pixels)
  - visible words, compared with markup 0                          (same words; code order may differ)
  - class names, compared with markup 0                            (markup >= 1: almost none may be shared)
Also saves screenshots of layout 1 / 2, copy 1 and interruptions 2 for a human look (not compared).
Prints "LOOK OK" when every check passes.

    python test_shop/check_look.py [--base http://127.0.0.1:3010] [--out <folder for screenshots>]
The server must be running (node test_shop/server.js).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PAGES = {"home": "/", "category": "/c/electronics", "search": "/search?q=pro", "product": "/p/1001/x",
         "cart": "/cart", "checkout": "/checkout", "help": "/help", "login": "/account/login"}
MAX_DIFF = 0.001

VISIBLE_TEXT = """() => {
  const out = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const n = walk.currentNode, t = n.textContent.trim();
    if (!t) continue;
    let e = n.parentElement, hidden = false;
    while (e) { const cs = getComputedStyle(e);
      if (cs.clip === 'rect(0px, 0px, 0px, 0px)' || cs.display === 'none' || cs.visibility === 'hidden') { hidden = true; break; }
      e = e.parentElement; }
    if (!hidden) out.push(t);
  }
  return out.join(' ').replace(/\\s+/g, ' ');
}"""
CLASSES = "() => [...new Set([...document.querySelectorAll('[class]')].flatMap(e => [...e.classList]))]"
DIFF = """async ([a, b]) => {
  const load = (src) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.src = src; });
  const [x, y] = await Promise.all([load(a), load(b)]);
  if (x.width !== y.width || x.height !== y.height) return {size: [x.width, x.height, y.width, y.height], ratio: 1};
  const c = document.createElement('canvas'); c.width = x.width; c.height = x.height;
  const g = c.getContext('2d');
  g.drawImage(x, 0, 0); const p = g.getImageData(0, 0, c.width, c.height).data;
  g.clearRect(0, 0, c.width, c.height); g.drawImage(y, 0, 0); const q = g.getImageData(0, 0, c.width, c.height).data;
  let d = 0; for (let i = 0; i < p.length; i += 4) if (Math.abs(p[i]-q[i]) + Math.abs(p[i+1]-q[i+1]) + Math.abs(p[i+2]-q[i+2]) > 24) d++;
  return {ratio: d / (p.length / 4)};
}"""


def lab(base: str, key: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-lab-key": key, "content-type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


CART_ITEM: dict = {}


def shoot(browser, base: str, path: str, file: Path) -> tuple[bytes, str, list]:
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    r = ctx.request.post(base + "/api/cart", data=CART_ITEM)          # so cart and checkout are not empty
    if not r.ok:
        raise SystemExit(f"could not add {CART_ITEM} to the cart: {r.text()}")
    page = ctx.new_page()
    page.goto(base + path, wait_until="networkidle")
    page.wait_for_timeout(400)
    png = page.screenshot(full_page=True, animations="disabled", path=str(file))
    text, classes = page.evaluate(VISIBLE_TEXT), page.evaluate(CLASSES)
    ctx.close()
    return png, text, classes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3010")
    ap.add_argument("--out", default=str(HERE / "look_check_out"))
    args = ap.parse_args()
    key = (HERE / ".lab_key").read_text().strip()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    saved = lab(args.base, key, "/__lab/state")["config"]
    lab(args.base, key, "/__lab/config", {"content": 0, "reset": True})
    item = next(p for p in lab(args.base, key, "/__lab/truth")["products"] if p["stock"] >= 5 and not p["sizes"])
    CART_ITEM.update(productId=item["id"], qty=1, color=item["colors"][0] if item["colors"] else None)
    fails = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        cmp_page = browser.new_page()
        try:
            for markup in (0, 1, 2, 3):
                lab(args.base, key, "/__lab/config", {"markup": markup, "layout": 0, "copy": 0, "interruptions": 0,
                                                       "content": 0, "reset": True})
                for name, path in PAGES.items():
                    png, text, classes = shoot(browser, args.base, path, out / f"m{markup}_{name}.png")
                    if markup == 0:
                        PAGES_BASE[name] = (png, text, set(classes))
                        continue
                    b_png, b_text, b_cls = PAGES_BASE[name]
                    d = cmp_page.evaluate(DIFF, ["data:image/png;base64," + base64.b64encode(b_png).decode(),
                                                 "data:image/png;base64," + base64.b64encode(png).decode()])
                    shared = len(b_cls & set(classes)) / max(1, len(b_cls))
                    status = []
                    if d["ratio"] > MAX_DIFF:
                        status.append(f"look differs {d['ratio']:.4%}" + (f" size {d.get('size')}" if d.get("size") else ""))
                    # Same visible words; their order in the code may differ (markup 2 reorders fields, CSS restores the view).
                    if sorted(text.split()) != sorted(b_text.split()):
                        status.append("visible text differs")
                    if shared > 0.05:
                        status.append(f"{shared:.0%} class names unchanged")
                    line = f"markup {markup}  {name:<9} pixels {d['ratio']:.4%}  classes shared {shared:.0%}  " + \
                           ("OK" if not status else "FAIL: " + "; ".join(status))
                    print(line)
                    if status:
                        fails.append(line)
            for label, cfg in (("layout1", {"layout": 1}), ("layout2", {"layout": 2}), ("copy1", {"copy": 1}),
                               ("interruptions2", {"interruptions": 2})):
                lab(args.base, key, "/__lab/config", {"markup": 0, "layout": 0, "copy": 0, "interruptions": 0, **cfg})
                for name in ("home", "category", "product", "checkout"):
                    shoot(browser, args.base, PAGES[name], out / f"{label}_{name}.png")
        finally:
            browser.close()
            lab(args.base, key, "/__lab/config", {k: saved[k] for k in ("markup", "layout", "copy", "interruptions", "content")})
    print(f"screenshots: {out}")
    print("LOOK OK" if not fails else f"LOOK FAILED ({len(fails)})")
    sys.exit(1 if fails else 0)


PAGES_BASE: dict = {}

if __name__ == "__main__":
    main()
