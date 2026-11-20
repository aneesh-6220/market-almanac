# Price shock investigation: Oil (sunflower) (retail, 5 L) in North, Lebanon, April 2021

**Market:** North, North (Lebanon, LBN)  
**Commodity:** Oil (sunflower); Retail price in LBP per 5 L (nominal)  
**Period investigated:** February 2019 to December 2022; month of interest April 2021  
**Series:** `ps_4663d35d7cea9c96`, 116 monthly prices, 2017-01 to 2026-08  
**Configuration:** `cd803b2b80b80ce1` (method `shock-1`, price snapshot `20261118T020107_982be3`)

Reproduce this investigation: https://market-almanac-app.vercel.app/investigate?series=ps_4663d35d7cea9c96&event=2021-04&start=2019-02&end=2022-12&snapshot=20261118T020107_982be3&context=20261120T004928_ba3846

*This link names price snapshot `20261118T020107_982be3`. The site serves only the newest snapshot of each country, so if the data have been revised since, the link reports the mismatch instead of showing different numbers. The snapshot id, configuration id and method version above identify the data this brief was written from.*

## Research question

Was the rise in the retail price of Oil (sunflower) in North (Lebanon) around April 2021 unusual for that market, was it shared by comparable markets and other foods, and what can the available data say about why it happened?

## Summary

In April 2021 the price of Oil (sunflower) in North had risen 508.6% over 12 months, which is unusual for this market (robust z beyond +10; higher than all 37 earlier 12-month changes). The screening rule flagged 11 consecutive months. The episode dates show where the screening rule fired, not the full duration of any event. Most of the 9 assessable comparable markets (of 26 found) were also unusually high at the time. Most of the 9 assessable other foods in the same market were also unusually high. This pattern is consistent with country-wide supply or demand change for this commodity or general inflation or currency depreciation, but the data integrated here cannot establish which, if any, was responsible. It cannot assess weather-related production shock or policy intervention.

*Inference: descriptive and associational; no causal claim.*

| Question | Finding | Basis |
|---|---|---|
| 12-month change | +508.6% | large in nominal terms |
| Unusual for this market? | Yes | robust z beyond +10, 37 earlier changes |
| Persistence | 11 months | detected February 2021 to December 2021 (may split or truncate a longer event) |
| Other markets | Widespread | 9 of 9 assessable comparable markets also unusual (26 found) |
| Other foods, same market | Broad | 9 of 9 assessable foods also unusual |
| Seasonal? | No | usual pattern implies -0.3% over these months |
| Data quality | Adequate | 47 of 47 months observed |

## Observed facts

- The reported retail price of Oil (sunflower) in North for April 2021 was 114,747 LBP/5 L (nominal, LBP).
- Over the 12 observed months from February 2020 to January 2021 the price averaged 36,781 LBP/5 L.
- The highest 12-month change in the episode came in April 2021, at a price of 114,747 LBP/5 L.
- In the investigation window (February 2019 to December 2022) 47 of 47 months have a valid price; the longest run of missing months is 0.

## Quantitative description

- The 12-month change to April 2021 was +508.6%; the change from the previous month was +37.4%. *(descriptive)*
- The April 2021 price was +212.0% relative to its average over the 12 months before the movement began (price index 312, baseline = 100). *(descriptive)*
- Compared with the earlier 12-month changes of this series (from 4 calendar years, ending January 2021), it was higher than all 37 (robust z-score beyond +10; a typical 12-month change here was +0.0%, and 80% fell between -4.7% and +293.4%). *(descriptive)*
- The reference holds fewer than 60 earlier changes, so the rank and z-score may shift as more history accumulates. Consecutive 12-month changes overlap, so the number of independent years is about 4. *(descriptive)*
- The screening rule (|robust z| >= 2, reaching 3 at least once) flagged the 12-month change from February 2021 to December 2021 (11 months). A detected episode is the run of months in which the screening rule fired. It can split one longer disruption into several episodes (a single month just below the threshold ends a run) or cut it short (the rule needs earlier history and observed months), so its dates and length are not the duration of any real-world event. *(descriptive)*
- Six months after the peak the price was +56.2% relative to the peak. *(descriptive)*
- The usual seasonal pattern (from 4 earlier years) implies a change of -0.3% from January to April; the observed change over those months was +72.8%. *(descriptive)*
- Comparable markets (same commodity, unit, price type and currency): 26 comparable markets found; 20 reported a 12-month change within a month of the peak; 9 had enough history to be assessed against their own past; 9 of those 9 were also unusually high. The extent (widespread) describes only the 9 assessable markets, not every market in the country; the median 12-month change across the comparable markets with a change was +461.8%. *(associational)*
- Other foods in the same market: 29 other foods found; 11 reported a 12-month change within a month of the peak; 9 had enough history to be assessed against their own past; 9 of those 9 were also unusually high (their median 12-month change was +200.6%). The breadth (broad) describes only the 9 assessable foods. *(associational)*

