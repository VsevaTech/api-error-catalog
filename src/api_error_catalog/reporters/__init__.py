"""Report renderers: text (console), markdown, html, json."""

from __future__ import annotations

from collections.abc import Callable

from ..models import ScanResult
from .html import render_html
from .json_reporter import render_json
from .markdown import render_markdown
from .text import render_text

Renderer = Callable[[ScanResult], str]

RENDERERS: dict[str, Renderer] = {
    "text": render_text,
    "markdown": render_markdown,
    "html": render_html,
    "json": render_json,
}

__all__ = ["RENDERERS", "Renderer", "render_html", "render_json", "render_markdown", "render_text"]
