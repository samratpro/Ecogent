"""
BeautifulSoup page reading.

Implements the context ladder from how_work.md so the LLM sees as little as possible:
  level 1  probable elements  (e.g. only text inputs for a "fill" step, ranked by the hint)
  level 2  broader area       (every interactive element)
  level 3  whole page outline (noise and outliers removed)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

NOISE_TAGS = ["script", "style", "noscript", "svg", "template", "canvas", "path", "meta", "link", "head"]
CHROME_TAGS = ["nav", "footer", "header", "aside"]
KEEP_ATTRS = ("id", "name", "type", "placeholder", "aria-label", "title", "role", "href", "value", "alt", "data-testid")
TEXT_INPUT_TYPES = {"", "text", "search", "email", "tel", "url", "password", "number", "date"}

BLOCKER_PATTERNS = [
    "captcha", "unusual traffic", "verify you are human", "are you a robot", "not a robot",
    "press and hold", "security check", "checking your browser",
]


def soup_of(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")
    for t in soup(NOISE_TAGS):
        t.decompose()
    return soup


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_hidden(el: Tag) -> bool:
    if el.get("type", "").lower() == "hidden" or el.has_attr("hidden"):
        return True
    if el.get("aria-hidden") == "true":
        return True
    style = el.get("style", "").replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


# --------------------------------------------------------------------------- selectors
_SAFE_ID = re.compile(r"^[A-Za-z][\w-]*$")


def _q(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def _unique(soup: BeautifulSoup, sel: str) -> bool:
    try:
        return len(soup.select(sel)) == 1
    except Exception:
        return False


def css_selector(el: Tag, soup: BeautifulSoup) -> str:
    """A selector that matches exactly this element, preferring stable attributes."""
    tag = el.name
    cands = []
    if el.get("id") and _SAFE_ID.match(el["id"]):
        cands.append(f"#{el['id']}")
    for attr in ("data-testid", "name", "aria-label", "placeholder", "title"):
        v = el.get(attr)
        if isinstance(v, str) and v and len(v) < 120:
            cands.append(f'{tag}[{attr}="{_q(v)}"]')
    href = el.get("href")
    if tag == "a" and isinstance(href, str) and href and len(href) < 200:
        cands.append(f'a[href="{_q(href)}"]')
    for c in cands:
        if _unique(soup, c):
            return c
    # Positional path, anchored at the nearest ancestor with a safe unique id.
    parts = []
    node: Optional[Tag] = el
    while node is not None and isinstance(node, Tag) and node.name not in ("[document]", "html"):
        if node is not el and node.get("id") and _SAFE_ID.match(node["id"]) and _unique(soup, f"#{node['id']}"):
            parts.append(f"#{node['id']}")
            break
        parent = node.parent
        if parent is None:
            parts.append(node.name)
            break
        same = [s for s in parent.find_all(node.name, recursive=False)]
        parts.append(f"{node.name}:nth-of-type({same.index(node) + 1})" if len(same) > 1 else node.name)
        node = parent
    return " > ".join(reversed(parts))


def describe(el: Tag) -> dict:
    attrs = {}
    for a in KEEP_ATTRS:
        v = el.get(a)
        if v:
            v = " ".join(v) if isinstance(v, list) else str(v)
            attrs[a] = v[:80]
    return {"tag": el.name, "text": _norm(el.get_text(" "))[:80], "attrs": attrs}


# --------------------------------------------------------------------------- candidates
def _kind_match(el: Tag, action: str) -> bool:
    tag, role = el.name, (el.get("role") or "").lower()
    typ = (el.get("type") or "").lower()
    if action in ("fill", "press"):
        return (tag == "input" and typ in TEXT_INPUT_TYPES) or tag == "textarea" or \
            el.get("contenteditable") in ("", "true") or role in ("textbox", "searchbox", "combobox")
    if action == "select_option":
        return tag == "select" or role in ("combobox", "listbox")
    if action == "upload":
        return tag == "input" and typ == "file"
    # click / wait
    return tag in ("a", "button", "summary", "label") or role in ("button", "link", "tab", "menuitem", "checkbox", "option") \
        or (tag == "input" and typ in ("submit", "button", "checkbox", "radio", "image")) or el.has_attr("onclick")


def _interactive(el: Tag) -> bool:
    return el.name in ("a", "button", "input", "textarea", "select", "summary", "label") or \
        el.has_attr("role") or el.has_attr("onclick") or el.has_attr("contenteditable")


def _score(info: dict, words: list[str]) -> int:
    hay = (info["text"] + " " + " ".join(info["attrs"].values())).lower()
    return sum(3 if w in info["text"].lower() else 1 for w in words if w in hay)


def candidates(html: str, action: str, hint: str, level: int = 1, limit: Optional[int] = None) -> list[dict]:
    soup = soup_of(html)
    words = [w for w in re.findall(r"[a-z0-9]+", (hint or "").lower()) if len(w) > 2]
    pool = []
    for el in soup.find_all(True):
        if _is_hidden(el):
            continue
        if level == 1 and not _kind_match(el, action):
            continue
        if level >= 2 and not _interactive(el):
            continue
        info = describe(el)
        if not info["text"] and not info["attrs"]:
            continue
        info["_el"] = el
        info["score"] = _score(info, words)
        pool.append(info)
    limit = limit or (15 if level == 1 else 60)
    pool.sort(key=lambda d: -d["score"])  # stable: keeps document order on ties
    out = []
    for i, info in enumerate(pool[:limit]):
        el = info.pop("_el")
        info.pop("score")
        info["i"] = i
        info["selector"] = css_selector(el, soup)
        out.append(info)
    return out


def candidates_for_prompt(cands: list[dict]) -> str:
    lines = []
    for c in cands:
        attrs = " ".join(f'{k}="{v}"' for k, v in c["attrs"].items())
        lines.append(f'[{c["i"]}] <{c["tag"]} {attrs}> {c["text"]}'.replace("  ", " "))
    return "\n".join(lines)


# --------------------------------------------------------------------------- page text
def main_text(html: str, max_chars: int = 12000) -> tuple[str, str]:
    """(title, readable main text) with menus, footers and repeated boilerplate removed."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.IGNORECASE | re.DOTALL)
    title = _norm(BeautifulSoup(m.group(1), "html.parser").get_text()) if m else ""
    soup = soup_of(html)
    root = soup.find("main") or soup.find("article") or soup.body or soup
    for t in root.find_all(CHROME_TAGS):
        t.decompose()
    lines = [_norm(l) for l in root.get_text("\n").splitlines()]
    lines = [l for l in lines if len(l) > 2]
    counts = Counter(lines)
    seen, kept = set(), []
    for l in lines:
        if counts[l] > 3 and len(l) < 60:   # outlier: repeated short boilerplate
            continue
        if l in seen:
            continue
        seen.add(l)
        kept.append(l)
    return title, "\n".join(kept)[:max_chars]


