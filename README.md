# API Error Catalog

Generate a unified API error catalog from OpenAPI specifications and detect inconsistent error contracts across microservices.

[![CI](https://github.com/VsevaTech/api-error-catalog/actions/workflows/ci.yml/badge.svg)](https://github.com/VsevaTech/api-error-catalog/actions/workflows/ci.yml)
[![Action self-test](https://github.com/VsevaTech/api-error-catalog/actions/workflows/action-self-test.yml/badge.svg)](https://github.com/VsevaTech/api-error-catalog/actions/workflows/action-self-test.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Live demo:** <https://VsevaTech.github.io/api-error-catalog/> — an HTML catalog generated from the synthetic example specs in this repository.

## Why

In a microservice system, error responses are described in dozens of OpenAPI files owned by different teams. Over time they drift:

- the same error code is returned with different HTTP statuses (`user_not_found` → `404` in one service, `400` in another);
- the same error code is returned with different response structures;
- the same error code is documented with different descriptions;
- some `4xx`/`5xx` responses have no documented error code at all;
- nobody can quickly answer "where is `company_access_denied` actually used?".

`api-error-catalog` reads every specification, builds one searchable catalog of error codes, and reports the contradictions — locally and in CI.

## Features

- Scans directories of OpenAPI **3.0.x** and **3.1.x** documents (YAML and JSON).
- Extracts error codes from response `example`/`examples`, and from schema `enum`, `const`, `default` and `example` — via configurable field names (`error_code`, `errorCode`, `code` by default).
- Resolves local `$ref`s (schemas, responses, `allOf` extensions, `oneOf`/`anyOf` variants); remote references produce a warning instead of a crash.
- Five consistency rules (see [Rules](#rules)) with `CONFLICT` / `WARNING` severities.
- Reports as **text**, **Markdown** (for PRs and `$GITHUB_STEP_SUMMARY`), **HTML** (self-contained, client-side search and filters, no framework) and **JSON** (for tooling).
- **API governance for existing codebases**: a reviewed **baseline** of known debt (CI fails only on *new* findings) and **owned, time-boxed exceptions** (`owner`, `reason`, `expires_at`) that turn back into errors when they expire. See [Adopting in an existing codebase](#adopting-in-an-existing-codebase-baseline--exceptions).
- CI-friendly exit codes and a ready-to-use **composite GitHub Action**.
- No heavy dependencies: Typer, PyYAML and Jinja2.

## Example

```console
$ api-error-catalog scan examples/specs
API Error Catalog

Specifications: 3
Services: 3
Operations scanned: 11
Error codes: 15
Conflicts: 2
Warnings: 8

CONFLICT
rule: ERROR001 SAME_CODE_DIFFERENT_HTTP_STATUS
error_code: user_not_found
  Auth API                 GET /v1/users/{id} 404
  Customer API             GET /v1/customers/{id}/subscriptions 400
Problem: Same error code is associated with different HTTP statuses: 400 (Customer API), 404 (Auth API).
--------------------------------------------------
CONFLICT
rule: ERROR002 SAME_CODE_INCOMPATIBLE_SCHEMA
error_code: rate_limit
  Auth API                 POST /v1/auth/otp/request 429
  Auth API                 POST /v1/auth/otp/verify 429
  Payment API              POST /v1/payments 429
Problem: Same error code is returned with 2 different response schemas: {code*: string, message*: string, retry_after*: integer} in Payment API; {details: object, error_code*: string, message*: string} in Auth API.
--------------------------------------------------
WARNING
rule: ERROR004 UNDOCUMENTED_ERROR_CODE
  Auth API                 POST /v1/auth/token/refresh 401
Problem: POST /v1/auth/token/refresh 401 (Auth API): error response exists but no documented error code could be extracted (the response schema has no error-code field with enum/const/example).
--------------------------------------------------
...
```

The same scan rendered as HTML is the [live demo](https://VsevaTech.github.io/api-error-catalog/); the Markdown, JSON and HTML reports for the examples are generated on every CI run (`python scripts/build_examples.py`) and attached to the workflow as the `example-reports` artifact.

## Installation

Requires Python 3.12 or newer.

```bash
pip install git+https://github.com/VsevaTech/api-error-catalog.git@v0.1.0
```

Or from a clone:

```bash
git clone https://github.com/VsevaTech/api-error-catalog.git
cd api-error-catalog
pip install -e .
```

The package is not published on PyPI yet.

## Quick Start

```bash
# Put your OpenAPI files (YAML or JSON) in one directory, then:
api-error-catalog scan ./specs

# Produce a browsable HTML catalog
api-error-catalog scan ./specs --format html --output error-catalog.html

# Fail the build when conflicting contracts are found
api-error-catalog scan ./specs --fail-on-conflict
```

## CLI Usage

```text
api-error-catalog scan PATH [OPTIONS]

Arguments:
  PATH                       Directory with OpenAPI specs, or a single spec file.

Options:
  -f, --format [text|markdown|html|json]   Report format (default: text).
  -o, --output PATH          Write the report to a file instead of stdout.
  -c, --config PATH          Path to .api-error-catalog.yaml.
  -b, --baseline PATH        Baseline file with known debt (overrides `baseline:` in the config).
  --fail-on-conflict         Exit with code 1 when at least one enforced CONFLICT is found
                             (new, or covered only by an expired exception).
  -q, --quiet                Suppress the console summary when writing to a file.
  --today YYYY-MM-DD         Evaluate exception expiry as of this date (default: today, UTC).
  -h, --help                 Show help.

api-error-catalog baseline create PATH [-c CONFIG] [-o FILE] [--force]
api-error-catalog baseline update PATH [-c CONFIG] [-b FILE] [--check]
```

Examples:

```bash
api-error-catalog scan ./specs --format markdown --output error-catalog.md
api-error-catalog scan ./specs --format html     --output error-catalog.html
api-error-catalog scan ./specs --format json     --output error-catalog.json
api-error-catalog scan ./specs --config governance/.api-error-catalog.yaml --fail-on-conflict
```

## GitHub Action

The repository ships a composite action that installs the tool, scans your specs, writes a Markdown report to the job summary and (optionally) fails the job on conflicts.

```yaml
name: API governance

on: [push, pull_request]

jobs:
  error-catalog:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: VsevaTech/api-error-catalog@v1
        with:
          path: specs
          fail-on-conflict: true
```

Inputs:

| Input              | Default                 | Description                                              |
|--------------------|-------------------------|----------------------------------------------------------|
| `path`             | `specs`                 | Directory (or file) with OpenAPI specifications.         |
| `fail-on-conflict` | `true`                  | Fail the job when at least one `CONFLICT` is found.      |
| `config`           | `""`                    | Optional path to `.api-error-catalog.yaml`.              |
| `baseline`         | `""`                    | Optional baseline file (overrides `baseline:` in config).|
| `today`            | `""`                    | Optional `YYYY-MM-DD` to evaluate exception expiry against. |
| `output`           | `api-error-catalog.md`  | Where to write the Markdown report.                      |
| `python-version`   | `3.12`                  | Python version used to run the tool.                     |

Outputs: `report` (path of the Markdown file), `conflicts`, `warnings`, `exit-code`, and for governance `enforced-conflicts` (what fails the job), `baselined`, `excepted`, `expired`.

Adopting the action on a repository with legacy debt:

```yaml
      - uses: VsevaTech/api-error-catalog@v1
        with:
          path: specs
          config: .api-error-catalog.yaml   # declares `baseline:` and `exceptions:`
          fail-on-conflict: true            # fails only on new debt and expired exceptions
```

This repository runs the action on itself in [`action-self-test.yml`](.github/workflows/action-self-test.yml).

## Generated Catalog

Every report contains three sections:

1. **Summary** — specifications, services, operations scanned, unique error codes, conflicts, warnings.
2. **Error Catalog** — one entry per error code: HTTP status(es), services, operations that use it, description(s), source file(s) and the schema it is based on.
3. **Conflicts & Warnings** — every rule violation with the affected operations.

The HTML report is a single self-contained file with a search box and service / HTTP-status filters implemented in plain JavaScript; it works from the file system, from an artifact store, or from GitHub Pages.

The JSON report (`schema_version: 1`) contains the same data plus every raw occurrence, including `location` (`example`, `examples`, `schema.enum`, `schema.const`, `schema.default`, `schema.example`) and a normalized `signature` of the response schema.

## Adopting in an existing codebase: baseline & exceptions

Turning on `--fail-on-conflict` in a system that already has 200 inconsistent error contracts
would block every pull request. The governance layer separates **known debt** from **new
debt**, and turns every tolerated inconsistency into an explicit, owned, dated decision.

### 1. Baseline — freeze the current debt

```bash
api-error-catalog baseline create specs/ --output api-error-catalog.baseline.json
git add api-error-catalog.baseline.json   # the debt register goes through code review
```

```yaml
# .api-error-catalog.yaml
baseline: api-error-catalog.baseline.json   # relative to this file
```

From now on `scan --fail-on-conflict` fails only on findings that are **not** in the baseline.
Every finding has a stable, human-readable *fingerprint* and a set of *facets*:

| Rule | Fingerprint | Facets — how the debt can grow |
|---|---|---|
| `ERROR001` | `ERROR001:user_not_found` | `service -> status` pairs |
| `ERROR002` | `ERROR002:rate_limit` | `service -> schema signature` pairs |
| `ERROR003` | `ERROR003:customer_blocked` | `service -> normalized description` pairs |
| `ERROR004` | `ERROR004:Auth API:POST /v1/auth/token/refresh 401` | — (one finding per response) |
| `ERROR005` | `ERROR005:customer_blocked@Customer API` | `schema definition -> signature` pairs |
| `REF001`   | `REF001:<file>: <message>` | — |

A baselined finding stays accepted while its facets are a subset of the baseline entry. It is
enforced again as soon as the debt **grows** — e.g. a third service starts returning
`user_not_found` with `422` — and the report says exactly what is new:

```text
CONFLICT
rule: ERROR001 SAME_CODE_DIFFERENT_HTTP_STATUS
error_code: user_not_found
status: new — the baselined debt grew
  Auth API                 GET /v1/users/{id} 404
  Billing API              GET /v1/invoices/{id} 422
  Customer API             GET /v1/customers/{id}/subscriptions 400
  + new since baseline: Billing API -> 422
```

Adding another endpoint that repeats an already-baselined facet (one more `404` in Auth API)
is not new debt. The baseline is sorted JSON, so `git diff` on it reads as a debt changelog.

**Ratchet.** When debt is fixed, the report shows `GOV004 BASELINE_DEBT_RESOLVED` (INFO).
`baseline update` removes fixed entries and facets and **never adds** new findings:

```bash
api-error-catalog baseline update specs/          # prune fixed debt, commit the diff
api-error-catalog baseline update specs/ --check  # CI: exit 1 if the baseline lists fixed debt
```

Accepting new debt is deliberate and visible in review: either an exception (below) or
`baseline create --force`.

### 2. Exceptions — owned, time-boxed decisions

The baseline answers *"what did we inherit?"*. Exceptions answer *"what do we knowingly tolerate,
who owns it, why, and until when?"*:

```yaml
# .api-error-catalog.yaml
exceptions:
  - rule: ERROR002                       # rule ID or name (SAME_CODE_INCOMPATIBLE_SCHEMA)
    error_code: rate_limit
    owner: "@payments-team"
    reason: Payment API keeps {code, retry_after} until the v2 SDK ships.
    ticket: PAY-1423                     # optional
    expires_at: 2027-06-30               # inclusive

  - rule: ERROR004
    service: Auth API                    # every occurrence must be in this service…
    endpoint: POST /v1/auth/token/*      # …and match this fnmatch pattern
    owner: "@identity-team"
    reason: Refresh errors are owned by the gateway spec.
    expires_at: 2027-03-31
```

| Key | Required | Meaning |
|---|---|---|
| `rule` | yes | `ERROR001`…`ERROR005`, by ID or name. |
| `owner` | yes | Team or person accountable for the debt. |
| `reason` | yes | Why it is tolerated — shown in every report. |
| `expires_at` | yes | `YYYY-MM-DD`, inclusive. |
| `error_code` / `service` / `endpoint` | at least one | Narrow the match. Blanket, rule-wide exceptions are rejected. `service`/`endpoint` require *every* occurrence of the finding to match, so a cross-service conflict can only be excepted by error code, never by one of its participants. |
| `ticket` | no | Link to the remediation task. |

Lifecycle of an exception, evaluated as of today (UTC) or `--today`:

| State | Effect | Finding |
|---|---|---|
| 🟢 active | The finding is `excepted` and does not fail CI. | — |
| 🟡 expiring | Still active; expires within `exception_expiry_warning_days` (default 14). | `GOV003` INFO |
| 🔴 expired | **The finding is enforced again**, even if it is also in the baseline, and the build fails with a finding that names the owner. | `GOV001` CONFLICT |
| ⚪ unused | Matches nothing — the problem was fixed or the matcher is wrong. | `GOV002` WARNING |

Findings covered by an exception are never written to the baseline, so deleting an expired
exception cannot quietly turn the problem into "known debt". The way out of an expired
exception is to fix the finding or renew it with a new `expires_at` — both are reviewable diffs.

### Precedence

1. An **active** exception matches → `excepted`.
2. Otherwise an **expired** exception matches → `expired` (enforced) + `GOV001`.
3. Otherwise the baseline has the fingerprint and all facets → `baselined`.
4. Otherwise → `new` (enforced).

Only CONFLICTs with status `new`/`expired` (including `GOV001`) fail `--fail-on-conflict`;
warnings never fail the run. Reports list enforced findings in full and collapse accepted debt
(Markdown `<details>`, HTML "Show accepted debt" toggle); the JSON report carries `fingerprint`,
`status`, `exception` and `new_facets` per issue plus a `governance` block.

A complete example lives in [`examples/governance/`](examples/governance):

```bash
api-error-catalog scan examples/specs -c examples/governance/.api-error-catalog.yaml --fail-on-conflict
# → exit 0: 2 legacy conflicts accepted (1 baselined, 1 excepted)
api-error-catalog scan examples/specs -c examples/governance/.api-error-catalog.yaml --fail-on-conflict --today 2027-07-01
# → exit 1: both exceptions expired, GOV001 names @payments-team and @identity-team
```

## Rules

| ID         | Name                                  | Severity              | Fires when                                                                                                         |
|------------|---------------------------------------|-----------------------|--------------------------------------------------------------------------------------------------------------------|
| `ERROR001` | `SAME_CODE_DIFFERENT_HTTP_STATUS`     | CONFLICT              | One error code is returned with more than one HTTP status (across or within services).                             |
| `ERROR002` | `SAME_CODE_INCOMPATIBLE_SCHEMA`       | CONFLICT              | One error code is returned with structurally different response schemas (property names, types, required fields). |
| `ERROR003` | `DESCRIPTION_MISMATCH`                | WARNING               | One error code has different response descriptions after normalization (case, whitespace, punctuation).           |
| `ERROR004` | `UNDOCUMENTED_ERROR_CODE`             | WARNING               | A `4xx`/`5xx` response exists but no error code can be extracted from its example or schema.                       |
| `ERROR005` | `DUPLICATE_OR_INCONSISTENT_DEFINITION`| WARNING / CONFLICT    | One service declares the same error code in several schema definitions — WARNING if they are identical (duplication), CONFLICT if they differ. |
| `REF001`   | `UNRESOLVED_REFERENCE`                | WARNING               | A remote or unresolvable `$ref` was skipped.                                                                       |
| `SPEC001`  | `NOT_AN_OPENAPI_DOCUMENT`             | INFO                  | A YAML/JSON file in the scanned directory is not an OpenAPI 3.x document and was skipped.                          |
| `GOV001`   | `EXCEPTION_EXPIRED`                   | CONFLICT              | An exception matching a current finding is past its `expires_at`.                                                  |
| `GOV002`   | `UNUSED_EXCEPTION`                    | WARNING               | An exception matches no current finding (fixed, or wrong matcher).                                                  |
| `GOV003`   | `EXCEPTION_EXPIRING_SOON`             | INFO                  | An active exception expires within `exception_expiry_warning_days`.                                                |
| `GOV004`   | `BASELINE_DEBT_RESOLVED`              | INFO                  | Baseline entries (or facets of them) no longer occur — run `baseline update`.                                      |

Schema comparison (`ERROR002`, `ERROR005`) uses a deliberately shallow *schema signature*: the set of top-level property names, their JSON types, and which of them are required. `allOf` members are merged; `oneOf`/`anyOf` branches are treated as separate variants.

## Configuration

Create `.api-error-catalog.yaml` next to your specs (or in the working directory), or pass `--config`:

```yaml
# Field names that carry the machine-readable error identifier, in priority order.
error_code_fields:
  - error_code
  - errorCode
  - code

# Glob patterns used to discover specification files (recursive).
include_patterns:
  - "*.yaml"
  - "*.yml"
  - "*.json"

# Error codes to leave out of the catalog and all rules.
ignore_error_codes: []

# Governance (optional) — see "Adopting in an existing codebase".
baseline: api-error-catalog.baseline.json
exception_expiry_warning_days: 14
exceptions: []
```

Error codes are looked up at the top level of the error payload first; nested envelopes such as `{"error": {"code": "..."}}` are searched up to three levels deep.

## Exit Codes

| Code | Meaning                                                          |
|------|------------------------------------------------------------------|
| `0`  | Scan completed. Either no enforced conflicts, or `--fail-on-conflict` not set. Warnings never fail the run. |
| `1`  | `--fail-on-conflict` was set and at least one enforced `CONFLICT` was found (new, expired exception, or `GOV001`). `baseline update --check`: the baseline lists fixed debt. |
| `2`  | Parsing or configuration error (malformed YAML/JSON, missing path, invalid config, invalid exception, missing or malformed baseline). |

## Example Project

[`examples/specs/`](examples/specs) contains three fully synthetic services — `auth-api.yaml`, `customer-api.yaml`, `payment-api.yaml` — that intentionally include:

- a clean code (`invalid_otp`, from a schema `enum`);
- `user_not_found` returned as `404` by one service and `400` by another (`ERROR001`);
- `rate_limit` with two different response schemas and different field names (`ERROR002`);
- `payment_declined` declared with OpenAPI 3.1 `const`;
- `4xx`/`5xx` responses without any error code (`ERROR004`);
- a duplicated inline definition of `customer_blocked` (`ERROR005`);
- a remote `$ref` (`REF001`).

`python scripts/build_examples.py` renders the three example reports into `examples/expected/` and the demo page into `docs/index.html`; CI builds and uploads them, and the Pages workflow publishes the HTML as the live demo.

## Architecture

```text
src/api_error_catalog/
├── cli.py            Typer CLI, exit codes
├── config.py         .api-error-catalog.yaml handling
├── loader.py         spec discovery, YAML/JSON parsing, OpenAPI 3.x detection
├── resolver.py       local $ref resolution (JSON pointers, cycles, remote refs)
├── extractor.py      operations → 4xx/5xx responses → ErrorOccurrence records
├── models.py         dataclasses: ErrorOccurrence, Issue, CatalogEntry, ScanResult
├── analyzer.py       orchestration: load → extract → catalog → rules
├── rules/            one module per rule (ERROR001…ERROR005)
├── governance/       fingerprints & facets, baseline file, exceptions → issue status (GOV001…GOV004)
└── reporters/        text, markdown, json, html (Jinja2 template in templates/)
```

The pipeline is `loader → resolver → extractor → rules → governance → reporters`. Every stage works on plain dataclasses, so new rules and reporters are single functions.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"

ruff check .            # lint
ruff format --check .   # formatting
pytest                  # tests
pytest --cov            # tests with coverage

api-error-catalog scan examples/specs
python scripts/build_examples.py   # render examples/expected/* and docs/index.html
```

## Roadmap

- Resolve remote and multi-file `$ref`s.
- Suppress individual findings inline (`x-error-catalog-ignore`).
- Governance policy knobs: maximum exception lifetime, required `ticket`, CODEOWNERS-validated `owner`.
- Naming-convention rule (e.g. enforce `snake_case` error codes) and near-duplicate detection (`user_not_found` vs `userNotFound`).
- SARIF output for GitHub code scanning; PR annotations pointing at the offending lines.
- PyPI release and pre-commit hook.

## Limitations

- Only OpenAPI 3.0.x / 3.1.x documents are analyzed; Swagger 2.0 and unrelated YAML/JSON files are skipped and listed as `INFO` (`SPEC001`).
- Only local `$ref`s (`#/...`) are resolved. Remote references are reported, not followed.
- Only JSON media types (`application/json`, `application/problem+json`, …) are inspected.
- The `default` response is not treated as an error response.
- Schema comparison is structural and shallow by design (top-level properties, types, required); it does not perform full JSON Schema compatibility checks.
- Error codes are matched on the exact string; `user_not_found` and `USER_NOT_FOUND` are different codes.

## License

[MIT](LICENSE)
