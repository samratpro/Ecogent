"""
Summarize drift benchmark CSVs (markdown, ready for notes or a paper draft):

  1. variant x drift level x phase: success %, precision, recall, LLM calls, tokens, USD, seconds
     (mean ± sample sd) and a 95% bootstrap confidence interval of the mean cost
  2. paired comparison of a reference variant (default: ecogent) against every other variant on the
     same (task, seed, repeat, level) reruns: Wilcoxon signed-rank test on cost, exact binomial
     (McNemar-style) test on success
  3. total cost of ownership: cumulative cost over the run sequence cold -> rerun at level 0..4, its
     cost per successful run, and the break-even run index against the no-reuse baseline (nocache)
  4. optional per-task tables

    python bench/summarize.py bench/results/main.csv [more.csv ...] [--by-task] [--ref ecogent] [--out summary.md]

Cost = USD when every row is priced, otherwise input+output tokens (the header says which).
"""

from __future__ import annotations

import argparse
import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

PHASE_ORDER = {"cold": 0, "rerun": 1, "rerun2": 2}
FORMATS = {"ratio": "{:.2f}", "count": "{:.1f}", "tokens": "{:,.0f}", "usd": "{:.5f}", "seconds": "{:.1f}"}


def num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ms(values: list, kind: str) -> str:
    """mean ± sample standard deviation in the column's format."""
    vals = [v for v in values if v is not None]
    if not vals:
        return "-"
    f = FORMATS[kind]
    sd = st.stdev(vals) if len(vals) > 1 else 0.0
    return f"{f.format(st.mean(vals))} ± {f.format(sd)}"


def boot_ci(values: list, kind: str, n: int = 2000) -> str:
    """95% percentile bootstrap confidence interval of the mean (fixed seed: reproducible)."""
    vals = np.array([v for v in values if v is not None], dtype=float)
    if len(vals) < 2:
        return "-"
    rng = np.random.default_rng(0)
    means = vals[rng.integers(0, len(vals), size=(n, len(vals)))].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    f = FORMATS[kind]
    return f"[{f.format(lo)}, {f.format(hi)}]"


def sort_key(k: tuple) -> tuple:
    """Phases in protocol order, levels numerically, names alphabetically."""
    return tuple((0, PHASE_ORDER[x], "") if x in PHASE_ORDER else (1, int(x), "") if str(x).isdigit() else (2, 0, x)
                 for x in k)


def add_cost(rows: list[dict]) -> tuple[str, str]:
    priced = all(r.get("cost_usd") not in ("", None) for r in rows)
    for r in rows:
        r["_cost"] = num(r["cost_usd"]) if priced else (num(r["input_tokens"]) or 0) + (num(r["output_tokens"]) or 0)
        r.setdefault("repeat", "1")
        r["repeat"] = r["repeat"] or "1"
    return ("USD", "usd") if priced else ("tokens (in+out)", "tokens")


