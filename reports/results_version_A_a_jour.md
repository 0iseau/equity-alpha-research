# Version A: results of the out-of-sample test, 1993–2025

Status: single test, run once on 2026-11-13 under freeze `ee22d6708bdc`
(runs: candidates `f713bd2fcd67`, backtest `8c89f31d11d4`, alphas
`83a28ed892ef`). No step was retried. Nothing was changed after the results
were seen. Full grid of numbers: [tables_A.md](tables_A.md). Figures:
`figures/A_*.png`.

Reading guide: sections 1 to 5 are **measured** (numbers straight from
`alphas_A.csv`, `summary_A.csv` and the monthly record of the backtest).
Section 6 is **interpretation**. Section 7 lists the reservations to state.

Units: returns and alphas in % a year (monthly value × 12); t-statistics in
parentheses, Newey-West with 6 lags; costs in basis points (bp) of the fund a
month; turnover is the sum of the absolute trades of a month (purchases plus
sales) in % of the fund.

## 1. Main result (defined before the test)

**Version A (market characteristics only), boosted trees, all sizes, execution
on the first trading day, order cap of 10 % of the ADV, net of half spread and
price impact, before commissions, 1993–2025: the alpha against the five
Fama-French factors and momentum is −5.09 % a year (t = −5.13).**

The strategy does not deliver alpha. It loses to its factor benchmark, and the
loss is statistically significant.

- Before trading costs the alpha is −0.88 % a year (t = −0.90): not different
  from zero.
- Trading costs take 4.23 % a year (21.4 bp of half spread and 13.8 bp of price
  impact a month).
- With the commission stress (6 cents a share until 2004, 4 cents after): −6.96 %
  a year (t = −6.59).
- Conditional diagnostic (loadings allowed to move with the share of the fund
  invested): −4.78 % a year (t = −4.90). The conclusion does not come from the
  cash held at the start of the sample.

## 2. The main configuration in detail

| | 1993–2025 | 1993–2008 | 2009–2025 |
|---|---|---|---|
| Months | 396 | 192 | 204 |
| Excess return, gross | 9.00 | 5.74 | 12.07 |
| Excess return, net (t) | 4.76 (1.70) | −2.01 (−0.47) | 11.14 (3.68) |
| Volatility, net | 15.6 | 15.5 | 15.5 |
| Sharpe ratio, net | 0.31 | −0.13 | 0.72 |
| Market excess return | 9.06 | 3.96 | 13.87 |
| Market Sharpe ratio | 0.60 | 0.26 | 0.90 |
| Net return minus market (t) | −4.30 (−4.47) | −5.97 (−3.76) | −2.73 (−2.61) |
| Worst month, net | −16.5 | −16.5 | −14.2 |
| **Alpha, net: CAPM** | −3.81 (−3.74) | −5.64 (−3.50) | −2.24 (−1.91) |
| **Alpha, net: FF3** | −4.03 (−3.88) | −5.88 (−3.46) | −2.49 (−2.09) |
| **Alpha, net: FF5** | −4.37 (−4.12) | −6.44 (−3.48) | −2.54 (−2.26) |
| **Alpha, net: FF5 + momentum** | **−5.09 (−5.13)** | −7.28 (−4.07) | −2.78 (−3.04) |
| Alpha, gross: CAPM | 0.46 (0.44) | 2.09 (1.23) | −1.31 (−1.17) |
| Alpha, gross: FF3 | 0.23 (0.22) | 1.83 (1.04) | −1.56 (−1.36) |
| Alpha, gross: FF5 | −0.13 (−0.12) | 1.29 (0.68) | −1.62 (−1.50) |
| Alpha, gross: FF5 + momentum | −0.88 (−0.90) | 0.46 (0.26) | −1.85 (−2.05) |
| Alpha, net + commission stress: FF5 + momentum | −6.96 (−6.59) | −10.13 (−5.57) | −3.76 (−3.94) |
| Half spread, bp a month | 21.4 | 42.0 | 2.1 |
| Price impact, bp a month | 13.8 | 22.6 | 5.6 |
| Commission stress, bp a month | 15.5 | 23.2 | 8.2 |
| Turnover wanted / filled, % a month | 113 / 110 | 144 / 138 | 84 / 83 |
| Orders capped / not filled, % of orders | 13.3 / 5.8 | 22.0 / 8.8 | 2.2 / 1.9 |
| Cash after the trades, mean % | 0.7 | 1.4 | 0.03 |
| Stocks to hold / held, median | 614 / 976 | 682 / 1,165 | 588 / 841 |
| Effective number of stocks, median | 33 | 29 | 35 |
| Largest weight, maximum % of the fund | 35.7 | 33.8 | 35.7 |
| Largest weight, median % of the invested part | 10.8 | 11.1 | 10.5 |

