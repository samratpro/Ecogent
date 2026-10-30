"""Write final deliverables in the format the user asked for."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

TEXT_FORMATS = {"md", "txt", "docx", "json", "html"}
TABLE_FORMATS = {"csv", "xlsx"}


def normalize_format(fmt: str) -> str:
    fmt = (fmt or "md").lower().lstrip(".")
    return {"markdown": "md", "excel": "xlsx", "xls": "xlsx", "doc": "docx", "word": "docx", "text": "txt"}.get(fmt, fmt)


def output_path(folder: Path, filename: str, fmt: str) -> Path:
    fmt = normalize_format(fmt)
    stem = Path(filename).stem if filename else "output"
    return Path(folder) / f"{stem}.{fmt}"


def write_rows(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)
    suffix = path.suffix.lower()
    if suffix == ".json":
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
    if suffix == ".xlsx":
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.append(columns)
            for r in rows:
                ws.append([_cell(r.get(c)) for c in columns])
            wb.save(path)
            return path
        except ImportError:
            path = path.with_suffix(".csv")
    if suffix in (".md", ".txt", ".docx"):
        return write_text(_rows_to_md(rows, columns), path)
    path = path.with_suffix(".csv")
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _cell(r.get(c)) for c in columns})
    return path


def write_text(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".docx":
        try:
            return _markdown_to_docx(text, path)
        except ImportError:
            path = path.with_suffix(".md")
    path.write_text(text, encoding="utf-8")
    return path


def _cell(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else v


def _rows_to_md(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "_No records._\n"
    head = "| " + " | ".join(columns) + " |\n|" + "---|" * len(columns) + "\n"
    body = "".join("| " + " | ".join(str(_cell(r.get(c))).replace("|", "/").replace("\n", " ") for c in columns) + " |\n"
                   for r in rows)
    return head + body


def _markdown_to_docx(text: str, path: Path) -> Path:
    from docx import Document

    doc = Document()
    for line in text.splitlines():
        s = line.rstrip()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            doc.add_heading(m.group(2), level=min(len(m.group(1)), 4))
        elif re.match(r"^\s*[-*+]\s+", s):
            doc.add_paragraph(re.sub(r"^\s*[-*+]\s+", "", s), style="List Bullet")
        elif re.match(r"^\s*\d+[.)]\s+", s):
            doc.add_paragraph(re.sub(r"^\s*\d+[.)]\s+", "", s), style="List Number")
        elif s:
            doc.add_paragraph(re.sub(r"\*\*(.+?)\*\*", r"\1", s))
    doc.save(path)
    return path