## Price history in the window

*Robust z* here compares each month with every 12-month change before that month. The headline score compares the month investigated only with changes before the episode began, so that an episode does not dilute its own reference; the two can differ inside an episode.

| Month | Price (LBP/5 L) | Change on month | Change on year | Robust z | Assessment |
|---|---|---|---|---|---|
| 2019-02 | 10,749.00 | -0.0% | -1.1% |  | withheld (short_history) |
| 2019-03 | 10,500.00 | -2.3% | -3.4% |  | withheld (short_history) |
| 2019-04 | 10,498.00 | -0.0% | -4.6% |  | withheld (short_history) |
| 2019-05 | 10,300.00 | -1.9% | -5.3% |  | withheld (short_history) |
| 2019-06 | 10,250.00 | -0.5% | -5.7% |  | withheld (short_history) |
| 2019-07 | 10,250.00 | +0.0% | -4.7% |  | withheld (short_history) |
| 2019-08 | 10,248.00 | -0.0% | -4.7% |  | withheld (short_history) |
| 2019-09 | 10,500.00 | +2.5% | -2.3% |  | withheld (short_history) |
| 2019-10 | 9,719.00 | -7.4% | -9.6% |  | withheld (short_history) |
| 2019-11 | 10,617.00 | +9.2% | -1.1% |  | withheld (short_history) |
| 2019-12 | 14,233.00 | +34.1% | +32.4% |  | withheld (short_history) |
| 2020-01 | 15,849.00 | +11.4% | +47.4% |  | withheld (short_history) |
| 2020-02 | 15,148.00 | -4.4% | +40.9% |  | withheld (short_history) |
| 2020-03 | 16,147.00 | +6.6% | +53.8% |  | withheld (short_history) |
| 2020-04 | 18,853.00 | +16.8% | +79.6% |  | withheld (short_history) |
| 2020-05 | 26,053.00 | +38.2% | +152.9% |  | withheld (short_history) |
| 2020-06 | 28,527.00 | +9.5% | +178.3% |  | withheld (short_history) |
| 2020-07 | 40,273.00 | +41.2% | +292.9% |  | withheld (short_history) |
| 2020-08 | 39,764.00 | -1.3% | +288.0% |  | withheld (short_history) |
| 2020-09 | 39,337.00 | -1.1% | +274.6% |  | withheld (short_history) |
| 2020-10 | 46,026.00 | +17.0% | +373.6% |  | withheld (short_history) |
| 2020-11 | 48,745.00 | +5.9% | +359.1% |  | withheld (short_history) |
| 2020-12 | 56,106.00 | +15.1% | +294.2% |  | withheld (short_history) |
| 2021-01 | 66,391.32 | +18.3% | +318.9% |  | withheld (few_years) |
| 2021-02 | 66,943.60 | +0.8% | +341.9% | +21.04 | assessed |
| 2021-03 | 83,535.70 | +24.8% | +417.3% | +23.02 | assessed |
| 2021-04 | 114,747.45 | +37.4% | +508.6% | +25.02 | assessed |
| 2021-05 | 115,043.78 | +0.3% | +341.6% | +19.01 | assessed |
| 2021-06 | 130,333.33 | +13.3% | +356.9% | +18.08 | assessed |
| 2021-07 | 168,411.00 | +29.2% | +318.2% | +15.08 | assessed |
| 2021-08 | 188,443.00 | +11.9% | +373.9% | +14.72 | assessed |
| 2021-09 | 155,367.00 | -17.6% | +295.0% | +8.86 | assessed |
| 2021-10 | 179,192.00 | +15.3% | +289.3% | +6.62 | assessed |
| 2021-11 | 215,882.00 | +20.5% | +342.9% | +4.19 | assessed |
| 2021-12 | 253,178.00 | +17.3% | +351.2% | +2.52 | assessed |
| 2022-01 | 262,561.00 | +3.7% | +295.5% | +1.99 | assessed |
| 2022-02 | 207,907.00 | -20.8% | +210.6% | +1.36 | assessed |
| 2022-03 | 350,644.00 | +68.7% | +319.8% | +1.73 | assessed |
| 2022-04 | 415,172.00 | +18.4% | +261.8% | +1.37 | assessed |
| 2022-05 | 417,326.00 | +0.5% | +262.8% | +1.27 | assessed |
| 2022-06 | 407,135.00 | -2.4% | +212.4% | +0.98 | assessed |
| 2022-07 | 410,115.00 | +0.7% | +143.5% | +0.46 | assessed |
| 2022-08 | 398,751.00 | -2.8% | +111.6% | +0.18 | assessed |
| 2022-09 | 397,833.00 | -0.2% | +156.1% | +0.27 | assessed |
| 2022-10 | 437,440.00 | +10.0% | +144.1% | +0.13 | assessed |
| 2022-11 | 430,226.00 | -1.6% | +99.3% | -0.13 | assessed |
| 2022-12 | 441,478.00 | +2.6% | +74.4% | -0.18 | assessed |

