# Global expansion: status ledger

The ledger of the November 2026 global expansion: what was there at the start, what was built, what
was verified, and what remains. Every number below was produced by a command in this repository
on the date shown; nothing is projected.

## Baseline (start)

| Item | Value |
|---|---|
| Starting commit | `6c464e2` (2026-11-17 19:31 −04:00) |
| Live coverage | 10 countries, 22,880 series, 959 markets, 502,883 monthly prices (single-snapshot lake) |
| Studies | `sahel-production-weather-v1` (tag `protocol-sahel-v1`), confirmatory for Mali and Niger: no established improvement |
| Python tests | 185 collected at the start of the expansion (README then said 172; stale) |
| Production | API on Render Free, web on Vercel, Neon PostgreSQL index, $0/month |

## Phase status

| Phase | Status | Evidence |
|---|---|---|
| 0 Audit and ledger | done | this file |
| 1 Global data foundation | done | 95 of 95 HDX HAPI countries ingested (93 new snapshots, 2 unchanged on re-run); QC per country; registry for 244 areas; NASA POWER for 711 additional grid cells in 39 countries |
| 2 Research workbench | done | specs, validate/preview/freeze/run/verify/export/publish in the CLI; validation and study endpoints; `/workbench` builder |
| 3 Confirmatory flagship study | done | Forecastability Atlas v1: protocol tagged `protocol-atlas-v1` (`5ab8f82`), freeze recorded (`abea5d2`); 565 experiments, 0 failures; `research verify` passed; independent audit matched to 1.6e-15. Outcome: no improvement established (H1 0.981, H2 1.005); see [RESULTS.md](RESULTS.md) |
| 4 Researcher UI | done | `/atlas`, `/forecastability`, `/studies`, `/workbench`; existing pages unchanged |
| 5 CI, security, docs, deploy | see the final section | CI updated; docs listed below; deploy verification recorded below |
| 6 Advanced extensions | not started | deliberately deferred (see [ROADMAP.md](ROADMAP.md)) |

## Coverage registry (rebuilt 2026-11-18 10:53 UTC, after the atlas was published)

| Status | Countries |
|---|---|
| forecast_evaluated | 42 (39 atlas countries + Mali, Niger, Burkina Faso from the Sahel study) |
| research_eligible | 10 (eligible, but no qualifying cereal/tuber group in the atlas) |
| validated | 43 |
| ingested | 0 |
| temporarily_unavailable | 0 |
| discoverable | 0 |
| unsupported (no integrated price source) | 149 |

Totals: 95 countries with observations, 3,801,021 observations, 125,202 series, 4,835 markets,
19,920 eligible series. Partition storage 32 MB of Parquet.

## Sources

Integrated: HDX HAPI (WFP prices, all countries), NASA POWER (weather), and, as in v1.0, World Bank
WDI, IMF CPI/FX and FAOSTAT for the original countries. Investigated, not integrated: FAO FPMA,
FEWS NET, World Bank Pink Sheet, CHIRPS v3, geoBoundaries
([reasons](DATA_SOURCES.md#sources-investigated-but-not-integrated)).

## Integrity of the confirmatory study

1. The spec and protocol were committed and tagged `protocol-atlas-v1` before any atlas model ran.
2. `research freeze` ran on a clean tree at `853d3d7`; the freeze (groups, selection hash, snapshot
   hashes) was committed as `abea5d2` before estimation started.
3. No file of the experiment engine, feature builder, models or the workbench execution and pooling
   modules changed between the tag and the results commit (`git diff protocol-atlas-v1 -- <paths>`
   is empty; recorded in RESULTS.md).
4. Mali, Niger and Burkina Faso are excluded from the atlas because they informed earlier work.

## Performance (local: Apple M2, 8 cores, 8 GB; live data)

| Measurement | Value |
|---|---|
| `GET /api/v1/coverage/registry` | 94.7 KB raw, 7.0 KB gzip, median 5.0 ms |
| `GET /api/v1/coverage/registry/ETH` | 2.7 KB, median 3.0 ms |
| `GET /api/v1/coverage/markets` | 252 KB raw, 77 KB gzip, median 5.7 ms |
| `GET /api/v1/workbench/studies/{id}` (descriptive study) | 108 KB raw, 24 KB gzip, median 6.0 ms |
| `POST /api/v1/workbench/validate` (atlas spec) | 14 ms; 70 KB body rejected with 413 |
| API process memory | about 58 MB RSS after serving all of the above |
| Descriptive study run (95 countries) | 1.7 GB peak memory, which is why studies run locally ([ADR 0006](adr/0006-local-execution-published-summaries.md)) |
| Atlas run (113 groups × 5 variants, 6 workers) | 5 h 39 min wall clock, 1.49 GB peak resident memory of the parent process, 0 failures |
| Packaged production data | registry 444 KB, market index 252 KB, two study summaries 134 KB and 132 KB |

Request medians are over ten requests to a local uvicorn; production adds network latency and Render
cold starts.

## Documentation produced

[SYSTEMS_WALKTHROUGH](SYSTEMS_WALKTHROUGH.md) (with an annotated observation trace) ·
[RESEARCH_DESIGN_EXPLAINED](RESEARCH_DESIGN_EXPLAINED.md) (with an experiment walkthrough) ·
[ADRs](adr/README.md) · [MAINTAINER_RUNBOOK](MAINTAINER_RUNBOOK.md) ·
[exercises 6–10](../exercises/README.md) · [FORECASTABILITY_ATLAS_PROTOCOL](research/FORECASTABILITY_ATLAS_PROTOCOL.md) ·
[RESUME_EVIDENCE](RESUME_EVIDENCE.md) · [CHANGELOG](../CHANGELOG.md) · [CITATION.cff](../CITATION.cff)

## Deployment verification (2026-11-18)

Pushed `06e03eb` (results) and `86c4403` (CI fix) to `main` with a normal fast-forward push; tags
`protocol-atlas-v1` and `protocol-sahel-v1` pushed. CI run 44294319294 on `86c4403`: Python, Web,
end-to-end (demo) and Docker jobs all succeeded. The Web job had failed on every push since
`layout.tsx` adopted `LayoutProps`; `typecheck` now runs `next typegen` first.

| Check | Result |
|---|---|
| Render API `/api/v1/status` | version 1.1.0, mode live |
| `/api/v1/coverage/registry` | 200, packaged copy, 42 forecast-evaluated, 10 research-eligible, 43 validated, 149 unsupported |
| `/api/v1/workbench/studies` | both studies listed; atlas detail 200 (106 KB) |
| `POST /api/v1/workbench/validate` | atlas spec valid, hash `ad09ac46…` |
| Existing endpoints (`/health`, `/sources`, `/catalog/*`, `/studies`, `/experiments`) | 200 |
| CORS from an unknown origin | no `Access-Control-Allow-Origin` header |
| Vercel pages `/`, `/atlas`, `/forecastability`, `/studies`, `/workbench`, `/lab`, `/explorer` | 200; atlas and study data render; Lab shows the Sahel confirmatory results |

Observed during verification: for about a minute after the Render deploy, the new instance answered
before its data bundle had reinstalled, so `/api/v1/studies` returned `[]` and the Lab's study panel
showed "Loading study…" with 404s. It recovered without intervention. This is the existing Render
Free cold-start behaviour (ephemeral disk); the new endpoints are unaffected because they read
packaged files.
