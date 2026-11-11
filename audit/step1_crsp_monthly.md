# Audit pack: steps 1-2, monthly CRSP panel and delisting returns

For the reviewer (ChatGPT). Please check the method, the code and the numbers.
Report anything wrong, risky or unclear.

## Goal

Build one row per stock and month from the CRSP CIZ monthly file, with correct
delisting returns and market equity. No universe filter yet: that is step 3.

## Files

- Code: `scripts/crsp_monthly.py` and `scripts/utils.py`
- Spec: `CleaningSpec.md`, steps 1 and 2
- Outputs (local, not in Git): `data/processed/crsp_monthly.parquet`,
  `crsp_distributions.parquet` and `crsp_monthly_report.json`
- Inputs: `data/raw/crsp_ciz_monthly_stock.csv`, `crsp_ciz_delistings.csv` and
  `crsp_ciz_monthly_market_indexes.csv`. Their SHA-256 hashes are in the report.

## Reference code reused

- JKP `bkelly-lab/jkp-data` (commit `b5695ea`), `src/jkp/data/aux_functions.py`:
  - `gen_crsp_sf`: columns, bidask flag, shrout in millions;
  - `prepare_crsp_sf`, monthly branch: delisting join, −30 % imputation, the
    `ret = 0` rule and compounding unless `MthDelFlg ∈ {A, P, V}`, plus
    `me_company`.
- Tidy Finance `chapters/wrds-crsp-and-compustat.qmd`: `mktcap = 0` becomes
  null, and `mktcap_lag` comes from a one-month shifted join.

## Deviations from the references, with evidence

1. **`me = MthCap / 1000`, not `prc × shrout`.** In 180 rows the price date is
   before the start of the current share count. CRSP's MthCap uses the shares at
   the price date. A check shows every gap is either this case or rounding.
2. **No ×100 on monthly volume** (JKP applies one). In our export, MthVol equals
   the sum of DlyVol (PERMNO 10000, 1986-01: 177,082 in both).
3. **274 delisting-month rows added.** These delistings happen in the month after
   the last CRSP row, which has no row of its own. JKP's left join drops these
   delisting returns (mean −12 %, bankruptcies included). The new row has
   `date = delistingdt`, `delist_row_added = True`, and its return is the
   delisting return (−30 % if missing and performance-related).
4. Returns without `delret` are kept exactly equal to MthRet. JKP's neutral
   `(1+ret)(1+0)−1` is skipped because it adds float noise.
5. NASDAQ volume adjustment and dollar volume move to step 3, since they need the
   exchange. `div_tot` is not computed, because `MthCumFacShr` is not in the
   export.

## Key checks (all passed)

| Check | Result |
|---|---|
| Stock fields identical across raw rows of a stock-month | 0 conflicts |
| Unique permno × month | yes |
| Unknown CRSP flag values | none |
| Delistings of stocks in the file matched to a month | 29,509 of 29,509 (19 others not in export) |
| Delisting return on a flag-N month (would double count) | 0 |
| Compounded delisting returns | M: 2,844, G: 547, added rows: 273 |
| −30 % imputations | 2,900 |
| Returns below −100 % | 0 |
| Value-weighted return of all securities vs CRSP `vwretd` | corr 0.99977, mean gap −0.002 %/month, 1,151 months |
| Returns above +300 % | 734, flagged and kept |

## Open questions for the reviewer

- Is adding the 274 delisting-month rows correct, or should they be handled
  another way?
- Is it right to trust MthCap over `prc × shrout` when the price is stale?
- Is the −30 % imputation (JKP, after Shumway 1997) acceptable, or should missing
  delisting returns stay missing?

## Reproduce

```powershell
cd Project
python scripts/crsp_monthly.py   # about 1 minute; needs polars
```
