"""
Paper figures from drift benchmark CSVs, as standalone SVG files (no plotting library needed):

  fig1_rerun_cost.svg     mean rerun cost per drift level, one line per system, 95% bootstrap CI whiskers
  fig2_success.svg        rerun success rate per drift level, one line per system
  fig3_cumulative.svg     cumulative cost over the run sequence (cold, L0..L4): the break-even picture
  fig4_ablations.svg      mean rerun cost at levels 1-4 per ablation (single hue), success % as labels

    python bench/plot.py bench/results/main.csv [ablations.csv ...] --out bench/results/figures

Design: one fixed colour + marker shape per system in every figure (validated categorical palette,
light surface, CVD-safe on adjacent pairs); lighter colours are always paired with a direct label
and a distinct marker shape; one y-axis per chart starting at 0; recessive grid. The numbers behind
every figure are in summarize.py's tables.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench.summarize import add_cost                  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
# Fixed entity -> (colour, marker); never re-assigned by rank or filter. Unknown systems fold into "other".
SYSTEMS = {
    "ecogent": ("#2a78d6", "circle", "Ecogent"),
    "nocache": ("#eb6834", "square", "No reuse"),
    "compile_only": ("#1baf7a", "triangle", "Compile only"),
    "no_cheap": ("#eda100", "diamond", "Ecogent, no cheap model"),
    "browser_use": ("#e87ba4", "circle", "browser-use"),
    "stagehand": ("#008300", "square", "Stagehand"),
    "other": ("#8a8984", "triangle", "Other"),
}
MAIN = ["ecogent", "compile_only", "nocache", "no_cheap", "browser_use", "stagehand"]
ABLATION_LABELS = {"ecogent": "Ecogent (full)", "no_identity": "without identity check",
                   "no_alternates": "without alternate locators", "no_refind": "without local re-find",
                   "no_obvious": "without obvious-pick", "no_graded": "without graded LLM views",
                   "no_cheap": "without cheap model", "no_repair": "without any repair"}
W, H = 600, 360
ML, MR, MT, MB = 70, 150, 64, 52


def esc(s) -> str:
    return html.escape(str(s), quote=True)


_DECIMALS = {"value": 2}


def nice_max(v: float, ticks: int = 4) -> tuple[float, float]:
    """A round tick step first (1, 2, 2.5 or 5 x 10^k), then the axis top as a whole number of steps."""
    if v <= 0:
        return 1.0, 0.25
    raw = v / ticks
    exp = 10 ** math.floor(math.log10(raw))
    step = next(m * exp for m in (1, 2, 2.5, 5, 10) if raw <= m * exp + 1e-15)
    _DECIMALS["value"] = max(0, -math.floor(math.log10(step)) + (1 if round(step / exp, 2) == 2.5 else 0))
    return step * math.ceil(v / step - 1e-9), step


def fmt(v: float, unit: str, decimals: int | None = None) -> str:
    d = _DECIMALS["value"] if decimals is None else decimals
    if unit == "USD":
        return f"${v:.{d}f}"
    if unit == "%":
        return f"{v:.0f}%"
    return f"{v / 1000:.{max(0, d - 3)}f}k" if v >= 1000 else f"{v:.0f}"


def marker(shape: str, x: float, y: float, color: str, r: float = 4.5) -> str:
    ring = f'stroke="{SURFACE}" stroke-width="2" fill="{color}"'
    if shape == "square":
        return f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" rx="1" {ring}/>'
    if shape == "triangle":
        pts = f"{x:.1f},{y - r - 1:.1f} {x + r + 0.5:.1f},{y + r:.1f} {x - r - 0.5:.1f},{y + r:.1f}"
        return f'<polygon points="{pts}" {ring}/>'
    if shape == "diamond":
        pts = f"{x:.1f},{y - r - 1:.1f} {x + r + 1:.1f},{y:.1f} {x:.1f},{y + r + 1:.1f} {x - r - 1:.1f},{y:.1f}"
        return f'<polygon points="{pts}" {ring}/>'
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" {ring}/>'


def frame(title: str, desc: str, ylabel: str, xlabel: str, xticks: list[str], ymax: float, ystep: float,
          unit: str) -> tuple[list[str], callable, callable]:
    pw, ph = W - ML - MR, H - MT - MB
    xs = lambda i: ML + (pw * (i + 0.5) / len(xticks))           # noqa: E731
    ys = lambda v: MT + ph - ph * (v / ymax if ymax else 0)       # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
           f'<title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>',
           f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
           f'<text x="{ML}" y="22" font-size="14" font-weight="600" fill="{INK}">{esc(title)}</text>']
    v = 0.0
    while v <= ymax + 1e-12:
        y = ys(v)
        out.append(f'<line x1="{ML}" x2="{W - MR}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{ML - 8}" y="{y + 4:.1f}" font-size="11" fill="{INK2}" text-anchor="end">{esc(fmt(v, unit))}</text>')
        v += ystep
    for i, t in enumerate(xticks):
        out.append(f'<text x="{xs(i):.1f}" y="{H - MB + 18}" font-size="11" fill="{INK2}" text-anchor="middle">{esc(t)}</text>')
    out.append(f'<text x="{ML + pw / 2:.1f}" y="{H - 10}" font-size="11" fill="{INK2}" text-anchor="middle">{esc(xlabel)}</text>')
    out.append(f'<text transform="translate(16,{MT + ph / 2:.1f}) rotate(-90)" font-size="11" fill="{INK2}" '
               f'text-anchor="middle">{esc(ylabel)}</text>')
    return out, xs, ys


def legend(out: list[str], systems: list[str]) -> None:
    x = ML
    for s in systems:
        color, shape, name = SYSTEMS.get(s, SYSTEMS["other"])
        out.append(marker(shape, x + 5, 42, color))
        out.append(f'<text x="{x + 15}" y="46" font-size="11" fill="{INK2}">{esc(name)}</text>')
        x += 24 + 6.2 * len(name)


def lines_chart(path: Path, title: str, desc: str, ylabel: str, xlabel: str, xticks: list[str],
                series: dict[str, list], unit: str, ci: dict[str, list] | None = None) -> None:
    """series: system -> list of values (None = missing) aligned with xticks; ci: system -> [(lo, hi)]."""
    top = max([v for vals in series.values() for v in vals if v is not None] +
              [hi for b in (ci or {}).values() for _, hi in b if hi is not None] + [0])
    ymax, ystep = (100.0, 25.0) if unit == "%" else nice_max(top * 1.05)
    out, xs, ys = frame(title, desc, ylabel, xlabel, xticks, ymax, ystep, unit)
    systems = [s for s in MAIN if s in series] + sorted(s for s in series if s not in MAIN)
    legend(out, systems)
    ends = []
    for s in reversed(systems):             # the reference system (Ecogent) is drawn last, on top
        color, shape, name = SYSTEMS.get(s, SYSTEMS["other"])
        pts = [(xs(i), ys(v)) for i, v in enumerate(series[s]) if v is not None]
        if ci and s in ci:
            for i, (lo, hi) in enumerate(ci[s]):
                if lo is None:
                    continue
                x = xs(i)
                out.append(f'<path d="M{x:.1f},{ys(lo):.1f}V{ys(hi):.1f}M{x - 3:.1f},{ys(lo):.1f}H{x + 3:.1f}'
                           f'M{x - 3:.1f},{ys(hi):.1f}H{x + 3:.1f}" stroke="{color}" stroke-width="1" fill="none" opacity="0.8"/>')
        if len(pts) > 1:
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            out.append(f'<path d="{d}" stroke="{color}" stroke-width="2" fill="none" stroke-linejoin="round"/>')
        for x, y in pts:
            out.append(marker(shape, x, y, color))
        if pts:
            ends.append([pts[-1][1], pts[-1][0], name])
    ends.sort()
    for i in range(1, len(ends)):                    # direct labels: keep 13px apart
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 13)
    for y, x, name in ends:
        out.append(f'<text x="{x + 10:.1f}" y="{y + 4:.1f}" font-size="11" fill="{INK}">{esc(name)}</text>')
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def bars_chart(path: Path, title: str, desc: str, labels: list[str], values: list[float], notes: list[str],
               unit: str) -> None:
    """Horizontal bars, one hue (a single series needs no legend)."""
    bh, gap, top = 22, 10, MT
    height = top + len(labels) * (bh + gap) + 40
    vmax, step = nice_max(max(values + [0]) * 1.05)
    x0, pw = 190, W - 190 - 90
    xs = lambda v: x0 + pw * (v / vmax if vmax else 0)            # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" '
           f'font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
           f'<title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>',
           f'<rect width="{W}" height="{height}" fill="{SURFACE}"/>',
           f'<text x="16" y="22" font-size="14" font-weight="600" fill="{INK}">{esc(title)}</text>']
    v = 0.0
    while v <= vmax + 1e-12:
        x = xs(v)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{height - 34}" stroke="{GRID}"/>')
        out.append(f'<text x="{x:.1f}" y="{height - 18}" font-size="11" fill="{INK2}" text-anchor="middle">{esc(fmt(v, unit))}</text>')
        v += step
    color = SYSTEMS["ecogent"][0]
    for i, (lab, val, note) in enumerate(zip(labels, values, notes)):
        y = top + i * (bh + gap)
        w = max(2.0, xs(val) - x0)
        out.append(f'<text x="{x0 - 10}" y="{y + bh / 2 + 4:.1f}" font-size="11" fill="{INK}" text-anchor="end">{esc(lab)}</text>')
        out.append(f'<path d="M{x0},{y} H{x0 + w - 4:.1f} Q{x0 + w:.1f},{y} {x0 + w:.1f},{y + 4} V{y + bh - 4} '
                   f'Q{x0 + w:.1f},{y + bh} {x0 + w - 4:.1f},{y + bh} H{x0} Z" fill="{color}"/>')
        out.append(f'<text x="{x0 + w + 8:.1f}" y="{y + bh / 2 + 4:.1f}" font-size="11" fill="{INK2}">'
                   f'{esc(fmt(val, unit, _DECIMALS["value"] + 1))} · {esc(note)}</text>')
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def boot(vals: list[float]) -> tuple[float | None, float | None]:
    a = np.array(vals, dtype=float)
    if len(a) < 2:
        return None, None
    m = a[np.random.default_rng(0).integers(0, len(a), size=(2000, len(a)))].mean(axis=1)
    return tuple(float(x) for x in np.percentile(m, [2.5, 97.5]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--out", default="bench/results/figures")
    args = ap.parse_args()
    rows = []
    for p in args.csv:
        with open(p, encoding="utf-8", newline="") as f:
            rows += list(csv.DictReader(f))
    if not rows:
        raise SystemExit("no rows")
    unit, _ = add_cost(rows)
    unit = "USD" if unit == "USD" else "tokens"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    levels = sorted({int(r["level"]) for r in rows if r["phase"] == "rerun"})
    xt = [f"L{lv}" for lv in levels]
    reruns = [r for r in rows if r["phase"] == "rerun"]
    by = defaultdict(list)
    for r in reruns:
        by[(r["variant"], int(r["level"]))].append(r)
    main_vars = [v for v in sorted({r["variant"] for r in rows}) if v in MAIN or v in ("ecogent",)]

    cost = {v: [np.mean([r["_cost"] for r in by[(v, lv)]]) if by[(v, lv)] else None for lv in levels] for v in main_vars}
    ci = {v: [boot([r["_cost"] for r in by[(v, lv)]]) if by[(v, lv)] else (None, None) for lv in levels] for v in main_vars}
    lines_chart(out / "fig1_rerun_cost.svg", "Rerun cost by amount of site change",
                "Mean LLM cost of rerunning a compiled task after the site changed, per drift level and system; "
                "whiskers are 95% bootstrap confidence intervals.",
                f"mean cost per rerun ({unit})", "drift level (L0 none ... L4 redesign)", xt, cost, unit, ci)
    succ = {v: [100 * np.mean([int(r["success"]) for r in by[(v, lv)]]) if by[(v, lv)] else None for lv in levels]
            for v in main_vars}
    lines_chart(out / "fig2_success.svg", "Rerun success by amount of site change",
                "Share of reruns the oracle scored as successful, per drift level and system.",
                "successful reruns", "drift level (L0 none ... L4 redesign)", xt, succ, "%")
    seqs = defaultdict(list)
    for r in rows:
        if r["variant"] in main_vars and r["phase"] in ("cold", "rerun"):
            seqs[(r["variant"], r["task"], r["seed"], r.get("repeat") or "1")].append(
                (-1 if r["phase"] == "cold" else int(r["level"]), r["_cost"]))
    cum = {}
    for v in main_vars:
        units = [sorted(s) for (vv, *_), s in seqs.items() if vv == v]
        n = max((len(u) for u in units), default=0)
        units = [u for u in units if len(u) == n]
        if units:
            cum[v] = list(np.array([[c for _, c in u] for u in units]).cumsum(axis=1).mean(axis=0))
    n = max((len(c) for c in cum.values()), default=0)
    lines_chart(out / "fig3_cumulative.svg", "Cumulative cost over repeated runs",
                "Mean cumulative LLM cost over the sequence: cold run, then one rerun per drift level.",
                f"cumulative cost ({unit})", "run sequence", ["cold"] + [f"L{i}" for i in levels][:n - 1],
                {v: c + [None] * (n - len(c)) for v, c in cum.items()}, unit)
    abl = sorted(v for v in {r["variant"] for r in rows} if v.startswith("no_") or v == "ecogent")
    if len(abl) > 1:
        labels, vals, notes = [], [], []
        for v in ["ecogent"] + [a for a in abl if a != "ecogent"]:
            g = [r for r in reruns if r["variant"] == v and int(r["level"]) >= 1]
            if not g:
                continue
            labels.append(ABLATION_LABELS.get(v, v.replace("_", " ")))
            vals.append(float(np.mean([r["_cost"] for r in g])))
            notes.append(f"{100 * np.mean([int(r['success']) for r in g]):.0f}% success")
        bars_chart(out / "fig4_ablations.svg", "What each part of the repair ladder saves",
                   "Mean rerun cost at drift levels 1-4 with one part of the ladder switched off; "
                   "labels give the success rate.", labels, vals, notes, unit)
    print(f"Figures written to {out}")


if __name__ == "__main__":
    main()
