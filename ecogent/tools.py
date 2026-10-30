"""
Built-in local file operation tools.

Every path is resolved against a base folder (the chat's selected folder, else its output
folder) and must stay inside the allowed roots: chat folder, temp folder, output folder,
selected folder, plus single files the user picked (read-only). A plan can never touch
other files on the machine.
"""

from __future__ import annotations

import csv
import fnmatch
import io
import json
import shutil
from pathlib import Path
from typing import Iterable

MAX_READ_CHARS = 200_000


class FileToolError(Exception):
    pass


class FileTools:
    def __init__(self, roots: Iterable[Path], base: Path, extra_files: Iterable[Path] = ()):
        self.roots = [Path(r).resolve() for r in roots if r]
        self.base = Path(base).resolve()
        self.extra = {Path(p).resolve() for p in extra_files if p}

    # ------------------------------------------------------------------ sandbox
    def path(self, path: str | Path, must_exist: bool = False, writable: bool = False) -> Path:
        if not str(path).strip():
            raise FileToolError("empty path")
        p = Path(str(path).strip().strip('"'))
        p = (p if p.is_absolute() else self.base / p).resolve()
        inside = any(p == r or r in p.parents for r in self.roots)
        if not inside and not (p in self.extra and not writable):
            raise FileToolError(f"path outside the allowed folders: {p}")
        if must_exist and not p.exists():
            raise FileToolError(f"not found: {p}")
        return p

    def _is_root(self, p: Path) -> bool:
        return p in self.roots

    # ------------------------------------------------------------------ read
    def read(self, path: str, max_chars: int = MAX_READ_CHARS) -> str:
        p = self.path(path, must_exist=True)
        if p.is_dir():
            raise FileToolError(f"{p} is a folder; use list_files")
        suffix = p.suffix.lower()
        if suffix == ".json":
            text = json.dumps(json.loads(p.read_text(encoding="utf-8")), indent=2, ensure_ascii=False)
        elif suffix == ".xlsx":
            text = self._read_xlsx(p)
        elif suffix == ".docx":
            text = self._read_docx(p)
        elif suffix == ".pdf":
            text = self._read_pdf(p)
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
        return text[:max_chars]

    @staticmethod
    def _read_xlsx(p: Path) -> str:
        from openpyxl import load_workbook
        wb = load_workbook(p, read_only=True, data_only=True)
        out = io.StringIO()
        for ws in wb.worksheets:
            out.write(f"## Sheet: {ws.title}\n")
            w = csv.writer(out)
            for row in ws.iter_rows(values_only=True):
                w.writerow(["" if v is None else v for v in row])
        return out.getvalue()

    @staticmethod
    def _read_docx(p: Path) -> str:
        from docx import Document
        doc = Document(str(p))
        parts = [para.text for para in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)

    @staticmethod
    def _read_pdf(p: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise FileToolError("reading PDF needs: pip install pypdf") from e
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)

    # ------------------------------------------------------------------ write
    def write(self, path: str, content: str, append: bool = False) -> Path:
        p = self.path(path, writable=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a" if append else "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def make_dir(self, path: str) -> Path:
        p = self.path(path, writable=True)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def copy(self, src: str, dest: str) -> Path:
        s = self.path(src, must_exist=True)
        d = self.path(dest, writable=True)
        if d.is_dir():
            d = d / s.name
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        return d

    def move(self, src: str, dest: str) -> Path:
        s = self.path(src, must_exist=True, writable=True)
        if self._is_root(s):
            raise FileToolError(f"cannot move a root folder: {s}")
        d = self.path(dest, writable=True)
        if d.is_dir():
            d = d / s.name
        d.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.move(str(s), str(d)))

    def delete(self, path: str) -> Path:
        p = self.path(path, must_exist=True, writable=True)
        if self._is_root(p):
            raise FileToolError(f"cannot delete a root folder: {p}")
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return p

    # ------------------------------------------------------------------ query
    def exists(self, path: str) -> bool:
        try:
            return self.path(path).exists()
        except FileToolError:
            return False

    def list(self, path: str = ".", pattern: str = "*", recursive: bool = False) -> list[str]:
        p = self.path(path or ".", must_exist=True)
        if not p.is_dir():
            raise FileToolError(f"{p} is not a folder")
        items = p.rglob("*") if recursive else p.iterdir()
        return sorted(str(x) for x in items if x.is_file() and fnmatch.fnmatch(x.name.lower(), (pattern or "*").lower()))
