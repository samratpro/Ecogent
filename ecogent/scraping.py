"""
Scraping with a reusable "programmatic pattern".

1. The LLM sees only a few repeated blocks and returns CSS selectors (the pattern).
2. Python applies the pattern, takes a 10-20 record sample and the LLM validates it.
3. On a bad sample the pattern is healed; then the user confirms the sample.
4. Python scrapes every page with the confirmed pattern (no more LLM calls).
5. The pattern + validation stats live in plan.json, so a rerun reuses it for free and
   only heals it when validation fails.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional
from urllib.parse import urljoin

from . import page_reader as pr
from . import prompts
from .output import write_rows

if TYPE_CHECKING:
    from .executor import Executor


def apply_pattern(pattern: dict, html: str, base_url: str) -> list[dict]:
    soup = pr.soup_of(html)
    try:
        items = soup.select(pattern.get("item_selector", "")) if pattern.get("item_selector") else []
    except Exception:
        return []
    rows = []
    for it in items:
        row = {}
        for name, f in (pattern.get("fields") or {}).items():
            f = f if isinstance(f, dict) else {"selector": str(f), "attr": "text"}
            sel, attr = f.get("selector") or "", f.get("attr") or "text"
            try:
                els = (it.select(sel) if f.get("many") else [it.select_one(sel)]) if sel else [it]
            except Exception:
                els = []
            vals = []
            for el in els:
                if el is None:
                    continue
                if attr == "text":
                    val = pr._norm(el.get_text(" "))
                else:
                    v = el.get(attr, "")
                    val = " ".join(v) if isinstance(v, list) else str(v)
                    if attr in ("href", "src") and val:
                        val = urljoin(base_url, val)
                if val:
                    vals.append(val)
            row[name] = ", ".join(vals)     # "many" fields (tags, authors) keep every value
        if any(row.values()):
            rows.append(row)
    return rows


def apply_filters(rows: list[dict], filters: list[dict]) -> list[dict]:
    if not filters:
        return rows
    out = []
    for r in rows:
        keep = True
        for flt in filters:
            field, op, want = flt.get("field"), flt.get("op", "=="), flt.get("value")
            have = str(r.get(field, ""))
            if op in ("<", "<=", ">", ">="):
                a, b = pr.parse_number(have), pr.parse_number(str(want))
                if a is None or b is None:
                    keep = False
                else:
                    keep = {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
            elif op == "contains":
                keep = str(want).lower() in have.lower()
            elif op == "not_contains":
                keep = str(want).lower() not in have.lower()
            elif op == "!=":
                keep = have.strip().lower() != str(want).strip().lower()
            else:
                keep = have.strip().lower() == str(want).strip().lower()
            if not keep:
                break
        if keep:
            out.append(r)
    return out


def fill_rates(rows: list[dict]) -> dict:
    if not rows:
        return {}
    return {k: round(sum(1 for r in rows if r.get(k)) / len(rows), 2) for k in rows[0]}


class ScrapeEngine:
    def __init__(self, ex: "Executor"):
        self.ex = ex
        self.spec = ex.plan.get("scrape", {}) or {}

    def log(self, text: str) -> None:
        self.ex.log(text)

    # ------------------------------------------------------------------ main
    def run(self, step: dict, key: str) -> int:
        ex, b = self.ex, self.ex.browser
        html, url = b.html(), b.url
        pattern = ex.plan.get("pattern")
        need_build = True
        if pattern:
            rows = apply_pattern(pattern, html, url)
            if pattern.get("confirmed") and self._still_valid(pattern, rows):
                ex.stats.cache_hits += 1
                self.log(f"Reusing confirmed scraping pattern ({len(rows)} records on this page)")
                need_build = False
            else:
                self.log("Stored pattern failed validation; healing it")

        feedback, user_rounds, llm_rejects = "", 0, 0
        budget = ex.settings.max_heal_attempts + 2      # pattern LLM calls per run, across step retries
        hint = step.get("item_selector") or ""
        while need_build:
            ex.check_stop()
            if ex.pattern_calls >= budget or user_rounds > 3:
                from .executor import NoHeal
                raise NoHeal(f"could not build a working scraping pattern after {ex.pattern_calls} tries: {feedback}")
            ex.pattern_calls += 1
            pattern = self.build(html, url, feedback, pattern, hint)
            rows = apply_pattern(pattern, html, url)
            if not rows:
                feedback = f"item_selector '{pattern.get('item_selector')}' matched 0 records with values."
                self.log(f"Pattern rejected: {feedback}")
                continue
            # Free checks first: only ask the LLM to validate a sample that is structurally sane.
            problems = self.local_problems(pattern, rows)
            if problems:
                feedback = problems
                self.log(f"Pattern rejected: {feedback}")
                continue
            filtered = apply_filters(rows, self.spec.get("filters", []))
            sample = (filtered or rows)[: ex.settings.scrape_sample_size]
            unfiltered = bool(self.spec.get("filters")) and not filtered
            verdict = self.validate(sample, unfiltered) if llm_rejects < 2 else {"ok": True}
            if not verdict.get("ok", True) and ex.pattern_calls < budget:
                llm_rejects += 1
                feedback = verdict.get("problems", "sample does not match the request")
                self.log(f"Sample rejected by LLM: {feedback}")
                continue
            sample_path = write_rows(sample, ex.session.output_dir / "sample.csv")
            self.log(f"Sample of {len(sample)} records saved: {sample_path}")
            ok, comment = ex.ui.confirm_sample(ex.chat_id, sample,
                                               note=f"{len(rows)} records found on this page. Is the data correct?")
            if ok:
                pattern["confirmed"] = True
                pattern["validation"] = {"fill_rates": fill_rates(rows), "min_items": max(1, len(rows) // 2)}
                ex.plan["pattern"] = pattern
                ex.save_plan()
                need_build = False
            else:
                user_rounds += 1
                feedback = f"User feedback on the sample: {comment or 'data is not correct'}"

        records = self.scrape_all(pattern)
        ex.vars["records"] = records
        path = ex.session.ensure_temp() / "records.json"
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        ex.data()["records_file"] = str(path)
        ex.data()["records_count"] = len(records)
        ex.save_plan()
        self.log(f"Scraped {len(records)} records")
        return len(records)

    def local_problems(self, pattern: dict, rows: list[dict]) -> str:
        """Structural problems found without the LLM (empty fields, whole-card text, missing fields)."""
        out = []
        wanted = [f.get("name") for f in self.spec.get("fields", []) if isinstance(f, dict) and f.get("name")]
        missing = [w for w in wanted if w not in (pattern.get("fields") or {})]
        if missing:
            out.append(f"pattern has no selector for fields {missing}; use exactly these field names")
        rates = fill_rates(rows)
        empty = [k for k, r in rates.items() if r == 0]
        if empty:
            out.append(f"fields {empty} are empty in every record: their selectors match nothing inside the item")
        for name, f in (pattern.get("fields") or {}).items():
            vals = [str(r.get(name, "")) for r in rows[:20] if r.get(name)]
            if vals and sum(len(v) for v in vals) / len(vals) > 300:
                out.append(f"field '{name}' contains the whole block text (avg {sum(len(v) for v in vals) // len(vals)} "
                           "chars); select the specific child element instead")
        return "; ".join(out)

    def _still_valid(self, pattern: dict, rows: list[dict]) -> bool:
        v = pattern.get("validation") or {}
        if len(rows) < min(v.get("min_items", 1), 3):
            return False
        now = fill_rates(rows)
        return all(now.get(k, 0) >= rate * 0.6 - 0.05 for k, rate in v.get("fill_rates", {}).items())

    # ------------------------------------------------------------------ LLM parts
    def build(self, html: str, url: str, feedback: str, previous: Optional[dict], hint: str = "") -> dict:
        # Rebuilds only need a smaller sample: the LLM already saw the structure once.
        groups = pr.repeating_groups(html, sample_chars=1500 if previous and feedback else 2500)
        nexts = pr.next_page_candidates(html)
        self.ex.stats.llm_lookups += 1
        msg = [
            f"Goal: {self.ex.plan.get('goal', '')}",
            f"Fields wanted: {json.dumps(self.spec.get('fields', []), ensure_ascii=False)}",
            f"Page: {url}",
            "Repeated blocks found on the page (selector, count, first block):",
        ]
        for g in groups:
            msg.append(f"- {g['selector']} x{g['count']}\n{g['sample_html']}")
        if not groups:
            msg.append(pr.page_outline(html, self.ex.settings.max_page_chars))
        msg.append(f"Next-page candidates: {json.dumps(nexts, ensure_ascii=False)}")
        if hint:
            msg.append(f"Planner's guess for item_selector (verify against the blocks above): {hint}")
        if previous:
            msg.append(f"Previous pattern: {json.dumps({k: previous.get(k) for k in ('item_selector', 'fields', 'pagination', 'next_selector')})}")
        if feedback:
            msg.append(f"Problem to fix: {feedback}")
        ans = self.ex.llm.ask_json("pattern", prompts.PATTERN, "\n".join(msg), max_tokens=1200)
        return ans if isinstance(ans, dict) else {}

    def validate(self, sample: list[dict], unfiltered: bool = False) -> dict:
        trimmed = [{k: (str(v)[:120] + "…" if len(str(v)) > 120 else str(v)) for k, v in r.items()} for r in sample[:8]]
        note = ("No record on this page passes the filters, so this sample is UNFILTERED: judge only whether the "
                "fields are extracted correctly, not the filter.\n") if unfiltered else ""
        try:
            ans = self.ex.llm.ask_json(
                "validate", prompts.VALIDATE,
                f"Goal: {self.ex.plan.get('goal', '')}\nFields: {json.dumps(self.spec.get('fields', []))}\n"
                f"Filters: {json.dumps(self.spec.get('filters', []))}\n{note}Sample:\n{json.dumps(trimmed, ensure_ascii=False)}",
                max_tokens=300)
            return ans if isinstance(ans, dict) else {"ok": True}
        except Exception as e:
            self.log(f"LLM validation skipped: {e}")
            return {"ok": True}

    # ------------------------------------------------------------------ full run
    def scrape_all(self, pattern: dict) -> list[dict]:
        ex, b = self.ex, self.ex.browser
        max_items = int(self.spec.get("max_items") or 200)
        max_pages = int(self.spec.get("max_pages") or 10)
        records, seen, seen_all = [], set(), set()
        for page_no in range(1, max_pages + 1):
            ex.check_stop()
            raw = apply_pattern(pattern, b.html(), b.url)
            rows = apply_filters(raw, self.spec.get("filters", []))
            new = 0
            for r in rows:
                k = json.dumps(r, sort_keys=True)
                if k not in seen:
                    seen.add(k)
                    records.append(r)
                    new += 1
            # "Pages ran out" is judged on ALL records, not the filtered ones: a page where every
            # item fails the filter (all over $50) must not stop the scrape before later pages.
            fresh = 0
            for r in raw:
                k = json.dumps(r, sort_keys=True)
                if k not in seen_all:
                    seen_all.add(k)
                    fresh += 1
            ex.ui.emit("status", ex.chat_id, text=f"Scraping page {page_no}: {len(records)} records")
            self.log(f"Page {page_no}: {new} new records (total {len(records)})")
            if len(records) >= max_items or (page_no > 1 and fresh == 0):
                break
            mode, sel = pattern.get("pagination", "none"), pattern.get("next_selector") or ""
            if mode == "none" and max_pages > 1 and pr.next_page_candidates(b.html()):
                # The user asked for several pages and the page has a Next link: follow it even if
                # the pattern said "none" (models often miss it).
                mode = "next"
            if mode == "next" and (not sel or not b.exists(sel)):
                # The stored selector may name one page ('a[href="page-2.html"]') and be gone on the
                # next page: find this page's own Next link locally (rel=next, "Next", class next).
                for c in pr.next_page_candidates(b.html()):
                    if b.exists(c["selector"]):
                        if sel:
                            self.log(f"Stored next-page selector not on page {page_no}; using {c['selector']}")
                        sel = c["selector"]
                        break
            if mode == "scroll":
                b.scroll(3)
                self._wait_for_new(pattern, raw)
            elif mode == "next" and sel and b.exists(sel):
                try:
                    b.click(sel)
                except Exception as e:
                    self.log(f"Next page failed: {e}")
                    break
                self._wait_for_new(pattern, raw)
                if ex._wait_out_blocker() and not ex.ui.hold(ex.chat_id, "Captcha on the next page. Solve it, then Continue."):
                    break
            else:
                break
        return records[:max_items]

    def _wait_for_new(self, pattern: dict, before: list[dict], timeout_s: float = 6.0) -> None:
        """After Next / scroll, wait until the records differ from the last page: JS-driven
        pagination updates the list after the click returns, and reading too early would end
        the scrape (no new records). Plain page loads pass at the first check."""
        b = self.ex.browser
        old = json.dumps(before[:5], sort_keys=True)
        old_n = len(before)
        waited = 0.0
        while waited < timeout_s:
            now = apply_pattern(pattern, b.html(), b.url)
            if json.dumps(now[:5], sort_keys=True) != old or len(now) != old_n:
                return
            b.page.wait_for_timeout(500)
            waited += 0.5
