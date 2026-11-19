# Price Shock Investigator

`/investigate` answers one question about one market and one food: **was this price movement unusual for that
market, was it shared, and what can the data integrated here say about why?** It finds candidate movements across
all 95 countries with stored WFP prices, and for any one of them assembles a reproducible investigation with an
explicit separation between what was observed, what was measured, what explanations the data are consistent
with, and what the data cannot show.

It does not estimate famine risk, crisis probabilities or food insecurity, it makes no causal claims, and it
writes no free-text narrative: every sentence comes from fixed rules applied to the numbers shown next to it.

- [How a movement is assessed](#how-a-movement-is-assessed)
- [Comparisons: other markets, other foods, seasons](#comparisons)
- [Context](#context)
- [Evidence framework](#evidence-framework)
- [Reproducibility](#reproducibility)
- [Worked example: imported rice in Maradi, Niger, 2023–24](#worked-example)
- [Validation on the archived data](#validation-on-the-archived-data)
- [Architecture and performance](#architecture-and-performance)
- [Limitations](#limitations)

## How a movement is assessed

Method version `shock-1`, implemented in
[`analytics/shocks.py`](../packages/market-almanac/src/market_almanac/analytics/shocks.py).

**Series.** One WFP series is one market, commodity, unit, price type and currency. Monthly prices are the first
valid record of each month (records flagged invalid, duplicate or conflicting are never used); zero, negative or
non-finite prices are dropped before any ratio is taken. Missing months stay missing: they are never filled, and
no change is computed across them.

**Signal.** The 12-month log change `y_t = ln P_t − ln P_{t−12}`, only when both months were observed. Comparing
a month with the same month a year earlier removes a regular seasonal pattern, so a lean-season rise that happens
every year is not unusual by construction.

**Unusualness.** `y_t` is compared with the same series' 12-month changes that ended **before** `t`:

- robust z-score: `(y_t − median) / max(1.4826 × MAD, 0.01)`;
- rank: the share of earlier changes below it.

Because the reference is the series' own past, a +40% year is ordinary in a market with persistent high
inflation, and +15% can be extraordinary in one where prices rarely move. Both the nominal change and the
z-score are always shown. z-scores beyond ±10 are reported as "beyond ±10": at that distance the change exceeds
every earlier one and further digits would be false precision.

**Eligibility (an assessment is withheld, with the reason, never scored).**

| Rule | Why |
|---|---|
| at least 36 earlier 12-month changes, from at least 4 calendar years | 12-month changes overlap; 36 hold about three independent years |
| at least 12 of the last 24 months observed | a change resting on a sparse record is not comparable |
| earlier changes not degenerate (MAD at least the 0.01 floor) | prices carried forward for years give no estimate of normal variability (on the real data such series produced z ≈ 350 before this rule) |

**Episodes.** A run of assessable months with z ≥ 2 (≤ −2 for falls) is an *unusual episode* if it reaches
z ≥ 3 at least once (Hampel hysteresis: about 2.3% of months exceed 2 by chance, 0.13% exceed 3, while a real
shock stays above 2 for its whole duration). A run never bridges an assessed month below the threshold. The peak
is the month with the largest change, re-assessed against changes recorded before the episode began, so that an
episode does not dilute its own reference.

Movements are kept in three separate kinds so the distinction stays visible:

| Kind | Definition |
|---|---|
| `unusual` | an episode as above |
| `large_typical` | 12-month change of 25% or more that stays within ±2 robust SDs on both references (every month against all earlier changes, and the peak against changes before the movement) |
| `withheld` | 12-month change of 25% or more that cannot be assessed (reason recorded) |

Large changes with 2 ≤ |z| < 3 that never reach the trigger belong to neither unusual nor typical; they are not
listed but can still be investigated directly.

**Flags.** `implausible_jump` (the price changed by more than ×4 within one month) and `single_month_reversed`
(one month, fully reversed the next) mark a **possible recording or unit error**; such episodes are hidden from
discovery by default. Also recorded: `possible_base_effect` (an unusual month a year earlier, so the 12-month
change is mechanically large), `short_reference` (fewer than 60 earlier changes), `sparse_recent_record`,
`missing_months_inside`.

## Comparisons

**Comparable markets** are other series of the same country, commodity, **unit, price type and currency**. No
conversion between units or currencies is ever made. A comparable market is *elevated* when its own robust z is
beyond 2 in the same direction in at least 2 of the 3 months around the peak (one noisy month does not count).
Of the assessable comparable markets: **widespread** ≥ 50% elevated, **local** < 25%, **mixed** in between,
**inconclusive** with fewer than 3 assessable. An investigation reads at most the 60 best-observed comparable
markets; the catalog's classification uses all of them.

**Price index.** The series and the median and middle half of comparable markets, each indexed to its own average
over the 12 months before the episode (100). Indexing within a series keeps currency and unit semantics intact.

**Other foods in the same market** (same currency, at most 40): the same rule gives **broad**, **narrow**,
**mixed** or **inconclusive**. Their median 12-month change is always reported, because "not unusual" is not
"flat": in the worked example other cereals rose 33–60% while staying within their own usual ranges.

**Seasonality.** The usual within-year profile from years **before** the episode (median of price / calendar-year
mean by month); the change it predicts over the episode is compared with the observed change: largely, partly or
not seasonal, or not assessable when the base month is missing.

**Persistence.** single month, short (≤ 3 months), persistent, or ongoing at the last observation; plus the price
six months after the peak relative to the peak.

## Context

Shown only where real data are integrated; missing context says "not integrated", never zero.

- **Weather** (NASA POWER at the market's grid cell; MapSPAM production region where defined): rainfall anomalies
  over the 12 months to the event. Labelled *contextual only*: it is not evaluated as an explanation, and
  Market Almanac's pre-registered studies did not find that these measurements improve price forecasts.
- **Consumer prices and exchange rate** (IMF, where integrated): their 12-month changes and the commodity's change
  deflated by CPI.

## Evidence framework

[`analytics/evidence.py`](../packages/market-almanac/src/market_almanac/analytics/evidence.py), deterministic.
Every statement carries an inference label and the document fields it rests on.

| Section | Content | Inference |
|---|---|---|
| Observed facts | prices, months, observation counts | descriptive |
| Quantitative description | changes, unusualness, persistence, seasonal expectation, comparisons | descriptive / associational |
| Possible mechanisms | data error, seasonal pattern, country-wide supply or demand change, local disruption, general inflation or currency, weather, policy, international prices; each with a status, the evidence for it and what would be needed | associational |
| Evidence gaps | data that would discriminate between mechanisms | — |
| Unsupported conclusions | causal attribution, food insecurity or crisis, forecasts | marked causal / predictive, and stated as **not shown** |

Mechanism statuses: *consistent*, *partly consistent*, *less likely* ("the available evidence argues against
this being the main explanation"), *not indicated*, *context only*, *cannot be assessed*. Policy and
international-price transmission are always *cannot be assessed*, because no policy records or world reference
prices are integrated. Without CPI or exchange-rate data, other foods standing still does not count against
general inflation (a currency effect reaches imported and traded foods first): the status is *not indicated*,
not *less likely*.

## Reproducibility

An investigation is fully determined by its configuration:

```json
{"format": "investigation-1", "method_version": "shock-1", "series_id": "ps_…", "event": "YYYY-MM",
 "window": {"start": "YYYY-MM", "end": "YYYY-MM"}, "peers": "same country, commodity, unit, price type and currency",
 "snapshot_id": "…"}
```

`config_id` is the first 16 hex digits of the SHA-256 of its canonical JSON. The same configuration on the same
snapshot returns a byte-identical document (tested); a data revision changes the snapshot id and therefore the
`config_id`. The permalink `/investigate?series=…&event=…&start=…&end=…` pins everything but the snapshot, which
the document and brief record. Defaults: the most recent unusual rise without a data concern, a window from 24
months before to 12 months after (at most 240 months).

Exports: the research brief (Markdown, with question, findings, history and comparisons, method and eligibility,
context, alternatives and limitations, sources, snapshot and configuration), the full document (JSON) and its
tables (CSV: monthly signals, comparable markets, other foods, price index). Charts download as PNG; the page
prints cleanly to PDF from the browser, so no PDF renderer is added to the API.

## Worked example

**Imported rice (retail, XOF/kg) in Maradi Commune, Niger, June 2024.**
[Open it](https://market-almanac-app.vercel.app/investigate?series=ps_f0d5ea3ff6ef122d&event=2024-06&start=2022-06&end=2025-06)
· [brief](examples/price-shock-maradi-rice-2024.md) · configuration `f36216db28d8fc03` on snapshot
`20261118T020240_33e3d9`.

**How it was chosen.** By criteria fixed before looking at any story: an unusual rise with no data concern and
no flags, a stable reference (≥ 60 earlier changes), at least 90% of months observed around it, at least 10
assessable comparable markets, a staple (cereals and tubers): 213 episodes in 17 countries. To exercise every
section of the investigation, the example was then restricted to persistent (≥ 4 months) and widespread
episodes: 26, of which 13 are Niger imported rice (peaks October 2023 to July 2024), 6 Ukraine millet (2026),
3 Togo red sorghum (2023), 3 Senegal imported rice (2024) and 1 Chad sweet potatoes (2025). Among the Niger
episodes, Maradi was taken as a major market with a moderate, readable z-score. That second restriction selects
for a shared movement; for contrast, a **local** episode from the first set:
[millet in Ansongo, Mali, August 2024](https://market-almanac-app.vercel.app/investigate?series=ps_0ea6a8b827d55559&event=2024-08)
(+69%, z +3.4, but only 3 of 71 assessable comparable markets also unusual).

**What the data show.**

| | |
|---|---|
| 12-month change, June 2024 | +53.3% (690 against 450 XOF/kg) |
| Unusual for this market? | yes: robust z +3.7, higher than all 71 earlier 12-month changes (6 years) |
| Persistence | 8 months above the threshold, December 2023 to July 2024; 6 months after the peak the price was 5.8% lower |
| Comparable markets | **widespread**: 18 of 22 assessable markets also unusual; median 12-month change +50% |
| Other foods in Maradi | narrow by the rule (0 of 3 assessable unusual), but millet, sorghum and maize rose 33–60% within their own usual ranges |
| Seasonal? | no: the usual pattern implies −2.8% over those months |
| Data | 37 of 37 months observed, no flagged records |

**What the investigator concludes.** The pattern is consistent with a country-wide change in the supply of or
demand for imported rice; a recording error and a purely local disruption are less likely; the usual seasonal
pattern runs the other way. General inflation or currency effects are *not indicated* (no CPI or exchange-rate
series is integrated for Niger). Policy measures and international price transmission *cannot be assessed*.

**What it deliberately does not say.** Niger's borders with neighbouring ECOWAS states were closed under
sanctions after the July 2023 coup, which is a plausible country-wide mechanism for imported goods. The
investigator does not mention it, because no dated record of trade policy or border status is integrated, and
the timing of a price rise alone cannot attribute it. That is the boundary the tool is designed to hold: it
narrows the field (country-wide, this commodity, not seasonal, not a recording artefact) and lists the data
that would discriminate further (import volumes, border and trade records, world rice prices).

**A limitation visible in the example.** The rise began in August 2023. By the episode rule it splits into
two unusual episodes (August–October 2023 and December 2023–July 2024) because November 2023 fell just below the
threshold (z 1.97). The page lists the earlier episode under "Other episodes in this window", and the
pre-episode baseline (December 2022–November 2023) therefore already contains part of the rise, so the price
index (136) understates the rise from mid-2023 levels.

## Validation on the archived data

Run on the pinned `global-prices-v1` snapshot (95 countries, 3.8 M observations), in
[`tests/integration/test_price_shocks_real.py`](../tests/integration/test_price_shocks_real.py) (skips without
the data):

- catalog invariants: no unusual episode below the trigger, no withheld episode with a score, no "large but
  typical" episode outside ±2 or below 25%, no extent claimed with fewer than 3 assessable peers, consistent
  dates;
- the worked example against the raw Parquet records (price, 12-month change), its classification, peer
  semantics and byte-identical reproduction;
- a large-but-typical rise in a high-inflation market is described as large and not unusual;
- a short series is withheld with its reason;
- 12 sampled episodes: discovery row and investigation agree on dates, peak z and extent;
- discovery stays bounded (≤ 100 rows, about 1.3 kB each; the page asks for 25) under the most expensive filters.

Synthetic tests ([`tests/scientific/test_price_shocks.py`](../tests/scientific/test_price_shocks.py)) cover
sparse and short series, missing months, zero and invalid prices, duplicates, look-ahead leakage, constant
histories, genuine versus corrupted spikes, base effects, seasonality, inflation, local versus widespread,
inconclusive peers, unit/price-type/currency separation, determinism and revisions.

**Catalog on the pinned snapshot** (125,202 series; 10 to 12 minutes on 6 cores of a laptop, peak about 0.5 GB; a 10 MB file):

| Kind | Episodes |
|---|---|
| unusual | 14,291: 8,188 rises and 6,103 falls; 1,867 flagged as possible recording or unit errors (hidden by default) |
| extent of the other 12,424 | local 5,928 · widespread 3,588 · mixed 2,438 · inconclusive 470 |
| large but typical | 56,749 |
| large, not assessable | 206,938: too short a history 203,937 · near-constant history 1,420 · fewer than 4 years 1,249 · sparse recent record 332 |

Most WFP series are too short to judge: a large change in them is listed, with the reason, never scored.

## Architecture and performance

```
offline (laptop or CI)                          Render (512 MB, 0.1 vCPU)
market-almanac global shocks  ──>  shock_catalog.parquet ─┐
  all series, ~10 min on 6 cores        (~10 MB)          ├─ price artefact (hash-pinned release) ─> install
market-almanac global prices-bundle  <────────────────────┘
                                                          /api/v1/shocks       one DuckDB query, ≤ 100 rows
                                                          /api/v1/investigations/{id}
                                                            1 series + ≤ 60 peers + ≤ 40 foods, from the
                                                            country partition already cached for market pages
```

- Building the price artefact now requires the shock catalog and refuses one computed from other snapshots; on
  a refresh, rerun `market-almanac global shocks` after `market-almanac global catalog`. If a country's prices
  are newer than its episodes, discovery reports it in `stale_countries`.
- No Neon reads: discovery and investigations use only the local Parquet lake. The investigator adds no database
  traffic.
- Measured locally (in-process API on the 95-country lake, 6-core laptop; Render's 0.1 vCPU is slower in time,
  not in work or memory):

  | | time | response |
  |---|---|---|
  | discovery page (25 rows), typical filters | 60 to 120 ms (first query after start 430 ms) | 33 kB |
  | discovery, worst case (100 rows at offset 9,900) | 120 ms | 127 kB |
  | investigation, first request | median 0.26 s, max 0.29 s (12 investigations, 7 countries) | median 53 kB, max 63 kB |
  | investigation, repeated (cached document) | 4 ms | |
  | research brief export (cached) | 3 ms | 16 kB |

  Peak resident memory, fresh process: 12 market pages 244 MB, the same 12 series investigated 260 MB; discovery
  queries add about 20 MB (230 MB after six, including the deepest page). Two design choices keep it there: episodes
  carry their series' descriptors so a query never joins the 125,000-row catalog before filtering, and pages are
  sorted on row numbers before full rows are read (that deepest page alone used to add 110 MB). The budget in
  [PERFORMANCE.md](PERFORMANCE.md) (burst below 400 MB of 512 MiB) holds.

## Limitations

- Prices are nominal local currency; no deflation unless CPI is integrated for the country.
- The reference is the series' own past. A market that has been in turmoil for its whole record has a wide
  reference, so a later shock looks less unusual.
- Robust z on 12-month changes is a screening statistic, not a test with a calibrated false-positive rate across
  125,000 series: some unusual episodes are chance, and the catalog is a list of candidates to investigate.
- Comparable markets are defined administratively (same country), not by trade links or distance.
- Episodes split when one month dips below the threshold (see the worked example).
- Weather and macro context are contextual only; policy, trade flows, conflict and world prices are not integrated.
- The investigation reads the 60 best-observed comparable markets; a country with more may classify extent
  slightly differently from the catalog, which uses all (the page says so when capped).
