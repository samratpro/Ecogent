"""
Benchmark tasks on the lab sites (24: 8 scraping, 7 analysis, 9 automation), each with an oracle that
scores the result against ground truth computed from the site data (never typed by hand).

An oracle returns {"success": bool, "precision": float, "recall": float, "detail": str}.
  scraping    rows in the output file vs the true record set (a row counts when one of its cells is
              an expected name)
  analysis    the report must contain each expected key phrase; naming other candidates lowers
              precision (wrong sources / hallucinated picks)
  automation  what the site recorded (applications, saves, cart, notes, deals) vs what should have
              been done; duplicates and wrong targets lower precision

Prompts contain {base}; the runner fills in the lab server address. Features covered: pagination,
search forms, dropdown filters, login, a click-blocking popup, a data table, JavaScript "Load more",
per-item forms, a 3-step wizard (dropdown, checkbox, date).
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import sites

USER_INFO = {"full_name": "Ada Tester", "email": "ada.tester@example.com", "name": "Ada Tester",
             "first_name": "Ada", "last_name": "Tester", "phone": "+10000000000"}
LOGIN = f"Log in to {{base}}/crm/login with username {sites.CRM_USER} and password {sites.CRM_PASS}, then"


@dataclass
class Task:
    name: str
    type: str                                   # analysis | scraping | automation
    prompt: str
    oracle: Callable[[Optional[Path], sites.LabState], dict]
    features: str = ""                          # page features the task exercises (for the paper's table)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _result(p: float, r: float, need: float, detail: str) -> dict:
    return {"success": p >= need and r >= need, "precision": round(p, 3), "recall": round(r, 3), "detail": detail}


# ----------------------------------------------------------------------------- output readers
def read_rows(path: Optional[Path]) -> list[list[str]]:
    if not path or not Path(path).exists():
        return []
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as f:
            return [r for r in csv.reader(f)][1:]
    if p.suffix.lower() == ".xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(p, read_only=True).active
        return [["" if c is None else str(c) for c in row] for row in list(ws.iter_rows(values_only=True))[1:]]
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        data = data.get("records", data) if isinstance(data, dict) else data
        return [[str(v) for v in (r.values() if isinstance(r, dict) else r)] for r in data if r]
    return []


def read_text(path: Optional[Path]) -> str:
    if not path or not Path(path).exists():
        return ""
    p = Path(path)
    if p.suffix.lower() == ".docx":
        import docx
        return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    if p.suffix.lower() in (".xlsx", ".csv", ".json"):
        return "\n".join(" ".join(r) for r in read_rows(p))
    return p.read_text(encoding="utf-8", errors="replace")


# ----------------------------------------------------------------------------- oracles
def _numbers(cells: list[str]) -> list[float]:
    out = []
    for c in cells:
        for m in re.findall(r"-?\d[\d,]*(?:\.\d+)?", str(c)):
            try:
                out.append(float(m.replace(",", "")))
            except ValueError:
                pass
    return out


def scrape_oracle(truth: dict[str, list[float]]) -> Callable:
    """truth: record name -> numbers its row must also contain (price, deal value). A row is correct
    only with the right name AND the right numbers, so a wrong price is an error, not a hit."""
    want = {_norm(k): v for k, v in truth.items()}

    def oracle(output: Optional[Path], state: sites.LabState) -> dict:
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
        p, rc = good / len(rows), len(found) / len(want)
        return _result(p, rc, 0.9, f"{len(rows)} rows, {len(found)}/{len(want)} expected found with correct values")
    return oracle


def products(rows: list[sites.Product]) -> dict[str, list[float]]:
    return {p.name: [p.price] for p in rows}


def contacts(rows: list[sites.Contact], with_value: bool = True) -> dict[str, list[float]]:
    return {c.name: [float(c.value)] if with_value else [] for c in rows}


def text_oracle(expected: list[str], universe: list[str], need: float = 0.66) -> Callable:
    """expected / universe are regex patterns (use re.escape for literal names)."""
    exp = list(dict.fromkeys(expected))
    uni = list(dict.fromkeys([*universe, *exp]))

    def oracle(output: Optional[Path], state: sites.LabState) -> dict:
        text = read_text(output).lower()
        if not text.strip():
            return _result(0, 0, need, "no report")
        found = [k for k in exp if re.search(k, text)]
        mentioned = [k for k in uni if re.search(k, text)]
        p = len(set(found)) / len(mentioned) if mentioned else 0.0
        r = len(found) / len(exp)
        return _result(p, r, need, f"{len(found)}/{len(exp)} expected, {len(mentioned)} candidates mentioned")
    return oracle


# A report may write a fact in other words: "47%", "47 per cent", "threefold", "halved".
_KEY_ALIASES = {
    "9k": r"\b9\s*k\b|\b9,000\b|\b9000\b",
    "90 days": r"\b90\s*days\b|three months",
    "factor of 3": r"factor of (3|three)|\b3\s*x\b|\bthree-?fold\b|\b3-?fold\b|\b(three|3) times\b",
    "by half": r"by half|\bhalved\b|\bin half\b|\b50\s*(%|percent|per cent)",
}


def key_pattern(key: str) -> str:
    m = re.fullmatch(r"(\d+) percent", key)
    if m:
        return rf"\b{m.group(1)}\s*(%|percent|per cent)"
    return _KEY_ALIASES.get(key, re.escape(key.lower()))


def papers_oracle(papers: list[sites.Paper]) -> Callable:
    return text_oracle([key_pattern(p.key) for p in papers], [key_pattern(p.key) for p in sites.PAPERS])


def names_oracle(expected: list[str], universe: list[str], need: float = 0.66) -> Callable:
    return text_oracle([re.escape(n.lower()) for n in expected], [re.escape(n.lower()) for n in universe], need)


def records_oracle(get: Callable[[sites.LabState], list], key: Callable[[object], object], want: set,
                   ok: Callable[[object], bool] = lambda r: True, what: str = "records") -> Callable:
    """Generic oracle over what the site recorded: unique correct targets vs everything recorded."""
    def oracle(output: Optional[Path], state: sites.LabState) -> dict:
        with state.lock:
            recs = list(get(state))
        if not recs:
            return _result(0, 0, 1.0, f"no {what}")
        good = {key(r) for r in recs if key(r) in want and ok(r)}
        p, r = len(good) / len(recs), len(good) / len(want)
        return _result(p, r, 1.0, f"{len(recs)} {what}, {len(good)}/{len(want)} correct")
    return oracle


def apply_oracle(job_ids: set, cover: str = "") -> Callable:
    return records_oracle(lambda s: s.applications, lambda a: a["job_id"], job_ids,
                          lambda a: _norm(a["full_name"]) == _norm(USER_INFO["full_name"])
                          and _norm(a["email"]) == _norm(USER_INFO["email"])
                          and (not cover or _norm(cover) in _norm(a["cover"])), "applications")


def deal_oracle(contact_id: int, title: str, amount: int, stage: str, priority: bool, close_date: str) -> Callable:
    def match(d: dict) -> bool:
        amt = re.sub(r"[^\d.]", "", d.get("amount", ""))
        return (d.get("contact_id") == str(contact_id) and _norm(d.get("title")) == _norm(title)
                and amt and float(amt) == float(amount) and d.get("stage") == stage
                and bool(d.get("priority")) == priority and d.get("close_date") == close_date)
    return records_oracle(lambda s: s.deals, lambda d: "deal", {"deal"}, match, "deals")


# ----------------------------------------------------------------------------- ground truth helpers
def _prod(cat: str, cond: Callable[[sites.Product], bool]) -> list[sites.Product]:
    return [p for p in sites.PRODUCTS if p.category == cat and cond(p)]


def _contacts(cond: Callable[[sites.Contact], bool]) -> list[sites.Contact]:
    return [c for c in sites.CONTACTS if cond(c)]


_BABY = _prod("baby", lambda p: True)
_DEAL1, _DEAL2 = sites.CONTACTS[4], sites.CONTACTS[11]

TASKS = [
    # ---------------------------------------------------------------- scraping
    Task("shop_baby_under_30", "scraping",
         "Go to {base}/shop/ , open the Baby category and collect the name, price and product URL of every "
         "product under $30 on all pages of that category. Save the result as a CSV file.",
         scrape_oracle(products(_prod("baby", lambda p: p.price < 30))), "pagination, filter"),
    Task("shop_books_rated", "scraping",
         "From {base}/shop/c/books collect the title, price and rating of every book rated 4 stars or more, "
         "across all pages, and save it as a CSV file.",
         scrape_oracle(products(_prod("books", lambda p: p.rating >= 4))), "pagination, filter"),
    Task("shop_toys_under_20", "scraping",
         "Scrape the name and price of every toy under $20 from the Toys category of {base}/shop/ (all pages) "
         "into a CSV file.",
         scrape_oracle(products(_prod("toys", lambda p: p.price < 20))), "pagination, filter"),
    Task("shop_books_all", "scraping",
         "Collect the title and price of all books in {base}/shop/c/books (every page) and save them as CSV.",
         scrape_oracle(products(_prod("books", lambda p: True))), "pagination"),
    Task("shop_search_mini", "scraping",
         'On {base}/shop/ search for "mini" and save the name and price of every product in the results as CSV.',
         scrape_oracle(products([p for p in sites.PRODUCTS if "mini" in p.name.lower()])), "search form"),
    Task("crm_customers", "scraping",
         f"{LOGIN} open Contacts, filter the list to status Customer and save the name, company and deal value "
         "of every customer as a CSV file (make sure you get all of them, not only the first rows).",
         scrape_oracle(contacts(_contacts(lambda c: c.status == "Customer"))),
         "login, popup, dropdown filter, table, load more"),
    Task("crm_all_contacts", "scraping",
         f"{LOGIN} export every contact in the Contacts table (name, company, status, deal value) to a CSV file. "
         "The table loads more rows with a button.",
         scrape_oracle(contacts(sites.CONTACTS)), "login, popup, table, load more"),
    Task("crm_big_deals", "scraping",
         f"{LOGIN} collect the name and deal value of every contact whose deal value is at least $5,000 "
         "and save it as CSV.",
         scrape_oracle(contacts(_contacts(lambda c: c.value >= 5000))), "login, popup, table, load more"),
    # ---------------------------------------------------------------- analysis
    Task("papers_caching", "analysis",
         'Go to {base}/papers/ , search for "web agent caching", open the top 3 results and write a markdown '
         "report with each paper's title and its main result.",
         papers_oracle(sites.search_papers("web agent caching")[:3]), "search form, result links"),
    Task("papers_localization", "analysis",
         'Go to {base}/papers/ , search for "element localization", read the top 3 papers and write a short '
         "markdown summary of what each one found.",
         papers_oracle(sites.search_papers("element localization")[:3]), "search form, result links"),
    Task("papers_caching_top5", "analysis",
         'Search {base}/papers/ for "web agent caching", read the first 5 results and write a markdown table '
         "with title, year and main result for each.",
         papers_oracle(sites.search_papers("web agent caching")[:5]), "search form, result links"),
    Task("papers_tokens", "analysis",
         'On {base}/papers/ search for "token reduction", read the top 2 results and summarize their main '
         "results in a markdown file.",
         papers_oracle(sites.search_papers("token reduction")[:2]), "search form, result links"),
    Task("papers_compare", "analysis",
         'On {base}/papers/ find the papers "Selector Drift in the Wild" and "Robust Locators for Test '
         'Automation" and write a markdown comparison of their main results.',
         papers_oracle([sites.PAPERS[3], sites.PAPERS[8]]), "search form, two lookups"),
    Task("shop_baby_price_report", "analysis",
         "Look through every page of the Baby category on {base}/shop/ and write a markdown note naming the "
         "cheapest and the most expensive product with their prices.",
         names_oracle([min(_BABY, key=lambda p: p.price).name, max(_BABY, key=lambda p: p.price).name],
                     [p.name for p in _BABY]), "pagination, comparison"),
    Task("crm_lost_report", "analysis",
         f"{LOGIN} write a markdown report listing every contact whose status is Lost, with their company.",
         names_oracle([c.name for c in _contacts(lambda c: c.status == "Lost")], [c.name for c in sites.CONTACTS],
                     need=0.9), "login, popup, dropdown filter, load more"),
    # ---------------------------------------------------------------- automation
    Task("jobs_python", "automation",
         'Go to {base}/jobs/ , search for "python" and apply to every job in the results using my full name and '
         "email (leave the cover letter empty).",
         apply_oracle({j.id for j in sites.search_jobs("python")}), "search form, per-item form"),
    Task("jobs_remote", "automation",
         "On {base}/jobs/ choose the location Remote in the location filter, search, and apply to every job "
         "listed using my full name and email.",
         apply_oracle({j.id for j in sites.search_jobs("", "Remote")}), "dropdown filter, per-item form"),
    Task("jobs_save_dhaka", "automation",
         "On {base}/jobs/ save every job located in Dhaka (use the Save link of each job). Do not apply.",
         records_oracle(lambda s: s.saved, lambda j: j, {j.id for j in sites.search_jobs("", "Dhaka")},
                        what="saves"), "dropdown filter or reading, links"),
    Task("jobs_frontend_cover", "automation",
         'Apply to the "Frontend Engineer" job on {base}/jobs/ with my full name and email and this cover '
         'letter: "I enjoy building fast React interfaces."',
         apply_oracle({202}, cover="I enjoy building fast React interfaces."), "search, textarea"),
    Task("shop_cart_baby_under_15", "automation",
         "On {base}/shop/ add every Baby product that costs less than $15 to the cart (check all pages of the "
         "category).",
         records_oracle(lambda s: s.cart, lambda p: p, {p.id for p in _prod("baby", lambda p: p.price < 15)},
                        what="cart additions"), "pagination, per-item form"),
    Task("shop_cart_toys_rated5", "automation",
         "Add every toy rated 5 stars on {base}/shop/c/toys (all pages) to the cart.",
         records_oracle(lambda s: s.cart, lambda p: p, {p.id for p in _prod("toys", lambda p: p.rating == 5)},
                        what="cart additions"), "pagination, per-item form"),
    Task("crm_add_deal", "automation",
         f"{LOGIN} create a new deal for the contact {_DEAL1.name} titled \"Annual license\" with amount 12000, "
         "stage Proposal, marked high priority, expected close date 2026-12-15.",
         deal_oracle(_DEAL1.id, "Annual license", 12000, "Proposal", True, "2026-12-15"),
         "login, popup, 3-step wizard, dropdown, checkbox, date"),
    Task("crm_add_deal_normal", "automation",
         f"{LOGIN} create a deal for {_DEAL2.name} named \"Support renewal\": amount 4500, stage Negotiation, "
         "normal priority (not high), expected close date 2027-01-31.",
         deal_oracle(_DEAL2.id, "Support renewal", 4500, "Negotiation", False, "2027-01-31"),
         "login, popup, 3-step wizard, dropdown, date"),
    Task("crm_notes_lost", "automation",
         f"{LOGIN} add the note \"Follow up in January\" to every contact whose status is Lost.",
         records_oracle(lambda s: s.notes, lambda n: n["contact_id"],
                        {c.id for c in _contacts(lambda c: c.status == "Lost")},
                        lambda n: "follow up in january" in _norm(n["note"]), "notes"),
         "login, popup, dropdown filter, load more, per-item form"),
]
BY_NAME = {t.name: t for t in TASKS}
