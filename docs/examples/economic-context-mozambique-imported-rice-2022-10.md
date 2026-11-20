# Price shock investigation: Rice (imported) (retail, KG) in Mutarara, Mozambique, October 2022

**Market:** Mutarara, Tete (Mozambique, MOZ)  
**Commodity:** Rice (imported); Retail price in MZN per KG (nominal)  
**Period investigated:** October 2020 to November 2023; month of interest October 2022  
**Series:** `ps_9a26f4dc59e9b2f2`, 73 monthly prices, 2017-01 to 2023-11  
**Configuration:** `7978b8ca8e49233a` (method `shock-1`, price snapshot `20261118T020220_59ed26`)

Reproduce this investigation: https://market-almanac-app.vercel.app/investigate?series=ps_9a26f4dc59e9b2f2&event=2022-10&start=2020-10&end=2023-11&snapshot=20261118T020220_59ed26&context=20261120T004928_ba3846

*This link names price snapshot `20261118T020220_59ed26`. The site serves only the newest snapshot of each country, so if the data have been revised since, the link reports the mismatch instead of showing different numbers. The snapshot id, configuration id and method version above identify the data this brief was written from.*

## Research question

Was the rise in the retail price of Rice (imported) in Mutarara (Mozambique) around October 2022 unusual for that market, was it shared by comparable markets and other foods, and what can the available data say about why it happened?

## Summary

In October 2022 the price of Rice (imported) in Mutarara had risen 13.9% over 12 months, which is unusual for this market (robust z +7.8; higher than 71% of the 48 earlier 12-month changes). The screening rule flagged 2 months. The episode dates show where the screening rule fired, not the full duration of any event. Few of the 6 assessable comparable markets (of 50 found) were unusually high at the time. Few of the 8 assessable other foods in the same market were unusually high against their own past. Several rose substantially in nominal terms (4 of 9 by 25% or more) while staying within their own usual ranges. This pattern is consistent with local supply or market-access disruption or general inflation or currency depreciation, but the data integrated here cannot establish which, if any, was responsible. It cannot assess weather-related production shock or policy intervention.

*Inference: descriptive and associational; no causal claim.*

| Question | Finding | Basis |
|---|---|---|
| 12-month change | +13.9% | nominal, local currency |
| Unusual for this market? | Yes | robust z +7.8, 48 earlier changes |
| Persistence | 2 months | detected October 2022 to November 2022 (may split or truncate a longer event) |
| Other markets | Local | 0 of 6 assessable comparable markets also unusual (50 found) |
| Other foods, same market | Narrow | 1 of 8 assessable foods also unusual |
| Seasonal? | No | usual pattern implies +0.0% over these months |
| Data quality | Adequate | 33 of 38 months observed |

## Observed facts

- The reported retail price of Rice (imported) in Mutarara for October 2022 was 68.33 MZN/KG (nominal, MZN).
- Over the 11 observed months from October 2021 to September 2022 the price averaged 65.22 MZN/KG.
- The highest 12-month change in the episode came in October 2022, at a price of 68.33 MZN/KG.
- In the investigation window (October 2020 to November 2023) 33 of 38 months have a valid price; the longest run of missing months is 1.

## Quantitative description

- The 12-month change to October 2022 was +13.9%; the change from the previous month was +6.5%. *(descriptive)*
- The October 2022 price was +4.8% relative to its average over the 12 months before the movement began (price index 105, baseline = 100). *(descriptive)*
- Compared with the earlier 12-month changes of this series (from 5 calendar years, ending September 2022), it was higher than 71% of the 48 (robust z-score +7.8; a typical 12-month change here was +0.0%, and 80% fell between -2.6% and +24.2%). *(descriptive)*
- The reference holds fewer than 60 earlier changes, so the rank and z-score may shift as more history accumulates. Consecutive 12-month changes overlap, so the number of independent years is about 5. *(descriptive)*
- The screening rule (|robust z| >= 2, reaching 3 at least once) flagged the 12-month change from October 2022 to November 2022 (2 months). A detected episode is the run of months in which the screening rule fired. It can split one longer disruption into several episodes (a single month just below the threshold ends a run) or cut it short (the rule needs earlier history and observed months), so its dates and length are not the duration of any real-world event. *(descriptive)*
- Six months after the peak the price was +8.5% relative to the peak. *(descriptive)*
- The usual seasonal pattern (from 5 earlier years) implies a change of +0.0% from September to October; the observed change over those months was +6.5%. *(descriptive)*
- Comparable markets (same commodity, unit, price type and currency): 50 comparable markets found; 14 reported a 12-month change within a month of the peak; 6 had enough history to be assessed against their own past; 0 of those 6 were also unusually high. The extent (local) describes only the 6 assessable markets, not every market in the country; the median 12-month change across the comparable markets with a change was +0.0%. *(associational)*
- Other foods in the same market: 12 other foods found; 9 reported a 12-month change within a month of the peak; 8 had enough history to be assessed against their own past; 1 of those 8 were also unusually high (their median 12-month change was +10.7%). The breadth (narrow) describes only the 8 assessable foods. *(associational)*

