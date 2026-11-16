"""
Benchmark tasks on the neutral test shop (test_shop/, "Northwind Market", port 3010).

Held-out set: written after Ecogent's prompts were frozen and never used to tune it (keep it that way: do
not change Ecogent because of results on these tasks without re-running everything).

Oracles score against the shop's ground truth *at scoring time* (GET /__lab/truth, /__lab/state), so
at the "new data" level the right answer is the new data: an agent that returns cached old prices fails.

Levels (--site shop): each level is ONE real-world change against the original shop (not cumulative),
so a drop in success points to one cause. See test_shop/README.md for what each change is.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ecogent import test_shop as ts                                     # noqa: E402
from bench.lab.tasks import Task, USER_INFO, _norm, _numbers, _result, read_rows, read_text  # noqa: E402

BASE_CFG = {"markup": 0, "layout": 0, "copy": 0, "interruptions": 0, "content": 0}
LEVELS = {0: "original", 1: "code-rebuild", 2: "code-refactor", 3: "code-every-load", 4: "nav-moved",
          5: "redesign", 6: "wording", 7: "popups", 8: "new-data", 9: "everything"}
LEVEL_CFG = {0: {}, 1: {"markup": 1}, 2: {"markup": 2}, 3: {"markup": 3}, 4: {"layout": 1}, 5: {"layout": 2},
             6: {"copy": 1}, 7: {"interruptions": 2}, 8: {"content": "seed"},
             9: {"markup": 2, "layout": 2, "copy": 1, "interruptions": 2, "content": "seed"}}
ADDRESS = "1 Test Street, Dhaka 1207, Bangladesh"
CARD = "card number 4242 4242 4242 4242, expiry 12/29, CVC 123"


class ShopState:
    """What an oracle gets: the shop's ground truth and recorded actions, read when scoring."""

    def truth(self) -> dict:
        return ts.lab("/truth", timeout=10)

    def recorded(self) -> dict:
        return ts.lab("/state", timeout=10)


class ShopTarget:
    """Same interface as bench.lab.server.LabServer, for drift_bench --site shop."""

    def __init__(self, port: int = 0):
        self.base = ts.PUBLIC_URL
        self.state = ShopState()
        self._server = None
        if not ts.is_up():
            print("  starting the test shop (first start builds it, about a minute)...", file=sys.stderr)
            self._server = ts.ShopServer(lambda line: print("  [shop]", line, file=sys.stderr), lambda s: None)
            self._server.start()
            t0 = time.time()
            while not ts.is_up():
                if self._server.state == "failed" or time.time() - t0 > 300:
                    raise SystemExit("The test shop did not start (see the [shop] lines above).")
                time.sleep(1)

    def set(self, level: int, seed: int) -> None:
        cfg = dict(BASE_CFG)
        for k, v in LEVEL_CFG[level].items():
            cfg[k] = seed if v == "seed" else v
        cfg["seed"] = seed                      # different seeds = different class names / different data change
        cfg["reset"] = True
        ts.lab("/config", cfg, timeout=10)

    def reset(self) -> None:
        ts.lab("/reset", {}, timeout=10)

    def config(self) -> dict:
        return ts.lab("/state", timeout=10)["config"]

    def close(self) -> None:
        try:
            ts.lab("/config", {**BASE_CFG, "seed": 1, "reset": True}, timeout=10)
        except (OSError, ValueError):
            pass
        if self._server:
            self._server.stop()


# ----------------------------------------------------------------------------- oracles
def _products(truth: dict, cond: Callable[[dict], bool]) -> list[dict]:
    return [p for p in truth["products"] if cond(p)]


def scrape_oracle(select: Callable[[dict], list[dict]], fields: Callable[[dict], list[float]] = lambda p: [p["price"]]) -> Callable:
    """A row counts when it has an expected product name AND its current values (price, rating)."""
    def oracle(output: Optional[Path], state: ShopState) -> dict:
        want = {_norm(p["name"]): fields(p) for p in select(state.truth())}
        rows = read_rows(output)
        if not rows:
            return _result(0, 0, 0.9, "no output rows")
        good, found = 0, set()
        for r in rows:
            name = next((_norm(c) for c in r if _norm(c) in want), None)
            nums = _numbers(r)
            if name and all(any(abs(n - v) < 0.005 for n in nums) for v in want[name]):
                good += 1
                found.add(name)
        p, rc = good / len(rows), len(found) / max(1, len(want))
        return _result(p, rc, 0.9, f"{len(rows)} rows, {len(found)}/{len(want)} expected with current values")
    return oracle


