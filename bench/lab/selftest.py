"""
Self-test of the benchmark lab (no LLM, no browser): drift invariants on every page type at every
level and two seeds, every form flow (apply, save, cart, CRM login, notes, 3-step deal wizard,
"Load more" fragment), the ground truth of every task, and the oracles. Prints "LAB OK".

    python -m bench.lab.selftest
"""

from __future__ import annotations

import http.cookiejar
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

from . import sites
from .server import LabServer
from .tasks import BY_NAME, TASKS, USER_INFO

PUBLIC = ["/shop/", "/shop/c/baby", "/shop/c/baby?page=2", "/shop/c/books?page=2", "/shop/p/101",
          "/shop/search?q=mini", "/papers/", "/papers/search?q=web+agent+caching", "/papers/p/2",
          "/jobs/", "/jobs/?q=python", "/jobs/?loc=Remote", "/jobs/j/203", "/jobs/apply/203", "/crm/login"]
PRIVATE = ["/crm/", "/crm/contacts", "/crm/contacts?status=Customer", "/crm/contacts?sort=value",
           f"/crm/contacts/{sites.CONTACTS[0].id}", "/crm/deals/new"]


class Client:
    def __init__(self, srv: LabServer):
        self.srv = srv
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path: str, data: dict | None = None) -> str:
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        with self.opener.open(self.srv.base + path, data=body) as r:
            return r.read().decode("utf-8")

    def login(self) -> str:
        return self.get("/crm/login", {"username": sites.CRM_USER, "password": sites.CRM_PASS})


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    return " ".join(soup.get_text(" ").split())


def links(html: str) -> set[str]:
    return {a["href"] for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)}


def forms(html: str) -> list[tuple]:
    out = []
    for f in BeautifulSoup(html, "html.parser").find_all("form"):
        names = sorted(i.get("name") for i in f.find_all(["input", "textarea", "select"]) if i.get("name"))
        out.append((f.get("action"), (f.get("method") or "get").lower(), tuple(names)))
    return sorted(out)


def data_strings(path: str) -> list[str]:
    """Text that must survive every drift level on this page (the data a task needs)."""
    if path.startswith("/shop/c/"):
        cat = path.split("/")[3].split("?")[0]
        n = int(path.split("page=")[1]) if "page=" in path else 1
        items = [p for p in sites.PRODUCTS if p.category == cat][(n - 1) * sites.PER_PAGE:n * sites.PER_PAGE]
        return [p.name for p in items] + [f"${p.price:.2f}" for p in items] + [f"{p.rating} stars" for p in items]
    if path.startswith("/shop/p/"):
        p = next(x for x in sites.PRODUCTS if str(x.id) == path.rsplit("/", 1)[1])
        return [p.name, f"${p.price:.2f}"]
    if path.startswith("/papers/search"):
        return [p.title for p in sites.search_papers("web agent caching")]
    if path.startswith("/papers/p/"):
        p = next(x for x in sites.PAPERS if str(x.id) == path.rsplit("/", 1)[1])
        return [p.title, p.finding]
    if path.startswith("/jobs/?q="):
        return [j.title for j in sites.search_jobs("python")]
    if path.startswith("/jobs/?loc="):
        return [j.title for j in sites.search_jobs("", "Remote")]
    if path.startswith("/jobs/j/"):
        return [next(j.title for j in sites.JOBS if str(j.id) == path.rsplit("/", 1)[1])]
    if path.startswith("/crm/contacts?status="):
        return [c.name for c in sites.crm_contacts("Customer")[:sites.CRM_PAGE]]
    if path == "/crm/contacts":
        return [c.name for c in sites.crm_contacts()[:sites.CRM_PAGE]]
    return []


def check_drift(srv: LabServer, fails: list) -> None:
    for seed in (1, 2):
        for path in PUBLIC + PRIVATE:
            c = Client(srv)
            srv.set(0, seed)
            if path in PRIVATE:
                c.login()
            base = c.get(path)
            for level in range(1, 5):
                srv.set(level, seed)
                a, b = c.get(path), c.get(path)
                tag = f"{path} L{level} s{seed}"
                if a != b:
                    fails.append(f"{tag}: not deterministic")
                if a == base:
                    fails.append(f"{tag}: page did not change")
                text = visible_text(a)
                for s in data_strings(path):
                    if s not in text:
                        fails.append(f"{tag}: data lost: {s!r}")
                missing = links(base) - links(a)
                if missing:
                    fails.append(f"{tag}: links lost: {sorted(missing)[:3]}")
                if forms(a) != forms(base):
                    fails.append(f"{tag}: forms changed: {forms(base)} -> {forms(a)}")
        srv.set(1, seed)
        if "product-card" in Client(srv).get("/shop/c/baby"):
            fails.append("L1 kept original class names")
        srv.set(3, seed)
        if ">Search<" in Client(srv).get("/shop/"):
            fails.append("L3 kept button wording")
        srv.set(4, seed)
        form = Client(srv).get("/jobs/apply/203").split("<form", 1)[1].split("</form>", 1)[0]
        if "<button" in form:
            fails.append("L4 kept the submit <button>")


