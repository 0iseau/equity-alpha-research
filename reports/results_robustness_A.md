# Version A: robustness tests, for the report

**Status to keep in the report and on every table or figure taken from here:
these three tests were designed after the out-of-sample test of version A was
read, and they are evaluated on the same years (1993–2025).** They ask whether
the negative result depends on a choice of ours. They are not a new test, and
none of them replaces the main result (alpha of −5.09 % a year against FF5 and
momentum, t = −5.13).

Everything is in `RobustnessJournal.md` (design, tables R1 to R5, audits). This
note is the short version. Units: % a year; t-statistics in parentheses
(Newey-West, 6 lags); bp = basis points of the fund a month. Both audits (a
separate agent that recomputed every number, then Astra) found no wrong number.

## The answer in four lines

1. **The forecasts are not empty.** They order the stocks, strongly where small
   stocks weigh more, weakly (trees) or moderately (ridge) among large stocks.
2. **The fund does not turn that ordering into a positive alpha.** Not even at
   zero cost for the trees; for the ridge only if our costs were about three
   times too high.
3. **A smaller fund is not enough.** With USD 10 million instead of 100 million
   the alpha is still negative.
4. **So the conclusion of the project stands**, and it becomes more precise:
   the failure is in turning the forecasts into a long-only, value-weighted
   fund, not in the forecasts being worthless.

## Test 1. Do the forecasts order the stocks?

Each month the stocks are sorted into ten groups on the forecast (NYSE
breakpoints, all sizes). Paper portfolios: no cost, no order cap.

| Model | Weights | Top group | Bottom group | Top minus bottom (t) | Alpha of the top group (t) |
|---|---|---|---|---|---|
| Trees | Equal | 17.80 | −1.19 | 18.99 (5.93) | 10.96 (3.37) |
| Trees | Value | 8.41 | 5.04 | 3.37 (1.11) | −1.50 (−1.17) |
| Ridge | Equal | 19.97 | −2.26 | 22.23 (6.18) | 11.66 (5.28) |
| Ridge | Value | 15.93 | 5.90 | 10.03 (2.38) | 5.32 (2.41) |

Market excess return: 9.06 %. Figure: `figures/R_decile_returns.png`.

- On the same 396 months, top minus bottom is 15.62 points a year higher with
  equal weights than with value weights for the trees (t = 5.04), and 12.20
  points for the ridge (t = 4.60).
- The rank correlation between forecast and realised return is positive in
  about 70 % of the months (0.043 for the trees, t = 9.08; 0.047 for the ridge,
  t = 8.42), and about half as large among large stocks.

**To write.** "The forecasts order stocks; the ordering is much stronger where
small stocks weigh more. With value weights the spread of the trees is small
and imprecise."

**Not to write.** "The forecasts hold no information" (false). "The ordering is
absent among large stocks" (too strong). And do not quote the alpha of 5.32 %
of the ridge alone: it is a paper portfolio, one number among many, and the
ridge fund at zero cost has 2.10 % (t = 1.22). Why the fund does not capture
the difference was not measured.

## Test 2. How wrong would our costs have to be?

The backtest is run again with the half spread and the price impact multiplied
by k. k = 1 is the test; k = 0 is a fund that pays nothing.

| Net alpha (t) | k = 0 | k = 0.25 | k = 0.5 | k = 1 (test) | k = 2 | Break-even k |
|---|---|---|---|---|---|---|
| Trees, all sizes | −0.86 (−0.87) | −1.92 (−2.01) | −2.98 (−3.15) | −5.09 (−5.13) | −9.29 (−7.18) | none |
| Trees, large | −0.70 (−0.65) | −1.68 (−1.61) | −2.67 (−2.58) | −4.64 (−4.32) | −8.56 (−6.48) | none |
| Ridge, all sizes | 2.10 (1.22) | 0.57 (0.33) | −0.95 (−0.56) | −4.01 (−2.28) | −10.13 (−5.09) | 0.34 |
| Ridge, large | 2.42 (1.54) | 1.07 (0.69) | −0.27 (−0.17) | −2.96 (−1.85) | −8.34 (−4.52) | 0.45 |

Figure: `figures/R_cost_multiplier.png`.

**To write.** "For the main model, over 1993–2025, no cost multiplier gives a
positive estimated alpha, not even zero. The ridge breaks even at about a third
of our costs, and its alpha is not significant even at zero cost."

**Not to write.** "The strategy loses money even without costs": at zero cost
the alpha of the trees (−0.86 %, t = −0.87) is not different from zero, so it
is "no alpha", not "a loss". "No error on costs can rescue it": the test
changes one multiplier, not the structure of the costs. The break-even is an
estimate with no confidence interval. In 2009–2025 alone the break-even of the
ridge is 0.88 and 1.15, so there its result does depend on the cost level.

## Test 3. Is it a problem of size?

The backtest is run again with another capital, everything else as in the test.

| Capital | Trees: net alpha (t) | Trees: costs bp | Trees: cash % | Ridge: net alpha (t) | Ridge: costs bp | Ridge: cash % |
|---|---|---|---|---|---|---|
| USD 10 million | −4.24 (−4.27) | 28.7 | 0.0 | −3.10 (−1.66) | 50.9 | 0.3 |
| USD 100 million (test) | −5.09 (−5.13) | 35.3 | 0.7 | −4.01 (−2.28) | 51.5 | 4.7 |
| USD 1 billion | −4.83 (−5.40) | 31.1 | 12.2 | −4.46 (−3.17) | 32.2 | 31.8 |

All sizes; the large universe is in the journal. Figure: `figures/R_capital.png`.

- The cost of a dollar traded rises with size: 25.5, 32.1 and 37.3 bp for the
  trees. At USD 1 billion the fund pays less in total only because the order
  cap stops 40 % of its orders and leaves 12 % of it in cash.

**To write.** "Taking the capital from USD 100 million to 10 million is not
enough: the alpha stays negative. At USD 1 billion the fund is partly in cash."

**Not to write.** "The strategy has a capacity of X": three scenarios do not
give a maximum capacity, nor the alpha of a billion fully invested.

## Limits to state

- Done after the test, on the same years; the design was written before the
  runs, but nothing proves it (the files were not under Git yet).
- Many numbers: sixteen sorts, three periods. The t-statistics are nominal and
  no single cell confirms a strategy.
- Paper portfolios trade at the month-end close and, for top minus bottom, use
  short sales. The fund does neither.
- The ridge case is not explained: on paper its top group has an alpha, the
  fund does not capture it, and which rule accounts for it is not measured.
- Version A only. Not done: q-factors, factors rebuilt from our data, delisting
  return of −55 %, Ken French breakpoints, a second run of the forecasts.

## Files

| File | Content |
|---|---|
| `RobustnessJournal.md` | Design, tables R1 to R5 (with the large universe, sub-periods and the ten groups), readings, the two audits |
| `reports/figures/R_decile_returns.png` | Returns of the ten groups, equal and value weights |
| `reports/figures/R_cost_multiplier.png` | Net alpha against the cost multiplier |
| `reports/figures/R_capital.png` | Net alpha at three fund sizes |
| `reports/robustness/*.csv` | Every number, three periods |
