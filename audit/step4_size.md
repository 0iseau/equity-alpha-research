# Audit pack: step 4, NYSE breakpoints and size groups

## Goal

Each month, compute the NYSE market-equity percentiles (1, 20, 50, 80 %) and
label every stock with a size group (nano, micro, small, large, mega). Add a
capped market equity `me_cap = min(me, NYSE p80)` for capped value weights. No
stock is removed (decision D7: any exclusion happens later, by a cost rule).

## Files

- Code: `scripts/crsp_size.py`, `scripts/download_french_data.py` (new) and
  `scripts/utils.py`
- Spec: `CleaningSpec.md`, step 4, and D7
- Inputs: `data/processed/crsp_universe.parquet` (checked against its report
  hash) and `data/raw/french/ME_Breakpoints_CSV.zip`, downloaded from the Ken
  French Data Library (`data/raw/french/manifest.json` has the URL, time and
  SHA-256)
- Outputs: `data/processed/nyse_cutoffs.parquet`, `crsp_panel.parquet` and
  `crsp_size_report.json`

## Reference code reused

- JKP `nyse_size_cutoffs`: the SQL aggregates (`QUANTILE_DISC`), copied; the
  NYSE filter uses our step-3 eligibility.
- JKP `classify_stocks_size_groups`: the group thresholds, copied.
- JKP `me_cap = min(me, nyse_p80)` (`market_returns`, `portfolio`).

## Deviations

1. The NYSE sample is our eligible NYSE stocks from step 3, using
   security-level me like JKP. Unlike JKP, it also requires US incorporation,
   which Tidy Finance also does.
2. No "mega" fallback for a month without breakpoints (JKP keeps it to match
   SAS). An eligible stock with no group stops the script; this never happens.

## Key results

| Check | Result |
|---|---|
| Months of breakpoints; ordered p1 ≤ p20 ≤ p50 ≤ p80 | 1,152; always ordered |
| NYSE stocks per month, 1963+ | 1,139 to 1,874 |
| NYSE shares by group | nano 1.0 %, micro 19.0 %, small 30.0 %, large 30.0 %, mega 20.0 % |
| Eligible stocks by group, count (1963+) | nano 18.8 %, micro 40.7 %, small 20.5 %, large 12.9 %, mega 7.2 % |
| Eligible market cap by group (1963+) | nano 0.3 %, micro 2.7 %, small 6.6 %, large 16.0 %, mega 74.5 % |
| vs Ken French NYSE breakpoints (756 months) | log corr 0.998 (p20), 0.9996 (p50), 0.9998 (p80) |

The gap with Ken French is below 1 % in the 1960s-70s, about −3 % on the median
in 1990-2019, and about −13 % in the 2020s. Two causes were checked:

- Ken French uses firm-level ME, with share classes summed; JKP and we use
  security-level ME. This explains most of the gap until 2019.
- In the 2020s, SPAC-like securities on the NYSE (43 named "ACQUISITION" in
  2022-04, mostly SIC 6799) seem to be absent from Ken French's count (1,416 vs
  1,228 stocks).

We keep the JKP convention. The question for the reviewer is whether that is
acceptable.

## Answers to the Astra audit (verdict "À CORRIGER")

To be checked quickly during the step 5 audit. New run: `5f371b20c0f4`.

| # | Finding | Action |
|---|---|---|
| 1 | BLOCKING: `me_cap` set to p80 when `me` is null (84,527 rows, 0 eligible) | Fixed: `me_cap` is null unless `me` and p80 are both known. New full-panel check: null if either is missing, else exactly `min(me, p80)`. Result: 84,527 null `me` = 84,527 null `me_cap` = 84,527 null `size_grp`; 10007/1988-01 is now null. Keys unchanged. |
| 2 | IMPORTANT: Ken French gap explained too firmly | Spec rewritten with the firm-level test (1990–2019: −3.4 % → −0.6 %; 1980s not explained). SPAC is now a hypothesis (51 names with "ACQUISITION", 41 SIC 6799; 118 firms still extra). 29,969 group changes with French bounds documented; French-bound sorts kept as a possible robustness test. |
| 3 | MINOR: "SQL copied word for word" | Wording fixed: aggregates copied, NYSE filter replaced by our step-3 eligibility. |
| 4 | MINOR: French comparison could miss a gap or a duplicate month | Added checks: French months unique, every sample month present, compared bounds > 0. |
| 5 | MINOR: downloader could overwrite a used vintage | Fixed: download all first; stop before writing if any file has new bytes; manifest written last via a temp file. Rerun: 4 files unchanged. |
| Step 3 | 9,043 counter covers 8,283 delisting months and 760 N months | Noted: the report key `nasdaq_vol_adjusted_from_last_active_interval` counts all rows that use the last active exchange, not only delisting months. |

## Quick check of the step 3 fixes

Please confirm briefly; there is no need for a full review.

- **NASDAQ volume in delisting months**: the exchange of the last *active*
  interval is used when the stock is not active at the date (9,043 rows). The
  reference case is PERMNO 10003, 1995-12, with `vol_adj` = 73,190.5 and
  `dolvol` = 400,260.55; the script fails if it differs. Note: the very last
  interval of 10003 is a 3-day "X / D" post-delisting interval, so the last
  *active* interval must be used.
- **Counters**: 22,948 delisting months in t+1 after an eligible formation
  (22,673 with a numeric return), and 25,481 next rows not eligible (24,235
  numeric).
- **New columns**: `prc_age_days` and `zero_volume` (execution flags for the
  backtest); the weight of unknown t+1 returns is in the report.
- **`read_verified`** now hashes and reads the same bytes.
