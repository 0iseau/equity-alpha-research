# Data

Private WRDS CSV files stay local in `raw/`. Their inventory is tracked in `raw/manifest.json`.
Six public FRED CSV snapshots and their source inventory are tracked in `raw/fred/`.
BAA10Y stays local because its Moody's notice restricts redistribution without written consent.

`preview/` contains only the column names of each raw CSV. No data rows are included.

## Public supplementary data

Run `python src/download_public_data.py`. Python's standard library is sufficient;
no FRED API key is required. Downloads stay local under `raw/public/`, in a new
timestamped folder for each run. Selected current-history CSVs from the verified
2026-10-22 collection are also published, unchanged, in `raw/fred/`. Sources,
citations, hashes and actual retrieval times are in that folder. The complete
ALFRED archives remain local and can be downloaded again with the script.

The default observation **and vintage** cutoff is **2025-12-31**, matching the end
of the local CRSP monthly market-index extract (1926-2025). This is a collection
boundary, not a chosen estimation or testing window. `--end YYYY-MM-DD` can change
it. We retain each series' full available observation history for flexibility and
warm-up; we do not extend it artificially back to the start of CRSP.

| Series | Native frequency | Requested history | Reason to collect |
| --- | --- | --- | --- |
| [VIXCLS](https://fred.stlouisfed.org/series/VIXCLS) | Daily close | 1990-01-02 to 2025-12-31 | Forward-looking equity uncertainty from option prices |
| [BAA10Y](https://fred.stlouisfed.org/series/BAA10Y) | Daily | 1986-01-02 to 2025-12-31 | Corporate credit conditions; spread in percentage points |
| [T10Y3M](https://fred.stlouisfed.org/series/T10Y3M) | Daily | 1982-01-04 to 2025-12-31 | Yield-curve slope and monetary/business-cycle conditions |
| [UNRATE](https://fred.stlouisfed.org/series/UNRATE) | Monthly, seasonally adjusted | 1948-01-01 to 2025-12-31 | Labour-market conditions, in percent |
| [INDPRO](https://fred.stlouisfed.org/series/INDPRO) | Monthly, seasonally adjusted | 1919-01-01 to 2025-12-31 | Real activity; index currently based on 2017=100 |
| [CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL) | Monthly, seasonally adjusted | 1947-01-01 to 2025-12-31 | Inflation environment; raw price index, currently 1982-84=100 |
| [NFCI](https://fred.stlouisfed.org/series/NFCI) | Weekly, ending Friday | 1971-01-08 to 2025-12-31 | Optional published financial-conditions comparison |

These are economically motivated **candidates**, not seven mandatory inputs and
not evidence of predictable alpha. NFCI overlaps credit and volatility information;
adding all series by default would increase redundancy and model-selection risk.
Daily returns and realised market volatility can later come from existing CRSP
data, so no duplicate equity-price download is needed. Quarterly GDP is omitted
for now because monthly activity data already cover that role at finer frequency.
NBER recession labels are retrospective and are not collected as a live signal.
Professor-required alpha factors and the risk-free series remain a separate choice.

## Historical availability and revisions

The script distinguishes current histories from archived information sets:

- `*_latest.csv`: FRED's current revised history, bounded by the observation cutoff.
  Useful for description and comparison; **not safe as a historical information set**.
  A 2025 cutoff does not remove revisions made after 2025.
- `*_realtime_*.zip` for monthly macro data and weekly NFCI: the official ALFRED
  **Observations by Real-Time Period** export, selecting every archived revision
  vintage on/before the cutoff in batches of 50. It retains the
  original CSV, revision intervals and README with historical metadata. These dates
  permit later reconstruction of the information set, within archive coverage.
- `*_snapshots_*.csv` for the three daily market series: **daily observations** as
  they were known at each calendar month-end, plus the first archive date and the
  exact cutoff. The script checks every requested vintage in the returned headers.
  These snapshots support monthly decisions **after** the snapshot date. They are
  not a complete daily information panel. Daily trading would need finer vintage
  collection and publication timing. Native observation frequency remains daily.

December 2025 monthly observations can exist in the current-history files while
being absent from the information available on 2025-12-31, because their first
release occurs in 2026. That difference is expected, not a gap to fill.

The month-end vintage grid keeps download volume manageable while retaining the
historical daily observations needed at monthly decisions. This collection cadence does not choose a trading
strategy or prove that a monthly regime model is effective. Records whose intervals
span several ZIP batches can appear in multiple exports; deduplicate identical
records when a future processing step combines them.

The [ALFRED documentation](https://alfred.stlouisfed.org/help/downloaddata) explains
the difference between an observation period and a vintage. Archive beginnings
differ: VIX 2010-11-22; BAA10Y/T10Y3M 2014-01-27; UNRATE 1960-03-15;
INDPRO 1927-01-26; CPIAUCSL 1972-07-21; NFCI 2011-05-25. The script reads these
dates from each official download form and records them in the manifest. An older
observation date inside the first vintage is a backfill, not proof of earlier
availability. Full strictly archived coverage of all six core candidates therefore
cannot be assumed before 2014. Earlier samples need separately justified sources
or explicit limitations. NFCI's 1971 history is not a signal available since 1971.

Within the complete monthly/weekly archives, an ALFRED record applies when
`realtime_start_date <= as_of_date <= realtime_end_date`; an empty end means open.
Do not select only initial releases: later revisions already known at the decision
date belong to the information set too. Missing/deletion records must remain
missing. The collector does not yet build an as-of panel.

ALFRED dates have day precision, not publication timestamps. A conservative future
implementation must require a vintage date **strictly before** the decision date,
then execute at a subsequent tradable time. Same-close signals cannot trade at
that close. A monthly reference date is not its release date; a Friday NFCI date
is not its release date either. A fixed one-month shift does not repair revisions.
Monthly macro observations must not be interpolated into synthetic daily releases.
The trading calendar and exact signal/execution convention still need implementation.

Index bases and definitions change across vintages. Inspect the archived README
before using older data, especially CPI's predecessor concept before 1981 and
industrial-production rebasing. Compute a future growth rate using both levels
from the **same** as-of vintage. [Cboe](https://www.cboe.com/tradable-products/vix/vix-historical-data)
also documents that current VIX methodology was introduced in 2003; earlier
history is reconstructed. [Chicago Fed](https://www.chicagofed.org/research/data/nfci/current-data)
explains the NFCI data and revisions. No series is automatically declared suitable
for a full historical backtest merely because it downloaded successfully.

## Reproducibility and checks

Each run preserves response bytes, official download forms, selected vintages,
POST fields where used, retrieval timestamps, SHA-256 hashes, source URLs, actual coverage,
missing counts and validation results in `manifest.json`. ZIP contents remain in
the original archive, including the provider's terms and metadata. Do not publish
raw downloads automatically; source-specific terms still apply.

Schema changes, nonnumeric values, duplicated dates, out-of-range observations,
future revision starts and overlapping revision intervals cause a failed run, rather
than silent corrections. Holidays and missing values remain as delivered; negative
yield spreads and negative NFCI values are valid. No filling, aggregation,
normalisation, signal selection or model estimation happens in this script.

If an ALFRED snapshot labels a numeric observation **after its vintage date**, the
raw response is preserved and the offending cell is listed under
`quarantined_future_observations`, excluded from eligible counts. A future as-of
panel must exclude those cells explicitly. Successful retrieval does not certify
that every cell in the provider's raw file is usable. This check detected a VIX
observation labelled 2024-09-02 inside the 2024-08-31 snapshot during collection.

Run offline validation checks with `python -m unittest discover -s tests -v`.
