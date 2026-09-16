"""
Browser Task Fingerprinting.

Converts natural-language task descriptions into stable, comparable fingerprints
for pattern lookup — without using any LLM.

Strategy:
  1. Extract URL domain (if present)  →  "amazon.com"
  2. Tokenize, lowercase, remove stopwords
  3. Keep only action/object keywords
  4. Sort tokens for order-invariance
  5. Combine: "{domain}_{sorted_keywords}"

Example:
  "go to Amazon, check gaming laptop prices and compare"
  → domain: "amazon"
  → keywords: ["check", "compare", "gaming", "laptop", "price"]
  → fingerprint: "amazon_check_compare_gaming_laptop_price"

  "do the same Amazon laptop price check again"
  → domain: "amazon"
  → keywords: ["check", "laptop", "price"]   (subset match)
  → fingerprint: "amazon_check_laptop_price"

  Chroma semantic similarity handles near-matches between these fingerprints.
"""

import hashlib
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Stopwords — removed before fingerprinting
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "up", "about", "into", "through",
    "then", "that", "this", "these", "those", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could",
    "me", "my", "we", "our", "you", "your", "it", "its", "they", "their",
    "he", "she", "him", "her", "i", "am",
    # Task verb noise
    "go", "open", "visit", "navigate", "click", "please", "just", "again",
    "same", "task", "do", "run", "repeat", "want", "need", "get", "tell",
    "give", "show", "make", "let", "try", "use", "back",
    # Ordinal words — normalized separately via extract_task_variables()
    "first", "second", "third", "fourth", "fifth", "top", "nth",
}

# Known action keywords that are worth keeping
_ACTION_KEYWORDS = {
    "search", "find", "check", "compare", "buy", "add", "fill", "select",
    "login", "signup", "submit", "extract", "scrape", "price", "prices",
    "product", "products", "list", "listing", "review", "reviews", "order",
    "cart", "checkout", "form", "category", "filter", "sort", "download",
    "upload", "register", "verify", "confirm", "pay", "book", "schedule",
}


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

def extract_url_domain(task: str) -> str:
    """
    Extract the primary domain name from a task string.

    Examples:
      "go to amazon.com and..."      → "amazon"
      "visit https://www.ebay.com"   → "ebay"
      "go to Amazon"                 → "amazon"
      "search the web"               → ""
    """
    # Try full URL first
    url_match = re.search(
        r"https?://(?:www\.)?([a-zA-Z0-9\-]+)(?:\.[a-zA-Z]{2,})+",
        task,
    )
    if url_match:
        return url_match.group(1).lower()

    # Try "site.com" pattern
    domain_match = re.search(
        r"\b(?:www\.)?([a-zA-Z0-9\-]+)\.(?:com|org|net|io|co|uk|de|fr|jp)\b",
        task,
        re.I,
    )
    if domain_match:
        return domain_match.group(1).lower()

    # Generic heuristic: capitalized word after action verbs likely a site name
    # e.g. "visit Amazon", "go to Flipkart", "open Etsy"
    brand_match = re.search(
        r'\b(?:visit|go\s+to|open|on|at|use|check)\s+([A-Z][a-zA-Z0-9\-]{2,})\b',
        task,
    )
    if brand_match:
        return brand_match.group(1).lower()

    return ""


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def extract_keywords(task: str, domain: str = "") -> list[str]:
    """
    Extract meaningful action/object keywords from a task description.

    Removes stopwords, domain name, and common noise verbs.
    Keeps nouns, action verbs, and product/category words.
    """
    # Lowercase and tokenize
    text = task.lower()

    # Remove URLs
    text = re.sub(r"https?://\S+", " ", text)

    # Remove the domain name itself (already captured separately)
    if domain:
        text = re.sub(rf"\b{re.escape(domain)}\b", " ", text)

    # Tokenize — keep only alphabetic tokens
    tokens = re.findall(r"[a-z]+", text)

    # Filter: remove stopwords, keep length >= 3
    keywords = [
        t for t in tokens
        if t not in _STOPWORDS and len(t) >= 3
    ]

    # Deduplicate preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    return unique


