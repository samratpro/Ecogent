"""
Four local benchmark sites rendered from fixed data (ground truth is known exactly):

  /shop/    catalog: categories, 6 products per page with pagination, product pages, search,
            an add-to-cart form (posts recorded in LabState.cart)
  /papers/  paper search: query form, result list with "Cited by" / "Related" noise links, paper pages
  /jobs/    job board: keyword + location filter, job pages, save links and an application form
            (applications / saves recorded)
  /crm/     login-protected CRM: newsletter popup that blocks clicks, contacts TABLE with status filter
            and sort dropdowns and a JavaScript "Load more" button, contact pages with a note form,
            and a 3-step deal wizard (dropdown, checkbox, date) - notes and deals recorded

Pages carry the clutter real sites have (menu, footer, cookie banner, sidebar). Every response is
server-rendered HTML that drift.py changes per drift level. route() returns (status, html, headers).
"""

from __future__ import annotations

import html
import random
import secrets
import threading
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

# ----------------------------------------------------------------------------- data
_rng = random.Random(20261108)          # fixed: the same data on every machine

CATEGORIES = {"baby": "Baby", "toys": "Toys", "books": "Books"}
_NOUNS = {
    "baby": ["Soft Blanket", "Feeding Bottle", "Teether Ring", "Baby Monitor", "Bath Tub", "Stroller Fan",
             "Bib Set", "Night Light", "Rattle", "Crib Mobile", "Diaper Bag", "Sleep Sack", "Bottle Warmer",
             "Play Mat", "Booties", "Pacifier Clip"],
    "toys": ["Robot Kit", "Wooden Blocks", "Puzzle Box", "Toy Train", "Kite", "Water Gun", "Doll House",
             "Race Car", "Yo-Yo", "Marble Run", "Plush Bear", "Drone Mini"],
    "books": ["Python Basics", "Web Scraping Guide", "Data Science Notes", "Algorithms Explained",
              "Clean Code Stories", "Networks 101", "Deep Learning Primer", "SQL Cookbook",
              "History of Computing", "Design Patterns Lite", "Linux Handbook", "Testing in Practice"],
}
_ADJ = ["Classic", "Deluxe", "Eco", "Mini", "Pro", "Smart", "Happy", "Cozy"]


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    category: str
    price: float
    rating: int


def _products() -> list[Product]:
    out, pid = [], 100
    for cat, nouns in _NOUNS.items():
        for i, noun in enumerate(nouns):
            pid += 1
            out.append(Product(pid, f"{_ADJ[(i + pid) % len(_ADJ)]} {noun}", cat,
                               round(_rng.uniform(5, 60), 2), 1 + (pid * 7 + i) % 5))
    return out


PRODUCTS = _products()
PER_PAGE = 6


@dataclass(frozen=True)
class Paper:
    id: int
    title: str
    authors: str
    year: int
    topic: str
    finding: str            # the fact an analysis must report (oracle checks its key phrase)
    key: str                # short phrase from the finding the oracle looks for


PAPERS = [
    Paper(1, "Caching Plans for Web Agents", "L. Chen, M. Rossi", 2025, "web agent caching",
          "Reusing cached plans cut LLM cost by 47 percent on repeated web tasks.", "47 percent"),
    Paper(2, "Replay Is Not Enough: Repairing Web Automations", "A. Okafor, J. Kim", 2026, "web agent caching",
          "Automatic repair recovered 83 percent of workflows broken by site updates.", "83 percent"),
    Paper(3, "Cost-Aware Browser Agents", "P. Novak", 2025, "web agent caching",
          "Graded fallback lowered tokens per task from 41k to 9k.", "9k"),
    Paper(4, "Selector Drift in the Wild", "R. Silva, T. Brown", 2024, "element localization",
          "A third of CSS selectors broke within 90 days on popular sites.", "90 days"),
    Paper(5, "Similarity-Based Element Re-Finding", "K. Ito", 2023, "element localization",
          "Multi-attribute scoring located 88 percent of moved elements.", "88 percent"),
    Paper(6, "Vision Grounding for GUI Agents", "S. Gupta", 2025, "vision agents",
          "Screenshot grounding reached 71 percent click accuracy.", "71 percent"),
    Paper(7, "Prompt Compression for Agents", "D. Weber", 2024, "token reduction prompt compression",
          "Compression kept accuracy while removing 60 percent of prompt tokens.", "60 percent"),
    Paper(8, "Web Agents Need Memory", "F. Haddad, E. Moore", 2025, "web agent caching",
          "Episodic memory reduced repeated exploration steps by a factor of 3.", "factor of 3"),
    Paper(9, "Robust Locators for Test Automation", "N. Park", 2024, "element localization",
          "Fallback locators cut flaky test failures by half.", "by half"),
    Paper(10, "Benchmarking Browser Agents Under Change", "C. Diaz", 2026, "web agent caching",
           "Success fell from 92 to 54 percent after scripted layout changes.", "54 percent"),
    Paper(11, "Token Budgets for Tool-Using Agents", "M. Lund", 2025, "token reduction",
           "A per-task token budget avoided 95 percent of runaway loops.", "95 percent"),
    Paper(12, "Trajectory Pruning Saves Tokens", "Y. Zhao", 2025, "token reduction prompt compression",
           "Pruning stale observations saved 38 percent of input tokens.", "38 percent"),
]