## Comparison with other markets

Comparable markets: same commodity, unit (5 L), price type and currency (LBP) in Lebanon. 26 comparable markets found; 20 reported a 12-month change within a month of the peak; 9 had enough history to be assessed against their own past; 9 of those 9 were also unusually high. Classification **widespread**, which describes only the 9 assessable markets (a peer is elevated when its robust z is beyond 2 in the same direction in at least 2 of the 3 months around the peak; widespread: >= 50% of assessable peers elevated; local: < 25%; inconclusive: fewer than 3 assessable peers).

| Market | Admin 1 | Month | 12-month change | Robust z | Unusual, same direction |
|---|---|---|---|---|---|
| Baalbek-El Hermel | Baalbek-El Hermel | 2021-04-01 | +467.4% | +22.04 | yes |
| El Nabatieh | El Nabatieh | 2021-03-01 | +455.9% | +21.11 | yes |
| Bekaa | Bekaa | 2021-04-01 | +456.2% | +19.76 | yes |
| Minieh-Dannieh | North | 2021-03-01 | +448.6% | +19.63 | yes |
| Chouf | Mount Lebanon | 2021-03-01 | +494.1% | +17.72 | yes |
| Akkar | Akkar | 2021-04-01 | +479.1% | +17.54 | yes |
| Baabda | Mount Lebanon | 2021-03-01 | +428.8% | +13.32 | yes |
| South | South | 2021-04-01 | +518.2% | +10.85 | yes |
| West Beqaa | Bekaa | 2021-05-01 | +372.2% | +6.03 | yes |
| Bint Jbeil | El Nabatieh | 2021-04-01 | +516.3% | too little earlier history |  |
| Beirut | Beirut | 2021-04-01 | +696.9% | too little earlier history |  |
| Kesrwane | Mount Lebanon | 2021-04-01 | +480.8% | too little earlier history |  |
| Rashaya | Bekaa |  |  | no 12-month change within a month of the peak |  |
| Hermel | Baalbek-El Hermel | 2021-04-01 | +251.0% | too little earlier history |  |
| Bechare | North |  |  | no 12-month change within a month of the peak |  |
| Jezzine | South |  |  | no 12-month change within a month of the peak |  |
| Hasbaya | El Nabatieh | 2021-04-01 | +445.0% | too little earlier history |  |
| Batroun | North |  |  | no 12-month change within a month of the peak |  |
| El Metn | Mount Lebanon | 2021-04-01 | +360.2% | too little earlier history |  |
| Mount Lebanon | Mount Lebanon |  |  | no 12-month change within a month of the peak |  |
| Koura | North | 2021-04-01 | +505.4% | too little earlier history |  |
| Marjayoun | El Nabatieh | 2021-04-01 | +571.2% | too little earlier history |  |
| Jbeil | Mount Lebanon |  |  | no 12-month change within a month of the peak |  |
| Sour | South | 2021-04-01 | +642.3% | too little earlier history |  |
| Aley | Mount Lebanon | 2021-04-01 | +430.6% | too little earlier history |  |
| Zgharta | North | 2021-04-01 | +242.7% | too little earlier history |  |