Loadings of the net return on FF5 + momentum, 1993–2025: market 1.01, SMB
−0.09, HML 0.07, RMW 0.04, CMA 0.01, momentum 0.10; R² = 0.87.

Value of 1 invested at the end of 1992, at the end of 2025: market 29.7; fund
before costs 28.6; fund after costs 7.1 (figure `A_cumulative_value.png`).

Costs through time (figure `A_costs.png`), main configuration:

| Years | Half spread bp | Impact bp | Turnover filled % | Cash % | Stocks held | Effective stocks |
|---|---|---|---|---|---|---|
| 1993–1996 | 63.0 | 32.0 | 117 | 5.3 | 1,597 | 36 |
| 1997–2000 | 62.8 | 22.5 | 144 | 0.3 | 1,263 | 27 |
| 2001–2004 | 32.3 | 19.6 | 140 | 0.1 | 890 | 22 |
| 2005–2008 | 9.9 | 16.2 | 152 | 0.1 | 938 | 37 |
| 2009–2012 | 4.6 | 11.7 | 119 | 0.1 | 904 | 37 |
| 2013–2016 | 1.2 | 4.5 | 69 | 0.0 | 750 | 45 |
| 2017–2020 | 1.1 | 3.5 | 67 | 0.0 | 774 | 32 |
| 2021–2025 | 1.7 | 3.4 | 78 | 0.0 | 1,098 | 25 |

Other measured facts on the main configuration:

- The largest position is above 10 % of the fund in 226 months of 396, above
  20 % in 18 months; the smallest effective number of stocks in a month is 7.
- 97.4 % of the amounts traded pay a quoted spread, 2.6 % a high-low estimate.
- Write-offs for unknown returns (rule D16) sum to 0.31 % of the fund over the
  33 years: immaterial.
- Cash is 8.9 % on average in 1993 (the fund starts all in cash) and zero in
  2025 (figure `A_cash_share.png`).
- Candidates: the top 10 % holds 518 stocks in the median month (272 to 2,378).
  The tree forecasts are coarse: up to 931 stocks tie with the breakpoint, and
  in 34 months of 396 the top 10 % equals the top 20 % (the 10 % / 20 % buffer
  does nothing in those months). The ridge has no ties.

## 3. The ten configurations, 1993–2025

Alpha against FF5 + momentum, % a year (t):

| Configuration | Gross | Net | Net + commission stress | Costs bp a month | Turnover % | Cash % | Net excess return | Sharpe |
|---|---|---|---|---|---|---|---|---|
| **Trees, all sizes, first day (MAIN)** | −0.88 (−0.90) | **−5.09 (−5.13)** | −6.96 (−6.59) | 35.3 | 110 | 0.7 | 4.76 | 0.31 |
| Trees, large universe, first day | −0.71 (−0.67) | −4.64 (−4.32) | −6.25 (−5.56) | 32.9 | 111 | 0.4 | 5.30 | 0.34 |
| Ridge, all sizes, first day | 2.09 (1.22) | −4.01 (−2.28) | −7.04 (−3.92) | 51.5 | 130 | 4.7 | 6.29 | 0.37 |
| Ridge, large universe, first day | 2.41 (1.54) | −2.96 (−1.85) | −5.32 (−3.28) | 45.3 | 137 | 2.3 | 7.59 | 0.46 |
| Trees, all sizes, close to close | −1.11 (−0.97) | −5.48 (−4.58) | −7.40 (−5.89) | 36.5 | 110 | 0.9 | 4.52 | 0.29 |
| Trees, large universe, close to close | −1.05 (−0.83) | −5.07 (−3.91) | −6.71 (−4.99) | 33.7 | 111 | 0.5 | 5.01 | 0.32 |
| Ridge, all sizes, close to close | 3.72 (1.82) | −2.50 (−1.24) | −5.57 (−2.74) | 52.4 | 130 | 5.0 | 7.63 | 0.45 |
| Ridge, large universe, close to close | 3.57 (2.06) | −1.88 (−1.11) | −4.26 (−2.50) | 46.0 | 136 | 2.7 | 8.72 | 0.52 |
| Trees, all sizes, first day, cap 1 % | −1.11 (−1.18) | −3.16 (−3.55) | −4.44 (−4.90) | 17.3 | 83 | 12.4 | 5.91 | 0.42 |
| Trees, large universe, first day, cap 1 % | −0.57 (−0.59) | −2.56 (−2.83) | −3.70 (−4.02) | 16.8 | 85 | 11.4 | 6.60 | 0.47 |

