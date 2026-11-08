"""
Deterministic site drift: the same page at drift level 0-4 (cumulative), reproducible from a seed.

  0 none        the original page
  1 attributes  CSS classes and ids renamed (labels / #anchors follow), data-testid removed
  2 structure   + elements wrapped in extra containers, a promo banner inserted, menu order reversed
  3 text        + interface wording changed (buttons, links, labels, placeholders, aria-labels)
  4 redesign    + repeated item lists rebuilt with other tags and reordered fields, table columns
                  reversed, submit buttons become <input type=submit>, the first GET form moves to the
                  header, pagination restyled

Invariants (checked by bench/lab/selftest.py): the data on the page (product names, prices,
paper findings, job titles) is unchanged, every original link target still exists, and every form
keeps its action, method and field names - so each task stays solvable at every level.
"""

from __future__ import annotations

import hashlib
import random
import re

from bs4 import BeautifulSoup, NavigableString, Tag

LEVELS = {0: "none", 1: "attributes", 2: "structure", 3: "text", 4: "redesign"}

# Interface wording only (exact match, case-insensitive). Data text is never in this table.
UI_TEXT = {
    "search": "Find", "next": "More results", "previous": "Back", "apply": "Start application",
    "submit application": "Send", "add to cart": "Buy now", "full name": "Your name", "email": "E-mail address",
    "save": "Bookmark", "save job": "Bookmark job", "accept all": "OK", "search products": "What are you looking for?",
    "search papers": "Find literature", "job title or skill": "Keywords", "related articles": "Similar papers",
    "home": "Start", "cover letter (optional)": "Message (optional)", "my account": "Account",
    "load more": "Show more", "apply filter": "Update list", "sign in": "Log in", "username": "User ID",
    "password": "Passcode", "continue": "Next step", "create deal": "Confirm", "save note": "Add note",
    "add a note": "Note", "no thanks": "Close", "status": "Stage of contact", "sort by": "Order",
    "deal title": "Name of deal", "amount (usd)": "Value (USD)", "expected close date": "Closing on",
    "high priority": "Urgent", "any location": "All locations", "contact": "Client",
}
_CITED = re.compile(r"^Cited by (\d+)$")
_TEXT_ATTRS = ("placeholder", "aria-label", "title", "value")


def _h(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:6]


def apply(html: str, level: int, seed: int = 1, page_key: str = "", fragment: bool = False) -> str:
    """The page at a drift level. page_key (path + query) makes per-page choices stable.
    fragment=True: an HTML snippet loaded by JavaScript (e.g. "Load more" rows) - it gets the same
    renames and wording as the page around it."""
    if level <= 0 or not html or (not fragment and "<html" not in html[:400].lower()):
        return html
    soup = BeautifulSoup(html, "html.parser")
    rng = random.Random(f"{seed}|{level}|{page_key}")
    _attributes(soup, seed)
    if level >= 2:
        _structure(soup, rng, seed)
    if level >= 3:
        _text(soup)
    if level >= 4:
        _redesign(soup, seed)
    return str(soup)


# ----------------------------------------------------------------------------- level 1
def _attributes(soup: BeautifulSoup, seed: int) -> None:
    ids = {}
    for el in soup.find_all(True):
        if el.get("class"):
            el["class"] = [f"c{_h(seed, c)}" for c in el["class"]]
        if el.get("id"):
            new = f"i{_h(seed, el['id'])}"
            ids[el["id"]] = new
            el["id"] = new
        if "data-testid" in el.attrs:
            del el["data-testid"]
    for el in soup.find_all(attrs={"for": True}):
        el["for"] = ids.get(el["for"], el["for"])
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("#") and a["href"][1:] in ids:
            a["href"] = "#" + ids[a["href"][1:]]


# ----------------------------------------------------------------------------- level 2
def _wrap(soup: BeautifulSoup, el: Tag, seed: int, tag: str = "span") -> None:
    w = soup.new_tag(tag)
    w["class"] = [f"w{_h(seed, 'wrap', el.name)}"]
    el.wrap(w)


