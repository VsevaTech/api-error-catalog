from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from tests.conftest import error_response_spec
from typer.testing import CliRunner

from api_error_catalog.analyzer import scan
from api_error_catalog.cli import app
from api_error_catalog.config import Config, ConfigError, load_config
from api_error_catalog.governance import Baseline, BaselineError, load_baseline
from api_error_catalog.models import ExceptionState, IssueStatus, Severity
from api_error_catalog.reporters import render_html, render_json, render_markdown, render_text

runner = CliRunner()
TODAY = date(2026, 9, 24)
GOVERNANCE = Path(__file__).parent.parent / "examples" / "governance"


def _exception(**overrides) -> dict:
    item = {
        "rule": "ERROR001",
        "error_code": "user_not_found",
        "owner": "@team-customer",
        "reason": "Legacy mobile clients rely on 400",
        "expires_at": "2026-12-31",
    }
    item.update(overrides)
    return {k: v for k, v in item.items() if v is not None}


def _config(*exceptions: dict, **extra) -> Config:
    return Config.from_dict({"exceptions": list(exceptions), **extra})


def _by_fp(result):
    return {i.fingerprint: i for i in result.issues if i.fingerprint}


def _gov(result, rule_id):
    return [i for i in result.issues if i.rule_id == rule_id]


# --------------------------------------------------------------------------- fingerprints


def test_fingerprints_are_stable_and_readable(examples_dir):
    fps = set(_by_fp(scan(examples_dir, Config())))
    assert {
        "ERROR001:user_not_found",
        "ERROR002:rate_limit",
        "ERROR005:customer_blocked@Customer API",
        "ERROR004:Auth API:POST /v1/auth/token/refresh 401",
    } <= fps
    # Same input -> same fingerprints and facets.
    again = _by_fp(scan(examples_dir, Config()))
    assert {fp: i.facets for fp, i in _by_fp(scan(examples_dir, Config())).items()} == {
        fp: i.facets for fp, i in again.items()
    }


def test_facets_describe_how_the_debt_can_grow(examples_dir):
    issues = _by_fp(scan(examples_dir, Config()))
    assert issues["ERROR001:user_not_found"].facets == ("Auth API -> 404", "Customer API -> 400")
    assert len(issues["ERROR002:rate_limit"].facets) == 2
    assert issues["ERROR004:Auth API:POST /v1/auth/token/refresh 401"].facets == ()


def test_no_governance_keeps_previous_behaviour(examples_dir):
    result = scan(examples_dir, Config())
    assert result.governance is None
    assert all(i.status == IssueStatus.NEW for i in result.issues)
    assert len(result.blocking) == 2
    assert "Governance" not in render_text(result)
    assert json.loads(render_json(result))["governance"] is None


# ------------------------------------------------------------------------------- baseline


def test_baseline_suppresses_known_debt(examples_dir):
    baseline = Baseline.from_issues(scan(examples_dir, Config()).issues)
    result = scan(examples_dir, Config(), baseline=baseline, today=TODAY)
    assert result.blocking == []
    assert all(
        i.status == IssueStatus.BASELINED for i in result.issues if i.severity != Severity.INFO
    )
    assert result.summary()["baselined"] == 10
    assert result.summary()["enforced_conflicts"] == 0


def test_baseline_excludes_info_findings(tmp_path, write_spec):
    write_spec("notes.yaml", {"just": "yaml"})
    write_spec("a.yaml", error_response_spec(title="A", path="/a", status="404", example_code="x"))
    result = scan(tmp_path, Config())
    assert any(i.rule_id == "SPEC001" for i in result.issues)
    assert len(Baseline.from_issues(result.issues)) == 0


def _two_services(tmp_path, write_spec, statuses=("404", "400"), extra=()):
    for index, status in enumerate(statuses):
        write_spec(
            f"s{index}.yaml",
            error_response_spec(
                title=f"S{index}", path=f"/s{index}", status=status, example_code="user_not_found"
            ),
        )
    for name, doc in extra:
        write_spec(name, doc)
    return tmp_path