Other foods in the same market and currency: 29 other foods found; 11 reported a 12-month change within a month of the peak; 9 had enough history to be assessed against their own past; 9 of those 9 were also unusually high. Classification **broad**, which describes only the 9 assessable foods. Only relative (percentage) changes are compared across different foods.

In nominal terms, 11 of the 11 other foods with a 12-month change around the peak rose by 25% or more (median +200.6%). A food that moved a lot but stayed within its own historical range is *not unusual* by this method; that is a statement about its history, not about whether its price rose, and it is not evidence for or against any macroeconomic mechanism.

## Seasonality

Seasonal profile from 4 pre-episode years: prices typically peak in December and are lowest in May (amplitude +18.8%). Expected change from 2021-01 to 2021-04: -0.3%; observed: +72.8%. Verdict: not seasonal.

## Contextual evidence

- Weather: not integrated for this market or crop.
- Consumer price index: not integrated for this country (prices are nominal).
- Exchange rate: not integrated for this country.
- Without a price index or an exchange rate, an inflation or currency mechanism **cannot be assessed**: other foods rising together, or staying within their usual ranges, neither supports nor argues against it.
- Missing context is reported as missing; it is never treated as zero.

## Economic context

**Context snapshot:** `20261120T004928_ba3846` (observation hash `ba3846fda542`); context identity `84f456739fbcc9a9`  
**Vintage:** current archived vintage at retrieval: historical values may since have been revised, so comparisons of past months are exploratory, not a reconstruction of what was known then.  
**Window:** February 2019 to December 2022; month of interest April 2021; pre-episode baseline February 2020 to January 2021.

### Observed facts

- The IMF headline consumer price index for Lebanon is available from January 2010 to August 2026 (200 months; 0 of 47 window months missing).
- The IMF food consumer price index for Lebanon is available from January 2010 to August 2026 (200 months; 0 of 47 window months missing).
- The IMF exchange rate for Lebanon is available from January 2010 to March 2026 (195 months; 0 of 47 window months missing).
- Oil (sunflower) is mapped to Palm oil (Malaysia), Soybean oil, Sunflower oil with low confidence (oil of unstated type). The benchmark is a related but different product or grade, or the local product is mostly produced and traded regionally. A similar movement would be weak evidence and a different movement would not argue against anything.
- Exchange rate, period average (domestic currency per US dollar) for LBN ends in 2026-03, well before the newest data in the snapshot.
- Exchange rate, end of period (domestic currency per US dollar) for LBN ends in 2026-03, well before the newest data in the snapshot.
- LBN is listed among the countries for which this applies. Official exchange rates in these countries diverged from rates actually used in markets (parallel or multiple rates, controls, or abrupt reforms) during parts of 2017-2026. The IMF series is the official rate; it may not describe the rate at which importers or households transacted, and step changes in it can reflect an administrative revaluation rather than a market movement. Which months are affected differs by country and is not asserted here.
- The benchmark mapping for Oil (sunflower) is rated 'low': The benchmark is a related but different product or grade, or the local product is mostly produced and traded regionally. A similar movement would be weak evidence and a different movement would not argue against anything.

### Quantitative description