## Price history in the window

*Robust z* here compares each month with every 12-month change before that month. The headline score compares the month investigated only with changes before the episode began, so that an episode does not dilute its own reference; the two can differ inside an episode.

| Month | Price (MZN/KG) | Change on month | Change on year | Robust z | Assessment |
|---|---|---|---|---|---|
| 2020-10 | 48.33 | -12.1% | -3.3% |  | withheld (short_history) |
| 2020-11 | 50.00 | +3.5% | +0.0% |  | withheld (short_history) |
| 2020-12 | 52.50 | +5.0% | +5.0% |  | withheld (short_history) |
| 2021-01 | 50.00 | -4.8% | +0.0% |  | withheld (short_history) |
| 2021-02 | 50.00 | +0.0% | +0.0% |  | withheld (short_history) |
| 2021-03 | 56.33 | +12.7% |  |  |  |
| 2021-04 | 60.00 | +6.5% |  |  |  |
| 2021-05 | 56.25 | -6.2% | -6.2% |  | withheld (short_history) |
| 2021-06 | 53.75 | -4.4% | -6.2% |  | withheld (short_history) |
| 2021-07 | 55.00 | +2.3% | -8.3% |  | withheld (short_history) |
| 2021-08 |  |  |  |  | no observation |
| 2021-09 | 49.17 |  | -10.6% |  | withheld (degenerate_history) |
| 2021-10 | 60.00 | +22.0% | +24.1% |  | withheld (degenerate_history) |
| 2021-11 | 60.00 | +0.0% | +20.0% |  | withheld (degenerate_history) |
| 2021-12 | 66.67 | +11.1% | +27.0% |  | withheld (degenerate_history) |
| 2022-01 | 65.00 | -2.5% | +30.0% |  | withheld (degenerate_history) |
| 2022-02 | 68.33 | +5.1% | +36.7% |  | withheld (degenerate_history) |
| 2022-03 | 70.00 | +2.4% | +24.3% |  | withheld (degenerate_history) |
| 2022-04 | 63.75 | -8.9% | +6.3% |  | withheld (degenerate_history) |
| 2022-05 | 67.00 | +5.1% | +19.1% |  | withheld (degenerate_history) |
| 2022-06 | 66.67 | -0.5% | +24.0% |  | withheld (degenerate_history) |
| 2022-07 | 65.83 | -1.3% | +19.7% |  | withheld (degenerate_history) |
| 2022-08 |  |  |  |  | no observation |
| 2022-09 | 64.17 |  | +30.5% |  | withheld (degenerate_history) |
| 2022-10 | 68.33 | +6.5% | +13.9% | +7.81 | assessed |
| 2022-11 | 66.67 | -2.4% | +11.1% | +3.17 | assessed |
| 2022-12 | 66.67 | +0.0% | +0.0% | +0.00 | assessed |
| 2023-01 | 68.33 | +2.5% | +5.1% | +1.50 | assessed |
| 2023-02 | 60.00 | -12.2% | -12.2% | -3.91 | assessed |
| 2023-03 |  |  |  |  | no observation |
| 2023-04 | 74.17 |  | +16.3% | +4.55 | assessed |
| 2023-05 |  |  |  |  | no observation |
| 2023-06 | 76.67 |  | +15.0% | +3.34 | assessed |
| 2023-07 |  |  |  |  | no observation |
| 2023-08 | 75.00 |  |  |  |  |
| 2023-09 | 66.67 | -11.1% | +3.9% | +0.76 | assessed |
| 2023-10 | 52.00 | -22.0% | -23.9% | -5.10 | assessed |
| 2023-11 | 55.00 | +5.8% | -17.5% | -3.40 | assessed |