def test_new_conflict_is_enforced_despite_baseline(tmp_path, write_spec):
    root = _two_services(tmp_path, write_spec)
    baseline = Baseline.from_issues(scan(root, Config()).issues)
    write_spec(
        "s2.yaml",
        error_response_spec(title="S2", path="/s2", status="409", example_code="order_locked"),
    )
    write_spec(
        "s3.yaml",
        error_response_spec(title="S3", path="/s3", status="423", example_code="order_locked"),
    )
    result = scan(root, Config(), baseline=baseline, today=TODAY)
    blocking = {i.fingerprint for i in result.blocking}
    assert blocking == {"ERROR001:order_locked"}
    assert _by_fp(result)["ERROR001:user_not_found"].status == IssueStatus.BASELINED


def test_grown_debt_is_enforced_with_new_facets(tmp_path, write_spec):
    root = _two_services(tmp_path, write_spec)
    baseline = Baseline.from_issues(scan(root, Config()).issues)
    write_spec(
        "s2.yaml",
        error_response_spec(title="S2", path="/s2", status="422", example_code="user_not_found"),
    )
    issue = _by_fp(scan(root, Config(), baseline=baseline, today=TODAY))["ERROR001:user_not_found"]
    assert issue.status == IssueStatus.NEW
    assert issue.new_facets == ("S2 -> 422",)


def test_repeating_a_baselined_facet_is_not_new_debt(tmp_path, write_spec):
    root = _two_services(tmp_path, write_spec)
    baseline = Baseline.from_issues(scan(root, Config()).issues)
    doc = error_response_spec(title="S0", path="/s0", status="404", example_code="user_not_found")
    doc["paths"]["/s0-bis"] = doc["paths"]["/s0"]
    write_spec("s0.yaml", doc)
    issue = _by_fp(scan(root, Config(), baseline=baseline, today=TODAY))["ERROR001:user_not_found"]
    assert len(issue.occurrences) == 3
    assert issue.status == IssueStatus.BASELINED


def test_resolved_debt_is_reported_and_pruned(tmp_path, write_spec):
    root = _two_services(tmp_path, write_spec)
    baseline = Baseline.from_issues(scan(root, Config()).issues)
    write_spec(
        "s1.yaml",
        error_response_spec(title="S1", path="/s1", status="404", example_code="user_not_found"),
    )
    result = scan(root, Config(), baseline=baseline, today=TODAY)
    assert result.governance.resolved_baseline_entries == ["ERROR001:user_not_found"]
    [info] = _gov(result, "GOV004")
    assert info.severity == Severity.INFO and "baseline update" in info.message
    pruned, removed = baseline.pruned(result.issues)
    assert len(pruned) == 0 and removed == ["ERROR001:user_not_found"]


def test_partially_fixed_debt_prunes_facets(tmp_path, write_spec):
    root = _two_services(tmp_path, write_spec, statuses=("404", "400", "422"))
    baseline = Baseline.from_issues(scan(root, Config()).issues)
    write_spec(
        "s2.yaml",
        error_response_spec(title="S2", path="/s2", status="404", example_code="user_not_found"),
    )
    result = scan(root, Config(), baseline=baseline, today=TODAY)
    pruned, removed = baseline.pruned(result.issues)
    assert removed == ["ERROR001:user_not_found [S2 -> 422]"]
    assert pruned.entries["ERROR001:user_not_found"].facets == ("S0 -> 404", "S1 -> 400")


def test_baseline_roundtrip_is_deterministic(tmp_path, examples_dir):
    baseline = Baseline.from_issues(scan(examples_dir, Config()).issues)
    target = tmp_path / "b.json"
    baseline.write(target)
    loaded = load_baseline(target)
    assert loaded.dumps() == baseline.dumps()
    fps = [e["fingerprint"] for e in json.loads(target.read_text())["entries"]]
    assert fps == sorted(fps)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{not json", "invalid JSON"),
        ('{"schema_version": 99, "entries": []}', "unsupported baseline format"),
        ('{"schema_version": 1, "entries": {}}', "'entries' must be a list"),
        ('{"schema_version": 1, "entries": [{"facets": []}]}', "string 'fingerprint'"),
        ('{"schema_version": 1, "entries": [{"fingerprint": "x", "facets": "a"}]}', "facets"),
    ],
)
def test_malformed_baseline(tmp_path, content, message):
    target = tmp_path / "b.json"
    target.write_text(content)
    with pytest.raises(BaselineError, match=message):
        load_baseline(target)


