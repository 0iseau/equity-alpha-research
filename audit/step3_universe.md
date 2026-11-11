# Audit pack: step 3, security info and eligible universe

## Goal

For each stock-month, attach the security information valid at that date and
flag whether the stock can be bought at the end of the month (`eligible`). Keep
the return of the next month (`ret_lead1`) for every eligible stock, whatever
its status in that next month. This gives no look-ahead and no lost delisting
months.

## Files

- Code: `scripts/crsp_universe.py`; `scripts/utils.py` (new `read_verified`)
- Spec: `CleaningSpec.md`, step 3, and decisions D1 and D2
- Inputs: `data/processed/crsp_monthly.parquet` (step 1-2 output, read only if
  its SHA-256 matches `crsp_monthly_report.json`),
  `data/raw/crsp_ciz_security_history.csv`, `resources/Siccodes49.txt` (copied
  from JKP) and the CRSP index file
- Outputs: `data/processed/crsp_universe.parquet` and
  `crsp_universe_report.json`

## Reference code reused

- JKP `gen_crsp_sf`: date-range join of the security info; the `common` and
  `crsp_nyse` definitions.
- JKP `prepare_crsp_sf` and `adj_trd_vol_NASDAQ` (copied): NASDAQ volume
  adjustment and dollar volume.
- JKP `crsp_industry`, `_parse_siccodes_file` and `ff_ind_class` (copied):
  `sic = 0` becomes null, plus the FF49 industries.
- Tidy Finance: the `usincflg = 'Y'` and `tradingstatusflg = 'A'` filters, and
  `siccd` from the security history.

## Deviations, with reasons

1. **No `conditionaltype`** in our export (JKP and TF use `RW`). We use
   `tradingstatusflg = 'A'` with `primaryexch ∈ {N, A, Q}` instead (D2).
2. **Eligibility at the formation date t**, with `ret_lead1` from the t+1 row.
   JKP and TF filter in the same month. Here the security history ends at the
   delisting date, so 22,341 delisting-month rows have no security info: a
   same-month filter would drop them.
3. **Not eligible if the stock delists during month t** (`MthDelFlg ≠ N`): it
   cannot be bought at the end of t.
4. No ×100 on dolvol: our volume is already in shares (step 1).

## Key results

| Check | Result |
|---|---|
| Input hash vs step 1-2 report | match (run `b051fbb62322`) |
| Overlapping security intervals | 0 |
| Rows without security info | 22,341, all delisting months (A 14,345, P 6,207, M 1,631, V 152, G 6). The script fails if an N month has none. |
| Eligible stock-months | 3,805,426; from 1963: 1,963 to 7,462 per month, at least 1,139 NYSE |
| Next-month returns kept although not eligible in t+1 | 25,481, of which 3,322 delisting months |
| Eligible with no next row | 3,659: last month 2025-12, plus 2 cases in 1930-32 |
| VW t+1 return of eligible stocks vs CRSP `vwretd` (1963+) | corr 0.99869, mean gap +0.03 %/month |
| FF49 missing among eligible | 2.5 % |

## Also: quick check of the step 1-2 fixes (v3)

The counter-review of v2 asked for one blocking fix (N1) and three smaller ones.
Please confirm briefly; there is no need to redo the full review.

- **N1**: a day with a price but no return now breaks the chain, and the D9
  return becomes null (`pre_delist_break` in `crsp_d9_reconciliation.csv`). All
  18 listed keys are now `missing_pre_delisting`, plus 11 others of the same
  type. The 65788 and 12964 values are unchanged.
- **N2**: before any filter, the daily rows of D9 stocks are checked for flags
  (only N/Y), duplicate days, finite returns of at least −100 %, and a valid raw
  delret. 263 exact duplicate daily rows were found and dropped; a conflicting
  duplicate stops the script.
- **N3**: status priority documented; the overlap is counted in
  `missing_pre_delisting_and_no_record` (4).
- **N4**: spec numbers corrected (732 returns above +300 %; 83,884 final nulls).
- Deferred to later steps: funding of late delisting proceeds (backtest) and the
  hash check on reading (done here with `read_verified`).
