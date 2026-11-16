"""
Self-test of the test-shop tasks (no LLM, no browser; the shop must be running or it is started):
  1. every oracle gives success for the correct answer, built from the ground truth (scraping / analysis: a file;
     automation: the right actions done through the shop's own API, like a user's browser would)
  2. every oracle gives failure for no answer
  3. stale answers fail: the correct answer for the original data, scored after the "new data" change,
     fails for every task whose answer depends on the data
Prints "SHOP TASKS OK".

    python -m bench.shop_selftest
"""

from __future__ import annotations

import csv
import http.cookiejar
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

from bench import shop_tasks as S
from bench.lab.tasks import USER_INFO
from ecogent import test_shop as ts

DATA_DEPENDENT = {"nw_electronics_all", "nw_books_under_20", "nw_sports_top_rated", "nw_kitchen_price_range",
                  "nw_top_deals", "nw_wishlist_pets"}


class Browser:
    """A cookie-keeping client for the shop API (one shop session, like one browser)."""

    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path: str, body=None, method=None):
        req = urllib.request.Request(ts.BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"content-type": "application/json"}, method=method or ("POST" if body is not None else "GET"))
        with self.op.open(req) as r:
            return json.loads(r.read())


def answer_file(task, truth: dict, folder: Path) -> Path | None:
    """The correct deliverable for scraping / analysis tasks, from the ground truth."""
    prods = truth["products"]
    if task.type == "scraping":
        if task.name == "nw_electronics_all":
            rows = [[p["name"], p["brand"], f"${p['price']:.2f}", "in stock" if p["stock"] else "out of stock"]
                    for p in prods if p["category"] == "electronics"]
        elif task.name == "nw_books_under_20":
            rows = [[p["name"], p.get("author", ""), f"{p['price']:.2f}"] for p in prods if p["category"] == "books" and p["price"] < 20]
        else:
            rows = [[p["name"], str(p["rating"]), f"{p['price']:.2f}"] for p in prods
                    if p["category"] == "sports-outdoors" and p["rating"] >= 4.5]
        out = folder / f"{task.name}.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["name", "a", "b", "c"], *rows])
        return out
    if task.type == "analysis":
        if task.name == "nw_kitchen_price_range":
            k = [p for p in prods if p["category"] == "home-kitchen" and p["stock"] > 0]
            lo, hi = min(k, key=lambda p: p["price"]), max(k, key=lambda p: p["price"])
            text = f"Cheapest: {lo['name']} at ${lo['price']:.2f}. Most expensive: {hi['name']} at ${hi['price']:.2f}."
        elif task.name == "nw_policy_summary":
            text = ("Returns are accepted within 30 days. Standard shipping costs $4.99 and is free from $50; "
                    "express costs $14.99.")
        else:
            sale = sorted([p for p in prods if p["compareAt"] and p["stock"] > 0],
                          key=lambda p: -(p["compareAt"] - p["price"]) / p["compareAt"])[:3]
            text = "\n".join(f"- {p['name']}: was ${p['compareAt']:.2f}, now ${p['price']:.2f}" for p in sale)
        out = folder / f"{task.name}.md"
        out.write_text(text, encoding="utf-8")
        return out
    return None


def do_actions(task, truth: dict) -> None:
    """The correct automation, through the shop API."""
    b = Browser()
    if task.name == "nw_buy_earbuds":
        b.call("/cart", {"productId": 1001, "qty": 1, "color": "White"})
        b.call("/cart/coupon", {"code": "SAVE10"})
        b.call("/orders", {"contact": {"email": USER_INFO["email"], "name": USER_INFO["full_name"]},
                           "address": {"line1": "1 Test Street", "city": "Dhaka", "postcode": "1207", "country": "Bangladesh"},
                           "shipping": "express", "payment": {"card": "4242 4242 4242 4242"}})
    elif task.name == "nw_wishlist_pets":
        b.call("/login", {"email": "ada.tester@example.com", "password": "Shop!2026"})
        for p in S._cheapest_pets(truth):
            b.call("/wishlist", {"productId": p["id"]})
    elif task.name == "nw_cart_setup":
        b.call("/cart", {"productId": 1005, "qty": 2, "color": "Black"})
        b.call("/cart", {"productId": 1055, "qty": 1})
        b.call("/cart/coupon", {"code": "FREESHIP"})


def main() -> None:
    target = S.ShopTarget()
    fails = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for task in S.TASKS:
                # 1. correct answer on the original shop
                target.set(0, 1)
                truth0 = target.state.truth()
                out = answer_file(task, truth0, folder)
                do_actions(task, truth0)
                ok = task.oracle(out, target.state)
                # 2. no answer
                target.set(0, 1)
                empty = task.oracle(None, target.state)
                # 3. the original answer, scored after the data changed (automation: replayed blindly, e.g. a cached list)
                target.set(8, 1)
                if task.type == "automation":
                    if task.name == "nw_wishlist_pets":
                        b = Browser()
                        b.call("/login", {"email": "ada.tester@example.com", "password": "Shop!2026"})
                        for p in S._cheapest_pets(truth0):
                            b.call("/wishlist", {"productId": p["id"]})
                    else:
                        do_actions(task, truth0)
                stale = task.oracle(out, target.state)
                expect_stale_fail = task.name in DATA_DEPENDENT
                good = ok["success"] and not empty["success"] and (stale["success"] != expect_stale_fail)
                print(f"{task.name:<24} correct={ok['success']!s:<5} ({ok['detail']})  empty={empty['success']!s:<5} "
                      f"stale={'fails' if not stale['success'] else 'passes'}{' (expected)' if good else ''}")
                if not good:
                    fails.append(task.name)
    finally:
        target.close()
    print("SHOP TASKS OK" if not fails else f"SHOP TASKS FAILED: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
