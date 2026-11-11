# Audit pack v2: steps 1-2, answer to the audit of 2026-11-11

Answer to `Workspace/output/2026-11-11_audit_CRSP_etapes_1_2_pour_Claude.md`.
The first pack is `step1_crsp_monthly.md`. The new run is `run_id` in
`data/processed/crsp_monthly_report.json`, which also holds the SHA-256 of every
input and output.

## Answer to each finding

| # | Finding | Decision | What changed |
|---|---|---|---|
| 1 | D9 rows miss the return before delisting | **Fixed** | `pre_delisting_returns()` compounds the daily `DlyDelFlg = N` returns after the last monthly date, up to the delisting date. The `Y` row is left out. Then `ret = (1+r_pre)(1+delret)−1`. If no daily return is usable, `ret` is null (`missing_pre_delisting`). CRSP bridges days with a missing price: on our data, the product of available daily returns equals MthRet in 1,052 of 1,062 comparable months with such days. Reference cases: 65788 gives −22.7349 %, 12964 gives −79.8203 %. The script fails if they differ. |
| 2 | Only one-way delisting check | **Fixed** | Reverse check added: 236 flagged months have no record, all dated 1949-12-31 or earlier (the delisting file starts 1950-05-06). A/P keep MthRet. The 98 M/G become `missing_delist_record`. The script fails if such a month appears after 1950-05-06. These months are outside the sample (1963+). |
| 3 | 340 M months have a partial ret | **Fixed (decision D10)** | No more zero fill: when delret is unknown and not imputed, `ret` is null (`missing_delret`). `ret_crsp` keeps MthRet. The JKP `ret = 0` rule is also dropped: a missing MthRet with a delret gives a null ret (`missing_pre_delisting`). The backtest will report the weight of these positions. |
| 4 | Availability of delisting amounts | **Documented** | `delamtdt`, `delnextdt` and `delretmisstype` are kept. Convention in `CleaningSpec.md`: the delisting return is the holding return of the delisting month (CRSP and JKP). The stock leaves the universe at delisting, so this value feeds no signal. Proceeds are reinvested at the end of the delisting month. |
| 5 | Header CUSIP looks historical | **Fixed** | Renamed `hdr_cusip`. The historical CUSIP will come from the security history in step 3. |
| 6 | Partial `me_company` | **Fixed** | New flag `me_company_complete`: 1,393 partial company-months. `me_company` is defined as of `eom`. |
| 7 | Weak guards | **Fixed** | Null keys, dates or flags stop the script. Non-finite numbers, non-positive prices and shares, and MthRet < −1 stop it too. After the adjustment, all N/A/P/V months must keep `ret == ret_crsp` exactly. A null flag is allowed only on D9 rows. A delisting record on an N month stops the script. |
| 8 | Step 5 spec used MthRet | **Fixed** | `ret_exc = ret − rf`, with the validated total `ret`. |
| 9 | Counter computed before imputation | **Fixed** | Replaced by `ret_status_counts` and a full `delisting_crosstab` (flag × record × imputed × status), both computed after the adjustment. |
| 10 | Outputs of two runs could mix | **Fixed** | `utils.publish()` uses temp names that include the run id. It writes all outputs, renames them, then writes the report last with each output's SHA-256 and the run id. The index CSV and the daily CSV hashes are now in the report. |
| — | "177" in the script header | **Fixed** | Now 180. |

## New counts (run of 2026-11-11, v2)

| Item | Value |
|---|---|
| Stock-months + D9 rows | 5,210,620 + 274 = 5,210,894 |
| D9: rebuilt (observed delret / imputed) | 211 / 51 |
| D9: missing (no pre-delisting return / no delret) | 11 / 1 |
| M/G compounded (observed / imputed) | 547 / 2,841 |
| M with unknown delret → null | 340 |
| Null ret, total | 83,866 (83,409 missing MthRet + 457 incomplete) |
| −30 % imputations | 2,900 |
| VW return vs CRSP vwretd | corr 0.99978 over 1,151 months |

`ret_status_counts`: crsp 5,123,378 · missing_crsp 83,409 ·
crsp_plus_delret_imputed 2,841 · crsp_plus_delret 547 · missing_delret 341 ·
daily_plus_delret 211 · missing_delist_record 98 · daily_plus_delret_imputed 51 ·
missing_pre_delisting 18.

## Answers to the review criteria

- The table of the 274 D9 keys is in `data/processed/crsp_d9_reconciliation.csv`.
  Each row gives the month, the source, the window days, the pre-delisting part,
  the raw, imputed and used delret, the total, and the reason when a value is
  missing.
- The flag crosstab is `delisting_crosstab` in the report.
- The report lists the output hashes and the run id, so the counts can be matched
  to the Parquet files.

## Still open

- D3 sensitivity at −55 % for NASDAQ: to run at the backtest step.
- Why WRDS has no monthly row for the 274 delisting months: not established.
  The fix does not depend on it.
