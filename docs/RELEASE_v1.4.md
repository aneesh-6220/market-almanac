# Release v1.4 checklist (Economic Context Engine)

Persistent progress record for shipping v1.4. Facts below were observed, not assumed; rows marked "pending" were not
done when this was written and are updated as each is.

| # | Step | State | Evidence |
|---|---|---|---|
| 1 | Establish state | done 2026-11-19 | `main` and the v1.3.0 deployment unchanged; work on `dev/economic-context-engine`; Neon at 4.70 / 5 GB so no development used the production database |
| 2 | Source research and coverage matrix | done | [ECONOMIC_CONTEXT_COVERAGE.md](ECONOMIC_CONTEXT_COVERAGE.md) (95 price countries: 94 in the IMF, 38 full macro) |
| 3 | Ingestion, snapshots, validation | done | `market-almanac context refresh`; snapshot `20261120T004928_ba3846` verifies; 783 series |
| 4 | Engine, evidence, API, UI, exports | done | see [ECONOMIC_CONTEXT.md](ECONOMIC_CONTEXT.md) |
| 5 | Tests | done locally | ruff, mypy (112 files), pytest, web typecheck, eslint, vitest (60) all pass; Playwright demo and live suites run in CI |
| 6 | Worked investigations on real data | done | [Niger](examples/economic-context-niger-imported-rice-2024-06.md), [Lebanon](examples/economic-context-lebanon-sunflower-oil-2021-04.md), [Mozambique](examples/economic-context-mozambique-imported-rice-2022-10.md) |
| 7 | Publish the full artefact, pin URL and SHA-256 | done 2026-11-20 | `economic-context-v2`, SHA-256 `2cc2eac8e49f67682854026c9a6cf8f5e47b4892a978162f957475c4fd1b8820`, 860,620 bytes, snapshot `20261120T134942_14798b`, 138,977 observations, 703 series with data (`data_included: full`) |
| 8 | Push branch, CI, merge to `main` without force | pending | |
| 9 | Deploy and verify production | done 2026-11-20 | `/api/v1/context` serves `20261120T134942_14798b`; Maradi, Lebanon and Mozambique investigations return `status: ok` with real values, Markdown and CSV exports 200; Neon `data_transfer_bytes` 4,698,524,480 before and after (no context reads) |

## Licensing decision

Superseding the 2026-11-20 morning decision (metadata-only): the operator confirmed in writing in the release request
that they hold the necessary rights to acquire and publicly distribute the IMF and World Bank datasets. The artefact
therefore includes the observations, with the attribution and third-party notices of the sources preserved, and the
licence records in the snapshot manifest say `confirmed` (operator-attested). The bundle policy that withholds a source
whose record is not `confirmed` is unchanged. Startup now upgrades a metadata-only snapshot from the pinned artefact.

## Neon (free plan, 5 GB egress per month, resets 2026-12-01)

Baseline before v1.4 work: 4,698,390,295 bytes (4.70 GB, 2026-11-20 00:36Z). The economic context never touches the
database. Readings after deployment are recorded below.