def _money(v: float) -> str:
    """Regex for a price written as 55.99 / $55.99 / 55.99 USD."""
    return re.escape(f"{v:.2f}")


def facts_oracle(facts: Callable[[dict], list[str]], universe: Callable[[dict], list[str]], need: float = 0.75) -> Callable:
    """facts: regexes the report must contain; universe: product names that count as 'mentioned' (precision)."""
    def oracle(output: Optional[Path], state: ShopState) -> dict:
        truth = state.truth()
        text = read_text(output).lower()
        if not text.strip():
            return _result(0, 0, need, "no report")
        exp = facts(truth)
        found = [f for f in exp if re.search(f, text)]
        names, rest = [], text
        for n in sorted(set(universe(truth)), key=len, reverse=True):   # longest first: "Mixer" is not "Mixer Pro"
            if n.lower() in rest:
                names.append(n)
                rest = rest.replace(n.lower(), " ")
        expected_names = [n for n in universe(truth) if any(re.escape(n.lower()) == f for f in exp)]
        right = [n for n in names if n in expected_names]
        p = len(right) / len(names) if names else (1.0 if found else 0.0)
        return _result(p, len(found) / len(exp), need, f"{len(found)}/{len(exp)} facts, {len(names)} products named")
    return oracle


def order_oracle(product_id: int, color: str, qty: int, shipping: str, coupon: str) -> Callable:
    def oracle(output: Optional[Path], state: ShopState) -> dict:
        orders = state.recorded()["orders"]
        if not orders:
            return _result(0, 0, 1.0, "no order placed")
        good = [o for o in orders
                if [(l["productId"], l["color"], l["qty"]) for l in o["lines"]] == [(product_id, color, qty)]
                and o["shipping"] == shipping and o["coupon"] == coupon
                and _norm(o["contact"]["email"]) == _norm(USER_INFO["email"])
                and _norm(o["contact"]["name"]) == _norm(USER_INFO["full_name"])]
        return _result(len(good) / len(orders), min(1, len(good)), 1.0,
                       f"{len(orders)} orders, {len(good)} exactly as asked")
    return oracle


def wishlist_oracle(select: Callable[[dict], list[dict]], user: str) -> Callable:
    def oracle(output: Optional[Path], state: ShopState) -> dict:
        want = {p["id"] for p in select(state.truth())}
        lists = [s["wishlist"] for s in state.recorded()["sessions"] if s["user"] == user]
        got = set().union(*lists) if lists else set()
        if not got:
            return _result(0, 0, 1.0, "nothing saved by the logged-in user")
        good = got & want
        return _result(len(good) / len(got), len(good) / len(want), 1.0, f"{len(got)} saved, {len(good)}/{len(want)} correct")
    return oracle


def cart_oracle(lines: dict[int, tuple[int, Optional[str]]], coupon: str) -> Callable:
    def oracle(output: Optional[Path], state: ShopState) -> dict:
        rec = state.recorded()
        if rec["orders"]:
            return _result(0, 0, 1.0, "an order was placed although the task said not to")
        best = 0.0
        for s in rec["sessions"]:
            have = {l["productId"]: (l["qty"], l["color"]) for l in s["cart"]}
            if not have:
                continue
            right = sum(1 for pid, (q, c) in lines.items() if have.get(pid) == (q, c))
            score = right / len(lines) * (1 if s["coupon"] == coupon else 0.5) * (1 if set(have) == set(lines) else 0.8)
            best = max(best, score)
        return _result(best, best, 1.0, f"best cart matches {best:.0%} (items, quantities, colours, code)")
    return oracle


# ----------------------------------------------------------------------------- tasks
def _cheapest_pets(truth: dict) -> list[dict]:
    pets = _products(truth, lambda p: p["category"] == "pet-supplies" and p["stock"] > 0)
    return sorted(pets, key=lambda p: (p["price"], p["id"]))[:3]