def check_flows(srv: LabServer, fails: list) -> None:
    for level in (0, 4):
        srv.set(level, 1)
        srv.reset()
        c = Client(srv)
        # jobs: apply + save
        done = c.get("/jobs/apply/203", {"full_name": USER_INFO["full_name"], "email": USER_INFO["email"], "cover": ""})
        c.get("/jobs/save/209")
        if "Application sent" not in done or len(srv.state.applications) != 1 or srv.state.saved != [209]:
            fails.append(f"L{level}: jobs apply/save not recorded")
        # shop cart
        c.get("/shop/cart/add/101", {})
        if srv.state.cart != [101]:
            fails.append(f"L{level}: cart add not recorded")
        # crm: protected, login, popup, fragment, note, wizard
        if "Sign in" not in c.get("/crm/contacts") and "Log in" not in c.get("/crm/contacts"):
            fails.append(f"L{level}: CRM not protected")
        dash = c.login()
        if "newsletter" not in dash.lower():
            fails.append(f"L{level}: popup missing on the dashboard")
        page = c.get("/crm/contacts")
        frag = c.get(f"/crm/contacts/more?offset={sites.CRM_PAGE}")
        want = [x.name for x in sites.crm_contacts()[sites.CRM_PAGE:2 * sites.CRM_PAGE]]
        if not all(n in frag for n in want):
            fails.append(f"L{level}: load-more fragment rows wrong")
        if level:
            row_cls = lambda h: (BeautifulSoup(h, "html.parser").find("tr", class_=True) or {}).get("class")  # noqa: E731
            if row_cls(frag) != row_cls(page.split("<tbody>", 1)[1]):
                fails.append("L4: fragment rows not drifted like the page rows")
        cid = sites.CONTACTS[2].id
        c.get(f"/crm/contacts/{cid}/note", {"note": "Follow up in January"})
        if srv.state.notes != [{"contact_id": cid, "note": "Follow up in January"}]:
            fails.append(f"L{level}: note not recorded")
        d = BY_NAME["crm_add_deal"]
        dc = sites.CONTACTS[4]
        s1 = c.get("/crm/deals/new", {"step": "1", "contact_id": str(dc.id), "title": "Annual license"})
        s2 = c.get("/crm/deals/new", {"step": "2", "contact_id": str(dc.id), "title": "Annual license",
                                      "amount": "12000", "stage": "Proposal", "priority": "yes",
                                      "close_date": "2026-12-15"})
        hidden = {i["name"]: i.get("value", "") for i in BeautifulSoup(s2, "html.parser").find_all("input", type="hidden")}
        c.get("/crm/deals/new", {**hidden, "step": "3"})
        if "step 2 of 3" not in s1 or not d.oracle(None, srv.state)["success"]:
            fails.append(f"L{level}: deal wizard: {srv.state.deals} -> {d.oracle(None, srv.state)}")
        srv.reset()
        if "Sign in" not in c.get("/crm/") and "Log in" not in c.get("/crm/"):
            fails.append(f"L{level}: CRM session survived a reset")


def check_tasks(fails: list) -> None:
    if len(TASKS) < 20 or len({t.name for t in TASKS}) != len(TASKS):
        fails.append(f"task list: {len(TASKS)} tasks / duplicate names")
    by_type = {t: sum(1 for x in TASKS if x.type == t) for t in ("scraping", "analysis", "automation")}
    if min(by_type.values()) < 6:
        fails.append(f"too few tasks of a type: {by_type}")
    # every filter must select some, but not all, records (otherwise the task tests nothing)
    checks = {"baby<30": [p for p in sites.PRODUCTS if p.category == "baby" and p.price < 30],
              "baby<15": [p for p in sites.PRODUCTS if p.category == "baby" and p.price < 15],
              "toys<20": [p for p in sites.PRODUCTS if p.category == "toys" and p.price < 20],
              "toys5": [p for p in sites.PRODUCTS if p.category == "toys" and p.rating == 5],
              "books4": [p for p in sites.PRODUCTS if p.category == "books" and p.rating >= 4],
              "mini": [p for p in sites.PRODUCTS if "mini" in p.name.lower()],
              "customers": sites.crm_contacts("Customer"), "lost": sites.crm_contacts("Lost"),
              "big": [c for c in sites.CONTACTS if c.value >= 5000],
              "remote": sites.search_jobs("", "Remote"), "dhaka": sites.search_jobs("", "Dhaka"),
              "python": sites.search_jobs("python"), "tokens": sites.search_papers("token reduction")}
    for name, rows in checks.items():
        if not rows:
            fails.append(f"ground truth empty: {name}")
    if len(checks["customers"]) <= sites.CRM_PAGE and len(checks["lost"]) <= sites.CRM_PAGE:
        fails.append("no CRM filter needs 'Load more' (all fit on the first page)")


