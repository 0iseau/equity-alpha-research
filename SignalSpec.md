# Signal specification

Version 0.3, 2026-11-12. Corrected after the Astra audit of the list and the
plan (section 8); 15 daily characteristics added to step 9 by decision of the
project owner (section 7). Status: **list fixed at 194 characteristics;
scripts 1 and 2 are built and pass their checks (section 4.5); script 3 is not
written; nothing is closed until the audits are back.** Two decisions wait for
the project owner (section 7).

## 1. Where the signals come from

Two sources only, so that nothing is arbitrary:

- **The adviser's brief** (an industry adviser consulted by the project owner):
  select stocks with several families of signals (momentum, value, quality,
  earnings revisions, volatility, possibly alternative data); compare a
  traditional multi-factor model with machine learning (boosted trees, neural
  networks); control sector and factor exposures; judge out of sample, after
  trading costs.
- **The literature.** Jensen, Kelly and Pedersen (2023, JKP) build a library of
  published signals with public code (local clone, commit `b5695ea`: 404
  characteristics, themes file v1.0; the 2023 paper itself has 153 factors in 13
  themes, so the code and its version are cited separately from the paper). Gu,
  Kelly and Xiu (2020, GKX) is the reference for return prediction with machine
  learning from such a list.

## 2. Selection rule

**Every one of the 404 JKP characteristics gets a decision, with its reason, in
a register checked by `scripts/signals/0_signal_list.py`.** A characteristic is
kept when its JKP formula (annual US branch) can be computed from the admitted
tables. The criterion is data availability only: nothing is kept or dropped for
what it is expected to earn, and the register was fixed before any signal or
return was computed.

**Admitted tables** (the final outputs of the closed cleaning):
`crsp_panel_acc`, `compustat_annual`, `crsp_daily_agg`, and the market and
risk-free columns of `ff_factors_monthly`.

**What "computed with the JKP formula" means here.** We do not claim to
reproduce the JKP data set. JKP combine annual and quarterly accounts, North
American and Global files, and their own market factors. We apply the JKP
formulas to our annual US extract. Three statements must stay separate: the
column exists; the branch reached gives the JKP value on that row; the coverage
is the same as JKP's. Only the first two are claimed, row by row:

- when JKP writes a chain of choices (`coalesce`), a value is produced on a row
  only with a branch whose inputs and guards are all known on that row;
- **an item that is absent from our extract is unknown, never zero.** A
  characteristic is excluded when its formula would put a zero in place of such
  an item (`xrd`, `ivao`, `ivst`, `intan`, ...);
- an item that is in our extract but empty on a row follows the JKP code,
  including its SAS-style sums (`sum_sas(dltt, dlc)` takes the other component
  when one is missing; 3,596 balance sheets);
- **three first choices are absent from our extract** (`gp`, `xopr`, `ebitda`).
  The Compustat definitions are used instead (`sale − cogs`, `cogs + xsga`,
  `oibdp`). The 26 characteristics concerned carry the label
  `definitional_fallback`. Evidence measured by the auditor: on 256,728 complete
  rows, `sale − cogs − xsga − oibdp` differs from zero by more than USD 1,000 on
  421 rows (0.16 %). The separate identities cannot be tested (the four items
  are not in the raw export either): a declared limit;
- book equity: step 7 has `txditc` but not its JKP fallback `txdb + itcb`. For
  31,939 positive book equities with `txditc` missing, equality with JKP cannot
  be established. **Rule: these values are published as a local approximation**
  (deferred taxes unknown and counted as zero, which is also the last step of
  the JKP formula), not masked; the same holds for every lag and ratio built on
  them, `eq_dur` included. The claim "the branch reached gives the JKP value on
  that row" does not cover them, nor the 26 `definitional_fallback`
  characteristics.