# ----------------------------------------------------------------------------- 1. main table
def table(rows: list[dict], keys: tuple, cost_kind: str) -> str:
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in keys)].append(r)
    head = [*keys, "n", "success %", "precision", "recall", "LLM calls", "input tok", "output tok", "cost",
            "cost 95% CI", "seconds"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for k in sorted(groups, key=sort_key):
        g = groups[k]
        col = lambda name, kind: ms([num(r[name]) for r in g], kind)   # noqa: E731
        succ = 100 * sum(int(r["success"]) for r in g) / len(g)
        costs = [r["_cost"] for r in g]
        out.append("| " + " | ".join([*map(str, k), str(len(g)), f"{succ:.0f}", col("precision", "ratio"),
                                       col("recall", "ratio"), col("calls", "count"), col("input_tokens", "tokens"),
                                       col("output_tokens", "tokens"), ms(costs, cost_kind),
                                       boot_ci(costs, cost_kind), col("seconds", "seconds")]) + " |")
    return "\n".join(out)


# ----------------------------------------------------------------------------- 2. paired tests
def paired(rows: list[dict], ref: str, cost_kind: str) -> str:
    from scipy import stats
    by = {(r["variant"], r["task"], r["seed"], r["repeat"], r["level"]): r for r in rows if r["phase"] == "rerun"}
    variants = sorted({r["variant"] for r in rows} - {ref})
    levels = sorted({r["level"] for r in rows if r["phase"] == "rerun"}, key=int)
    head = ["vs", "level", "pairs", f"{ref} cost", "other cost", "mean diff", "p (Wilcoxon)",
            f"{ref} success %", "other success %", "p (success)"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    f = FORMATS[cost_kind]
    for v in variants:
        for lv in levels:
            pairs = [(by[k], by[(v, *k[1:])]) for k in by if k[0] == ref and k[4] == lv and (v, *k[1:]) in by]
            if not pairs:
                continue
            a = np.array([p[0]["_cost"] for p in pairs], dtype=float)
            b = np.array([p[1]["_cost"] for p in pairs], dtype=float)
            d = a - b
            p_cost = "-"
            if len(pairs) >= 5 and np.any(d != 0):
                p_cost = f"{stats.wilcoxon(a, b, zero_method='zsplit').pvalue:.4f}"
            sa = [int(p[0]["success"]) for p in pairs]
            sb = [int(p[1]["success"]) for p in pairs]
            only_a = sum(1 for x, y in zip(sa, sb) if x and not y)
            only_b = sum(1 for x, y in zip(sa, sb) if y and not x)
            p_succ = f"{stats.binomtest(only_a, only_a + only_b, 0.5).pvalue:.4f}" if only_a + only_b else "1.0000"
            out.append("| " + " | ".join([v, lv, str(len(pairs)), f.format(a.mean()), f.format(b.mean()),
                                           f.format(d.mean()), p_cost, f"{100 * np.mean(sa):.0f}",
                                           f"{100 * np.mean(sb):.0f}", p_succ]) + " |")
    out.append("")
    out.append("p (Wilcoxon): paired signed-rank test on cost (shown for >= 5 pairs). p (success): exact binomial test "
               "on the pairs where only one variant succeeded. Small p (< 0.05) = the difference is unlikely to be chance.")
    return "\n".join(out)


# ----------------------------------------------------------------------------- 3. total cost
def lifetime(rows: list[dict], cost_kind: str, baseline: str = "nocache") -> str:
    seqs = defaultdict(list)          # (variant, task, seed, repeat) -> [(order, cost, success)]
    for r in rows:
        if r["phase"] == "cold":
            order = -1
        elif r["phase"] == "rerun":
            order = int(r["level"])
        else:
            continue
        seqs[(r["variant"], r["task"], r["seed"], r["repeat"])].append((order, r["_cost"], int(r["success"])))
    per_variant = defaultdict(list)
    for (v, *_), seq in seqs.items():
        seq.sort()
        per_variant[v].append(seq)
    if not per_variant:
        return "(no data)"
    f = FORMATS[cost_kind]
    head = ["variant", "units", "runs per unit", "total cost (mean)", "successful runs (mean)",
            "cost per successful run", "cumulative cost by run (cold, L0, L1, ...)"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    curves = {}
    for v in sorted(per_variant):
        units = [s for s in per_variant[v] if len(s) == max(len(x) for x in per_variant[v])]
        if not units:
            continue
        costs = np.array([[c for _, c, _ in s] for s in units], dtype=float)
        succ = np.array([[ok for _, _, ok in s] for s in units], dtype=float)
        cum = costs.cumsum(axis=1).mean(axis=0)
        curves[v] = cum
        total, wins = costs.sum(axis=1).mean(), succ.sum(axis=1).mean()
        out.append("| " + " | ".join([v, str(len(units)), str(costs.shape[1]), f.format(total), f"{wins:.2f}",
                                       f.format(total / wins) if wins else "-",
                                       ", ".join(f.format(x) for x in cum)]) + " |")
    out.append("")
    if baseline in curves:
        for v, cum in curves.items():
            if v == baseline:
                continue
            base = curves[baseline][:len(cum)]
            idx = next((i for i in range(len(cum)) if cum[i] < base[i] and all(cum[j] < base[j]
                                                                                 for j in range(i, len(cum)))), None)
            label = "never within this sequence" if idx is None else f"from run {idx + 1} on (break-even)"
            out.append(f"- **{v}** costs less in total than **{baseline}** {label}; "
                       f"after {len(cum)} runs: {f.format(cum[-1])} vs {f.format(base[-1])}.")
    out.append("")
    out.append("A unit = one task x seed x repeat. Sequence = cold run, then one rerun per drift level in order. "
               "The protocol restores the compiled plan before each level, so this approximates a deployment where "
               "changes accumulate; it is not a simulation of one.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--by-task", action="store_true", help="also one table per task")
    ap.add_argument("--ref", default="ecogent", help="reference variant for the paired tests")
    ap.add_argument("--out", default="", help="write the markdown here as well")
    args = ap.parse_args()
    rows = []
    for p in args.csv:
        with open(p, encoding="utf-8", newline="") as f:
            rows += list(csv.DictReader(f))
    if not rows:
        raise SystemExit("no rows")
    cost_label, cost_kind = add_cost(rows)
    models = ", ".join(sorted({r["main_model"] for r in rows}))
    cheap = ", ".join(sorted({r["cheap_model"] for r in rows if r.get("cheap_model")}))
    parts = ["# Drift benchmark summary", "",
             f"{len(rows)} runs; tasks: {len({r['task'] for r in rows})}; cost unit: **{cost_label}**; "
             f"models: {models}" + (f" (cheap: {cheap})" if cheap else ""), "",
             "## 1. All tasks: variant x drift level x phase", "", table(rows, ("variant", "level", "phase"), cost_kind)]
    if any(r["variant"] == args.ref for r in rows) and len({r["variant"] for r in rows}) > 1:
        parts += ["", f"## 2. Paired comparison: {args.ref} vs each variant (reruns)", "", paired(rows, args.ref, cost_kind)]
    parts += ["", "## 3. Total cost of ownership", "", lifetime(rows, cost_kind)]
    if args.by_task:
        for t in sorted({r["task"] for r in rows}):
            parts += ["", f"## Task: {t}", "",
                      table([r for r in rows if r["task"] == t], ("variant", "level", "phase"), cost_kind)]
    md = "\n".join(parts)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # "±" on Windows consoles
    print(md)
    if args.out:
        Path(args.out).write_text(md + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