Market: excess return 9.06 % a year, Sharpe 0.60. **No configuration has a
positive net alpha, and none beats the market after costs** (net return minus
market between −0.34 % and −4.55 % a year; see `tables_A.md`).

## 4. Sub-periods, net alpha against FF5 + momentum

| Configuration | 1993–2008 | 2009–2025 |
|---|---|---|
| **Trees, all sizes, first day (MAIN)** | −7.28 (−4.07) | −2.78 (−3.04) |
| Trees, large universe, first day | −7.06 (−3.59) | −2.18 (−2.58) |
| Ridge, all sizes, first day | −7.39 (−3.08) | −0.32 (−0.15) |
| Ridge, large universe, first day | −5.89 (−2.46) | 0.29 (0.15) |
| Trees, all sizes, close to close | −8.53 (−4.00) | −2.57 (−2.34) |
| Trees, large universe, close to close | −8.21 (−3.47) | −2.05 (−2.09) |
| Ridge, all sizes, close to close | −4.39 (−1.49) | 0.23 (0.10) |
| Ridge, large universe, close to close | −3.46 (−1.43) | 0.34 (0.16) |
| Trees, all sizes, first day, cap 1 % | −3.54 (−2.43) | −2.70 (−3.03) |
| Trees, large universe, first day, cap 1 % | −3.08 (−1.93) | −2.08 (−2.57) |

Gross alpha against FF5 + momentum by sub-period:

| Configuration | 1993–2008 | 2009–2025 |
|---|---|---|
| Trees, all sizes, first day (MAIN) | 0.46 (0.26) | −1.85 (−2.05) |
| Trees, large universe, first day | 0.16 (0.08) | −1.32 (−1.58) |
| Ridge, all sizes, first day | 2.38 (0.96) | 2.35 (1.07) |
| Ridge, large universe, first day | 3.07 (1.25) | 2.28 (1.19) |

## 5. The comparisons fixed at the freeze, one by one

1. **Two universes.** Removing the stocks below the NYSE 20th percentile
   changes little: net alpha −4.64 % (t = −4.32) against −5.09 %. Costs are
   almost the same (32.9 against 35.3 bp a month).
2. **Two models.** The ridge has a positive gross alpha that is not
   significant (2.09 %, t = 1.22; large universe 2.41 %, t = 1.54) and trades
   more (130 % a month, 51.5 bp of costs). Net: −4.01 % (t = −2.28). The two
   models agree on the sign of the net result.
3. **Close-to-close execution.** For the trees: −5.48 % (t = −4.58), close to
   the first-day result. For the ridge the gross alpha is higher close to close
   (3.72 %, t = 1.82) than on the first day (2.09 %): a difference of 1.6
   points a year, which a real order placed after the close of month t cannot
   earn.
4. **Order cap of 1 %.** Net alpha −3.16 % (t = −3.55). Less negative only
   because the fund trades less (83 % a month, 17.3 bp of costs) and holds
   12.4 % of cash on average (76 % in 1993).
5. **Commission stress.** Adds 15.5 bp a month (1.86 % a year) for the main
   configuration: −6.96 % (t = −6.59).
6. **Sub-periods.** The net loss is larger in 1993–2008 (−7.28 %), when costs
   are 64.6 bp a month, than in 2009–2025 (−2.78 %), when they are 7.7 bp. In
   2009–2025 the alpha of the trees is negative even before costs (−1.85 %,
   t = −2.05).
