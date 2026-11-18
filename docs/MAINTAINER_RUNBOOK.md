# Maintainer runbook

Operational procedures for the global data platform and research workbench. Every command runs from
the repository root. `MARKET_ALMANAC_MODE=live` selects real data; without it the commands use the
synthetic demo lake. `HDX_APP_IDENTIFIER` must be set in `.env` (never commit it).

## 1. Refresh global prices

```bash
MARKET_ALMANAC_MODE=live uv run market-almanac global discover        # which countries HDX HAPI lists
MARKET_ALMANAC_MODE=live uv run market-almanac global ingest           # all discovered countries
MARKET_ALMANAC_MODE=live uv run market-almanac global status           # latest run summary
```

- A run log is written to `data/global/live/runs/<run_id>.json` after every country.
- If the run stops (network, sleep, Ctrl-C): `global ingest --resume <run_id>`. Succeeded and
  unchanged countries are skipped; failed ones are retried up to three attempts.
- `unchanged` means the provider returned exactly the observations already stored (the
  `observation_hash` matched). No snapshot is written.
- A country whose QC is blocking (schema error, future dates, more than 5% invalid rows or more than
  10% conflicting duplicates) is stored but not `validated`. Read its manifest's `qc.problems`.

## 2. Refresh weather for a study population

```bash
MARKET_ALMANAC_MODE=live uv run market-almanac global weather --spec docs/research/specs/<spec>.yaml
```

NASA POWER rate-limits (HTTP 429). The command fails a country if more than 20% of its grid cells
fail; resume it with `--resume <run_id>`. **Do not freeze a confirmatory study until every country
in it has weather**; the freeze records the weather snapshots it saw.

## 3. Rebuild and ship the coverage registry

```bash
MARKET_ALMANAC_MODE=live uv run market-almanac global registry --package
```

This rewrites `data/public/live/coverage_registry.json`, `coverage_markets.json` and the packaged
copies in `packages/market-almanac/src/market_almanac/globaldata/`. Commit the packaged copies; the
production API serves them. Check the diff: a country should not lose a status without a reason (QC,
a failed run, a superseded evaluation).

## 4. Run a study

```bash
uv run market-almanac research validate docs/research/specs/<id>.yaml
MARKET_ALMANAC_MODE=live uv run market-almanac research preview docs/research/specs/<id>.yaml
# confirmatory only: commit the spec, make sure the tree is clean, then
MARKET_ALMANAC_MODE=live uv run market-almanac research freeze docs/research/specs/<id>.yaml
git tag protocol-<short-name>-v1         # before running anything
MARKET_ALMANAC_MODE=live uv run market-almanac research run docs/research/specs/<id>.yaml --workers 6
MARKET_ALMANAC_MODE=live uv run market-almanac research verify data/studies/live/<id>
```

- Runs are resumable: experiments already written with the same configuration hash are reused.
- For a predictive study, also run the independent audit:
  `uv run python scripts/audit/recompute_atlas.py data/studies/live/<id>` (exit 1 on any discrepancy
  of 1e-9 or more).

## 5. Publish a study

```bash
MARKET_ALMANAC_MODE=live uv run market-almanac research publish docs/research/specs/<id>.yaml --package
```

Commit `packages/market-almanac/src/market_almanac/research/published/<id>.json`. Rebuild the
registry (section 3) so evaluated countries show `forecast_evaluated`. Record the outcome in
`docs/RESULTS.md`, including null results, without editing earlier results.

## 6. Correcting a published result

Never edit a published summary or a frozen spec in place. Fix the code, create a new spec id
(`<id>-v2`), re-freeze, re-run, publish, and add a dated note to `docs/RESULTS.md` explaining what
changed and why. Superseded experiments stay on disk with `superseded_by`.

## 7. Deploy

Pushing to `main` deploys the API on Render and the web app on Vercel. A successful push is not a
successful deploy. Check both:

```bash
curl -s https://market-almanac.onrender.com/api/v1/status | python3 -m json.tool | head
curl -s https://market-almanac.onrender.com/api/v1/coverage/registry | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['generated_at'], d['counts'])"
curl -s https://market-almanac.onrender.com/api/v1/workbench/studies | python3 -m json.tool | head -20
```

Render Free sleeps after inactivity; the first request can take about a minute. Then open
https://market-almanac-app.vercel.app/atlas, `/forecastability`, `/studies`, `/workbench` and `/lab`.

**Rollback:** revert the commit on `main` and push (never force-push). Render and Vercel redeploy the
previous state. Packaged JSON files are the only production data, so a revert fully restores them.

## 8. Incidents

| Symptom | Likely cause | Action |
|---|---|---|
| `/coverage/registry` returns 404 in production | packaged registry missing from the image | rebuild with `--package`, commit, push |
| HDX requests fail with 401/403 | app identifier missing or revoked | check `.env` locally and the Render environment variable |
| HAPI pagination returns the same page twice | provider bug; the client raises instead of looping | retry later; the run resumes |
| Schema drift error during ingest | HAPI changed a field | update `providers/hdx_hapi.py` and its contract test; do not loosen the check silently |
| Study run killed by memory | too many workers | lower `--workers`; each worker holds one group |

## 9. Secrets

`.env` holds the HDX app identifier and the Neon `DATABASE_URL`. Never print it, commit it or paste
it into an issue. CI uses repository secrets only for deploy hooks. If a secret leaks, rotate it at
the provider first, then remove it from history with the provider's guidance; do not force-push
`main` without agreement.
