# Version B: results of the out-of-sample test, 1993–2025

Status: single test, run once on 2026-11-13 under freeze `ee22d6708bdc`, after
the test of version A and through the same frozen scripts (runs: candidates
`feb21459bbc2`, backtest `ca7630c772f5`, alphas `db7e90ae9d97`). No step was
retried. No rule was changed between A and B. Full grid of numbers:
[tables_B.md](tables_B.md). Figures: `figures/B_*.png`. Results of version A:
[results_version_A.md](results_version_A.md).

**What version B is.** Version A forecasts returns from the 59 market
characteristics (prices, returns, volume). Version B uses those 59 **and 135
accounting characteristics** (194 in all: value, profitability, investment,
leverage, growth). Everything else is identical: same models, same portfolio
rule, same costs, same test. By the rules fixed before the test (D23), **A is
the main conclusion and B is a complement**: B answers one question, "do the
accounting characteristics change the answer?".

Reading guide: sections 1 to 6 are **measured** (numbers straight from
`alphas_B.csv`, `summary_B.csv` and the monthly record of the backtest).
Section 7 is **interpretation**. Section 8 lists the reservations to state.

Units: returns and alphas in % a year (monthly value × 12); t-statistics in
parentheses, Newey-West with 6 lags; costs in basis points (bp) of the fund a
month; turnover is the sum of the absolute trades of a month (purchases plus
sales) in % of the fund.

Words used below:

- **ADV**: average daily dollar volume of a stock. An order cannot exceed 10 %
  of it (1 % in the stress test).
- **Top 10 %**: the stocks whose forecast is at or above the 90th percentile of
  the forecasts of NYSE stocks. All stocks are judged against that NYSE
  threshold, so the group holds more than 10 % of the names.
- **Stocks to hold / held**: the stocks the rule wants in the fund, and those
  really in it after the trades. More are held than wanted because a sale that
  is capped or cannot be filled leaves the position in the book.
- **Effective number of stocks**: 1 over the sum of the squared weights. A fund
  of 1,000 names worth "30 effective stocks" is as concentrated as 30 stocks of
  equal weight.
- **Gross**: the net return plus the trading costs of the month, on the
  positions really held. It is not the return of a fund that pays no cost.
- **Main configuration**: boosted trees, all sizes, first-day execution, cap of
  10 %. The main *result* of the project is this configuration in version A.

## 1. The answer in four lines

**Adding the accounting characteristics does not change the answer.** With
version B, boosted trees, all sizes, execution on the first trading day, order
cap of 10 % of the average daily dollar volume (ADV), net of half spread and
price impact, before commissions, 1993–2025: **the alpha against the five Fama-French factors and
momentum is −5.54 % a year (t = −4.52)**. Version A gave −5.09 % (t = −5.13).

- Before trading costs the alpha is −1.17 % a year (t = −1.01): not different
  from zero.
- Trading costs take 4.40 % a year (21.8 bp of half spread and 14.9 bp of price
  impact a month).
- With the commission stress (6 cents a share until 2004, 4 cents after):
  −7.55 % a year (t = −5.96).
- Conditional diagnostic (loadings allowed to move with the share of the fund
  invested): −5.03 % a year (t = −4.47). Same conclusion.

## 2. Version A against version B

Alpha against FF5 + momentum, 1993–2025, % a year (t):

| Configuration | A, gross | B, gross | A, net | B, net |
|---|---|---|---|---|
| **Trees, all sizes, first day (main configuration)** | −0.88 (−0.90) | −1.17 (−1.01) | **−5.09 (−5.13)** | **−5.54 (−4.52)** |
| Trees, large universe, first day | −0.71 (−0.67) | −0.32 (−0.30) | −4.64 (−4.32) | −4.29 (−3.83) |
| Ridge, all sizes, first day | 2.09 (1.22) | 1.38 (0.96) | −4.01 (−2.28) | −3.94 (−2.77) |
| Ridge, large universe, first day | 2.41 (1.54) | 1.32 (1.07) | −2.96 (−1.85) | −3.41 (−2.86) |
| Trees, all sizes, close to close | −1.11 (−0.97) | −0.50 (−0.37) | −5.48 (−4.58) | −4.98 (−3.62) |
| Trees, large universe, close to close | −1.05 (−0.83) | 0.01 (0.01) | −5.07 (−3.91) | −4.03 (−3.29) |
| Ridge, all sizes, close to close | 3.72 (1.82) | 1.83 (1.24) | −2.50 (−1.24) | −3.53 (−2.50) |
| Ridge, large universe, close to close | 3.57 (2.06) | 1.76 (1.29) | −1.88 (−1.11) | −3.00 (−2.40) |
| Trees, all sizes, first day, cap 1 % | −1.11 (−1.18) | −1.45 (−1.42) | −3.16 (−3.55) | −3.37 (−3.37) |
| Trees, large universe, first day, cap 1 % | −0.57 (−0.59) | −0.78 (−0.79) | −2.56 (−2.83) | −2.69 (−2.82) |

