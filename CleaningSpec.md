# Data cleaning and preparation specification

Version 0.1, 2026-11-11. Validated by Danny, audited by ChatGPT ("Astra").

## Reference sources

- **JKP**: Jensen, Kelly and Pedersen (2023), *Is There a Replication Crisis in
  Finance?*, JF. Python code `github.com/bkelly-lab/jkp-data`, files
  `src/jkp/data/main.py`, `config.py` and `aux_functions.py`. The pipeline reads
  the **CIZ** format, like our files.
- **TF**: Tidy Finance with Python, chapters `wrds-crsp-and-compustat`,
  `value-and-bivariate-sorts` and `replicating-fama-and-french-factors` (source:
  `github.com/tidy-finance/website/chapters`). These chapters also read the
  **CIZ** format.
- **Course**: Goyal's slides, lectures 1 (Strategies) and 3 (Trading costs).

General rule: **JKP for rigour** of the definitions, **TF for simplicity** of the
implementation, and **the course wins** in case of conflict. Every deviation is
justified below.

Results quoted inside a step are those of the date given in that step. When a
later audit changed a figure, the "Corrections" paragraph of the step and the
section "Final audit" at the end give the current one.

## Profile of our raw files (checked on 2026-11-11)

| Finding | Consequence |
|---|---|
| `crsp_ciz_security_history.csv` does **not have `conditionaltype`**. JKP and TF use this field to isolate regular trading. | A substitute is needed (see step 3). |
| The intervals from `secinfostartdt` to `secinfoenddt` do not overlap and have no gap (191,048 rows, 40,518 PERMNOs). | The join by date interval is safe. |
| For **23,114 delistings out of 29,528**, the information interval ends before the end of the delisting month. The delisting month then falls on a row where `primaryexch = 'X'`. | The TF join as it is **would drop the delisting month**, which brings back a survivorship bias (see step 3). |
| The file also has funds (`FUND`, `ETF`, `CEF`), ADRs (`AD`), REITs and securities not incorporated in the US (47,421 rows with `usincflg = N`). | They are filtered at step 3. |
| The Compustat file is already filtered: `INDL`, `STD`, `C` and `D` everywhere. It has 5,388 rows in CAD and 15 without a currency. | Only USD rows are kept (step 7). |
| The Compustat file has **2,933 gvkey-datadate duplicates**. It is a CCM extract with `LPERMNO`, so probably one row per linked PERMNO. | The table must be deduplicated (step 7). |
| In the link table, `LINKENDDT = 'E'` means a link that is still open. | This code is treated as an infinite date. |
| The monthly CRSP file has one row per distribution event. Price, return, market cap and volume are always identical within a month. | The panel is deduplicated and the distributions go to a separate table (step 1). |

## Conventions for all steps

- **Outputs**: Parquet files in `data/processed/`, written atomically. Each table
  has a JSON check report saved next to it, with the key figures and the list of
  rejected cases.
- **Native units are kept** and documented in a data dictionary. Only exception:
  market equity `me` is in **USD millions** (`MthCap / 1000`), as in JKP and TF.
- **Time key**: `eom`, the calendar month end. `MthCalDt` is kept as it is.
- **Cleaned data keep the full history.** The analysis sample (1963-2025) is
  chosen later.
- **Missing stays missing.** No filling and no imputation, with these documented
  exceptions: the −30 % delisting return of step 2 (D3); the JKP book-equity
  formula of step 7, where a missing preferred stock or deferred tax counts as
  zero inside the formula only; the high-low spread of step 9, where JKP carries
  the last valid range forward. Shares are converted from thousands to millions
  (`shrout`), market equity from thousands to millions of USD (`me`).
- **Fail on any anomaly.** An unexpected schema, key or range of values stops
  the script. Unusual values are flagged, not removed.

## Steps

### Steps 1 and 2: monthly CRSP panel and delistings — **implemented**

Script `scripts/data_cleaning/1_crsp_monthly.py`, version 2, corrected after the
Astra audit of 2026-11-11. Outputs:
- `crsp_monthly.parquet`;
- `crsp_distributions.parquet`;
- `crsp_d9_reconciliation.csv`;
- `crsp_monthly_report.json`, written last, with the run id and the SHA-256 of
  the inputs and outputs.

**Code reused**:
- JKP `gen_crsp_sf`: choice of columns, `bidask` flag (BA → 1, TR → 0), `shrout`
  in millions.
- JKP `prepare_crsp_sf`, monthly branch:
  - join of the delistings on `(permno, month)`;
  - imputation of −30 % for performance delistings without a return (CIZ codes
    c2 and c3);
  - compounding `(1+ret)(1+delret)−1` unless `MthDelFlg ∈ {A, P, V}`;
  - computation of `me_company`.
- TF: `me = 0` becomes missing, and `me_lag1` comes from a join shifted by one
  month (missing if there is a gap).

**Total return `ret` and its column `ret_status`**:
- `crsp`: `MthRet` as it is (months N, A, P and V);
- `crsp_plus_delret` / `crsp_plus_delret_imputed`: month M or G compounded with
  `delret`, observed or imputed at −30 %;
- `daily_plus_delret` / `daily_plus_delret_imputed`: month added by D9;
- `missing_*`: a part of the return is unknown, so `ret` is missing, with the
  reason:
  - `missing_crsp`: `MthRet` is missing;
  - `missing_pre_delisting`: the part before the delisting is unknown;
  - `missing_delret`: the delisting return is unknown;
  - `missing_delist_record`: no delisting record (before 1950).
- `ret_crsp` always keeps the raw `MthRet`, and `delret_raw` the raw `delret`.

**Availability of delisting amounts.** The delisting return is assigned to the
delisting month: it is the holding return of the position, following the CRSP
and JKP convention. It can rest on an amount known later (`delamtdt`,
`delnextdt` are kept), for example 537 of the 547 G cases. The stock leaves the
universe at its delisting, so this return cannot reach a signal **through its
own stock** (checked at step 3 since the final audit). It could still reach one
through another security (a signal on another share class of the company, or an
industry aggregate): the mask `ret_signal_ok` must be applied to the source rows
(see "Counter-audit"). How the backtest funds proceeds that arrive later is an
open decision (see "Rules proposed before the backtest").

**Deviations justified by our data**:
- **`me = MthCap / 1000`** instead of `prc × shrout` (JKP). In 180 rows, the last
  price is older than the current number of shares, and only `MthCap` uses the
  shares at the price date. The check confirms that **all** gaps come from this
  case or from rounding.
- **Volume in shares.** JKP multiplies the monthly volume by 100, but in our
  export `MthVol` is exactly the sum of `DlyVol`. The NASDAQ volume adjustment
  and the dollar volume move to step 3, because they need the exchange.
- **No `div_tot`**, because `MthCumFacShr` is not in the export. Dividends stay
  in the distributions table.
- **274 delisting months added (D9).** These stocks delist in the month after
  their last CRSP row, with no row for that month, and the JKP join loses their
  delisting return.
  - A row is added with `date = delistingdt` and `delist_row_added = True`.
  - Its return is `(1 + r_before)(1 + delret) − 1`, where `r_before` compounds
    the daily returns with `DlyDelFlg = N` between the last monthly date and the
    delisting date. The daily row `Y`, which carries the delisting return, is
    left out of this product.
  - CRSP bridges the days without a price: on our data, this product matches
    `MthRet` in 99 % of the 1,062 comparable months that have such days.
  - **Break**: a day with a price but no return means that CRSP did not link
    this price to the previous one. The chain is cut, the part before the
    delisting is unknown, and `ret` stays missing (`pre_delist_break`).
  - With no usable daily return, `ret` stays missing too.
  - Daily rows repeated identically are deduplicated. Two different rows for
    the same day stop the script.
  - If several parts are missing at once, `ret_status` gives priority to the
    part before the delisting. The report counts these overlaps.
- **No `ret = 0` (D10).** JKP replaces a missing return by 0 when `delret`
  exists, and a missing `delret` by 0 for delistings not linked to performance.
  Here, if a part of the holding return is unknown, `ret` stays missing and
  `ret_status` says why: a missing value is not zero.
- Months N, A, P and V keep `ret` **exactly** equal to `MthRet`, which a check
  verifies.
- The header CUSIP is renamed `hdr_cusip`. The historical CUSIP comes from the
  security history, at step 3.
- `me_company` is dated at the month end. `me_company_complete` says whether all
  share classes of the company have a market equity that month (1,393 partial
  company-months).

**Check results** (JSON report of version 3, after the Astra counter-review):
- 5,276,434 raw rows give 5,210,620 stock-months, plus 274 added delisting
  months, for 40,437 stocks from 1930-01 to 2025-12;
- stock-level fields are never in conflict; keys, dates and flags are never
  null; numbers are finite; prices and shares are positive;
- 1,089,403 distribution events, without conflict;
- the 29,509 delistings of the stocks present are all linked to a month, and
  none falls on an N month;
- **reverse check**: 236 months have a delisting flag without a record, all in
  1949 or before, because the delisting file starts on 1950-05-06. The A and P
  cases are complete; the 102 M and G cases have a missing return (98
  `missing_delist_record` and 4 `missing_pre_delisting`, which have no record
  either);
- D9: 244 returns rebuilt (197 with an observed `delret`, 47 imputed) and 30
  missing, of which 29 trading breaks: the 18 cases of the counter-review and 11
  others of the same kind;
- audit reference cases found again: PERMNO 65788 at −22.73 % and 12964 at
  −79.82 %;
- 2,900 imputations at −30 %;
- 83,884 final returns missing, of which 83,409 with status `missing_crsp`;
- the value-weighted return of all stocks follows `vwretd` with a correlation
  of 0.99978 over 1,151 months;
- 732 returns exceed +300 %: they are flagged, not removed.

