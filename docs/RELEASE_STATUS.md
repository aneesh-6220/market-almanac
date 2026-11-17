# Release status (as of 2026-11-16 audit)

| Status level | Met? | Evidence |
|---|---|---|
| Working demo | **Yes** | Synthetic demo mode; 73 Python tests, 20 frontend unit tests and TypeScript checks pass locally. The 8 Playwright tests were **not** re-run in this audit. |
| Live-data research prototype | **Yes** | Live HDX/POWER/IMF/WB/FAOSTAT snapshots; four BFA experiments re-run with identical input hashes. |
| Scientifically qualified research application | **Partially, with explicit qualifications** | No look-ahead found; inference correctly specified; one P0 numerical defect fixed. It is a **lag-assumption-based retrospective** backtest (not point-in-time / real-time). Supported claim: no detectable improvement from market-local weather in BFA, 2021–2026. See `docs/audits/SCIENTIFIC_VALIDITY_AUDIT.md`. |
| Independently reproducible open-source release | **No** | `data/` (lake snapshots, experiment artefacts) is untracked; live re-ingestion yields new vintages; no Git remote/push; `main` has no commits; Docker untested; CLI does not auto-migrate the DB. |
| Production-deployable service | **No** | Docker/compose never executed; no deployment performed or verified; the Neon DB still holds pre-audit experiment rows; no auth/rate-limit review in this audit. |

Do not describe ShockTrace as production-ready, real-time validated, or as having found a
weather effect.
