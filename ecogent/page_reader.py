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
    # automatic checks (Cloudflare & co.) that usually pass by themselves after a few seconds
    "verifying you are human", "just a moment", "checking if the site connection is secure",
]

# ---- token diet: what never needs to reach the LLM
# Generated / hashed class names (css-1x2y3z, sc-AbCd, jsx-123, a1b2c3d4): unstable and pure noise.
_HASHED_CLASS = re.compile(r"^(css|sc|jsx|emotion|styled|svelte|chakra)[-_][\w-]+$|\d{3,}|"
                           r"^(?=[A-Za-z\d]*\d)(?=[A-Za-z\d]*[A-Za-z])[A-Za-z\d]{6,}$")
# Blocks that are never page content (for page text only, not for element search).
_NOISE_BLOCK = re.compile(r"cookie|consent|gdpr|newsletter|subscribe|social|share|breadcrumb|advert|\bads?\b|"
                          r"promo|popup|sidebar|related|recommend|banner", re.I)
_NOISE_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search"}
# Short UI lines that carry no information.
_NOISE_LINE = re.compile(r"^(skip to (main )?content|menu|main menu|close|open|share( this)?|sign in|log ?in|log ?out|"
                         r"sign up|register|subscribe|accept( all)?( cookies)?|reject( all)?|cookie settings|"
                         r"back to top|toggle navigation|search|home|more|show more|read more|loading\.*|"
                         r"advertisement|sponsored|previous|next)$", re.I)
_TRACKING_PARAM = re.compile(r"^(utm_\w+|fbclid|gclid|msclkid|ref|ref_|_ga|mc_\w+|igshid|spm|si)$", re.I)
STOP_WORDS = {"the", "and", "for", "with", "this", "that", "into", "from", "main", "page", "please", "click",
              "type", "enter", "field", "box", "button", "link", "input", "area", "section", "top", "your"}