- **In all ten configurations the net alpha of B is negative, and significant
  (|t| of 2.40 or more), as in A for the trees.** For the ridge, B is more
  significantly negative than A: the |t| is larger in all four cells (for
  example −3.00 %, t = −2.40, against −1.88 %, t = −1.11).
- **B is not better than A before costs.** For the trees the gross alphas are
  within about one point of each other (0.2 to 1.1) and none differs from zero. For the ridge the
  gross alpha of B is lower than that of A in all four cells.
- Direct comparison of the monthly net returns, B minus A, same configuration
  (this comparison and the correlations below are descriptive: they are not
  among the tests fixed at the freeze): trees, all sizes
  −0.52 % a year (t = −0.67); trees, large universe +0.24 % (t = 0.33); ridge,
  all sizes +0.35 % (t = 0.27); ridge, large universe −0.18 % (t = −0.15).
  **No difference between the two versions is distinguishable from zero.**
- The two funds are nearly the same fund: the correlation of the monthly net
  returns of A and B is 0.94 to 0.96 for the six tree configurations and 0.91
  to 0.93 for the four ridge configurations.

## 3. The main configuration of version B in detail

| | 1993–2025 | 1993–2008 | 2009–2025 |
|---|---|---|---|
| Months | 396 | 192 | 204 |
| Excess return, gross | 8.64 | 5.64 | 11.46 |
| Excess return, net (t) | 4.24 (1.49) | −2.39 (−0.56) | 10.48 (3.36) |
| Volatility, net | 15.6 | 15.6 | 15.4 |
| Sharpe ratio, net | 0.27 | −0.15 | 0.68 |
| Market excess return | 9.06 | 3.96 | 13.87 |
| Market Sharpe ratio | 0.60 | 0.26 | 0.90 |
| Net return minus market (t) | −4.82 (−3.88) | −6.34 (−2.88) | −3.39 (−2.94) |
| Worst month, net | −17.7 | −17.7 | −13.3 |
| **Alpha, net: CAPM** | −4.29 (−3.49) | −6.06 (−2.83) | −2.66 (−2.21) |
| **Alpha, net: FF3** | −4.41 (−3.48) | −6.62 (−2.88) | −2.84 (−2.27) |
| **Alpha, net: FF5** | −4.73 (−3.49) | −6.99 (−2.71) | −3.01 (−2.50) |
| **Alpha, net: FF5 + momentum** | **−5.54 (−4.52)** | −8.03 (−3.35) | −3.24 (−3.04) |
| Alpha, gross: CAPM | 0.14 (0.12) | 1.95 (0.93) | −1.68 (−1.44) |
| Alpha, gross: FF3 | 0.00 (0.00) | 1.37 (0.62) | −1.85 (−1.52) |
| Alpha, gross: FF5 | −0.33 (−0.25) | 1.01 (0.41) | −2.03 (−1.74) |
| Alpha, gross: FF5 + momentum | −1.17 (−1.01) | −0.02 (−0.01) | −2.25 (−2.14) |
| Alpha, net + commission stress: FF5 + momentum | −7.55 (−5.96) | −11.07 (−4.64) | −4.31 (−3.94) |
| Half spread, bp a month | 21.8 | 42.6 | 2.2 |
| Price impact, bp a month | 14.9 | 24.3 | 6.0 |
| Commission stress, bp a month | 16.6 | 24.8 | 9.0 |
| Turnover wanted / filled, % a month | 114 / 110 | 145 / 137 | 85 / 84 |
| Orders capped / not filled, % of orders | 15.8 / 5.9 | 25.6 / 8.9 | 2.4 / 1.9 |
| Cash after the trades, mean % | 1.0 | 2.0 | 0.00 |
| Stocks to hold / held, median | 605 / 958 | 714 / 1,236 | 560 / 825 |
| Effective number of stocks, median | 30 | 28 | 31 |
| Largest weight, maximum % of the fund | 43.4 | 34.3 | 43.4 |
| Largest weight, median % of the invested part | 11.4 | 11.6 | 11.4 |