def search_papers(q: str) -> list[Paper]:
    words = [w for w in q.lower().split() if len(w) > 2]
    scored = []
    for p in PAPERS:
        hay = f"{p.title} {p.topic} {p.finding}".lower()
        s = sum(hay.count(w) for w in words)
        if s:
            scored.append((-s, p.id, p))
    return [p for _, _, p in sorted(scored)]


@dataclass(frozen=True)
class Job:
    id: int
    title: str
    company: str
    location: str
    tags: str


JOBS = [
    Job(201, "Python Developer", "DataNest", "Remote", "python django"),
    Job(202, "Frontend Engineer", "Pixelry", "Berlin", "react typescript"),
    Job(203, "Senior Python Engineer", "CloudOwl", "Dhaka", "python aws"),
    Job(204, "QA Tester", "Bugless", "Remote", "testing selenium"),
    Job(205, "Backend Developer (Python)", "Quantly", "London", "python fastapi"),
    Job(206, "Data Analyst", "Insightful", "Remote", "sql excel"),
    Job(207, "DevOps Engineer", "Shipit", "Toronto", "kubernetes"),
    Job(208, "Python Automation Engineer", "Botworks", "Remote", "python playwright"),
    Job(209, "Mobile Developer", "Appify", "Dhaka", "flutter"),
    Job(210, "Machine Learning Engineer", "NeuralCo", "Remote", "pytorch"),
    Job(211, "Support Engineer", "Helpdesk.io", "Dhaka", "linux customer"),
]
LOCATIONS = ["Remote", "Dhaka", "Berlin", "London", "Toronto"]


def search_jobs(q: str = "", loc: str = "") -> list[Job]:
    q = q.lower().strip()
    return [j for j in JOBS if (not q or q in f"{j.title} {j.tags}".lower()) and (not loc or j.location == loc)]


@dataclass(frozen=True)
class Contact:
    id: int
    name: str
    company: str
    status: str             # Lead | Customer | Lost
    value: int              # deal value, USD


def _contacts() -> list[Contact]:
    first = ["Amina", "Ben", "Chen", "Dara", "Elif", "Farid", "Grace", "Hugo", "Ines", "Jamal", "Kofi", "Lena",
             "Mateo", "Nadia", "Omar"]
    last = ["Rahman", "Smith", "Wang", "Lopez", "Yilmaz", "Haque", "Kim", "Novak", "Silva", "Okoro"]
    companies = ["Acme", "Globex", "Initech", "Umbrella", "Hooli", "Vandelay", "Stark", "Wayne"]
    out, seen = [], set()
    rng = random.Random(77)
    while len(out) < 30:
        name = f"{rng.choice(first)} {rng.choice(last)}"
        if name in seen:
            continue
        seen.add(name)
        out.append(Contact(300 + len(out) + 1, name, rng.choice(companies),
                           ["Lead", "Customer", "Lost"][rng.randrange(3)], rng.randrange(5, 120) * 100))
    return out


CONTACTS = _contacts()
CRM_PAGE = 8                # rows before "Load more": Customer (10) needs it, Lost (7) does not
CRM_USER, CRM_PASS = "demo", "demo123"
STAGES = ["Qualification", "Proposal", "Negotiation", "Won"]