- The local price changed +508.6% over the 12 months to April 2021 (nominal, LBP).
- The national consumer price index changed +121.7% over the same 12 months (IMF/World Bank snapshot 20261120T004928_ba3846). A change in one food's price and the change in the general price level are different quantities.
- The food component of the consumer price index changed +228.6%.
- Food inflation exceeded headline inflation by +107.0 percentage points.
- Price relative to headline CPI (12-month change at the event month): the price changed +508.6% against +121.7% for the headline CPI, a relative change of +174.6%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Price relative to food CPI (12-month change at the event month): the price changed +508.6% against +228.6% for the food CPI, a relative change of +85.2%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Price relative to headline CPI (change from the pre-episode baseline to the peak): the price changed +212.0% against +64.1% for the headline CPI, a relative change of +90.2%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Price relative to food CPI (change from the pre-episode baseline to the peak): the price changed +212.0% against +110.5% for the food CPI, a relative change of +48.2%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Domestic currency per US dollar changed +0.0% over the 12 months (the official rate did not move), a +0.0% change in the dollar value of one unit of the local currency (official rate, period average).
- At the official period-average rate the price in US dollars changed +508.6% (official rates in this country have diverged from market rates, so this may be far from the dollar price households faced).
- Palm oil (Malaysia) changed +77.0% in US dollars over the 12 months to April 2021.
- In local currency the same benchmark changed +77.0%: a +77.0% change in dollars combined with a +0.0% change in the exchange rate (log changes +0.571 and +0.000, adding exactly). The split is arithmetic and does not show why either part moved.
- The benchmark's local-currency change is 32% of the price's 12-month log change (arithmetic ratio of two logarithmic changes).
- Soybean oil changed +103.8% in US dollars over the 12 months to April 2021.
- In local currency the same benchmark changed +103.8%: a +103.8% change in dollars combined with a +0.0% change in the exchange rate (log changes +0.712 and +0.000, adding exactly). The split is arithmetic and does not show why either part moved.
- The benchmark's local-currency change is 39% of the price's 12-month log change (arithmetic ratio of two logarithmic changes).
- Sunflower oil changed +114.9% in US dollars over the 12 months to April 2021.
- In local currency the same benchmark changed +114.9%: a +114.9% change in dollars combined with a +0.0% change in the exchange rate (log changes +0.765 and +0.000, adding exactly). The split is arithmetic and does not show why either part moved.
- The benchmark's local-currency change is 42% of the price's 12-month log change (arithmetic ratio of two logarithmic changes).
- Rank correlations between monthly changes in this price and Palm oil (Malaysia) (USD) led by 0 to 6 months ranged from +0.10 to +0.25 (up to 71 paired months through December 2022). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Soybean oil (USD) led by 0 to 6 months ranged from +0.07 to +0.22 (up to 71 paired months through December 2022). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Sunflower oil (USD) led by 0 to 6 months ranged from +0.10 to +0.35 (up to 71 paired months through December 2022). Descriptive; no lag is singled out.
- Monthly changes of Exchange rate (domestic currency per USD) take too few distinct values in the overlapping months (71) for a rank correlation to be defined (for example an administered rate that did not move).
- Rank correlations between monthly changes in this price and Consumer price index (all items) led by 0 to 6 months ranged from +0.18 to +0.47 (up to 71 paired months through December 2022). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Consumer price index (food) led by 0 to 6 months ranged from +0.21 to +0.55 (up to 71 paired months through December 2022). Descriptive; no lag is singled out.

### Propositions the figures can be set beside

| Proposition | Assessment | Basis |
|---|---|---|
| The national consumer price index rose by a comparable amount to this price | same direction, smaller magnitude | the national consumer price index changed +121.7% against +508.6% for this price, 44% of its log change. The index is a national average of a different basket, so a small figure says nothing about whether general inflation matters, because the basket differs from this product |
| The food component of the consumer price index rose by a comparable amount to this price | same direction, comparable or larger magnitude | food CPI changed +228.6% against +508.6% for this price (66% of its log change) |
| The local currency lost value against the US dollar by a comparable amount to the price rise | context only | units of local currency per dollar changed +0.0% against +508.6% for the price (0% of its log change). Official rates in this country have diverged from market rates, so the figure may not describe the rate importers faced |
| International benchmark prices, in local currency, moved by a comparable amount to this price | context only | the mapping is rated low: a similar movement would be weak evidence and a different one would not argue against anything |

### Changes at a glance

