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

**Rules of the prediction step, written on 2026-11-13 after the choice of the
models (section 7, decision 2) and accepted by the project owner the same day,
before any fit** (the settings may be reviewed on the validation and
development years only, never on the results of 1993–2025). They replace the two statuses above: the retrospective fixed score
is no longer planned.

1. **Rows.** Training and validation: eligible stock-months with a known
   `ret_exc_lead1` (3,447,236 of the 3,448,288 eligible stock-months from
   1962-12 to 2025-11). Predictions: every eligible stock-month, whether its
   next return is known or not. Outputs of `scripts/predictions/1_predictions.py`,
   for each version, with `pred_gbrt` and `pred_ridge`:
   `predictions_<version>_development.parquet` (return years 1981–1992, rule 8)
   and `predictions_<version>_test.parquet` (1993–2025).
   **Rule D27, date at which a target is known** (after the audit by Astra,
   section below; validated by its counter-audit, after which the project
   owner had the first fit launched). The return of a
   delisting month can rest on an amount paid later (`delamtdt`) or on a price
   of a later date (`delnextdt`). A target is known at the end of the latest
   of: its return month, the month of `delamtdt`, the month of `delnextdt`. The
   fit of the return year Y, made at the end of December Y − 1, uses in
   training and in validation only the targets known by then; a target that
   becomes known later enters the later fits. Its value and the rows predicted
   do not change. 3,952 targets are known after their return month, 895 of them
   in a later calendar year (the longest delay is 393 months); for the fit of
   1993, 46 targets are set aside. A delisting return with no date of amount
   (1,285 targets, among them the −30 % imputation of D3) is dated at its
   month. This date does not replace D17, which is about the holding return of
   the portfolio.
2. **Inputs.** Version A: the 59 ranks and 59 flags of the market
   characteristics. Version B: the 194 ranks and 194 flags. One fit on all
   eligible stocks, each stock-month with the same weight (GKX); the universe
   above the NYSE 20th percentile is applied to the portfolio, not to the fit.
3. **Calendar.** One fit per year, as GKX. For the returns of year Y: training
   on the returns of 1963 to Y − 13, validation on Y − 12 to Y − 1; the model
   that predicts is the one fitted on the training sample with the values
   chosen on the validation sample (it is not fitted again on both). Y goes
   from 1993 to 2025.
4. **Main model.** Gradient-boosted trees, **LightGBM 4.7** (decided on
   2026-11-13 before any fit: the engine of scikit-learn converts its inputs to
   64-bit numbers, about 9 GB for version B, which does not fit in the 16 GB of
   the machine; LightGBM bins 32-bit inputs directly). Squared error, learning
   rate 0.03, depth in {1, 2, 3} with 2^depth leaves, trees in {50, 100, 200}
   read from one fit of 200 trees, at least 0.1 % of the training rows per
   leaf, no sampling of rows or columns in the fit, no other penalty, seed 0,
   8 threads. The 255 bins of each input are built from training rows only: all
   of them up to 500,000, a random sample of 500,000 with a fixed seed above
   (the default of LightGBM is 200,000; with every row, the construction of the
   bins alone needs about 8 GB for version B). Every training row is then
   used in the fit; only the thresholds between which the trees can cut come
   from the sample. Their stability for rare values (flags, ties, the mass of
   missing ranks at zero) is not measured. Every
   setting is written in the script; nothing rests on a default of the
   library. At a maximum depth d, LightGBM and XGBoost can both give binary
   trees of at most 2^d leaves; LightGBM splits the leaf with the best gain,
   XGBoost in its level-wise mode the shallowest nodes. These common bounds
   guarantee neither the same shape nor the same thresholds. When no split is left that improves the fit, LightGBM stops before
   200 trees; the number of trees fitted is recorded.
5. **Robustness model.** Ridge regression: mean squared error plus
   λ times the sum of the squared coefficients, constant not penalised, inputs
   as they are (ranks in [−1, 1], flags 0 or 1), λ in {1e-4, 1e-3, 1e-2, 1e-1,
   1, 10, 100}. Ties broken by the larger λ. A value chosen at the edge of the
   grid is reported; the grid is not extended.
6. **Choice of the values.** The mean over the validation months of the monthly
   mean squared error (already written above), for both models.