def crm_contacts(status: str = "", sort: str = "name") -> list[Contact]:
    rows = [c for c in CONTACTS if not status or c.status == status]
    return sorted(rows, key=(lambda c: -c.value) if sort == "value" else (lambda c: c.name))


# ----------------------------------------------------------------------------- state
@dataclass
class LabState:
    level: int = 0
    seed: int = 1
    applications: list = field(default_factory=list)      # job_id, full_name, email, cover
    saved: list = field(default_factory=list)             # job ids saved
    cart: list = field(default_factory=list)              # product ids added
    notes: list = field(default_factory=list)             # contact_id, note
    deals: list = field(default_factory=list)             # contact_id, title, amount, stage, priority, close_date
    sessions: set = field(default_factory=set)            # CRM login sessions (cleared every run)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self.lock:
            for lst in (self.applications, self.saved, self.cart, self.notes, self.deals):
                lst.clear()
            self.sessions.clear()


# ----------------------------------------------------------------------------- page chrome
def _e(s) -> str:
    return html.escape(str(s), quote=True)


MENUS = {
    "shop": [("/shop/", "Home"), ("/shop/c/baby", "Baby"), ("/shop/c/toys", "Toys"), ("/shop/c/books", "Books"),
             ("/shop/cart", "Cart"), ("/shop/account", "My account")],
    "papers": [("/papers/", "Search"), ("/papers/about", "About"), ("/papers/alerts", "Alerts"),
               ("/papers/settings", "Settings")],
    "jobs": [("/jobs/", "Find jobs"), ("/jobs/companies", "Companies"), ("/jobs/salaries", "Salaries"),
             ("/jobs/post", "Post a job")],
    "crm": [("/crm/", "Dashboard"), ("/crm/contacts", "Contacts"), ("/crm/deals/new", "New deal"),
            ("/crm/reports", "Reports")],
}

POPUP = ('<div class="modal-backdrop" style="position:fixed;top:0;left:0;right:0;bottom:0;'
         'background:rgba(0,0,0,.55);z-index:1000">'
         '<div class="modal" style="background:#fff;max-width:420px;margin:120px auto;padding:20px">'
         '<h3>Get our weekly newsletter</h3><p>Tips for growing your sales, every Monday.</p>'
         '<input type="email" class="nl-email" placeholder="Your email" aria-label="Newsletter email">'
         '<button type="button" class="nl-join">Join</button> '
         '<button type="button" class="nl-close" onclick="this.parentNode.parentNode.remove()">No thanks</button>'
         '</div></div>')


def page(site: str, title: str, body: str, popup: bool = False) -> str:
    nav = "".join(f'<li class="nav-item"><a class="nav-link" href="{h}">{_e(t)}</a></li>' for h, t in MENUS[site])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{_e(title)}</title>