def test_missing_baseline(tmp_path):
    with pytest.raises(BaselineError, match="baseline create"):
        load_baseline(tmp_path / "nope.json")


# ----------------------------------------------------------------------------- exceptions


def test_active_exception_suppresses_finding(examples_dir):
    result = scan(examples_dir, _config(_exception()), today=TODAY)
    issue = _by_fp(result)["ERROR001:user_not_found"]
    assert issue.status == IssueStatus.EXCEPTED
    assert issue.exception.owner == "@team-customer"
    assert {i.fingerprint for i in result.blocking} == {"ERROR002:rate_limit"}
    [st] = result.governance.exceptions
    assert st.state == ExceptionState.ACTIVE and st.matched == ["ERROR001:user_not_found"]


def test_expiry_date_is_inclusive(examples_dir):
    cfg = _config(_exception(expires_at="2026-09-24"))
    assert (
        _by_fp(scan(examples_dir, cfg, today=TODAY))["ERROR001:user_not_found"].status
        == IssueStatus.EXCEPTED
    )


def test_expired_exception_becomes_an_error_again(examples_dir):
    cfg = _config(_exception(expires_at="2026-09-01", ticket="CUST-42"))
    result = scan(examples_dir, cfg, today=TODAY)
    issue = _by_fp(result)["ERROR001:user_not_found"]
    assert issue.status == IssueStatus.EXPIRED and issue.is_enforced
    [gov] = _gov(result, "GOV001")
    assert gov.severity == Severity.CONFLICT
    assert "@team-customer" in gov.message and "23 days ago" in gov.message
    assert "CUST-42" in gov.message
    assert gov.occurrences == issue.occurrences
    assert result.governance.exceptions[0].state == ExceptionState.EXPIRED


def test_expired_exception_beats_baseline(examples_dir):
    baseline = Baseline.from_issues(scan(examples_dir, Config()).issues)
    cfg = _config(_exception(expires_at="2026-01-01"))
    result = scan(examples_dir, cfg, baseline=baseline, today=TODAY)
    assert _by_fp(result)["ERROR001:user_not_found"].status == IssueStatus.EXPIRED
    assert {i.rule_id for i in result.blocking} == {"ERROR001", "GOV001"}


def test_expired_exception_on_a_warning_still_fails(examples_dir):
    cfg = _config(
        _exception(
            rule="UNDOCUMENTED_ERROR_CODE",
            error_code=None,
            service="Auth API",
            endpoint="post /v1/auth/token/*",
            expires_at="2026-01-01",
        )
    )
    result = scan(examples_dir, cfg, today=TODAY)
    issue = _by_fp(result)["ERROR004:Auth API:POST /v1/auth/token/refresh 401"]
    assert issue.status == IssueStatus.EXPIRED
    assert "GOV001" in {i.rule_id for i in result.blocking}


def test_renewed_exception_wins_over_expired_one(examples_dir):
    cfg = _config(_exception(expires_at="2026-01-01"), _exception(expires_at="2027-01-01"))
    result = scan(examples_dir, cfg, today=TODAY)
    assert _by_fp(result)["ERROR001:user_not_found"].status == IssueStatus.EXCEPTED
    states = [st.state for st in result.governance.exceptions]
    assert states == [ExceptionState.UNUSED, ExceptionState.ACTIVE]
    [unused] = _gov(result, "GOV002")
    assert "also expired" in unused.message
    assert not _gov(result, "GOV001")


def test_unused_exception_is_a_warning(examples_dir):
    result = scan(examples_dir, _config(_exception(error_code="no_such_code")), today=TODAY)
    [gov] = _gov(result, "GOV002")
    assert gov.severity == Severity.WARNING and "Remove it" in gov.message
    assert "GOV002" not in {i.rule_id for i in result.blocking}


def test_expiring_soon_is_info(examples_dir):
    cfg = _config(_exception(expires_at="2026-10-01"), exception_expiry_warning_days=10)
    result = scan(examples_dir, cfg, today=TODAY)
    [gov] = _gov(result, "GOV003")
    assert gov.severity == Severity.INFO and "in 7 days" in gov.message
    assert result.governance.exceptions[0].state == ExceptionState.EXPIRING


