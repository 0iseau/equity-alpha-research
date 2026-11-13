# Robustness journal: version A, after the out-of-sample test

Separate from `ProjectJournal.md`. It records the robustness tests decided by
Danny on 2026-11-13, in the order of the work: design first, then results,
then audits.

## 0. Status of everything in this file

- The out-of-sample test of version A was run once and read before any of this
  (main journal, section 8.10: alpha of −5.09 % a year against FF5 and
  momentum, t = −5.13), and so was the exploration of slower trading rules
  (main journal, section 8.11). **These tests are run with those results
  known, on the same years.** The main journal is `ProjectJournal_with_B.md`
  (`ProjectJournal.md` is an identical copy kept under the name Git tracks).
  Everything about robustness is in this file only.
- Section 1 was written before the first run, but nothing proves it: the
  files were not under Git at the time. Part of the outcome could also be
  foreseen from numbers already read: the break-even of test 2 is close to
  gross alpha / (gross alpha − net alpha) of the test (0.343 and 0.449 against
  0.344 and 0.450 measured). The reading rules of section 1 are therefore a
  discipline of writing, not a pre-registration. They ask whether the negative conclusion depends on a choice of
  ours; none of them can become a new main result.
- The frozen chain is not edited. The tests import the frozen monthly step
  (`scripts/backtest/2_backtest.py`) unchanged and change only what is passed
  to it. With the frozen parameters each test must reproduce the test result
  month by month, or it stops.
- Script: `scripts/robustness/1_robustness_tests.py`. Outputs:
  `reports/robustness/`.
- Units: returns and alphas in % a year (monthly value × 12); t-statistics in
  parentheses, Newey-West with 6 lags, as in the test; costs in basis points
  of the fund a month.

## 1. Design (written before any of the three tests was run)

### Test 1. Do the forecasts order the stocks? (decile sorts, no costs)

**Question.** The test measures a fund: top decile, value weights, costs. It
does not say whether the forecasts themselves hold information. Two readings of
the failure are possible, and they call for different conclusions:
(a) the forecasts order stocks, but mostly small ones, so a value-weighted
long-only fund cannot use them; (b) the forecasts do not order stocks at all.

**Method.**

- Sample: every eligible stock-month of `predictions_A_test.parquet` (formation
  months 1992-12 to 2025-11, read against the hash of the freeze), with the
  excess return of the following month (`ret_exc_lead1`, the target of the
  models). A stock-month with no next-month return is left out of the sort and
  counted.
- Each month the stocks are sorted into ten groups on the forecast. Two sets
  of breakpoints: the eligible NYSE stocks (the rule of the project, discrete
  quantile of the cleaning) and all eligible stocks (the usual choice of the
  literature on machine-learning forecasts). Group = 1 + number of
  breakpoints at or below the forecast, so that the top group is exactly the
  "top 10 %" of the test.
- Two universes (all sizes; at or above the NYSE 20th percentile of size), two
  models (trees, ridge), two weightings (equal; market equity of month t).
- Reported: mean excess return of each group; top minus bottom, its
  t-statistic and its alpha against FF5 and momentum; the alpha of the top
  group alone; three periods. Tree forecasts tie: the months where a group is
  empty are counted, and top minus bottom uses the months where both exist.
- A measure that does not depend on groups: the rank correlation between
  forecast and realised return across stocks, month by month (mean and
  t-statistic), in both universes.

**What it is not.** These are paper portfolios: no cost, no order cap, every
stock traded at the month-end close. Top minus bottom needs short sales.

**How it will be read (fixed here).** A top-minus-bottom return that is
positive and significant with equal weights, and absent with value weights or
in the large universe, supports reading (a). No spread anywhere supports
reading (b). A spread with value weights in the large universe would say that
the construction of the fund, not the forecasts, loses the result.

### Test 2. How wrong would our costs have to be? (cost multiplier)

**Question.** The costs are a model (half spread measured in CRSP, price impact
from a formula). At what fraction of them would the net alpha be zero?