7. **What the script may show.** No statistic on the returns of 1993–2025: the
   predictive R² of the test period is a result and belongs to the single
   out-of-sample test. The validation losses are part of it from the return
   year 1994 on, because their window then reaches into 1993–2025 (and lies
   wholly inside it from 2005): compared with the loss of a nearly constant
   forecast, they would give a reader the predictive power of the models in the
   test period. So the values chosen and the validation losses of every year go
   to a separate table, `predictions_<version>_choices_sealed.parquet`, **not
   to be opened before the strategy is frozen**; the report and the screen show
   them for the return year 1993 only (validation on 1981–1992). Any review of
   the settings is decided on that record and on the development years only.
   After the freeze, the report states how often a value was chosen at the edge
   of its grid.
8. **Development of the portfolio and cost code.** On the predictions of
   1981–1992 only (model fitted on 1963–1980), which are not out of sample and
   are never reported as a result: these years chose the values of the model.
   They are in a file of their own; the portfolio and cost code reads that
   file only and must fail on any later year. The rules of costs, portfolio
   and evaluation are frozen before the test file is opened, and the trials
   made on the development years are written down.
9. **Computing time and memory.** Measured with the engine of scikit-learn on
   random numbers of the shape of our data (8 cores): about 1 hour for version
   A and 3 hours for version B with one fit per year; not measured with
   LightGBM before the first run. Version A, which carries the main conclusion
   (D12), is run first. Version B keeps its 5.4 GB of inputs in a temporary
   file, deleted at the end.

**The script and its audit by a separate agent (2026-11-13).**
`scripts/predictions/1_predictions.py` has three modes: `--selftest` (random
numbers only), `--version A --dry-run` (reads and checks the real inputs, fits
nothing), and the real run. **No model has been fitted on the project data.**

The self-test: the two models find a planted relation; the whole procedure is
compared with the same rules written a second time in the plainest way (one new
fit per depth and number of trees, ridge by least squares on an augmented
system): same values chosen, same predictions; changing the targets of year Y
and later, or dropping the later rows, changes no prediction up to Y, and each
of these tests has a counter-test; ridge against scikit-learn (1e-16); leaf
size, depth and learning rate against the numbers of the rules; ties on losses
written by hand. Dry runs of A and B: 3,448,288 eligible stock-months, 3,447,236
with a known target; for 1993, 711,192 training rows and 817,539 validation
rows; for 2025, 2,853,954 and 548,607.

The agent (blank context, read only, forbidden to fit anything on real data;
report: `Workspace/output/2026-11-13_AUDIT_AGENT_predictions.md`) found no
look-ahead: its own reimplementation gives the same predictions on seven
synthetic scenarios, and poisoned targets at the edges of the samples never
reach an earlier prediction. All 32 LightGBM settings are read by the library
(no unknown name), the fit is deterministic, the first k trees of 200 are the
fit of k trees. Its row counts from the panel equal those of the dry run.

| # | Finding of the agent | What was done |
|---|---|---|
| 1 | Blocking for version B: memory. A copy of the whole matrix because 1,052 targets are unknown; the bins built from every training row; checks that copy half of the matrix. Estimated peak 14 to 20 GB for 16 GB installed. | Rows with a known target are placed first when the inputs are read: no copy. Checks column by column. Bins from at most 500,000 training rows (rule 4, changed before any fit). Inputs of version B in a temporary file. |
| 2 | Important: the report showed the validation losses of every year, which from 1994 on are out-of-sample errors inside the test period. | Rule 7 rewritten: these go to a sealed table; only the record of 1993 is shown. |
| 3 | Important: 9 of 20 mutations of the code passed the self-test (a fit on training and validation together, a wrong choice of the values, another learning rate, a tie test that tested nothing). The code itself was right. | The comparison with the plain second version, the tie tests on losses written by hand and the checks against the numbers of the rules were added. |
| 4 | Minor: three neutral LightGBM settings not written; no check of the LightGBM version; no hash of the dictionary; the ridge sums depend on the threads of the linear algebra library at the 17th decimal. | Settings written, version checked, hash added; the last point is noted in the script and the outputs are compared between two runs. |
| 5 | No restart point: a failure in year 30 loses the run. | Not changed (fail closed); version A is short. |

**Lightened audit by Astra (2026-11-13), before any fit.** Report:
`Workspace/output/2026-11-13_AUDIT_ALLEGE_predictions_pour_Claude.md`. Verdict:
"to correct before the first real fit", one blocking finding. Astra fitted
nothing on the real data.