**Deferred to later steps** (reservations of the counter-review, no effect on
the panel):
- **Funding of late delisting proceeds**, reservation on finding 4. The scenario
  written on 2026-11-11 (proceeds of a G delisting reinvested only from
  `delamtdt`, a receivable in between) is no longer a rule: it is one of the
  three scenarios of the open decision B3 (see "Rules proposed before the
  backtest").
- **Safe reading**, reservation on finding 10: every script that reads these
  outputs first checks their SHA-256 against `crsp_monthly_report.json`.

**Status: steps 1 and 2 closed on 2026-11-11.** Astra counter-review handled; no
blocking finding open.

### Step 3: eligible universe (`eligible` in the panel)

**Based on**: TF and JKP filters, with one adaptation on the time at which
eligibility is judged.

TF filters reused:
- `sharetype = 'NS'`;
- `securitytype = 'EQTY'`;
- `securitysubtype = 'COM'`;
- `issuertype ∈ {ACOR, CORP}`;
- `primaryexch ∈ {N, A, Q}`;
- `tradingstatusflg = 'A'`;
- `usincflg = 'Y'`. JKP does not apply this last filter. **Decision D1.**

The field `conditionaltype ∈ {RW, NW}` is **absent** from our export. It is
replaced by `tradingstatusflg = 'A'` and `primaryexch ∈ {N, A, Q}`, and this
limit is documented. **Decision D2.** Alternative: export the security history
again from WRDS.

**Key adaptation.** Eligibility is judged **at the formation date**, the end of
month t, from the information valid at `MthCalDt` of month t. The return of
month t+1 is then **always kept**, whatever the status of the stock in t+1. This
avoids both look-ahead and the loss of the delisting month: JKP and TF filter in
the same month, which would lose 23,114 delisting months here.

The historical SIC code `siccd` is taken from the security history (TF).

**Implementation: `scripts/data_cleaning/3_crsp_universe.py`** (2026-11-11).
Outputs: `crsp_universe.parquet`, the whole panel with the flags, and
`crsp_universe_report.json`.

- **Safe reading**: `crsp_monthly.parquet` is read only if its SHA-256 matches
  the step 1 report (`utils.read_verified`).
- **Join** (JKP `gen_crsp_sf`): the security-history interval valid at `date` is
  used (`secinfostartdt ≤ date ≤ secinfoenddt`). Intervals never overlap, which
  is checked.
- **Flags**:
  - `common` (JKP): `EQTY`, `COM`, `NS` and `issuertype ∈ {ACOR, CORP}`;
  - `exch_main`: `primaryexch ∈ {N, A, Q}` and `tradingstatusflg = 'A'` (D2);
  - `us_inc`: `usincflg = 'Y'` (D1);
  - `eligible`: `common`, `exch_main` and `us_inc`, with `me` known and **no
    delisting in the month** (`MthDelFlg = 'N'`), because a stock delisted
    during month t cannot be bought at the end of t;
  - `crsp_nyse`: eligible and `primaryexch = 'N'`, for the NYSE breakpoints of
    step 4.
- **`ret_lead1`**: total return of the row of month t+1 (`ret` and `ret_status`
  of steps 1 and 2), if this row exists. The status of the stock in t+1 is not
  used.
- **Volume** (JKP): Gao-Ritter NASDAQ volume adjustment (`adj_trd_vol_NASDAQ`,
  copied as it is) and `dolvol = |prc| × vol_adj` in USD, without JKP's ×100.
- **Industries** (JKP `crsp_industry`, `_parse_siccodes_file`): `sic = 0`
  becomes missing, and `ff49` comes from `resources/Siccodes49.txt`, copied from
  JKP.
- **Historical CUSIP**: `cusip` comes from the security history, at the row
  date. `hdr_cusip` stays the header CUSIP.

**Check results**:
- **22,341 rows without security information**, all delisting months (flags A,
  P, M, G and V): the security history stops at the delisting date, before the
  month end. The script fails if an N month has no information;
- **3,805,426 eligible stock-months**. Since 1963: between 1,963 and 7,462
  stocks per month (4,563 on average, about 80 % of the stock count of the CRSP
  index), and at least 1,139 NYSE stocks per month;
- effect of the filters since 1963, on 4,844,588 rows: `common` keeps
  3,782,727, then `exch_main` 3,717,129, then `us_inc` 3,466,247, and finally
  known `me` and no delisting in the month 3,449,977;
- **25,481 t+1 rows kept** while the stock is no longer eligible in t+1, of
  which 24,235 have a numeric return. Among the positions eligible in t,
  **22,948** have a delisting month in t+1, of which 22,673 with a numeric
  return: these are the returns that a same-month filter would have lost. The
  count uses the delisting flag of t+1; version 1 of the report counted only M,
  G and D9, that is 3,322;
- t+1 missing for an eligible stock: 3,659 "no next row", all in 2025-12 except
  2 cases in 1930-32. Add 1,036 `missing_crsp` and 275 unknown delisting
  returns. Their weight will be reported in the backtest;
- the value-weighted t+1 return of the stocks eligible in t follows `vwretd`
  with a correlation of 0.99869 over 756 months since 1963 (+0.03 % per month on
  average: the index also holds funds, ADRs and REITs);
- `ff49` is missing on 2.5 % of the eligible rows: SIC code missing or outside
  the FF49 list, as in JKP.

**Corrections after the Astra audit of step 3** (2026-11-11):
- **NASDAQ volume in delisting months**, finding 1. The Gao-Ritter adjustment
  takes the exchange at the date if the stock is active there. Otherwise it
  takes the exchange of the **last active interval**, where the volume was
  traded: 9,043 rows corrected. Check case: PERMNO 10003 in 1995-12 gives
  `vol_adj` = 73,190.5. Regime changes inside a month are not split day by day,
  a documented limit. These rows are all ineligible in t, so no return is
  affected.
- **Counters**, finding 2: corrected, see above.
- **`eligible` is a universe filter**, finding 3; it does not guarantee
  execution at the closing price. Two columns help the backtest to separate the
  formation of the order from its execution:
  - `prc_age_days`: age of the last price. Among the eligible rows, 3,737 have a
    price older than the date, of which 1,158 by more than 7 days;
  - `zero_volume`: no volume in the month (5,624 eligible rows).

  The returns of positions already held are not affected.
- **Weight of unknown t+1 returns**, finding 4: published in the report, 0.0097 %
  of the eligible market equity per month on average.
- **`read_verified`**, finding 5: the hash and the read now use the same bytes.
- Note on D2: JKP requires `conditionaltype = RW`, while TF accepts RW and NW
  with an active status. Our substitute is closer to TF. The gap cannot be
  measured without exporting `conditionaltype` again.
- Version 3 corrections of steps 1 and 2: N1 to N4 confirmed as solved by Astra.

**Status: step 3 closed on 2026-11-11.**

### Step 4: NYSE breakpoints and size groups

**Based on**: JKP (`nyse_size_cutoffs`, `classify_stocks_size_groups`).

- Breakpoints computed each month on the eligible stocks with
  `primaryexch = 'N'`: percentiles 1, 20, 50 and 80 of `me`.
- Groups: **mega** above p80, **large** between p50 and p80, **small** between
  p20 and p50, **micro** between p1 and p20, **nano** below p1.
- **All sizes are kept** in the data. The size group is only a label, and no
  stock is removed at the cleaning stage. **Decision D7.**
- The possible exclusion of a group is decided later, at the backtest stage, by
  a **rule fixed now**:
  - for each size group, we measure the gross alpha, the turnover, the
    estimated costs (spread and price impact for USD 100 million) and the
    **break-even cost**, equal to the gross alpha divided by the turnover;
  - a group is removed from the final portfolio if its estimated costs exceed
    this break-even cost, or if USD 100 million would be too large a share of
    the traded volume;
  - the rule is about costs and capacity, **never about alpha alone**. Sources:
    Novy-Marx and Velikov (2016) and lecture 3.
  - Results are shown in three versions: all stocks, without the stocks below
    the NYSE 20th percentile, and with our rule.
  - The volume participation threshold is still to be fixed before the backtest.
- The NYSE breakpoints will also serve for decile sorts (course).

**Implementation: `scripts/data_cleaning/4_crsp_size.py`** (2026-11-11).
Outputs:
- `nyse_cutoffs.parquet`: one row per month with `n`, `nyse_p1`, `nyse_p20`,
  `nyse_p50` and `nyse_p80`;
- `crsp_panel.parquet`: the step 3 panel, plus `size_grp` and `me_cap`;
- `crsp_size_report.json`.

- **Code reused**:
  - JKP `nyse_size_cutoffs`: SQL aggregates copied (`QUANTILE_DISC` at 1 %,
    20 %, 50 % and 80 %). JKP's NYSE filter (`obs_main`, `exch_main`,
    `primary_sec`, `common`) is replaced by our step 3 eligibility;
  - JKP `classify_stocks_size_groups`: groups nano, micro, small, large and
    mega;
  - JKP `me_cap = min(me, nyse_p80)`, for capped weights. `me_cap` is missing if
    `me` or p80 is missing (audit correction: `min_horizontal` skips missing
    values). Checked on the whole panel.
- **NYSE sample**: our eligible stocks listed on the NYSE (`crsp_nyse`), with
  the market equity of the **security**, like JKP. TF also requires US
  incorporation.
- **Deviation from JKP**: JKP puts a month without breakpoints in "mega" to
  reproduce SAS. Here, an eligible stock without a group stops the script.
- The read of `crsp_universe.parquet` is checked by SHA-256.

**Check results**:
- 1,152 months of breakpoints, always ordered. Since 1963: 1,139 to 1,874 NYSE
  stocks per month, and every eligible stock has a group;
- share of NYSE stocks by group: 1.0 / 19.0 / 30.0 / 30.0 / 20.0 %, as expected;
- all eligible stocks since 1963, by count then by market equity:

  | Group | Share of stocks | Share of market equity |
  |---|---|---|
  | nano | 18.8 % | 0.3 % |
  | micro | 40.7 % | 2.7 % |
  | small | 20.5 % | 6.6 % |
  | large | 12.9 % | 16.0 % |
  | mega | 7.2 % | 74.5 % |

- **independent check** against Ken French's NYSE breakpoints
  (`ME_Breakpoints`), over 756 months since 1963: correlation of the logs of
  0.998 (p20), 0.9996 (p50) and 0.9998 (p80);
  - the 1960s and 1970s agree within 1 %;
  - the median gap of p50 (ours / French − 1) then grows. Astra's test, which
    sums the share classes by PERMCO, gives:

    | Period | By security | By company |
    |---|---|---|
    | 1963–1979 | +0.0 % | 0.0 % |
    | 1980–1989 | −1.3 % | −1.3 % |
    | 1990–2019 | −3.4 % | −0.6 % |
    | 2020–2025 | −13.4 % | −11.2 % |

  - Ken French counts **companies** (classes summed), while JKP and we count
    securities. This explains most of the gap from 1990 to 2019, but not the gap
    of the 1980s;
  - the gap of the 2020s may come from SPACs: 51 NYSE securities have the word
    "ACQUISITION" in their name in 2022-04, of which 41 with SIC 6799. This is a
    **hypothesis**, because the French file does not list its securities. Even
    without them, 118 companies more than French remain;
  - choice made: stay with the JKP convention, at the security level. No return
    is affected, but groups change: with the French breakpoints, 29,969 eligible
    observations from 1963 to 2019 would change group. Sorts with the Ken French
    breakpoints are a **possible robustness test** at the backtest.
  - The check also verifies that every month since 1963 is present exactly once
    in the French file and that the compared breakpoints are positive.