def check_oracles(srv: LabServer, fails: list) -> None:
    srv.reset()
    o = BY_NAME["jobs_python"].oracle
    with srv.state.lock:
        srv.state.applications.append({"job_id": 203, "full_name": USER_INFO["full_name"],
                                       "email": USER_INFO["email"], "cover": ""})
    if o(None, srv.state)["recall"] >= 1:
        fails.append("apply oracle: one application counted as complete")
    with srv.state.lock:
        for j in sites.search_jobs("python"):
            if j.id != 203:
                srv.state.applications.append({"job_id": j.id, "full_name": USER_INFO["full_name"],
                                               "email": USER_INFO["email"], "cover": ""})
    if not o(None, srv.state)["success"]:
        fails.append(f"apply oracle rejects a complete run: {o(None, srv.state)}")
    with srv.state.lock:
        srv.state.applications.append({"job_id": 206, "full_name": "x", "email": "y", "cover": ""})
    if o(None, srv.state)["success"]:
        fails.append("apply oracle: a wrong application still counted as success")
    with tempfile.TemporaryDirectory() as td:
        truth = [p for p in sites.PRODUCTS if p.category == "baby" and p.price < 30]
        good, bad = Path(td, "good.csv"), Path(td, "bad.csv")
        good.write_text("name,price,url\n" + "".join(f"{p.name},${p.price},/shop/p/{p.id}\n" for p in truth),
                        encoding="utf-8")
        bad.write_text("name,price\n" + "".join(f"{p.name},{p.price}\n" for p in sites.PRODUCTS[:20]),
                       encoding="utf-8")
        so = BY_NAME["shop_baby_under_30"].oracle
        if not so(good, srv.state)["success"] or so(bad, srv.state)["success"]:
            fails.append(f"scrape oracle wrong: {so(good, srv.state)} / {so(bad, srv.state)}")
        rep = Path(td, "r.md")
        exp = sites.search_papers("web agent caching")[:3]
        rep.write_text("\n".join(f"- {p.title}: {p.finding}" for p in exp), encoding="utf-8")
        ao = BY_NAME["papers_caching"].oracle
        if not ao(rep, srv.state)["success"]:
            fails.append(f"analysis oracle rejects a correct report: {ao(rep, srv.state)}")
        rep.write_text("\n".join(f"- {p.finding}" for p in sites.PAPERS), encoding="utf-8")
        if ao(rep, srv.state)["precision"] > 0.5:
            fails.append("analysis oracle: listing every paper keeps high precision")
        # the same facts in other words must still count ("47%", "threefold", "halved")
        rep.write_text("Plans cut cost by 47%.\nRepair recovered 83 per cent.\nTokens fell to 9,000.", encoding="utf-8")
        if not ao(rep, srv.state)["success"]:
            fails.append(f"analysis oracle rejects paraphrased numbers: {ao(rep, srv.state)}")
        lo = BY_NAME["papers_localization"].oracle
        rep.write_text("Breaks within three months; 88% re-found; failures halved.", encoding="utf-8")
        if not lo(rep, srv.state)["success"]:
            fails.append(f"analysis oracle rejects 'three months' / 'halved': {lo(rep, srv.state)}")
        # a row with the right name but a wrong price is an error, not a hit
        wrong = Path(td, "wrong.csv")
        wrong.write_text("name,price\n" + "".join(f"{p.name},${p.price + 1:.2f}\n" for p in truth), encoding="utf-8")
        if so(wrong, srv.state)["recall"] > 0:
            fails.append("scrape oracle accepts wrong prices")
        crm = Path(td, "crm.csv")
        cust = [c for c in sites.CONTACTS if c.status == "Customer"]
        crm.write_text("name,company,value\n" + "".join(f"{c.name},{c.company},\"${c.value:,}\"\n" for c in cust),
                       encoding="utf-8")
        if not BY_NAME["crm_customers"].oracle(crm, srv.state)["success"]:
            fails.append(f"crm scrape oracle rejects '$1,200' values: {BY_NAME['crm_customers'].oracle(crm, srv.state)}")
        lost = [c for c in sites.CONTACTS if c.status == "Lost"]
        rep.write_text("\n".join(f"- {c.name} ({c.company})" for c in lost), encoding="utf-8")
        if not BY_NAME["crm_lost_report"].oracle(rep, srv.state)["success"]:
            fails.append("crm report oracle rejects a correct report")


def main() -> None:
    srv = LabServer(port=8791)
    fails: list = []
    try:
        check_tasks(fails)
        check_drift(srv, fails)
        check_flows(srv, fails)
        check_oracles(srv, fails)
    finally:
        srv.close()
    if fails:
        print("\n".join(fails[:40]))
        print(f"LAB FAILED ({len(fails)} problems)")
        sys.exit(1)
    by_type = {t: sum(1 for x in TASKS if x.type == t) for t in ("scraping", "analysis", "automation")}
    print(f"{len(TASKS)} tasks {by_type}")
    print("LAB OK")


if __name__ == "__main__":
    main()