| Item | 12-month change | Baseline to peak | State |
|---|---|---|---|
| local price | +508.6% | +212.0% | ok |
| Consumer price index (all items) | +121.7% | +64.1% | ok |
| Consumer price index (food and non-alcoholic beverages) | +228.6% | +110.5% | ok |
| Exchange rate, period average (domestic currency per US dollar) | +0.0% | +0.0% | ok |
| Exchange rate, end of period (domestic currency per US dollar) | +0.0% | +0.0% | ok |
| Palm oil (Malaysia) | +77.0% | +40.6% | ok |
| Palm oil (Malaysia) (local currency) | +77.0% | +40.6% | ok |
| Soybean oil | +103.8% | +61.8% | ok |
| Soybean oil (local currency) | +103.8% | +61.8% | ok |
| Sunflower oil | +114.9% | +71.0% | ok |
| Sunflower oil (local currency) | +114.9% | +71.0% | ok |
| Price relative to headline CPI (12-month change at the event month) | +174.6% | — | ok |
| Price relative to food CPI (12-month change at the event month) | +85.2% | — | ok |
| Price relative to headline CPI (change from the pre-episode baseline to the peak) | — | +90.2% | ok |
| Price relative to food CPI (change from the pre-episode baseline to the peak) | — | +48.2% | ok |

### Cautions

- Exchange rate, period average (domestic currency per US dollar) for LBN ends in 2026-03, well before the newest data in the snapshot.
- Exchange rate, end of period (domestic currency per US dollar) for LBN ends in 2026-03, well before the newest data in the snapshot.
- LBN is listed among the countries for which this applies. Official exchange rates in these countries diverged from rates actually used in markets (parallel or multiple rates, controls, or abrupt reforms) during parts of 2017-2026. The IMF series is the official rate; it may not describe the rate at which importers or households transacted, and step changes in it can reflect an administrative revaluation rather than a market movement. Which months are affected differs by country and is not asserted here.
- The price's currency is assumed to be the national currency of the IMF exchange-rate series (not independently verifiable here).
- The benchmark mapping for Oil (sunflower) is rated 'low': The benchmark is a related but different product or grade, or the local product is mostly produced and traded regionally. A similar movement would be weak evidence and a different movement would not argue against anything.
- Historical comparisons use the current archived vintage of each series; revisions and re-basing since publication mean this is an exploratory reading, not what was visible at the time. Set an as-of month to apply the assumed release lags.

### Not established by this context

- That inflation, depreciation or an international price caused the local price movement. The context places magnitudes side by side; attributing the movement to any of them requires a design that separates it from the others, which move together. *(causal)*
- That a lead-lag pattern in monthly changes shows transmission from a benchmark, a currency or an index. Seven lags are examined and monthly changes are autocorrelated. *(causal)*
- That a benchmark's path describes the cost of the product sold locally. A world export quotation differs from the local product in grade, place, stage of the chain and currency. *(causal)*
- That a relative price change is a change in households' purchasing power or welfare. *(causal)*

### Unresolved alternatives

- Local supply conditions (harvest, stocks), transport and border costs, trade and price policy, conflict and access, demand shifts and recording changes can each coincide with the movements shown above; the integrated data cannot separate them.

### Sources

Consumer price indices and exchange rates: International Monetary Fund (IMF), CPI and ER datasets. International benchmark prices: World Bank Commodity Price Data (the Pink Sheet). Each series' source reference, vintage, retrieval time and SHA-256 hashes are in the `economic_lineage` CSV table. Percentage changes are computed by Market Almanac from those series.

Methods: (1) 12-month change = level(t) / level(t-12) - 1 over calendar months; withheld if either month is missing or a base break lies between them. (2) change from the mean level over the 12 months before the episode onset to the level at the peak; withheld with fewer than 3 baseline months, a missing peak month or a base break in between. (3) each series indexed to 100 = its own mean over the baseline months, so series in different units share one axis; withheld on the far side of a base break. (4) (1 + price change) / (1 + deflator change) - 1: how the price moved relative to the national basket; not purchasing power, not a causal share. (5) local price / domestic currency per USD (period average), month by month: an indicative dollar value at the official rate. (6) benchmark USD price x domestic currency per USD (period average); its log change splits exactly into the benchmark's log change and the exchange rate's. (7) Spearman correlation between monthly log changes of the local price at t and of the reference at t - lag; no p-values; fewer than 24 paired months is insufficient.

