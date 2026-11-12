# Signal specification

Version 0.1, 2026-11-12. Status: **list and plan written, nothing built yet.**
To be audited by Astra before any signal is computed.

## 1. Where the signals come from

Two sources only, so that nothing is arbitrary:

- **The adviser's brief** (an industry adviser consulted by the project owner): select stocks with several families
  of signals (momentum, value, quality, earnings revisions, volatility, possibly
  alternative data); compare a traditional multi-factor model with machine
  learning (boosted trees, neural networks); control sector and factor
  exposures; judge out of sample, after trading costs.
- **The literature.** Jensen, Kelly and Pedersen (2023, JKP) is a census of the
  published signals, with public code (local clone, commit `b5695ea`). Gu,
  Kelly and Xiu (2020, GKX) is the reference for return prediction with machine
  learning from such a list of characteristics.

## 2. Selection rule

**A JKP characteristic is kept if and only if every input of its JKP formula
exists in our cleaned tables.** The only criterion is data availability. No
characteristic is kept or dropped because of what it is expected to earn, and
the list was fixed before any signal or return was computed.

Precisions:

- When JKP writes a fallback chain (`coalesce`), the first choice must be in our
  tables, or the fallback we use must be a Compustat identity (`xopr` = `cogs`
  + `xsga`; `gp` = `sale` − `cogs`; `ebitda` = `oibdp`).
- A characteristic is **not** kept when JKP would replace an item we do not
  have by zero (`coalesce(x, 0)` with `x` absent from our extract): an item that
  is not in our data is not a zero. This removes everything built on `xrd`,
  `ivao`, `ivst`, `intan`, and so `op_x`, `ncoa_x`, accruals, cash flows.
- A characteristic is not kept when only a non-identity fallback is available
  (`bev_x` without `icapt` and `mib`; net debt issuance from balance-sheet
  changes).

The rule is applied by `scripts/signals/0_signal_list.py`, which stops if a
name is not a JKP characteristic, has no JKP theme, or needs a column that our
tables do not have. Output: `resources/signal_list.csv`.

## 3. The list: 176 of the 404 JKP characteristics

| JKP theme | Version A (price) | Version B adds (accounting) | In JKP |
|---|---|---|---|
| Momentum | 13 | 0 | 16 |
| Short-term reversal | 1 | 0 | 1 |
| Long-term reversal | 12 | 0 | 12 |
| Seasonality | 5 | 0 | 5 |
| Low risk | 3 | 2 | 29 |
| Size | 4 | 5 | 18 |
| Issuance | 4 | 14 | 65 |
| Value | 0 | 13 | 32 |
| Profitability | 0 | 15 | 41 |
| Fundamental momentum | 0 | 16 | 32 |
| Investment | 0 | 37 | 72 |
| Financial strength | 0 | 27 | 41 |
| Operating efficiency | 0 | 4 | 20 |
| Earnings quality | 0 | 1 | 10 |
| Intangibles, Quality | 0 | 0 | 8 |
| **Total** | **42** | **134** | 404 |

- **Version A (rule D12)** = the 42 characteristics with no accounting input:
  the 21 momentum and reversal returns `ret_j_i`, the 10 seasonality returns,
  `eqnpo_1m` to `eqnpo_12m`, `market_equity`, `prc`, `rvol_21d`, `rvol_252d`,
  `beta_252d`, `dolvol_126d`, `bidaskhl_21d`.
- **Version B** = version A plus the 134 accounting characteristics.

Mapping to the adviser's families: momentum → Momentum, reversals, Seasonality;
volatility → Low risk; value → Value; quality → Profitability, Investment,
Fundamental momentum, Financial strength, Operating efficiency, Issuance,
Earnings quality. Size and liquidity characteristics are in JKP and in GKX.

**Families we cannot build, to state in the report:**

- **earnings revisions**: they need analyst forecasts (I/B/E/S), not in our
  collection. No substitute is used;
- **alternative data**: none in the project;
- most of **Low risk** and trading characteristics (idiosyncratic volatility,
  skewness, Amihud, turnover, zero-trade days): step 9 was reduced (D11);
- accruals, cash flows, R&D, quality composites (QMJ, F-score, O-score,
  Z-score): our Compustat extract has 21 items, without depreciation, R&D,
  cash-flow items, inventories or receivables;
- quarterly characteristics: we only have the annual file;
- `age`: JKP uses Compustat dates before the listing, absent from our extract;
- `chcsho_*`: needs the monthly cumulative share factor, absent from the
  monthly table (the daily table has it; adding it is a possible extension, to
  be decided before the build);
- `div*_me`: needs `div_tot` (D-step 1: no `MthCumFacShr`);
- residual momentum and `prc_highprc_252d`: not computed at step 9.

## 4. Construction plan

Rule: each script copies the JKP function named in `signal_list.csv`, cites it,
and justifies every deviation. Same standards as the cleaning: verified reads
(`utils.read_verified`), fail closed, atomic outputs, JSON report with run id
and hashes, explicit sort before any order-sensitive computation.

| Script | Output | Content |
|---|---|---|
| `0_signal_list.py` | `resources/signal_list.csv` | The list and its checks (done). |
| `1_price_signals.py` | `signals_price.parquet`, key `permno`–`eom` | The 37 monthly price characteristics, plus the 5 of step 9 read from `crsp_daily_agg`. |
| `2_accounting_signals.py` | `signals_acc.parquet`, key `gvkey`–`datadate` | Helper variables and the accounting characteristics that need no market value. |
| `3_signal_panel.py` | `signal_panel.parquet` (raw values) and `signal_ranks.parquet` (ranks), key `permno`–`eom` | Join at the formation date, market-scaled characteristics, ranks and missing flags. |