Loadings of the net return on FF5 + momentum, 1993–2025: market 0.99, SMB
−0.01, HML 0.04, RMW 0.00, CMA 0.08, momentum 0.11; R² = 0.86. The fund is the
market with a small momentum tilt.

Value of 1 invested at the end of 1992, at the end of 2025: market 29.7; fund
after costs 6.0; gross index 25.4 (the gross index adds back the costs of each
month on the path of the fund that paid them: it is not a fund that could have
existed). Figure `B_cumulative_value.png`.

Costs through time (figure `B_costs.png`), main configuration:

| Years | Half spread bp | Impact bp | Turnover filled % | Cash % | Stocks held | Effective stocks |
|---|---|---|---|---|---|---|
| 1993–1996 | 63.8 | 32.2 | 112 | 7.0 | 1,657 | 34 |
| 1997–2000 | 64.0 | 25.8 | 144 | 1.0 | 1,406 | 24 |
| 2001–2004 | 33.1 | 21.5 | 144 | 0.1 | 967 | 23 |
| 2005–2008 | 9.6 | 17.7 | 150 | 0.0 | 910 | 34 |
| 2009–2012 | 4.7 | 11.8 | 114 | 0.0 | 896 | 32 |
| 2013–2016 | 1.3 | 5.0 | 74 | 0.0 | 734 | 40 |
| 2017–2020 | 1.1 | 3.4 | 64 | 0.0 | 692 | 26 |
| 2021–2025 | 1.8 | 4.3 | 85 | 0.0 | 1,052 | 30 |

Other measured facts on the main configuration:

- The largest position is above 10 % of the fund in 253 months of 396, above
  20 % in 27 months, above 30 % in 8 months; the smallest effective number of
  stocks in a month is 4.4.
- 98.0 % of the amounts traded pay a quoted spread, 2.0 % a high-low estimate.
- Write-offs for unknown returns (rule D16) sum to 0.34 % of the fund over the
  33 years: immaterial.
- Cash is 12.6 % on average in 1993 (the fund starts all in cash) and zero in
  2025 (figure `B_cash_share.png`).
- Candidates: the top 10 % holds 494 stocks in the median month (242 to 2,120).
  The tree forecasts are coarse: up to 947 stocks tie with the breakpoint; in
  27 months of 396 the top 10 % equals the top 20 % (the 10 % / 20 % buffer
  does nothing in those months), and in 33 months more than 15 % of the NYSE
  stocks are in the "top 10 %" (41 % in the worst month). The ridge has no
  ties.

## 4. The ten configurations of version B, 1993–2025

Alpha against FF5 + momentum, % a year (t):

| Configuration | Gross alpha | Net alpha | Net alpha + commission stress | Half spread + impact, bp a month | Turnover filled, % a month | Mean cash, % | Net excess return | Sharpe | Net minus market (t) |
|---|---|---|---|---|---|---|---|---|---|
| **Trees, all sizes, first day (main configuration)** | −1.17 (−1.01) | **−5.54 (−4.52)** | −7.55 (−5.96) | 36.7 | 110 | 1.0 | 4.24 | 0.27 | −4.82 (−3.88) |
| Trees, large universe, first day | −0.32 (−0.30) | −4.29 (−3.83) | −5.97 (−5.15) | 33.4 | 110 | 0.4 | 5.54 | 0.35 | −3.52 (−3.00) |
| Ridge, all sizes, first day | 1.38 (0.96) | −3.94 (−2.77) | −6.89 (−4.88) | 45.0 | 102 | 4.4 | 6.64 | 0.36 | −2.43 (−1.28) |
| Ridge, large universe, first day | 1.32 (1.07) | −3.41 (−2.86) | −5.63 (−4.72) | 40.1 | 109 | 2.2 | 7.41 | 0.41 | −1.65 (−1.01) |
| Trees, all sizes, close to close | −0.50 (−0.37) | −4.98 (−3.62) | −7.04 (−5.00) | 37.6 | 110 | 1.2 | 4.72 | 0.30 | −4.35 (−3.24) |
| Trees, large universe, close to close | 0.01 (0.01) | −4.03 (−3.29) | −5.73 (−4.57) | 34.0 | 110 | 0.5 | 5.80 | 0.37 | −3.26 (−2.67) |
| Ridge, all sizes, close to close | 1.83 (1.24) | −3.53 (−2.50) | −6.51 (−4.62) | 45.4 | 101 | 4.6 | 7.10 | 0.38 | −1.97 (−1.03) |
| Ridge, large universe, close to close | 1.76 (1.29) | −3.00 (−2.40) | −5.24 (−4.19) | 40.2 | 108 | 2.4 | 7.78 | 0.44 | −1.28 (−0.75) |
| Trees, all sizes, first day, cap 1 % | −1.45 (−1.42) | −3.37 (−3.37) | −4.68 (−4.62) | 16.3 | 81 | 15.0 | 5.41 | 0.38 | −3.66 (−3.44) |
| Trees, large universe, first day, cap 1 % | −0.78 (−0.79) | −2.69 (−2.82) | −3.87 (−3.99) | 16.2 | 83 | 12.8 | 6.20 | 0.43 | −2.86 (−2.76) |

