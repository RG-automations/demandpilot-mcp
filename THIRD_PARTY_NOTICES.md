# Third-Party Notices

DemandPilot MCP's own source code is licensed under AGPL-3.0-only (see
[`LICENSE`](LICENSE) / [`LICENSING.md`](LICENSING.md)). The dependencies listed below keep their
own, separate licenses - using them does not place their code under AGPL, and this project
claims no ownership over them.

**Source of this audit**: a disposable, isolated virtual environment built only from
`requirements-dev.txt` plus an editable install of this project (Python 3.14.4) - not the
project's own development `.venv`, to keep unrelated tooling out of the measurement. Inspected
with `pip-licenses==5.5.5` and `pipdeptree` (both one-off audit tools, installed only in that
disposable environment, not project dependencies themselves). **Post-audit correction
(POST_AUDIT_REPORT.md, finding M5)**: an earlier version of this document and of
`FINAL_REPORT.md` attributed this audit to `pip-licenses`/`pipdeptree` while those tools were not
actually present in the environment being described; this run genuinely used them, in a clean
environment, and reproduces the same 47-package, zero-copyleft result as before - the dependency
closure and license conclusion were already correct, only the stated methodology was wrong.
**This is an automated license-metadata report, not a legal opinion**; license classification is
as declared in each package's own metadata.

## Runtime dependencies (installed when you `pip install demandpilot`)

Direct dependencies are `mcp`, `statsmodels`, and `numpy` (see `requirements.txt`); everything
else below is pulled in transitively by those three.

| Package | Version | License | Notes |
|---|---|---|---|
| mcp | 2.3.0 | MIT | Direct dependency (MCP SDK) |
| mcp-types | 2.3.0 | MIT | transitive (mcp) |
| statsmodels | 0.15.0 | BSD-3-Clause | Direct dependency |
| numpy | 2.5.5 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Direct dependency; multi-licensed bundle, all permissive |
| scipy | 1.18.1 | BSD License | transitive (statsmodels) |
| pandas | 3.1.1 | BSD-3-Clause | transitive (statsmodels) |
| patsy | 1.0.3 | BSD License | transitive (statsmodels) |
| formulaic | 1.2.2 | MIT | transitive (statsmodels) |
| interface_meta | 2.0.1 | MIT | transitive (formulaic) |
| narwhals | 2.29.0 | MIT | transitive (formulaic) |
| python-dateutil | 4.0.0 | BSD-3-Clause | transitive (pandas) |
| tzdata | 2026.6 | Apache-2.0 | transitive (python-dateutil) |
| wrapt | 2.6.0.dev1 | BSD-2-Clause | transitive (formulaic) |
| packaging | 26.4 | Apache-2.0 OR BSD-2-Clause | transitive (statsmodels, patsy) |
| anyio | 4.16.0 | MIT | transitive (mcp) |
| idna | 3.20 | BSD-3-Clause | transitive (anyio, httpx2) |
| typing_extensions | 4.16.0 | PSF-2.0 | transitive (mcp, pydantic, ...) |
| httpx2 | 2.16.2 | BSD-3-Clause | transitive (mcp) |
| httpcore2 | 2.16.2 | BSD-3-Clause | transitive (httpx2) |
| h11 | 0.16.0 | MIT | transitive (httpcore2, uvicorn) |
| truststore | 0.10.5 | MIT | transitive (httpx2, httpcore2) |
| jsonschema | 4.26.0 | MIT | transitive (mcp) |
| attrs | 26.1.0 | MIT | transitive (jsonschema, referencing) |
| jsonschema-specifications | 2025.9.1 | MIT | transitive (jsonschema) |
| referencing | 0.37.0 | MIT | transitive (jsonschema-specifications) |
| rpds-py | 2026.9.1 | MIT | transitive (jsonschema, referencing) |
| pydantic | 2.14.4 | MIT | transitive (mcp-types) |
| annotated-types | 0.8.0 | MIT | transitive (pydantic) |
| pydantic_core | 2.50.5 | MIT | transitive (pydantic) |
| typing-inspection | 0.4.5 | MIT | transitive (pydantic) |
| opentelemetry-api | 1.45.2 | Apache-2.0 | transitive (mcp) |
| PyJWT | 2.15.1 | MIT | transitive (mcp) |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | transitive (PyJWT, `crypto` extra) |
| cffi | 2.1.1 | MIT-0 | transitive (cryptography) |
| pycparser | 3.12 | BSD-3-Clause | transitive (cffi) |
| python-multipart | 0.0.34 | Apache-2.0 | transitive (mcp) |
| sse-starlette | 3.7.1 | BSD-3-Clause | transitive (mcp) |
| starlette | 1.10.0 | BSD-3-Clause | transitive (sse-starlette) |
| uvicorn | 0.54.0 | BSD-3-Clause | transitive (mcp) |
| click | 8.5.1 | BSD-3-Clause | transitive (uvicorn) |

## Development-only dependencies (never distributed with the installed package)

| Package | Version | License | Notes |
|---|---|---|---|
| pytest | 9.2.0 | MIT | test runner |
| pytest-cov | 7.1.0 | MIT | coverage plugin |
| coverage | 7.17.5 | Apache-2.0 | transitive (pytest-cov) |
| iniconfig | 2.3.1 | MIT | transitive (pytest) |
| pluggy | 1.7.0 | MIT | transitive (pytest) |
| Pygments | 2.21.0 | BSD-2-Clause | transitive (pytest) |
| ruff | 0.17.6 | MIT | linter/formatter |

## Audit result

**No copyleft license (GPL, LGPL, AGPL, or similar) appears anywhere in the runtime or
development dependency closure.** Every entry above is a permissive license (MIT, MIT-0,
BSD-2-Clause, BSD-3-Clause, Apache-2.0, 0BSD, Zlib, CC0-1.0, PSF-2.0, or a dual-license
combination of these).

**Implications for AGPL distribution of DemandPilot's own code**: none of these licenses
restrict distributing them alongside AGPL-licensed code, and none of them require DemandPilot's
own code to adopt their license. Their standard obligation is attribution: preserving their
copyright and license notices when redistributing the software (satisfied by this notices file
plus each package's own license, obtainable from its project page or PyPI metadata; this project
does not vendor or modify any dependency's source).

**Implications for a future commercial license**: because every dependency is permissively
licensed, none of them block the copyright holder from also offering DemandPilot's own code
under a separate commercial license (see `COMMERCIAL_LICENSE.md`). A permissive dependency
license does not grant *this project* any extra relicensing rights over the dependency itself -
it only means using that dependency does not *prevent* DemandPilot's own code from being
dual-licensed.

**Not a substitute for legal review**: this is a metadata-based audit, not a professional legal
opinion. It should be re-verified (and reviewed by a qualified lawyer) before any commercial
licensing decision or public release that relies on it.