## Comparison with other markets

Comparable markets: same commodity, unit (KG), price type and currency (MZN) in Mozambique. 50 comparable markets found; 14 reported a 12-month change within a month of the peak; 6 had enough history to be assessed against their own past; 0 of those 6 were also unusually high. Classification **local**, which describes only the 6 assessable markets (a peer is elevated when its robust z is beyond 2 in the same direction in at least 2 of the 3 months around the peak; widespread: >= 50% of assessable peers elevated; local: < 25%; inconclusive: fewer than 3 assessable peers).

| Market | Admin 1 | Month | 12-month change | Robust z | Unusual, same direction |
|---|---|---|---|---|---|
| Lichinga | Niassa | 2022-09-01 | +40.0% | +2.60 | no |
| Montepuez | Cabo Delgado | 2022-09-01 | +22.2% | +1.56 | no |
| Maputo | Cidade de Maputo | 2022-10-01 | +3.5% | +0.09 | no |
| Mocuba | Zambézia | 2022-10-01 | +0.0% | +0.00 | no |
| Massinga | Inhambane | 2022-10-01 | +2.1% | -0.23 | no |
| Inhambane | Inhambane | 2022-10-01 | -1.1% | -0.39 | no |
| Nacala | Nampula |  |  | no 12-month change within a month of the peak |  |
| Xai Xai | Gaza |  |  | no 12-month change within a month of the peak |  |
| Quelimane | Zambézia |  |  | no 12-month change within a month of the peak |  |
| Macanga | Niassa |  |  | no 12-month change within a month of the peak |  |
| Nhamatanda | Sofala |  |  | no 12-month change within a month of the peak |  |
| Bela Vista | Maputo |  |  | no 12-month change within a month of the peak |  |
| Chibuto | Gaza |  |  | no 12-month change within a month of the peak |  |
| Inharrime | Inhambane | 2022-10-01 | +20.0% | too little earlier history |  |
| Tete | Tete |  |  | no 12-month change within a month of the peak |  |
| Cuamba | Niassa |  |  | no 12-month change within a month of the peak |  |
| Moamba | Maputo |  |  | no 12-month change within a month of the peak |  |
| Govuro | Inhambane |  |  | no 12-month change within a month of the peak |  |
| Namuno | Cabo Delgado |  |  | no 12-month change within a month of the peak |  |
| Gondola | Manica | 2022-10-01 | -9.1% | too little earlier history |  |
| Manhica | Maputo |  |  | no 12-month change within a month of the peak |  |
| Changara | Tete |  |  | no 12-month change within a month of the peak |  |
| Buzi | Sofala |  |  | no 12-month change within a month of the peak |  |
| Boane | Maputo |  |  | no 12-month change within a month of the peak |  |
| Chokwe | Gaza |  |  | no 12-month change within a month of the peak |  |
| Pemba | Cabo Delgado |  |  | no 12-month change within a month of the peak |  |
| Beira | Sofala |  |  | no 12-month change within a month of the peak |  |
| Cidade da Matola | Maputo |  |  | no 12-month change within a month of the peak |  |
| Inhassoro | Inhambane | 2022-10-01 | +0.0% | too little earlier history |  |
| Chimoio | Manica |  |  | no 12-month change within a month of the peak |  |

(20 more in the CSV export.)

Other foods in the same market and currency: 12 other foods found; 9 reported a 12-month change within a month of the peak; 8 had enough history to be assessed against their own past; 1 of those 8 were also unusually high. Classification **narrow**, which describes only the 8 assessable foods. Only relative (percentage) changes are compared across different foods.

In nominal terms, 4 of the 9 other foods with a 12-month change around the peak rose by 25% or more (median +10.7%). A food that moved a lot but stayed within its own historical range is *not unusual* by this method; that is a statement about its history, not about whether its price rose, and it is not evidence for or against any macroeconomic mechanism.

## Seasonality

Seasonal profile from 5 pre-episode years: prices typically peak in May and are lowest in January (amplitude +0.2%). Expected change from 2022-09 to 2022-10: +0.0%; observed: +6.5%. Verdict: not seasonal.

## Contextual evidence

- Weather: not integrated for this market or crop.
- Consumer price index: not integrated for this country (prices are nominal).
- Exchange rate: not integrated for this country.
- Without a price index or an exchange rate, an inflation or currency mechanism **cannot be assessed**: other foods rising together, or staying within their usual ranges, neither supports nor argues against it.
- Missing context is reported as missing; it is never treated as zero.

