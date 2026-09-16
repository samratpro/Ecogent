"""
Built-in Web Tools.

Architecture:
  1. Fetch raw HTML  (stdlib urllib → requests → playwright)
  2. Strip all JS/CSS/tags with stdlib regex → compact readable text
  3. Pass clean text to ask_llm → LLM extracts exactly what's needed
  4. Return structured result

No BeautifulSoup. No brittle selectors. No hardcoded site patterns.
Token cost controlled by slicing clean text before sending to LLM.
"""

import re
import json
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional, Callable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Max chars of clean page text to send to LLM (controls token cost)
_LLM_CONTEXT_LIMIT = 4000


# ---------------------------------------------------------------------------
# Step 1 — Fetch
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: int = 15) -> str:
    """Fetch URL → raw HTML string. stdlib urllib only, no extra deps."""
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            return r.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        if e.code not in (403, 429, 503):
            raise
    # Try requests if urllib blocked
    try:
        import requests as _req
        r = _req.get(url, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except ImportError:
        pass
    # Last resort: playwright
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        pg = b.new_page()
        pg.goto(url, timeout=30000)
        html = pg.content()
        b.close()
    return html


# ---------------------------------------------------------------------------
# Step 2 — Strip HTML → clean text (stdlib regex, no deps)
# ---------------------------------------------------------------------------

# Tags whose entire block (open + content + close) we discard
_BLOCK_TAGS = re.compile(
    r"<(script|style|noscript|svg|iframe|head|nav|footer|header|aside|form)"
    r"[^>]*>.*?</\1>",
    re.S | re.I,
)
# HTML comments
_COMMENTS = re.compile(r"<!--.*?-->", re.S)
# Remaining tags
_TAGS = re.compile(r"<[^>]+>")
# HTML entities (common ones)
_ENTITIES = re.compile(r"&(amp|lt|gt|quot|nbsp|apos|#\d+|#x[0-9a-fA-F]+);")
_ENTITY_MAP = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "nbsp": " ", "apos": "'"}
# Collapse whitespace
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _clean(html: str) -> str:
    """
    Strip all markup, JS, CSS from raw HTML.
    Returns compact readable text with no extra whitespace.
    Pure stdlib — no BeautifulSoup needed.
    """
    text = _BLOCK_TAGS.sub(" ", html)
    text = _COMMENTS.sub(" ", text)
    text = _TAGS.sub(" ", text)

    def _decode_entity(m):
        name = m.group(1)
        if name in _ENTITY_MAP:
            return _ENTITY_MAP[name]
        if name.startswith("#x"):
            return chr(int(name[2:], 16))
        if name.startswith("#"):
            return chr(int(name[1:]))
        return m.group(0)

    text = _ENTITIES.sub(_decode_entity, text)
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Step 3 — LLM extracts structured data from clean text
# ---------------------------------------------------------------------------

def _llm_extract_results(clean_text: str, query: str, ask_llm: Callable) -> list:
    """
    Send a slice of clean page text to ask_llm.
    Ask it to extract the top search result URLs and titles as JSON.
    Token cost = len(clean_text[:_LLM_CONTEXT_LIMIT]) / 4 roughly.
    """
    snippet = clean_text[:_LLM_CONTEXT_LIMIT]
    prompt = (
        f"This is text scraped from a search results page for query: '{query}'.\n"
        f"Extract the top organic search results (title and URL only).\n"
        f"Respond with a JSON array: "
        f'[{{"title": "...", "url": "https://..."}}, ...]\n'
        f"Output ONLY the JSON array. No extra text.\n\n"
        f"Page text:\n{snippet}"
    )
    try:
        raw = ask_llm(prompt)
        # Try to find a JSON array in the response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        else:
            raw = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
            
        data = json.loads(raw)
        if isinstance(data, list):
            return [r for r in data if r.get("url", "").startswith("http")]
    except Exception:
        pass
    return []


def _llm_parse_intent(task: str, ask_llm: Callable) -> dict:
    """
    Ask LLM to parse the user's natural language task into:
      {action: "search"|"browse", query: str, url: str, engine: "bing"|"google"}
    """
    prompt = (
        "Parse this web task into JSON with keys: "
        '"action" (search or browse), "query" (search terms), '
        '"url" (if browse), "engine" (bing or google, default bing).\n'
        "Output ONLY the JSON object.\n\n"
        f"Task: {task}"
    )
    try:
        raw = ask_llm(prompt)
        raw = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
        return json.loads(raw)
    except Exception:
        return {}


