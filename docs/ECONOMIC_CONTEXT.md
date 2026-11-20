# Economic Context Engine

New in v1.4. For a food-price movement, the Economic Context Engine sets the local price beside three kinds of
reference series and says, in numbers, how large each moved:

* **General inflation**: the IMF consumer price index (CPI), all items.
* **Food inflation**: the IMF CPI division 01, food and non-alcoholic beverages.
* **Exchange rates**: the IMF official rate, domestic currency per US dollar (period average and end of period).
* **International benchmark prices**: the World Bank Commodity Price Data (the Pink Sheet), where a credible
  benchmark exists for the commodity.

It is descriptive. It does not say what caused a price movement, and it is built so that it cannot: the evidence
text is generated from fixed templates, a test fails if a causal verb appears outside the "not established" notes,
and every statement carries its inference level (descriptive, associational, predictive or causal).

> A 53% rise in rice prices does not imply 53% general inflation. A rise in one food's price and a change in the
> general price level are different quantities, measured on different baskets. The engine reports both and the
> arithmetic that relates them; it does not equate them.

Coverage by country: [ECONOMIC_CONTEXT_COVERAGE.md](ECONOMIC_CONTEXT_COVERAGE.md). Worked examples with real data:
[Niger](examples/economic-context-niger-imported-rice-2024-06.md),
[Lebanon](examples/economic-context-lebanon-sunflower-oil-2021-04.md),
[Mozambique](examples/economic-context-mozambique-imported-rice-2022-10.md).

## What is delivered, and what is not