# ---------------------------------------------------------------------------
# Fingerprint generation
# ---------------------------------------------------------------------------

def task_to_fingerprint(task: str) -> str:
    """
    Convert a task description to a stable, comparable fingerprint string.

    Ordinals (first/second/third) are normalized to 'nth' so the same
    base pattern matches regardless of which item the user asks for.
    The actual ordinal is extracted separately via extract_task_variables().

    Returns:
        e.g. "amazon nth price product search"
    """
    domain = extract_url_domain(task)
    # Normalize ordinals before keyword extraction so fingerprint is position-agnostic
    normalized = _normalize_ordinals(task)
    keywords = extract_keywords(normalized, domain)

    # Sort for order-invariance
    sorted_kw = sorted(set(keywords))

    parts = []
    if domain:
        parts.append(domain)
    parts.extend(sorted_kw)

    return " ".join(parts) if parts else task.lower()[:60]


def fingerprint_to_id(fingerprint: str) -> str:
    """
    Convert a fingerprint string to a short stable ID for Chroma + filename.

    Returns:
        e.g. "bwp_a3f2c1d4"
    """
    h = hashlib.sha256(fingerprint.encode()).hexdigest()[:8]
    return f"bwp_{h}"


def tasks_are_similar(task_a: str, task_b: str, threshold: float = 0.5) -> bool:
    """
    Quick heuristic check: do two tasks share enough keywords to be similar?

    Used as a pre-filter before Chroma query.
    Returns True if Jaccard similarity of keyword sets >= threshold.
    """
    kw_a = set(extract_keywords(task_a, extract_url_domain(task_a)))
    kw_b = set(extract_keywords(task_b, extract_url_domain(task_b)))

    if not kw_a or not kw_b:
        return False

    intersection = kw_a & kw_b
    union = kw_a | kw_b
    jaccard = len(intersection) / len(union)
    return jaccard >= threshold


# ---------------------------------------------------------------------------
# Ordinal normalization and variable extraction
# ---------------------------------------------------------------------------

_ORDINAL_MAP = {
    # words → index (1-based)
    "first": 1, "1st": 1, "one": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
    "top": 1,  # "top product" = first
    "last": -1,  # -1 = last item
}

_QUERY_PATTERNS = [
    # "search <query>", "search for <query>", "find <query>"
    r"search\s+(?:for\s+)?['\"]?([a-zA-Z0-9 ]+?)['\"]?\s+(?:on|in|at|and|$)",
    r"search\s+(?:for\s+)?['\"]?([a-zA-Z0-9 ]+)['\"]?",
]


def _normalize_ordinals(task: str) -> str:
    """Replace ordinal words with 'nth' for fingerprint normalization."""
    pattern = r'\b(' + '|'.join(re.escape(k) for k in _ORDINAL_MAP) + r')\b'
    return re.sub(pattern, 'nth', task, flags=re.I)


def extract_task_variables(task: str) -> dict:
    """
    Extract runtime variables from a task description.

    Returns a dict of variables that will be passed to the browser pattern
    as substitution variables, e.g.:
      {"nth": "2", "query": "baby product"}

    This allows ONE saved pattern to serve many variations:
      - "first product price"  → {nth: 1}
      - "second product price" → {nth: 2}
      - "third item"           → {nth: 3}
    """
    variables = {}
    task_lower = task.lower()

    # ── Extract ordinal / position ────────────────────────────────
    for word, idx in _ORDINAL_MAP.items():
        if re.search(rf'\b{re.escape(word)}\b', task_lower):
            variables["nth"] = str(idx)
            break
    if "nth" not in variables:
        variables["nth"] = "1"  # Default to first

    # ── Extract search query ──────────────────────────────────
    for pat in _QUERY_PATTERNS:
        m = re.search(pat, task_lower)
        if m:
            variables["query"] = m.group(1).strip()
            break

    return variables