<style>body{{font-family:sans-serif;margin:0}} .wrap{{max-width:960px;margin:auto;padding:12px}}
td,th{{padding:4px 8px;border-bottom:1px solid #eee}}</style></head>
<body>
<header class="site-header" id="top">
  <div class="wrap"><a class="logo" href="/{site}/">{site.title()}Lab</a>
  <nav class="main-nav" aria-label="Main"><ul class="nav-list">{nav}</ul></nav></div>
</header>
<div class="cookie-banner" id="cookie-banner"><p>We use cookies to improve your experience.</p>
  <button type="button" class="btn-cookie" onclick="this.parentNode.style.display='none'">Accept all</button></div>
<main class="wrap" id="main">
{body}
</main>
<aside class="sidebar wrap"><h4>Popular</h4><ul class="side-links">
  <li><a href="/{site}/help">How it works</a></li><li><a href="/{site}/about">About us</a></li></ul></aside>
<footer class="site-footer wrap"><p>&copy; 2026 {site.title()}Lab</p>
  <ul class="footer-links"><li><a href="/{site}/privacy">Privacy</a></li><li><a href="/{site}/terms">Terms</a></li>
  <li><a href="/{site}/contact">Contact</a></li></ul></footer>
{POPUP if popup else ""}
</body></html>"""


def _q(query: dict, key: str) -> str:
    return (query.get(key) or [""])[0]


def _cart_form(pid: int) -> str:
    return (f'<form class="cart-form" action="/shop/cart/add/{pid}" method="post">'
            f'<button type="submit" class="add-cart">Add to cart</button></form>')


# ----------------------------------------------------------------------------- shop
def shop(method: str, path: str, query: dict, state: LabState, form: dict | None) -> tuple[int, str]:
    parts = [p for p in path.split("/") if p][1:]           # after "shop"
    if not parts:
        cats = "".join(f'<li class="cat"><a class="cat-link" href="/shop/c/{k}">{_e(v)}</a></li>'
                       for k, v in CATEGORIES.items())
        body = (f'<h1 class="page-title">Welcome to ShopLab</h1>'
                f'<form class="search-form" action="/shop/search" method="get">'
                f'<input type="text" name="q" class="search-input" placeholder="Search products" aria-label="Search products">'
                f'<button type="submit" class="search-btn">Search</button></form>'
                f'<h2>Categories</h2><ul class="cat-list">{cats}</ul>')
        return 200, page("shop", "ShopLab", body)
    if parts[0] == "c" and len(parts) > 1 and parts[1] in CATEGORIES:
        cat = parts[1]
        items = [p for p in PRODUCTS if p.category == cat]
        pages = (len(items) + PER_PAGE - 1) // PER_PAGE
        n = max(1, min(pages, int(_q(query, "page") or 1)))
        chunk = items[(n - 1) * PER_PAGE:n * PER_PAGE]
        cards = "".join(
            f'<li class="product-card" data-testid="product">'
            f'<h3 class="product-title"><a class="product-link" href="/shop/p/{p.id}">{_e(p.name)}</a></h3>'
            f'<span class="price">${p.price:.2f}</span> <span class="rating">{p.rating} stars</span>'
            f'{_cart_form(p.id)}</li>' for p in chunk)
        nums = "".join(f'<li><a class="page-num" href="/shop/c/{cat}?page={i}">{i}</a></li>' if i != n
                       else f'<li><span class="page-current">{i}</span></li>' for i in range(1, pages + 1))
        prev = f'<li><a class="page-prev" href="/shop/c/{cat}?page={n - 1}">Previous</a></li>' if n > 1 else ""
        nxt = f'<li><a class="page-next" href="/shop/c/{cat}?page={n + 1}">Next</a></li>' if n < pages else ""
        body = (f'<h1 class="page-title">{CATEGORIES[cat]}</h1><p class="count">{len(items)} products</p>'
                f'<ul class="product-grid">{cards}</ul><nav class="pagination"><ul class="pages">{prev}{nums}{nxt}</ul></nav>')
        return 200, page("shop", f"{CATEGORIES[cat]} - ShopLab", body)
    if parts[0] == "p" and len(parts) > 1:
        p = next((x for x in PRODUCTS if str(x.id) == parts[1]), None)
        if not p:
            return 404, page("shop", "Not found", "<h1>Product not found</h1>")
        body = (f'<article class="product-detail"><h1 class="product-name">{_e(p.name)}</h1>'
                f'<p class="price">${p.price:.2f}</p><p class="rating">{p.rating} stars</p>'
                f'<p class="desc">A {CATEGORIES[p.category].lower()} product.</p>{_cart_form(p.id)}</article>')
        return 200, page("shop", p.name, body)
    if parts[0] == "cart" and len(parts) > 2 and parts[1] == "add" and method == "POST":
        p = next((x for x in PRODUCTS if str(x.id) == parts[2]), None)
        if not p:
            return 404, page("shop", "Not found", "<h1>Product not found</h1>")
        with state.lock:
            state.cart.append(p.id)
        return 200, page("shop", "Added to cart",
                         f'<h1 class="done">Added to cart</h1><p>{_e(p.name)} is in your cart.</p>'
                         f'<a class="back" href="/shop/c/{p.category}">Continue shopping</a>')
    if parts[0] == "cart":
        with state.lock:
            ids = list(state.cart)
        rows = "".join(f"<li>{_e(next(p.name for p in PRODUCTS if p.id == i))}</li>" for i in ids)
        return 200, page("shop", "Cart", f'<h1>Your cart</h1><ul class="cart-items">{rows or "<li>Empty</li>"}</ul>')
    if parts[0] == "search":
        q = _q(query, "q").lower()
        hits = [p for p in PRODUCTS if q and q in p.name.lower()]
        cards = "".join(f'<li class="product-card"><a class="product-link" href="/shop/p/{p.id}">{_e(p.name)}</a>'
                        f' <span class="price">${p.price:.2f}</span></li>' for p in hits)
        return 200, page("shop", "Search - ShopLab", f'<h1>Results for "{_e(q)}"</h1><ul class="product-grid">{cards}</ul>')
    return 200, page("shop", "ShopLab", "<h1>Information</h1><p>Static page.</p>")


# ----------------------------------------------------------------------------- papers
def papers(path: str, query: dict) -> tuple[int, str]:
    parts = [p for p in path.split("/") if p][1:]
    form = (f'<form class="search-form" action="/papers/search" method="get">'
            f'<input type="text" name="q" class="query" placeholder="Search papers" aria-label="Search papers">'
            f'<button type="submit" class="search-btn">Search</button></form>')
    if not parts:
        return 200, page("papers", "PaperLab", f'<h1 class="page-title">PaperLab Search</h1>{form}')
    if parts[0] == "search":
        q = _q(query, "q")
        res = search_papers(q)
        items = "".join(
            f'<div class="result" data-testid="result">'
            f'<h3 class="result-title"><a href="/papers/p/{p.id}">{_e(p.title)}</a></h3>'
            f'<div class="result-meta">{_e(p.authors)} - {p.year}</div>'
            f'<div class="result-links"><a href="/papers/cites/{p.id}">Cited by {10 + p.id * 3}</a> '
            f'<a href="/papers/related/{p.id}">Related articles</a></div></div>' for p in res)
        body = (f'{form}<p class="count">About {len(res)} results for "{_e(q)}"</p>'
                f'<div class="results">{items or "<p>No results.</p>"}</div>')
        return 200, page("papers", f"{q} - PaperLab", body)
    if parts[0] == "p" and len(parts) > 1:
        p = next((x for x in PAPERS if str(x.id) == parts[1]), None)
        if not p:
            return 404, page("papers", "Not found", "<h1>Paper not found</h1>")
        filler = " ".join(["We describe the setting, the method and the evaluation in detail."] * 6)
        body = (f'<article class="paper"><h1 class="paper-title">{_e(p.title)}</h1>'
                f'<p class="authors">{_e(p.authors)} ({p.year})</p>'
                f'<section class="abstract"><h2>Abstract</h2><p>{_e(filler)}</p>'
                f'<p class="finding">Main result: {_e(p.finding)}</p></section></article>')
        return 200, page("papers", p.title, body)
    return 200, page("papers", "PaperLab", "<h1>Information</h1><p>Static page.</p>")


# ----------------------------------------------------------------------------- jobs
def jobs(path: str, query: dict, state: LabState, form: dict | None = None) -> tuple[int, str]:
    parts = [p for p in path.split("/") if p][1:]
    if not parts:
        q, loc = _q(query, "q"), _q(query, "loc")
        res = search_jobs(q, loc)
        opts = "".join(f'<option value="{l}"{" selected" if l == loc else ""}>{l}</option>' for l in LOCATIONS)
        items = "".join(
            f'<li class="job-card"><h3 class="job-title"><a href="/jobs/j/{j.id}">{_e(j.title)}</a></h3>'
            f'<span class="company">{_e(j.company)}</span> <span class="location">{_e(j.location)}</span>'
            f' <a class="save-job" href="/jobs/save/{j.id}">Save</a></li>' for j in res)
        body = (f'<h1 class="page-title">Find your next job</h1>'
                f'<form class="job-search" action="/jobs/" method="get">'
                f'<input type="text" name="q" class="job-query" placeholder="Job title or skill" aria-label="Job title or skill" value="{_e(q)}">'
                f'<select name="loc" class="job-loc" aria-label="Location"><option value="">Any location</option>{opts}</select>'
                f'<button type="submit" class="search-btn">Search</button></form>'
                f'<p class="count">{len(res)} jobs</p><ul class="job-list">{items}</ul>')
        return 200, page("jobs", "JobLab", body)
    if parts[0] == "save" and len(parts) > 1:
        j = next((x for x in JOBS if str(x.id) == parts[1]), None)
        if not j:
            return 404, page("jobs", "Not found", "<h1>Job not found</h1>")
        with state.lock:
            state.saved.append(j.id)
        return 200, page("jobs", "Saved", f'<h1 class="done">Job saved</h1><p>{_e(j.title)} was saved.</p>'
                                           f'<a class="back" href="/jobs/">Back to jobs</a>')
    if parts[0] == "j" and len(parts) > 1:
        j = next((x for x in JOBS if str(x.id) == parts[1]), None)
        if not j:
            return 404, page("jobs", "Not found", "<h1>Job not found</h1>")
        body = (f'<article class="job-detail"><h1 class="job-name">{_e(j.title)}</h1>'
                f'<p class="company">{_e(j.company)} - {_e(j.location)}</p><p class="tags">Skills: {_e(j.tags)}</p>'
                f'<a class="apply-btn" href="/jobs/apply/{j.id}">Apply</a> '
                f'<a class="save-job" href="/jobs/save/{j.id}">Save job</a></article>')
        return 200, page("jobs", j.title, body)
    if parts[0] == "apply" and len(parts) > 1:
        j = next((x for x in JOBS if str(x.id) == parts[1]), None)
        if not j:
            return 404, page("jobs", "Not found", "<h1>Job not found</h1>")
        if form is not None:
            name, email = _q(form, "full_name").strip(), _q(form, "email").strip()
            if not name or not email:
                return 400, page("jobs", "Missing fields", "<h1>Please fill in your name and email.</h1>")
            with state.lock:
                state.applications.append({"job_id": j.id, "full_name": name, "email": email,
                                           "cover": _q(form, "cover")})
            return 200, page("jobs", "Application sent",
                             f'<h1 class="done">Application sent</h1><p>Thank you for applying to {_e(j.title)}.</p>')
        body = (f'<h1 class="page-title">Apply: {_e(j.title)}</h1>'
                f'<form class="apply-form" action="/jobs/apply/{j.id}" method="post">'
                f'<label for="full_name">Full name</label><input type="text" id="full_name" name="full_name">'
                f'<label for="email">Email</label><input type="email" id="email" name="email">'
                f'<label for="cover">Cover letter (optional)</label><textarea id="cover" name="cover"></textarea>'
                f'<button type="submit" class="submit-btn">Submit application</button></form>')
        return 200, page("jobs", f"Apply - {j.title}", body)
    return 200, page("jobs", "JobLab", "<h1>Information</h1><p>Static page.</p>")


# ----------------------------------------------------------------------------- crm
LOAD_MORE_JS = """<script>
function loadMore(btn){
  var n = parseInt(btn.getAttribute('data-offset'), 10);
  var qs = window.location.search ? window.location.search.substring(1) + '&' : '';
  fetch('/crm/contacts/more?' + qs + 'offset=' + n).then(function(r){ return r.text(); }).then(function(t){
    document.querySelector('table tbody').insertAdjacentHTML('beforeend', t);
    var next = n + %d;
    btn.setAttribute('data-offset', next);
    if (next >= parseInt(btn.getAttribute('data-total'), 10)) { btn.style.display = 'none'; }
  });
}
</script>""" % CRM_PAGE


def _crm_rows(rows: list[Contact]) -> str:
    return "".join(f'<tr class="contact-row"><td class="c-name"><a href="/crm/contacts/{c.id}">{_e(c.name)}</a></td>'
                   f'<td class="c-company">{_e(c.company)}</td><td class="c-status">{c.status}</td>'
                   f'<td class="c-value">${c.value:,}</td></tr>' for c in rows)


def crm(method: str, path: str, query: dict, state: LabState, form: dict | None,
        cookies: dict) -> tuple[int, str, dict]:
    parts = [p for p in path.split("/") if p][1:]
    logged_in = cookies.get("crm_sid") in state.sessions
    if parts[:1] == ["login"]:
        if form is not None:
            if _q(form, "username") == CRM_USER and _q(form, "password") == CRM_PASS:
                sid = secrets.token_hex(8)
                with state.lock:
                    state.sessions.add(sid)
                return 303, "", {"Location": "/crm/", "Set-Cookie": f"crm_sid={sid}; Path=/; HttpOnly"}
            err = '<p class="error">Wrong username or password.</p>'
        else:
            err = ""
        body = (f'<h1 class="page-title">Sign in to CRM</h1>{err}'
                f'<form class="login-form" action="/crm/login" method="post">'
                f'<label for="username">Username</label><input type="text" id="username" name="username">'
                f'<label for="password">Password</label><input type="password" id="password" name="password">'
                f'<button type="submit" class="login-btn">Sign in</button></form>')
        return 200, page("crm", "Sign in - CRM", body), {}
    if not logged_in:
        return 303, "", {"Location": "/crm/login"}
    if not parts:
        counts = {s: sum(1 for c in CONTACTS if c.status == s) for s in ("Lead", "Customer", "Lost")}
        tiles = "".join(f'<div class="tile"><span class="tile-label">{s}</span> <b>{n}</b></div>' for s, n in counts.items())
        body = (f'<h1 class="page-title">Dashboard</h1><div class="tiles">{tiles}</div>'
                f'<p><a class="go-contacts" href="/crm/contacts">View all contacts</a></p>')
        return 200, page("crm", "Dashboard - CRM", body, popup=True), {}
    if parts == ["contacts", "more"]:                      # the "Load more" fragment (rows only)
        rows = crm_contacts(_q(query, "status"), _q(query, "sort") or "name")
        off = int(_q(query, "offset") or 0)
        return 200, _crm_rows(rows[off:off + CRM_PAGE]), {"X-Fragment": "1"}
    if parts == ["contacts"]:
        status, sort = _q(query, "status"), _q(query, "sort") or "name"
        rows = crm_contacts(status, sort)
        sopts = "".join(f'<option value="{s}"{" selected" if s == status else ""}>{s}</option>'
                        for s in ("Lead", "Customer", "Lost"))
        oopts = "".join(f'<option value="{k}"{" selected" if k == sort else ""}>{v}</option>'
                        for k, v in (("name", "Name"), ("value", "Deal value")))
        more = (f'<button type="button" class="load-more" data-offset="{CRM_PAGE}" data-total="{len(rows)}" '
                f'onclick="loadMore(this)">Load more</button>' if len(rows) > CRM_PAGE else "")
        body = (f'<h1 class="page-title">Contacts</h1>'
                f'<form class="filter-form" action="/crm/contacts" method="get">'
                f'<label for="status">Status</label><select id="status" name="status"><option value="">All</option>{sopts}</select>'
                f'<label for="sort">Sort by</label><select id="sort" name="sort">{oopts}</select>'
                f'<button type="submit" class="filter-btn">Apply filter</button></form>'
                f'<p class="count">{len(rows)} contacts</p>'
                f'<table class="contacts"><thead><tr><th>Name</th><th>Company</th><th>Status</th><th>Deal value</th></tr></thead>'
                f'<tbody>{_crm_rows(rows[:CRM_PAGE])}</tbody></table>{more}{LOAD_MORE_JS}')
        return 200, page("crm", "Contacts - CRM", body, popup=True), {}
    if parts[0] == "contacts" and len(parts) >= 2:
        c = next((x for x in CONTACTS if str(x.id) == parts[1]), None)
        if not c:
            return 404, page("crm", "Not found", "<h1>Contact not found</h1>"), {}
        if len(parts) == 3 and parts[2] == "note" and form is not None:
            note = _q(form, "note").strip()
            if note:
                with state.lock:
                    state.notes.append({"contact_id": c.id, "note": note})
            return 200, page("crm", "Note saved", f'<h1 class="done">Note saved</h1><p>Note added to {_e(c.name)}.</p>'
                                                   f'<a class="back" href="/crm/contacts">Back to contacts</a>'), {}
        body = (f'<article class="contact"><h1 class="contact-name">{_e(c.name)}</h1>'
                f'<p class="company">{_e(c.company)}</p><p class="status">Status: {c.status}</p>'
                f'<p class="value">Deal value: ${c.value:,}</p></article>'
                f'<form class="note-form" action="/crm/contacts/{c.id}/note" method="post">'
                f'<label for="note">Add a note</label><textarea id="note" name="note"></textarea>'
                f'<button type="submit" class="note-btn">Save note</button></form>')
        return 200, page("crm", f"{c.name} - CRM", body), {}
    if parts == ["deals", "new"]:
        step = _q(form or {}, "step") if form is not None else "0"
        hidden = "".join(f'<input type="hidden" name="{k}" value="{_e(_q(form, k))}">'
                         for k in ("contact_id", "title", "amount", "stage", "priority", "close_date")
                         if form is not None and k in form)
        if form is None or step == "0":
            copts = "".join(f'<option value="{c.id}">{_e(c.name)} ({_e(c.company)})</option>' for c in crm_contacts())
            body = (f'<h1 class="page-title">New deal - step 1 of 3</h1>'
                    f'<form class="deal-form" action="/crm/deals/new" method="post"><input type="hidden" name="step" value="1">'
                    f'<label for="contact_id">Contact</label><select id="contact_id" name="contact_id">{copts}</select>'
                    f'<label for="title">Deal title</label><input type="text" id="title" name="title">'
                    f'<button type="submit" class="next-btn">Continue</button></form>')
            return 200, page("crm", "New deal - CRM", body), {}
        if step == "1":
            sopts = "".join(f'<option value="{s}">{s}</option>' for s in STAGES)
            body = (f'<h1 class="page-title">New deal - step 2 of 3</h1>'
                    f'<form class="deal-form" action="/crm/deals/new" method="post">{hidden}<input type="hidden" name="step" value="2">'
                    f'<label for="amount">Amount (USD)</label><input type="number" id="amount" name="amount">'
                    f'<label for="stage">Stage</label><select id="stage" name="stage">{sopts}</select>'
                    f'<label for="priority"><input type="checkbox" id="priority" name="priority" value="yes"> High priority</label>'
                    f'<label for="close_date">Expected close date</label><input type="date" id="close_date" name="close_date">'
                    f'<button type="submit" class="next-btn">Continue</button></form>')
            return 200, page("crm", "New deal - CRM", body), {}
        if step == "2":
            c = next((x for x in CONTACTS if str(x.id) == _q(form, "contact_id")), None)
            summary = (f'<ul class="summary"><li>Contact: {_e(c.name if c else "?")}</li><li>Title: {_e(_q(form, "title"))}</li>'
                       f'<li>Amount: {_e(_q(form, "amount"))}</li><li>Stage: {_e(_q(form, "stage"))}</li>'
                       f'<li>Priority: {"high" if _q(form, "priority") else "normal"}</li>'
                       f'<li>Close date: {_e(_q(form, "close_date"))}</li></ul>')
            body = (f'<h1 class="page-title">New deal - step 3 of 3</h1>{summary}'
                    f'<form class="deal-form" action="/crm/deals/new" method="post">{hidden}<input type="hidden" name="step" value="3">'
                    f'<button type="submit" class="create-btn">Create deal</button></form>')
            return 200, page("crm", "New deal - CRM", body), {}
        if step == "3":
            deal = {k: _q(form, k).strip() for k in ("contact_id", "title", "amount", "stage", "close_date")}
            deal["priority"] = bool(_q(form, "priority"))
            with state.lock:
                state.deals.append(deal)
            return 200, page("crm", "Deal created", '<h1 class="done">Deal created</h1>'
                                                     '<a class="back" href="/crm/">Back to dashboard</a>'), {}
    return 200, page("crm", "CRM", "<h1>Information</h1><p>Static page.</p>"), {}


# ----------------------------------------------------------------------------- dispatch
def route(method: str, path: str, query: dict, state: LabState, body: bytes = b"",
          cookie_header: str = "") -> tuple[int, str, dict]:
    form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True) if method == "POST" else None
    if path.startswith("/shop"):
        return (*shop(method, path, query, state, form), {})
    if path.startswith("/papers"):
        return (*papers(path, query), {})
    if path.startswith("/jobs"):
        return (*jobs(path, query, state, form), {})
    if path.startswith("/crm"):
        jar = SimpleCookie()
        try:
            jar.load(cookie_header or "")
        except Exception:
            pass
        return crm(method, path, query, state, form, {k: v.value for k, v in jar.items()})
    links = "".join(f'<li><a href="/{s}/">{s.title()}Lab</a></li>' for s in ("shop", "papers", "jobs", "crm"))
    return 200, f"<html><body><h1>Ecogent benchmark lab</h1><ul>{links}</ul></body></html>", {}
