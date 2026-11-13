# Version A: exploration after the test (not out of sample)

**Status: in-sample exploration.** Everything below was run on 2026-11-13
**after** the single out-of-sample test of version A had been read (main
result: alpha of −5.09 % a year, t = −5.13; see
[results_version_A.md](results_version_A.md)). The variants were chosen knowing
that result and are evaluated on the same years, 1993–2025. They explain why
the frozen strategy fails; they are not a test and not a result of the
strategy.

Script: `scripts/exploration/1_post_test_variants.py`. It imports the frozen
monthly step unchanged and changes only what is passed to it; with the frozen
parameters it reproduces `backtest_A_test.parquet` exactly (checked month by
month). All numbers: `exploration/post_test_variants_A.csv` (three periods) and
`exploration/post_test_variants_A_monthly.csv`.

Three parameters were varied; execution (first day), order cap (10 % of the
ADV), costs and the alpha regression are those of the frozen chain.

- **Every k months**: orders are sent only every k-th month (from December
  1992); nothing is traded in between. Frozen rule: k = 1. Side effect: an
  order that is capped or not filled waits k months, so the fund holds more
  cash in the 1990s (ridge, k = 12: 80 %, 53 % and 46 % of cash in 1993, 1994
  and 1995; 9.8 % on average against 4.7 % for the frozen rule). The patience
  rule does not have this effect.
- **Patience p**: a stock held is kept while it was in the top 20 % of the
  forecasts in at least one of the last p months. Frozen rule: p = 1.
- **Weight cap**: no target weight above 5 % (value weights otherwise). Frozen
  rule: no cap.

## Trees, all sizes, 1993–2025 (% a year; t in parentheses)

Market excess return: 9.06 % a year.

| Every k | Patience p | Weight cap | Net excess return | Net minus market | Alpha FF5 + mom., gross | Alpha FF5 + mom., net | Costs bp a month | Turnover % a month | Effective stocks |
|---|---|---|---|---|---|---|---|---|---|
| **1** | **1** | **none (frozen)** | 4.76 | −4.30 (−4.47) | −0.88 (−0.90) | −5.09 (−5.13) | 35.3 | 110 | 33 |
| 1 | 1 | 5 % | 5.37 | −3.69 (−3.83) | −0.19 (−0.20) | −4.52 (−4.52) | 36.4 | 109 | 50 |
| 3 | 1 | none | 8.01 | −1.06 (−1.26) | −0.61 (−0.75) | −1.96 (−2.43) | 11.1 | 37 | 32 |
| 6 | 1 | none | 8.32 | −0.75 (−0.79) | −0.71 (−0.87) | −1.44 (−1.79) | 5.7 | 20 | 32 |
| 12 | 1 | none | 8.09 | −0.98 (−1.19) | −1.13 (−1.44) | −1.53 (−1.93) | 2.9 | 11 | 28 |
| 1 | 3 | none | 8.18 | −0.88 (−1.35) | −0.35 (−0.61) | −1.36 (−2.39) | 8.5 | 33 | 63 |
| 1 | 6 | none | 8.36 | −0.71 (−1.44) | −0.62 (−1.47) | −1.03 (−2.38) | 3.5 | 15 | 92 |
| 1 | 12 | none | 8.74 | −0.33 (−0.82) | −0.28 (−0.97) | −0.47 (−1.49) | 1.6 | 6 | 128 |
| 3 | 3 | none | 8.13 | −0.93 (−1.42) | −0.94 (−1.44) | −1.65 (−2.56) | 5.8 | 22 | 44 |
| 3 | 3 | 5 % | 8.00 | −1.06 (−1.51) | −0.93 (−1.44) | −1.67 (−2.61) | 6.1 | 22 | 60 |

## Ridge, all sizes, 1993–2025

| Every k | Patience p | Weight cap | Net excess return | Net minus market | Alpha FF5 + mom., gross | Alpha FF5 + mom., net | Costs bp a month | Turnover % a month | Effective stocks |
|---|---|---|---|---|---|---|---|---|---|
| **1** | **1** | **none (frozen)** | 6.29 | −2.78 (−1.53) | 2.09 (1.22) | −4.01 (−2.28) | 51.5 | 130 | 28 |
| 1 | 1 | 5 % | 5.35 | −3.72 (−2.16) | 0.69 (0.51) | −5.38 (−3.84) | 51.3 | 124 | 57 |
| 3 | 1 | none | 8.24 | −0.82 (−0.52) | 0.55 (0.34) | −1.51 (−0.96) | 17.0 | 47 | 21 |
| 6 | 1 | none | 7.72 | −1.34 (−0.84) | −0.64 (−0.48) | −1.71 (−1.30) | 8.4 | 24 | 21 |
| 12 | 1 | none | 10.37 | 1.30 (0.89) | 2.36 (1.60) | 1.75 (1.23) | 4.2 | 11 | 20 |
| 1 | 3 | none | 8.03 | −1.03 (−0.78) | 0.05 (0.04) | −2.01 (−1.65) | 17.5 | 50 | 45 |
| 1 | 6 | none | 8.47 | −0.59 (−0.57) | −0.31 (−0.36) | −1.18 (−1.34) | 7.4 | 24 | 67 |
| 1 | 12 | none | 8.67 | −0.40 (−0.46) | −0.61 (−1.00) | −0.99 (−1.64) | 3.3 | 10 | 102 |

The large universe gives the same picture (CSV file).

## What the exploration shows

Measured:

- Trading less brings the fund back close to the market. With a patience of 12
  months the tree portfolio is 0.33 point a year behind the market (t = −0.82),
  against 4.30 points for the frozen rule; its costs fall from 35 to 1.6 bp a
  month and its turnover from 110 % to 6 % a month.
- No variant has a positive alpha that is significant. The net alpha against
  FF5 and momentum stays between −0.5 % and −2 % a year for the trees once
  trading is slowed (−4.5 % with the weight cap alone), and several values
  remain significantly negative.
- The gross alpha does not rise when trading slows: it stays between −1.1 %
  and −0.2 % for the trees.
- The cap of 5 % on weights changes little at any trading frequency; alone, it
  makes the ridge worse.
- The only positive net alphas are the ridge traded once a year (4 cells of
  52; the largest is 1.75 %, t = 1.23; 2.13 %, t = 1.38, on 1998–2025, once
  the cash of the first years is gone). The same rule at six months gives −1.71 %: the result is not
  monotonic in the frequency, and it depends on the month in which the year
  starts (December here).

Interpretation:

- The frozen strategy loses to the market because of what it pays to trade, as
  the main report says. Removing most of the trading removes most of the loss.
- It does so by making the fund more passive: fewer changes, more names (128
  effective stocks instead of 33), a return close to the market's. The fund
  gets back to the market by ceasing to act on the forecasts, not by acting on
  them better. There is still no alpha.
- The ridge traded once a year is not evidence: four cells of a grid of 52, none
  significant, chosen after the test, with a neighbour of the opposite sign.

How this may be used in the report: as a diagnostic section placed after the
main result ("why it fails, and what turnover would have to be"), with the
statement that it was done after the test. It cannot replace the main result
and it cannot be presented as a rule fixed in advance: the freeze record, its
Git tag and the log of the test openings date the order of events.