**Method.** The backtest is run again with the half spread and the impact
coefficient of every trade multiplied by k = 0, 0.25, 0.5, 1 and 2, everything
else frozen (first-day execution, order cap of 10 %, USD 100 million). k = 1
must reproduce the test. k = 0 is a fund that really pays nothing, which the
"gross" return of the test is not (that one adds back the costs paid on the
path of the fund that paid them). Four configurations: two models, two
universes. Reported: net excess return, return minus market, alpha against FF5
and momentum, with t-statistics; the break-even k, by linear interpolation
between the two values of k where the alpha changes sign, if it does.

**How it will be read.** If the alpha is negative at k = 0, no error on costs
can rescue the strategy. If the break-even k is far below 1, the conclusion
holds unless our costs are several times too high.

### Test 3. Is it a problem of size? (capital of the fund)

**Question.** The fund has USD 100 million. Price impact and the order cap
depend on the size of the orders; the spread does not. Would a smaller fund
have an alpha, and how fast does a larger one lose?

**Method.** The backtest is run again with a capital of USD 10 million, 100
million (must reproduce the test) and 1 billion, everything else frozen. Same
four configurations and the same statistics, plus costs, turnover filled, cash
and the share of orders capped.

**How it will be read.** If the alpha is still negative at USD 10 million, the
failure is not a capacity problem. The difference between 10 million and 1
billion gives the capacity curve to show to the committee.

## 2. Results (run on 2026-11-13; all numbers for 1993–2025 unless stated)

Files: `reports/robustness/decile_spreads_A.csv`, `decile_sorts_A.csv`,
`decile_sorts_A_monthly.csv`, `rank_ic_A.csv`, `cost_multiplier_A.csv`,
`cost_break_even_A.csv`, `capital_A.csv` (each with the three periods).
Control: with k = 1 and USD 100 million the script reproduces the frozen
backtest month by month for the four configurations; the 90th percentile of
test 1 equals the one of the test in every month.

### Test 1. The forecasts do order the stocks, mostly the small ones

1,918,624 stock-months; 119 have no next-month return and are left out. No
month has an empty top or bottom group.

Table R1. Top group minus bottom group, paper portfolios without costs (computed after the test, on the same years).

| Model | Universe | Breakpoints | Weights | Top, excess return | Bottom | Top minus bottom (t) | Alpha of top minus bottom (t) | Alpha of the top group (t) |
|---|---|---|---|---|---|---|---|---|
| Trees | All sizes | NYSE | Equal | 17.80 | −1.19 | 18.99 (5.93) | 17.71 (5.86) | 10.96 (3.37) |
| Trees | All sizes | NYSE | Value | 8.41 | 5.04 | 3.37 (1.11) | 0.51 (0.21) | −1.50 (−1.17) |
| Trees | All sizes | All stocks | Equal | 18.60 | −6.39 | 24.99 (6.08) | 23.14 (6.81) | 11.89 (3.63) |
| Trees | All sizes | All stocks | Value | 8.83 | 2.98 | 5.85 (1.44) | 2.20 (0.75) | −0.93 (−0.70) |
| Trees | Large | NYSE | Equal | 9.82 | 4.92 | 4.91 (1.41) | 1.58 (0.80) | −0.84 (−0.98) |
| Trees | Large | NYSE | Value | 8.16 | 6.28 | 1.88 (0.63) | −0.70 (−0.30) | −1.98 (−1.44) |
| Ridge | All sizes | NYSE | Equal | 19.97 | −2.26 | 22.23 (6.18) | 19.43 (6.75) | 11.66 (5.28) |
| Ridge | All sizes | NYSE | Value | 15.93 | 5.90 | 10.03 (2.38) | 5.84 (1.76) | 5.32 (2.41) |
| Ridge | All sizes | All stocks | Equal | 21.68 | −3.22 | 24.89 (6.25) | 22.04 (6.98) | 13.55 (5.67) |
| Ridge | All sizes | All stocks | Value | 16.45 | 4.47 | 11.98 (2.66) | 6.95 (2.19) | 5.40 (2.56) |
| Ridge | Large | NYSE | Equal | 14.80 | 3.82 | 10.98 (2.60) | 5.45 (2.05) | 2.79 (1.83) |
| Ridge | Large | NYSE | Value | 15.16 | 5.84 | 9.32 (2.22) | 4.63 (1.47) | 4.08 (2.16) |