Market: excess return 9.06 % a year, Sharpe 0.60. **Against FF5 + momentum no
configuration has a positive net alpha, and none beats the market after
costs** (net return minus
market between −1.28 % and −4.82 % a year; the gap is not significant for the
four ridge configurations).

## 5. Sub-periods, alpha against FF5 + momentum

| Configuration | Net, 1993–2008 | Net, 2009–2025 | Gross, 1993–2008 | Gross, 2009–2025 |
|---|---|---|---|---|
| **Trees, all sizes, first day (main configuration)** | −8.03 (−3.35) | −3.24 (−3.04) | −0.02 (−0.01) | −2.25 (−2.14) |
| Trees, large universe, first day | −6.51 (−3.04) | −2.35 (−2.31) | 0.75 (0.37) | −1.46 (−1.44) |
| Ridge, all sizes, first day | −5.61 (−2.49) | −1.95 (−1.27) | 2.84 (1.23) | 0.37 (0.24) |
| Ridge, large universe, first day | −4.06 (−2.21) | −2.35 (−1.63) | 4.06 (2.15) | −0.81 (−0.56) |
| Trees, all sizes, close to close | −6.93 (−2.56) | −3.16 (−2.81) | 1.26 (0.49) | −2.13 (−1.92) |
| Trees, large universe, close to close | −5.85 (−2.45) | −2.32 (−2.01) | 1.53 (0.68) | −1.39 (−1.22) |
| Ridge, all sizes, close to close | −4.41 (−2.01) | −2.24 (−1.41) | 4.04 (1.73) | 0.17 (0.11) |
| Ridge, large universe, close to close | −2.90 (−1.58) | −2.46 (−1.62) | 5.21 (2.58) | −0.86 (−0.57) |
| Trees, all sizes, first day, cap 1 % | −3.79 (−2.11) | −2.97 (−2.90) | −0.76 (−0.42) | −2.12 (−2.08) |
| Trees, large universe, first day, cap 1 % | −3.29 (−1.96) | −2.23 (−2.25) | −0.24 (−0.14) | −1.41 (−1.43) |

Against FF5 + momentum no net alpha is positive in either sub-period, for any
configuration; the same holds against FF3 and FF5. Against the CAPM one cell of
the 30 is positive and not significant (ridge, large universe, close to close,
1993–2008: 0.84 %, t = 0.32; see `tables_B.md`).

## 6. The comparisons fixed at the freeze, one by one

1. **Version A against version B.** Section 2: no difference distinguishable
   from zero; B is not better before costs.
2. **Two universes.** Removing the stocks below the NYSE 20th percentile:
   net alpha −4.29 % (t = −3.83) against −5.54 %; costs 33.4 against 36.7 bp a
   month.
3. **Two models.** The ridge has a positive gross alpha that is not
   significant (1.38 %, t = 0.96; large universe 1.32 %, t = 1.07) and pays
   more (45.0 bp a month). Net: −3.94 % (t = −2.77). The two models agree on
   the sign of the net result.
4. **Close-to-close execution.** Trees: −4.98 % (t = −3.62) against −5.54 % on
   the first day. Ridge: −3.53 % (t = −2.50) against −3.94 %.
5. **Order cap of 1 %.** Net alpha −3.37 % (t = −3.37). Less negative because
   the fund trades less (81 % a month, 16.3 bp of costs) and holds 15.0 % of
   cash on average.