| # | Finding | What was done |
|---|---|---|
| 1 | Blocking: the script could use, in validation or training, a target that rests on a delisting amount not yet known at the date of the fit. Astra's synthetic test: one late target changes the values chosen and the forecasts of both models. | Measured on dates only: 3,952 late targets, 895 known in a later calendar year, 11 known 12 years or more after their month. **Rule D27** (rule 1 above). The self-test holds Astra's test: changing every target not yet known at a fit changes neither the values chosen nor the forecasts up to that year; with the dates removed the same change does move them; a late target does enter a later fit. The comparison with the plain second version covers the rule. |
| 2 | Important: the predictions of the development years and of the test years were in one file; a forgotten filter would expose the test. | Two files (rule 1 and rule 8). |
| 3 | Minor: the time of each year and the number of trees fitted are indirect channels; file metadata can reveal losses. | Both moved to the sealed table; the report keeps the total time; the sealed table is not to be opened, metadata included. The time of each year still appears on the screen during the run. |
| 4 | Minor: the sentence on LightGBM and XGBoost trees "of the same shape" was wrong; the justification "inputs close to uniform" for the bins was wrong. | Both rewritten (rule 4). |
| 5 | The four modelling choices (squared error with equal weights; twelve years kept for the choice of the values; the budget; the bins from 500,000 rows): keep, and state the gaps to GKX, who use a Huber loss for their boosted trees. | Kept. |

**Counter-audit by Astra of the corrected script (2026-11-13).** Report:
`Workspace/output/2026-11-13_AUDIT_ALLEGE_predictions_v2_pour_Claude.md`.
Verdict: "version A can be run", no blocking and no minor finding. D27 lifts
the blocking finding. The ordering by training entry is proved (for a return
year R and a year of knowledge K, max(R, K − 12) ≤ Y − 13 is R ≤ Y − 13 and
K ≤ Y − 1) and checked on 9,240 synthetic rows at the 33 fits. Astra's own test
of one late target now gives the same values chosen and the same forecasts
whether the target is hidden or not, and the old defect when the date is
removed. The 1,285 targets without a date of amount all carry the −30 %
imputation of D3: dating them at their month is defensible if the reason of
the delisting is known then, which the extract cannot show. Not verified: the
dates at which CRSP released its data. **The first fit (version A) was launched
after this report, on the instruction of the project owner.**

Not handled: the vintages upstream that Astra recalls (share factor, monthly
risk-free rate of Ken French in the targets, restated accounts of version B):
already declared limits. The 1,052 unknown targets are predicted and never
used in a fit; training therefore estimates a mean given that the return is
observable, a possible selection that the small share (0.03 %) does not bound.

**What a committee may attack, to state in the report** (finding 5 of the agent):

- the model that predicts year Y is fitted on the returns up to Y − 13; the
  twelve years before Y only choose its values (the GKX design);
- squared error on raw returns, every stock-month with the same weight: small
  stocks weigh on the fit and on the choice of the values (GKX use a Huber loss
  for the trees, to check in the paper); the answer of the project is in the
  portfolio rules (costs, capacity, universe above the NYSE 20th percentile);
- 200 trees at a learning rate of 0.03 is a small capacity: a choice at the
  edge of the grid is likely; it is reported after the freeze and the grid is
  not extended;
- two versions and two models give four sets of forecasts: the main one
  (version A, boosted trees) was named before any fit, and all four are
  reported.
- Portfolio and costs: rules D13 to D23. Alphas against FF5 + momentum, CAPM,
  FF3, FF5, and our own factors (D20).

**Portfolio construction: the candidates of each month** (decided by the
project owner on 2026-11-13, before any result; script
`scripts/portfolio/1_candidates.py`). This step uses the information of month t
only and reads no return. The weights really held are computed by the backtest,
because they depend on the orders that were filled (D13, D21).

1. Two universes (D19): all eligible stocks; eligible stocks at or above the
   NYSE 20th percentile of market equity (size groups small, large, mega).
2. **Top decile of the forecasts, with NYSE breakpoints.** Each month, the 90th
   and 80th percentiles of the forecasts are taken over the eligible NYSE
   stocks of the universe (discrete quantile, as at step 4 of the cleaning). A
   stock is in the top 10 % if its forecast is at or above the 90th percentile,
   in the top 20 % if at or above the 80th. Stocks tied with a breakpoint are
   all in.
