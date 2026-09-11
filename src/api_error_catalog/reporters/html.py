"""Self-contained HTML report rendered from a Jinja2 template."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from jinja2 import Environment, PackageLoader, select_autoescape

from .. import __version__
from ..models import ScanResult
from ..rules.schema_conflict import describe
from .json_reporter import to_dict

_env = Environment(
    loader=PackageLoader("api_error_catalog.reporters", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["describe_signature"] = describe


def render_html(result: ScanResult) -> str:
    template = _env.get_template("catalog.html.j2")
    data = to_dict(result)
    return template.render(
        result=result,
        summary=result.summary(),
        version=__version__,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        # Embedded as inert JSON data; `<`/`>` are escaped so it is safe inside <script>.
        catalog_json=json.dumps(data["catalog"], ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e"),
    )