- The Ken French downloader stops without writing anything if an online file
  differs from the local file (new vintage). The manifest is written last,
  through a temporary file.

**Status: step 4 closed on 2026-11-11** (Astra audit "to correct", blocking
finding `me_cap` fixed; run `51233f73d9fe` after the two minor reservations of
the step 5 audit).

### Step 5: excess returns

**Based on**: TF.

- `ret_exc = ret − rf`, where `ret` is the validated total return of steps 1 and
  2, not `MthRet`. The rate `rf` comes from the Ken French Data Library. JKP
  uses CRSP `t30ret`, which we do not have.
- The excess return of the next month is computed only if the next month exists
  in the panel, or if it is the delisting month.

**Implementation: `scripts/data_cleaning/5_crsp_excess.py`** (2026-11-11).
Outputs:
- `ff_factors_monthly.parquet`: by month `yyyymm`, the FF3 factors
  (`mkt_excess`, `smb`, `hml`), the FF5 factors (`mkt_excess_ff5`, `smb_ff5`,
  `hml_ff5`, `rmw`, `cma`), momentum `mom` and `risk_free`, in decimals;
- `crsp_panel_exc.parquet`: the step 4 panel, plus `risk_free`, `ret_exc` and
  `ret_exc_lead1`;
- `crsp_excess_report.json`.

- **Code reused**:
  - TF, reading of the Ken French files: codes −99.99 and −999 → missing,
    division by 100, `Mkt-RF` → `mkt_excess`, `RF` → `risk_free`;
  - TF, left join on the month then `ret_excess = ret − risk_free`;
  - JKP `ret_exc_lead1m`: here `ret_exc_lead1 = ret_lead1 − rf(t+1)`, where
    `ret_lead1` comes from step 3 (row of month t+1, delisting month included).
- **Deviations**:
  - JKP uses CRSP `t30ret`, absent from our extract: we use the Ken French RF;
  - TF drops missing excess returns; here no row is removed, and a missing
    return stays missing.
- **Factors**: the FF5 RF is identical to the FF3 RF. The FF5 Mkt-RF differs
  slightly (at most 0.08 %, 30 months beyond the 0.01 % rounding). The cause is
  not established: the French notes give the same criteria for the market. SMB
  differs almost every month (different construction), HML never. Like TF, each
  model keeps its own factors: FF5 regressions will use the `_ff5` columns, from
  1963-07 at the earliest.
- **Vintage**: the Ken French files are revised at each release. We keep the
  downloaded vintage (CRSP 202609), protected by the downloader. The factors run
  to 2026-09, beyond our panel (2025-12): regressions will stop at 2025-12.

**Check results**:
- Ken French files: SHA-256 equal to the manifest (on the bytes read), exact
  header, real, unique and consecutive months, finite values;
- each factor is present on its whole calendar of use: 1963-01 to 2025-12 for
  FF3, momentum and RF, 1963-07 to 2025-12 for FF5;
- monthly RF between −0.06 % and 1.35 %, never missing, present and equal in FF3
  and FF5 on every common month;
- `ret_exc` is missing exactly when `ret` is (83,884 rows), the same for
  `ret_exc_lead1` and `ret_lead1` (122,584 rows), and every return has its RF;
- **stock-by-stock timing check**: on the 5,210,894 rows, `ret_exc_lead1` of
  month t equals `ret_exc` of the row of month t+1 of the same stock, missing
  values included. This check fails if the RF of the wrong month is subtracted
  (tested: 3.9 million rows in error);
- **market check**: the value-weighted excess return in t+1 of the eligible
  stocks, weighted by `me` of t, against the Fama-French Mkt-RF of month t+1,
  over 755 months since 1963: correlation **0.99999**, mean absolute gap of
  0.009 % per month. Shifted by one month, the correlation falls to 0.04. It
  places the market month, but cannot tell which RF was used.

**Status: step 5 closed on 2026-11-11** (Astra audit "validated with
reservations", reservations handled; runs `51233f73d9fe` for step 4 and
`372513cad024` for step 5, after the "no empty month" check asked by the step 6
audit).

### Step 6: CRSP-Compustat links (`ccm_links.parquet`)

**Based on**: TF, more cautious than JKP.

- `LINKTYPE ∈ {LC, LU}` and `LINKPRIM ∈ {P, C}` (TF). JKP adds `LS` and does not
  use `LINKPRIM`. **Decision D5.**
- `LINKENDDT = 'E'` is treated as +∞; the date is valid if
  `LINKDT ≤ date ≤ LINKENDDT`.

**Checks**: **zero duplicate** `(PERMNO, date)` or `(gvkey, date)` after the
filter. Otherwise the script fails.

**Implementation: `scripts/data_cleaning/6_ccm_links.py`** (2026-11-11).
Outputs:
- `ccm_link_table.parquet`: the 32,306 links kept (`permno`, `gvkey`, `linkdt`,
  `linkenddt` null if the link is still active, type, flag, `liid`);
- `ccm_links.parquet`: one row per linked stock-month (`permno`, `yyyymm`,
  `eom`, `date`, `gvkey`), 4,125,224 rows. The `gvkey` is joined to the panel at
  step 8;
- `ccm_links_report.json`.

- **Code reused**:
  - TF `ccm_linking_table`: `linktype ∈ {LU, LC}` and `linkprim ∈ {P, C}`;
  - TF `ccm_links`: join on `permno`, then date inside `[linkdt, linkenddt]`;
  - JKP `gen_crsp_sf`: the test is on the CRSP row date, and an open end is +∞.
    This date is our `date` column: `MthCalDt` on a CRSP row (last trading day
    of the month in the CRSP calendar), and `delistingdt` on an added delisting
    row (D9). With the calendar month end, 267 eligible links would be lost and
    9 would point to another company.
- **Strict reading**: exact header, known types and flags, dates converted
  strictly, unique key `(gvkey, LIID, LINKDT)`, `LPERMNO` missing only for the
  types without a CRSP security (NR, NU). The file size is compared with the raw
  manifest, and its SHA-256 is recorded in the report.

**Check results**:
- links kept: **no overlap** by `permno` or by `gvkey`;
- zero duplicate `(permno, month)` and zero duplicate `(gvkey, date)`. Only one
  month has two securities for the same company (179077, 2017-10): the old
  security delists on the 5th and its successor trades at the month end. Never
  two eligible securities for one company in the same month;
- **coverage of eligible stock-months since 1963**: 93.3 % by count and
  **98.1 % by market equity**;

  | Decade | By count | By market equity |
  |---|---|---|
  | 1960 | 71.0 % | 92.6 % |
  | 1970 | 84.4 % | 97.2 % |
  | 1980 | 91.1 % | 98.5 % |
  | 1990 | 97.5 % | 99.5 % |
  | 2000 | 98.6 % | 99.3 % |
  | 2010 | 98.6 % | 97.9 % |
  | 2020 | 96.0 % | 97.3 % |

- by size group, by count: nano 88.5 %, micro 92.5 %, small 95.0 %, large
  97.2 %, mega 98.5 %;
- **links left out (D5), among eligible stocks since 1963**:
  - flags J and N (secondary share classes, for example a second listed class
    of the same company): 330 securities, 30,763 stock-months, **1.75 % of
    market equity**. These securities stay in the panel, without accounting
    data;
  - type LS: 18 securities, 1,589 stock-months, 0.05 % of market equity;
- **check by a second route**: for every panel row, take the last kept link
  that started on or before the row date, if it has not ended. The result must
  be exactly the published table (4,125,224 rows, 0 missing, 0 extra). This
  check fails if a month of links disappears (tested). Every month since 1963
  must also have more than 80 % of its market equity linked (lowest observed:
  88.1 % in 1963-02);
- the link `PERMCO` equals the one of the panel row on all linked rows;
- **reconciliation with the WRDS export**: WRDS merged the annual accounts file
  with this same table. Its 343,569 rows `(gvkey, permno, datadate)` all fall
  inside a raw link, and 99.1 % inside a kept link. This test validates our
  reading of the link dates, not the existence of accounts for each linked
  month.

**Limits**:
- the link table is today's table (CRSP sometimes corrects old links). This is
  standard practice; the validity intervals are respected;
- 234 linked `gvkey` are absent from the annual accounts extract (2,044 eligible
  stock-months). The real availability of accounts is measured when they are
  joined (steps 7 and 8);
- D5: among the 330 J/N securities, 29,493 of the 30,763 stock-months would join
  a company that already has an eligible linked security that month. Their
  weight reaches 3.3 % of market equity in 2025-11. To recall when building the
  accounting signals.

**At step 8**: the table is joined to the panel by a **left join** on
`(permno, eom)`, to keep the returns and the stocks without accounts.

**Status: step 6 closed on 2026-11-11** (Astra audit "validated with
reservations", reservations handled; runs `372513cad024` for step 5 and
`2a792dacd465` for step 6).

### Step 7: annual accounting data (`compustat_annual.parquet`)

**Based on**: JKP (`standardized_accounting_data`, `add_helper_vars`) and TF.

- Filters already checked: `INDL`, `STD`, `C`, `D`. We keep **`curcd = 'USD'`**
  (TF). JKP converts currencies, which is not needed here. **Decision D6.**
- **Deduplication**: the table is first brought to the `gvkey × datadate` level
  by dropping `LPERMNO`, after checking that the accounting fields are
  identical. `gvkey × fyear` must then be unique. Any conflict stops the script.
- **Book equity** (JKP):
  `be_x = coalesce(seq, ceq + coalesce(pstk_x, 0), at − lt) + coalesce(txditc, 0) − coalesce(pstk_x, 0)`,
  with `pstk_x = coalesce(pstkrv, pstkl, pstk)`, and `be_x` set to missing if it
  is ≤ 0. Our extract has neither `txdb` nor `itcb`, so `txditc` is used
  directly.
- The other helper variables (ROE, asset growth, accruals, etc.) are defined at
  the signal step, with the JKP formulas.

**Implementation: `scripts/data_cleaning/7_compustat_annual.py`** (2026-11-11,
run `b3acac9ae9d4`). Outputs:
- `compustat_annual.parquet`: one row per `gvkey × datadate`, 335,244 fiscal
  years for 27,438 companies, from 1950-06 to 2026-09. Columns: `gvkey`,
  `datadate`, `fyear`, `fyr`, `sich`, the 21 raw accounting items (USD
  millions), then `pstk_x`, `txditc_x`, `seq_x` and `be_x`;