3. Why a decile: it is the usual sort of the literature (GKX form decile
   portfolios of their forecasts) and the buffer validated on 2026-11-12 (D21:
   bought in the top 10 %, kept in the top 20 %) already assumes it. The
   threshold is fixed before any result; no other threshold is tried.
4. Why NYSE breakpoints, on theory and literature (the course convention is not
   the argument; references to check before citing). The smallest stocks are
   most of the names and a few per cent of the market value, and the extreme
   forecasts sit among them: with breakpoints over all stocks, the top decile
   would be made of stocks that a fund of USD 100 million cannot hold (order
   cap of D22). Fama and French (2008) find about 60 % of the names for 3 %
   of the market value among the smallest stocks; Hou, Xue and Zhang (2020)
   combine NYSE breakpoints on the sorting variable with value weights. These
   justify a reference universe for the breakpoints. Two limits, after the
   audit by Astra: Avramov, Cheng and Metzker (2023) remove stocks below the
   NYSE 20th percentile of **size**, they do not put NYSE breakpoints on a
   forecast; and GKX sort all stocks on the forecast. The NYSE 90th percentile
   of the forecast is therefore **a choice of the project**, not a rule taken
   from a paper. It does not keep small stocks out: off the NYSE the forecasts
   are more spread, and many small stocks pass the breakpoint (measured below).
   Whether the basket can be held with USD 100 million is not assumed: the
   backtest reports the number of names, the weights in dollars and the
   amounts really filled under the order cap.
5. A stock with no observed characteristic at all cannot start a purchase (D18).
6. Flags for each model and each universe. Before the freeze the script reads
   the development forecasts only; it refuses the test file unless the freeze
   is recorded in `resources/strategy_freeze.json`.

**Audit of the candidates by a separate agent (2026-11-13)** (blank context,
forbidden to open any forecast file; report:
`Workspace/output/2026-11-13_AUDIT_AGENT_portefeuille.md`). No logic error: its
own implementation gives the same flags on ten synthetic data sets, and the
quantile equals the one of the size groups. No blocking finding. Corrected: the
sample must be whole (first and last months, number of months, return years);
the freeze record must hold a date, a declaration and the hash of this script;
the breakpoints and the effect of equal forecasts are written to
`portfolio_breakpoints_<version>_<sample>.parquet`; the self-test checks the
columns passed through, rows in any order and equal forecasts.

Measured on the development years 1981–1992, version A (run `5125549bdd51`;
counts of stocks only, no return):

| Model, universe | Stocks in the top 10 %, median month (min to max) | Share of the universe | NYSE share in the top 10 %, largest month | Distinct forecasts, smallest month | Stocks tied with the breakpoint, largest month |
|---|---|---|---|---|---|
| Trees, all sizes | 1,140 (556 to 2,003) | 20.3 % | 12.5 % | 259 | 162 |
| Trees, large | 192 (136 to 373) | 10.3 % | 18.6 % | 106 | 173 |
| Ridge, all sizes | 1,312 (941 to 1,735) | 23.3 % | 10.1 % | 4,701 | 1 |
| Ridge, large | 230 (161 to 334) | 12.4 % | 10.1 % | 1,682 | 1 |

Two things to read in it. With NYSE breakpoints, the top 10 % holds about a
fifth of the names in the all-sizes universe: stocks off the NYSE have the more
extreme forecasts, as expected, and the value weights and the order cap decide
what they weigh. The trees give equal forecasts: the NYSE share of the top
10 % goes above 11 % in 13 months of 144 (all sizes) and 31 months (large), and
above 15 % in 4 months (large); the top 10 % never equals the top 20 %.

**Lightened audit by Astra (2026-11-13).** Report:
`Workspace/output/2026-11-13_AUDIT_ALLEGE_portefeuille_pour_Claude.md`. Verdict:
"yes to develop the backtest on 1981–1992; the test of 1993–2025 stays closed
until the freeze is really validated and D21 is made consistent on ties".
Astra read the first version of the script and opened no forecast file.