7. **Conditional diagnostic.** −4.78 % (t = −4.90): same conclusion.
8. **Version B** (market and accounting characteristics): run later the same
   day through the same frozen scripts; it confirms the result (net alpha of
   the main configuration −5.54 %, t = −4.52). See
   [results_version_B.md](results_version_B.md).

## 6. Reading for the investment committee (interpretation)

**Is the strategy worthwhile for a manager? No.** As frozen, it earns less
than the market it is exposed to, in every configuration that was planned, and
significantly so for the main one. A manager holding the market portfolio would
have ended with about four times the wealth of the fund after costs.

What the numbers suggest, in order of importance:

1. **Turnover destroys the result.** The fund replaces about 110 % of its
   value every month in trades (purchases plus sales), roughly thirteen times a
   year. Monthly forecasts from market characteristics (short-term reversal,
   momentum, volatility, liquidity) change quickly, and a buffer of 10 % / 20 %
   does not slow them enough. At 35 bp a month, costs take 4.2 % a year, almost
   the whole distance between the gross alpha (−0.9 %) and the net alpha
   (−5.1 %).
2. **There is no gross alpha to protect in the main model.** Before the
   costs it paid, the tree portfolio has an alpha of −0.9 % (t = −0.90), not
   different from zero. Its return is the
   market's: beta 1.01, R² 0.87, small loadings elsewhere. The gross alpha
   of the value-weighted tree fund is not statistically different from zero
   (this does not show that the forecasts hold no information).
3. **Value weights put the fund in very large stocks.** The book holds about a
   thousand names but is worth 33 stocks of equal weight; one stock often
   weighs more than 10 % of the fund. Forecasts of monthly returns are known to
   work mostly in small and illiquid stocks; with value weights the result is
   decided by a few mega-caps, where the forecast has the least to say. This is
   also why the two universes give the same answer. The price paid is tracking
   error without reward, not capacity.
4. **Cash is not the explanation.** With the 10 % cap the fund is almost
   fully invested from 1997 on (0.7 % of cash on average over the sample); the conditional diagnostic gives the same alpha.
5. **Lower costs in recent years do not rescue the strategy.** After 2009 costs
   fall to under 8 bp a month, and the net alpha of the trees is still −2.8 %
   (t = −3.04), with a negative gross alpha. Whether predictability itself
   declined is not measured here (the literature on anomalies after
   publication describes such a decline; to check before citing: McLean and
   Pontiff 2016).
6. **The ridge is the less bad model, not a good one.** Its gross alpha of 2 to
   4 % a year is not significant, part of it is earned before an order can be
   filled, and its turnover (130 %) costs more than it earns. After 2009 its
   net alpha is zero (−0.3 % to +0.3 %, t below 0.2 in absolute value).

What this result is: an honest negative. The method was fixed before the test,
the test was run once, and the answer is that a long-only, value-weighted,
monthly-rebalanced fund of USD 100 million built on machine-learning forecasts
from market characteristics has no alpha after realistic trading costs. It is
consistent with the objection of Avramov, Cheng and Metzker (2023, to check
before citing) that such forecasts earn their returns in stocks that are hard
to trade and at a turnover that costs erase.

What it is not: evidence that return prediction is impossible. The tests say
nothing about equal weights, a long-short portfolio, a slower rebalancing or a
cost-aware construction; none of these was planned, and a variant tried now on
1993–2025 is data snooping, not a test.

Added later the same day: a slower trading rule was tried after this note was
written, by decision of the project owner, to understand the failure. It is
reported apart, as an in-sample diagnostic, in
[exploration_post_test_A.md](exploration_post_test_A.md); it changes nothing
above.

## 7. Reservations to state

- **One test, many numbers.** The main result was named before the test. The
  other nine configurations, three periods and three cost levels are secondary:
  with that many comparisons, a t-statistic near 2 is not evidence. The gross
  alpha of the ridge has a t-statistic above 2 in 11 of its 16 cells of
  1993–2025 (for example 2.08 and 2.51 against FF3 on the first day), but not
  against FF5 and momentum on the first day (1.22 and 1.54), and none of its
  net alphas is positive and significant.