| | State |
|---|---|
| Offline ingestion of IMF CPI and exchange-rate data and the Pink Sheet, idempotent and resumable, with schema validation, SHA-256 manifests, explicit missingness, revision detection and immutable snapshots | Delivered (`market-almanac context refresh`) |
| Engine: nominal change, general and food inflation, relative price change, exchange rate with explicit quote direction, pegs and dollarized economies, benchmark mapping with confidence, exact log decomposition, descriptive lag comparison, deterministic evidence | Delivered |
| API: the context section of every investigation, `context=` and `as_of=` pinning, `/api/v1/context`, `/api/v1/context/coverage` | Delivered |
| Price Shock Investigator section 7, "Economic context", on desktop and mobile | Delivered |
| Exports: Markdown brief section, JSON, five CSV tables, versioned JSON Schema ([docs/schemas/economic-context-1.schema.json](schemas/economic-context-1.schema.json)) | Delivered |
| Public production deployment showing the observations | **Not delivered by default.** The public artefact is metadata-only (see [Licensing](#licensing-and-what-production-shows)); a deployment shows the numbers only when the full artefact is installed privately or the provider's permission is on record |
| Causal attribution, forecasting, "what-if" simulation, parallel-market (effective) exchange rates, sub-national CPI, nowcasting | Not built and not claimed |

## Method

### Quantities

* **Nominal local price change.** The investigated series' change over 12 months to the month of interest
  (`yoy`) and from a baseline to the peak. The baseline is the mean of the 12 months before the episode began; the
  peak is the episode's highest month. Both are used for every series so the comparison is like for like.
* **General inflation** and **food inflation** are 12-month and baseline-to-peak changes of the CPI index. The
  difference between food and headline inflation is reported in percentage points.
* **Relative price change.** `(1 + n) / (1 + d) - 1`, where `n` is the nominal change of the price and `d` the
  change of the deflator (headline or food CPI), over the same horizon. It answers "did this price rise faster
  than the national average basket?", not "what happened to anyone's purchasing power". It is shown only where both
  changes exist for the horizon.
* **Exchange rate.** The IMF quote is domestic currency per US dollar. A positive change means more units of local
  currency per dollar (the local currency bought fewer dollars); `usd_value_change = 1 / (1 + x) - 1`. A rate that
  did not move is described as not having moved, never as "fewer units per dollar" at 0.0%.
* **Price in US dollars.** The local price at the official period-average rate. For countries whose official
  rate diverged from the rate in use (see below) the text states that it may be far from the dollar price households
  faced.
* **Benchmark.** The Pink Sheet price in US dollars, and in local currency (`benchmark x rate`), with the exact
  decomposition `log(1 + local change) = log(1 + dollar change) + log(1 + exchange-rate change)`. The three terms are
  reported; the split is arithmetic and is not a statement about why either part moved.
* **Relative magnitude (descriptive).** For each comparison (general inflation, food inflation, currency, benchmark),
  the log of the reference's change over the log of the price's change. This is a size ratio, not an explanatory
  contribution. At least 0.5 is reported as *same direction, comparable or larger magnitude*, at least 0.2 as
  *same direction, smaller magnitude*, below that as *much smaller magnitude or opposite direction*, and only when the
  price rose by at least 10%. A small ratio is never evidence against inflation, a currency effect or transmission:
  baskets, grades, places and unofficial exchange rates differ from the series compared, and a benchmark moving in the
  same direction does not establish a transmission mechanism. Each statement also carries coverage, missing evidence and
  the limits of causal interpretation.
* **Charts.** Indexed, with 100 equal to the mean of the baseline months; never dual axes. Missing months are gaps,
  not interpolated and not joined.

### Lag comparison

Spearman rank correlations between monthly changes in the price and each reference series led by 0 to 6 months,
reported as a range with the number of paired months. Fewer than 24 pairs is `insufficient`; fewer than 3 distinct
values (an administered rate that does not move) is `no_variation`, and the text says that rather than "too few
overlapping months". No p-values, no "best lag", no ranking of references: a rank correlation of monthly changes is
descriptive and cannot establish that one series moves another.

### Information at a date (`as_of`)

Official statistics are published after the month they describe. The engine assumes a release lag (CPI 2 months,
exchange rate 1, Pink Sheet 1) and `as_of=YYYY-MM` shows what would have been available by that month under those
lags. This does **not** reconstruct what was known then: the snapshot is the *current* archived vintage, so past
months may since have been revised. Every output carries that statement, and a context run on the current vintage is
labelled exploratory.

### Benchmarks

`context/data/benchmark_mappings.json` maps commodities to Pink Sheet series with a confidence rating:

* `medium`: the same internationally traded commodity, a plausible reference for imported supplies (for example
  imported rice, wheat flour, sugar).
* `low`: a related but different product or grade, or a product traded mainly regionally (for example "oil" of
  unstated type against palm, soybean and sunflower oil). A similar movement is weak evidence; a different one is
  not evidence against anything. The section is shown as *context only* and no proposition is assessed.
* `none`: no credible benchmark among the integrated series. The section says so (*cannot be assessed*) and shows
  nothing.

No mapping is rated "high": an export quotation and a retail price differ in transport, tariffs, margins, quality
and currency. With several mapped benchmarks the proposition uses the **median** share across them, with the range
stated, so a single favourable series cannot carry the conclusion.

### Currency regimes

`context/data/currency_regimes.json` records pegs (CFA francs, others), dollarized economies, and the countries for
which the official rate has diverged from the rate actually used (parallel or multiple rates, controls, abrupt
reforms). The IMF series is the **official** rate, not an effective one:

* For a **peg**, a flat rate is the regime, not evidence that currency was irrelevant; the proposition is worded
  accordingly or withheld.
* For a **dollarized** economy, an exchange-rate proposition is not applicable and is withheld.
* For a country on the **divergence list**, the warning names the country explicitly, and the dollar price is
  presented with the caution that official and market rates differed.
* If the price series' currency differs from the IMF series' currency (for example a price in NGN against a CFA
  country), the proposition is withheld and says so.

### Evidence statements

The evidence layer turns the figures into: observed facts; quantitative description; propositions the figures can
be set beside (with the assessments above); what is consistent; unresolved alternatives; and what the context does
**not** establish (a causal claim, the effect on any household, a lead-lag order). Generic phrases are avoided where
a specific one is available. Missing inputs appear as gaps, never as zeros, and never as "no relationship".

## Data and reproducibility

| Item | Value |
|---|---|
| IMF CPI | `IMF.STA,CPI` `{ISO3}.CPI._T.IX.M` (headline), `{ISO3}.CPI.CP01.IX.M` (food) |
| IMF exchange rates | `IMF.STA,ER` `{ISO3}.XDC_USD.PA_RT.M` (period average), `...EOP_RT.M` (end of period) |
| World Bank | Commodity Price Data (The Pink Sheet), monthly workbook |
| Snapshot id | `YYYYMMDDTHHMMSS_<6 hex>`; immutable, never overwritten |
| Manifest | per-source request, retrieval time, response SHA-256, observation counts, licence record; per-series observation SHA-256 |
| Observation hash | over all kept observations; identifies the context a result was computed from |
| `context_id` | identifies the context result (snapshot, window, as-of); separate from the investigation's `config_id` so existing links and exports keep working |

Snapshots are produced offline only. The API never calls the IMF or the World Bank, never queries the Neon
database for context, and reads local files only.

```bash
market-almanac context refresh            # retrieve IMF + Pink Sheet into DATA_DIR/context/<mode>/<snapshot>
market-almanac context verify             # structure and SHA-256 checks of a snapshot
market-almanac context coverage --markdown --countries KEN,NER,LBN
market-almanac context bundle --out dist  # package the newest snapshot (metadata-only by default)
market-almanac context install            # install the pinned artefact into DATA_DIR, hash-verified
market-almanac context check-against series_hashes.json   # compare your retrieval with the published hashes
```

A retrieval made later may differ: new months and revisions are expected. `check-against` reports which series match
the published hashes exactly and which differ, which is a revision rather than an error. Revisions between two
retrievals are detected per series and recorded in the snapshot.

## Licensing and what production shows

IMF data are available under the IMF's copyright and usage terms; the Pink Sheet is a World Bank publication
compiled from named third-party sources. Whether this project may *redistribute the observations themselves* in a
public download is not confirmed, so the default public artefact (`market-almanac context bundle`) is
**metadata-only**: the series table, coverage and bases, citations and licence records, source vintages, the SHA-256
of every retrieved response and of every series' observations, and retrieval instructions. It contains no IMF or
World Bank observations.

Consequently a deployment installed from the public artefact reports the economic section as `metadata_only`: it
lists what the context would hold and why the numbers are not shown. A deployment whose operator has installed the
full artefact (`context bundle --include-unconfirmed`, never the public default) or has the provider's written
permission shows the full section. The licence position is a record in the snapshot manifest, one per source, and
the bundle builder honours it per source.

Raw provider responses, HTTP caches and credentials are never bundled.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/v1/investigations/{id}` | The investigation. `context.economic` is the economic-context section (or `{status, reason}` for `demo_mode`, `not_installed`, `metadata_only`) and `evidence.economic` its evidence. `context=<snapshot id>` requires that context snapshot (409 if another is served, as for `snapshot=`); `as_of=YYYY-MM` limits information to what was assumed published by that month. |
| `GET /api/v1/investigations/{id}/export` | `format=md` includes the section; `format=json` the document; `format=csv` with `table=economic_series`, `economic_changes`, `economic_lags`, `economic_lineage` or `economic_notes`. |
| `GET /api/v1/context` | Snapshot description: id, vintage, sources with licence records, whether observations are present. |
| `GET /api/v1/context/coverage` | Country coverage, paged (`limit` at most 100, `offset` at most 1,000), filtered by `country` (ISO3) and `usable`; 404 when no data are installed. |

The investigation's `config_id` does not change when context is added: v1.3 links and exports still resolve.
The JSON schema for the section is versioned: [docs/schemas/economic-context-1.schema.json](schemas/economic-context-1.schema.json).

## Exports

Every export carries, for each series: provider, dataset, series reference, first and last month, release lag
assumed, vintage publication date, retrieval time, response and observation SHA-256, licence and attribution
(`economic_lineage`); the transformations used and every warning, missing input, proposition and "not established"
note (`economic_notes`); the indexed series (`economic_series`); every change (`economic_changes`); and the lag
rows (`economic_lags`). Cells that do not apply to a horizon are a dash; missing values are empty or "not
available", never zero.

## Performance and security

Measured on the real snapshot (95 countries, 40 investigations): about +22 MB peak resident memory and +25 ms median
latency against the same run without context; no network or database access is added. Context routes bypass the install gate and
read local files only. Inputs are validated (`as_of`, `context`, `country`, `usable`, paging bounds); no request
parameter reaches a file path. See [PERFORMANCE.md](PERFORMANCE.md).

## Limitations

* The IMF CPI is a national average of a fixed basket; a local food market can move for reasons the national index
  cannot show, and a small CPI change does not exclude a local price-level movement.
* Food CPI is missing or empty for many countries (see the coverage page), including Niger.
* Official exchange rates can be administratively fixed or far from rates in use; effective and parallel rates are
  not integrated.
* Benchmark mappings are judgement and are rated; no mapping is rated high.
* The current archived vintage is used, so past comparisons are exploratory, not a reconstruction of what was
  known at the time. The `as_of` release lags are assumptions.
* Rank correlations of monthly changes are descriptive; they do not identify direction or cause.
* Coverage is 38 of 95 price countries for the complete macro comparison, 68 of 95 for at least headline CPI and
  the exchange rate; PSE has no IMF series.
* Public production shows the metadata-only section unless the observations are installed privately or the rights
  are confirmed.
