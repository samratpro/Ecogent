"""
Flow check for the test shop: a scripted user can finish the main journeys in every layout and markup
version (a version nobody can finish would be an unfair test). Uses role/label selectors, like a person
reading the page, never the version-specific class names.

Journeys per version: search -> product -> choose colour -> add to cart -> cart -> coupon -> checkout ->
order confirmed (checked against the server's recorded orders); log in -> order history.
Prints "FLOWS OK".

    python test_shop/check_flows.py [--base http://127.0.0.1:3010] [--headed]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WORDS = {0: {"add": "Add to cart", "checkout": "Checkout", "continue": "Continue", "place": "Place order", "apply": "Apply",
             "coupon": "Coupon code", "signin": "Sign in", "email": "Email", "orders": "My orders"},
         1: {"add": "Add to bag", "checkout": "Check out", "continue": "Next step", "place": "Complete purchase", "apply": "Redeem",
             "coupon": "Promo code", "signin": "Log in", "email": "Email address", "orders": "Order history"}}


def lab(base, key, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-lab-key": key, "content-type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def journey(page, base, layout, copy, product):
    w = WORDS[copy]
    page.goto(base + "/")
    page.get_by_role("searchbox").fill(product["name"].split()[-1] if len(product["name"].split()) > 1 else product["name"])
    page.get_by_role("searchbox").press("Enter")
    page.get_by_role("link", name=product["name"], exact=True).first.click()
    expect(page.get_by_role("heading", level=1)).to_have_text(product["name"])
    color = product["colors"][1]
    if layout == 2:
        page.get_by_role("radio", name=color, exact=True).click()
    else:
        page.get_by_role("combobox", name=re.compile("colou?r", re.I)).select_option(color)
    page.get_by_role("button", name=w["add"], exact=True).click()
    page.get_by_role("status").filter(has_text=re.compile("added", re.I)).wait_for()
    page.goto(base + "/cart")
    page.get_by_role("textbox", name=w["coupon"]).fill("SAVE10")
    page.get_by_role("button", name=w["apply"], exact=True).click()
    page.get_by_text("SAVE10").first.wait_for()
    page.get_by_role("button", name=w["checkout"], exact=True).click()
    fields = {"email": "ada.tester@example.com", "name": "Ada Tester", "line1": "1 Test Street", "city": "Dhaka", "postcode": "1207"}
    for k, v in fields.items():
        page.locator(f"input[name={k}]").fill(v)
    page.locator("select[name=country]").select_option("Bangladesh")
    if layout != 2:
        page.get_by_role("button", name=w["continue"], exact=True).click()
        page.get_by_role("radio", name=re.compile("Express")).check()
        page.get_by_role("button", name=w["continue"], exact=True).click()
    else:
        page.get_by_role("radio", name=re.compile("Express")).check()
    page.locator("input[name=card]").fill("4242 4242 4242 4242")
    page.locator("input[name=exp]").fill("12/29")
    page.locator("input[name=cvc]").fill("123")
    page.get_by_role("button", name=re.compile("^" + w["place"])).click()
    page.wait_for_url(re.compile(r"/order/ORD-"))
    return page.url.rsplit("/", 1)[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3010")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    key = (HERE / ".lab_key").read_text().strip()
    saved = lab(args.base, key, "/__lab/state")["config"]
    fails = []
    versions = [(m, l, c, i) for m in (0, 2, 3) for l in (0, 1, 2) for c, i in ((0, 0), (1, 2))]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        try:
            for markup, layout, copy, inter in versions:
                lab(args.base, key, "/__lab/config", {"markup": markup, "layout": layout, "copy": copy, "interruptions": inter,
                                                       "content": 0, "reset": True})
                product = next(p for p in lab(args.base, key, "/__lab/truth")["products"]
                               if p["stock"] >= 3 and len(p["colors"]) > 1 and not p["sizes"] and p["category"] == "electronics")
                ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                if inter:       # a person closes the popups once; the flow under test is the shop, not the popups
                    ctx.add_init_script("try{sessionStorage.setItem('nw_cookie','1');sessionStorage.setItem('nw_news','1')}catch(e){}")
                page = ctx.new_page()
                page.set_default_timeout(8000)
                tag = f"markup {markup} layout {layout} copy {copy} interruptions {inter}"
                try:
                    order_id = journey(page, args.base, layout, copy, product)
                    orders = lab(args.base, key, "/__lab/state")["orders"]
                    ok = any(o["id"] == order_id and o["lines"][0]["productId"] == product["id"] and o["coupon"] == "SAVE10"
                             and o["shipping"] == "express" for o in orders)
                    w = WORDS[copy]
                    page.goto(args.base + "/account/login")
                    page.get_by_role("textbox", name=w["email"]).fill("ada.tester@example.com")
                    page.locator("input[name=password]").fill("Shop!2026")
                    page.get_by_role("button", name=w["signin"], exact=True).click()
                    page.get_by_role("heading", name=w["orders"]).wait_for()
                    print(f"{tag}: {'OK' if ok else 'FAIL (order not recorded as expected)'}  {order_id}")
                    if not ok:
                        fails.append(tag)
                except Exception as e:  # noqa: BLE001 - report every version
                    print(f"{tag}: FAIL {type(e).__name__}: {str(e).splitlines()[0][:160]}")
                    fails.append(tag)
                ctx.close()
        finally:
            browser.close()
            lab(args.base, key, "/__lab/config", {**{k: saved[k] for k in ("markup", "layout", "copy", "interruptions", "content")}, "reset": True})
    print("FLOWS OK" if not fails else f"FLOWS FAILED ({len(fails)})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