def soup_of(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")
    for t in soup(NOISE_TAGS):
        t.decompose()
    return soup


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_classes(classes, limit: int = 3) -> list[str]:
    """Stable, human-written class names only (hashed / generated ones dropped)."""
    if isinstance(classes, str):
        classes = classes.split()
    return [c for c in (classes or []) if c and len(c) < 40 and not _HASHED_CLASS.search(c)][:limit]


def short_url(url: str, base_url: str = "") -> str:
    """Drop scheme/host when it is the page's own host and strip tracking params."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    try:
        u = urlsplit(url)
        q = urlencode([(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not _TRACKING_PARAM.match(k)])
        host = urlsplit(base_url).netloc if base_url else ""
        if host and u.netloc == host:
            return urlunsplit(("", "", u.path or "/", q, ""))
        return urlunsplit((u.scheme, u.netloc, u.path, q, ""))
    except ValueError:
        return url


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


def hint_words(hint: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (hint or "").lower()) if len(w) > 2 and w not in STOP_WORDS]


# Words in a step target that describe the element kind ("search box", "Next button").
_KIND_WORDS = {
    "button": lambda t, r, ty: t == "button" or r == "button" or ty in ("submit", "button"),
    "link": lambda t, r, ty: t == "a" or r == "link",
    "box": lambda t, r, ty: t in ("input", "textarea") or r in ("textbox", "searchbox"),
    "field": lambda t, r, ty: t in ("input", "textarea", "select"),
    "input": lambda t, r, ty: t in ("input", "textarea"),
    "dropdown": lambda t, r, ty: t == "select" or r in ("combobox", "listbox"),
    "checkbox": lambda t, r, ty: ty == "checkbox" or r == "checkbox",
    "tab": lambda t, r, ty: r == "tab",
}


def score_element(info: dict, words: list[str], hint: str = "") -> int:
    """Text match counts most (3), attribute match 1, element-kind match ("button") 1."""
    text = info["text"].lower()
    hay = text + " " + " ".join(info["attrs"].values()).lower()
    s = sum(3 if w in text else 1 for w in words if w in hay)
    tag, role, typ = info["tag"], info["attrs"].get("role", "").lower(), info["attrs"].get("type", "").lower()
    low = (hint or "").lower()
    s += sum(1 for kw, test in _KIND_WORDS.items() if kw in low and test(tag, role, typ))
    if text and low.strip() and text == low.strip():
        s += 3                      # exact visible text: "Search" for target "Search"
    return s


def candidates(html: str, action: str, hint: str, level: int = 1, limit: Optional[int] = None) -> list[dict]:
    """Probable elements for a step, best first. Each has i, tag, text, attrs, selector, score.
    Identical-looking elements (same tag/text/attrs) are listed once."""
    soup = soup_of(html)
    words = hint_words(hint)
    pool, seen = [], set()
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
        sig = (info["tag"], info["text"], tuple(sorted(info["attrs"].items())))
        if sig in seen:
            continue
        seen.add(sig)
        info["_el"] = el
        info["score"] = score_element(info, words, hint)
        pool.append(info)
    limit = limit or (15 if level == 1 else 60)
    pool.sort(key=lambda d: -d["score"])  # stable: keeps document order on ties
    out = []
    for i, info in enumerate(pool[:limit]):
        el = info.pop("_el")
        info["i"] = i
        info["selector"] = css_selector(el, soup)
        out.append(info)
    return out


_ATTR_SHORT = {"placeholder": "ph", "aria-label": "aria", "data-testid": "tid"}


def candidates_for_prompt(cands: list[dict], base_url: str = "") -> str:
    """One short line per candidate: `[3] <input name=q ph="Search papers"> text`.
    Attributes repeating the visible text are dropped, links are shortened."""
    lines = []
    for c in cands:
        text = c["text"]
        low = text.lower()
        parts = []
        shown = set()
        for k, v in c["attrs"].items():
            vl = v.lower()
            if vl == low or vl in shown or (k == "value" and c["tag"] in ("input", "textarea")
                                           and c["attrs"].get("type", "text") not in ("submit", "button", "reset")):
                continue
            if k == "href":
                v = short_url(v, base_url)[:70]
            shown.add(vl)
            v = v if re.fullmatch(r"[\w./:-]+", v) else f'"{v}"'
            parts.append(f"{_ATTR_SHORT.get(k, k)}={v}")
        attrs = (" " + " ".join(parts)) if parts else ""
        lines.append(f'[{c["i"]}] <{c["tag"]}{attrs}> {text}'.rstrip())
    return "\n".join(lines)


def obvious_choice(cands: list[dict], action: str) -> Optional[dict]:
    """The candidate that clearly wins without asking the LLM, or None when it is ambiguous:
    the only candidate of the right kind, or a top score that is strong and well ahead."""
    if not cands:
        return None
    if len(cands) == 1 and (cands[0].get("score", 0) > 0 or action in ("fill", "press", "select_option", "upload")):
        return cands[0]
    top = cands[0].get("score", 0)
    second = cands[1].get("score", 0) if len(cands) > 1 else 0
    if top >= 4 and top >= 2 * second + 1:
        return cands[0]
    return None


# --------------------------------------------------------------------------- page text
def main_text(html: str, max_chars: int = 12000) -> tuple[str, str]:
    """(title, readable main text) with menus, footers and repeated boilerplate removed."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.IGNORECASE | re.DOTALL)
    title = _norm(BeautifulSoup(m.group(1), "html.parser").get_text()) if m else ""
    soup = soup_of(html)
    root = _content_root(soup)
    for t in root.find_all(CHROME_TAGS):
        t.decompose()
    _drop_noise_blocks(root)
    lines = [_norm(l) for l in root.get_text("\n").splitlines()]
    lines = [l for l in lines if len(l) > 2 and not _NOISE_LINE.match(l) and not _is_junk_line(l)]
    counts = Counter(lines)
    kept: list[str] = []
    seen_long: set[str] = set()
    for l in lines:
        # Outlier: short boilerplate repeated on every card ("Add to cart"). Lines with digits are data
        # (prices, ratings) and are kept even when two products share the same value.
        if counts[l] > 3 and len(l) < 60 and not re.search(r"\d", l):
            continue
        if kept and kept[-1] == l:          # adjacent duplicates are noise
            continue
        if len(l) >= 60:                    # a long sentence repeated anywhere (teasers, captions)
            if l in seen_long:
                continue
            seen_long.add(l)
        kept.append(l)
    return title, "\n".join(kept)[:max_chars]


def _content_root(soup: BeautifulSoup) -> Tag:
    """<main>, else the article only when it holds most of the page (a listing page has one
    <article> per card: taking the first would keep a single product), else <body>."""
    body = soup.body or soup
    main = soup.find("main")
    if main:
        return main
    articles = soup.find_all("article")
    if articles:
        total = len(body.get_text(" ")) or 1
        best = max(articles, key=lambda a: len(a.get_text(" ")))
        if len(articles) == 1 or len(best.get_text(" ")) > total * 0.5:
            return best
    return body


def _drop_noise_blocks(root: Tag) -> None:
    """Remove cookie banners, share bars, newsletter boxes, sidebars, ... by role / id / class.
    A block holding most of the page text is never removed (a body class like 'has-sidebar')."""
    total = len(root.get_text(" ")) or 1
    for el in list(root.find_all(True)):
        if getattr(el, "decomposed", False) or el.parent is None:
            continue
        if el.name in ("main", "article", "body", "html"):
            continue
        role = (el.get("role") or "").lower()
        ident = " ".join([el.get("id") or "", *(el.get("class") or [])])
        if role in _NOISE_ROLES or (ident and _NOISE_BLOCK.search(ident)):
            if len(el.get_text(" ")) < total * 0.5:
                el.decompose()


def _is_junk_line(line: str) -> bool:
    """URL-only lines, base64 / hash blobs and lines without a single letter."""
    if re.fullmatch(r"(https?://|www\.)\S+", line):
        return True
    if len(line) > 40 and " " not in line and re.fullmatch(r"[A-Za-z0-9+/=_-]+", line):
        return True
    return not re.search(r"[^\W\d_]", line) and not re.search(r"\d", line)


REPEAT_SHOW = 3     # repeated sibling blocks shown in full in the page outline


def page_outline(html: str, max_chars: int = 12000) -> str:
    """Compact HTML-ish outline for level-3 element search."""
    soup = soup_of(html)
    body = soup.body or soup
    out: list[str] = []

    size = [0]

    def walk(el: Tag, depth: int) -> None:
        if size[0] > max_chars or depth > 25:
            return
        if _is_hidden(el):
            return
        kids = el.find_all(True, recursive=False)
        own = _norm("".join(t for t in el.find_all(string=True, recursive=False)))[:60]
        attrs = describe(el)["attrs"]
        if attrs.get("href"):
            attrs["href"] = short_url(attrs["href"])[:70]
        if own and attrs.get("title", "").lower() == own.lower():
            attrs.pop("title")
        cls = clean_classes(el.get("class"), 2)
        if cls and "id" not in attrs:
            attrs["class"] = " ".join(cls)
        # Plain wrappers (no text, no meaningful attrs, one child) add a line but no information.
        meaningful = own or _interactive(el) or any(k != "class" for k in attrs) or (attrs and len(kids) > 1)
        if meaningful:
            a = " ".join(f'{_ATTR_SHORT.get(k, k)}="{v}"' for k, v in attrs.items())
            line = f"{' ' * min(depth, 12)}<{el.name}{' ' + a if a else ''}>{own}"
            out.append(line)
            size[0] += len(line) + 1
        # Repeated siblings (product cards, result rows, table rows): show the first few in full,
        # then one summary line - enough to write a selector, a fraction of the tokens.
        shown: Counter = Counter()
        skipped: Counter = Counter()
        for child in kids:
            sig = (child.name, tuple(clean_classes(child.get("class"), 3)))
            if len(kids) > REPEAT_SHOW and shown[sig] >= REPEAT_SHOW:
                skipped[sig] += 1
                continue
            shown[sig] += 1
            walk(child, depth + 1 if meaningful else depth)
        for (tag, cls), n in skipped.items():
            line = f"{' ' * min(depth + 1, 12)}... {n} more <{tag}{' class=' + chr(34) + ' '.join(cls) + chr(34) if cls else ''}> like above"
            out.append(line)
            size[0] += len(line) + 1

    walk(body, 0)
    return "\n".join(out)[:max_chars]


def focus_outline(outline: str, hint: str, max_chars: int = 3000, around: int = 3) -> str:
    """The parts of a page outline that mention the hint, each with its ancestor lines (so a
    selector can still be written) and a few neighbours. '' when nothing matches or the
    outline is already small - then the caller sends the full outline."""
    if len(outline) <= max_chars:
        return ""
    words = hint_words(hint)
    if not words:
        return ""
    lines = outline.split("\n")
    depth = [len(l) - len(l.lstrip(" ")) for l in lines]
    scores = [sum(1 for w in words if w in l.lower()) for l in lines]
    if not any(scores):
        return ""
    keep: set[int] = set()
    size = 0
    for i in sorted(range(len(lines)), key=lambda i: (-scores[i], i)):
        if not scores[i]:
            break
        block = set(range(max(0, i - around), min(len(lines), i + around + 1)))
        d = depth[i]
        for j in range(i - 1, -1, -1):          # ancestors: nearest line above with less indent
            if depth[j] < d:
                block.add(j)
                d = depth[j]
                if d == 0:
                    break
        new = block - keep
        add = sum(len(lines[j]) + 1 for j in new)
        if keep and size + add > max_chars:
            break
        keep |= new
        size += add
    out, last = [], -2
    for j in sorted(keep):
        if j != last + 1:
            out.append("...")
        out.append(lines[j])
        last = j
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


_LOGIN_HINT = re.compile(r"log[ _-]?in|sign[ _-]?in|signin|auth|sso|session", re.I)


def detect_login_wall(html: str, url: str) -> bool:
    """A login form: a visible password box on a page whose URL or title talks about logging in."""
    soup = soup_of(html)
    if not any(not _is_hidden(i) for i in soup.find_all("input", attrs={"type": "password"})):
        return False
    title = soup.title.get_text(" ") if soup.title else ""
    return bool(_LOGIN_HINT.search(f"{url} {title}"))


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
    """Page links (deduplicated by URL). Content links come first; links inside nav / header /
    footer / aside follow, flagged chrome=True, so a cut-off list keeps the useful ones."""
    soup = soup_of(html)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        text = _norm(a.get_text(" ")) or a.get("aria-label", "") or a.get("title", "")
        if url in seen or not text:
            continue
        seen.add(url)
        chrome = a.find_parent(CHROME_TAGS) is not None
        out.append({"text": text[:100], "href": url, "sig": _signature(a), "chrome": chrome})
    return [l for l in out if not l["chrome"]] + [l for l in out if l["chrome"]]


def links_to_offer(items: list[dict], hint: str, limit: int, max_show: int = 80) -> list[dict]:
    """The links worth showing the LLM for "pick the links that match <hint>".
    Each cut only happens while enough links remain (at least 2x the wanted number):
      * nav / header / footer / aside links (chrome),
      * links whose text repeats on the page ("Cited by 12", "Related articles", "Read more")
        unless the hint names them - per-result actions, not results.
    Order is kept (content first), so the result is a prefix-style subset of `items`."""
    enough = max(limit * 2, 10)
    out = items
    content = [l for l in out if not l.get("chrome")]
    if len(content) >= enough:
        out = content
    words = set(hint_words(hint))
    shape = lambda t: re.sub(r"\d[\d,.]*", "#", t.lower()).strip()
    counts = Counter(shape(l["text"]) for l in out)
    kept = [l for l in out if counts[shape(l["text"])] < 3
            or words & set(re.findall(r"[a-z0-9]+", l["text"].lower()))]
    if len(kept) >= enough:
        out = kept
    return out[:max_show]


def result_group(items: list[dict], min_size: int = 3) -> list[dict]:
    """The page's one clear list of repeated content links (search results, product titles):
    the largest group sharing a specific signature, outside nav/header/footer, at least twice as
    big as the next group. [] when there is no clear list."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for l in items:
        if not l.get("chrome") and "." in (l.get("sig") or ""):
            groups[l["sig"]].append(l)
    ranked = sorted(groups.values(), key=len, reverse=True)
    if not ranked or len(ranked[0]) < min_size or (len(ranked) > 1 and len(ranked[0]) < 2 * len(ranked[1])):
        return []
    return ranked[0]


def links_for_prompt(items: list[dict], base_url: str = "") -> str:
    """`[i] text -> /path` (own host and tracking params dropped)."""
    return "\n".join(f"[{i}] {l['text'][:80]} -> {short_url(l['href'], base_url)[:90]}" for i, l in enumerate(items))


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
    """A record block as short HTML for the PATTERN prompt: stable classes only, at most two
    data-* attributes, short URLs, data: URIs and long text cut, whitespace collapsed."""
    el = BeautifulSoup(str(el), "html.parser")
    for t in el.find_all(True):
        keep, data_attrs = {}, 0
        for k, v in t.attrs.items():
            if k == "class":
                cls = clean_classes(v, 3)
                if cls:
                    keep["class"] = cls
            elif k in ("href", "src"):
                v = str(v)
                keep[k] = "data:..." if v.startswith("data:") else short_url(v)[:90]
            elif k in ("id", "alt", "title", "aria-label", "itemprop"):
                keep[k] = str(v)[:80]
            elif k.startswith("data-") and data_attrs < 2 and len(str(v)) <= 60:
                keep[k] = v
                data_attrs += 1
        t.attrs = keep
    for s in el.find_all(string=True):
        if len(s) > 200:
            s.replace_with(s[:200] + "...")
    s = re.sub(r">\s+<", "><", re.sub(r"\s+", " ", str(el)))
    return s[:max_chars]


def next_page_candidates(html: str) -> list[dict]:
    soup = soup_of(html)
    out = []
    for el in soup.find_all(["a", "button", "li", "span"]):
        txt = _norm(el.get_text(" ")).lower()
        bare = re.sub(r"[›»>→\s]+", " ", txt).strip()       # "Next →", "next »" -> "next"
        aria = (el.get("aria-label") or "").lower()
        rel = " ".join(el.get("rel", [])) if el.get("rel") else ""
        cls = " ".join(el.get("class", [])).lower()
        parent_cls = " ".join(el.parent.get("class", [])).lower() if isinstance(el.parent, Tag) else ""
        arrow_only = bare == "" and txt and el.name in ("a", "button")         # a link that is just "»"
        if bare in ("next", "next page") or arrow_only or "next" in aria or rel == "next" \
                or ("next" in cls and el.name in ("a", "button")) \
                or (el.name == "a" and re.search(r"\bnext\b", parent_cls)):     # <li class="next"><a>
            if el.name in ("li", "span") and el.find("a"):
                continue            # the link inside is the clickable one
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