## Possible mechanisms

| Mechanism | Assessment | What the available data show | What would be needed |
|---|---|---|---|
| Recording, unit or measurement error | The available evidence argues against this being the main explanation | the movement persisted for several months and was shared by other markets | the original survey records or enumerator notes; confirmation of the unit and outlet by the data provider |
| Normal seasonal pattern (lean season, harvest timing) | The available evidence argues against this being the main explanation | the usual seasonal pattern implies -0.3% over these months against +72.8% observed; the unusualness test compares 12-month changes, which already removes a regular seasonal pattern | the local crop calendar and the timing of the most recent harvest |
| Country-wide supply or demand change for this commodity (harvest shortfall, import or trade disruption) | Consistent with the available evidence | 26 comparable markets found; 20 reported a 12-month change within a month of the peak; 9 had enough history to be assessed against their own past; 9 of those 9 were also unusually high; the classification (widespread) describes only the 9 assessable markets; the others could not be judged either way | national production estimates for the relevant season (not integrated); import, export and cross-border trade flows (not integrated) |
| Local supply or market-access disruption (transport, insecurity, market closure) | The available evidence argues against this being the main explanation | 26 comparable markets found; 20 reported a 12-month change within a month of the peak; 9 had enough history to be assessed against their own past; 9 of those 9 were also unusually high; the episode lasted 11 months | conflict and access-constraint records for the area (not integrated); transport costs and road or border closures (not integrated) |
| General inflation or currency depreciation | Consistent with the available evidence | The national consumer price index rose by a comparable amount to this price: same direction, smaller magnitude (the national consumer price index changed +121.7% against +508.6% for this price, 44% of its log change. The index is a national average of a different basket, so a small figure says nothing about whether general inflation matters, because the basket differs from this product); The food component of the consumer price index rose by a comparable amount to this price: same direction, comparable or larger magnitude (food CPI changed +228.6% against +508.6% for this price (66% of its log change)); The local currency lost value against the US dollar by a comparable amount to the price rise: context only (units of local currency per dollar changed +0.0% against +508.6% for the price (0% of its log change). Official rates in this country have diverged from market rates, so the figure may not describe the rate importers faced) | a parallel-market or import-cost exchange rate where the official rate diverged (not integrated); import prices, tariffs and freight for the commodity (not integrated) |
| Weather-related production shock (drought, floods) | Cannot be assessed with the data integrated here | no weather data are integrated for this market or crop | harvest outcome for the season (not integrated); evidence that this market is supplied from those areas |
| Policy intervention (export ban, tariff, subsidy removal, price control) | Cannot be assessed with the data integrated here | no record of policy measures is integrated | dated records of trade and price policy measures for the country |
| Transmission of international prices | Only contextual data are available; not evaluated | International benchmark prices, in local currency, moved by a comparable amount to this price: context only (the mapping is rated low: a similar movement would be weak evidence and a different one would not argue against anything) | the commodity's actual origin, grade and landed cost (not integrated); import dependence and trade policy for the country (not integrated) |

## Evidence gaps

- the original survey records or enumerator notes
- confirmation of the unit and outlet by the data provider
- the local crop calendar and the timing of the most recent harvest
- national production estimates for the relevant season (not integrated)
- import, export and cross-border trade flows (not integrated)
- conflict and access-constraint records for the area (not integrated)
- transport costs and road or border closures (not integrated)
- a parallel-market or import-cost exchange rate where the official rate diverged (not integrated)
- import prices, tariffs and freight for the commodity (not integrated)
- harvest outcome for the season (not integrated)
- evidence that this market is supplied from those areas
- dated records of trade and price policy measures for the country
- the commodity's actual origin, grade and landed cost (not integrated)
- import dependence and trade policy for the country (not integrated)

## What this evidence does not establish