## Economic context

**Context snapshot:** `20261120T004928_ba3846` (observation hash `ba3846fda542`); context identity `33cae43052b41e7a`  
**Vintage:** current archived vintage at retrieval: historical values may since have been revised, so comparisons of past months are exploratory, not a reconstruction of what was known then.  
**Window:** October 2020 to November 2023; month of interest October 2022; pre-episode baseline October 2021 to September 2022.

### Observed facts

- The IMF headline consumer price index for Mozambique is available from January 2010 to October 2026 (202 months; 0 of 38 window months missing).
- The IMF food consumer price index for Mozambique is available from January 2010 to October 2026 (202 months; 0 of 38 window months missing).
- The IMF exchange rate for Mozambique is available from January 2010 to August 2025 (188 months; 0 of 38 window months missing).
- Rice (imported) is mapped to Rice, Thailand 5% broken, white, milled, Rice, Viet Nam 5% broken, white, milled, Rice, Thailand 25% broken, white, milled with medium confidence (imported supply). The benchmark is the same commodity, traded internationally, and a plausible reference for imported supplies of this product. It still differs from the local price in grade, place, stage of the supply chain and currency.
- Exchange rate, period average (domestic currency per US dollar) for MOZ ends in 2025-08, well before the newest data in the snapshot.
- Exchange rate, end of period (domestic currency per US dollar) for MOZ ends in 2025-08, well before the newest data in the snapshot.

### Quantitative description

- The local price changed +13.9% over the 12 months to October 2022 (nominal, MZN).
- The national consumer price index changed +11.8% over the same 12 months (IMF/World Bank snapshot 20261120T004928_ba3846). A change in one food's price and the change in the general price level are different quantities.
- The food component of the consumer price index changed +14.7%.
- Food inflation exceeded headline inflation by +2.9 percentage points.
- Price relative to headline CPI (12-month change at the event month): the price changed +13.9% against +11.8% for the headline CPI, a relative change of +1.8%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Price relative to food CPI (12-month change at the event month): the price changed +13.9% against +14.7% for the food CPI, a relative change of -0.7%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Price relative to headline CPI (change from the pre-episode baseline to the peak): the price changed +4.8% against +4.9% for the headline CPI, a relative change of -0.1%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Price relative to food CPI (change from the pre-episode baseline to the peak): the price changed +4.8% against +5.8% for the food CPI, a relative change of -1.0%. This is the price relative to the national average basket, not a change in any household's purchasing power.
- Domestic currency per US dollar changed +0.1% over the 12 months (more units per dollar), a -0.1% change in the dollar value of one unit of the local currency (official rate, period average).
- At the official period-average rate the price in US dollars changed +13.8% (indicative; households may have faced a different rate).
- Rice, Thailand 5% broken, white, milled changed +7.5% in US dollars over the 12 months to October 2022.
- In local currency the same benchmark changed +7.5%: a +7.5% change in dollars combined with a +0.1% change in the exchange rate (log changes +0.072 and +0.001, adding exactly). The split is arithmetic and does not show why either part moved.
- The benchmark's local-currency change is 56% of the price's 12-month log change (arithmetic ratio of two logarithmic changes).
- Rice, Viet Nam 5% broken, white, milled changed +1.1% in US dollars over the 12 months to October 2022.
- In local currency the same benchmark changed +1.2%: a +1.1% change in dollars combined with a +0.1% change in the exchange rate (log changes +0.011 and +0.001, adding exactly). The split is arithmetic and does not show why either part moved.
- The benchmark's local-currency change is 9% of the price's 12-month log change (arithmetic ratio of two logarithmic changes).
- Rice, Thailand 25% broken, white, milled changed +6.3% in US dollars over the 12 months to October 2022.
- In local currency the same benchmark changed +6.4%: a +6.3% change in dollars combined with a +0.1% change in the exchange rate (log changes +0.061 and +0.001, adding exactly). The split is arithmetic and does not show why either part moved.
- The benchmark's local-currency change is 48% of the price's 12-month log change (arithmetic ratio of two logarithmic changes).
- Rank correlations between monthly changes in this price and Rice, Thailand 5% broken, white, milled (USD) led by 0 to 6 months ranged from -0.30 to +0.08 (up to 63 paired months through November 2023). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Rice, Viet Nam 5% broken, white, milled (USD) led by 0 to 6 months ranged from -0.23 to +0.07 (up to 63 paired months through November 2023). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Rice, Thailand 25% broken, white, milled (USD) led by 0 to 6 months ranged from -0.31 to +0.09 (up to 63 paired months through November 2023). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Exchange rate (domestic currency per USD) led by 0 to 6 months ranged from -0.12 to +0.11 (up to 63 paired months through November 2023). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Consumer price index (all items) led by 0 to 6 months ranged from -0.13 to +0.17 (up to 63 paired months through November 2023). Descriptive; no lag is singled out.
- Rank correlations between monthly changes in this price and Consumer price index (food) led by 0 to 6 months ranged from -0.17 to +0.15 (up to 63 paired months through November 2023). Descriptive; no lag is singled out.

