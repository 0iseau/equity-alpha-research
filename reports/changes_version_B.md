# What changed: results of version B (2026-11-13, evening)

This note lists what is new or changed since the results of version A and the
corrected journal were sent. Nothing in the results of version A changed: its
tables, its figures and its conclusion are the same.

## New files

| File | Content |
|---|---|
| `reports/results_version_B.md` | Results of version B with their reading: the answer in four lines, A against B, the main configuration in detail, the ten configurations, sub-periods, the comparisons fixed at the freeze, the reading for the committee, the reservations, the settings chosen, the provenance |
| `reports/tables_B.md` | Every number of version B, by configuration and period |
| `reports/figures/B_cumulative_value.png` | Value of 1 invested at the end of 1992: fund after costs, gross index, market |
| `reports/figures/B_cash_share.png` | Share of the fund in cash through time |
| `reports/figures/B_costs.png` | Trading costs through time |

## Changed files

| File | What changed |
|---|---|
| `reports/results_version_A.md` | Section 5, item 8 only: "Version B: not available yet" is replaced by its result and a link to the note on B. No number of A changed. |
| `ProjectJournal.md` | New section 8.12 (test of version B, table A against B, reading, audit). Section 8.10: the last paragraph now points to 8.12. Section 10: version B is no longer an open item. |

Unchanged: `reports/tables_A.md`, `reports/figures/A_*.png`,
`reports/exploration_post_test_A.md`, `reports/errata_for_team.md`.

## What version B says, in short

Version B adds 135 accounting characteristics to the 59 market characteristics
of version A. Everything else is the same (models, portfolio rule, costs,
test). It was run once, after A, through the same frozen scripts.

| Main configuration, 1993–2025, % a year (t) | Version A | Version B |
|---|---|---|
| Alpha against FF5 + momentum, net of costs | −5.09 (−5.13) | −5.54 (−4.52) |
| Alpha against FF5 + momentum, gross | −0.88 (−0.90) | −1.17 (−1.01) |
| Alpha, net with the commission stress | −6.96 (−6.59) | −7.55 (−5.96) |
| Net excess return (market: 9.06) | 4.76 | 4.24 |
| Sharpe ratio, net (market: 0.60) | 0.31 | 0.27 |
| Trading costs, bp a month | 35.3 | 36.7 |
| Turnover, % of the fund a month | 110 | 110 |
| Value of 1 at the end of 2025, after costs (market: 29.7) | 7.1 | 6.0 |

1. **The accounting characteristics do not change the answer.** No alpha
   before costs, a significantly negative alpha after costs.
2. **B is not better than A.** The difference between their monthly net returns
   is −0.52 % a year (t = −0.67); no difference is distinguishable from zero in
   any configuration.
3. **Same mechanism.** Costs of about 37 bp a month (4.4 % a year) are almost
   the whole distance between the gross and the net alpha.
4. **Against FF5 + momentum the net alpha is negative in all ten
   configurations of both versions.**

## How to state it in the report

- Version A remains the conclusion of the project; version B is a complement
  (rule fixed before any result). Write "version B confirms version A", not
  "two independent tests".
- Do not write "negative in every cell": over all periods and factor models, 13
  of the 120 net cells of A and 1 of the 120 of B are positive (all for the
  ridge, none significant). The sentence that is exact is the one of point 4.
- "Gross" is the net return plus the costs paid that month, on the positions
  really held: not a fund without costs.
- The comparison "B minus A" and the correlations between the two funds are
  descriptive: they were not among the tests fixed at the freeze.
- Restated accounts (version B only): the reservation does not rescue B, but
  neither the sign nor the size of its effect is measured. Do not write that
  it "cannot matter".
- Not verified: a second run of the forecasts to confirm identical files (A and
  B); the factors rebuilt from our own data.

## Checks made on the note on B

A separate audit recomputed every alpha and t-statistic of both versions from
the monthly records with its own code (largest gap 4e-16), the 464 numbers of
the tables of the note (two cells corrected, a rounding) and the 1,250 numbers
of `tables_B.md` (no gap). Seven sentences that were wrong or too strong in the
first draft were rewritten before sending.
