# DemandPilot MCP

A local [Model Context Protocol](https://modelcontextprotocol.io) server that lets an AI agent
analyze synthetic sales history, forecast demand, monitor inventory, detect stockout risk, and
recommend replenishment quantities - using deterministic Python business logic, not LLM
arithmetic.

## What problem this addresses

Demand planners routinely repeat the same analysis: pull recent sales, forecast near-term
demand, check current stock against that forecast, and decide whether (and how much) to reorder,
respecting minimum order quantities and pack sizes. DemandPilot MCP packages that workflow as
five tools an AI agent can call directly, so the agent orchestrates the analysis while every
number comes from auditable, testable Python code.

## What this is - and is not

This is a **portfolio / demonstration decision-support system** built on **entirely synthetic
data**. It is not connected to, and does not reproduce, any real company's sales or inventory
data. It is not production software, not "enterprise-grade," and does not guarantee forecasting
accuracy or stock availability. It never places an order or writes to its database - every tool
is read-only and advisory.

## Key features

- Five read-only MCP tools: sales history, demand forecasting, inventory snapshot, stockout-risk
  scan across the whole catalog, and replenishment recommendation.
- Holt-Winters forecasting with an explicit, never-hidden fallback hierarchy (Seasonal Naive ->
  historical mean -> zero-demand -> insufficient-history), chronological backtesting, and
  Monte Carlo prediction intervals.
- A documented (R, S) periodic-review replenishment model: protection period, safety stock,
  target stock level, MOQ and pack-size rounding.
- Rule-based (not statistical-probability) stockout risk classification.
- A deterministic synthetic data generator covering 10 demand-profile scenarios and 7
  inventory scenarios (including incoming orders and reservations) across 20 demo SKUs.
- 101 automated tests, including real subprocess + official-client MCP protocol tests.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full layer breakdown, data flow, and a
sequence diagram. In short: `server.py` (MCP layer) -> `logic/` + `forecasting/` (pure business
logic) -> `data/` (parameterized, read-only SQLite access).

## Tech stack

| Area | Technology |
|---|---|
| Language | Python 3.12+ (developed and tested locally on 3.14; CI matrix covers 3.12/3.13/3.14) |
| Protocol | Model Context Protocol, official `mcp` SDK, `MCPServer` (see note below) |
| Transport | stdio only |
| Database | SQLite via stdlib `sqlite3`, opened read-only by the server |
| Forecasting | `statsmodels` (Holt-Winters) + `numpy` |
| Testing | `pytest`, `pytest-cov` |
| Linting / formatting | `ruff` |
| Secret scanning | Gitleaks (see Security and Privacy) |

**Note on the SDK class name**: the original specification named
`mcp.server.fastmcp.FastMCP`. In the pinned `mcp==2.3.0` release, that class was renamed to
`MCPServer` (`from mcp.server import MCPServer`) in the SDK's v2 line. This project uses
`MCPServer`; the decorator API (`@server.tool()`, `@server.resource()`, `@server.prompt()`) and
behavior are otherwise identical to what was specified. This project does **not** declare "zero
runtime dependencies" - it has three direct runtime dependencies (`mcp`, `statsmodels`, `numpy`)
plus their transitive dependencies.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
python -m pip install -e .

python -m demandpilot.data_gen --seed 42 --reference-date 2026-01-01 --db ./demo.sqlite3

python -m demandpilot --db ./demo.sqlite3
```

The server will not start without an existing database file, and it never generates one
automatically; run the generator first. It will not overwrite an existing database unless you
pass `--overwrite` to the generator.

## Installation (development)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

## Generating the demo database

```bash
python -m demandpilot.data_gen \
  --seed 42 --reference-date 2026-01-01 \
  --sku-count 20 --history-days 730 \
  --db ./demo.sqlite3 [--overwrite]
```

All data is deterministic for a given `--seed`: the same seed always produces the same database;
a different seed produces different (but still internally consistent) data. The dataset is
explicitly marked synthetic in its own `dataset_metadata` table and in the `demandpilot://catalog`
resource.

## Running the MCP server

```bash
python -m demandpilot --db ./demo.sqlite3
```

Communicates over stdio only. All logs go to stderr; nothing but MCP protocol frames is ever
written to stdout.

## Claude Desktop configuration

See [`examples/claude_desktop_config.json`](examples/claude_desktop_config.json) (replace the
placeholder paths with your actual project path, then add it to your Claude Desktop config under
`mcpServers`).

## Claude Code configuration

See [`examples/claude_code_config.json`](examples/claude_code_config.json) - put it (with real
paths) at `.mcp.json` in a project, or register it with `claude mcp add`.

Neither example was used to modify any real local Claude Desktop/Code configuration during
development; they are example files only. Protocol-level communication was verified with the
official `mcp` Python client (`ClientSession` + `stdio_client`) over a real subprocess - this is
not the same as testing inside the actual Claude Desktop or Claude Code applications, which was
not done.

## The five MCP tools

| Tool | Parameters | Returns |
|---|---|---|
| `get_sales_history` | `sku`, `days` (1-730) | Daily sales records for one SKU |
| `forecast_demand` | `sku`, `horizon_days` (1-90) | Forecast, model used, prediction interval, backtest metrics |
| `get_inventory` | `sku` | Current stock snapshot and logistics parameters |
| `detect_stockout_risk` | `horizon_days` (1-90) | Risk-ranked list across the whole catalog |
| `recommend_replenishment` | `sku` | Advisory order-quantity recommendation (never places an order) |

## The resource

`demandpilot://catalog` - read-only JSON listing of all demo SKUs, their demand profiles, and the
dataset's seed/reference date/generator version, explicitly marked `is_synthetic: true`.

## The prompt

`weekly-replenishment-report` - guides an AI client through an 8-step stockout review and
replenishment report, instructing it to use only tool results (never invent or recompute
figures) and to present the result as advisory, human-reviewed output.

## Example business scenario

See [`docs/DEMO.md`](docs/DEMO.md) for a full walk-through with real tool responses.

## Example real tool responses

See [`examples/sample_responses/`](examples/sample_responses/) for actual JSON responses
captured from a running server (seed 42, reference date 2026-01-01), including a case where the
Seasonal Naive baseline outperforms Holt-Winters, a short-history fallback case, and a
zero-demand case.

## Forecasting methodology

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md): Holt-Winters, Seasonal Naive, the fallback
hierarchy, chronological backtesting, MAE/WAPE/Forecast Bias, and prediction intervals, explained
for a Supply Chain audience.

