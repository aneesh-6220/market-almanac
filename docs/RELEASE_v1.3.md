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
| 6 | Merge PR #2 | pending | |
| 7 | Deploy and verify production | pending | |
| 8 | Final report | pending | |

## Neon (free plan, 5 GB egress per month, resets 2026-12-01)

- 2026-11-19, before the fix reached production: 4,696,861,549 bytes transferred (93.9%); compute active, not suspended.
- Neon's counter lags: it was unchanged after the fix deployed. Re-read it with `describe_project` before and after the
  production verification and record the delta here.
- Budget rule: no production request that reads the database may be repeated in a loop; the investigator never touches Neon.

## Continuation

If this stops mid-release: read `git log --oneline -8` and `gh pr list`, then continue from the first `pending` row.
Build and publish commands are in [DEPLOYMENT.md](DEPLOYMENT.md#the-price-artefact-global-explorer).
