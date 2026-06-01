# KubeSilence

> **AlertOps-Reducer** — Combat alert fatigue in CloudOps/DevOps environments.

KubeSilence ingests alerts from monitoring providers (Opsgenie, Datadog), analyzes them for duplicates, cascades, and noise, then automates remediation via provider APIs — all from a single CLI.

```text
┌─────────────┐    ┌──────────────┐    ┌──────────────────┐
│  Providers  │───▶│   Analytics  │───▶│   Remediation    │
│  (Ingest)   │    │   (Engine)   │    │   (Engine)       │
│             │    │              │    │                  │
│ • Opsgenie  │    │ • Dedup      │    │ • Silence rules  │
│ • Datadog   │    │ • Cascade    │    │ • Dry-run mode   │
│ • Mock      │    │ • Noise %    │    │ • Safety layer   │
└─────────────┘    └──────────────┘    └──────────────────┘
```

---

## Features

- **Unified Alert Schema** — Normalise alerts from any provider into a standardised Pandas DataFrame
- **Duplicate Detection** — RapidFuzz token-sort similarity + configurable time-window clustering
- **Cascade / Storm Detection** — Cross-service burst identification with root-cause suspect isolation
- **Dry-Run Safety** — Preview every silence payload before execution; nothing touches the API until you approve
- **Interactive CLI** — Rich terminal tables, Y/N confirmation prompts, and `--yes` for automation
- **Config Management** — Securely save provider API keys to `~/.config/kubesilence/.env`

---

## Quick Start

### Requirements

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) _(recommended)_ or pip

### Install

```bash
# Using uv (fastest)
uv sync
uv run kubesilence --version

# Or pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
kubesilence --version
```

### Run with mock data (no API keys needed)

```bash
# Analyze 10 realistic fixture alerts
kubesilence analyze mock --days 366

# Remediate (dry-run preview first, then apply with --yes)
kubesilence remediate mock --yes
```

### Connect a real provider

```bash
# Save your API key
kubesilence configure opsgenie --api-key "your-api-key"

# Analyze your real alerts
kubesilence analyze opsgenie --days 7
```

---

## CLI Reference

### `kubesilence analyze`

Fetch and analyze alerts, printed as Rich tables.

```bash
kubesilence analyze [PROVIDER] [OPTIONS]

Arguments:
  PROVIDER  Alert provider: mock, opsgenie, datadog  [default: mock]

Options:
  -d, --days INT          Look-back window in days  [default: 7, max: 366]
  -t, --threshold INT     Similarity threshold 0-100  [default: 85]
  -w, --window INT        Dedup time window in seconds  [default: 60]
  -V, --version           Show version and exit
  --help                  Show help
```

### `kubesilence remediate`

Analyze alerts, present a remediation plan, then interactively apply silence rules.

```bash
kubesilence remediate [PROVIDER] [OPTIONS]

Arguments:
  PROVIDER  Alert provider: mock, opsgenie, datadog  [default: mock]

Options:
  -d, --days INT   Look-back window in days  [default: 7]
  -y, --yes        Skip confirmation prompt  [default: False]
  --help           Show help
```

### `kubesilence configure`

Save provider API credentials to `~/.config/kubesilence/.env`.

```bash
kubesilence configure opsgenie --api-key "your-key"
kubesilence configure datadog --api-key "your-key" --app-key "your-app-key"
```

---

## Architecture

```
src/kubesilence/
├── __init__.py             # Package version
├── providers/              # Layer 1 — Data ingestion
│   ├── base.py             #   BaseAlertProvider (abstract ABC)
│   ├── mock.py             #   MockAlertProvider (10 fixtures)
│   ├── opsgenie.py         #   OpsgenieProvider (cursor pagination + retry)
│   └── datadog.py          #   DatadogProvider (scaffold)
├── analytics/              # Layer 2 — Intelligence engine
│   ├── parser.py           #   Alert Parser (normalise → DataFrame)
│   ├── deduplication.py    #   Fuzzy-matched time-window clustering
│   └── cascade.py          #   Cross-service burst / storm detection
├── remediation/            # Layer 3 — Automated fixing
│   ├── schema.py           #   SilenceRequest dataclass
│   └── engine.py           #   RemediationEngine (dry-run + execute)
└── cli/
    ├── __init__.py
    └── app.py              #   Typer CLI (analyze, remediate, configure)
```

### Core Mandates

| Principle | How it's enforced |
|-----------|------------------|
| **Strict Typing** | `SilenceRequest` dataclass + `STANDARD_FIELDS` DataFrame schema |
| **Idempotency** | Provider pagination never duplicates; silence requests are per-cluster |
| **Decoupling** | Engine knows only `AlertRecord` / `UOF` — never provider internals |
| **Auditability** | Every operation is a `dict` result; dry-run captures payloads before execution |

---

## Development

```bash
# Install in development mode
uv sync           # or: pip install -e ".[dev]"

# Run tests
python -m pytest                    # all tests
python -m pytest tests/ -v          # verbose
python -m pytest tests/ -k "parser" # specific module

# Run linting
ruff check src/                      # code style
ruff format src/ --check             # formatting
mypy src/                            # type checking
```

### Project State

Tracking is maintained in [`Project_state.md`](Project_state.md) and [`task_list.md`](task_list.md).

---

## Roadmap

- [x] Phase 1: Foundation & project scaffolding
- [x] Phase 2: Data ingestion (Mock, Opsgenie, Datadog providers)
- [x] Phase 3: Analytics engine (parser, dedup, cascade detection)
- [x] Phase 4: Remediation engine (SilenceRequest, dry-run safety)
- [x] Phase 5: CLI & Rich presentation tables
- [ ] Phase 6: CI/CD, GitHub Actions, OSS readiness ← **You are here**

---

## License

MIT