(Large universe with all-stock breakpoints: in the CSV; same picture.) Market
excess return over the period: 9.06 %.

Table R2. Mean excess return of the ten groups, all sizes, NYSE breakpoints (computed after the test, on the same years).

| Model | Weights | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Trees | Equal | −1.2 | 8.1 | 8.3 | 9.1 | 10.5 | 12.2 | 12.0 | 13.4 | 14.2 | 17.8 |
| Trees | Value | 5.0 | 7.7 | 7.4 | 10.0 | 9.5 | 9.7 | 8.8 | 11.3 | 11.2 | 8.4 |
| Ridge | Equal | −2.3 | 4.2 | 4.8 | 7.6 | 9.7 | 9.4 | 10.9 | 12.1 | 13.2 | 20.0 |
| Ridge | Value | 5.9 | 6.2 | 8.2 | 7.8 | 10.3 | 10.4 | 10.2 | 11.5 | 12.5 | 15.9 |

Tree forecasts tie: in table R2 the groups 2 to 9 of the trees are empty in 4
to 34 months of 396 (group 9: 34, group 8: 28, group 4: 19), so their means
are taken over slightly different months. Groups 1 and 10 are never empty, and
table R1 is not affected. Giving −100 % to the 119 missing returns moves the
equal-weighted top group of the trees from 17.80 to 17.55 and their
equal-weighted top minus bottom from 18.99 to 18.83 (measured by the audit).
These 119 stock-months stay in the computation of the breakpoints; only their
returns are left out of the means.

Table R3. Rank correlation between forecast and realised return (monthly mean) (computed after the test, on the same years).

| Model | Universe | 1993–2025 (t) | 1993–2008 (t) | 2009–2025 (t) | Months positive, 1993–2025 |
|---|---|---|---|---|---|
| Trees | All sizes | 0.043 (9.08) | 0.048 (5.86) | 0.038 (7.70) | 73 % |
| Trees | Large | 0.023 (3.74) | 0.029 (3.17) | 0.018 (2.13) | 60 % |
| Ridge | All sizes | 0.047 (8.42) | 0.050 (5.55) | 0.044 (6.57) | 70 % |
| Ridge | Large | 0.034 (4.52) | 0.046 (4.17) | 0.023 (2.33) | 62 % |

Measured:

- Both models order the stocks. With equal weights, top minus bottom earns 19
  to 25 % a year (t about 6), and the returns rise almost regularly from group
  1 to group 10. The rank correlation is positive in about 70 % of the months
  and in both sub-periods.
- For the trees the ordering is in the small stocks: with value weights the
  spread is 3.4 % (t = 1.11), in the large universe 1.9 to 4.9 % (t below
  1.5), and the value-weighted top group has an alpha of −1.50 % (t = −1.17),
  close to the gross alpha of the fund (−0.88 %).
- The ridge keeps part of it in large stocks: value-weighted spread of 10.0 %
  (t = 2.38), value-weighted top group with an alpha of 5.32 % (t = 2.41) in
  all sizes and 4.08 % (t = 2.16) in the large universe.
- The rank correlation is about half as large in the large universe as in all
  sizes, and lower in 2009–2025 than in 1993–2008 for both models.
- Paired on the same 396 months (all sizes, NYSE breakpoints; only the weights
  change inside a sort): top minus bottom is 15.62 points a year higher with
  equal weights than with value weights for the trees (t = 5.04), and 12.20
  points for the ridge (t = 4.60). Leaving out the stocks below the NYSE 20th
  percentile lowers the equal-weighted spread by 14.1 points for the trees and
  11.3 for the ridge; the breakpoints are then recomputed, so this is not the
  isolated contribution of the stocks left out.

Reading, by the rule fixed in section 1:

- Trees: reading (a). The ordering is much stronger where small stocks weigh
  more. With value weights the spread of the trees is small and imprecise
  (3.4 %, t = 1.11), not shown to be absent: their rank correlation stays
  positive above the NYSE 20th percentile (0.023, t = 3.74). The statement
  "the forecasts hold no information" would be wrong.
- A paper spread also uses the short side and trades at the close of the
  formation month. The absence of a positive net alpha is a statement about
  the frozen fund, not about these sorts.