| # | Finding | What was done |
|---|---|---|
| 1 | Blocking for the opening of the test: the freeze file was only checked for its presence, and a file mixing 1992 and 1993 passed. | Already corrected after the agent (date, declaration, hash of this script, checked before the test file is read; whole sample required). Added: every return year is checked against the month after its formation month. The full freeze record (periods, models, universes, rules, costs, comparisons, hashes of code and inputs) is to be written at the freeze step, and each script of the backtest will have its own guard. |
| 2 | Important: the references do not say all that the text made them say. | Point 4 above rewritten: the NYSE breakpoint on a forecast is a choice of the project; small stocks do pass it; capacity is measured, not assumed. |
| 3 | Minor: keep 10 % and 20 %, with no added sensitivity. | Kept. |
| 4 | Important: keep every stock tied with a breakpoint (a PERMNO carries no information); amend D21; log each month the share tied with each breakpoint and the months where the two breakpoints are equal. | Logged in the breakpoint table and in the report. Rule to be confirmed by the project owner (below). |
| 5 | Important: how the flags become orders (below). | To be confirmed by the project owner. |
| 6 | Important, D15: show side by side "after half spread and impact, before commissions" and the result with commissions; the stress schedule is plausible (5 to 6 cents in 2000 according to the chairman of the SEC; Greenwich series: 4.7 cents in 2004, 4.0 in 2005, 2.5 in 2017), cautious from 2005 on. Apply to the absolute number of shares of each fill, at the unadjusted price. | Written in the commission rule below. |

Astra's own test: 100 large NYSE stocks and 300 small stocks off the NYSE with
higher forecasts give 311 candidates of 400, the small stocks weighing 21 % of
the market value of the candidates: the breakpoints alone do not protect, the
weights and the order cap do.

**Still to decide by the project owner, before the backtest is written**
(findings 2 and 4 of the agent; the recommendations of Claude and of Astra
agree):

- equal forecasts: every stock tied with a breakpoint is in, with no cap on
  the number of names and no tie-break; the mention "ties by PERMNO" of D21
  (journal, 8.4) is withdrawn;
- a stock not held is bought if it is in the top 10 % and can start a purchase;
- a stock held is kept while it is in the top 20 %, even with every
  characteristic missing; while they are all missing its position may be
  reduced but not increased. No such stock exists in 1981–1992;
- a stock held that falls below the NYSE 20th percentile (large universe) gets
  a target weight of zero; if it comes back, what is still held is judged on
  the top 20 %, and a new purchase on the top 10 %;
- a stock held that is no longer eligible in t (it has no row) gets a sale
  order;
- a sale that is capped or cannot be filled leaves the rest in the book (D13).

**The six order rules above were validated by the project owner on
2026-11-13.**

**Backtest: execution, costs and alphas** (scripts `scripts/backtest/`,
written on 2026-11-13; rules D13 to D23 of the journal, section 8.4).

- `1_first_day.py` → `first_day_fills.parquet`: for each stock and month,
  whether an order could be filled on the first trading day (trade price,
  positive volume, no delisting). It reads no return. Share of rows where a
  fill is possible: 53 % in the 1970s, 56 % in the 1980s, 85 % in the 1990s,
  94 to 98 % from 2000 (NASDAQ closes were bid-ask midpoints, not trades,
  before the 1990s).
- `2_backtest.py` → `backtest_<version>_<sample>.parquet`: one month at a
  time. Target = value weights over the stocks to hold; order = target minus
  weight held, frozen with the data of t; capped; filled at the close of the
  first trading day of t+1 if a trade was possible; sales first, then
  purchases paid with the cash available and all reduced by one factor if it
  is short; half spread and price impact on each fill; the book held earns the
  first-day return, a position the rest of the month; unknown return of a
  stock held: full write-off; cash earns the risk-free rate; a stock with no
  row the following month has left the panel and its value goes to cash. Ten
  configurations: two models, two universes, first-day or close-to-close
  execution, and the stress cap for the main model.
- `3_alphas.py` → `alphas_<version>.csv`, `summary_<version>.csv` (test sample
  only): CAPM, FF3, FF5 and FF5 with momentum on the Ken French factors,
  Newey-West t-statistics with 6 lags; gross, net, and net with the commission
  stress; sub-periods 1993–2008 and 2009–2025. The factors rebuilt from our
  data (D20) are not done.
- `4_freeze.py` → `resources/strategy_freeze.json`: the freeze, written once,
  with the hash of every script; the three scripts above refuse the test
  sample without it.
- Before the freeze these scripts read the development years only and print
  no return: only turnover, fills, cash and costs.

**Rule D22 amended by the project owner on 2026-11-13, before the freeze: the
order cap is 10 % of the ADV, and 1 % becomes the stress test** (in place of
0.5 %). Reason, measured on the development years 1981–1992 with the main
model, on the mechanics only (no return of the strategy was computed):

