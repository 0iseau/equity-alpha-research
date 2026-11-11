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

Some items were seen only through a summary of the code, not the exact text.
They are marked *(to reconfirm)*.

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
- **Missing stays missing.** No filling and no imputation, except the delisting
  returns described in step 2.
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
universe at its delisting, so this return **feeds no signal**. In the backtest,
the proceeds are assumed to be reinvested at the end of the delisting month.

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
- **Funding of late delisting proceeds**, reservation on finding 4: in the
  backtest, the proceeds of a G delisting whose amount is known after the month
  (`delamtdt > eom`) are reinvested only from `delamtdt`. In between, they are
  treated as a receivable.
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

- Rows with `DlyDelFlg = 'Y'` are excluded (JKP). The 22 GB file is read once.
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
    at least 10 days). Days where the price is a bid-ask average
    (`DlyPrcFlg = 'BA'`) are left out of this computation.
  - The course replaces missing spreads by the mean of the size category; this
    imputation serves **only the cost model**, not the signals.

**Implementation: `scripts/data_cleaning/9_crsp_daily_agg.py`** (2026-11-11, run
`f7a7e36567cf`, reduced scope D11 plus the high-low estimator). Outputs:
- `crsp_daily_min.parquet`: the daily columns used (intermediate table, 102
  million rows);
- `crsp_daily_agg.parquet`: one row per stock-month (4,891,218), key
  `(permno, yyyymm)`, with `rvol_21d`, `rvol_252d`, `beta_252d`, `dolvol_21d`,
  `dolvol_126d`, `spread_quoted_21d`, `bidaskhl_21d` and the observation counts;
- `crsp_daily_agg_report.json`.

- **Code reused from JKP**:
  - the "21, 126 and 252 day" windows are **1, 6 and 12 calendar months** ending
    at the month end (`gen_aux_windows`);
  - minimum number of observations: 15, 60 and 120;
  - `rvol` = standard deviation of `ret_exc`; `beta` = cov(`ret_exc`, market) /
    var(market); `dolvol` = mean of the daily dollar volume;
  - guards: no value if raw returns are near-constant (standard deviation
    ≤ 1e-6) or zero 90 % of the time or more;
  - `DlyDelFlg = 'Y'` rows excluded; a return after a gap of more than 14 days
    not used; days without a market return excluded;
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
  removed, no conflicting duplicate; 29,362 delisting rows excluded; no gap of
  more than 14 days; 100 rows without a known exchange (dollar volume missing);
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
10 days.
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

**Status: implemented, waiting for the Astra audit.**

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
(144 columns): meaning, unit, source, availability and role(s).

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
    the bias;
  - **version B**: price signals and accounting signals (value, quality),
    exposed to the bias.
- Both versions get the same tests (alphas and t-tests on the factor models,
  costs included).
- Reading of the results:
  - if version A has a significant alpha, the conclusion holds without any
    accounting signal. The gap between B and A is the contribution of the
    accounting signals, reported as a **maximum**, because a part of it may come
    from the bias;
  - if alpha appears only with version B, the report says that the result rests
    on signals exposed to a bias that cannot be measured.
- Complements: a test with a lag of 12 months instead of 6 for the accounting
  signals (late filings), and a verified academic reference on the gap between
  restated and as-first-reported data, to find when writing the report.
- The limit is disclosed in the report, with the Super Micro Computer example.

## Order of implementation

1. Steps 1 and 2.
2. Steps 3 and 4.
3. Step 5, once the risk-free rate is downloaded.
4. Steps 6, 7 and 8.
5. Step 9.

Each step ends with its check report and an audit pack for ChatGPT before the
next one starts.