def _structure(soup: BeautifulSoup, rng: random.Random, seed: int) -> None:
    main = soup.find("main") or soup.body
    for el in list(soup.find_all(["a", "button", "input", "textarea"])):
        if rng.random() < 0.4:
            _wrap(soup, el, seed)
    for li in list(soup.find_all("li")):
        if rng.random() < 0.4 and li.contents:
            inner = soup.new_tag("div")
            inner["class"] = [f"w{_h(seed, 'li')}"]
            for child in list(li.contents):
                inner.append(child.extract())
            li.append(inner)
    if main is not None:
        banner = BeautifulSoup(
            f'<div class="p{_h(seed, "promo")}"><p>Limited offer: free delivery this week.</p>'
            f'<a href="/promo">See offer</a></div>', "html.parser")
        main.insert(0, banner)
    for ul in soup.find_all("ul"):
        if ul.find_parent("nav") is not None and ul.find_parent("header") is not None:
            items = [li.extract() for li in ul.find_all("li", recursive=False)]
            for li in reversed(items):
                ul.append(li)


# ----------------------------------------------------------------------------- level 3
def _new_text(s: str) -> str | None:
    t = " ".join(s.split())
    if not t:
        return None
    m = _CITED.match(t)
    if m:
        return f"{m.group(1)} citations"
    return UI_TEXT.get(t.lower())


def _text(soup: BeautifulSoup) -> None:
    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString) or node.parent.name in ("script", "style", "title"):
            continue
        new = _new_text(str(node))
        if new is not None:
            node.replace_with(new)
    for el in soup.find_all(True):
        for attr in _TEXT_ATTRS:
            if attr in el.attrs and isinstance(el[attr], str):
                if attr == "value" and el.name == "input" and el.get("type") not in ("submit", "button"):
                    continue            # a filled-in value is data, not wording
                new = _new_text(el[attr])
                if new is not None:
                    el[attr] = new


# ----------------------------------------------------------------------------- level 4
def _repeated_containers(soup: BeautifulSoup) -> list[Tag]:
    out = []
    for el in soup.find_all(["ul", "div"]):
        kids = [k for k in el.find_all(True, recursive=False)]
        if len(kids) >= 3 and len({k.name for k in kids}) == 1 and el.find_parent(["nav", "header", "footer"]) is None:
            out.append(el)
    return out


def _redesign(soup: BeautifulSoup, seed: int) -> None:
    # Repeated item lists: other tags, fields in reverse order (title no longer first).
    for box in _repeated_containers(soup):
        box.name = "div"
        box["class"] = [f"g{_h(seed, 'grid')}"]
        for item in box.find_all(True, recursive=False):
            if item.name in ("li", "div"):
                item.name = "article"
            kids = [k.extract() for k in list(item.contents)]
            for k in reversed(kids):
                item.append(k)
            for hd in item.find_all(["h3", "h2"]):
                hd.name = "div"
                hd["role"] = "heading"
    # Tables: columns in reverse order (header and rows alike, also in "Load more" fragments).
    for tr in soup.find_all("tr"):
        cells = [c.extract() for c in tr.find_all(["td", "th"], recursive=False)]
        for c in reversed(cells):
            tr.append(c)
    # Submit buttons become inputs (same form, same submission).
    for btn in soup.find_all("button"):
        if btn.find_parent("form") is not None and btn.get("type", "submit") == "submit":
            inp = soup.new_tag("input", attrs={"type": "submit", "value": btn.get_text(" ", strip=True)})
            if btn.get("class"):
                inp["class"] = btn["class"]
            btn.replace_with(inp)
    # The first search form moves into the header.
    header, form = soup.find("header"), (soup.find("main") or soup).find("form", method="get")
    if header is not None and form is not None:
        header.append(form.extract())
    # Pagination: arrows instead of words, numbers kept.
    for a in soup.find_all("a", href=re.compile(r"page=\d+")):
        label = a.get_text(" ", strip=True).lower()
        if label in ("more results", "next"):
            a.string, a["aria-label"] = "›", "Next page"
        elif label in ("back", "previous"):
            a.string, a["aria-label"] = "‹", "Previous page"