| Order cap | Cash, all sizes | Cash, large universe | Costs a month, large universe |
|---|---|---|---|
| 0.5 % of the ADV | 92 % | 85 % | 3 bp |
| 1 % (rule of 2026-11-12) | 85 % | 72 % | 6 bp |
| 5 % | 52 % | 33 % | 28 bp |
| 10 % (new rule) | 33 % | 18 % | 46 bp |
| 25 % | 15 % | 6 % | 75 bp |
| 100 % | 5 % | 1 % | 98 bp |

The simulation trades one day a month: 1 % of the volume of that single day is
about twenty times stricter than 1 % a day over a month, and USD 100 million
is very large against the volumes of the 1980s. At 1 % the main result would
mostly be the return of cash. The cap stays, because without it the simulation
would buy in one day more than the stock trades, and the impact formula of the
course is not made for such orders; at 10 % the size of the order is paid
through that formula. **A reference for 10 % of the daily volume as a
participation limit is still to be found before it is cited.** In the
all-sizes universe a stock of the top 10 % has a median daily volume of
USD 5,636 and a third of the orders cannot be filled on the first day: this
universe stays the main one (D19) and the large universe is shown next to it.

Mechanics of the development years with the new rule (run `058a8eb81b5a`; not
a result): main model, all sizes, 1,426 stocks to hold in the median month,
turnover wanted 125 % a month, 67 % filled, cash 33 %, 25 bp of spread and
22 bp of impact a month; large universe, 284 stocks to hold, 78 % filled, cash
18 %, 23 bp and 23 bp.

**Audit of the backtest by a separate agent (2026-11-13)** (report:
`Workspace/output/2026-11-13_AUDIT_AGENT_backtest.md`). Its own rewriting of
the monthly step gives the same weights, cash and record to 1e-14, on eleven
synthetic scenarios and on the real inputs of 1981–1992; no look-ahead; the
fill table and the half spreads recomputed from the sources with no
difference. No blocking finding. Done before the freeze: the record of each
month now holds the fills by source of spread (D14), the largest write-off
(D16), the proceeds credited before their date (D17), the orders without ADV,
the concentration of the book (largest weight, effective number of stocks)
and the positions above one millionth; the self-test fixes the cap, the
commission schedule after 2004, the funding of purchases with a price impact
and a missing price; the header of the script states the limits (NASDAQ
closes, fallbacks, gross return, risk-free rate).

Measured on 1981–1992 (run `62a277336c30`; mechanics, not a result): in the
all-sizes universe the largest weight reaches 32 % of the fund and the book
is worth about 51 stocks of equal weight (48 in the large universe, 106 for
the ridge); 91 % of the amounts filled pay a high-low spread and 9 % a quoted
one; a third of the orders cannot be filled on the first day.

**To decide by the project owner before the freeze** (findings of the agent):

- concentration: value weights let one stock weigh up to a third of the fund.
  Keep them and report the concentration, or use capped value weights
  (`me_cap`, the weighting of Jensen, Kelly and Pedersen), or show both;
- NASDAQ: the rule "a closing trade price" makes NASDAQ stocks impossible to
  trade before the 1990s (0 % of them until October 1982, 46 % until mid-1992).
  Kept as the letter of D13 unless decided otherwise;
- the exposure of the fund varies in time (cash 55 % in 1981, 18 % in 1990;
  projected on the inputs alone: 73 % of the capital can be placed in a day in
  1993, 99 % after 2007), so that a regression with constant betas is
  misspecified at the start of the test; the sub-periods are the answer
  planned so far.

**Lightened audit by Astra of the backtest, the alphas and the freeze
(2026-11-13).** Report:
`Workspace/output/2026-11-13_AUDIT_ALLEGE_backtest_alphas_pour_Claude.md`.
Verdict: "no to the freeze as it stands". The estimation of the alpha passes
Astra's synthetic checks (months, risk-free rate, factor columns, Newey-West
with Bartlett weights and 6 lags); the freeze did not protect the single test.
Astra opened no test or sealed file and computed no statistic of return.

