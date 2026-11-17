# Execution status

Updated 2026-11-17. Branch `release/v1.0.0`. Supersedes the state described in
`docs/HANDOFF_FABLE_5_2.md` (kept as history).

## Where things stand

| Area | State | Evidence |
|---|---|---|
| Frontend / API integration | Done | All pages load real data with no console errors or horizontal overflow at desktop and phone widths; 7 live-data and 8 demo Playwright tests pass |
| Research integrity | Verified | Tag `protocol-sahel-v1` (4dd600f) precedes the confirmatory run; no model, feature, evaluation or study code changed between tag and results commit 57b1a3b; all 18 pooled comparisons recomputed independently (max discrepancy 4.4e-16) |
| Local database lineage | Done | `data/live_local.db` and a clean-install SQLite: revision 0002, 9 superseded runs, public listings exclude them |
| Neon (shared) database | Done (2026-11-17, owner-authorised) | Migrated 0001 → 0002 and synced: 77 experiment rows, no duplicates, 9 superseded, 0 pre-v1 runs current; the 7 prior rows kept verdict, config hash, conclusion and timestamp unchanged; an API pointed at Neon lists 11 current experiments and none superseded, and still serves an old run by id. Pre-migration backup: `data/backups/db_backup_rev0001_*.json` (local) |
| Production data | Done locally | `market-almanac bundle-export/install`; bundle `dist/market-almanac-live-data-20261117T114519Z.tar.gz` (SHA-256 `0963b87d0aed79bec156c0e323726147a01c729cc9b2bc656df3922b83ebd11d`) installed into a fresh clone and served the full app |
| Clean install | Done | Fresh `git clone`, `uv sync --frozen`, `npm ci`, migrations, demo seed, production build, standalone server, e2e |
| Docker | Not verified | Docker not installed on this machine |
| Git remote / publication | Not done | No remote configured; nothing pushed |
| Public deployment | Not done | No hosting configured or authorised; no live URL |
| Documentation | Done | README, RESULTS, REPRODUCIBILITY, DEPLOYMENT, DATA_SOURCES (redistribution), API, CHANGELOG 1.0.0, learning guide, portfolio, final report |

## Test results (2026-11-17, HEAD of `release/v1.0.0`)

```
uv run pytest -o addopts="" -m "not live"   172 passed, 6 deselected
uv run ruff check . / ruff format --check .  pass / 136 files formatted
uv run mypy packages apps/api/src            no issues in 69 files
npx tsc --noEmit / npx eslint src e2e        pass / pass
npx vitest run                               20 passed
E2E_MODE=live npx playwright test            7 passed (repeated 3 times)
playwright demo suite (clean-clone build)    8 passed
next build (clean clone)                     success, 12 static routes
```

## Next executable tasks (in order)

1. Create the GitHub repository, push `release/v1.0.0`, open a PR to `main`, let CI run (it has
   never run on GitHub).
2. Confirm the WFP licence on the HDX dataset page, then attach the data bundle to a GitHub release
   and record its URL and SHA-256 in the README.
3. Choose a host (for example one container host for the API with a persistent volume, and a static
   or Node host for the web app), set `DATA_BUNDLE_URL`, `DATA_BUNDLE_SHA256`, `DATABASE_URL`,
   `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`, deploy, then run the live e2e suite with
   `E2E_BASE_URL`/`E2E_API_URL` against the public URLs.
4. Run `docker compose up --build` once on a machine with Docker.
