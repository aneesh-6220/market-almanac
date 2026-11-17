# Data sources

All five providers are implemented, tested against recorded real responses
(`data/fixtures/`), and were **live-verified on 2026-11-16** (health checks and real ingestion for
Burkina Faso). FAOSTAT's authenticated API was live-verified while a token was valid; its token
then expired, and live agricultural data were ingested from FAOSTAT's public bulk file.

The provider's verification state is visible in the app (`/data`) and at `GET /api/v1/sources`:
`live_verified` is shown only after a successful live health check or a non-empty live
ingestion, never from mocked tests.

| | HDX HAPI (WFP prices) | NASA POWER | World Bank | IMF | FAOSTAT |
|---|---|---|---|---|---|
| Role | Target series and price features | Weather anomalies (family B) | Annual context | CPI and FX (family C) | Production, yield, area (family D) |
| Endpoint | `https://hapi.humdata.org/api/v2/food-security-nutrition-poverty/food-prices-market-monitor` (+ metadata endpoints) | `https://power.larc.nasa.gov/api/temporal/daily/point` | `https://api.worldbank.org/v2/country/{iso3}/indicator/{code}` | `https://api.imf.org/external/sdmx/2.1/data/{agency},{flow}/{key}` | `https://faostatservices.fao.org/api/v1` (token) or bulk zip at `bulks-faostat.fao.org` |
| Auth | App identifier (header `X-HDX-HAPI-APP-IDENTIFIER`) | None | None | None | Bearer token or username/password (API); none (bulk) |
| Frequency | Monthly | Daily → monthly | Annual | Monthly | Annual |
| Spatial unit | Market (lat/lon) | 0.5° × 0.625° grid cell | Country | Country | Country |
| Licence | HDX terms; WFP data CC BY-IGO | Public (cite NASA POWER) | CC BY 4.0 | IMF terms of use | CC BY 4.0 |

## HDX HAPI — WFP food prices

- Pagination: 10,000 rows per page, up to 200 pages; app identifier sent as a header (never in
  URLs, logs or cache keys).
- Reference periods run from the 15th to the 14th; observations are labelled with the month of
  `reference_period_start`.
- Kept per record: market, admin areas, coordinates, commodity and category, unit, price type,
  price flag, currency, price, source reference, retrieval time. Publication date is unknown
  (left empty, not inferred).
- Records with non-positive or non-numeric prices are flagged `invalid_price`; conflicting
  duplicates are flagged `duplicate_conflict`.

## NASA POWER — daily agroclimatology

- Parameters `PRECTOTCORR` (mm/day), `T2M`, `T2M_MAX`, `T2M_MIN` (°C), community `AG`, explicit
  time standard.
- Coordinates are snapped to the POWER grid so markets in the same cell share one request and
  one `location_id` (`wx_{lat}_{lon}`).
- Fill values (−999) become missing and are reported as warnings; unit metadata is checked.
- Monthly aggregation: rainfall total, mean temperatures, days with Tmax ≥ 35 °C; months with
  fewer than 90% of days are marked incomplete and excluded from features.
- Caveat: this is a geographic proxy at the market, not the production area.

## World Bank Indicators API

Indicators: `SP.POP.TOTL`, `SP.POP.GROW`, `NY.GDP.PCAP.KD`, `NY.GDP.MKTP.KD.ZG`,
`FP.CPI.TOTL.ZG`, `AG.PRD.FOOD.XD`, `NV.AGR.TOTL.ZS`. Error payloads (e.g. an invalid indicator)
raise `DatasetNotAvailable`. Annual values are context only and never interpolated to months.

## IMF SDMX 2.1

- `IMF.STA,CPI` `{ISO3}.CPI._T.IX.M` — headline CPI index, monthly.
- `IMF.STA,CPI` `{ISO3}.CPI.CP01.IX.M` — food and non-alcoholic beverages CPI index.
- `IMF.STA,ER` `{ISO3}.XDC_USD.PA_RT.M` — national currency per USD, period average.
- Observations without `OBS_VALUE` are missing, not zero. A series the IMF does not publish for a
  country is reported unavailable, not replaced with another measure (e.g. food CPI for Burkina
  Faso).
- Release lags applied: CPI 2 months, exchange rate 1 month.

## FAOSTAT — Crops and livestock products (QCL)

- API: area/item/element queries with a bearer token (JWT expiry is checked before use) or a
  login with username/password.
- Bulk fallback: the normalised QCL zip (no credentials), filtered locally to the country.
- Elements: production (5510, t), area harvested (5312, ha), yield (5412, kg/ha in current
  releases).
- Commodity mapping (`COMMODITY_TO_FAO_ITEM`) links WFP commodity names to FAO items by keyword,
  e.g. maize → 56, sorghum → 83, millet → 79, rice → 27, cowpeas (niébé) → 195. Unmapped
  commodities get no family-D features.
- FAOSTAT country codes come from a reference table generated from FAOSTAT definitions
  (`providers/faostat_areas.csv`, 244 areas).
- Annual values are usable from December of the following year.

## Redistribution (public data bundle)

The public data bundle (`shocktrace bundle-export`) redistributes derived snapshots of these
sources. Checked 2026-11-17; confirm before each publication:

| Source | What the terms allow | Status |
|---|---|---|
| WFP food prices via HDX | HDX's licence guidance: CC BY-IGO permits copying, redistribution and adaptation, including commercially, if the licence is stated and notices kept | **Confirm the licence field on the HDX "Global WFP food prices" dataset page** before publishing (not verified from the page itself) |
| NASA POWER | Public; cite NASA POWER | Allowed with citation |
| World Bank WDI | CC BY 4.0 | Allowed with attribution |
| IMF data | IMF copyright and usage terms (effective 11 Oct 2024): data may be copied, distributed and used to create derivative works; **commercial reuse needs written permission** (copyright@imf.org) | Allowed for this non-commercial project with attribution |
| FAOSTAT | CC BY 4.0 | Allowed with attribution |
| IFPRI MapSPAM 2010 | CC BY 4.0 | Only derived crop weights are inside experiment results; raw rasters are not bundled |

The bundle manifest carries an attribution block naming every source. Raw provider downloads
(MapSPAM rasters, CHIRPS files, the FAOSTAT bulk archive) and the HTTP cache are never bundled;
the ingestion commands retrieve them from the providers.

Sources consulted: [IMF copyright and usage](https://www.imf.org/en/about/copyright-and-terms),
[HDX data licences](https://docs.humdata.org/about/data-licenses),
[HDX Global WFP food prices](https://data.humdata.org/dataset/global-wfp-food-prices).

## Reliability features shared by all adapters

Retries on 408/425/429/5xx with full-jitter exponential backoff and `Retry-After`, per-request
timeouts, a global concurrency limit, a disk cache with TTL (credentials excluded from keys), an
outbound host allow-list, schema validation of every normalised frame, and health checks with
latency.

## Fixtures

`data/fixtures/` contains small real responses recorded from each provider (Kenya, 2019–2025
slices) used by offline tests. They contain no credentials. Passing fixture tests does **not**
establish live compatibility; that is checked by `make test-live` and `shocktrace doctor --live`.
