#!/usr/bin/env python
"""Render `examples/expected/*` and `docs/index.html` from `examples/specs`.

Both locations are git-ignored: CI renders them on every run and the Pages workflow
publishes the HTML as the live demo.

Usage:
    python scripts/build_examples.py          # rewrite the files
    python scripts/build_examples.py --check  # exit 1 if any file is out of date
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from api_error_catalog.analyzer import scan
from api_error_catalog.config import Config
from api_error_catalog.reporters import render_html, render_json, render_markdown

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "examples" / "specs"
EXPECTED = ROOT / "examples" / "expected"
DOCS_INDEX = ROOT / "docs" / "index.html"

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")


def _normalize(text: str) -> str:
    """Strip the generation timestamp so the check is stable across runs."""
    return _TIMESTAMP.sub("<timestamp>", text)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    result = scan(SPECS, Config())
    outputs = {
        EXPECTED / "catalog.md": render_markdown(result),
        EXPECTED / "catalog.json": render_json(result),
        EXPECTED / "catalog.html": render_html(result),
        DOCS_INDEX: render_html(result),
    }
    stale: list[Path] = []
    for path, content in outputs.items():
        if check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if _normalize(current) != _normalize(content):
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        for path in stale:
            print(f"out of date: {path.relative_to(ROOT)}", file=sys.stderr)
        print("run: python scripts/build_examples.py", file=sys.stderr)
        return 1
    if check:
        print("example reports are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