- **Gross is not a costless strategy.** The gross return is the net return plus
  the costs of the month, on the path of the fund that paid them.
- **Order cap of 10 % of the ADV**: a capacity scenario with no source; the
  result at 1 % is shown next to it. The fill is not capped by the volume of
  the day itself.
- **Costs are a model.** Half spread measured in CRSP (97 % quoted), price
  impact from the formula λ√(order/ADV); no commission in the main number (the
  stress is shown). All trades happen in one day a month: a real desk would
  spread them, with less impact and more delay.
- **Concentration.** Value weights with no cap: one stock up to 35.7 % of the
  fund, 33 effective stocks. The alpha of the fund is in part the alpha of a
  few large stocks.
- **Coarse tree forecasts.** Up to 931 stocks tie with the breakpoint; in 34
  months the top 10 % equals the top 20 %. Squared-error loss instead of the
  Huber loss of Gu, Kelly and Xiu; a small grid (see section 8).
- **Training design.** The model of year Y is fitted on data up to Y − 13; the
  twelve years before Y only choose its settings.
- **Factors.** Ken French factors, not rebuilt from our data (rule D20
  postponed); q-factors not used (data not available).
- **Start of the sample.** The fund starts in cash in January 1993 (8.9 % of
  cash on average in 1993).
- **Development trials.** The order cap was chosen on the mechanics of
  1981–1992 (cash, turnover, costs), with no return looked at; listed in the
  freeze record.
- **NASDAQ.** Not a limit on 1993–2025 (closing trade prices exist from 1992),
  but it shaped the development years.
- Every figure quoted from a paper is still to be verified before the report.

## 8. Settings chosen by validation (sealed table, opened after the test)

`predictions_A_choices_sealed.parquet` was opened on 2026-11-13, after the
results above were written. One choice per return year (33 years) and model.
The grid is not extended.

Trees (grid: depth 1, 2, 3; 50, 100, 200 trees; learning rate 0.03):

| | 50 trees | 100 trees | 200 trees | Total |
|---|---|---|---|---|
| Depth 1 | 0 | 2 | 0 | 2 |
| Depth 2 | 2 | 6 | 4 | 12 |
| Depth 3 | 9 | 7 | 3 | 19 |
| Total | 11 | 15 | 7 | 33 |

- **Depth 3, the deepest allowed, is chosen in 19 years of 33**: the grid binds
  on depth. Deeper trees were not tried and will not be.
- The largest number of trees (200) is chosen in 7 years, the smallest (50) in
  11; the corner of highest capacity (depth 3, 200 trees) in 3 years (1996,
  2004, 2005). From 2012 to 2022 the choice is mostly depth 3 with 50 trees.
- Only 6 years of 33 are strictly inside the grid (depth 2, 100 trees).
- The validation loss is almost flat over the grid: the worst setting of a year
  is on average 0.48 % above the best (at most 1.29 %). The choice between
  settings rests on very small differences.

Ridge (grid: seven penalties from 0.0001 to 100): 1 in 17 years, 0.1 in 14
years, 0.01 in 2 years (2004, 2005). **No choice at an edge of the grid.** The
worst penalty of a year is on average 0.19 % above the best.

Reading (interpretation): the flat validation loss says that the tree model
extracts little more than the mean from the training data, whatever its size;
this agrees with the coarse forecasts and the absence of gross alpha. The
binding depth is a limit to state, not a reason to reopen the grid.

## 9. Provenance

| Item | Value |
|---|---|
| Freeze | `ee22d6708bdc` (tag `freeze-ee22d6708bdc`) |
| Forecasts (test), SHA-256 | `83662f11…f569546` |
| `alphas_A.csv`, SHA-256 | `87da1eb2…3641253` |
| `summary_A.csv`, SHA-256 | `4881b72e…ddf1c6db` |
| `backtest_A_test.parquet`, SHA-256 | `6c08b498…cfdd5b98` |
| Openings of the test | `resources/test_openings.jsonl` (three lines, one per step) |
| Steps | `resources/test_steps/ee22d6708bdc_A_*.attempt1.json` (one attempt each) |
| Tables and figures | `python scripts/reports/1_results_tables.py --version A` |
