# Release status (v1.0.0, 2026-11-17)

| Level | Met? | Evidence |
|---|---|---|
| Local working prototype | Yes | Demo and live modes run locally |
| Functional integrated application | **Yes** | Every page uses the live API; 7 live-data and 8 demo browser tests; production build; outage handling tested |
| Research-qualified application | **Yes, with stated qualifications** | Protocol tag precedes confirmatory runs; leakage guards tested; study tables independently recomputed; superseded results excluded by default. Qualification: lag-assumption-based retrospective backtests, not real-time |
| Reproducible open-source release | **Not yet** | Clean-clone install, demo and data-bundle install all verified locally, but there is no Git remote, CI has never run on GitHub and the data bundle is not published |
| Publicly deployed operational product | **No** | No deployment; Docker images never built (the shared Neon database is migrated and current) |

Do not describe Market Almanac as deployed, real-time validated, or as having found a weather effect.
Details: [FINAL_ENGINEERING_REPORT.md](FINAL_ENGINEERING_REPORT.md).