- Ridge: partly reading (a), partly the third case. A value-weighted top group
  without costs has an alpha of about 5 % (t = 2.41), where the fund at zero
  cost has 2.1 % (t = 1.22, test 2). The two differ by the buffer of 10 % /
  20 %, the first-day execution, the order cap and the start in cash; which of
  them accounts for the difference is **not measured**. The rule of section 1
  gave no threshold for "a spread": with t-statistics between 1.5 and 2.6,
  the ridge case is suggestive, not established.
- These are paper portfolios. The sixteen sorts and three periods overlap and
  each gives several statistics: the t-statistics are nominal, and no single
  cell confirms a strategy. The alpha of 5.32 % (t = 2.41) may be quoted only
  as the paper alpha of the value-weighted top group of the ridge, all sizes,
  NYSE breakpoints, before costs, next to the 2.10 % (t = 1.22) of the ridge
  fund at zero cost. The gap of 3.2 points between the two is descriptive: no
  paired test gives its uncertainty.

### Test 2. No cost multiplier gives the trees a positive alpha; the ridge breaks even near a third of our costs

Table R4. Net alpha against FF5 and momentum when every cost is multiplied by k (computed after the test, on the same years).

| Configuration | k = 0 | k = 0.25 | k = 0.5 | k = 1 (test) | k = 2 | Break-even k |
|---|---|---|---|---|---|---|
| Trees, all sizes | −0.86 (−0.87) | −1.92 (−2.01) | −2.98 (−3.15) | −5.09 (−5.13) | −9.29 (−7.18) | none: negative at zero cost |
| Trees, large | −0.70 (−0.65) | −1.68 (−1.61) | −2.67 (−2.58) | −4.64 (−4.32) | −8.56 (−6.48) | none: negative at zero cost |
| Ridge, all sizes | 2.10 (1.22) | 0.57 (0.33) | −0.95 (−0.56) | −4.01 (−2.28) | −10.13 (−5.09) | 0.34 |
| Ridge, large | 2.42 (1.54) | 1.07 (0.69) | −0.27 (−0.17) | −2.96 (−1.85) | −8.34 (−4.52) | 0.45 |

Return minus market at k = 0: trees −0.03 % (t = −0.03) and +0.20 % (0.18);
ridge +3.43 % (1.85) and +3.99 % (2.18). Break-even k by sub-period, ridge:
0.25 and 0.34 in 1993–2008; 0.88 and 1.15 in 2009–2025 (where its net alpha at
k = 1 is about zero). Trees in 1993–2008: 0.07 and 0.03.

Measured:

- A tree fund that pays nothing at all has an alpha of −0.86 % (t = −0.87):
  the same as the "gross" return of the test (−0.88 %). The caveat that gross
  is not a costless fund changes nothing in practice.
- The ridge fund has no significant alpha even at zero cost (t = 1.22 and
  1.54), and its alpha is zero when the costs are about a third (all sizes) to
  less than a half (large) of ours.
- Doubling the costs takes them from 35.3 to 70.3 bp a month and the alpha of
  the trees from −5.09 % to −9.29 %: turnover does not react to costs, because
  the rule ignores them.
- The break-even k is a point estimate, by interpolation of the estimated
  alpha; it has no confidence interval and says nothing about the true cost of
  execution. The test varies one multiplier common to the spread and the
  impact, not other structures of fees or of execution.

Reading: for the main model, over 1993–2025, none of the five cost multipliers
gives a positive estimated alpha, not even zero (−0.86 %, t = −0.87: not
different from zero, so "no alpha", not "a loss"; in 1993–2008 alone the sign
does change, at k = 0.07);
the significant loss of the test is the costs. For the ridge over the whole
period our costs would have to be two to three times too high. In 2009–2025
alone the break-even of the ridge is 0.88 and 1.15: there its result does
depend on the level of the costs, and it is about zero either way.

### Test 3. A fund ten times smaller is not enough

Table R5. Capital of the fund (order cap 10 % of the ADV, costs as in the test) (computed after the test, on the same years).