def _heuristic_intent(task: str) -> dict:
    """Fallback intent extraction when ask_llm is unavailable."""
    t = task.lower()
    url_m = re.search(r"https?://\S+", task)
    if url_m:
        return {"action": "browse", "url": url_m.group(0)}
    engine = "google" if "google" in t else "bing"
    # Strip all verb/site words, keep the rest as query
    query = re.sub(
        r"\b(go to|open|search|find|look up|browse|visit|use|on|with|for|"
        r"the|web|internet|bing|google|and tell.*|and show.*)\b",
        " ", t, flags=re.I,
    )
    query = re.sub(r"\s{2,}", " ", query).strip() or task
    return {"action": "search", "query": query, "engine": engine}


def _search_url(query: str, engine: str) -> str:
    q = urllib.parse.quote_plus(query)
    if engine == "google":
        return f"https://www.google.com/search?q={q}"
    elif engine == "duckduckgo":
        return f"https://html.duckduckgo.com/html/?q={q}"
    else:
        # Fallback to DDG if bing is requested, since Bing serves honeypots
        return f"https://html.duckduckgo.com/html/?q={q}"


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def web_search(
    query: Optional[str] = None,
    task: Optional[str] = None,
    engine: str = "bing",
    ask_llm: Optional[Callable] = None,
    **kwargs,
) -> dict:
    """
    Search the web and return top results.

    Flow:
      ask_llm parses intent → fetch → strip HTML → ask_llm extracts results

    Args:
        query:   Explicit search query (skips intent parsing).
        task:    Natural-language task description.
        engine:  Fallback engine if LLM doesn't specify ('bing'|'google').
        ask_llm: LLM callback injected by the executor.

    Returns:
        {success, query, engine, results[{title,url}], top_result, preview}
    """
    # --- Resolve intent ---
    if query:
        intent = {"action": "search", "query": query, "engine": engine}
    elif task:
        intent = _llm_parse_intent(task, ask_llm) if ask_llm else _heuristic_intent(task)
        if not intent:
            intent = _heuristic_intent(task)
    else:
        return {"success": False, "error": "No query or task provided.", "results": []}

    if intent.get("action") == "browse" and intent.get("url"):
        return browse_website(url=intent["url"], ask_llm=ask_llm)

    search_query = intent.get("query") or task or ""
    chosen_engine = intent.get("engine", engine)
    url = _search_url(search_query, chosen_engine)

    # --- Fetch ---
    try:
        html = _fetch(url)
    except Exception as e:
        return {"success": False, "error": f"Fetch failed: {e}", "results": [], "query": search_query}

    # --- Strip HTML → clean text ---
    clean = _clean(html)

    # --- LLM extracts results from clean text (token-efficient) ---
    results = []
    if ask_llm:
        results = _llm_extract_results(clean, search_query, ask_llm)

    if not results:
        # No LLM or LLM returned nothing — return the clean text slice as preview
        preview = clean[:2000]
        return {
            "success": True,
            "query": search_query,
            "engine": chosen_engine,
            "results": [],
            "preview": preview,
            "message": "Fetched page. No structured results extracted (ask_llm unavailable or failed).",
        }

    preview_lines = [f"{i}. {r['title']}\n   {r['url']}" for i, r in enumerate(results[:10], 1)]
    return {
        "success": True,
        "query": search_query,
        "engine": chosen_engine,
        "results": results,
        "top_result": results[0],
        "preview": "\n".join(preview_lines),
        "message": f"Found {len(results)} results for '{search_query}'.",
    }


def browse_website(
    url: Optional[str] = None,
    task: Optional[str] = None,
    ask_llm: Optional[Callable] = None,
    **kwargs,
) -> dict:
    """
    Fetch a URL, strip markup, return clean text (and optionally ask LLM to summarize).

    Flow:
      resolve URL → fetch → strip HTML → return clean text
      (ask_llm can summarize if needed, but raw clean text is returned for token efficiency)

    Args:
        url:     Explicit URL.
        task:    Natural-language task; URL extracted via ask_llm or regex.
        ask_llm: LLM callback injected by the executor.

    Returns:
        {success, url, content, preview}
    """
    target_url = url

    if not target_url and task:
        if ask_llm:
            intent = _llm_parse_intent(task, ask_llm)
            target_url = intent.get("url")
            if not target_url and intent.get("action") == "search":
                return web_search(task=task, ask_llm=ask_llm)
        if not target_url:
            m = re.search(r"https?://\S+", task or "")
            target_url = m.group(0) if m else None

    if not target_url:
        return {"success": False, "error": "No URL found."}

    try:
        html = _fetch(target_url)
    except Exception as e:
        return {"success": False, "url": target_url, "error": str(e)}

    clean = _clean(html)
    preview = clean[:2000] + ("..." if len(clean) > 2000 else "")
    return {
        "success": True,
        "url": target_url,
        "content": clean,
        "preview": preview,
        "message": f"Fetched and cleaned {target_url} ({len(clean)} chars of readable text)",
    }


# Alias
browser_scrape = browse_website