6. **Commission stress.** Adds 16.6 bp a month (2.00 % a year) for the main
   configuration: −7.55 % (t = −5.96).
7. **Sub-periods.** The net loss is larger in 1993–2008 (−8.03 %), when costs
   are 66.9 bp a month, than in 2009–2025 (−3.24 %), when they are 8.2 bp. In
   2009–2025 the alpha of the trees is negative even gross of costs (−2.25 %,
   t = −2.14).
8. **Conditional diagnostic.** −5.03 % (t = −4.47): same conclusion.

## 7. Reading for the investment committee (interpretation)

**Do the accounting characteristics rescue the strategy? No.** With 194
characteristics instead of 59, the fund earns about the same return as before
(4.2 % against 4.8 % a year above the risk-free rate, a gap that is not
significant), pays about the same costs (36.7 against 35.3 bp a month), and
loses about the same 5 % a year to its factor benchmark. The
conclusion of version A stands, and it does not depend on which set of
characteristics is used.

What the numbers suggest, in order of importance:

1. **The same mechanism as in version A.** The fund trades about 110 % of its
   value every month, pays about 37 bp a month, and that cost (4.4 % a year)
   is almost the whole distance between the gross alpha (−1.2 %) and the net
   alpha (−5.5 %). Before costs there is nothing to protect: the return is the
   market's (beta 0.99, R² 0.86).
2. **Accounting characteristics move slowly, but the tree fund does not trade
   less.** One could expect signals whose accounting inputs change once a year
   to slow the portfolio down. They do not: the turnover of the trees is 110 %
   a month in B as in A (measured). Why is not measured: the forecasts may
   still be driven by the fast market signals, or the ranking near the
   breakpoint may be unstable enough to keep the fund trading. One measured
   fact points to the first reading: in 36 formation months between December
   2014 and November 2024, the threshold and the number of stocks of the top
   10 % of the trees are identical in A and in B, and the settings chosen by
   validation are the same in those years; in those months the trees of B
   appear to make no use of the accounting characteristics (the forecasts
   themselves were not compared). The ridge behaves differently: its turnover
   is lower in B (102 % against 130 % in A), its costs too (45.0 against
   51.5 bp), and so is its gross alpha (1.4 % against 2.1 %): it pays less and
   earns less.
3. **Value weights decide the result, again.** The book holds about a thousand
   names but is worth 30 stocks of equal weight, and one stock weighs up to
   43 % of the fund (measured). Whatever the 135 accounting characteristics
   add for small companies, the return of the fund is then largely that of a
   few very large stocks (plausible; the contribution of each stock to the
   result is not measured).
4. **The reservation on restated accounts does not rescue B.** Version B uses
   Compustat accounts in today's state, which can contain later corrections
   (rule D12). The usual presumption is that restated data flatter a backtest;
   under it, a version B built on the accounts as first published would be no
   better than what is shown, and B shows no gain to explain away. Neither the
   sign nor the size of this effect is measured here: if restatements hurt B
   instead, nothing could be concluded from this argument.
5. **Coarse tree forecasts, as in A.** The tree forecasts take few distinct
   values in some months: in the worst month 41 % of the NYSE stocks are tied
   into the "top 10 %" (the same month, January 2024, and the same figure as in
   A), and the 10 % / 20 % buffer vanishes in 27 months of 396 (34 in A). In
   those months the rule does not separate its candidates. B is not coarser
   than A: its forecasts take more distinct values in the median month (1,654
   against 1,326).

What this result is: the complement confirms the negative result of A. Two
sets of characteristics, two models, two universes, two executions, two order
caps: against FF5 + momentum over 1993–2025, the net alpha is negative in all
ten configurations of both versions, and for the main configuration it is
significant at any usual level in both (t = −5.13 and −4.52). Over all periods
and factor models, 13 of the 120 net cells of A and 1 of the 120 of B are
positive (all for the ridge, none significant); with the commission stress all
240 are negative.

What it is not: evidence that accounting information is useless for stock
selection. The test covers one use of it (a long-only, value-weighted, monthly
fund of USD 100 million), and says nothing about equal weights, a long-short
portfolio, or a slower rebalancing. None of these was planned; a variant tried
now on 1993–2025 is exploration, not a test.

## 8. Reservations to state