| # | Finding | What was done |
|---|---|---|
| 1 | Blocking: the guards checked only the script that runs. Changed utilities, other factors, or candidates made under another freeze could reach an unchanged reader; a second run could overwrite the first result; the freeze record could be replaced. | `scripts/backtest/freeze_guard.py`, called by the three scripts before any read of the test sample: the code (five scripts, the guard, the shared utilities), the inputs (panel, daily summaries, first-day fills, factors, ranks) and the forecasts must have the SHA-256 recorded at the freeze; the forecasts must come from the frozen prediction script; an upstream result must carry the same freeze identifier; a result that exists is never overwritten; every opening is logged before the first read. The record is created once (exclusive creation) and is to be committed and tagged. Tested on fifteen cases in a temporary folder. A direct read of a parquet file remains possible: it is a rule of conduct, written in the record. |
| 2 | Version B after version A: acceptable only if B is committed before A is seen. | Written in the frozen rules: B is a complement, run later through the same frozen scripts, on forecasts that must come from the frozen prediction script; its forecasts are fixed at their first opening; no rule is reopened after A. |
| 3 | Important: a month replaced by a copy of another one still gave "396 months" in the alpha script. | The script now requires the exact calendar for every configuration and period, the ten expected configurations, finite values and regressors of full rank. |
| 4 | Important: the share of the fund invested varies in time, so a regression with constant betas is misspecified; the Newey-West estimator does not correct it; two sub-periods leave the exposure moving inside each. | One conditional diagnostic, fixed before the freeze (Ferson and Schadt 1996): for the main configuration on 1993–2025, the six factors and their products with the share invested at the previous month end, centred on its mean. The alpha of the whole fund against FF5 and momentum stays the main result. The return is not divided by the invested share. |
| 5 | Important: nothing validates a fill of 10 % of the daily volume at the last trade of each stock; the fill is tested on the presence of a volume, not on its size. | The cap of 10 % is named a capacity scenario in the frozen rules and in the script, with the result at 1 % next to it. Not done: capping the fill by the volume really traded that day. |
| 6 | Important: CRSP reports closing trade prices of the NASDAQ National Market from November 1982 and of the SmallCap Market from June 1992; "before the 1990s" was too broad. Keep the rule (trade price, volume, no delisting). | Wording corrected; rule kept. The amounts wanted and not filled are in the record of each month. |
| 7 | Important: keep the value weights already announced; show the largest weight, its share of the invested part and the effective number of stocks. | Kept; the three numbers are in the record and in the summary table. |
| 8 | To publish next to the main result: cash and capped orders by sub-period; the two universes; the result "after spread and impact, before commissions" and the commission stress; the share of the amounts filled and the cost in basis points by source of spread. | In the summary table (`summary_<version>.csv`). |
| 9 | Complete the list of frozen rules; keep the versions of the libraries; say that the simulator does produce returns on the development years and that the alpha script computes its statistics there without showing them. | Done in `4_freeze.py`. Rule D20 (factors rebuilt from our data) is recorded as postponed. |

**Counter-audit by Astra of these corrections (2026-11-13).** Report:
`Workspace/output/2026-11-13_AUDIT_ALLEGE_gel_v2_pour_Claude.md`. Verdict: "no
as it stands", on the procedure only: the calendar, the computation of the
alpha, the conditional diagnostic, the list of frozen rules and the four
choices left aside (the fill is not capped by the volume of the day; D20
postponed; no bid-ask variant for the NASDAQ; no cap on a weight) are accepted.
Two blocking findings, shown on fake files, and their corrections:

- two runs could obtain the same step, and the second publication replaced the
  first. Now each step of each version is reserved by the exclusive creation of
  a file in `resources/test_steps/` before anything is read; a completed step
  is never run again, even if its output has disappeared; a step whose attempt
  did not finish needs `--retry`, and the new attempt is numbered and recorded;
  at the end of a step the SHA-256 of every output, report included, is written
  in the file of the attempt;
- the hash that was checked was not the hash of the bytes read. Now the test
  forecasts and the results of earlier steps are read by `read_frozen`: the
  bytes decoded are the bytes hashed, against the hash of the freeze (forecasts)
  or the one recorded at the end of the producing step (candidates, backtest);
  the freeze record itself is hashed again when the step is reserved.

Also done: the reports are among the outputs that must not exist; the list of
signals is among the files checked; `2_backtest.load` refuses the test sample
without the hash given by the guard; version B is committed before A is seen
(its report must show the frozen prediction script and the same inputs,
settings and calendar as the report of version A, recorded in the freeze); two
precisions in the frozen rules (the impact is charged on the amount really
filled; the fallback of the spread also applies to a group without donor). The
guard is tested on 25 cases in a temporary folder. Known limit: `--retry`
passed while a first run is still going lets a second run start; both are
recorded, and a step with two completed attempts is refused downstream.