### Propositions the figures can be set beside

| Proposition | Assessment | Basis |
|---|---|---|
| General inflation, as measured by the national consumer price index, accounts for most of the rise | consistent | the national consumer price index changed +11.8% against +13.9% for this price, 86% of its log change. The index is a national average of a different basket, so a small figure does not exclude a local or product-specific price-level movement |
| Food inflation, as measured by the food component of the index, accounts for most of the rise | consistent | food CPI changed +14.7% against +13.9% for this price (106% of its log change) |
| A depreciation of the local currency against the US dollar accounts for most of the rise | argued against by these figures | units of local currency per dollar changed +0.1% against +13.9% for the price (0% of its log change) |
| International benchmark prices, in local currency, moved by a comparable amount to this price | partly consistent | Rice, Thailand 5% broken, white, milled changed +7.5% in local currency; Rice, Viet Nam 5% broken, white, milled changed +1.2% in local currency; Rice, Thailand 25% broken, white, milled changed +6.4% in local currency against +13.9% for this price; the share of the price's log change is 48% at the median across 3 benchmarks (range 9% to 56%). The median is used so that the most favourable of several alternative quotations does not decide the status. Grade, place, freight, duties and margins differ between the benchmark and the local product |

### Changes at a glance

| Item | 12-month change | Baseline to peak | State |
|---|---|---|---|
| local price | +13.9% | +4.8% | ok |
| Consumer price index (all items) | +11.8% | +4.9% | ok |
| Consumer price index (food and non-alcoholic beverages) | +14.7% | +5.8% | ok |
| Exchange rate, period average (domestic currency per US dollar) | +0.1% | +0.0% | ok |
| Exchange rate, end of period (domestic currency per US dollar) | +0.1% | +0.0% | ok |
| Rice, Thailand 5% broken, white, milled | +7.5% | +1.3% | ok |
| Rice, Thailand 5% broken, white, milled (local currency) | +7.5% | +1.4% | ok |
| Rice, Viet Nam 5% broken, white, milled | +1.1% | +2.1% | ok |
| Rice, Viet Nam 5% broken, white, milled (local currency) | +1.2% | +2.1% | ok |
| Rice, Thailand 25% broken, white, milled | +6.3% | +0.2% | ok |
| Rice, Thailand 25% broken, white, milled (local currency) | +6.4% | +0.2% | ok |
| Price relative to headline CPI (12-month change at the event month) | +1.8% | — | ok |
| Price relative to food CPI (12-month change at the event month) | -0.7% | — | ok |
| Price relative to headline CPI (change from the pre-episode baseline to the peak) | — | -0.1% | ok |
| Price relative to food CPI (change from the pre-episode baseline to the peak) | — | -1.0% | ok |

### Cautions

