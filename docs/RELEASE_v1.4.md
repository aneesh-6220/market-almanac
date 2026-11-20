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
| 7 | Publish the metadata-only artefact, pin URL and SHA-256 | pending | `economic-context-v1`, SHA-256 `a2f540200927066b03f540481ef2973c06600108d56a7ff95781a7144af107ae`, 45,860 bytes; no IMF or World Bank observations (`data_included: none`) |
| 8 | Push branch, CI, merge to `main` without force | pending | |
| 9 | Deploy and verify production | pending | expect a `metadata_only` section, v1.3 behaviour unchanged |

## Licensing decision

The observations of the IMF and World Bank series are **not** published in the public artefact: redistribution of
the data in bulk is not confirmed (see [DATA_SOURCES.md](DATA_SOURCES.md#redistribution-public-data-bundle)).
Production therefore shows the economic section as `metadata_only` until the operator installs the full artefact
privately or the providers' permission is on record. The worked examples contain derived percentages only.

## Neon (free plan, 5 GB egress per month, resets 2026-12-01)

Baseline before v1.4 work: 4,698,390,295 bytes (4.70 GB, 2026-11-20 00:36Z). The economic context never touches the
database. Readings after deployment are recorded below.