def test_service_scope_does_not_waive_cross_service_conflicts(examples_dir):
    cfg = _config(_exception(service="Customer API"))
    result = scan(examples_dir, cfg, today=TODAY)
    assert _by_fp(result)["ERROR001:user_not_found"].status == IssueStatus.NEW
    assert result.governance.exceptions[0].state == ExceptionState.UNUSED


def test_service_scope_waives_within_service_findings(examples_dir):
    cfg = _config(
        _exception(rule="ERROR005", error_code="customer_blocked", service="Customer API")
    )
    issue = _by_fp(scan(examples_dir, cfg, today=TODAY))["ERROR005:customer_blocked@Customer API"]
    assert issue.status == IssueStatus.EXCEPTED


def test_excepted_findings_are_not_written_to_the_baseline(examples_dir):
    result = scan(examples_dir, _config(_exception()), today=TODAY)
    assert "ERROR001:user_not_found" not in Baseline.from_issues(result.issues).entries


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"owner": None}, "missing required keys: \\['owner'\\]"),
        ({"reason": ""}, "missing required keys: \\['reason'\\]"),
        ({"expires_at": "31.12.2026"}, "YYYY-MM-DD"),
        ({"rule": "ERROR999"}, "cannot be excepted"),
        ({"rule": "REF001"}, "cannot be excepted"),
        ({"error_code": None}, "blanket exceptions are not allowed"),
        ({"team": "x"}, "unknown keys"),
        ({"owner": 42}, "'owner' must be a non-empty string"),
    ],
)
def test_invalid_exceptions_are_config_errors(override, message):
    with pytest.raises(ConfigError, match=message):
        _config(_exception(**override))


def test_exception_accepts_rule_name_and_yaml_dates(tmp_path):
    cfg_path = tmp_path / ".api-error-catalog.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"baseline": "debt/baseline.json"}) + "exceptions:\n"
        "  - rule: SAME_CODE_DIFFERENT_HTTP_STATUS\n"
        "    error_code: user_not_found\n"
        "    owner: '@a'\n"
        "    reason: r\n"
        "    expires_at: 2026-12-31\n"
    )
    cfg = load_config(None, tmp_path)
    assert cfg.exceptions[0].rule == "ERROR001"
    assert cfg.exceptions[0].expires_at == date(2026, 12, 31)
    assert cfg.baseline == tmp_path / "debt" / "baseline.json"


def test_bad_expiry_warning_days():
    with pytest.raises(ConfigError, match="non-negative integer"):
        Config.from_dict({"exception_expiry_warning_days": -1})


# ------------------------------------------------------------------------------ reporters


def _governed(examples_dir, today=TODAY):
    cfg = load_config(GOVERNANCE / ".api-error-catalog.yaml", examples_dir)
    return scan(examples_dir, cfg, baseline=load_baseline(cfg.baseline), today=today)


def test_reports_show_governance(examples_dir):
    result = _governed(examples_dir)
    text = render_text(result)
    assert "Governance (as of 2026-09-24)" in text
    assert "No new conflicts or warnings" in text
    assert "[excepted until 2027-06-30 · @payments-team] ERROR002:rate_limit" in text

    md = render_markdown(result)
    assert "| Enforced conflicts | 0 |" in md
    assert "## Governance" in md and "PAY-1423" in md
    assert "<summary>Accepted debt (10)" in md

    html = render_html(result)
    assert 'id="governance"' in html and 'id="show-accepted"' in html
    assert "badge gov-baselined" in html and "state-active" in html

    data = json.loads(render_json(result))
    assert data["governance"]["baseline"]["entries"] == 8
    assert {i["status"] for i in data["issues"]} == {"baselined", "excepted"}
    assert data["summary"]["enforced_conflicts"] == 0


def test_reports_show_expired_exception(examples_dir):
    result = _governed(examples_dir, today=date(2027, 7, 1))
    assert {i.rule_id for i in result.blocking} == {"ERROR002", "GOV001"}
    md = render_markdown(result)
    assert "🔴 expired" in md and "Expired exceptions | 2 |" in md
    assert "status: expired exception" in render_text(result)


# ------------------------------------------------------------------------------------ CLI


def _cli(*args):
    return runner.invoke(app, [str(a) for a in args])