- Exchange rate, period average (domestic currency per US dollar) for MOZ ends in 2025-08, well before the newest data in the snapshot.
- Exchange rate, end of period (domestic currency per US dollar) for MOZ ends in 2025-08, well before the newest data in the snapshot.
- MOZ's exchange-rate arrangement is not classified in the reference table (it is not assumed to float).
- The price's currency is assumed to be the national currency of the IMF exchange-rate series (not independently verifiable here).
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
| Recording, unit or measurement error | Not indicated by the available evidence | no implausible jumps or reversing single-month spikes were detected | the original survey records or enumerator notes; confirmation of the unit and outlet by the data provider |
| Normal seasonal pattern (lean season, harvest timing) | The available evidence argues against this being the main explanation | the usual seasonal pattern implies +0.0% over these months against +6.5% observed; the unusualness test compares 12-month changes, which already removes a regular seasonal pattern | the local crop calendar and the timing of the most recent harvest |
| Country-wide supply or demand change for this commodity (harvest shortfall, import or trade disruption) | The available evidence argues against this being the main explanation | 50 comparable markets found; 14 reported a 12-month change within a month of the peak; 6 had enough history to be assessed against their own past; 0 of those 6 were also unusually high; the classification (local) describes only the 6 assessable markets; the others could not be judged either way | national production estimates for the relevant season (not integrated); import, export and cross-border trade flows (not integrated) |
| Local supply or market-access disruption (transport, insecurity, market closure) | Consistent with the available evidence | 50 comparable markets found; 14 reported a 12-month change within a month of the peak; 6 had enough history to be assessed against their own past; 0 of those 6 were also unusually high; the episode lasted 2 months | conflict and access-constraint records for the area (not integrated); transport costs and road or border closures (not integrated) |
| General inflation or currency depreciation | Consistent with the available evidence | General inflation, as measured by the national consumer price index, accounts for most of the rise: consistent (the national consumer price index changed +11.8% against +13.9% for this price, 86% of its log change. The index is a national average of a different basket, so a small figure does not exclude a local or product-specific price-level movement); Food inflation, as measured by the food component of the index, accounts for most of the rise: consistent (food CPI changed +14.7% against +13.9% for this price (106% of its log change)); A depreciation of the local currency against the US dollar accounts for most of the rise: argued against by these figures (units of local currency per dollar changed +0.1% against +13.9% for the price (0% of its log change)) | a parallel-market or import-cost exchange rate where the official rate diverged (not integrated); import prices, tariffs and freight for the commodity (not integrated) |
| Weather-related production shock (drought, floods) | Cannot be assessed with the data integrated here | no weather data are integrated for this market or crop | harvest outcome for the season (not integrated); evidence that this market is supplied from those areas |
| Policy intervention (export ban, tariff, subsidy removal, price control) | Cannot be assessed with the data integrated here | no record of policy measures is integrated | dated records of trade and price policy measures for the country |
| Transmission of international prices | Partly consistent with the available evidence | International benchmark prices, in local currency, moved by a comparable amount to this price: partly consistent (Rice, Thailand 5% broken, white, milled changed +7.5% in local currency; Rice, Viet Nam 5% broken, white, milled changed +1.2% in local currency; Rice, Thailand 25% broken, white, milled changed +6.4% in local currency against +13.9% for this price; the share of the price's log change is 48% at the median across 3 benchmarks (range 9% to 56%). The median is used so that the most favourable of several alternative quotations does not decide the status. Grade, place, freight, duties and margins differ between the benchmark and the local product) | the commodity's actual origin, grade and landed cost (not integrated); import dependence and trade policy for the country (not integrated) |

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
- That prices of this commodity rose across the country. *(descriptive)*
- That a robust z-score is a probability, significance level or false-positive rate. The robust z-score thresholds are screening rules, not calibrated significance tests: food-price changes are heavy-tailed and overlap from month to month, so a z-score is not a probability and no false-positive rate is claimed. *(descriptive)*
- That the detected episode is the full duration of a real-world disruption. A detected episode is the run of months in which the screening rule fired. It can split one longer disruption into several episodes (a single month just below the threshold ends a run) or cut it short (the rule needs earlier history and observed months), so its dates and length are not the duration of any real-world event. *(descriptive)*

## Data quality

33 of 38 months observed in the window; longest gap 1 months. 33 stored records, 0 not used.

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

Market Almanac, price-shock investigation `7978b8ca8e49233a`, method `shock-1`, price snapshot `20261118T020220_59ed26`.

## Reproducible configuration

```json
{
  "event": "2022-10",
  "format": "investigation-1",
  "method_version": "shock-1",
  "peers": "same country, commodity, unit, price type and currency",
  "series_id": "ps_9a26f4dc59e9b2f2",
  "snapshot_id": "20261118T020220_59ed26",
  "window": {
    "end": "2023-11",
    "start": "2020-10"
  }
}
```

Retrieve the same analysis from the API: `GET /api/v1/investigations/ps_9a26f4dc59e9b2f2?event=2022-10&start=2020-10&end=2023-11&snapshot=20261118T020220_59ed26&context=20261120T004928_ba3846` (add the snapshots to be told if the data have since been revised).