| Configuration | Capital | Net alpha (t) | Net minus market (t) | Costs bp | Turnover % | Cash % | Orders capped % |
|---|---|---|---|---|---|---|---|
| Trees, all sizes | USD 10 million | −4.24 (−4.27) | −3.40 (−3.55) | 28.7 | 112 | 0.0 | 1.8 |
| Trees, all sizes | USD 100 million (test) | −5.09 (−5.13) | −4.30 (−4.47) | 35.3 | 110 | 0.7 | 13.3 |
| Trees, all sizes | USD 1 billion | −4.83 (−5.40) | −4.81 (−5.38) | 31.1 | 83 | 12.2 | 40.4 |
| Trees, large | USD 10 million | −3.78 (−3.54) | −2.87 (−2.72) | 25.1 | 112 | 0.0 | 0.3 |
| Trees, large | USD 100 million (test) | −4.64 (−4.32) | −3.77 (−3.54) | 32.9 | 111 | 0.4 | 4.5 |
| Trees, large | USD 1 billion | −4.21 (−4.64) | −4.11 (−4.25) | 30.5 | 85 | 11.2 | 26.3 |
| Ridge, all sizes | USD 10 million | −3.10 (−1.66) | −1.52 (−0.80) | 50.9 | 141 | 0.3 | 6.9 |
| Ridge, all sizes | USD 100 million (test) | −4.01 (−2.28) | −2.78 (−1.53) | 51.5 | 130 | 4.7 | 36.8 |
| Ridge, all sizes | USD 1 billion | −4.46 (−3.17) | −5.41 (−3.22) | 32.2 | 80 | 31.8 | 69.6 |
| Ridge, large | USD 10 million | −1.66 (−1.02) | 0.01 (0.01) | 37.3 | 142 | 0.1 | 1.2 |
| Ridge, large | USD 100 million (test) | −2.96 (−1.85) | −1.48 (−0.85) | 45.3 | 137 | 2.3 | 12.9 |
| Ridge, large | USD 1 billion | −4.20 (−2.98) | −4.69 (−2.91) | 34.3 | 92 | 24.8 | 43.3 |

Measured:

- A fund ten times smaller still has a negative alpha in the four
  configurations (−4.24 % for the main one, t = −4.27). It saves 7 bp a month
  of the 35.
- The cost per dollar traded rises with size (costs divided by turnover,
  trees, all sizes): 25.5, 32.1 and 37.3 bp at USD 10 million, 100 million and
  1 billion. The costs per dollar of the fund do not rise at USD 1 billion
  only because the order cap binds (40 % of the orders of the main
  configuration): the fund trades less (83 % a month) and holds 12 % of cash
  (32 % for the ridge). The alpha stays about the same and the return against
  the market falls.

Reading: size changes the cost of a dollar traded by about a fifth either way.
Taking the capital from USD 100 million to 10 million is not enough to make the
strategy worthwhile; at USD 1 billion the fund is partly in cash. These three
scenarios show an effect of capacity on exposure and costs; they give neither a
maximum capacity nor the alpha of a billion fully invested. How
much of the cost is spread and how much is impact at each size is not in these
files (at USD 100 million the test gives 21.4 bp of spread out of 35.3, 61 %;
the audit measured 82 % at 10 million and 35 % at 1 billion with its own
simulation).

### What the three tests add to the conclusion

1. The forecasts are not empty: they order stocks, strongly among small
   stocks, weakly (trees) or moderately (ridge) among large ones.
2. The long-only, value-weighted fund of the test does not turn that ordering
   into a positive alpha: not at zero cost for the trees, and for the ridge
   only below a third of our costs (and not significantly even at zero).
3. Trees: none of the cost multipliers and none of the three capitals gives
   a positive estimated alpha over 1993–2025. Ridge: its estimated alpha is
   positive at zero cost (2.10 %, t = 1.22) and negative at our costs
   (−4.01 %); it is negative at the three capitals.
4. Why the fund fails is only partly shown here. For the trees, test 1 shows
   that the ordering is weak and imprecise among the stocks that carry a
   value-weighted fund. For the ridge that explanation does not hold: its value-weighted top
   group has an alpha on paper, and the fund does not capture it. The role of
   turnover (110 % a month: main journal, section 8.10) comes from the
   exploration of section 8.11 of the main journal, not from these three
   tests.

