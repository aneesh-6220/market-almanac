# Release v1.3 checklist

Persistent progress record for shipping v1.3 (Neon egress fix + Price Shock Investigator + `global-prices-v2`).
Updated after each milestone so work survives a context limit. Facts below were observed, not assumed.

| # | Step | State | Evidence |
|---|---|---|---|
| 1 | Establish state | done 2026-11-19 | `main` a91e5f5; PR #1 `fix/neon-quality-egress` and PR #2 `dev/price-shock-investigator` open, PR #1 an ancestor of PR #2; both CI green; `main` not protected; Render live a91e5f5 (v1.2.0), Vercel a91e5f5 |
| 2 | Verify and merge PR #1 | done | PostgreSQL SQL checked against the live report on Neon with count-only queries (22,880 series, 1,255 eligible, 31,504 extremes, meta 7 KB); merged as `aa7121b`; Render live `aa7121b`; `/status` 2.8 KB, `/data-quality?limit=1` 0.2 MB (was 20.9 MB) |
| 3 | v1.3 correctness fixes | done | inflation/currency, peer population, screening-rule wording, episode caveat, snapshot pin; regression tests in `tests/scientific/test_price_shocks.py` and `tests/integration/test_investigations_api.py`, web tests in `investigation-api.test.ts` |
| 4 | Build and verify `global-prices-v2` | done 2026-11-19 | clean-room rebuild from the pinned v1 snapshots: shock catalog 277,978 rows, content sha256 `1e8794f2…` identical to the local catalog (644 s, 4 workers); bundle 194 files = v1's 192 (all per-file SHA-256 identical, same snapshots) + `shock_catalog.parquet` and its manifest; attribution is WFP-only CC BY-IGO with the adaptation notice; no credentials found in a text and binary scan; installs into an empty `DATA_DIR` (194 written), a wrong SHA-256 is refused; real-data tests 30 passed, 2 skipped (research bundle not installed) |
| 5 | Publish release, pin URL and SHA-256 | done 2026-11-19 | https://github.com/aneesh-6220/market-almanac/releases/tag/global-prices-v2, tag target `246f589`; archive SHA-256 `e736b0279b3a0b983e079448c9bfd0bdeedf9e28294f9dc05e2e3b9b650f7540`, 29,489,666 bytes; the downloaded asset re-hashed to the same value; pinned in `prices_release.json`. GitHub does not make release assets provably immutable: integrity rests on the pinned hash |
| 6 | Merge PR #2 | done 2026-11-19 | CI green on the branch head `68a6b22` (six jobs); regular merge `3574746` (no force-push; contains PR #1's `aa7121b`); version bumped to 1.3.0 in `8a09601` so `/health` reports it; CI on `main` `8a09601` green (six jobs) |
| 7 | Deploy and verify production | done 2026-11-19 | Render `dep-dbvo6nrbc2fs73c6b9d0` (`3574746`), then the 1.3.0 deploy of `8a09601`: `/health` 1.3.0, `/ready` ready, start-up log `global price artefact installed` 194 files, 95 countries (v2), shock catalog `built_at` 22:55:54Z; Vercel `dpl_8hVwfE9FZJSBgrRhc6h9BQbnSGoE` (`8a09601`) READY. Real browser on https://market-almanac-app.vercel.app: `/investigate` lists 6,639 unusual food rises (95 countries), country, commodity and non-food filters, pagination (Niger imported rice 53 episodes, 3 pages), Maradi imported rice June 2024 (z +3.7, 18 of 22 assessable peers, 67 found, macro mechanism cannot be assessed), Ansongo millet Aug 2024 as the local contrast (2 of 30 assessable peers), stale pinned link shows the recovery message (API 409), md/json/csv exports 200, no page-level horizontal overflow at 375 px, no console errors other than the deliberate 409; Explorer, market page, Atlas, Lab, Study library, Workbench load. Not run: the live Playwright suite (it OOM-killed the 512 MiB instance in v1.2.0 verification) |
| 8 | Final report | done 2026-11-19 | in the session's final message |

## Neon (free plan, 5 GB egress per month, resets 2026-12-01)

- 2026-11-19, before the fix reached production: 4,696,861,549 bytes transferred (93.9%); compute active, not suspended.
- Neon's counter lags: it was unchanged after the fix deployed. Re-read it with `describe_project` before and after the
  production verification and record the delta here.
- 2026-11-19 after the production verification: 4,697,447,046 bytes (+585,497 over the earlier reading, about 0.6 MB across three deploys and the page checks); not suspended. The counter lags, so treat it as a lower bound.
- Budget rule: no production request that reads the database may be repeated in a loop; the investigator never touches Neon.

## Continuation

If this stops mid-release: read `git log --oneline -8` and `gh pr list`, then continue from the first `pending` row.
Build and publish commands are in [DEPLOYMENT.md](DEPLOYMENT.md#the-price-artefact-global-explorer).