## Replenishment methodology

Also in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md): the (R, S) periodic-review model
(protection period, safety stock, target stock level, MOQ/pack-size rounding), stockout risk
rules, and one fully hand-calculated example that matches the unit tests exactly.

## Running the tests

```bash
python -m pytest tests/ -v
python -m pytest tests/ --cov=demandpilot --cov-report=term-missing
```

## Real local verification results

Measured on this machine (Python 3.14.4, `mcp==2.3.0`, `statsmodels==0.15.0`):

- `pytest tests/` - **101 passed**, 0 failed (6 database, 17 data-generator, 11 evaluation,
  14 forecasting, 9 inventory-logic, 26 replenishment-logic, 14 real-subprocess MCP integration,
  4 server edge cases). Grown from an original 90 through two rounds of audit-driven regression
  tests (9 from an independent pre-publication audit, 2 from a later focused fix).
- `ruff check .` - all checks passed.
- `ruff format --check .` - all files already formatted.
- Full details and coverage numbers were captured in an internal audit report, kept as a local
  working document and not included in this repository.

## Security and Privacy

- All data is synthetic; no real companies, customers, or personal data are used anywhere.
- No API keys, tokens, passwords, or external service accounts are required.
- No network access during normal operation (data generation and server startup are both fully
  offline).
- The server opens the database with `sqlite3 mode=ro` - a write attempted through that
  connection fails at the SQLite level, not just by application convention.
- All SQL is parameterized; no user-supplied value is ever concatenated into a SQL string.
- No tool argument can specify an arbitrary file path; the database path is fixed once at process
  startup from `--db`.
- Logs go to stderr only; stdout carries only MCP protocol frames.

## Limitations

See the "Documented limitations" section of [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the
complete list (fixed lead time, no delivery scheduling, no lost-demand estimation, single fixed
backtest window, synthetic data only, etc.).

## Licensing

DemandPilot MCP is available under a dual-licensing model:

**Open Source - AGPL-3.0**

The project's own code is available under the GNU Affero General Public License v3.0
(`AGPL-3.0-only`, full unmodified text in [`LICENSE`](LICENSE)). You may use, study, modify, and
distribute the software, including for commercial purposes, subject to the terms of the
AGPL-3.0 - most notably, that a modified version operated as a network-accessible service must
offer its users the Corresponding Source (AGPL section 13). Merely running the server yourself,
or connecting an MCP client to it, carries no obligation at all. See
[`LICENSING.md`](LICENSING.md) for a full explanation of what AGPL does and does not require.

**Commercial Licensing**

Organizations requiring alternative licensing terms, proprietary integrations, closed-source
modifications, or commercial redistribution arrangements may contact the copyright holder to
discuss a separate commercial license - see [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md).
**A commercial license is not automatically granted by downloading, installing, or using this
repository.**

Third-party dependencies keep their own (permissive) licenses - see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the full audit. Contribution and CLA
expectations are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

The commercial-licensing contact in [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md) is
`kontakt@splotix.pl`. No other file in this repository names a copyright holder at all (not even
as a placeholder) - `LICENSE`, `LICENSING.md`, and this README only ever say "the copyright
holder" generically, which AGPL-3.0 does not require to be a specific name. All of this should
still be reviewed by a qualified lawyer before any public release or commercial use.