**Commissions on 1993–2025: rule D15 amended by the project owner on
2026-11-13, before any result.** The commission series of Jones (2002) is not a
published data file and ends in 2000: it cannot cover the test period. No clean
series was found for 1993–2025, only scattered figures for institutional
investors, in cents per share (to check before citing: about 6.3 then 5.6 cents
from 1993 to 1997 and 5 to 6 cents around 2004, Greenwich Associates and a
study of institutional orders; in the mid-2010s about 3.7 cents with a
traditional broker and 1 to 1.7 cents by algorithm).

- **Main result: no commission added to the half spread (D14) and to the price
  impact (D22).** These two costs are measured in our data or taken from a
  stated formula; on this period the spread is the dominant explicit cost, and
  studies of trading costs of anomalies work with the spread alone (Novy-Marx
  and Velikov 2016, to check).
- **One stress test, shown next to the main result whatever it gives: a
  commission in cents per share**, 6 cents until 2004 and 4 cents from 2005,
  on every share bought or sold, converted with the price of the trade (a
  stock at USD 5 pays ten times the rate of a stock at USD 50). The schedule is
  fixed here, before any result; it is cautious for a fund that trades by
  algorithm.
- The two results are shown side by side: "after half spread and price
  impact, before commissions", and "with commissions". The spread is an
  implicit cost and the commission an explicit one (Jones 2002 keeps them
  apart). The stress does not change the path of the portfolio: it is taken
  off the net return of each month. The commission is the absolute number of shares of each purchase and
  each sale filled, times USD 0.06 or 0.04, the number of shares being the
  amount traded over the unadjusted price of the fill.
- Sources of the schedule (read by Astra): about 5 to 6 cents with a traditional
  broker in 2000 (chairman of the SEC); Greenwich series, 4.7 cents in 2004,
  4.0 in 2005, 2.5 in 2017. The stress is at the average in 2005 and well above
  it later.
- The reservation "commissions are not in the main number" is thus a number in
  the tables, not a warning (requirement of section 8.4 of the journal).

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
2. **The models: decided on 2026-11-13, before any estimation.** The aim is to
   look for alpha as realistically as possible, not to compare machine learning
   with econometric models (the committee does not ask for that comparison).
   - **Main model: gradient-boosted trees.** The conclusion of the project is
     read on this model, named before the first fit.
   - **Robustness model: a linear regression with a penalty.** It is of a
     different nature (no interaction, no threshold) and is reported whatever it
     gives: if both models agree, the result does not rest on the choice of the
     model; if they do not, the report says so.
   - **Target: the excess return of the next month, as it is** (`ret_exc_lead1`),
     the target of GKX. A direction target (up or down) was considered and
     rejected: it drops the size of the return and keeps a sign that is as
     noisy, it mostly follows the market, and the forecast is only used to order
     the stocks of a month.
   - Neural networks, first in GKX, are left out: a fit that depends on the
     seed and on many choices of architecture cannot be audited in the time
     available. A random forest was considered instead of boosting and not
     added to it: its forecasts would be close to those of the boosted trees,
     for one more trial.
   - The signed equal-weight score below is no longer planned: its only purpose
     was a comparison that the project does not need.

   Why these two (the references are to be checked in the papers before they
   are cited). Data: a very weak signal in monthly stock returns, 388 inputs
   that are strongly correlated, missing values that carry information.
   Penalised linear regression: with a weak signal the variance matters more
   than the bias, and a ridge penalty shares the weight between correlated
   inputs; unique solution, no seed (Lewellen 2015; Kozak, Nagel and Santosh
   2020). Boosted trees of low depth: invariant to monotone transformations,
   hence consistent with ranks; they use interactions of low order, for
   instance between a missing flag and another characteristic (GKX 2020, where
   trees come just after neural networks). The objection to expect: the gains of
   non-linear models are concentrated in small and hard-to-trade stocks and
   shrink with costs (Avramov, Cheng and Metzker 2023); the rules D13 to D23
   (costs, capacity, universe above the NYSE 20th percentile) are the answer.

   Former text, kept for the record. The equal-weight average of ranks needs a sign
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