- That any of the mechanisms above caused this movement. The evidence can be consistent or inconsistent with a mechanism; it does not identify causes. *(causal)*
- That households faced food insecurity, hunger or a crisis. Prices alone do not measure incomes, access or consumption, and no risk score is computed here. *(causal)*
- That the price will continue to rise or fall back. No forecast is made in this investigation. *(predictive)*
- That the same factor drove every market's movement. Shared timing is consistent with a common cause but does not establish one. *(causal)*
- That a robust z-score is a probability, significance level or false-positive rate. The robust z-score thresholds are screening rules, not calibrated significance tests: food-price changes are heavy-tailed and overlap from month to month, so a z-score is not a probability and no false-positive rate is claimed. *(descriptive)*
- That the detected episode is the full duration of a real-world disruption. A detected episode is the run of months in which the screening rule fired. It can split one longer disruption into several episodes (a single month just below the threshold ends a run) or cut it short (the rule needs earlier history and observed months), so its dates and length are not the duration of any real-world event. *(descriptive)*

## Data quality

47 of 47 months observed in the window; longest gap 0 months. 47 stored records, 0 not used.

Episode flags: `short_reference`.

## Methodology

12-month log price change compared with the same series' earlier 12-month changes (robust z-score: median and 1.4826 x MAD, scale floor 0.01; rank: share of earlier changes below it). Assessed only with at least 36 earlier changes from 4+ calendar years and at least 50% of the last 24 months observed. Episode: consecutive months with |z| >= 2.0 that reaches |z| >= 3.0 at least once; its peak is re-assessed against changes recorded before it began. The thresholds are screening rules, not calibrated significance tests, and an episode is where the rule fired: it can split or truncate a longer real-world disruption, so its length is not the duration of any event.

Eligibility: an unusualness assessment is withheld, with the reason, when the series has fewer than 36 earlier 12-month changes, they span fewer than 4 calendar years, fewer than half of the 24 months up to the month were observed, or earlier prices barely varied. 12-month changes compare a month with the same month a year earlier, so a regular seasonal pattern does not by itself look unusual. Consecutive 12-month changes overlap: the effective number of independent observations is roughly the number of years.

The robust z-score thresholds are screening rules, not calibrated significance tests: food-price changes are heavy-tailed and overlap from month to month, so a z-score is not a probability and no false-positive rate is claimed.

A detected episode is the run of months in which the screening rule fired. It can split one longer disruption into several episodes (a single month just below the threshold ends a run) or cut it short (the rule needs earlier history and observed months), so its dates and length are not the duration of any real-world event.

Prices are nominal and in local currency; nothing is converted between currencies or deflated unless a consumer price index is shown above. Comparisons across markets use only series with the same commodity, unit, price type and currency.

## Sources and citation

- World Food Programme market prices, via the HDX Humanitarian API (HAPI) (all prices); licence: CC BY-IGO; cite WFP / HDX; https://hapi.humdata.org/
- NASA POWER daily meteorology (market grid cell) and MapSPAM 2010 crop areas (production region) (weather context, where integrated); licence: NASA POWER: public; MapSPAM: CC BY 4.0 (IFPRI); https://power.larc.nasa.gov/
- IMF consumer price index and exchange rates (macroeconomic context, where integrated); licence: IMF terms of use; https://data.imf.org/
- World Bank Commodity Price Data (The Pink Sheet) (international benchmark context, where installed); licence: World Bank terms; third-party price sources are named in each benchmark's definition; https://www.worldbank.org/en/research/commodity-markets

Market Almanac, price-shock investigation `cd803b2b80b80ce1`, method `shock-1`, price snapshot `20261118T020107_982be3`.

## Reproducible configuration

```json
{
  "event": "2021-04",
  "format": "investigation-1",
  "method_version": "shock-1",
  "peers": "same country, commodity, unit, price type and currency",
  "series_id": "ps_4663d35d7cea9c96",
  "snapshot_id": "20261118T020107_982be3",
  "window": {
    "end": "2022-12",
    "start": "2019-02"
  }
}
```

Retrieve the same analysis from the API: `GET /api/v1/investigations/ps_4663d35d7cea9c96?event=2021-04&start=2019-02&end=2022-12&snapshot=20261118T020107_982be3&context=20261120T004928_ba3846` (add the snapshots to be told if the data have since been revised).