**`1_price_signals.py`** (JKP `market_chars_monthly`, `mom_rev_cols`,
`seasonality`, `eqnpo_cols`):

- complete monthly grid per `permno` from its first to its last month (JKP
  `expand`); `count` = position in this grid;
- `ret_x` = `ret` where `ret_signal_ok` is true, missing otherwise (our mask
  replaces JKP's `ret_miss`; it is applied on the source row, before any shift);
- return index `ri_x` = cumulative product of `1 + coalesce(ret_x, 0)`;
- `ret_j_i` = `ri_x(t−i) / ri_x(t−j) − 1` if `ri_x(t−j) ≠ 0`, `count > j` and
  `ret_x(t−i)` is known (JKP conditions copied);
- seasonality: JKP sums of shifted returns, `count ≥ 12 × end year`;
- `eqnpo_lag` = `ln(ri / ri_lag) − ln(me / me_lag)`, absolute values below
  1e-5 set to 0 (JKP);
- `market_equity` = `me`, `prc` = absolute price of the month.

**`2_accounting_signals.py`** (JKP `add_helper_vars`, `var_growth`,
`chg_to_assets`, `safe_div` and its modes, `add_accounting_misc_cols_1`,
`financial_soundness_and_misc_ratios_exps`, `add_liq_and_efficiency_ratios`,
`add_profit_scaled_by_lagged_vars`, `compute_capex_abn`, `chg_to_exp`,
`chg_var1_to_var2`, `vola`, earnings persistence):

- complete monthly grid per `gvkey` between its first and last `datadate`; a
  12-month change compares two dates 12 months apart, never two neighbouring
  rows, and needs `count > 12` (JKP);
- helper variables with the JKP names (`sale_x`, `debt_x`, `gp_x`, `ebitda_x`,
  `ope_x`, ...); `be_x`, `seq_x`, `pstk_x` are read from step 7;
- every division goes through the JKP guard of the same mode (zero or negative
  denominator → missing).

**`3_signal_panel.py`** (JKP `add_me_data_and_compute_me_mev_mat_eqdur_vars`;
GKX for the ranks):

- left join of the accounting characteristics on `(gvkey, acc_datadate)` of
  `crsp_panel_acc` (availability rule D4, already tested at step 8);
- market value of the **company** at t: `me_company`, only when
  `me_company_complete` is true; `mev = me_company + netdebt_x`, missing if
  ≤ 0; `x_me` and `x_mev` as in JKP (`scale_me`, `scale_mev`);
- secondary share classes and stocks without accounts yet keep missing
  accounting characteristics (D5, D18);
- ranks: within each month, over the stocks with `eligible` true, each
  characteristic is ranked and scaled to [−1, 1]; a missing value becomes 0
  **after** ranking, with one missing flag per characteristic (D18; GKX). Raw
  values are kept in a separate file and never filled.

**Checks that stop the scripts:**

1. the columns built are exactly the names of `signal_list.csv`;
2. **truncation test**: hide every row after a date T, rebuild, and the signals
   up to T must be identical (three dates);
3. **delisting test**: change the delisting returns and the returns after t;
   no signal at t may change, including the signals of other stocks;
4. no column with availability `t+1` or `after_t` in the data dictionary is
   read;
5. hand-written reference cases for one characteristic of each JKP function,
   and a second writing for `ret_12_1` (direct product of monthly returns) and
   `be_me`;
6. negative tests: a 5-month accounting lag and a shift of one month in the
   momentum window must be caught;
7. coverage by characteristic and by decade among eligible stocks, published in
   the report;
8. the data dictionary is extended to the new tables and checked.

## 5. Method to look for alpha (to be frozen with the model step)

Following GKX, as the adviser describes:

- target: `ret_exc_lead1`; inputs: the ranks of version A, then of version B;
- models: (1) equal-weight average of the ranks, signed by the JKP direction
  of each characteristic (no estimation); (2) linear regression with a
  penalty; (3) gradient-boosted trees. A neural network is optional;
- sample split in GKX proportions (18 years of training, 12 of validation, the
  rest for the test): training 1963–1980, validation 1981–1992, **test
  1993–2025**, with a yearly re-estimation on expanding data. The test period
  is the sub-period of rule D23;
- portfolio and costs: rules D13 to D23; alphas against CAPM, FF3, FF5 and our
  own factors (D20).

## 6. Open points (to decide before the build or the model)

1. Sector neutrality asked by the adviser: ranks inside each industry, or an
   industry constraint at the portfolio step. Industry grid (D8) still open.
2. `chcsho_*`: add the month-end share factor from the daily table, or leave
   these four characteristics out.
3. The sign of each characteristic for model (1): the JKP file `themes.csv`
   gives a direction; it comes from the literature, not from our data.
4. Whether the two reference signals (`ret_12_1`, `be_me`) may be compared
   with the Ken French momentum and HML factors as a construction check before
   the freeze.
5. Sources to verify before citing: GKX (2020), Green, Hand and Zhang (2017),
   Freyberger, Neuhierl and Weber (2020), Avramov, Cheng and Metzker (2023).
   No reference paper on machine learning for **long-only** US portfolios was
   confirmed.