def test_cli_baseline_create_then_scan_passes(examples_dir, tmp_path):
    target = tmp_path / "baseline.json"
    result = _cli("baseline", "create", examples_dir, "-o", target)
    assert result.exit_code == 0, result.output
    assert "10 entries" in result.output
    result = _cli("scan", examples_dir, "--baseline", target, "--fail-on-conflict")
    assert result.exit_code == 0, result.output
    assert "Enforced: 0 conflicts" in result.output


def test_cli_baseline_create_refuses_to_overwrite(examples_dir, tmp_path):
    target = tmp_path / "baseline.json"
    target.write_text("{}")
    result = _cli("baseline", "create", examples_dir, "-o", target)
    assert result.exit_code == 2 and "already exists" in result.output
    assert _cli("baseline", "create", examples_dir, "-o", target, "--force").exit_code == 0


def test_cli_fails_on_new_conflict(tmp_path, write_spec):
    specs = tmp_path / "specs"
    specs.mkdir()
    for i, status in enumerate(("404", "400")):
        (specs / f"s{i}.yaml").write_text(
            yaml.safe_dump(
                error_response_spec(
                    title=f"S{i}", path="/x", status=status, example_code="user_not_found"
                )
            )
        )
    target = tmp_path / "b.json"
    assert _cli("baseline", "create", specs, "-o", target).exit_code == 0
    (specs / "s2.yaml").write_text(
        yaml.safe_dump(
            error_response_spec(title="S2", path="/x", status="409", example_code="user_not_found")
        )
    )
    result = _cli("scan", specs, "-b", target, "--fail-on-conflict")
    assert result.exit_code == 1, result.output
    assert "+ new since baseline: S2 -> 409" in result.output


def test_cli_expired_exception_fails_the_build(examples_dir):
    cfg = GOVERNANCE / ".api-error-catalog.yaml"
    ok = _cli("scan", examples_dir, "-c", cfg, "--fail-on-conflict", "--today", "2026-09-24")
    assert ok.exit_code == 0, ok.output
    late = _cli("scan", examples_dir, "-c", cfg, "--fail-on-conflict", "--today", "2027-04-01")
    assert late.exit_code == 1, late.output
    assert "GOV001 EXCEPTION_EXPIRED" in late.output and "@identity-team" in late.output


def test_cli_bad_today_and_missing_baseline(examples_dir, tmp_path):
    assert _cli("scan", examples_dir, "--today", "tomorrow").exit_code == 2
    result = _cli("scan", examples_dir, "--baseline", tmp_path / "nope.json")
    assert result.exit_code == 2 and "baseline file not found" in result.output


def test_cli_baseline_update_ratchets(tmp_path):
    specs = tmp_path / "specs"
    specs.mkdir()

    def write(name, status, code="user_not_found"):
        doc = error_response_spec(title=name, path="/x", status=status, example_code=code)
        (specs / f"{name}.yaml").write_text(yaml.safe_dump(doc))

    write("A", "404")
    write("B", "400")
    target = tmp_path / "b.json"
    assert _cli("baseline", "create", specs, "-o", target).exit_code == 0
    assert _cli("baseline", "update", specs, "-b", target, "--check").exit_code == 0

    write("B", "404")  # fixed
    write("C", "409", code="order_locked")
    write("D", "423", code="order_locked")  # new debt, must not be absorbed
    check = _cli("baseline", "update", specs, "-b", target, "--check")
    assert check.exit_code == 1 and "out of date" in check.output

    update = _cli("baseline", "update", specs, "-b", target)
    assert update.exit_code == 0, update.output
    assert "resolved: ERROR001:user_not_found" in update.output
    assert "were NOT added" in update.output
    assert json.loads(target.read_text())["entries"] == []
    assert _cli("scan", specs, "-b", target, "--fail-on-conflict").exit_code == 1


def test_cli_invalid_exception_is_exit_2(examples_dir, tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("exceptions:\n  - rule: ERROR001\n    error_code: x\n")
    result = _cli("scan", examples_dir, "-c", cfg)
    assert result.exit_code == 2 and "missing required keys" in result.output


def test_committed_example_baseline_is_up_to_date(examples_dir):
    cfg = GOVERNANCE / ".api-error-catalog.yaml"
    result = _cli("baseline", "update", examples_dir, "-c", cfg, "--check", "--today", TODAY)
    assert result.exit_code == 0, result.output