- `compustat_annual_report.json`.

- **Code reused**:
  - JKP `load_raw_fund_table_and_filter` and TF: the filters `INDL`, `STD`, `C`
    and `D` are checked on every row; `curcd = 'USD'` (TF);
  - JKP `add_helper_vars`: negative `at`, `sale` and `che` set to missing, then
    `pstk_x = coalesce(pstkrv, pstkl, pstk)`,
    `seq_x = coalesce(seq, ceq + coalesce(pstk_x, 0), at − lt)`,
    `be_x = seq_x + coalesce(txditc_x, 0) − coalesce(pstk_x, 0)`, missing if
    ≤ 0. We follow JKP word for word (TF writes `ceq + pstk` without the
    `coalesce`).
- **Deviations from the first spec and from the references**:
  - **no selection of the last `datadate` per fiscal year**: after the USD
    filter, `gvkey × fyear` is already unique (blocking check). The only
    duplicate seen in the profile came from the 15 rows without fiscal year or
    currency. TF keeps the last report per **calendar year** of `datadate`: it
    would drop 632 transition fiscal years (change of year end) that we keep;
  - the header fields `costat`, `fic` and `ipodate` are **dropped**: they
    describe the company as it is today, and must not be used at a past date.
    `ajex` and `prcc_f` are not used;
  - `sich` (historical SIC code, known since 1982) is kept.
- **Strict reading**: exact header, size compared with the raw manifest and
  SHA-256 recorded, dates and numbers converted strictly, finite numbers.

**Check results**:
- 343,569 raw rows → 340,636 after removing the copies by `LPERMNO` (2,933),
  **with no conflict** on the other fields;
- currencies: 335,244 USD rows kept, 5,377 CAD and 15 without currency removed.
  197 companies have fiscal years in USD and in CAD, 13 in USD with a missing
  currency, and 463 have no fiscal year in USD. Only 30 CAD year ends of 5
  companies fall in the middle of a USD series;
- keys: `datadate` always a month end, `fyr` equal to the month of `datadate`,
  `fyear` follows the Compustat rule (a year ending in January to May belongs to
  the previous fiscal year), `gvkey × fyear` unique;
- negative values set to missing: 143 `sale`, 42 `che`, 0 `at`;
- `seq_x`: 302,524 times `seq`, 1,585 times `ceq + pstk_x`, 6,612 times
  `at − lt`, 24,523 times missing;
- `be_x`: 297,865 positive values (88.9 %), 12,856 set to missing because ≤ 0,
  24,523 missing for lack of data;
- accounting identities: `seq = ceq + pstk` within 1 % on 99.999 % of the rows;
  `at = lt + seq` within 10 % on 98.1 % (the gap is mostly minority interest);
- 304,717 intervals of 12 months between two reports, 1,063 shorter and 2,026
  longer (changes of fiscal year and gaps);
- **book equity checks**: a small table computed by hand (the three sources of
  `seq_x`, missing adjustments, negative values, zero boundary) is tested at
  every run. `be_x` is also recomputed by a second writing of the formula on all
  rows, missing values included;
- spot check against public annual reports: Apple 2020 (equity 65,339, sales
  274,515, net income 57,411) and IBM 2019 (20,841, 77,147, 9,431) agree;
- companies linked at step 6: 27,391 of 28,147 have at least one fiscal year in
  USD, **at any date**, that is 98.75 % of the linked stock-months. This figure
  does not say whether accounts are available at the formation date.

**Known limits**:
- **Our extract is a CCM merge**: it only has the fiscal years whose year end
  falls inside a CRSP link. Fiscal years closed before the listing are missing,
  even when they were public (example checked by Astra: Google's prospectus of
  August 2004 had the 2002 and 2003 balance sheets, absent from the extract). In
  the usual case, a newly listed company waits for its first full fiscal year
  plus 6 months; the wait can exceed 18 months. Astra's measure: 250,708
  eligible linked stock-months since 1963 come before the first usable
  accounts, that is **7.8 % by count and 1.2 % by market equity**. These stocks
  keep their returns and their price signals. This also limits the Compustat
  backfill bias.
- Compustat accounts are in their current state (restatements included): the
  values published at the time are not available. Example: Apple's 2009 sales
  are 42,905 in the table, after an amended filing in January 2010, against
  36,537 at the first announcement. This is standard practice (JKP, TF); the
  6-month lag covers a part of the revisions, not all.
- Without `txdb` and `itcb`, `txditc_x` is missing on 56,279 fiscal years, and
  then counts as zero in `be_x` (JKP convention).

**Passed on to the next steps** (Astra audit):
- step 8: report the coverage of accounts **at the formation date**, by age of
  the link and by the items each signal needs (one balance sheet for value, two
  fiscal years for some quality measures);
- step 8: three stock-months where an old USD fiscal year reaches 18 months just
  when a newer CAD fiscal year reaches 6 months (`gvkey` 002770, 005682,
  010120). To settle with the 18-month bound;
- signals: two successive rows are not always 12 months apart (1,063 shorter
  intervals, 2,026 longer). Growth signals will compare dates 12 months apart,
  like JKP, not neighbouring rows;
- `sich` is dated with its fiscal year if a signal uses it.