def page_outline(html: str, max_chars: int = 12000) -> str:
    """Compact HTML-ish outline for level-3 element search."""
    soup = soup_of(html)
    body = soup.body or soup
    out: list[str] = []

    def walk(el: Tag, depth: int) -> None:
        if sum(len(x) for x in out) > max_chars or depth > 25:
            return
        if _is_hidden(el):
            return
        own = _norm("".join(t for t in el.find_all(string=True, recursive=False)))[:60]
        attrs = describe(el)["attrs"]
        cls = el.get("class")
        if cls:
            attrs["class"] = " ".join(cls)[:50]
        if own or attrs or _interactive(el):
            a = " ".join(f'{k}="{v}"' for k, v in attrs.items())
            out.append(f"{'  ' * min(depth, 12)}<{el.name}{' ' + a if a else ''}>{own}")
        for child in el.find_all(True, recursive=False):
            walk(child, depth + 1)

    walk(body, 0)
    return "\n".join(out)[:max_chars]


def detect_blocker(html: str) -> Optional[str]:
    """Return a reason when the page shows a captcha / bot challenge."""
    raw = (html or "").lower()
    if re.search(r"<iframe[^>]+(recaptcha|hcaptcha|challenges\.cloudflare|turnstile)", raw):
        return "captcha challenge"
    _, text = main_text(html, 4000)
    low = text.lower()
    if len(low) < 3000:  # challenge pages are short; avoid false hits on articles
        for p in BLOCKER_PATTERNS:
            if p in low:
                return f"page says '{p}'"
    return None


