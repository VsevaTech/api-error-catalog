from __future__ import annotations

import json

from api_error_catalog.analyzer import scan
from api_error_catalog.config import Config
from api_error_catalog.reporters import render_html, render_json, render_markdown, render_text


def _result(examples_dir):
    return scan(examples_dir, Config())


def test_markdown_generation(examples_dir):
    md = render_markdown(_result(examples_dir))
    assert md.startswith("# API Error Catalog\n")
    assert "## Summary" in md
    assert "| Conflicts | 2 |" in md
    assert "## Error Catalog" in md
    assert "| `user_not_found` | 400, 404 | Auth API, Customer API |" in md
    assert "### Conflicts (2)" in md
    assert "ERROR001 `SAME_CODE_DIFFERENT_HTTP_STATUS` · `user_not_found`" in md
    assert "ERROR002 `SAME_CODE_INCOMPATIBLE_SCHEMA` · `rate_limit`" in md
    assert "ERROR004" in md


def test_html_generation(examples_dir):
    html = render_html(_result(examples_dir))
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>API Error Catalog</title>" in html
    for section in ("Summary", "Specifications", "Error Catalog", "Conflicts &amp; Warnings"):
        assert section in html
    assert 'id="search"' in html and 'id="service-filter"' in html
    assert 'id="code-user_not_found"' in html
    assert 'data-statuses="400|404"' in html
    assert 'class="badge conflict"' in html
    assert "Auth API" in html and "Payment API" in html
    assert 'type="application/json"' in html
    # Descriptions containing apostrophes must be HTML-escaped.
    assert "customer&#39;s company" in html or "customer's company" in html


def test_html_escapes_untrusted_strings():
    from pathlib import Path

    from tests.conftest import error_response_spec

    from api_error_catalog.analyzer import analyze_specs
    from api_error_catalog.loader import LoadedSpec

    doc = error_response_spec(
        title="<script>alert(1)</script>",
        path="/x",
        status="400",
        example_code="bad",
        description="<img src=x onerror=alert(1)>",
    )
    result = analyze_specs([LoadedSpec(Path("evil.yaml"), doc)], Config())
    html = render_html(result)
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html


def test_json_generation(examples_dir):
    data = json.loads(render_json(_result(examples_dir)))
    assert data["schema_version"] == 1
    assert data["generator"]["name"] == "api-error-catalog"
    assert data["summary"] == {
        "specifications": 3,
        "services": 3,
        "operations_scanned": 11,
        "error_codes": 15,
        "conflicts": 2,
        "warnings": 8,
        "info": 0,
    }
    codes = {c["error_code"]: c for c in data["catalog"]}
    assert codes["user_not_found"]["http_statuses"] == ["400", "404"]
    assert codes["payment_declined"]["occurrences"][0]["location"] == "schema.const"
    assert codes["invalid_otp"]["occurrences"][0]["location"] == "schema.enum"
    assert {i["rule_id"] for i in data["issues"] if i["severity"] == "CONFLICT"} == {
        "ERROR001",
        "ERROR002",
    }
    assert len(data["uncategorized"]) == 3
    occ = codes["rate_limit"]["occurrences"][0]
    assert set(occ) >= {"service", "source_file", "http_status", "method", "path", "signature"}


def test_text_generation(examples_dir):
    text = render_text(_result(examples_dir))
    assert text.startswith("API Error Catalog\n")
    assert "Conflicts: 2" in text
    assert "CONFLICT\nrule: ERROR001" in text
    assert "Problem:" in text


def test_reports_with_empty_results():
    from api_error_catalog.analyzer import analyze_specs

    result = analyze_specs([], Config())
    assert "No conflicts or warnings found." in render_markdown(result)
    assert "No conflicts or warnings found." in render_html(result)
    assert json.loads(render_json(result))["catalog"] == []