- **B is a complement.** The conclusion of the project is read on version A
  (D23, fixed before any result). B was run after A was seen, through the same
  frozen scripts; no rule was reopened. Its forecast file was finished after
  the freeze (15:38 UTC, the freeze being at 14:15), by the frozen prediction
  script and on the inputs, settings and calendar recorded in the freeze; its
  hash is therefore not in the freeze record, only in the log of the openings
  of the test.
- **Many numbers, one test.** Ten configurations, three periods, three cost
  levels, four factor models, two versions. A t-statistic near 2 in a secondary
  cell is not evidence. In B, against FF5 + momentum, the gross alpha of the
  ridge in the large universe has a t-statistic above 2 in 1993–2008 (4.06 %,
  t = 2.15 on the first day; 5.21 %, t = 2.58 close to close) and is negative
  in 2009–2025; against the CAPM and FF3 other gross cells of the ridge in
  1993–2008 are above 2 as well (up to t = 3.15). No net alpha against FF5 +
  momentum is positive, and the only positive net cell of B (section 5) is not
  significant.
- **Restated accounts.** Compustat in today's state (D12): version B only. See
  point 4 of section 7.
- **Gross is not a costless strategy.** The gross return is the net return plus
  the costs of the month, on the path of the fund that paid them.
- **Order cap of 10 % of the ADV**: a capacity scenario with no source; the
  result at 1 % is shown next to it. The fill is not capped by the volume of
  the day itself.
- **Costs are a model.** Half spread measured in CRSP (98 % quoted), price
  impact from the formula λ√(order/ADV); no commission in the main number (the
  stress is shown). All trades happen in one day a month.
- **Concentration.** Value weights with no cap: one stock up to 43.4 % of the
  fund, 30 effective stocks (4.4 in the worst month).
- **Coarse tree forecasts** (section 3) and a small grid (section 9).
  Squared-error loss instead of the Huber loss of Gu, Kelly and Xiu.
- **Training design.** The model of year Y is fitted on data up to Y − 13; the
  twelve years before Y only choose its settings.
- **Factors.** Ken French factors, not rebuilt from our data (rule D20
  postponed); q-factors not used (data not available).
- **Reproducibility.** The forecasts of B were computed once (141 minutes); a
  second run to confirm identical files was not made, for A or for B.
- Every figure quoted from a paper is still to be verified before the report.

## 9. Settings chosen by validation (sealed table, opened after the test)

`predictions_B_choices_sealed.parquet` was opened on 2026-11-13, after the
results above were written. One choice per return year (33 years) and model.

Trees (grid: depth 1, 2, 3; 50, 100, 200 trees; learning rate 0.03):

| | 50 trees | 100 trees | 200 trees | Total |
|---|---|---|---|---|
| Depth 1 | 0 | 2 | 0 | 2 |
| Depth 2 | 1 | 3 | 5 | 9 |
| Depth 3 | 12 | 6 | 4 | 22 |
| Total | 13 | 11 | 9 | 33 |

- **Depth 3, the deepest allowed, is chosen in 22 years of 33**: the grid binds
  on depth, as in A (19 years). Deeper trees were not tried and will not be.
- The largest number of trees (200) is chosen in 9 years, the smallest (50) in
  13. Only 3 years of 33 are strictly inside the grid (depth 2, 100 trees).
- The validation loss is almost flat over the grid: the worst setting of a year
  is on average 0.48 % above the best (at most 1.12 %).

Ridge (grid: seven penalties from 0.0001 to 100): 1 in 17 years, 0.1 in 5
years, 0.01 in 7 years, 0.001 in 3 years, **0.0001, the smallest of the grid,
in 1 year**. The worst penalty of a year is on average 0.29 % above the best
(at most 0.58 %). With 388 inputs the ridge of B chooses smaller penalties
than that of A, and reaches the edge of its grid once.

## 10. Provenance

| Item | Value |
|---|---|
| Freeze | `ee22d6708bdc` (tag `freeze-ee22d6708bdc`) |
| Forecasts of B (run `d78f1bbbbbef`), test file, SHA-256 | `5d1275dd…` |
| `alphas_B.csv`, SHA-256 | `e22bc01d…` |
| `summary_B.csv`, SHA-256 | `9f9d9621…` |
| `backtest_B_test.parquet`, SHA-256 | `1b0a8c3b…` |
| Openings of the test | `resources/test_openings.jsonl` (six lines: three for A, three for B) |
| Steps | `resources/test_steps/ee22d6708bdc_B_*.attempt1.json` (one attempt each) |
| Tables and figures | `python scripts/reports/1_results_tables.py --version B` |