**Status: step 7 closed on 2026-11-11** (Astra audit "validated with
reservations", reservations handled; run `b3acac9ae9d4`).

### Step 8: availability of accounting data

**Based on**: JKP (`create_acc_chars`, `lag_to_public`, `max_data_lag`).

- JKP treats a report as public 4 months after `datadate` and keeps it at most
  18 months. The course asks for **6 months**, and this lag is used. Window:
  from the end of month `datadate + 6` to the first of two events, the
  publication of the next fiscal year or `datadate + 18` months.
  **Decision D4.**
- **Monthly update**, like JKP, instead of once in June like Fama-French in TF.
  This fits a monthly rebalancing and the course rule: "using most up-to-date
  data is preferable".
- Value ratios use the market equity **of month t** (JKP; Asness and Frazzini,
  2013). Accounts are joined on `(gvkey, availability month)` through the step 6
  links.

**Automatic no-look-ahead check**: for every row, the availability date must be
on or before the formation date. Any violation stops the script.

**Implementation: `scripts/data_cleaning/8_accounting_availability.py`**
(2026-11-11, run `e983304b3cfc`). Outputs:
- `acc_public.parquet`: for each company and each month, the usable report
  (`gvkey`, `public_date`, `datadate`), 4,048,344 rows;
- `crsp_panel_acc.parquet`: the step 5 panel, plus `gvkey`, `acc_datadate`
  (fiscal year end of the usable report) and `acc_age_months`. No row is removed
  (left joins);
- `accounting_availability_report.json`.

Accounting values stay in `compustat_annual.parquet`. They are joined on
`(gvkey, acc_datadate)` at the signal step.

- **Code reused** from JKP (`add_earnings_persistence_and_expand`, `expand`):
  - start: end of month `datadate + 6 months`;
  - end: the earlier of the month before the start of the next report and the
    end of month `datadate + 18 months` (bounds included);
  - one row per month from start to end, then a join on `(gvkey, eom)`.
- **Deviations from JKP**:
  - lag of 6 months (course, D4) instead of 4;
  - the "next report" is the company's next report **in any currency**, read
    from the raw file. A newer report replaces the old one even if its values
    cannot be used (non-USD): no accounts are then available. This settles the
    three boundary cases raised in the step 7 audit;
  - JKP keeps the first row of a duplicate `(gvkey, public_date)`; here a
    duplicate stops the script.
- **Example**: a fiscal year ending on 31 December 2019 is usable from the
  formation at the end of June 2020 (returns of July 2020) to the one at the end
  of May 2021, then fiscal year 2020 replaces it.

**Check results**:
- **look-ahead test**: on the 3,710,004 rows with accounts, the report is always
  public at the formation date. The report age goes from 6 to 18 months (18
  months: 1,318 eligible rows, when the next report is late);
- **second route**: for every linked row (4,125,224), we look for the company's
  last public report, in any currency. It must be the report kept if it is in
  USD and at most 18 months old; otherwise nothing is expected. Zero difference;
- **truncation test**: all reports not yet public at a date T are hidden, the
  table is rebuilt, and the past must stay identical. Zero difference at
  1975-06, 1999-12 and 2015-03;
- **negative tests**: a lag of 5 months instead of 6 is caught (323,608 rows),
  and so is the use of the next report in place of the current one (296,024
  rows);
- run consistency: the links were built on this panel, and the accounts on
  these links (run ids checked);
- 58,116 linked rows have nothing usable because the last public report is not
  in USD.

**Coverage at the formation date** (eligible stock-months since 1963):

| Measure | By count | By market equity |
|---|---|---|
| Compustat link | 93.3 % | 98.1 % |
| Usable report | 85.5 % | 96.8 % |
| Total assets known | 84.2 % | 96.8 % |
| Book equity known | 81.3 % | 94.3 % |
| Two fiscal years (current and 12 months before) | 77.6 % | 95.3 % |

- book equity by decade, by market equity: 88.3 % (1960), 94.3 % (1970), 95.2 %
  (1980), 96.3 % (1990), 96.8 % (2000), 94.6 % (2010), 92.4 % (2020). Lowest
  month: 77.6 %;
- book equity by size, by count: nano 74.3 %, micro 77.2 %, small 85.2 %, large
  91.1 %, mega 95.2 %;
- by age of the link (linked stocks), share with a usable report: 1.8 % in the
  first 6 months, 53.2 % from 6 to 17 months, 98.1 % from 18 to 35 months,
  99.3 % after. This is the effect of the missing pre-listing accounts.

**Corrections after the Astra audit** (run `e983304b3cfc`, no value changed):
- **reference cases written by hand**, independent of the script constants and
  tested at every run: December year end → first formation at the end of June,
  replacement by the next report, 18-month bound, late next report, next report
  in CAD. A global lag of 5 months or a maximum age of 24 months fails this
  test;
- the report age is checked on every row, and the `gvkey` of every row is
  compared with the input link table, missing values included;
- the raw file read again for the calendar must have the hash recorded at
  step 7;
- the counter of rows without usable accounts is split: 57,957 whose last public
  report is in CAD, 159 whose currency is unknown. Among them, only 28 would
  still have an old usable USD report without the replacement rule, of which 3
  eligible since 1963.

**Limits**:
- accounting signals are missing for recently listed companies (see step 7).
  The handling of missing signals is fixed at the signal step;
- among the reports kept on eligible rows, 43,496 have no item filled: each
  signal must check its own inputs;
- **restatements and late filings (blocking finding of the Astra audit,
  decision D12)**: the availability date is inferred from the fiscal year end.
  Our export has neither a filing date nor a version history. The values are
  today's values, so an amount restated after the formation can enter a signal.
  Example checked by Astra, Super Micro Computer (`gvkey` 176567): for the
  fiscal year ending in June 2024, the table gives USD 5,417.2 million of
  equity, while the public figure in December 2024 was 5,469.5 (a 1 % gap); for
  fiscal year 2017, the sales in the table (2,484.9) come from a 2019
  restatement, against 2,529.9 announced at the time. At least 10 eligible
  stock-months are affected; the total cannot be measured with our data.
  - This is the limit of standard Compustat, used with a fixed lag by JKP, Tidy
    Finance, Fama-French and the course convention. Fixing it needs a
    point-in-time database, which we do not have.
  - It only affects accounting signals (value, quality). Price signals
    (momentum, volatility) are not concerned.

**Status: step 8 closed on 2026-11-11** (Astra audit "to correct": check
findings fixed, run `e983304b3cfc`; blocking finding handled by decision D12,
validated by Danny, see "Rule D12" at the end of this document).

### Step 9: monthly summaries of the daily file (`crsp_daily_agg.parquet`)

**Based on**: JKP (`prepare_daily`, `roll_apply_daily`, `bidask_hl`).

**Reduced scope, validated by Danny on 2026-11-11 (decision D11)**, to meet the
13 November deadline. We compute only what serves a chosen signal or the cost
model:
- **kept**: volatility over 21 and 252 days, market beta over 252 days, dollar
  volume over 126 days, quoted spread (`DlyBid`, `DlyAsk`);
- **left out**: maximum return over 21 days, Amihud illiquidity, share of days
  without trading. The Corwin-Schultz estimator, first left out, was added back
  (see below).

The full list below stays the reference if time allows.

- Rows with `DlyDelFlg = 'Y'` are excluded (JKP). The 22 GB file is hashed in one
  pass and converted in a second pass (its size and modification time must be
  the same before and after).
- Measures by stock and by window-end month, with the **minimum number of
  observations of JKP**:
  - volatility over 21 days (at least 15) and over 252 days (at least 120);
  - maximum return over 21 days;
  - market beta over 252 days (at least 120);
  - dollar volume and share of days without trading over 126 days (at least 60);
  - Amihud illiquidity over 126 days.
- **Spreads**:
  - quoted spread from `DlyBid` and `DlyAsk` when they exist;
  - otherwise the Corwin-Schultz high-low estimator, like JKP (`bidaskhl_21d`,
    at least 11 daily estimates: JKP's threshold is strictly more than 10). On a
    day where the price is a bid-ask average (`DlyPrcFlg = 'BA'`) or without
    volume, JKP does not use the day's own range: it carries the last valid
    range forward. A month can therefore have an estimate without any range
    observed in the month; `n_hl_observed_21d` counts the observed ranges.
  - The course replaces missing spreads by the mean of the size category; this
    imputation serves **only the cost model**, not the signals.

**Implementation: `scripts/data_cleaning/9_crsp_daily_agg.py`** (2026-11-11, run
`f7a7e36567cf`, reduced scope D11 plus the high-low estimator). Outputs:
- `crsp_daily_min.parquet`: the daily columns used (intermediate table, 102
  million rows);
- `crsp_daily_agg.parquet`: one row per stock-month (4,891,218), key
  `(permno, yyyymm)`, with `rvol_21d`, `rvol_252d`, `beta_252d`, `dolvol_21d`,
  `dolvol_126d`, `spread_quoted_21d`, `bidaskhl_21d`, `n_hl_observed_21d` and
  the observation counts;
- `crsp_daily_agg_report.json`.

- **Code reused from JKP**:
  - the "21, 126 and 252 day" windows are **1, 6 and 12 calendar months** ending
    at the month end (`gen_aux_windows`);
  - minimum number of observations: 15, 60 and 120;
  - `rvol` = standard deviation of `ret_exc`; `beta` = cov(`ret_exc`, market) /
    var(market); `dolvol` = mean of the daily dollar volume;
  - guards: no value if raw returns are near-constant (standard deviation
    ≤ 1e-6) or zero 90 % of the time or more;
  - `DlyDelFlg = 'Y'` rows excluded; a return whose previous price is more than
    14 days old is not used; every CRSP day must have a market return;
  - Gao-Ritter NASDAQ volume adjustment (step 3 function).
- **Deviations**:
  - daily market and risk-free returns from Ken French (JKP builds its own
    market and uses `t30ret / 21`);
  - windows are computed from monthly sums (count, sum, sum of squares, cross
    products), in one pass;
  - quoted spread `(ask − bid) / midpoint`, monthly mean over at least 10 days
    with a valid quote (`ask > bid > 0`, spread ≤ 50 % of the midpoint). It
    comes in addition to JKP's high-low estimator;
  - a value exists only for a month where the stock has daily rows.
- **Availability**: data of month t serve the formation at the end of t.

**Check results**:
- daily file: size equal to the manifest, hash identical to the one of step 1,
  exact header. 102,059,931 rows for 40,058 stocks; 31,620 exact duplicates
  removed, no conflicting duplicate; 29,362 delisting rows excluded. (First run:
  no row gap of more than 14 days and 100 rows without a known exchange; after
  the step 9 audit, 40 returns dropped and 0 row without an exchange, see the
  corrections below);
- **second route**: on 101 stocks, each statistic is recomputed directly on the
  daily rows of each window. Largest relative gap of 1e-13, no difference in
  missing values;
- **independent check of the daily file**: daily returns compounded over the
  month equal the CRSP monthly return within 0.0001 on 99.99998 % of the
  4,672,805 months compared (correlation 1.0000);
- mean value-weighted market beta: 1.01 (from 0.79 to 1.14);
- **coverage of eligible stocks since 1963**, by market equity: 12-month
  volatility and beta 99.3 %, 6-month dollar volume 99.6 %, quoted spread
  94.0 %;
- medians: daily volatility 2.6 % (1 month) and 2.9 % (12 months), beta 0.73,
  quoted spread 1.9 %. Median spread by size: mega 0.06 %, large 0.13 %, small
  0.58 %, micro 2.8 %, nano 8.5 %.

**High-low estimator (`bidaskhl_21d`), added on 2026-11-11 with Danny's
agreement.** Quoted spreads barely exist before the 1990s (coverage by market
equity: 0.3 % in the 1960s, 7.5 % in the 1970s, 12.6 % in the 1980s, 85.9 % in
the 1990s). The imputation by size category cannot be enough for these years.
We therefore reuse the Corwin and Schultz (2012) estimator as JKP codes it
(`bidask_hl`, `impute_high_low`, `adjust_overnight_returns`,
`compute_bidask_spread`, copied): spread from the high and low prices of the day
and of the day before, negative values set to zero, monthly mean over more than
10 daily estimates (at least 11). Prices are divided by `DlyCumFacShr`, the
cumulative factor for share splits (not the price factor that also adjusts for
distributions), as in JKP.
- coverage by market equity: 99.9 % (1960), 92.7 % (1970), 96.5 % (1980), then
  above 99.8 %. Either of the two spreads: at least 99.9 % in every decade,
  99.2 % of eligible stock-months by count;
- on the 2,183,967 stock-months that have both measures, the mean monthly rank
  correlation is 0.71 and the medians are close (1.30 % quoted, 1.25 %
  high-low);
- **but the high-low estimator compresses the gaps across sizes**: median of
  0.50 % for mega (0.06 % quoted) and 2.8 % for nano (8.5 % quoted). It
  overstates the cost of large caps and understates the cost of small caps. How
  to combine the two measures (for example the quoted spread when it exists,
  otherwise the high-low one) is a **decision of the cost model**, to fix before
  the backtest.

**Corrections after the Astra audit of step 9** (2026-11-12, verdict "to
correct"):
- **Exchange of the day, blocking finding 1.** The NASDAQ volume adjustment used
  the exchange of the month end for every day of the month. It now uses the
  exchange valid on each daily date (security-history interval, bounds
  included; if the stock is not active there, the last active interval, as in
  step 3). Reference case checked at every run: PERMNO 62500 in March 2000
  (NYSE until the 20th, NASDAQ from the 21st) has a mean daily dollar volume of
  29,143,056, against 17,097,119 before. Astra's count: 1,636 one-month values
  and 9,824 six-month values change (1,489 and 8,929 eligible). No daily row is
  left without a known exchange.
- **14-day rule, blocking finding 2.** The gap was measured from the previous
  row. Rows without a price can sit between two prices, so a return could cover
  several weeks. The gap is now measured from the **previous row with a price**.
  40 returns are dropped (0 before). Reference case checked at every run: PERMNO
  37022 in December 1978, where a +103 % return after weeks without a price
  made the daily volatility 23.65 %; it is now 1.05 %. This is a project rule:
  JKP's CRSP branch does not apply its own 14-day rule. 1,087 returns have no
  earlier price in the file and are not used, as before.
- **High-low ranges carried forward, finding 3.** New column
  `n_hl_observed_21d`: days of the month with an observed range (trade price,
  volume, high above low). 51,018 stock-months have a high-low spread with no
  observed range in the month: the estimate rests only on carried ranges. The
  cost model must not use them as if they were observed (see below).
- **Market calendar, finding 4.** A CRSP trading day missing from the Ken French
  calendar now stops the script (it used to drop the day for all measures). The
  direct check also requires the same stock-months in the output and in the
  direct computation. Both negative tests are caught.
- **Cache stamp, finding 5.** Written through a temporary file.
- All other figures above are unchanged at the precision shown (coverage,
  medians, correlation with monthly returns, value-weighted beta 1.01).

**Open decision for the cost model** (to fix before the backtest; Astra's
recommendation, not decided yet):
1. use the quoted spread when it exists;
2. otherwise the high-low spread, only if the month has observed ranges
   (`n_hl_observed_21d > 0`), rescaled by the ratio of the medians "quoted /
   high-low" of the same size group, estimated on pairs strictly before t
   (window, minimum count and zero denominator fixed in advance);
3. otherwise the mean of the size category at the formation date (course rule);
   with no usable reference, the cost is left undetermined and the weight of the
   turnover concerned is reported;
4. cost of a trade = half the relative spread × the absolute amount traded;
   commissions and price impact are kept apart;
5. report the net result under this rule and under the simple course fallback.
On the same stock-months, the medians are (quoted / high-low): mega 0.056 % /
0.545 %, large 0.114 % / 0.651 %, small 0.333 % / 0.927 %, micro 2.196 % /
1.657 %, nano 4.703 % / 2.948 %. These full-period ratios must not enter the
historical estimates. A sensitivity to the 50 % cap of the quoted spread is
shown if nano-cap costs change the conclusion (the cap removes 563,008 quotes).

**Status: step 9 closed on 2026-11-12** (Astra audit "to correct": the two
blocking findings and the three others are fixed; the fixes are checked in the
final audit).

### Step 10: extreme values

- **No winsorisation** of portfolio returns.
- JKP winsorises returns at 0.1 % and 99.9 % only for the factor regressions;
  this choice is made at the alpha step.
- Characteristics are turned into ranks at the signal step, which neutralises
  extreme values without removing them.

**Status: step 10 closed on 2026-11-11.** No code: nothing is removed or clipped
in the cleaned data. The two choices above are applied at the signal and alpha
steps.

### Data dictionary (`resources/data_dictionary.csv`)

Planned by `ProjectWorkflow.md`. One row per column of the seven cleaned tables
(148 columns): meaning, unit, source, availability and role(s).

- **Availability**: `key` (row key), `t` (known at the end of month t),
  `interval` (validity interval), `acc_6m` (annual report usable 6 months after
  the year end), `t+1` (known after the holding month), `after_t` (can be dated
  after t), `today` (today's value).
- **Roles**: `identifier`, `universe`, `predictor`, `outcome`, `benchmark`,
  `execution_cost`, `weight`, `audit`. A column can have several.
- **`scripts/data_cleaning/check_data_dictionary.py`** stops if a column of a
  table is missing from the dictionary, if the dictionary lists a column that
  does not exist, or if a role does not fit the availability:
  - a decision role (`universe`, `predictor`, `execution_cost`, `weight`) needs
    an availability of `key`, `t`, `interval` or `acc_6m`;
  - `t+1` and the role `outcome` always go together, with no other role.
- Restricted use: `ret` and `ret_exc` are predictors only on rows with
  `del_flag = N` (see "Final audit"); `me_company` needs `me_company_complete`
  when the whole company is required; `ticker` is not a key (join on `permno`).
- Columns never to use as an input: `hdr_cusip` (`today`), `delamtdt` and
  `delnextdt` (`after_t`), and the three `t+1` columns (`ret_lead1`,
  `ret_lead1_status`, `ret_exc_lead1`).
- Tables covered: `crsp_panel_acc`, `crsp_daily_agg`, `compustat_annual`,
  `ff_factors_monthly`, `acc_public`, `ccm_links`, `nyse_cutoffs`.

## What we do not reuse from JKP

- The international layer (Compustat security returns, currency conversion,
  country classification).
- Quarterly Compustat and the annual / quarterly combination: we only have the
  annual file.
- The GICS classification: we do not have it, so we use SIC and the 49
  Fama-French industries.
- The CRSP `t30ret` series, replaced by the Ken French risk-free rate.

## Decisions

| ID | Decision | Alternative |
|---|---|---|
| D1 | `usincflg = 'Y'` (TF) | No filter (JKP) |
| D2 | No `conditionaltype`: substitute `tradingstatusflg = 'A'` and `primaryexch ∈ {N, A, Q}`, documented limit | Export again from WRDS |
| D3 | −30 % for a performance delisting without a return (JKP, Shumway). Audit opinion: accept, with a sensitivity test at the backtest at −55 % for NASDAQ (Shumway and Warther, 1999; 2,094 cases concerned) | No imputation (TF) |
| D4 | Availability at 6 months, maximum validity of 18 months, monthly update | 4 months (JKP) or June only (FF/TF) |
| D5 | Links LC/LU and P/C (TF) | LC/LU/LS without LINKPRIM (JKP) |
| D6 | Compustat in USD only | Currency conversion (JKP) |
| D7 | **Validated**: all sizes are kept, and a group is later excluded only by a rule based on costs and capacity, fixed in advance | Exclude everything below the NYSE 20th percentile (Fama-French) or only the nano group (JKP) |
| D8 | Industries: 49 FF industries for the data, a coarser grouping for the neutralisation, to fix at the signal step | SIC divisions (TF) |
| D9 | Add a row in the delisting month when CRSP has none (274 cases). Its return = daily returns up to the delisting, compounded with `delret`. Audit opinion: keep | Lose these delisting returns (JKP) |
| D10 | No filling with 0: if a part of the holding return is unknown, `ret` is missing and `ret_status` says why | `ret = 0` and `delret = 0` (JKP) |
| D11 | **Validated**: step 9 reduced to volatility (21 and 252 days), beta (252 days), dollar volume and the quoted spread; the high-low spread was added back | Full JKP list |
| D12 | **Validated by Danny on 2026-11-11**: keep the accounting signals despite the Compustat restatement limit (today's values, fixed 6-month lag), without claiming that the bias is small. Detailed rule below the table | Get a point-in-time database or the filing dates (new WRDS export), or give up the accounting signals |

### Rule D12: accounting signals and restatements

The bias cannot be measured with our data. So we never say it is negligible. We
show that the conclusion does not depend on it, or we say that it does.

- The backtest shows **two versions** of the strategy, fixed in advance:
  - **version A**: price signals only (momentum, volatility), not exposed to
    the bias. Its universe must not depend on the availability of accounts
    either;
  - **version B**: price signals and accounting signals (value, quality),
    exposed to the bias.
- Both versions get the same tests (alphas and t-tests on the factor models,
  costs included).
- Reading of the results:
  - if version A has a significant alpha, the conclusion holds without any
    accounting signal. The gap between B and A is the **observed gap** between
    the two strategies (interactions and costs included). It is not a bound on
    the contribution of the accounting signals: the sign of the effect of
    restatements is unknown (correction from the step 9 audit);
  - if alpha appears only with version B, the report says that the result rests
    on signals exposed to a bias that cannot be measured.
- Complements: a test with a lag of 12 months instead of 6 for the accounting
  signals (it explores late filings; it does not restore the values published
  at the time), and a verified academic reference on the gap between
  restated and as-first-reported data, to find when writing the report.
- The limit is disclosed in the report, with the Super Micro Computer example.

## Final audit of the cleaning (Astra, 2026-11-12)

Astra audited the whole chain (instructions in
`audit/AUDIT_FINAL_nettoyage_consignes_pour_Astra.md`, report in
`Workspace/output/2026-11-12_AUDIT_FINAL_nettoyage_pour_Claude.md`). Verdict:
"to correct", with one blocking finding. Astra reran the eight scripts and got
15 data files out of 15 identical; its independent rebuild of HML (2×3 sorts in
June, 750 months from 1963-07) has a correlation of 0.982 with the Fama-French
HML and a mean gap of −1.9 basis points a month. All findings are handled:

1. **Monthly adjusted volume (blocking).** Step 3 applied the month-end exchange
   to the whole monthly volume, while step 9 adjusts each day. Fix: new column
   `vol_exch_transfer` in the panel. It is true when an active interval of the
   security history that overlaps the month is on the other side (NASDAQ or not)
   of the exchange used; `vol_adj` and `dolvol` are then missing: 2,297
   stock-months, 2,123 eligible since 1963 (Astra counted 1,668 with a real
   difference; the flag is wider on purpose). New cross-step check in step 9: on
   2,502,768 months where the daily rows add up to the monthly raw volume, the
   monthly adjusted volume equals the sum of the daily ones, with 0 difference.
   For costs, use `dolvol_21d` and `dolvol_126d`.
2. **Late delisting amounts.** A delisting return can rest on an amount known
   after the month (`delamtdt > eom`: 4,811 rows). New check in step 3: no stock
   is eligible again between its delisting month and the date of that amount, so
   such a return cannot reach a signal through its own stock. The dictionary now
   limits `ret` and `ret_exc` as predictors to rows with `del_flag = N`. **The
   earlier sentence "the proceeds are assumed to be reinvested at the end of the
   delisting month" is withdrawn**: the funding of late proceeds (economic
   result, receivable, cash available) is a backtest decision, still open.
3. **Flag V.** CRSP flag V means that a part of the delisting distributions is
   unknown. The return is kept as delivered (JKP), but its status is now
   `crsp_partial_delisting` instead of `crsp`: 200 rows (199 since 1963, 166
   after an eligible formation). Whether such a return counts as known is a
   backtest decision, still open; their weight will be reported.
4. **Raw FRED files.** The files restored after the Git incident had Windows
   line endings and failed their own hashes. They were restored again byte for
   byte from the Git objects of commit `ed8bc04`: the six CSV files match the
   hashes of `data/raw/fred/manifest.json`. No cleaned table uses them.
5. **Hash and read in separate passes.** For the large CSV files, steps 1 and 9
   now record the size and modification time before hashing and check them again
   before publishing. Step 3 reads the security history from the bytes it
   hashes. The temporary files of the daily cache are named with a unique id.
6. **Spread coverage.** Step 9 also reports the coverage of the spread usable by
   the cost rule (quoted, or high-low with at least one observed range): 99.1 %
   of eligible stock-months by count, 99.96 % by market equity.
7. **Field meanings.** `naics = 0` is set to missing, like `sic = 0`. The
   dictionary warns on `ticker` and `me_company`.
8. **Checks that took their population from the object under test.** The
   dictionary check now requires the seven expected tables. The direct check of
   step 9 draws its sample from the daily input.
9. **Stale passages** of this document are dated or replaced.
10. **Observed ranges.** `n_hl_observed_21d` now counts only the ranges accepted
    by the estimator (high / low ratio of at most 8).

**Proposal to fix for the spread rule** (Astra, not decided): pairs from the 36
months before t; at least 100 pairs over 12 distinct months per size group;
ratio of the two medians; otherwise the mean quoted spread of the size category
at t; otherwise an undetermined cost with the traded weight reported; the raw
high-low spread tested apart at the start of the history.

**Before the signals** (Astra, B10), to decide and write down first:
- delistings and cash: flag V, unknown returns of positions already held, late
  proceeds;
- execution and capacity: time and price of the trade (the daily open is not in
  our export), capital, horizon in days, participation limit, impact
  coefficients, and what to do with a stale price, no volume or no reliable cost;
- the spread rule above;
- signals: industry grouping and an "unknown industry" bucket (94,997 eligible
  rows have no FF49), minimum coverage, missing-value rules (a missing
  accounting item is not zero; only 2,030,962 eligible stock-months have book
  equity, sales, cost of goods sold, SG&A and interest together), 12-month
  comparisons on the same `gvkey`, market equity of the security or of all
  share classes for book-to-market, momentum window and skipped month;
- versions A and B (D12) and the sensitivity tests (D3 at −55 % for NASDAQ,
  12-month lag, Ken French breakpoints, costs), frozen before any result;
- the q and q5 factors, needed for the alphas only;
- Ken French factors are fine for ex post regressions; they are not a signal
  known in real time.

## What the references do about the problems found (2026-11-12)

After the final audit, the reference code was searched for each problem. Where
a reference has a solution, our code follows it.

| Problem | In the references | In our code |
|---|---|---|
| Output changing from one run to the next | JKP sorts the rows before order-sensitive computations (comments in `capm` and `res_mom`: cov, var and std are "float-order-sensitive") and replaces a non-deterministic `.unique()` by a sort and a keyed dedup. | Explicit sort right after every `.unique()` that feeds a computation (steps 1, 7, 8, 9); sort and `maintain_order=True` before the monthly sums of step 9. The 15 outputs are the same bytes before and after this change. |
| Return covering more than 14 days | JKP computes `ret_lag_dif` as the days since the previous observation among rows that have a price, and requires `ret_lag_dif <= 14` in `prepare_daily`. Its CRSP branch sets `ret_lag_dif = 1`, so the rule is not applied to CRSP stocks. | Same definition as JKP's Compustat branch (gap since the last row with a price), applied to our CRSP stocks. A stated deviation from JKP's CRSP branch. |
| Exchange used for the NASDAQ volume | In `gen_crsp_sf`, JKP takes `primaryexch` from the dated stock file itself (the join to the security history adds no column). `prepare_crsp_sf` adjusts the volume only when the exchange is Q and `conditionaltype` is RW. | We rebuild the exchange of each date from the security history, with the last active interval as fallback; we have no `conditionaltype` (D2). Daily: exchange of each day. Monthly: missing in transfer months (our own rule). Coefficients and dates of the adjustment follow JKP. |
| High-low ranges carried forward | Intended behaviour of `impute_high_low`; JKP does not count observed ranges. | Code copied; `n_hl_observed_21d` added. |
| Industry code 0 | JKP sets `sic = 0` to missing (`crsp_industry`). | Same, extended to `naics`. |
| Next return not consecutive | JKP has a condition on the next `ret_lag_dif`, but its CRSP monthly branch sets that field to 1 and its `LEAD` follows the next observed row, even after a missing calendar month. The gap is really computed for Compustat securities only. | Stricter: `ret_lead1` needs the row of the next calendar month (0 case since 1963 where the two definitions differ). |
| Missing returns inside a portfolio | In its market aggregates JKP drops missing returns and renormalises the weights. | Same in our market checks only. For the strategy portfolio the rule is an open decision. |
| 12-month changes of accounting items | JKP needs more than 12 months of history (`count > 12`) and compares with the value 12 months before, not with the neighbouring row. | To apply at the signal step. |
| Firms recently added to Compustat | Tidy Finance quotes the Fama and French (1993) rule (a firm is left out until it has been in Compustat for two years) as an exercise. JKP has no such rule. | Our extract already lacks the fiscal years closed before listing. A "two fiscal years available" filter is kept as a sensitivity test for accounting signals. |
| Late or partial delisting proceeds | JKP compounds the delisting return into the delisting month unless the flag is A, P or V. Tidy Finance uses the CIZ returns as delivered, which already include it. Neither dates the availability of the amount; neither is a schedule of cash received. | JKP compounding; a separate status for V; missing when a required part is missing (D10); a check that the stock is not eligible again before the amount date; the mask `ret_signal_ok`. |
| Restated accounts | JKP and Tidy Finance use standard Compustat with a fixed lag. | 6-month lag (course) and rule D12. |

No reference solution was found for: combining quoted and high-low spreads;
restatements; the funding of late delisting proceeds; the unknown return of a
position already held; accounts missing before listing; secondary share
classes; execution at the close; the 50 % cap on quoted spreads; NYSE
breakpoints at the security level; the vintage of the Ken French factors. Astra
is asked for hypotheses on these
(`audit/AUDIT_corrections_finales_et_hypotheses_pour_Astra.md`).

## Counter-audit and rules proposed before the backtest (Astra, 2026-11-12)

Report: `Workspace/output/2026-11-12_AUDIT_corrections_et_hypotheses_pour_Claude.md`.
Verdict on the corrections: "validated with reservations". Astra reran the eight
scripts from the raw files, with no daily cache: 15 data files out of 15 have
the same SHA-256. The blocking volume finding is solved (all 1,668 months with a
real difference are flagged; 0 escapes the flag).

**Counter-audit: reservations handled**
- **Late delisting returns and aggregation.** The step 3 check protects the
  delisted stock itself. Astra found 15 stock-months where such a return sits
  next to another eligible security of the same company, and 3,103 next to an
  eligible stock of the same FF49 industry in the same month. `retx` had no
  restriction. Fix: new panel column `ret_signal_ok` (`del_flag = N`); the
  dictionary requires it for `ret`, `retx` and `ret_exc` used as predictors, on
  the source rows and before any lag, group, index or join. The signal step
  must also test that changing a delisting return after t changes no signal,
  including the signal of a peer.
- **Two statuses of the funding of late proceeds** in this document: the old
  scenario is now dated and points to the open decision.
- **Three descriptions of the references** corrected in the table above
  (exchange in JKP, next return in JKP, delisting in Tidy Finance).
- Left as documented limits: size and modification time do not prove that the
  bytes are the same across two reads; two runs at the same time are not
  supported (run the chain one at a time); the direct check of step 9 is a
  sample of 101 stocks.

**Rules proposed before the backtest.** For the ten problems without a solution
in the references, Astra gives a mechanism, a likely size, a way to measure it
with our files, a rule that can be fixed in advance and a reference. **None is
decided yet: each needs the project owner's validation before any result is
seen.** In Astra's order of importance for the conclusion:

| Rank | Problem | Rule proposed |
|---|---|---|
| 1 | Execution (B7) | Form the order after the close of t, send it for the next session, and simulate the trade at that session's observed close at the earliest. Without a reliable trade price or capacity, keep the old position or cash and carry the order, with a cancel horizon fixed in advance. Show close-to-close as a theoretical benchmark. 18.97 % of eligible formations have a stale price, a bid-ask average or no volume. |
| 2 | Spreads (B1) | Quoted spread at t. Otherwise the high-low spread with observed ranges, times the ratio of the medians quoted / high-low of the size group over t−36 to t−1 (at least 100 pairs with positive values over 12 distinct months). Otherwise the mean quoted spread of the group at t. Otherwise an undetermined cost with the traded weight reported. Raw high-low as a sensitivity. The thresholds are first met in 1964-01 (nano, micro, small), 1967-04 (large) and 1984-01 (mega). |
| 3 | Restatements (B2) | D12 with versions A and B, plus a stress test: shock book equity and earnings by ±10 % on 1 %, 5 % and 10 % of the firm-years (same shock for all months and securities of a firm-year), re-rank, and report positions, turnover and net alpha. No unconditional bound exists from a single vintage. |
| 4 | 50 % cap on quoted spreads (B8) | Keep 50 % for the main result; record sensitivities at 100 % and without a cap before the backtest. For nano caps the cap lowers the monthly spread by 4.05 points at the median on the months it affects. |
| 5 | Unknown return of a held position (B4) | Keep the position and its funding at the last observable mark, buy nothing with it, adjust once when trading resumes. Show three scenarios: −100 %, unchanged mark, and the 95 % quantile of past returns of the size group. On a value-weighted universe the unknown weight is 0.0015 % a month on average, 0.10 % at most. |
| 6 | Late delisting proceeds (B3) | Receivable scenario: proceeds cannot be spent before the amount date, no borrowing against them. Show the two extremes (immediate credit; zero until proven). The amount date is 2 days after the month end at the median, 259 days at the 90th percentile. |
| 7 | Accounts missing before listing (B5) | Keep every stock and its returns in version A. In version B give the neutral rank to a missing sub-score, with a missing flag; fill no accounting item. Report apart the variant with complete accounts and the one with two fiscal years. |
| 8 | NYSE breakpoints (B9) | Keep the JKP convention and D7. If a size limit is applied later, justify it by costs and capacity and redo the test at the Ken French breakpoint. 30,431 p20 decisions change with the French breakpoints (0.18 % of market equity). |
| 9 | Secondary share classes (B6) | Keep D5; same neutral-rank treatment as B5. Giving them the issuer's accounts is a sensitivity only (one balance sheet per issuer, full company market equity, weight limits by company). |
| 10 | Vintage of the Ken French factors (B10) | Freeze the files and their hashes; use each model's own columns for ex post alphas. Stress the intercept with ±1, 5 and 10 basis points a month on the premia. A declared limit if the conclusion is stable. |

References given by Astra, to check before they are cited in the report: Corwin
and Schultz (2012); Shumway (1997); Shumway and Warther (1999); Fama and French
(2008); Gompers, Ishii and Metrick (2010); Holden and Jacobsen (2014); Lyle,
Siano and Yohn (2024); Freyberger et al. (NBER WP 30761); Asparouhova,
Bessembinder and Kalcheva; a GAO report on restatements; "Noisy factors?"
(Review of Finance, 2026).

## Backtest rules validated by the project owner (2026-11-12)

Principle: **the main number already pays for realism.** Wherever a rule offers
a choice, the main version takes the cautious option, so that the result does
not need a list of excuses. A separate scenario is kept only where the choice
can change the conclusion. These rules are fixed before any backtest result is
seen. They replace the proposals of the table above where they differ.

| ID | Rule | Based on |
|---|---|---|
| D13 | **Execution one day after the signal.** The signal uses data up to the close of month t. The new portfolio is traded at the close of the first trading day of month t+1. During that first day the old portfolio is still held. A stock bought earns `(1 + ret_lead1) / (1 + ret_d1 of t+1) − 1` in t+1, where `ret_d1` is the first-day return (new column of `crsp_daily_agg`). If a stock has no return on that first day, its order is not executed that month and the old position is kept. The usual close-to-close return is shown as a comparison. | Project rule (no signal and trade at the same close); Asparouhova, Bessembinder and Kalcheva (2013) on noisy prices. No study was found that prescribes a one-day lag. |
| D14 | **Spread without calibration.** Quoted spread when it exists; otherwise the raw high-low spread if the month has observed ranges (`n_hl_observed_21d > 0`); otherwise the mean of the available spreads of the size group in month t. Cost of a trade = half the spread × the absolute change in weight. Sensitivity: the high-low spread everywhere. | Chen and Velikov (2023): observed spreads when available, low-frequency estimates otherwise; these estimates are biased upward, the cautious direction. Astra's 36-month calibration is not adopted (too few pairs for mega caps before 1984). |
| D15 | **Commissions before May 1975.** A one-way commission is added to the costs of the years with fixed commissions, from the annual series of Jones (2002). **The series is not in the project yet**: it must be obtained and checked before the backtest; until then the report must say that costs before 1975 leave out commissions. | Jones (2002): half the spread plus the commission was at least 1 % one way from 1953 to 1975. |
| D16 | **Unknown return of a position already held: −100 %.** One pessimistic rule, no scenario (the weight concerned is 0.0015 % a month on average on a value-weighted universe). The count and weight of these cases are reported. | Astra B4; the three-scenario version is not adopted. |
| D17 | **Delisting proceeds credited in the delisting month**, as in the references. The late amount dates (2 days after the month end at the median) are a declared limit. | JKP, Tidy Finance; Shumway (1997). Astra's receivable scenario is not adopted. |
| D18 | **Missing signal: neutral rank.** Each characteristic is ranked within the month; a missing value gets the median rank, and a missing flag is kept. No accounting item is filled. The result on stocks with complete signals is reported next to the main one. Same rule for secondary share classes (D5) and for stocks without accounts yet. | Gu, Kelly and Xiu (2020); Bryzgalova et al. (2024): missing data are not random, so the complete-case result must be shown. |
| D19 | **Three universes, fixed in advance**: all sizes; without stocks below the NYSE 20th percentile; and the cost rule of D7. Value weights are the main weighting. | Hou, Xue and Zhang (2020); Avramov, Cheng and Metzker (2023): machine-learning profits fall sharply without micro caps. |
| D20 | **Alphas against two sets of factors**: the Ken French files, and factors rebuilt from our own data (our market return matches theirs at 0.99999). | Akey, Robertson and Simutin: alphas move with the vintage of the Fama-French files. |
| D21 | **Turnover buffer of the course**: buy in the top 10 %, sell only outside the top 20 %. | Course; Novy-Marx and Velikov (2016): the most effective way to cut costs. |
| D12 | Unchanged: version A (price signals) and version B (price and accounting signals), plus the 12-month lag test. Astra's random ±10 % stress test is not adopted. | Lyle, Siano and Yohn (2024). |

**Comparisons shown next to the main number: three, not ten.** (1) version A
against version B; (2) execution one day later against close-to-close; (3) the
three universes.

**Limits that no rule removes**, to state plainly in the report: accounts are in
today's state, so version B stays exposed to restatements; costs before 1993
are estimated, not observed; the NYSE breakpoints, the 50 % cap on quoted
spreads and the vintage of the Ken French files are declared limits.

**Not done, optional**: a second low-frequency spread estimator (Abdi and
Ranaldo, 2017) averaged with the high-low one, as Chen and Velikov do.

**Status of the sources.** These rules rest on abstracts and summaries read on
2026-11-12, not on the full papers. Every figure quoted from them must be
checked in the paper before it goes into the report.

## Audit of the backtest rules (Astra, 2026-11-12)

Report: `Workspace/output/2026-11-12_AUDIT_regles_backtest_pour_Claude.md`.
Verdict: "to review". **No defect was found in the cleaned data**: Astra
recomputed `ret_d1` from the raw daily CSV (4,891,218 keys, 0 difference), the 14
outputs match the SHA-256 of the eight reports, and the dictionary has 148
columns. All findings are about the specification of the backtest.

**Fixed in the cleaning (finding 9, minor)**:
- step 9 now checks six more `ret_d1` source cases recomputed by the auditor
  (first day of the market calendar and not first row of the stock, suspension,
  bid-ask close, D9 month, flag V);
- dictionary: `ret_d1` has the role `audit` only. Read through the row of t+1
  it is observed after the order is submitted; it is not a cost measure and not
  a predictor, and a known value does not prove that a trade was possible.

**Correction of a formula.** The price impact of the course has a square root
(checked in `Courses/3.Trading costs.pptx`, slide 24: the equation has a radical
around order / dollar volume; the text extract had lost it). Impact per dollar
traded = `λ × sqrt(order / ADV)`, with λ in decimals. Unit test from slide 25:
order of USD 100,000, ADV of USD 10 million, micro cap → 0.025 × sqrt(0.01) =
25 basis points of the order.

**Amendments to the rules, validated by the project owner on 2026-11-12, before
any backtest result, with two changes to the table below**: (a) amendment 3 is
simplified: the third universe (D7 rule) is dropped, two universes remain (all
sizes as the main one; above the NYSE 20th percentile), because the order cap
of amendment 2 already handles capacity without an extra threshold; (b) new
rule D23: version A (price signals only) is the main conclusion, and the
sub-period 1993–2025 (observed spreads, no fixed commissions) is shown next to
1963–2025. Amendment 2 is rule D22. The final wording of every rule, with its
justification, is in `ProjectJournal.md`, section 8.4.

| # | Rule | Finding | Amendment proposed |
|---|---|---|---|
| 1 | D13 | A known `ret_d1` does not prove a closing trade (662,223 eligible formations have it with a bid-ask close or no volume; 1,275 have a delisting on or before day 1). | Separate valuation from execution. Orders (amounts) are frozen with the data of t and never replaced by the next candidate. An order is filled at the close of day 1 only if that day has a trade price, a positive volume and no delisting on or before it. Unfilled buy: cash. Unfilled sale: position kept. The order expires at the end of day 1. The fill flag is built from the daily table at the backtest step. |
| 2 | D13, D14, D19 | No capacity limit and no price impact on the amounts traded. | Constant nominal capital of USD 100 million. Impact with the square root, λ = 0.025 (nano, micro), 0.015 (small), 0.010 (large, mega). ADV = the smaller of `dolvol_21d` and `dolvol_126d` at t, both required. Order capped at 1 % of ADV; one stress test at 0.5 %. |
| 3 | D19 / D7 | The break-even rule of D7 uses the alpha of the tested sample: a selection after the fact. The main portfolio is not named. | Main number: all sizes, value weights, net of costs at USD 100 million with the capacity limit. Second universe: above the NYSE 20th percentile. Third universe: a capacity rule known at t (a size group is left out when more than 10 % of its desired amount exceeds the caps), in place of the alpha break-even test. |
| 4 | D15 | The commission series is missing; zero would flatter 1963–1975. The "1 %" of Jones already includes the half spread; commissions do not stop in May 1975. | Use the commission series alone, added to our spread. No net result is shown on a period without commissions: until the series is in the project, the net result is reported only from the first month priced correctly, and labelled as such. |
| 5 | D16 | A missing return is not a final loss (869 of 879 ordinary cases have a known return later). | Keep −100 %, named "full write-off convention", applied once to the lot held, no recovery booked. The mechanical end of the sample is excluded. Weight, effect in basis points and largest case are reported. |
| 6 | D17 | A return credited in the month is not always cash that can be spent (0.444 % of capital in the worst month of a nano + micro control portfolio). | Keep D17; report the stock of late proceeds on the positions really held; do not call the rule cautious. |
| 7 | D14 | Raw high-low is not cautious for all sizes (nano before 1993: 8.72 % quoted, 5.19 % high-low). | Keep D14. Group mean = arithmetic mean over the eligible stocks of the size group in t that have a quoted or an observed high-low spread (no imputed value as a donor). Report the turnover by source of cost. |
| 8 | D12, D18, D20, D21 | Open parameters. | To freeze at the signal step: ranks scaled to [−1, 1], missing → 0 after ranking, fixed weights not rescaled by stock; a stock with no signal at all cannot start a purchase; buffer on the book really held, ties by PERMNO; rebuilt factors: market, SMB, HML, plus RMW, CMA and momentum if FF5 or momentum alphas are shown; t-statistics with a fixed HAC lag (6 months). |

**Sources corrected by the audit** (to respect in the report):
- Jones (2002): at least 1 % one way is the aggregate average of the half
  spread of Dow stocks **plus** the average NYSE commission, not a floor for
  each order;
- Akey, Robertson and Simutin: "up to 4 % a year, momentum the most sensitive"
  is **not** supported. Their Table 5A: 10 % of the alphas of B/M deciles and
  5 % of momentum deciles move by more than 1 point a year;
- Chen and Velikov (2023) prefer **effective** intraday spreads and average
  four low-frequency proxies; D14 is a simpler adaptation, not their method;
- Shumway (1997): −30 % is an empirical average (−29.9 % on 734 observed
  cases), not a prescription; Shumway and Warther (1999): −55 % for missing
  performance delistings on NASDAQ only;
- Bryzgalova et al.: more than 70 % of firms miss **at least one** of 45
  characteristics;
- Asparouhova et al. (2013) motivate care with noisy prices, not a one-day lag.

## Final runs and reproducibility (2026-11-12)

The whole chain was rerun from the raw files after the scripts were moved to
`scripts/data_cleaning/` and after the step 9 corrections. The run ids quoted in
each step above are older; the current ones are:

| Step | Script | Run id |
|---|---|---|
| 1-2 | `1_crsp_monthly.py` | `591588b4ddfc` |
| 3 | `3_crsp_universe.py` | `675782030a3a` |
| 4 | `4_crsp_size.py` | `3a0b1171f186` |
| 5 | `5_crsp_excess.py` | `f920bd39db56` |
| 6 | `6_ccm_links.py` | `90aff624d621` |
| 7 | `7_compustat_annual.py` | `a20b514d1dab` |
| 8 | `8_accounting_availability.py` | `87be465f4640` |
| 9 | `9_crsp_daily_agg.py` | `86a807cdfece` |

- **Reproducibility defect found and fixed.** The first full rerun showed six
  outputs changing from one run to the next. Cause: in step 1, the product of
  the daily returns of the added delisting rows (D9) was computed in an order
  that was not fixed (`unique()` does not keep the row order). Effect:
  `ret_pre_delist` on 77 rows and `ret` on 61 rows differed at the 16th decimal,
  with no change in missing values. The rows are now sorted by `PERMNO` and
  `DlyCalDt` before the product.
- Two full runs in a row then give **15 outputs out of 15 identical byte for
  byte**.
- The SHA-256 of the seven WRDS files and of the five Ken French files were
  checked again against the step reports on 2026-11-12: all equal.

## Order of implementation

1. Steps 1 and 2.
2. Steps 3 and 4.
3. Step 5, once the risk-free rate is downloaded.
4. Steps 6, 7 and 8.
5. Step 9.

Each step ends with its check report and an audit pack for ChatGPT before the
next one starts.