Each accounting characteristic carries a **branch label** in
`resources/signal_list.csv`: `leaves_present` (27: every item of every JKP
branch is in our extract), `first_choice` (82: the first choice of each chain is
in our extract, a fallback is not, so coverage can be lower than JKP's),
`definitional_fallback` (26).

**Two kinds of exclusion** (`resources/signal_exclusions.csv`):

- `data` (195): an input is not in our data at all;
- `scope` (15): computable from the daily file, but not computed at step 9.
  This is a choice of scope, not a lack of data, and it is reported as such:
  10 daily regressions or moments against the market (idiosyncratic volatility
  and skewness, short and downside betas, Dimson beta, 5-year correlation and
  betting-against-beta), left out because of their cost before the deadline; 5
  turnover and zero-trade characteristics, which need the daily shares
  outstanding, not kept in the intermediate daily table.

## 3. The list: 194 of the 404 JKP characteristics

404 = 194 kept + 195 excluded for data + 15 excluded for scope.

| JKP theme | Version A (market data) | Version B adds (accounting) | In JKP |
|---|---|---|---|
| Momentum | 14 | 0 | 16 |
| Short-term reversal | 1 | 0 | 1 |
| Long-term reversal | 12 | 0 | 12 |
| Seasonality | 5 | 0 | 5 |
| Low risk | 9 | 2 | 29 |
| Size | 6 | 5 | 18 |
| Issuance | 8 | 14 | 65 |
| Value | 4 | 14 | 32 |
| Profitability | 0 | 15 | 41 |
| Fundamental momentum | 0 | 16 | 32 |
| Investment | 0 | 37 | 72 |
| Financial strength | 0 | 27 | 41 |
| Operating efficiency | 0 | 4 | 20 |
| Earnings quality | 0 | 1 | 10 |
| Intangibles | 0 | 0 | 5 |
| Quality | 0 | 0 | 3 |
| No theme (special dividends) | 0 | 0 | 2 |
| **Total** | **59** | **135** | 404 |

- **Version A (rule D12)**: 59 characteristics with no accounting input:
  - 21 momentum and reversal returns, 10 seasonality returns;
  - `eqnpo_1m` to `eqnpo_12m`, `chcsho_1m` to `chcsho_12m` (share changes),
    `div1m_me` to `div12m_me` (dividend yields from `ret − retx`);
  - `market_equity`, `prc`, `dolvol_126d`, `dolvol_var_126d`, `ami_126d`,
    `bidaskhl_21d`;
  - `rvol_21d`, `rvol_252d`, `rvolhl_21d`, `beta_252d`, `beta_60m`,
    `ivol_capm_60m`, `rmax1_21d`, `rmax5_21d`, `rmax5_rvol_21d`;
  - `prc_highprc_252d`.

  The auditor compared the panel before and after the accounting join: zero
  difference on `eligible`, `ret_signal_ok`, `me`, `prc`, `ff49`, `ret`. Version
  A uses the market equity of the **security**. The 501,578 eligible formations
  without accounts stay in the ranks of version A.
- **Version B**: version A plus 135 accounting characteristics.
- Changes after the audit: `eq_dur` added (its inputs are in our extract; the
  projected dividends come from the JKP recursion, not from an accounting
  dividend); `beta_60m` and `ivol_capm_60m` added (60 monthly returns, at least
  36, against the Ken French market, the deviation already declared at step 9).
- **Fifteen daily characteristics added on 2026-11-12** (decision of the project
  owner, taken before any signal or return was computed): step 9 was extended
  with the JKP functions `rmax`, `ami`, `dolvol`, `prc_to_high` and the
  high-low volatility of `compute_bidask_spread`, and with the cumulative share
  factor of the monthly date (`cfacshr_mth`), from which `chcsho_*` and
  `div*_me` are computed. See `CleaningSpec.md`, step 9, "Columns added for the
  signals".

**Concentration, to keep in mind when reading results.** Coverage is uneven:
37 characteristics of Investment, 27 of Financial strength; in version A, 31
of 59 are windows of the same monthly returns. An equal-weight average gives
more weight to mechanisms that appear several times; regression coefficients
can be unstable; trees split the importance among substitutes. The weight by
theme, the missing rates and the correlations on the training sample are
reported.

**Families we cannot build, to state in the report** (wording proposed by the
auditor): *we measure the predictability available from prices and from the
annual items of this extract. Analyst revisions, alternative data, accruals,
cash flows, R&D and quarterly accounts are absent or very incompletely
represented. The loss of predictive power from these families is not
identified.*

## 4. Construction plan

Each script copies the JKP function named in `signal_list.csv`, cites it, and
justifies every deviation. Same standards as the cleaning: verified reads, fail
closed, atomic outputs, JSON report with run id and hashes, explicit sort
before any order-sensitive computation. The executed JKP code prevails over its
comments.

| Script | Output | Content |
|---|---|---|
| `0_signal_list.py` | `resources/signal_list.csv` | Register of the 404 and its checks (done). |
| `1_price_signals.py` | `signals_price.parquet`, key `permno`–`eom` | 47 monthly market characteristics, `rmax5_rvol_21d`, and the 11 read from step 9. |
| `2_accounting_signals.py` | `signals_acc.parquet`, key `gvkey`–`datadate` | Helper variables and the accounting characteristics that need no market value. |
| `3_signal_panel.py` | `signal_panel.parquet` (raw values), `signal_ranks.parquet` (ranks), key `permno`–`eom` | Join at the formation date, market-scaled characteristics, ranks and missing flags. |

### 4.1 `1_price_signals.py`

JKP `expand`, `mom_rev_cols`, `seasonality`, `eqnpo_cols`, market beta.

- Histories are built **before** any eligibility filter. Complete month grid per
  `permno`; `count` starts at 1.
- **One source of returns: `ret_x` = `ret` where `ret_signal_ok` is true,
  missing otherwise.** This mask is applied on the source row, before any
  cumulative product. It is a deliberate deviation: JKP masks after the indices
  are built, which would let a delisting return into an index.
- **Both JKP indices, `ri` and `ri_x`, are built from `ret_x`**: cumulative
  product of `1 + coalesce(ret_x, 0)`. We have no local-currency return, so the
  two are the same series.
- Missing months (decision D24, section 8d): a window with a month that has no
  usable return gives no value. A masked delisting row is a missing return,
  never a zero return. An index that reached zero after −100 % does not start
  again.
- `ret_j_i` = `ri(t−i) / ri(t−j) − 1` if `ri(t−j) ≠ 0`, `count > j` and
  `ret_x(t−i)` is known.
- Seasonality: lags `12(a−1)` to `12b − 1`; anniversary lags `12a − 1`,
  `12a + 11`, ..., `12b − 1`; `count ≥ 12b`; fixed divisors; ordinary sums. A
  missing anniversary month makes both columns missing; a missing month outside
  the anniversaries leaves `an` and makes `na` missing. `seas_1_1an(t)` =
  `ret_x(t − 11)`.
- `eqnpo_h` = `ln(ri / ri_h) − ln(me / me_h)`, both indices and both market
  equities strictly positive, `count > h`, then `|x| < 1e-5 → 0`.
- `beta_60m`, `ivol_capm_60m`: regression of the monthly excess return on the
  Ken French market over 60 months, at least 36 observations (JKP
  `market_beta`).
- `bidaskhl_21d` is used as a predictor as JKP defines it. The "observed range"
  mask of rule D14 concerns the cost model only.
- `chcsho_h` (JKP `chcsho_cols`): `aux = shrout × cfacshr_mth`;
  `aux / aux(t−h) − 1` if `aux(t−h) ≠ 0` and `count > h`. Shares times the
  factor do not move at a split. Check case: PERMNO 12490, 1999-05,
  `chcsho_1m` = −0.0143735248.
- `div_h_me` (JKP `prepare_crsp_sf`, `div_cols`): dividend per share of the
  month `div_tot = (ret − retx) × prc of the previous row × cfacshr_mth /
  cfacshr_mth of the previous row`, if the previous factor ≠ 0; amount
  `div_tot × shrout`; sum of the amounts over h months (at least one month
  present) divided by the current `me`, if `count ≥ h` and `me ≠ 0`; values
  below 1e-5 set to 0. `ret` and `retx` are masked by `ret_signal_ok` on the
  source row. Check case: PERMNO 12490, 1999-05, `div1m_me` = 0.0011469246.
- **`cfacshr_mth` is only used as a ratio between two dates of the same
  stock.** Its level is today's vintage and depends on later splits; in a ratio
  the later splits cancel. A test changes the factor of all dates by a constant
  and requires identical signals.
- `rmax5_rvol_21d` = `rmax5_21d / rvol_252d` (JKP `finish_daily_chars`); a
  non-finite result is missing.

### 4.2 `2_accounting_signals.py`

JKP `add_helper_vars`, `var_growth`, `chg_to_assets`, `safe_div`,
`add_accounting_misc_cols_1`, `financial_soundness_and_misc_ratios_exps`,
`add_liq_and_efficiency_ratios`, `add_profit_scaled_by_lagged_vars`,
`compute_capex_abn`, `chg_to_exp`, `chg_var1_to_var2`, `vola`,
`compute_earnings_persistence`, `equity_duration_cd`.

- Month-end grid per `gvkey`; grid months without accounts are never usable
  accounts. Our table has USD fiscal years only (D6): a fiscal year in another
  currency leaves a hole, and a 12-month change across it is **missing**. Check
  case: GVKEY 008644, `at_gr1` at 1995-12-31 must be missing (the 1994 accounts
  are in CAD), not +8.619.
- Negative `at`, `sale`, `che` are missing before any formula (already done at
  step 7).
- Growth (`var_growth`): value / base − 1, lagged base **positive**,
  `count > h`; 12 and 36 months, 24 for `capx_gr2`.
- Change scaled by assets (`chg_to_assets`): difference over h months /
  **current** assets, positive, `count > h`. `txditc_gr*a` uses the raw
  `txditc`.
- **`safe_div` has nine modes; each characteristic uses the mode of the JKP
  code.** Mode 1: denominator ≠ 0, a negative denominator is allowed (`gp_at`,
  `fi_at`, `debt_at`, `nix_sale`). Mode 3: denominator > 0 (`cash_cl`, `ca_cl`,
  `sale_nwc`, `cash_at`). Mode 4: denominator 12 months before > 0 and
  `count > 12` (`gp_atl1`, `ope_bel1`). The sentence of version 0.1 ("zero or
  negative denominator → missing") was wrong.
- `at_turnover` = `sale_x / mean_year(at_x)`: mean of the current and the
  12-month-old assets, or the one available; `count > 12`.
- `capex_abn`: ratio `capx / sale_x` (sales > 0 for each ratio used) over the
  mean of its three values at −12, −24, −36, minus 1; the three must be known,
  their sum not zero, `count > 36`.
- `CE(x) = x / mean(x at −12, x at −24) − 1`, both bases known, their sum > 0,
  `count > 24`. `dgp_dsale = CE(gp_x) − CE(sale_x)`;
  `dsale_dsga = CE(sale_x) − CE(xsga)`: each is a difference of two such terms.
- `*_ch5`: difference of the ratio over 60 months, both denominators positive,
  `count > 60`.
- `roe_be_std`: sample standard deviation of 5 annual values of `ni_x / be_x`
  (lags 0 to 48 months), `count > 48`.
- `ni_ar1`, `ni_ivol`: `ni_x / at_x` on its value 12 months before, five pairs
  (six aligned balance sheets), regression with a constant, regressor standard
  deviation above 1e-6; `ni_ivol` is the sample standard deviation of the
  residuals (divisor n − 1).
- `ol_x = col_x + ncol_x` keeps the JKP dependence on `cl_x`. `fi_x` uses
  `nix_x`; `nix_sale` uses the raw `ni`.

### 4.3 `3_signal_panel.py`

JKP `add_me_data_and_compute_me_mev_mat_eqdur_vars`; GKX for the ranks.

- **`signals_acc.parquet` is keyed by fiscal year end and has no availability
  date: it is never joined on the month of `datadate`**, only through
  `acc_datadate` of the panel (rule D4, step 8).
- Join `(gvkey, acc_datadate)` → `(gvkey, datadate)`, many to one, exactly one
  output row per `(permno, eom)`; accounts are 6 to 18 months old (D4).
- Market value of the **company at month t**, never of the fiscal year:
  `me_company`, only if `me_company_complete`; `mev = me_company + netdebt_x`;
  both missing if not positive.
- **Declared deviations from JKP for the 23 characteristics that use the
  company market value** (`eq_dur` and `enterprise_value` included): JKP
  sums the share classes that are present even if one is missing, and uses price
  × shares; we use the CRSP market cap and require all classes (60 eligible
  formations with an incomplete company value, 3 with accounts). Our links (D5)
  are stricter than JKP's. Secondary share classes keep their version A signals;
  their accounting signals stay missing and are never copied through `permco`.
  Two more differences in the denominator: JKP sums the classes by `permco` and
  CRSP date, we sum by `permco` and month; JKP then keeps, by `gvkey` and month,
  the largest company value among the main common stocks
  (`load_mkt_equity_data`), we take the company value of the linked stock.
- **Rule D26: one CRSP company, several Compustat companies.** When the
  `permco` of the month has stocks linked to more than one `gvkey` (tracking
  stocks: the Liberty groups, for instance), `me_company` is the value of the
  whole and the accounts are those of one part. The 23 characteristics are then
  missing; the other accounting characteristics are kept. 2,231 eligible
  formations with accounts, 26 CRSP companies. JKP has no such rule. Reference
  case: PERMNO 15997 (Braves Group), April 2023: `debt_mev` would be 697 of
  debt of the Braves Group over the 27,709 of market value of all Liberty
  groups; it is missing, `debt_at` is kept.
- **Ranks (D18, fixed after the audit).** At t, over the eligible stocks only,
  rank the finite observed values with the average rank for ties. For n ≥ 2
  observed: `s = 2(r − 1)/(n − 1) − 1`. A missing or non-finite value gets 0
  and flag 1. n = 1: the value gets 0, flag 0. All missing: all 0, flag 1. All
  equal: all 0, flag 0. Example: `[2, 2, 5, missing]` → `[−0.5, −0.5, 1, 0]`,
  flags `[0, 0, 0, 1]`. No threshold for near-constant series; the number of
  distinct values is reported. `permno` never breaks a tie between equal
  values. Ranks are never filtered on the existence of a return or of a trade
  in t+1.
- The missing flag per characteristic is our extension; GKX fill with the
  monthly median and have no such flag.

### 4.4 Checks that stop the scripts

1. The columns built are exactly the names of `signal_list.csv`.
2. **Version A is independent of the accounts**: same keys, values and ranks
   when every account and CCM link is removed.
3. **Truncation tests on the sources**, with all the history kept, at three
   dates including a fiscal year end and a delisting month.
4. **Perturbation tests**, each one apart: the return of a masked row; the
   delisting amounts; the targets; the execution data of t+1. No signal at t may
   change, including the signals of other stocks. Ranks do not change when
   ineligible stocks change.
5. Forbidding the `t+1` and `after_t` columns is not enough: a test also checks
   that no **row** of a later month is read.
6. Acceptance cases of section 5, at the first month allowed and the month
   before; cases with an inner gap, a missing end, a delisting, a split of the
   month grid, a currency hole, a secondary class; a strict sum of the two debt
   items must fail where JKP's SAS sum applies.
7. Negative tests: a 5-month accounting lag and a one-month shift of the
   momentum window must be caught.
8. Keys, cardinality of the joins, units, coverage by characteristic and
   decade, and byte-for-byte reproducibility.
9. The data dictionary is extended to the new tables and checked.

### 4.5 State of the build (2026-11-12)

Scripts 1 and 2 were written while the audit of the step 9 addition was still
running, by decision of the project owner. Nothing is declared closed, and **no
return of a strategy, of a portfolio or of a sorted group has been looked at**:
the checks below compare characteristic values only.

| | `1_price_signals.py` | `2_accounting_signals.py` |
|---|---|---|
| Output | `signals_price.parquet`: 5,210,894 stock-months, 59 characteristics | `signals_acc.parquet`: 335,244 fiscal years, 112 characteristics, plus the 18 items that script 3 divides by the market value |
| Run | `212e648e3d9d` (after the correction of step 9) | `2a6170765a81` |
| Acceptance cases of the auditor | 17 of 17 (two audits): 15 within 1e-8, one within 1e-5 (a reverse split taken from a dated event), one that must be missing | 7 of 7 within 1e-8 (`at_gr1`, `gp_at`, `debt_at`, `ni_ar1`, `ni_ivol`, `ed_cd`, `ed_cd_w`); growth across the CAD year of GVKEY 008644 is missing |
| Second route | 164 stocks, 20,970 months, 17 characteristics recomputed with numpy slices (no shift, no rolling sum): no difference in missing values, largest relative gap 1.3e-12 | 185 companies, 2,640 fiscal years, 27 values recomputed in plain Python with a lookup by date (no grid): no difference in missing values, largest relative gap 5.1e-13 |
| Truncation at 1975-06, 1999-12, 2015-03 | identical | identical |
| Other tests | a masked return replaced by another value changes nothing; the share factor doubled changes nothing; without the mask the test does detect the change; `ret_1_0` is missing on the 29,745 masked rows and equal to the monthly return elsewhere | SAS-style sum of debt on the 3,596 rows with one item only; a neighbouring-row lag would not pass the cases |
| Two runs in a row | same SHA-256 | same SHA-256 |

Notes on the build:

- **The panel has no missing month inside a stock** (5,210,894 grid rows for
  5,210,894 panel rows): the month grid adds no row.
- `beta_60m`, `ivol_capm_60m` (JKP `prep_data_factor_regs`, `capm`): months with
  a zero return are left out, as in JKP; the excess return is winsorised by
  month at the discrete 0.1 % and 99.9 % quantiles **of our cross-section** (all
  CRSP stocks of the panel; JKP uses its own universe); 60 months, at least 36.
- `ebitda_x` follows the rest of the JKP chain when `oibdp` is missing:
  `sale − (cogs + xsga)`, then `gp_x − xsga` (2,702 fiscal years).
- Joint identity `sale − cogs − xsga − oibdp` on 256,728 complete rows: 256,307
  within one rounding unit (USD 1,000), 421 above, 14 above USD 1 million.
- Coverage among eligible stock-months since 1963, by count: one-year momentum
  91.6 %, five-year reversal 64.6 %, seasonality of years 16 to 20: 22.3 %,
  `beta_60m` 74.8 %, share changes over 12 months 91.7 %. The long windows
  have low coverage by construction; rule D18 gives them a neutral rank and a
  flag.
- Script 3 and the extension of the data dictionary were done on 2026-11-13
  (section 8e), the lightened audit by Astra was handled (section 8f), and the
  step was closed the same day.

## 5. Acceptance cases (recomputed by the auditor from the tables)

PERMNO 12490, GVKEY 006066, formation of 2000-12-31, fiscal year 1999 attached.
Tolerance 1e-8.

| Characteristic | Expected value |
|---|---|
| `ret_12_1` | −0.1292730033 |
| `ret_60_12` | 3.8744844134 |
| `seas_1_1an` | 0.0405560000 |
| `eqnpo_12m` | 0.0317017933 |
| `be_me` | 0.1449682576 |
| `at_gr1` | 0.0162020906 |
| `gp_at` (fallback branch) | 0.4353163038 |
| `debt_at` | 0.3240642322 |
| `ni_ar1` | 0.7395355973 |
| `ni_ivol` | 0.0057040279 |
| `eq_dur` | 17.7678775022 |

Other cases: PERMNO 10028, 2013-09, `ret_12_1` = −0.5128204249 with one missing
month inside the window (JKP convention); GVKEY 008644, `at_gr1` missing at
1995-12-31.

## 6. Method to look for alpha (to freeze before the first estimation)

Following GKX, as the adviser describes.

- Target: `ret_exc_lead1`. Bounds are set by the **month of the target
  return**: the return of January 1993 goes with the characteristics of December
  1992. The mechanical end of the sample is excluded. At each fit, only targets
  known at that date are used.
- Split with the initial lengths of GKX (18 years, 12 years, the rest):
  training 1963–1980, validation 1981–1992, **test 1993–2025** (GKX: 1957–1974,
  1975–1986, 1987–2016). Each year, one year is added to the training sample
  and the 12-year validation window moves by one year. That 1993 is also the
  start of the sub-period of D23 follows from 1963 + 18 + 12 and was written
  before any result.
- Two statuses, always labelled in the tables:
  - **estimated models, out of sample, 1993–2025**: a linear regression with a
    penalty, and gradient-boosted trees. Their signs and weights come from the
    training data only;
  - **fixed score, retrospective, 1963–2025**: see decision 2 below.
- Budget of complexity proposed for the trees, to register before the first
  fit: one boosting engine; depth in {1, 2, 3}; learning rate 0.03; number of
  trees in {50, 100, 200}; at least 0.1 % of the training observations per
  leaf; fixed seed; no other search. Validation on the mean **by month** of the
  squared error; ties broken by the smaller depth, then the smaller number of
  trees. Version B has up to 388 inputs (194 ranks and their flags). One more
  model after the test has been seen is a new trial.
- The model predicts the close-to-close return of t+1; the position really
  traded starts at the first close of t+1 (D13). Two horizons, stated as such.
- Portfolio and costs: rules D13 to D23. Alphas against FF5 + momentum, CAPM,
  FF3, FF5, and our own factors (D20).

## 7. Decisions of the project owner

1. **Scope of the daily characteristics: decided on 2026-11-12.** Of the 30
   characteristics computable from the daily file, the project owner chose to
   add 15 within the time available: extreme returns, high-low volatility,
   dollar-volume liquidity, price to the 12-month high, share changes and
   dividend yields. The other 15 stay out and are reported as a choice of scope
   (section 2): nine daily statistics against the market, the skewness of the
   daily return, and five turnover and zero-trade measures. The decision was
   taken before any signal or return was computed, so these 15 were not sorted
   on their performance; their effect on the result is unknown.
2. **The traditional model.** The equal-weight average of ranks needs a sign
   for each characteristic. The JKP signs (v1.0, dated 2026-10-28) were set with
   the literature and with diagnostics on US data from 1972 to 2025: they were
   not known in 1993. 81 are positive and 95 negative on the first 176; two
   changed between versions (`debt_me`, `ni_ivol`). Recommendation: the
   traditional model that is compared out of sample is the penalised linear
   regression; the signed equal-weight score is shown on 1963–2025 and
   labelled **retrospective benchmark**, never as a strategy available at the
   time.
3. **Sector neutrality: ranks decided on 2026-11-13.** The ranks are taken
   over all eligible stocks of the month, not inside industries. Reasons, given
   before any return was looked at: it is the GKX rule that the method follows;
   a rank inside an industry would remove the part of a characteristic that
   differs between industries, which is information the model may use, and
   would make ranks noisy in small industries (few stocks per month before the
   1970s); and it would not make the portfolio neutral anyway. Still open, with
   the portfolio rules: a constraint on portfolio weights against
   the value-weighted universe, on the 12 Fama-French industries built from the
   historical CRSP SIC code, with an "unknown" industry; tolerance to fix with
   the portfolio rules. Factor neutrality is measured ex post by the alphas.

## 8. Audit of the list and the plan (Astra, 2026-11-12)

Report: `Workspace/output/2026-11-12_AUDIT_signaux_liste_et_plan_pour_Claude.md`.
Verdict: "to review". Version A is independent of the accounts in the tables
examined. Findings and what was done:

| # | Severity | Finding | Handling |
|---|---|---|---|
| 1 | Blocking | The script only checked the names it kept: an omission passed. | The register now covers the 404, each with a decision and a reason; the script stops otherwise. `eq_dur`, `beta_60m`, `ivol_capm_60m` added. |
| 2 | Blocking | 26 names rest on a first choice that is absent; other chains lose a fallback. | Rule rewritten (section 2): no claim of exact replication; branch label per characteristic; evidence and limits stated. |
| 3 | Blocking | The plan used `ri` without defining it; copying JKP would bring back the delisting return. | Both indices come from the masked return, before any product (4.1). |
| 4 | Blocking | The JKP signs were set with data that cover the test period. | Decision 2 (section 7): retrospective label, or estimated signs only. |
| 5 | Important | "Not computed at step 9" is a choice of scope. | Exclusions split into `data` and `scope`; decision 1. |
| 6 | Important | Guards and inputs not precise enough to reproduce the code. | Conditions written in 4.1 and 4.2; `ol_x` inputs corrected. |
| 7 | Important | A truncation of restated accounts does not prove their historical content. | D12 unchanged; row-lineage and perturbation tests added (4.4). |
| 8 | Important | Company market value: conventions differ from JKP. | Declared in 4.3. |
| 9 | Important | Ties, constant series, industry and target dates not specified. | Fixed in 4.3 and 6; decision 3. |
| 10 | Minor | Counts based on 402 themes; role of `bidaskhl_21d`. | Counts on the 404; role `predictor` added in the dictionary. |

## 8b. Audit of the step 9 addition and of plan v0.3 (Astra, 2026-11-12)

Report: `Workspace/output/2026-11-12_AUDIT_etape9_signaux_quotidiens_pour_Claude.md`.
Verdict: "to review". The six daily statistics and the reproducibility of
step 9 are confirmed; the 15 added signals do not depend on the accounts.

| # | Severity | Finding | Handling |
|---|---|---|---|
| 1 | Blocking | The CRSP share factor is today's vintage with 12 decimals: later reverse splits round it, down to zero, and make signals missing before those splits happen (PERMNO 12350). | Step 9 now builds a local factor from the past only (`CleaningSpec.md`, step 9). The auditor's two cases pass: `chcsho_1m` of November 2012 = 0.0048579838, and of February 2025 = 0.05279795. |
| 2 | Important | The `retx` test does not prove equality with CRSP's monthly factor. | Scope of the test restated in `CleaningSpec.md`. |
| 3 | Important | Plan of script 1: the two seasonality columns do not go missing together; the 60-month regression has more filters than "36 observations". | The code already followed JKP. Text corrected (4.1). Cases added: PERMNO 10028, November 2012, `seas_1_1an` = −0.036129 and `seas_1_1na` missing; zero-return month of PERMNO 10000. Registry: `ret` is an input of `beta_60m`. The script stops if a month is missing inside a stock (previous row = previous month). |
| 4 | Important | Accounting branches: equality by row promised too widely; two formulas described loosely. | Rule written in section 2 (local approximation, published and labelled). `dgp_dsale`, `dsale_dsga`, `capex_abn` restated (4.2); the code was right. |
| 5 | Important | "The 15 without regression" does not describe the exclusions; the role `predictor` would allow the level of the share factor. | Decision 1 reworded; reasons of the 15 exclusions corrected; role `transform_input`. |
| 6 | Minor | Bound stricter than JKP; variance from sums of squares; 23 dependences on the company market value, not 22. | Fixed in step 9 and in 4.3. |

## 8c. Audit by a separate agent (2026-11-12)

First use of the two-stage audit: before Astra, a separate agent with a fresh
context audited the local share factor and scripts 1 and 2. It had the files,
the rules of the project and the questions, but neither the developer's
reasoning nor Astra's findings. Report:
`Workspace/output/2026-11-12_AUDIT_AGENT_signaux_scripts_1_2.md`. Verdict:
"ready with reservations", no blocking finding. The agent shares the developer's
model: it is a first filter, not the audit that closes the step.

**What it recomputed with its own code, on the whole universe**: 22 market
columns on 5,210,894 rows and 116 accounting columns on 335,244 fiscal years,
with no difference in missing values and a largest relative gap of 2e-11; the
local share factor of the 40,058 stocks, largest gap 5e-15. It confirmed on the
data that only FRS events move the CRSP factor, that no delisting-month return
can reach a signal (the 29,745 masked rows are all the last row of their
stock), and that the month grid has no hole.

| # | Finding | Handling |
|---|---|---|
| 1 | Several FRS events on one ex-date add up in CRSP (`1 + sum`); the code multiplied them. Eight days in the file, all in the "levels" regime: no effect on the output, but a wrong rule. | Fixed. The unexplained changes of the CRSP factor fall from 13 to 5 (two without any event, three extreme reverse splits whose event has 6 decimals); the script now stops above 5. Output of step 9 unchanged (same SHA-256). |
| 2 | The vintage test was too loose and simulated no zero. | Two scenarios (levels divided by 1e7 and by 1e13, the second with 247,176 levels rounded to exactly zero), 109 stocks including those with several events on a day: every stock within 1e-4 (largest gap 4.5e-6), same missing values. |
| 3 | `chcsho_*`: 1,823 values at ±1e-14 instead of zero, which ranks would pull out of the tie of 2.5 million zeros. | A share change below 1e-9 is set to zero (project rule). |
| 4 | A missing return inside a window counts as "no change" (momentum, `eqnpo`), and a month without a computable dividend is skipped (`div*_me`): JKP conventions, against "missing stays missing". | Kept as in JKP and declared (section 4.1). Counted in the report of script 1, among eligible stock-months since 1963: 6,127 `eqnpo_12m` and 20,644 `div12m_me` with a missing month in the window; 39 `eqnpo_1m` whose own month has no usable return. Question put to Astra. |
| 5 | After a change of fiscal year end, growth compares with a short fiscal year (1,977 fiscal years; GVKEY 001076, 1996-12: `sale_gr1` = +53.9 % against a 9-month year). `at_turnover` uses the current assets alone when those of 12 months before are missing (3,542 rows). JKP behaviour. | Declared limit. Question put to Astra. |
| 6 | Guards in floating point (`dgp_dsale` = 1.9e15 for one fiscal year, a base that should be zero); negative items other than `at`, `sale`, `che` enter the ratios; extreme but true values (`chcsho_12m` up to 5e9). | JKP behaviour, kept. Signals are only used as ranks (D18), never as levels. |
| 7 | `signals_acc.parquet` has no availability date: joining it on the month of `datadate` would be a 6-month look-ahead. | It is only joined through `acc_public` / `acc_datadate` (script 3). Stated at the top of section 4.3. |
| 8 | Near-duplicates: `debtst_debt` and `debtlt_debt` (rank correlation −1), `ni_sale` and `nix_sale`, `ret_12_0` and `ret_12_1`, `dolvol_126d` and `ami_126d`; `assets`, `sales`, `book_equity`, `net_income` are the pass-through items under their JKP names. | Not separate pieces of information: to remember for the models (concentration, section 3). |
| 9 | The internal second routes cover part of the columns and share the assumptions of the main computation; the truncation test cannot see a look-ahead that sits inside an input. | True. The agent's own full recomputation covers the first point. The second is why the inputs have their own tests (step 8, step 9 vintage test). |

Not verifiable by the agent: the discrete quantile of DuckDB used by JKP before
the 60-month regression (DuckDB is not installed). Put to Astra.

## 8d. Lightened audit by Astra, and decisions D24 and D25 (2026-11-12)

Report: `Workspace/output/2026-11-12_AUDIT_ALLEGE_facteur_local_scripts_1_2_pour_Claude.md`.
Verdict: "ready with reservations", no blocking finding. Confirmed: the local
share factor removes the missing values caused by rounded zeros; our reading of
DuckDB's `QUANTILE_DISC` (rank `ceil(q × n)` counted from 1, DuckDB 1.5) is
exact; six values recomputed from the source tables on stocks nobody had used
(`chcsho_1m`, `ret_9_1`, `eqnpo_3m`, `div1m_me`, `at_turnover`, `capex_abn`)
agree within 2e-16; setting share changes below 1e-9 to zero is defensible.

**D24 — a missing month stays missing in a window (deviation from JKP).** JKP
carries its return index over a month without a return, as if the return were
zero, and sums the dividends of the months that exist. Both audits flagged it
as contrary to the rule "missing stays missing", which the project already put
before JKP for monthly returns (decision D10). Now:

- a momentum or reversal return `ret_j_i` needs a usable return in every month
  it compounds (months t−j+1 to t−i);
- `eqnpo_h` needs a usable return in each of the h months;
- `div_h_me` needs the h monthly dividend amounts (a known amount of zero
  counts);
- seasonality was already strict; `beta_60m` keeps the JKP minimum of 36 months
  out of 60, which is the usual rule for a regression.

Effect among eligible stock-months since 1963, by count: `ret_12_1` 91.6 % →
91.1 %; `ret_60_12` 64.6 % → 63.0 %; `eqnpo_12m` 91.2 % → 91.0 %; `div12m_me`
92.3 % → 91.0 %. The values lost get the neutral rank and a flag (D18). The
script checks on every row that no value survives a missing month in its
window. Reference case: PERMNO 10028, September 2013, `ret_12_1` is missing
(JKP would give −0.5128204249).

**D25 — the flows of a transition fiscal year are missing (project rule, no
equivalent in JKP).** A fiscal year that ends less than 12 months after the
previous report of the company follows a change of fiscal year end: 1,100
reports in the raw file, all with a new fiscal-year-end month, 1,068 of them in
our USD table. Its income-statement and cash-flow items (`sale`, `cogs`,
`xsga`, `oibdp`, `ib`, `ni`, `xint`, `capx`) cover less than 12 months: they
are set to missing. Every characteristic built on them is missing for that
year, and so is a growth that would use it as its base. Balance-sheet items are
kept. The previous report is looked up in the raw file, in any currency.
Reference case: GVKEY 001076 closes a 9-month year in December 1995; the growth
of sales of 1996 is missing (it would be +53.9 %), the growth of assets is
kept.

Both decisions follow the recommendations of the two audits and the principle
"missing stays missing"; they were applied before any return was looked at.
**Confirmed by the project owner on 2026-11-13** ("for now": they can be
reopened, but only before any result is looked at).

**Vintage of the share factor (finding 1, a declared limit).** The local factor
follows the CRSP level where it is precise and the dated events elsewhere. For
the few changes of the CRSP factor that have no dated event, a later vintage in
which the level is no longer precise would lose the change. `CleaningSpec.md`,
step 9, gives the measured effect. Removing this limit would need a historical
source of share events that we do not have.

## 8e. Script 3, and its audit by a separate agent (2026-11-13)

`3_signal_panel.py`, run `13160ba101a8`. Still open: the lightened audit by
Astra, which closes the step.

| | |
|---|---|
| `signal_panel.parquet` | 5,210,894 stock-months, 194 characteristics (59 A, 135 B of which 23 market-scaled); SHA-256 `0eb99366…a6e858` |
| `signal_ranks.parquet` | 3,805,426 eligible stock-months, 194 ranks (Float32) and 194 flags `<name>_miss` (Int8); SHA-256 `75c36f1f…a4b86a` |
| Three runs in a row | same SHA-256 for both files |
| Acceptance cases of section 5 | 11 of 11 within 1e-8 at 2000-12; the accounts of fiscal year 1999 are attached from 2000-06 to 2001-05 and not in 2000-05 or 2001-06; PERMNO 10028 at 2013-09 missing; GVKEY 008644 missing on its 12 stock-months |
| Tests at 1975-06, 1999-12, 2015-03 (twelve months each) | identical when the accounts closed less than 6 months before are hidden (and different when one more month is hidden); version A identical without accounts and links; ranks identical when the stocks that are not eligible change (and different when eligible ones change); ranks recomputed with scipy, largest gap 3e-8 |
| Company market value | 60 eligible formations incomplete, 3 with accounts: their 23 characteristics are missing |
| Lowest coverage (eligible, from 1963) | `pstk_gr3` 11.8 %, `pstk_gr1` 13.6 %, `seas_16_20na` 22.3 % |

Choices of the script with no effect on the values: work by blocks of five
years (the full table does not fit in memory), both outputs sorted by
(`yyyymm`, `permno`); `signal_ranks` holds the eligible rows only. The data
dictionary is extended to the four signal tables by `signal_dictionary.py`
(937 columns in 11 tables).

**Audit by the separate agent** (blank context, read only; report:
`Workspace/output/2026-11-13_AUDIT_AGENT_signaux_script_3.md`). It recomputed
both files in full with its own code, all months from 1930 to 2025: no
difference in values, missing values, ranks or flags. No blocking finding.

| # | Finding | What was done |
|---|---|---|
| 1 | Important: the published report did not come from the script on disk (the script was edited while a run was going), and the agent could not verify reproducibility. | Run again: same SHA-256 (third identical run). The report now records the SHA-256 of the script. |
| 2 | The "truncation" test cannot fail on the market side (a block reads its own months by key); on the accounting side the bound is exact for month T only. | The test is renamed for what it tests. That no later month is read holds by construction for this script; checks 3 and 5 of section 4.4 are met that way here, and by real truncation tests in scripts 1 and 2. |
| 3 | The two renames at publication are not one atomic step; a killed process leaves temporary files. | Same limit as `utils.publish`; a mixed state is detected downstream by the hash. Documented, not changed. |
| 4 | No hash for `signals_acc.parquet` and for the dictionary among the inputs. | Added. |
| 5 | Dictionary: `predictor` role in `signals_acc`, which has no availability date; market-scaled descriptions silent on `me_company`; `me_company_complete` used but labelled `audit`. | Every column of `signals_acc` is a `transform_input`; the 23 descriptions name `me_company` of month t; `me_company_complete` is `transform_input;audit`. |
| 6 | Two checks would raise a type error instead of a check error; `mev` is computed after the non-positive company value is removed (JKP: before). | Checks guarded. No row has a non-positive company value: no effect, left as is. |

Not verified by the agent: that `acc_datadate` is the latest usable fiscal year
(step 8) and the construction of `me_company` (cleaning), both audited with
their own steps. To know for the models: `chcsho_1m` has only 12 distinct
values in its worst month; GVKEY 179077 carries accounts on two stocks in
2017-10 (one of them not eligible).

## 8f. Lightened audit by Astra, rule D26 and the dating test (2026-11-13)

Report: `Workspace/output/2026-11-13_AUDIT_ALLEGE_signaux_script_3_pour_Claude.md`.
Verdict: "ready with reservations", no blocking finding. Two stock-months that
nobody had used (PERMNO 31318 in 1998-11, 15997 in 2023-04) give the published
`be_me`, `debt_mev` and ranks exactly. The figures of section 8e describe the
run before this audit; the current run is the one below.

| # | Finding | What was done |
|---|---|---|
| 1 | Important: for a CRSP company with several Compustat companies, the accounts of one part are divided by the market value of the whole (PERMNO 15997, Braves Group, 2023-04). | Checked: 2,031 eligible formations with accounts by Astra's count (several `gvkey` with accounts), 2,231 by ours (several `gvkey` linked). **Rule D26** (section 4.3): the 23 market-scaled characteristics are missing there. |
| 2 | Important: "by construction" does not meet checks 3 and 5 of section 4.4 to the letter. | Test added at the three dates: the production path runs on the block that holds T with sources that end at T (panel, a reader of `signals_price` for which later months do not exist, accounts closed at T − 6 months at the latest) and must give the file; the reader must refuse month T + 1; market characteristics moved by one month must be detected. The test covers the block that holds T (1975-01 to 1975-06, 1995-01 to 1999-12, 2015-01 to 2015-03), not all the months before it. |
| 3 | Minor: two differences from JKP in the denominator were not written. | Written in section 4.3. |
| 4 | Minor: keep D18. A rare characteristic gives a rank of 0 with a flag of 1 almost everywhere; a model can then learn from the flag (availability, age of the listing). `chcsho_1m` has 12 distinct values in its worst month. | Kept. For the models (section 6): a minimum leaf size is already in the budget; a comparison with and without flags on the validation sample is a possible check, to decide with the method. |
| 5 | Minor: the ranks over the whole universe can be defended; a measure is missing (by decade, stocks per industry and the share of the variance of the ranks explained by industry means), and the tolerance of the industry constraint is to fix before the test. | Not done: descriptive, for the report. The tolerance belongs to the portfolio rules (section 7, decision 3). |

Run after these corrections: `ff5eda29ad08` (two runs in a row with the same
SHA-256); `signal_panel.parquet` SHA-256 `0f078361…e3b462`,
`signal_ranks.parquet` `c49d9e1b…2ca4be`. Compared column by column with the
run before: of the 588 columns of the two files, 69 changed, which are the 23
market-scaled characteristics, their 23 ranks and their 23 flags (about 2,300
more missing values in each raw column, all rows counted); the 171 other
characteristics, their ranks and their flags are identical. Rule D26 is a
project rule added after an audit and before any return was looked at;
**confirmed by the project owner on 2026-11-13. The signal step is closed.**

## 9. Sources

Checked by the auditor in the papers: JKP (2023), p. 2219–2222; GKX (2020),
section 2.1 and notes 29–30 (ranks in [−1, 1], monthly median, 6-month lag for
annual accounts, split and yearly refit); Green, Hand and Zhang (2017), p. 4389
(12 independent characteristics among 94 outside micro caps, 1980–2014);
Freyberger, Neuhierl and Weber (2020), Table 5; Avramov, Cheng and Metzker
(2023), section 3.

Long-only US references given by the auditor, **not read by us yet**: Esakia
and Goltz (working paper, 2025: CRSP common stocks, ridge and neural network,
top-decile long-only portfolios net of proportional costs, 1993-07 to 2021-12);
Simon, Weibels and Zimmermann (2026), *Deep Parametric Portfolio Policies*; Li,
Wu and Zhou, *Journal of Financial Markets*.