## 3. Audits

**Separate agent, blank context (2026-11-13).** Report:
`Workspace/output/2026-11-13_AUDIT_AGENT_robustesse_A.md`. Verdict: ready with
reservations; no number of the CSV files is wrong.

Recomputed on its own: test 1 with its own code (breakpoints, groups, both
weightings, a hand-written Newey-West, rank correlation), equal to the four CSV
files to 1e-13; tests 2 and 3 with a simulator written from the rules without
importing the project (28 simulations), which reproduces the frozen backtest
to 7e-16 at k = 1 and USD 100 million and gives the 60 rows of the cost file,
the 36 of the capital file and the 12 break-even values; a copy of the script
gives the seven CSV files byte for byte. No look-ahead and no date shift in
test 1 (the return is the one of t + 1, market equity and flags are those of
t, group 10 is exactly the top 10 % of the test, factors aligned). Changing
the capital of the imported module touches every use of it and nothing else.
Of 304 numbers of tables R1 to R5, 300 were exact.

| Finding | What was done |
|---|---|
| Four numbers of table R5 rounded twice | Corrected (13.3, 25.1, 69.6, 43.3) |
| "Costs per dollar do not rise" is false per dollar traded; "mostly from the spread" is not in the published columns | Test 3 rewritten with the cost per dollar traded and what is and is not measured |
| "The negative conclusion holds with no costs at all" is too strong: at zero cost the alpha of the trees is not different from zero; for the ridge in 2009–2025 the result depends on the costs | Reading of test 2 rewritten |
| The explanation by value weights is contradicted by table R1 for the ridge; the causal role of turnover does not come from these tests | Final list rewritten (points 3 and 4) |
| The breakdown of the ridge gap (buffer, first day, cap) is not measured; the reading rule had no threshold | Stated as not measured |
| Nothing proves that section 1 came before the results; test 2 could be foreseen; the exploration of 8.11 was also known | Stated in section 0 |
| No JSON report with the hashes of the outputs | Added to the script (`reports/robustness/robustness_report.json`); outputs unchanged |
| `ProjectJournal.md` absent from the working tree; turnover is in 8.10, not 8.11 | References corrected |
| The captions of the tables did not carry the status | Added |
| Groups 2 to 9 of the trees empty in some months (table R2) | Note added under the table |

Left as they are (minor): the panel and the factor table are read without a
hash check by the script (the agent checked that they are those of the
freeze); approximations in the text ("about half", "about 70 %").

Not verified by the agent: that section 1 was written first; the rules of the
monthly step themselves (its simulator starts from the same text); the
breakdown of the ridge gap.

**Lightened audit by Astra (2026-11-13).** Report:
`Workspace/output/2026-11-13_AUDIT_ALLEGE_robustesse_A_pour_Claude.md`.
Verdict: yes, the three diagnostics can be quoted, each table stating that it
was designed after the test of A was read and evaluated on the same years; no
blocking finding.

| Finding | What was done |
|---|---|
| "Neither the level of the costs nor the size of the fund changes the sign" is false for the ridge (+2.10 % at k = 0, −4.01 % at k = 1) | Point 3 of the final list rewritten, model by model |
| "The ordering is absent" among large stocks is too strong for the trees | Replaced by "weak and imprecise"; paired contrast between weightings added (15.62 points, t = 5.04; 12.20, t = 4.60; checked) |
| The break-even k is a point estimate; "no error on costs" generalises beyond what was varied | Title and reading of test 2 rewritten |
| Test 3 shows an effect of capacity, not a maximum capacity | Title and reading of test 3 rewritten |
| Multiplicity: nominal t-statistics; how the alpha of 5.32 % may be quoted | Stated under the reading of test 1 |
| "And nothing else" under table R2 | Removed; the effect on top minus bottom added |
| In the note on version A already sent, "The forecast adds no information that survives value weighting" is not supported | Replaced in `reports/results_version_A_a_jour.md` (section 6, point 2) |

Astra recomputed only the paired contrasts; not verified: that section 1 came
first, the causal breakdown of the ridge gap, the real capacity of execution.
Test 1 contradicts no number of the frozen fund and does not reopen the
results of sections 8.10 to 8.12 of the main journal.