# --------------------------------------------------------------------------- links
def _signature(el: Tag) -> str:
    parts = []
    node = el
    for _ in range(3):
        if not isinstance(node, Tag) or node.name in ("body", "html", "[document]"):
            break
        cls = ".".join(sorted(c for c in node.get("class", []) if not re.search(r"\d{3,}", c)))
        parts.append(f"{node.name}{'.' + cls if cls else ''}")
        node = node.parent
    return " < ".join(parts)


def links(html: str, base_url: str) -> list[dict]:
    soup = soup_of(html)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urljoin(base_url, href)
        text = _norm(a.get_text(" ")) or a.get("aria-label", "") or a.get("title", "")
        if url in seen or not text:
            continue
        seen.add(url)
        out.append({"text": text[:100], "href": url, "sig": _signature(a)})
    return out


# --------------------------------------------------------------------------- scraping helpers
def repeating_groups(html: str, top: int = 3, sample_chars: int = 2500) -> list[dict]:
    """Find blocks that repeat many times (product cards, result rows, ...)."""
    soup = soup_of(html)
    groups: dict[str, list[Tag]] = defaultdict(list)
    for el in (soup.body or soup).find_all(True):
        cls = [c for c in el.get("class", []) if _SAFE_ID.match(c)]
        if not cls or (el.name in ("a", "span", "img", "i", "b", "strong", "em") and not el.find(True)):
            continue
        key = el.name + "".join(f".{c}" for c in sorted(cls))
        groups[key].append(el)
    scored = []
    for key, els in groups.items():
        if len(els) < 3:
            continue
        avg_text = sum(len(_norm(e.get_text(" "))) for e in els[:20]) / min(len(els), 20)
        avg_kids = sum(len(e.find_all(True)) for e in els[:20]) / min(len(els), 20)
        if avg_text < 20 or avg_kids < 3:
            continue
        scored.append((min(len(els), 60) * min(avg_text, 400) * min(avg_kids, 30), key, els))
    scored.sort(key=lambda t: -t[0])
    out = []
    for _, key, els in scored[:top]:
        out.append({"selector": key, "count": len(els), "sample_html": compact_html(els[0], sample_chars)})
    return out


def compact_html(el: Tag, max_chars: int = 2500) -> str:
    el = BeautifulSoup(str(el), "html.parser")
    for t in el.find_all(True):
        keep = {k: v for k, v in t.attrs.items()
                if k in ("class", "href", "src", "id", "alt", "title", "aria-label") or k.startswith("data-")}
        if "class" in keep:
            keep["class"] = [c for c in keep["class"] if len(c) < 40][:4]
        for k in list(keep):
            if isinstance(keep[k], str) and len(keep[k]) > 120:
                keep[k] = keep[k][:120]
        t.attrs = keep
    s = re.sub(r"\s+", " ", str(el))
    return s[:max_chars]


def next_page_candidates(html: str) -> list[dict]:
    soup = soup_of(html)
    out = []
    for el in soup.find_all(["a", "button", "li", "span"]):
        txt = _norm(el.get_text(" ")).lower()
        aria = (el.get("aria-label") or "").lower()
        rel = " ".join(el.get("rel", [])) if el.get("rel") else ""
        cls = " ".join(el.get("class", [])).lower()
        if txt in ("next", "next page", "›", "»", ">", "next ›", "next »") or "next" in aria or rel == "next" \
                or ("next" in cls and el.name in ("a", "button")):
            info = describe(el)
            info["selector"] = css_selector(el, soup)
            out.append(info)
    return out[:5]


def parse_number(value: str) -> Optional[float]:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", value or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None