def _kitchen_extremes(truth: dict) -> list[str]:
    k = _products(truth, lambda p: p["category"] == "home-kitchen" and p["stock"] > 0)
    lo, hi = min(k, key=lambda p: p["price"]), max(k, key=lambda p: p["price"])
    return [re.escape(lo["name"].lower()), _money(lo["price"]), re.escape(hi["name"].lower()), _money(hi["price"])]


def _top_deals(truth: dict) -> list[str]:
    on_sale = _products(truth, lambda p: p["compareAt"] and p["stock"] > 0)
    top = sorted(on_sale, key=lambda p: -(p["compareAt"] - p["price"]) / p["compareAt"])[:3]
    out = []
    for p in top:
        out += [re.escape(p["name"].lower()), _money(p["compareAt"]), _money(p["price"])]
    return out


TASKS = [
    # ---------------------------------------------------------------- scraping
    Task("nw_electronics_all", "scraping",
         "Go to {base} and collect every product in the Electronics category (all pages): name, brand, price "
         "and whether it is in stock. Save the result as a CSV file.",
         scrape_oracle(lambda t: _products(t, lambda p: p["category"] == "electronics")),
         "category, pagination / load more"),
    Task("nw_books_under_20", "scraping",
         "On {base}, find every book that costs less than $20 and save its title, author and price as a CSV file.",
         scrape_oracle(lambda t: _products(t, lambda p: p["category"] == "books" and p["price"] < 20)),
         "price filter or reading every book"),
    Task("nw_sports_top_rated", "scraping",
         "On {base}, list every Sports & Outdoors product with a customer rating of 4.5 or higher: name, rating "
         "and price. Save it as a CSV file.",
         scrape_oracle(lambda t: _products(t, lambda p: p["category"] == "sports-outdoors" and p["rating"] >= 4.5),
                       lambda p: [p["price"], p["rating"]]),
         "rating filter, two values per row"),
    # ---------------------------------------------------------------- analysis
    Task("nw_kitchen_price_range", "analysis",
         "On {base}, look at the Home & Kitchen category. Which in-stock product is the cheapest and which is the "
         "most expensive? Write a short report with both product names and their prices.",
         facts_oracle(_kitchen_extremes, lambda t: [p["name"] for p in _products(t, lambda p: p["category"] == "home-kitchen")]),
         "sorting, stock status"),
    Task("nw_policy_summary", "analysis",
         "Read the help pages of {base} and write a short summary of the return policy and the shipping options: "
         "how many days for returns, the price of standard and express shipping, and when standard shipping is free.",
         facts_oracle(lambda t: [r"\b30\s*days\b|thirty days", r"4\.99", r"14\.99", r"\$?50\b"], lambda t: [], need=1.0),
         "accordion / FAQ text"),
    Task("nw_top_deals", "analysis",
         "On {base}, find the three in-stock products with the biggest percentage discount (sale price compared with "
         "the original price). Report each product's name, original price and sale price.",
         facts_oracle(_top_deals, lambda t: [p["name"] for p in t["products"]], need=0.66),
         "deals section, comparing two prices"),
    # ---------------------------------------------------------------- automation
    Task("nw_buy_earbuds", "automation",
         "On {base}, buy one Kestrel Wireless Earbuds in the colour White. Use the discount code SAVE10 and choose "
         f"Express shipping. Use my full name and email, the address {ADDRESS}, and pay with the test {CARD}.",
         order_oracle(1001, "White", 1, "express", "SAVE10"),
         "variant, coupon, 3-step checkout, form validation"),
    Task("nw_wishlist_pets", "automation",
         "Log in to {base} with the email ada.tester@example.com and the password Shop!2026. Then add the three "
         "cheapest in-stock products of the Pet Supplies category to the wishlist.",
         wishlist_oracle(_cheapest_pets, "ada.tester@example.com"),
         "login, sorting, wishlist (answer changes with new data)"),
    Task("nw_cart_setup", "automation",
         "On {base}, put 2 Voltix Power Bank 20000mAh in the colour Black and 1 copy of the book The Quiet Algorithm "
         "in the cart, and apply the code FREESHIP. Do not place the order.",
         cart_oracle({1005: (2, "Black"), 1055: (1, None)}, "FREESHIP"),
         "variant, quantity, coupon, stop before ordering"),
]
BY_NAME = {t.name: t for t in TASKS}
