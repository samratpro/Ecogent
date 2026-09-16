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

    # Try known brand names mentioned without a TLD
    known_brands = {
        "amazon": "amazon",
        "ebay": "ebay",
        "google": "google",
        "youtube": "youtube",
        "twitter": "twitter",
        "facebook": "facebook",
        "instagram": "instagram",
        "linkedin": "linkedin",
        "reddit": "reddit",
        "github": "github",
        "wikipedia": "wikipedia",
        "netflix": "netflix",
        "spotify": "spotify",
        "aliexpress": "aliexpress",
        "walmart": "walmart",
        "etsy": "etsy",
        "shopify": "shopify",
    }
    task_lower = task.lower()
    for brand, name in known_brands.items():
        if re.search(rf"\b{brand}\b", task_lower):
            return name

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

    The fingerprint is order-invariant and stopword-free.
    Used as the ChromaDB document embedding text and as the JSON filename stem.

    Returns:
        e.g. "amazon check compare laptop price"
    """
    domain = extract_url_domain(task)
    keywords = extract_keywords(task, domain)

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
