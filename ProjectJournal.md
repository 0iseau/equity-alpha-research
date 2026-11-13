# Project journal: what was done, why, and how to defend it

Written on 2026-11-12, last updated on 2026-11-13 (results of the test of
version A: sections 8.10 and 8.11). Purpose: a single guide for **writing the report**, where
every step and every choice must be explained and justified. It consolidates the
history that used to sit in the context brief (`../CLAUDE.md`), in
`CleaningSpec.md` and in the audit packs.

How to read it:

- This journal gives, for each step: the goal, what was done, where the method
  comes from, the deviations and their reasons, the key figures, what the audit
  found, and the limits to disclose.
- **`CleaningSpec.md` stays the exhaustive technical record** (every check, every
  counter). When a figure is quoted in the report, take it from the JSON check
  report of the step in `data/processed/` (authoritative), not from memory.
- Figures below are those of the current runs (section 6.4) unless a date is
  given.
- Rule for the future: each new step (signals, backtest, alphas...) adds a
  section here when it is closed. `../CLAUDE.md` only keeps a one-line status.

Contents: 1 Timeline · 2 Method and working rules · 3 Raw data · 4 Cleaning,
step by step · 5 Data dictionary · 6 Audits across steps and reproducibility ·
7 Decision register D1–D21 · 8 Backtest rules, signals, predictions, portfolio,
freeze, **results of the test (8.10) and exploration after the test (8.11)** ·
9 Limits to
disclose · 10 Open items · 11 Incidents and lessons · 12 Sources to verify ·
13 Map to the report sections

---

## 1. Timeline

| Date | Event |
|---|---|
| 2026-10-14 | WRDS collection at the CEDIF (CRSP CIZ monthly and daily, security history, delistings, Compustat annual through CCM, link history, market indexes). Documented in `data/raw/manifest.json` (sizes, SHA-256). |
| 2026-10-22 | FRED / ALFRED collection checked (`scripts/data_download/download_public_data.py`, standard library only). |
| before 2026-11-04 | First attempt: a market-data audit (`src/audit_market_data.py`, tests, commit `ed8bc04`), developed with ChatGPT ("Astra") as developer. |
| 2026-11-04 | **Restart** (commit `eda4453`): the old audit is abandoned (still in Git). `ProjectWorkflow.md` written. Roles change: **Claude develops, Astra only audits.** |
| 2026-11-11 | Old scripts `data_cleaning.py` and `monthly_repetitions.py` and their outputs deleted; cleaning restarts from zero under `CleaningSpec.md` (JKP and Tidy Finance as references). Steps 1 to 10 implemented and audited one by one in the day. Scripts moved to `scripts/data_download/` and `scripts/data_cleaning/`. Repository switched to English. Git incident (section 11). |
| 2026-11-12 | Step 9 audit handled. Whole chain rerun from raw files, reproducibility defect fixed. Final audit of the cleaning, alignment on the references, counter-audit. Backtest rules D12–D21 validated by Danny; `ret_d1` added. Astra's audit of the backtest rules (verdict "to review", no defect in the cleaned data) handled; final rules validated by Danny (section 8.4). **Cleaning closed.** |
| 2026-11-13 | Signals: `3_signal_panel.py` written (join at the formation date, 23 market-scaled characteristics, ranks); data dictionary extended to the signal tables; audit by the separate agent (full recomputation, no difference), then lightened audit by Astra ("ready with reservations"); rule D26 and a dating test added. Ranks over the whole universe decided by Danny. **Signals closed** (section 8.6). |
| 2026-11-13 | Predictions: aim of the project restated and models chosen by Danny (boosted trees as the main model, ridge for robustness, raw excess return as the target). `scripts/predictions/1_predictions.py` written and tested on random numbers only; audit by the separate agent, two audits by Astra, rule D27. First fit launched for version A (section 8.7). |
| 2026-11-13 | Portfolio rules, backtest, order cap of 10 % and commission rule decided before any result; audits by the agent and by Astra; **strategy frozen** (`ee22d6708bdc`, sections 8.8 and 8.9). |
| 2026-11-13 | **Single out-of-sample test of version A: no alpha** (main result −5.09 % a year against FF5 and momentum, t = −5.13; section 8.10). Sealed table opened afterwards. |
| 2026-11-13 | Exploration after the test, decided by Danny: a patience rule brings the fund back to the market by making it passive; still no alpha (section 8.11, not out of sample). |
| 2026-11-13 (evening) | Deadline of the project. |
| 16 Nov, 23 Nov, 7 Dec 2026 | Project presentation sessions. |

What the first attempt had established (still valid, useful for the data
section of the report):

- the monthly CRSP CIZ file has one row per distribution event, not per
  stock-month; on repeated keys, price, return, market cap and volume are never
  in conflict (0 conflict);
- classification of repeated stock-months: 50,590 "distinct events only", 3
  "exact copies only", and 6,144 to review (3,333 where non-event fields differ,
  mostly name, ticker and NASD ids changing inside the month; 2,811 where the
  distribution count could not be reconciled). Step 1 settles all of them: the
  stock-level fields are never in conflict, and the events go to a separate
  table.

## 2. Method and working rules

### 2.1 References and their hierarchy

- **JKP**: Jensen, Kelly and Pedersen (2023), *Is There a Replication Crisis in
  Finance?*, JF. Python code `bkelly-lab/jkp-data`, local read-only clone at
  commit `b5695ea` (2026-11-10), files `src/jkp/data/main.py` and
  `aux_functions.py`. It reads the CRSP **CIZ** format, like our files.
- **TF**: Tidy Finance with Python, local clone at commit `4f915a9`
  (2026-09-14), chapters `wrds-crsp-and-compustat`, `value-and-bivariate-sorts`,
  `replicating-fama-and-french-factors`. Also CIZ.
- **Course**: Goyal's slides, lecture 1 (strategies) and lecture 3 (trading
  costs).

Rule: **JKP for the rigour of definitions, TF for the simplicity of the
implementation, the course wins in case of conflict.** Each step names the
function it reuses and justifies every deviation. Reference code is read, never
executed.

Why this is a good argument in the report: we did not invent a cleaning
procedure. Each choice is either a published convention or a deviation with a
stated reason and a measured effect.

### 2.2 Principles (non-negotiable)

1. **No look-ahead.** Each datum has an availability rule: annual accounts 6
   months after `datadate`; market data known at the close and tradable the next
   period; links and security attributes only inside their validity interval;
   macro data only through ALFRED vintages.
2. **No survivorship bias.** Dead stocks are kept and delisting returns are
   included.
3. **Missing stays missing.** Zero is not missing. Documented exceptions only
   (−30 % delisting imputation D3; JKP book-equity formula; high-low range
   carried forward).
4. **Fail closed.** An unexpected schema, value, key or duplicate stops the
   script. Unusual values are flagged, not removed.
5. **Raw data are immutable**; outputs are written atomically (temporary file,
   then replace) and only after a complete run.
6. **Traceability.** Every step writes a JSON report with a run id and the
   SHA-256 of inputs and outputs; every script reads its inputs only if their
   hash matches the report of the previous step (`utils.read_verified`,
   `read_raw_verified`).
7. **Statistical discipline.** Rules are fixed before results are seen; the
   strategy is frozen before a single final out-of-sample test.
8. **Licences.** WRDS data are never published; they are ignored by Git.

### 2.3 Development and audit process

- Claude develops; ChatGPT ("Astra") audits and modifies nothing.
- Each step ends with an **audit pack** (`audit/stepN_*.md`, Git-ignored, in
  French): goal, files, assumptions, commands to reproduce, control figures,
  limits, open questions. Astra's reports are in `../Workspace/output/`.
- Audit findings are judged on their merits before being applied.
- **Stopping rule**: one full audit per step, then corrections; the corrections
  are checked during the audit of the next step. Blocking findings and cheap
  important ones are fixed; the rest is documented.

Audit trail (for the report's "validation" paragraph):

| Step | Astra verdict | Outcome |
|---|---|---|
| 1–2 | "To correct", then counter-review of v2 | v3: trading breaks give a missing return (D9), no zero filling (D10). Closed. |
| 3 | Findings 1–5 | NASDAQ volume in delisting months, counters, execution flags. Closed. |
| 4 | "To correct" (1 blocking) | `me_cap` missing when `me` is missing; stronger French check; fail-closed downloader. Closed. |
| 5 | "Validated with reservations" | Stock-by-stock lead check, calendar per factor, verified read of the French ZIP files. Closed. |
| 6 | "Validated with reservations" | Second-route link check, minimum coverage per month. Closed. |
| 7 | "Validated with reservations" | Hand-made book-equity test, second writing of the formula, null-safe checks. Closed. |
| 8 | "To correct" (1 blocking) | Check findings fixed; blocking finding (restatements) not fixable with our data → decision D12. Closed. |
| 9 | "To correct" (2 blocking) | Exchange of the day; 14-day rule from the last valid price; observed-range counter. Closed 2026-11-12. |
| Final audit | "To correct" (1 blocking) | 10 findings, all handled (section 6.1). 15 of 15 files reproduced. |
| Counter-audit | "Validated with reservations" | `ret_signal_ok`; ten rules proposed (section 8.1). |
| Backtest rules | "To review" (4 blocking) | **Received, not handled yet** (section 8.3). |

## 3. Raw data

All in `data/raw/` (local, Git-ignored, never modified).

| File | Content and remarks |
|---|---|
| `crsp_ciz_monthly_stock.csv` (1.7 GB) | CRSP CIZ monthly, one row per distribution event. Cap and shares in thousands. |
| `crsp_ciz_daily_stock.csv` (22 GB) | Daily prices, returns, volume, bid/ask, high/low. No daily open. |
| `crsp_ciz_security_history.csv` | Dated attributes (share type, security type, exchange, US incorporation, trading status). 191,048 rows, 40,518 PERMNOs; intervals never overlap and have no gap. **No `conditionaltype`.** |
| `crsp_ciz_delistings.csv` | Delisting returns and reasons. Starts on 1950-05-06. |
| `ccm_fundamentals_annual.csv` | Compustat annual merged by WRDS with the CCM links (already `INDL`, `STD`, `C`, `D`). 21 items; no `txdb`, `itcb`. |
| `ccm_link_history.csv` | GVKEY–PERMNO links with dates; `LINKENDDT = 'E'` means still open. |
| `crsp_ciz_monthly_market_indexes.csv` | VW, EW and S&P, 1926-01 to 2025-12 (used as a check only). |
| `french/` | Ken French: NYSE ME breakpoints, FF3 with RF, FF5, momentum, daily factors. Vintage CRSP 202609, with a manifest. The downloader refuses to overwrite if the online file differs. |
| `fred/`, `public/` | FRED and ALFRED: VIX, BAA10Y, T10Y3M, UNRATE, INDPRO, CPI, NFCI, capped at 2025-12-31. |

Points to state in the report:

- **Sample**: the cleaned data keep the full CRSP history (1930-01 to 2025-12);
  the analysis sample is 1963–2025 (course convention, Compustat coverage, FF5
  from 1963-07).
- **Macro data are candidates only.** Full ALFRED archives really exist only
  since 2014 for the six main series; a `*_latest` file must never be used as a
  historical information set; one VIX observation dated 2024-09-02 is in
  quarantine. BAA10Y (Moody's) cannot be redistributed. No cleaned table uses
  FRED data so far.
- **Missing**: q-factors (Hou-Xue-Zhang, global-q.org), needed for the alphas;
  the commission series of Jones (2002), needed by rule D15.

## 4. Cleaning, step by step

Common conventions: Parquet outputs in `data/processed/`; time key `eom`
(calendar month end), `MthCalDt` kept as `date`; native units kept, except
market equity `me` in USD millions; full history kept.

Pipeline: step 1 → `crsp_monthly` → step 3 → `crsp_universe` → step 4 →
`crsp_panel` → step 5 → `crsp_panel_exc` → step 8 → **`crsp_panel_acc`** (final
monthly panel). Side tables: `ccm_links` (6), `compustat_annual` (7),
`acc_public` (8), `crsp_daily_agg` (9), `ff_factors_monthly` (5),
`nyse_cutoffs` (4).

### Steps 1 and 2 — Monthly panel and delisting returns

Script `scripts/data_cleaning/1_crsp_monthly.py`. Outputs `crsp_monthly.parquet`,
`crsp_distributions.parquet`, `crsp_d9_reconciliation.csv`.

**Goal.** One row per stock-month with a total return that includes the
delisting return, once and only once.

**What was done and why.**

- The raw file has one row per distribution event; stock-level fields are
  identical inside a month, so the panel is deduplicated and the 1,089,403
  events go to a separate table. 5,276,434 raw rows → 5,210,620 stock-months,
  40,437 stocks, 1930-01 to 2025-12.
- Delistings are joined on `(permno, month)` and compounded:
  `(1 + ret)(1 + delret) − 1`, unless the CRSP flag is A, P or V (JKP
  `prepare_crsp_sf`). Why: without delisting returns, the strategy would look
  better than it was (Shumway, 1997), especially for small, distressed stocks.
- **D3**: a performance delisting without a return gets −30 % (JKP, after
  Shumway): 2,900 imputations. Sensitivity planned: −55 % for NASDAQ (Shumway
  and Warther, 1999; 2,094 cases).
- `ret_status` documents how each return was built (`crsp`,
  `crsp_plus_delret[_imputed]`, `daily_plus_delret[_imputed]`,
  `crsp_partial_delisting`, and four `missing_*` reasons). `ret_crsp` and
  `delret_raw` keep the raw values.

**Deviations from the references, each justified.**

- **`me = MthCap / 1000`** instead of price × shares (JKP): in 180 rows the last
  price is older than the share count, and only `MthCap` uses the shares at the
  price date. All gaps are explained by this or by rounding.
- **Volume in shares**: JKP multiplies by 100, but in our export the monthly
  volume is exactly the sum of the daily volumes.
- **D9 — 274 delisting months added.** These stocks delist in the month after
  their last CRSP row; the JKP join would lose their delisting return. The added
  row's return compounds the daily returns up to the delisting with `delret`.
  If CRSP did not link a price to the previous one (a "trading break"), the part
  before the delisting is unknown and the return stays missing. Result: 244
  returns rebuilt (197 observed `delret`, 47 imputed), 30 missing (29 breaks).
  Reference cases: PERMNO 65788 (−22.73 %) and 12964 (−79.82 %).
- **D10 — no `ret = 0`.** JKP replaces some missing parts by 0. Here an unknown
  part makes the return missing, with the reason. A missing value is not a zero.
- `me_company` (all share classes) comes with `me_company_complete` (1,393
  partial company-months).

**Key checks.** Months without delisting keep `ret` exactly equal to `MthRet`.
The 29,509 delistings are all linked to a month. 236 months carry a delisting
flag without a record, all in 1949 or before (the file starts in 1950). 83,884
final returns are missing (83,409 because CRSP gives none). The value-weighted
return of all stocks follows the CRSP index `vwretd` (correlation 0.99978 over
1,151 months). 732 returns above +300 % are flagged, not removed.

**Later additions** (final audit): flag V (a part of the delisting
distributions is unknown) gets its own status `crsp_partial_delisting` (200
rows); delisting amounts can be known after the month (`delamtdt > eom`: 4,811
rows), see `ret_signal_ok` in section 6.3.

**Limit to disclose.** The delisting return is the holding return of the
position, assigned to the delisting month (CRSP and JKP convention). It can rest
on an amount paid later (median 2 days after the month end, 259 days at the
90th percentile).

### Step 3 — Eligible universe

Script `3_crsp_universe.py`. Output `crsp_universe.parquet` (whole panel with
flags).

**Goal.** Say which stocks a US long-only fund could buy at each formation
date, with no survivorship bias and no look-ahead.

**Filters** (TF, mapping of the old `shrcd 10/11`, `exchcd 1–3`):
`sharetype = NS`, `securitytype = EQTY`, `securitysubtype = COM`,
`issuertype ∈ {ACOR, CORP}` → flag `common`; `primaryexch ∈ {N, A, Q}` and
`tradingstatusflg = A` → `exch_main`; `usincflg = Y` → `us_inc`.

- **D1**: US incorporation required (TF; JKP does not). Reason: the mandate is
  "US equities".
- **D2**: our export has no `conditionaltype` (the field JKP and TF use to
  isolate regular trading). Substitute: active trading status and main
  exchange. Closer to TF than to JKP; the gap cannot be measured without a new
  WRDS export. A limit to disclose.
- `eligible` = `common`, `exch_main`, `us_inc`, `me` known, and **no delisting
  in the month** (a stock delisted during month t cannot be bought at the end of
  t).

**Key adaptation, and the main argument of this step.** Eligibility is judged
**at the formation date** (end of month t). The return of t+1 (`ret_lead1`) is
then **always kept**, whatever happens to the stock in t+1. JKP and TF filter in
the same month as the return: on our data this would drop the delisting month,
because for 23,114 of 29,528 delistings the security-information interval ends
before the month end. Among positions eligible in t, **22,948** have a
delisting month in t+1 (22,673 with a numeric return): these are the returns a
same-month filter would have lost.

**Other content.** Historical `siccd`, `cusip` and `naics` from the security
history (0 becomes missing); `ff49` industries from JKP's `Siccodes49.txt`
(missing on 2.5 % of eligible rows; 94,997 rows); Gao-Ritter NASDAQ volume
adjustment (JKP function copied); `dolvol`; execution helpers `prc_age_days`
(3,737 eligible rows with a stale price, 1,158 by more than 7 days) and
`zero_volume` (5,624 eligible rows). `eligible` is a universe filter: it does
not guarantee execution.

**Key figures.** 3,805,426 eligible stock-months. Since 1963: 1,963 to 7,462
stocks a month (4,563 on average), at least 1,139 NYSE stocks. Filter funnel
since 1963: 4,844,588 rows → `common` 3,782,727 → `exch_main` 3,717,129 →
`us_inc` 3,466,247 → known `me` and no delisting 3,449,977. Unknown t+1 returns
weigh 0.0097 % of eligible market equity a month on average. Value-weighted t+1
return of eligible stocks against `vwretd`: correlation 0.99869 over 756 months
(+0.03 % a month: the index also holds funds, ADRs and REITs).

**Audit corrections.** NASDAQ volume adjustment in delisting months uses the
exchange of the last active interval (9,043 rows; check case PERMNO 10003,
1995-12). Final audit: `vol_exch_transfer` flags months where the stock changes
side (NASDAQ or not); `vol_adj` and `dolvol` are then missing (2,297
stock-months). **For costs, use `dolvol_21d` and `dolvol_126d` of step 9.**

### Step 4 — NYSE breakpoints and size groups

Script `4_crsp_size.py`. Outputs `nyse_cutoffs.parquet`, `crsp_panel.parquet`
(adds `size_grp`, `me_cap`).

**What was done** (JKP `nyse_size_cutoffs`, `classify_stocks_size_groups`):
each month, percentiles 1, 20, 50, 80 of `me` among eligible NYSE stocks; groups
nano (< p1), micro (p1–p20), small (p20–p50), large (p50–p80), mega (> p80).
`me_cap = min(me, p80)` for capped weights.

**Why NYSE breakpoints**: course convention and Fama-French practice; otherwise
the thousands of tiny NASDAQ stocks would define the groups.

**D7 — all sizes are kept.** The size group is a label. A group may be excluded
later only by a rule on **costs and capacity, never on alpha alone** (Novy-Marx
and Velikov, 2016; lecture 3), and results are shown for three universes (D19).

**Key figures since 1963** (share of stocks / share of market equity): nano
18.8 % / 0.3 %; micro 40.7 % / 2.7 %; small 20.5 % / 6.6 %; large 12.9 % /
16.0 %; mega 7.2 % / 74.5 %. This table is the best justification for
value weights and for the three universes: micro and nano caps are 60 % of the
names and 3 % of the value.

**Independent check against Ken French's breakpoints** (756 months): log
correlations 0.998 (p20), 0.9996 (p50), 0.9998 (p80). Median gap of p50: 0.0 %
(1963–79), −1.3 % (1980s), −3.4 % (1990–2019), −13.4 % (2020–25). French counts
companies (share classes summed), JKP and we count securities: this explains
most of 1990–2019 (−0.6 % by company). The 2020s gap may come from SPACs (a
hypothesis). Choice: keep the JKP convention; no return is affected; about
30,000 group assignments would change with the French breakpoints (0.18 % of
market equity). Declared limit, possible robustness test.

**Deviation.** JKP puts a month without breakpoints in "mega"; here an eligible
stock without a group stops the script.

### Step 5 — Excess returns and factor table

Script `5_crsp_excess.py`. Outputs `ff_factors_monthly.parquet` (FF3, FF5 with
its own `_ff5` columns, momentum, `risk_free`, in decimals) and
`crsp_panel_exc.parquet` (adds `risk_free`, `ret_exc`, `ret_exc_lead1`).

- `ret_exc = ret − rf` with our validated total return; `rf` from Ken French
  (JKP uses CRSP `t30ret`, absent from our extract).
- No row is dropped (TF drops missing excess returns).
- Each model keeps its own factors: the FF5 market differs slightly from the FF3
  one (at most 0.08 %, cause not established) and SMB is built differently. FF5
  regressions start in 1963-07. Factors run to 2026-09; regressions stop at
  2025-12.

**Checks worth quoting.** Stock-by-stock timing: on 5,210,894 rows,
`ret_exc_lead1` of t equals `ret_exc` of the same stock in t+1 (the test fails
on 3.9 million rows if the wrong month's RF is used). **Market check: the
value-weighted t+1 excess return of our eligible universe against Fama-French
Mkt-RF has a correlation of 0.99999 over 755 months, mean absolute gap 0.009 %
a month; shifted by one month the correlation is 0.04.** This single number
validates universe, returns, delistings, weights and timing together.

### Step 6 — CRSP–Compustat links

Script `6_ccm_links.py`. Outputs `ccm_link_table.parquet` (32,306 links) and
`ccm_links.parquet` (4,125,224 linked stock-months, key `permno`–`eom`).

- **D5**: `LINKTYPE ∈ {LC, LU}` and `LINKPRIM ∈ {P, C}` (TF, more cautious than
  JKP, which adds LS and ignores LINKPRIM). Reason: one company's accounts must
  go to one primary security.
- Validity tested on the CRSP row date (`MthCalDt`, or the delisting date on a
  D9 row); with the calendar month end, 267 eligible links would be lost and 9
  would point to another company.
- No overlap by `permno` or by `gvkey`; zero duplicate key.

**Coverage of eligible stock-months since 1963**: 93.3 % by count, **98.1 % by
market equity** (1960s: 71.0 % / 92.6 %; from the 1990s: above 96 % / 97 %). By
size: nano 88.5 %, micro 92.5 %, small 95.0 %, large 97.2 %, mega 98.5 %.

**Left out by D5**: secondary share classes (flags J and N): 330 securities,
30,763 stock-months, 1.75 % of market equity (3.3 % in 2025-11). They stay in
the panel with returns and price signals, without accounting data. LS links: 18
securities, 0.05 %.

**Checks.** Second route (last link started before the date, not ended) gives
exactly the same table. Every month since 1963 has more than 80 % of market
equity linked (lowest 88.1 %, 1963-02). The 343,569 rows of the WRDS merge all
fall inside a raw link (99.1 % inside a kept link).

**Limits.** The link table is today's table (standard practice). 234 linked
`gvkey` have no accounts in our extract.

### Step 7 — Annual accounts and book equity

Script `7_compustat_annual.py`. Output `compustat_annual.parquet`: 335,244
fiscal years, 27,438 companies, one row per `gvkey × datadate`, 1950-06 to
2026-09, items in USD millions.

- 343,569 raw rows → 340,636 after removing the copies per linked PERMNO (2,933,
  no conflict) → 335,244 in USD (**D6**: USD only, like TF; 5,377 CAD rows and
  15 without currency removed).
- **Book equity, JKP word for word**: `pstk_x = coalesce(pstkrv, pstkl, pstk)`;
  `seq_x = coalesce(seq, ceq + pstk_x, at − lt)`;
  `be_x = seq_x + txditc − pstk_x`, missing if ≤ 0. Inside the formula only, a
  missing preferred stock or deferred tax counts as zero. `be_x` is positive on
  297,865 rows (88.9 %), set to missing on 12,856 (≤ 0), missing on 24,523.
- Negative `at`, `sale`, `che` set to missing (0, 143, 42 rows).
- Header fields `costat`, `fic`, `ipodate` are dropped: they describe the
  company as it is today (look-ahead).
- No "last report per calendar year" rule (TF): `gvkey × fyear` is already
  unique, and TF's rule would drop 632 transition fiscal years.

**Checks.** Hand-computed book-equity table tested at every run; second writing
of the formula on all rows; accounting identities; spot checks against annual
reports (Apple 2020: equity 65,339, sales 274,515, net income 57,411; IBM
2019).

**Limits to disclose.**

- **The extract is a CCM merge**: fiscal years closed before the listing are
  absent (example: Google's 2002–2003 accounts). 7.8 % of eligible linked
  stock-months (1.2 % of market equity) come before the first usable accounts.
  These stocks keep returns and price signals. Side effect: less Compustat
  backfill bias.
- **Accounts are in today's state** (restatements included): see step 8, D12.
- Without `txdb` and `itcb`, deferred taxes are missing on 56,279 fiscal years
  and count as zero in `be_x` (JKP convention).
- For signals: compare dates 12 months apart, not neighbouring rows (1,063
  shorter and 2,026 longer intervals).

### Step 8 — Availability of accounting data

Script `8_accounting_availability.py`. Outputs `acc_public.parquet` (usable
report per company and month, 4,048,344 rows) and **`crsp_panel_acc.parquet`**
(final panel: adds `gvkey`, `acc_datadate`, `acc_age_months`). Accounting values
stay in `compustat_annual.parquet` and are joined on `(gvkey, acc_datadate)`.

**D4 — the rule.** A report is usable from the end of month `datadate + 6` until
the next report becomes usable, or `datadate + 18` months at the latest; monthly
update. Example: a fiscal year ending 31 December 2019 serves formations from
the end of June 2020 to the end of May 2021.

**Justification.** JKP's mechanism (`lag_to_public`, 18-month maximum age) with
the **6-month lag of the course** instead of JKP's 4 (more cautious). Monthly
update rather than once in June (Fama-French): it fits a monthly rebalancing and
the course ("using most up-to-date data is preferable"). Value ratios will use
the market equity of month t (JKP; Asness and Frazzini, 2013).

**Deviations.** The "next report" is the next report in any currency: a newer
non-USD report replaces the old one and nothing is available (58,116 linked
rows). A duplicate stops the script (JKP keeps the first).

**Checks, the heart of the no-look-ahead argument.**

- Look-ahead test: on 3,710,004 rows with accounts, the report is always public
  at the formation date; age between 6 and 18 months.
- Second route (last public report of the company): zero difference on
  4,125,224 rows.
- **Truncation test**: hide all reports not yet public at T, rebuild, the past
  must not change: zero difference at 1975-06, 1999-12 and 2015-03.
- Negative tests: a 5-month lag is caught (323,608 rows), and so is the use of
  the next report (296,024 rows). Hand-written reference cases run at every
  execution.

**Coverage at formation, eligible stock-months since 1963** (count / market
equity): link 93.3 % / 98.1 %; usable report 85.5 % / 96.8 %; total assets
84.2 % / 96.8 %; **book equity 81.3 % / 94.3 %**; two fiscal years 77.6 % /
95.3 %. Book equity by size (count): nano 74.3 %, micro 77.2 %, small 85.2 %,
large 91.1 %, mega 95.2 %. Only 2,030,962 eligible stock-months have book
equity, sales, COGS, SG&A and interest together.

**Blocking audit finding → decision D12.** Compustat gives today's values, with
no filing date and no version history. A restated amount can enter a signal
formed before the restatement. Example: Super Micro Computer (`gvkey` 176567):
fiscal 2024 equity 5,417.2 in the table against 5,469.5 public in December
2024; fiscal 2017 sales 2,484.9 (2019 restatement) against 2,529.9 announced.
Apple 2009 sales: 42,905 after an amended filing, 36,537 first announced. This
is the limit of standard Compustat with a fixed lag (JKP, TF, Fama-French, the
course); fixing it needs a point-in-time database. **Not fixable with our
data**: handled by rule D12 (section 7).

### Step 9 — Monthly summaries of the daily file

Script `9_crsp_daily_agg.py` (about 10 minutes without cache). Outputs
`crsp_daily_min.parquet` (intermediate, 102 million rows) and
`crsp_daily_agg.parquet` (4,891,218 stock-months, key `permno`–`yyyymm`):
`rvol_21d`, `rvol_252d`, `beta_252d`, `dolvol_21d`, `dolvol_126d`,
`spread_quoted_21d`, `bidaskhl_21d`, `n_hl_observed_21d`, `ret_d1`, and the
observation counts.

**D11 — reduced scope** (deadline): only what serves a signal or the cost
model. Left out: 21-day maximum return, Amihud illiquidity, share of zero-trade
days.

**Method (JKP `prepare_daily`, `roll_apply_daily`, `bidask_hl`).** Windows of
"21, 126, 252 days" are 1, 6 and 12 calendar months; minimum observations 15,
60, 120; volatility is the standard deviation of daily excess returns; beta is
cov / var against the market; delisting rows excluded. Deviations: market and
risk-free from Ken French daily files (JKP builds its own); windows computed
from monthly sums in one pass.

**Spreads, the input of the cost model.**

- Quoted spread `(ask − bid) / midpoint`, monthly mean over at least 10 valid
  days (`ask > bid > 0`, spread ≤ 50 % of the midpoint; the cap removes 563,008
  quotes).
- Quoted spreads barely exist before the 1990s (coverage by market equity:
  0.3 % in the 1960s, 7.5 % 1970s, 12.6 % 1980s, 85.9 % 1990s). Hence the
  **Corwin-Schultz (2012) high-low estimator**, JKP code copied
  (`bidaskhl_21d`, at least 11 daily estimates). Either spread: at least 99.9 %
  of market equity in every decade.
- On 2,183,967 stock-months with both, rank correlation 0.71, medians 1.30 %
  quoted and 1.25 % high-low. **But high-low compresses the gaps across sizes**
  (same stock-months, quoted / high-low): mega 0.056 % / 0.545 %, large 0.114 %
  / 0.651 %, small 0.333 % / 0.927 %, micro 2.196 % / 1.657 %, nano 4.703 % /
  2.948 %. It overstates large-cap costs and understates small-cap costs: the
  reason for rule D14.
- JKP carries the last valid range forward on days without a trade price;
  `n_hl_observed_21d` counts the ranges really observed (51,018 stock-months
  have an estimate with none). Usable spread (quoted, or high-low with observed
  ranges): 99.1 % of eligible stock-months, 99.96 % of market equity.

**`ret_d1`** (added 2026-11-12 for rule D13): CRSP return of the first trading
day of the month (market calendar), missing if the stock has no return that
day. 4,766,718 known values. Reference case: PERMNO 14593, August 2020,
0.025198. Astra recomputed it from the raw CSV: 0 difference on all keys.

**Checks.** Second route on 101 stocks (largest relative gap 1e-13). Daily
returns compounded over the month equal the CRSP monthly return within 0.0001
on 99.99998 % of 4,672,805 months. Value-weighted mean beta 1.01. Cross-step
check with step 3: monthly adjusted volume equals the sum of daily ones on
2,502,768 months, 0 difference. Coverage by market equity: 12-month volatility
and beta 99.3 %, 6-month dollar volume 99.6 %, quoted spread 94.0 %. Median
quoted spread by size: mega 0.06 %, large 0.13 %, small 0.58 %, micro 2.8 %,
nano 8.5 %.

**Audit corrections (two blocking).**

- NASDAQ volume adjustment now uses the exchange of each day, not of the month
  end. Reference case PERMNO 62500, March 2000: mean daily dollar volume
  29,143,056 instead of 17,097,119. 1,636 one-month and 9,824 six-month values
  changed.
- The 14-day rule (a return whose previous price is older than 14 days is not
  used) now measures the gap from the last row **with a price**. Reference case
  PERMNO 37022, December 1978: daily volatility 1.05 % instead of 23.65 %. 40
  returns dropped. A project rule: JKP's CRSP branch does not apply it.
- A CRSP trading day missing from the French calendar now stops the script.

### Step 10 — Extreme values

No code. **No winsorisation** of returns in the cleaned data; extreme values are
flagged, not removed. Characteristics become ranks at the signal step, which
neutralises outliers without deleting them. JKP's 0.1 % / 99.9 % winsorisation
for factor regressions is a choice for the alpha step.

## 5. Data dictionary

`resources/data_dictionary.csv`: one row per column of the seven cleaned tables
(**155 columns**; 144 at the end of the cleaning, 146 after the final audit, 147
with `ret_signal_ok`, 148 with `ret_d1`, 155 with the seven columns added to
step 9 for the signals): meaning, unit,
source, **availability** (`key`, `t`, `interval`, `acc_6m`, `t+1`, `after_t`,
`today`) and **roles** (`identifier`, `universe`, `predictor`, `outcome`,
`benchmark`, `execution_cost`, `weight`, `audit`).

`scripts/data_cleaning/check_data_dictionary.py` stops if a column is missing or
extra, or if a role does not fit the availability (a decision role needs `key`,
`t`, `interval` or `acc_6m`; `t+1` and `outcome` always go together).

Why it matters in the report: look-ahead is prevented by construction, not by
care. Never used as inputs: `hdr_cusip` (`today`), `delamtdt`, `delnextdt`
(`after_t`), `ret_lead1`, `ret_lead1_status`, `ret_exc_lead1` (`t+1`).
Restricted use: `ret`, `retx`, `ret_exc` are predictors only where
`ret_signal_ok` is true; `me_company` needs `me_company_complete`; `ticker` is
not a key.

## 6. Audits across steps and reproducibility

### 6.1 Final audit of the cleaning (2026-11-12, "to correct", one blocking)

Astra reran the eight scripts (15 of 15 data files identical) and rebuilt HML
independently (2×3 sorts in June, 750 months): correlation **0.982** with the
Fama-French HML, mean gap −1.9 basis points a month. Ten findings, all handled:
monthly adjusted volume in exchange-transfer months (blocking,
`vol_exch_transfer`); late delisting amounts (check that no stock is eligible
again before the amount date); flag V status; FRED files restored byte for
byte; size and modification time of large raw files rechecked before
publishing; usable-spread coverage reported; `naics = 0` missing; checks no
longer take their population from the object under test; stale passages dated;
observed ranges counted only if accepted by the estimator.

### 6.2 Alignment on the references (2026-11-12)

For each problem found by the audits, the JKP and Tidy Finance code was
searched (table "What the references do about the problems found" in
`CleaningSpec.md`). Where a reference has a solution, our code follows it:
explicit sort after every `.unique()` and before floating-point sums (JKP
practice). Outputs unchanged byte for byte. **Ten problems have no solution in
the references**: spread combination, restatements, funding of late delisting
proceeds, unknown return of a held position, accounts missing before listing,
secondary share classes, execution at the close, the 50 % cap on quoted
spreads, NYSE breakpoints at the security level, the vintage of the French
factors. They became the backtest rules (section 8).

### 6.3 Counter-audit (2026-11-12, "validated with reservations")

15 of 15 files reproduced from raw files without cache. One fix: a late
delisting return could reach a signal through **another** security (15
stock-months next to another eligible class of the same company; 3,103 next to
an eligible stock of the same FF49 industry). New column **`ret_signal_ok`**
(`del_flag = N`): `ret`, `retx` and `ret_exc` are predictors only on source
rows where it is true, **before any lag, group, index or join to another
stock**. The signal step must test that changing a delisting return after t
changes no signal.

Documented limits: size and modification time do not prove identical bytes
across two reads; two runs at the same time are not supported; the direct check
of step 9 is a sample of 101 stocks.

### 6.4 Reproducibility and current runs

A first full rerun showed six outputs changing between runs: in step 1 the
product of daily returns of D9 rows was computed in an unfixed order
(`unique()` does not keep row order); 77 rows differed at the 16th decimal.
Fixed by sorting first. **Two full runs in a row now give 15 outputs identical
byte for byte** (the chain took about 6 minutes on 2026-11-12; step 9 alone
about 10 minutes when the daily file is converted again). Hashes of the seven
WRDS files and the five French files rechecked on 2026-11-12.

| Step | Script | Current run id |
|---|---|---|
| 1–2 | `1_crsp_monthly.py` | `591588b4ddfc` |
| 3 | `3_crsp_universe.py` | `675782030a3a` |
| 4 | `4_crsp_size.py` | `3a0b1171f186` |
| 5 | `5_crsp_excess.py` | `f920bd39db56` |
| 6 | `6_ccm_links.py` | `90aff624d621` |
| 7 | `7_compustat_annual.py` | `a20b514d1dab` |
| 8 | `8_accounting_availability.py` | `87be465f4640` |
| 9 | `9_crsp_daily_agg.py` | `7e9f0ff3a802` |

| Signals 1 | `signals/1_price_signals.py` | `212e648e3d9d` |
| Signals 2 | `signals/2_accounting_signals.py` | `2a6170765a81` |
| Signals 3 | `signals/3_signal_panel.py` | `ff5eda29ad08` |

Script 3 was run twice in a row after its last change: same SHA-256 for
`signal_panel.parquet` (`0f078361…e3b462`) and `signal_ranks.parquet`
(`c49d9e1b…2ca4be`). It takes about 7 minutes.

Run ids quoted in older documents are superseded. Scripts run from `Project/`,
one at a time, for example `python scripts/data_cleaning/4_crsp_size.py`.

## 7. Decision register

| ID | Decision | Justification | Alternative rejected |
|---|---|---|---|
| D1 | `usincflg = Y` | Mandate "US equities" (TF) | No filter (JKP) |
| D2 | Substitute for the absent `conditionaltype`: active status and main exchange | Field not in our export; declared limit | New WRDS export |
| D3 | −30 % for performance delistings without a return | JKP, after Shumway; sensitivity at −55 % for NASDAQ | No imputation (TF) |
| D4 | Accounts usable 6 months after year end, at most 18 months, monthly update | Course lag (more cautious than JKP's 4), JKP mechanism | 4 months; June-only update |
| D5 | Links LC/LU and P/C | One primary security per company (TF) | LC/LU/LS without LINKPRIM (JKP) |
| D6 | Compustat in USD only | No currency conversion needed for US stocks | Conversion (JKP) |
| D7 | Keep all sizes; exclude a group only by a cost and capacity rule fixed in advance | Never select on alpha; Novy-Marx and Velikov (2016) | Drop below NYSE p20 (FF) or nano only (JKP) |
| D8 | FF49 industries in the data; coarser grouping for neutralisation, to fix at the signal step | — | SIC divisions (TF) |
| D9 | Add the 274 missing delisting months | Otherwise delisting returns are lost | Lose them (JKP) |
| D10 | No zero filling of unknown returns | Missing is not zero | `ret = 0` (JKP) |
| D11 | Step 9 reduced to volatility, beta, dollar volume, spreads | Deadline; only what a signal or the cost model needs | Full JKP list |
| D12 | Keep accounting signals despite restatements; never call the bias small; versions A and B | See below | Point-in-time data; no accounting signals |
| D13–D21 | Backtest rules | Section 8.2 | Astra's proposals, section 8.1 |
| D24 | A window with a missing month gives no value | "Missing stays missing"; both audits | Index carried over the gap (JKP) |
| D25 | The flow items of a transition fiscal year are missing | A flow over less than 12 months is not an annual flow | Use it as it is (JKP) |
| D27 | A target is used in a fit only once it is known: end of the latest of its return month, the month of `delamtdt`, the month of `delnextdt` | A delisting return can rest on an amount paid later; found by Astra before any fit (3,952 targets, 895 known in a later calendar year) | Date every target at its return month |
| D15 (2026-11-13) | No commission in the main result on 1993–2025; one stress test at 6 then 4 cents per share | No series covers the period (Jones ends in 2000); the main number rests on measured costs only | A schedule of our own inside the main result |
| D26 | The 23 market-scaled characteristics are missing when the CRSP company of the month is linked to several Compustat companies | The accounts of one part would be divided by the market value of the whole (tracking stocks); 2,231 eligible formations | Largest company value by `gvkey` (JKP) |

**Rule D12 in full.** The restatement bias cannot be measured with our data, so
we never say it is negligible; we show that the conclusion does not depend on
it, or we say that it does. Two versions fixed in advance, same tests: **A**,
price signals only (momentum, volatility), not exposed, with a universe that
does not depend on accounts; **B**, price and accounting signals. If A has a
significant alpha, the conclusion holds without accounting signals, and B − A
is the **observed gap** (not a bound: the sign of the restatement effect is
unknown). If alpha appears only in B, the report says the result rests on
exposed signals. Complements: a 12-month lag test (explores late filings, does
not restore original values) and a verified reference on restated against
as-first-reported data (Lyle, Siano and Yohn, 2024, to check).

## 8. Backtest rules

### 8.1 Astra's proposals for the ten unsolved problems

Ranked by importance for the conclusion: execution (18.97 % of eligible
formations have a stale price, a bid-ask average or no volume); spreads
(36-month calibration of high-low on quoted); restatements (random ±10 %
shocks); 50 % quote cap; unknown return of a held position (three scenarios);
late delisting proceeds (receivable); accounts missing before listing (neutral
rank); NYSE breakpoints; secondary classes; vintage of the French factors. Full
table in `CleaningSpec.md`, "Rules proposed before the backtest".

### 8.2 Rules validated by Danny (2026-11-12, before any result)

Principle: **the main number already pays for realism.** Wherever a rule offers
a choice, the main version takes the cautious option, so that the alpha is not
followed by a list of excuses. A separate scenario is kept only where the choice
can change the conclusion.

| ID | Rule | Based on | Astra proposal not adopted |
|---|---|---|---|
| D13 | Signal at the close of t; trade at the close of the first trading day of t+1; the old portfolio is held that day. A stock bought earns `(1 + ret_lead1) / (1 + ret_d1) − 1`. No first-day return: order not executed, old position kept. Close-to-close shown as a comparison. | No signal and trade at the same close; Asparouhova, Bessembinder and Kalcheva (2013). No study prescribing a one-day lag was found. | Carry over 2 and 5 sessions, cancel horizon |
| D14 | Quoted spread; else raw high-low if ranges were observed; else mean of the size group in t. Cost = half spread × absolute weight change. Sensitivity: high-low everywhere. | Chen and Velikov (2023) | 36-month calibration (too few mega-cap pairs before 1984) |
| D15 | One-way commission added before May 1975, annual series of Jones (2002). **Series not yet in the project.** | Jones (2002) | — (new) |
| D16 | Unknown return of a held position: −100 %. Count and weight reported (0.0015 % a month on average, value-weighted). | Pessimistic single rule | Three scenarios |
| D17 | Delisting proceeds credited in the delisting month. Late amount dates are a declared limit. | JKP, TF, Shumway (1997) | Receivable scenario |
| D18 | Missing signal: median rank and a missing flag; no accounting item filled; complete-case result shown. Same for secondary classes and stocks without accounts yet. | Gu, Kelly and Xiu (2020); Bryzgalova et al. (2024) | — |
| D19 | Three universes fixed in advance: all sizes; above NYSE p20; cost rule D7. Value weights are the main weighting. | Hou, Xue and Zhang (2020); Avramov, Cheng and Metzker (2023) | — |
| D20 | Alphas against the Ken French files and against factors rebuilt from our data. | Akey, Robertson and Simutin ("Noisy factors") | ±bp stress on premia |
| D21 | Buffer: buy in the top 10 %, sell only outside the top 20 %. | Course; Novy-Marx and Velikov (2016) | — (new) |
| D12 | Unchanged (A and B, 12-month lag test). | Lyle, Siano and Yohn (2024) | Random ±10 % shocks |

Only **three comparisons** accompany the main number: A against B; one-day-lag
execution against close-to-close; the three universes.

Course cost model, to combine with these rules: turnover `Σ|Δw|` with weight
drift; price impact per dollar traded `λ × sqrt(order / ADV)` with λ = 0.025 /
0.015 / 0.010 (micro / small / large) and V0 = USD 100 million. The square root
was lost in the text extract of the slides and confirmed in the original slide
24 on 2026-11-12 (section 8.3).

### 8.3 Astra's audit of these rules — handled on 2026-11-12 (decision in 8.4)

Report: `../Workspace/output/2026-11-12_AUDIT_regles_backtest_pour_Claude.md`.
Verdict: **"to review"**. **No defect in the cleaned data**: `ret_d1` recomputed
from the raw CSV with 0 difference, 14 outputs equal to their recorded hashes.
The cleaning is therefore validated; every finding is about the specification of
the backtest.

What was done: finding 9 fixed (six more `ret_d1` source cases checked at every
run of step 9; dictionary role of `ret_d1` reduced to `audit`, with an explicit
"not a predictor, not a cost, not a proof of execution" note). The square root
of the course price-impact formula was confirmed in the original slide 24 and
restored in the documents. For findings 1 to 8, an amendment is proposed for
each rule in `CleaningSpec.md`, section "Audit of the backtest rules"; Danny
validated them the same evening with two simplifications (section 8.4). After
the fix, step 9 was rerun (run `86a807cdfece`): the six new cases pass and
`crsp_daily_agg.parquet` has the same SHA-256 as before. The same section lists
the source statements the audit corrected (Jones, Akey et al., Chen and Velikov,
Shumway, Bryzgalova et al.).

Summary of the findings:

| # | Severity | Rule | Finding (summary) |
|---|---|---|---|
| 1 | Blocking | D13 | A known first-day return does not prove a closing trade nor that the stock could be bought: 662,223 eligible formations have a known `ret_d1` with a non-trade close or no volume; 1,275 have a delisting on or before day 1. Separate the valuation return from the execution test. |
| 2 | Blocking | D13, D14, D19 | No participation cap and no price-impact rule on traded amounts. The impact formula in our brief lost the square root of the original slide (250 bp against 25 bp for micro caps in the slide example). |
| 3 | Blocking | D19 / D7 | The cost rule D7 can still select winning groups after the fact if its alpha or break-even cost uses the whole 1963–2025 sample. The main portfolio among the three universes must be named before computing. |
| 4 | Blocking for net results 1963–75 | D15 | The commission series is missing; zero until then would flatter exactly that period. Jones's "1 %" already includes the half spread: adding it to our spread would double count. Commissions do not vanish after May 1975. |
| 5 | Important | D16 | Missing is not a final loss: of 879 months without an ordinary CRSP return after an eligible formation, 869 have a known return later. If −100 % is kept, call it a stress convention and define recoveries. |
| 6 | Important | D17 | An ex post return is not always spendable cash: in a nano + micro value-weighted control portfolio, late terminal value reaches 0.444 % of capital in the worst month. |
| 7 | Important | D14 | Raw high-low and the quote cap are not cautious for all sizes (before 1993, nano: 8.72 % quoted against 5.19 % high-low). Define the donor population of the group mean. |
| 8 | Important | D12, D18, D20, D21 | Parameters still open: normalisation, weights, entries and exits, which factors to rebuild (FF3 minimum; RMW, CMA, MOM for FF5 and momentum), tie rules for the buffer. A stock with two price ranks of +1 and two missing accounting ranks scores +0.5. |
| 9 | Minor | Step 9, dictionary | Add independent source cases for `ret_d1`; the role `execution_cost` and the note "as a predictor" blur the use of a lagged value. |

Astra's source check (part C of the report) must be used before citing any
paper in the report.

### 8.4 Final backtest rules — validated by Danny on 2026-11-12 (evening)

Danny validated the amendments of section 8.3 with two simplifications and two
additions proposed by Claude. No signal, model or backtest result existed at
that time. **These rules replace sections 8.2 and 8.3 where they differ.**

Danny's requirement, which drives every choice below: not to end with concrete
results followed by "this may be wrong because we assume...". No backtest is
free of assumptions; the answer is that each assumption must be **standard in
the literature, cautious, or measured**. A reservation that cannot be removed is
turned into a number shown next to the main result, not into a warning.

**Rules as they now stand.**

| ID | Final rule | Why (argument for the report) |
|---|---|---|
| D13 (amended) | Signal with data up to the close of t. Orders (amounts) are frozen with the data of t and never replaced by the next candidate. An order is **filled** at the close of the first trading day of t+1 only if that day has a trade price (`prc_flag` = TR), a positive volume, and no delisting on or before it. Unfilled purchase: cash. Unfilled sale: position kept. The order expires at the end of that day. `ret_d1` only values the return; the fill flag is built from `crsp_daily_min` at the backtest step. | A known first-day return does not prove that a trade was possible: 662,223 eligible formations have one with a bid-ask close or no volume. Separating valuation from execution removes the objection "you could not have bought at that price". |
| D22 (new) | **Capacity and price impact.** Constant nominal capital of USD 100 million (course). Impact per dollar traded = `λ × sqrt(order / ADV)`, λ = 0.025 (nano, micro), 0.015 (small), 0.010 (large, mega). ADV = the smaller of `dolvol_21d` and `dolvol_126d` at t, both required. An order is capped at 1 % of ADV. One stress test at 0.5 %. | Course formula (slide 24, with the square root) and course coefficients; nano takes the micro coefficient and mega the large one, for lack of a calibration. The smaller of two horizons avoids using a short burst of liquidity. The cap makes a stock that is too small simply not bought: capacity is paid inside the main number. |
| D19 (amended) | **Two universes**, not three: all sizes (main), and above the NYSE 20th percentile. Value weights. The third universe (cost rule D7) is **dropped**. | The break-even rule of D7 used the alpha of the tested sample (a selection after the fact), and its replacement needed an arbitrary 10 % threshold. The order cap of D22 already does the job stock by stock, with no extra parameter. D7 remains true for the data: no size group is removed at the cleaning stage. |
| D15 (amended) | Commissions = the commission series of Jones (2002) **alone**, added to our spread (his "1 %" already contains the half spread). **No net result is shown on a period without commissions**: if the series is not in the project, the net result starts after May 1975 and is labelled as such. | Zero commissions would flatter exactly the years the rule is meant to correct. |
| D16 (wording) | Unknown return of a position held: −100 %, named **"full write-off convention"**, applied once to the lot held, no recovery booked; the mechanical end of the sample is excluded. Weight, effect in basis points and largest case are reported. | It is a stress convention, not a fact: 869 of 879 ordinary cases have a known return later. The weight is 0.0015 % a month on average on a value-weighted universe. |
| D17 (wording) | Delisting proceeds credited in the delisting month (unchanged). The stock of late proceeds on the positions really held is reported. The rule is not called cautious. | CRSP and JKP convention for the holding return; the cash may come later. |
| D14 (precision) | Quoted spread; else raw high-low with observed ranges; else the arithmetic mean over the eligible stocks of the same size group in t that have one of these two spreads (no imputed value as a donor). Cost = half spread × amount filled. Turnover is reported by source of cost. | Simple and reproducible. Not cautious for every size (before 1993, nano: 8.72 % quoted against 5.19 % high-low), so we do not say it is. |
| D18, D20, D21 (parameters) | Ranks scaled to [−1, 1]; missing → 0 after ranking, with a flag; fixed signal weights, not rescaled by stock; a stock with no signal at all cannot start a purchase. Buffer 10 % / 20 % on the book really held, ties by PERMNO. Rebuilt factors: market, SMB, HML, plus RMW, CMA and momentum if FF5 or momentum alphas are shown. t-statistics with a fixed HAC lag of 6 months. | Frozen before any result, so that no parameter can be tuned on the outcome. |
| D12 (unchanged) | Versions A (price signals only) and B (price and accounting signals), 12-month lag test. | See section 7. |
| D23 (new) | **How the conclusion is stated.** (1) **Version A is the main conclusion**; version B is a complement. (2) The main sample is 1963–2025 (course); the sub-period **1993–2025 is shown next to it**. | (1) Version A is not exposed to Compustat restatements, so that reservation cannot touch the conclusion. (2) From 1993 quoted spreads are observed and fixed commissions are gone: the reservations "old costs are estimated" and "commissions" become a measured comparison instead of a warning. |

**Comparisons shown next to the main number**: A against B; one-day-lag
execution against close-to-close; two universes; 1963–2025 against 1993–2025.
On the main portfolio, one cost breakdown: gross → half spread → commissions →
impact → net, with turnover submitted and filled and the share of cash.

**Risk accepted in advance.** Version A, net of costs, on 1993–2025 may show no
alpha. That would be the conclusion of the report, not a reservation.

**Reservations that remain whatever we do** (stated once, plainly): accounts in
today's state (version B only); costs before 1993 estimated, not observed; no
closing-auction data, so a closing trade price is a proxy for the execution
price.

**Still needed before the backtest**: the Jones (2002) commission series
(otherwise the net result starts after May 1975); the q and q5 factors; the
choice of the signals and the exact content of versions A and B.

### 8.5 Signals: list, construction plan and first two scripts (2026-11-12)

Full text: `SignalSpec.md` (version 0.3). Register: `resources/signal_list.csv`
and `resources/signal_exclusions.csv`, produced and checked by
`scripts/signals/0_signal_list.py`.

**Danny's requirement.** The list must be one that is historically known to hold
the information needed to find alpha, either from the literature or from an
industry adviser's brief. Nothing arbitrary.

**The adviser's brief** (systematic equity stock selection): several families of
signals (momentum, value, quality, earnings revisions, volatility, possibly
alternative data); compare a traditional multi-factor model with machine
learning (XGBoost, LightGBM, neural networks); neutralise sector and factor
exposures; judge out of sample after trading costs.

**Selection rule (the argument for the report).** Each of the 404
characteristics of the JKP library (code at commit `b5695ea`) gets a decision
and a reason. A characteristic is kept when its JKP formula (annual US branch)
can be computed from the final cleaned tables. The criterion is data
availability only, fixed before any signal or return was computed. An item
absent from our extract is unknown, never zero.

**What we claim, and what we do not.** We apply the JKP formulas to our annual
US extract; we do not claim to reproduce the JKP data set (JKP also use
quarterly and global files and their own market factors). Each accounting
characteristic carries a branch label: 27 where every item of every JKP branch
is in our extract; 82 where the first choice is, but a fallback is not (lower
coverage possible); 26 where the JKP first choice (`gp`, `xopr`, `ebitda`) is
absent and the Compustat definition is used (`sale - cogs`, `cogs + xsga`,
`oibdp`). Evidence for these 26: the joint identity fails on 421 of 256,728
rows (0.16 %).

**Result: 404 = 194 kept + 195 excluded for lack of data + 15 excluded by
scope.** Version A (market data only, rule D12): 59 (momentum 14, short-term
reversal 1, long-term reversal 12, seasonality 5, low risk 9, size and
liquidity 6, issuance 8, dividend yields 4). Version B adds 135 accounting
characteristics (investment 37, financial strength 27, fundamental momentum 16,
profitability 15, issuance 14, value 14, size 5, operating efficiency 4, low
risk 2, earnings quality 1).

**Step 9 reopened once for the signals (2026-11-12, decision of Danny).** The
audit showed that 30 characteristics were computable from the daily file but
left out by the reduced scope of step 9 (D11). Version A is the main conclusion
(D23) and had 44 characteristics, 31 of them windows of the same monthly
returns. Danny chose to add the 15 that need no regression against the market:
share changes, dividend yields, maximum returns, Amihud illiquidity,
dollar-volume variability, 52-week high, high-low volatility. The decision was
taken before any signal or return was computed; stopping at 15 rather than 30
is a choice made for the deadline, and the other 15 are reported as a choice of
scope. Controls of the addition (`CleaningSpec.md`, step 9): old columns
unchanged value for value; second route on 101 stocks; 17 reference values
computed apart in pandas, including two split cases; and a test of the share
factor (on the 36,056 months where it changes, the adjusted price matches the
return without dividends in 99.46 % of cases, against 0.09 % without the
factor). The cumulative share factor is today's vintage: it is only used as a
ratio between two dates of the same stock.

**What we cannot build, to state plainly**: earnings revisions (no analyst
forecasts) and alternative data, two families the adviser names; accruals, cash
flows, R&D and quality composites (21 Compustat items); quarterly
characteristics. The loss of predictive power from these families is not
identified. Coverage is uneven (37 investment characteristics; 31 of the 44 of
version A are windows of the same monthly returns): weights by theme and
correlations are reported.

**Construction plan**: three scripts copying the JKP functions (market signals;
accounting signals on a complete month grid per company; panel with
market-scaled characteristics and ranks in [-1, 1], missing = 0 with a flag).
Returns are masked by `ret_signal_ok` before any cumulative product. Stopping
checks: version A unchanged when all accounts are removed, truncation and
perturbation tests, acceptance cases, negative tests.

**Method** (Gu, Kelly and Xiu, 2020): target `ret_exc_lead1`; penalised linear
regression and gradient-boosted trees, estimated on 1963-1980, validated on
1981-1992, tested on 1993-2025 with a yearly refit (GKX lengths 18 / 12 / rest;
the test period is the sub-period of D23, by arithmetic, written before any
result).

**Audit by Astra (2026-11-12, verdict "to review", four blocking findings), all
handled in the list and the plan:**

1. the script only checked the names it kept → register of the 404, with
   `eq_dur`, `beta_60m` and `ivol_capm_60m` added (176 → 179);
2. 26 names rest on an absent first choice, other chains lose a fallback → rule
   rewritten, branch labels, no claim of exact replication;
3. the return index was not defined and could let a delisting return in → both
   indices built from the masked return;
4. the JKP signs (v1.0, 2026-10-28) were set with US data from 1972 to 2025,
   which covers the test → decision below.

Also fixed: exact guards of the JKP divisions (the plan wrongly said "negative
denominator → missing"), rank conventions for ties and empty months, deviations
on the company market value, counts on 404 names, role `predictor` for
`bidaskhl_21d`. The auditor recomputed 11 acceptance values (PERMNO 12490,
December 2000), now in `SignalSpec.md`, section 5, and found reference papers
on long-only US portfolios with machine learning (Esakia and Goltz, 2025;
Simon, Weibels and Zimmermann, 2026; Li, Wu and Zhou), not read by us yet.

**Scripts 1 and 2 built (2026-11-12, evening).** Danny chose to start the
build while Astra was still auditing the addition to step 9, to save time: the
code and its checks stay valid, and a correction of step 9 would only mean
running the scripts again. Two safeguards: nothing is declared closed before the
audits are back, and no return of a strategy or of a sorted portfolio is looked
at. `1_price_signals.py` gives the 59 market characteristics of version A
(run `212e648e3d9d`); `2_accounting_signals.py` gives 112 of the 135 accounting
characteristics (run `2a6170765a81`); the 23 others need the market value and belong to
script 3. Evidence, for the report: the 14 acceptance values recomputed by the
auditor are matched within 1e-8; a second route in plain numpy or Python finds
no difference in missing values and gaps below 2e-12; hiding the data after
1975-06, 1999-12 or 2015-03 leaves the earlier signals identical; replacing a
masked delisting return changes no signal, and the test was shown to detect the
change when the mask is removed; two runs give the same files. Details:
`SignalSpec.md`, section 4.5.

**Astra's audit of the step 9 addition (2026-11-12, "to review") and the local
share factor.** The six daily statistics were confirmed by an independent
recomputation from the raw CSV. One blocking finding, worth explaining in the
report as an example of a subtle look-ahead: the CRSP cumulative share factor is
today's vintage, exported with 12 decimals. For a stock that later goes through
many reverse splits, the factor of earlier dates is rounded, down to zero, and
the split-adjusted price (so the 52-week-high ratio, the high-low spread and
volatility, share changes and dividend yields) was missing **because of events
that happened after the formation date**. Exposure was small (143 eligible
stock-months with a zero factor, 2,255 with a level below 1e-6, out of 3.45
million) but it was a leak of future information through missing values, which
rule D18 turns into a flag that a model can read. Fix: step 9 builds a local
factor that starts at 1 and only uses past information (ratios of CRSP levels
when they are precise, dated split events otherwise). Evidence: only splits and
stock dividends move the CRSP factor (36,798 of 36,809 days); a simulated later
vintage leaves the local factor unchanged within 4.5e-6 and changes no missing
value; the auditor's reference cases pass. The correction also changed the
high-low spread of the cost rule for 11 stocks. Details: `CleaningSpec.md`,
step 9, and `SignalSpec.md`, section 8b.

**First audit by the separate agent (2026-11-12).** Verdict "ready with
reservations", no blocking finding. With its own code it recomputed 22 market
columns and 116 accounting columns on the whole universe and the local share
factor of all 40,058 stocks: no difference. It found a wrong rule without
effect today (two share events on the same day add up in CRSP, the code
multiplied them), a test that was too loose, and rounding noise in the share
changes that ranks would have amplified: all three fixed, step 9 output
unchanged. It also listed JKP conventions that count a missing month as "no
change" and the effect of changes of fiscal year end: kept as in JKP, counted,
declared, and put to Astra. Details: `SignalSpec.md`, section 8c.

**Lightened Astra audit (2026-11-12, "ready with reservations") and decisions
D24 and D25.** Astra confirmed the local share factor, the reading of DuckDB's
discrete quantile, and six values recomputed on stocks nobody had used (gap
2e-16). Two conventions of the JKP code were then replaced by stricter project
rules, on the recommendation of both audits and in line with "missing stays
missing": **D24**, a momentum, reversal, net-payout or dividend-yield window
gives no value when one of its months is missing (JKP treats the month as a zero
return or skips it; coverage of 12-month momentum goes from 91.6 % to 91.1 % of
eligible stock-months); **D25**, the income and cash-flow items of a transition
fiscal year (a year that ends less than 12 months after the previous report,
1,100 reports, all with a new fiscal-year-end month) are missing, because a
9-month flow is not an annual flow (GVKEY 001076: sales "growth" of 53.9 %
against a 9-month year). Both applied before any return was looked at; confirmed
by Danny on 2026-11-13 ("for now"). One limit stays declared: for the few changes of the CRSP
share factor that have no dated event, a later data vintage could change the
local factor. Details: `SignalSpec.md`, section 8d.

**Audit workflow from now on (Danny, 2026-11-12).** Each Astra audit uses about
half of Astra's token budget. So every audit has two stages: Claude first
launches a separate audit agent with a fresh context (read-only, with no access
to Claude's reasoning), handles its findings, and only then writes a lightened
prompt for Astra, which remains the audit that closes a step.

**Decisions** (`SignalSpec.md`, section 7). Scope of the daily
characteristics: decided, 15 added (above). Ranks over the whole universe:
decided on 2026-11-13 (section 8.6). Still open: the models (section 8.6) and
the constraint on portfolio weights by industry (12 Fama-French industries,
tolerance), to fix with the portfolio rules.

### 8.6 Signals: the panel, the ranks and the closing of the step (2026-11-13)

**What was built.** `scripts/signals/3_signal_panel.py` gives two tables, both
sorted by (`yyyymm`, `permno`):

- `signal_panel.parquet`: raw values of the 194 characteristics, one row per
  stock-month of the panel (5,210,894 rows; 59 of version A, 135 added by
  version B, of which 23 need a market value);
- `signal_ranks.parquet`: the 3,805,426 eligible stock-months, with one rank in
  [−1, 1] and one missing flag per characteristic.

The tables are about 3 GB each and do not fit in memory at once: the script
works by blocks of five years, and any later script must read them by columns
or by months.

**Rules** (`SignalSpec.md`, section 4.3).

- Accounting characteristics reach a stock-month only through `acc_datadate` of
  the panel (accounts 6 to 18 months old, D4), never by the month of the fiscal
  year end.
- The 23 market-scaled characteristics use the market value of the company at
  month t, only when every share class has a value (60 eligible formations
  without it, 3 of them with accounts).
- Ranks (D18): by month, over the eligible stocks only, average rank for ties,
  `s = 2(r − 1)/(n − 1) − 1`; a missing value gets 0 and a flag of 1.
- **Ranks over the whole universe, not inside industries** (Danny, 2026-11-13).
  Reasons written before any return was looked at: it is the rule of Gu, Kelly
  and Xiu; a rank inside an industry would remove the differences between
  industries, which a model may use, and would be noisy in small industries; it
  would not make the portfolio neutral anyway.
- **D26** (confirmed by Danny on 2026-11-13, after the audit by Astra): when the
  CRSP company of the month is linked to several Compustat companies (tracking
  stocks such as the Liberty groups), the 23 market-scaled characteristics are
  missing, because the accounts of one group would be divided by the market
  value of all groups. 2,231 eligible formations with accounts, 26 CRSP
  companies. Reference case: PERMNO 15997 (Braves Group), April 2023.

**How it was checked.**

- Acceptance cases of the specification: 11 of 11 within 1e-8 for PERMNO 12490
  at 2000-12. The accounts of fiscal year 1999 are attached from 2000-06 to
  2001-05 and in no other month.
- At 1975-06, 1999-12 and 2015-03: same output when all sources end at the date
  (panel, market characteristics, accounts closed at most 6 months before);
  version A unchanged without any account or link; ranks unchanged when stocks
  that are not eligible change; ranks recomputed with scipy (largest gap 3e-8,
  the precision of the stored ranks). Each test has a counter-test that shows it
  can fail.
- **Separate audit agent** (blank context): both tables recomputed in full with
  its own code, every month from 1930 to 2025: no difference in values, missing
  values, ranks or flags. No blocking finding; its findings on traceability, on
  the name of a test and on the dictionary were corrected.
- **Lightened audit by Astra**: "ready with reservations", no blocking finding;
  two stock-months that nobody had used recomputed exactly. Its two important
  findings gave rule D26 and the test with sources that end at the date.
- After D26, a comparison column by column with the run before: only the 23
  market-scaled characteristics, their ranks and their flags changed.

Details and the tables of findings: `SignalSpec.md`, sections 8e and 8f.

**To know for the models.** Lowest coverage among eligible stock-months since
1963: `pstk_gr3` 11.8 %, `pstk_gr1` 13.6 %, `seas_16_20na` 22.3 %; their rank is
0 with a flag of 1 almost everywhere, so a model can learn from the flag
(availability, age of the listing). `chcsho_1m` has only 12 distinct values in
its worst month. Two checks suggested by Astra were not done: by decade, the
share of the variance of the ranks explained by industry means (descriptive,
for the report), and a comparison with and without the flags on the validation
sample (to decide with the method).

**No return of a strategy, of a portfolio or of a sorted group was looked at
during this step.**

**Aim of the project, as Danny restated it on 2026-11-13.** The committee does
not expect a research question that compares machine learning with econometric
models; that framing came from an adviser who did not have the whole context.
The aim is to look for alpha as realistically as possible (no look-ahead, no
survivorship bias, costs), and not finding any is a result. The choice of the
method can be justified by theory and by the literature; a benchmark model
whose only purpose is to show what machine learning adds is not required. The
choice of the models is therefore still open, and section 6 of `SignalSpec.md`
is to be reread with this in mind before the first estimation.

### 8.7 Predictions: models, rules and the script (2026-11-13)

**Decisions of Danny, before any fit** (`SignalSpec.md`, section 7, decision 2).

- The committee does not ask for a comparison of machine learning with
  econometric models. The aim is alpha, looked for as realistically as
  possible; not finding any is a result.
- **Main model: gradient-boosted trees** (LightGBM). **Robustness model: ridge
  regression**, reported whatever it gives. Two models of different natures: if
  they agree, the conclusion does not rest on the model.
- **Target: the excess return of the next month, as it is.** A direction target
  (up or down) was rejected: it drops the size of the return, mostly follows
  the market, and the forecast only orders the stocks of a month.
- Left out: neural networks (first in the literature, but not auditable in the
  time available), a random forest on top of boosting (close forecasts for one
  more trial), the retrospective signed score.
- Why these two models: a very weak signal, 388 strongly correlated inputs and
  missing values that carry information. A ridge penalty shares the weight
  between correlated inputs and has a unique solution; shallow boosted trees
  are invariant to monotone transformations, hence consistent with ranks, and
  use interactions of low order. References to check before citing: Gu, Kelly
  and Xiu (2020), Lewellen (2015), Kozak, Nagel and Santosh (2020), Avramov,
  Cheng and Metzker (2023) for the objection on small stocks and costs.

**Rules** (`SignalSpec.md`, section 6, rules 1 to 9). One fit per return year
from 1993 to 2025; training on the return years 1963 to Y − 13, validation on
Y − 12 to Y − 1; the model that predicts is the one fitted on the training
sample with the values chosen on validation. Trees: squared error, learning
rate 0.03, depth 1 to 3, 50 to 200 trees, leaves of at least 0.1 % of the rows.
Ridge: seven values of the penalty from 1e-4 to 100. Choice on the mean of the
monthly squared errors of the validation months. Versions A (118 inputs) and B
(388 inputs).

**Why LightGBM.** The boosting engine of scikit-learn converts its inputs to
64-bit numbers: about 9 GB for version B, more than the machine can give.
LightGBM is the same family of algorithm in another implementation; every
setting is written in the script.

**What the audits changed, all before any fit.**

- **Separate agent**: no look-ahead found, own reimplementation identical on
  seven synthetic scenarios, all LightGBM settings checked. Three findings
  corrected: memory of version B (no copy of the matrix, inputs in a temporary
  file, bins from at most 500,000 training rows); a leak to the readers (from
  1994 on, the validation losses are out-of-sample errors inside the test
  period: they and the values chosen now go to a sealed table, and only the
  record of 1993 is shown); a self-test that let 9 of 20 mutations of the code
  pass (a second, plain writing of the rules was added to it).
- **Astra, first audit**: one blocking finding, real. A delisting return can
  rest on an amount paid later, and the script could use it before it was
  known. Measured on dates only: 3,952 such targets, 895 known in a later
  calendar year, 11 known twelve years or more after their month. **Rule D27**:
  a fit uses only the targets known at the end of December before its year.
  Also: the development years (1981–1992) and the test years are now in two
  files, so that the portfolio code cannot read the test by mistake.
- **Astra, counter-audit**: version A can be run, no finding left.

**Guard rails of this step.** The script shows no statistic that relates a
forecast to a return of 1993–2025. The sealed table is not to be opened before
the strategy is frozen. The portfolio and cost code is developed on the
forecasts of 1981–1992 only, which are not out of sample and never a result.
The settings can be reviewed on the record of 1993 and on these years only:
a change made after seeing the test period would be a new trial.

**To state in the report.** The model of year Y does not learn from the twelve
years before Y (they choose its values). Squared error with equal weights lets
small stocks weigh on the fit; GKX use a Huber loss for their trees. The
capacity is small (200 trees at 0.03): choices at the edge of the grid are
reported after the freeze, and the grid is not extended. Four sets of forecasts
(two versions, two models): the main one is version A with the trees, named
before any fit, and all four are reported.

### 8.8 Portfolio construction and commissions (2026-11-13, before any result)

**A rule of work changed.** Danny, 2026-11-13: the course does not prevail. Its
conventions are a simplified example; a choice is justified by theory (the
properties of the data and of the method) and by the literature. Decisions
already validated are not reopened.

**The candidates of each month** (`scripts/portfolio/1_candidates.py`;
`SignalSpec.md`, section 6, "Portfolio construction"). This step uses the
information of month t only and reads no return; the weights really held come
from the backtest, because they depend on the orders filled.

- **Top decile of the forecasts.** A decile is the usual sort of the literature
  (GKX form decile portfolios of their forecasts), and the buffer validated on
  2026-11-12 (bought in the top 10 %, kept in the top 20 %) already assumes it.
  The threshold was fixed before any result and no other threshold is tried.
- **NYSE breakpoints**: the 90th and 80th percentiles of the forecasts are
  taken over the eligible NYSE stocks of the universe. Theory: the smallest
  stocks are most of the names for a few per cent of the market value, and the
  extreme forecasts sit among them; with breakpoints over all stocks the top
  decile would be made of stocks that a fund of USD 100 million cannot hold.
  Literature (to check before citing): Fama and French (2008), Hou, Xue and
  Zhang (2020), and Avramov, Cheng and Metzker (2023) for the same criticism of
  machine-learning forecasts. GKX sort on all stocks: a declared difference,
  which answers in advance the most likely objection of the committee.
- Same quantile convention as the size groups of the cleaning (discrete
  quantile; a stock at or above the breakpoint is in). The "decile" therefore
  holds a little more than 10 % of the NYSE stocks. Stocks tied with a
  breakpoint are all in; shallow trees give many equal forecasts.
- Two universes (all sizes; at or above the NYSE 20th percentile), two models,
  flags for each. A stock with no observed characteristic cannot start a
  purchase.
- The script refuses the forecasts of 1993–2025 until the freeze is recorded in
  `resources/strategy_freeze.json`.

**Commissions (D15 amended).** The series of Jones (2002) is not a data file
and ends in 2000; no clean series exists for 1993–2025. Decision: **no
commission in the main result**, which keeps to the costs that are measured
(half spread) or taken from a stated formula (price impact), as the studies of
the trading costs of anomalies do (Novy-Marx and Velikov 2016, to check); and
**one stress test shown next to it**, with a commission of 6 cents per share
until 2004 and 4 cents from 2005, converted with the price of each trade. The
schedule comes from scattered figures for institutional investors (Greenwich
Associates and others, about 6 cents in the 1990s, 5 to 6 around 2004, 1 to 4
in the mid-2010s; to check before citing) and is cautious for a fund that
trades by algorithm. Sources read on 2026-11-13: the paper of Jones on the
Columbia and NBER sites; Markets Media ("Flashback Friday: commission rates",
"Cost to trade equities and ETFs"); Greenwich Associates, commission rate
study.

### 8.9 Backtest, order cap and freeze (2026-11-13)

**What exists.** `scripts/backtest/1_first_day.py` (could an order be filled on
the first trading day), `2_backtest.py` (the portfolio month by month with
execution and costs), `3_alphas.py` (alphas against CAPM, FF3, FF5 and FF5 with
momentum, Newey-West with 6 lags), `4_freeze.py` (the freeze record). Each has
a self-test on hand-written cases; the backtest's holds eight months computed
by hand and a check that no month depends on a later one. Description:
`SignalSpec.md`, section 6, "Backtest".

**Order rules validated by Danny** (after the audits of the agent and of Astra
on the portfolio): every stock tied with a breakpoint is in, and the mention
"ties by PERMNO" of D21 is withdrawn; a stock not held is bought in the top
10 % if it has at least one observed characteristic; a stock held is kept in
the top 20 %, and cannot be increased while every characteristic is missing; a
stock held that leaves the large universe or is no longer eligible gets a sale
order; a sale that cannot be filled leaves the position in the book.

**D22 amended: order cap at 10 % of the ADV, 1 % as the stress test.** With the
cap of 1 % written on 2026-11-12, the fund stayed 72 to 85 % in cash on
1981–1992: the simulation trades one day a month, and USD 100 million is very
large against the volumes of the 1980s. The main result would have been the
return of cash. Danny raised the cap to 10 % before the freeze, on the
mechanics of the development years only (cash, turnover, costs); **no return
of the strategy was computed or looked at**. With 10 % the fund is 67 to 82 %
invested and pays about 46 basis points a month of spread and impact. To
remember for the report: a reference for the 10 % limit is still to be found;
the all-sizes universe is mostly made of stocks that hardly trade (median
daily volume of a candidate: USD 5,636), and the large universe is the
realistic one.

**The freeze.** The rules are written in the freeze record with the hash of
every code file, of every input and of the forecasts; the scripts that read
1993–2025 refuse to run unless everything matches, never overwrite a result
and log each opening (`scripts/backtest/freeze_guard.py`). The trials made on
the development years are listed in the record (the order cap).

**Audits of the backtest.** The separate agent rewrote the monthly step on its
own: same weights, cash and record to 1e-14 on synthetic scenarios and on the
real inputs of 1981–1992, no look-ahead. Astra then refused the freeze as it
stood, rightly: the guards protected the script that runs, not its inputs nor
its utilities, and a second run could have overwritten the first result. This
was corrected before any opening. From the two audits, kept as rules: value
weights, with the concentration reported (one stock weighs up to 32 % of the
fund on 1981–1992, about 50 effective stocks); a closing trade price required
for a fill, which makes NASDAQ stocks impossible to trade before November 1982
(National Market) or June 1992 (SmallCap), a limit of the data; the cap of
10 % named a capacity scenario, with 1 % next to it. Added before the freeze:
one conditional diagnostic for the main result, because the share of the fund
that is invested rises during the test period and a regression with constant
betas is then misspecified (Ferson and Schadt 1996, to check). Postponed and
declared: the factors rebuilt from our data (D20). Details: `SignalSpec.md`,
section 6.

### 8.10 Out-of-sample test of version A (2026-11-13): no alpha

**The story in five sentences (for the report and the slides).**

1. The machine-learning strategy (boosted trees) is slightly below its factor
   benchmark before trading costs, not significantly, and clearly below it
   after the simulated costs.
2. The ridge regression is a little better: its alpha before costs is positive
   but not always significant (it is not against FF5 and momentum on the
   first-day execution), and it is negative after costs.
3. The fund trades a great deal (110 % of its value a month), and this turnover
   is what inflates the costs.
4. We therefore tried, **after the test**, a patience rule that trades less, to
   see whether another strategy would be worth trying (section 8.11).
5. Even so, the gain in performance comes only from passivity: the portfolio
   then follows the market more than it follows the forecasts. There is no
   alpha in either case.

**What was run.** The three frozen steps, once each, in order, under freeze
`ee22d6708bdc`: candidates (run `f713bd2fcd67`), backtest (`8c89f31d11d4`),
alphas (`83a28ed892ef`). No guard refused, no step was retried; the three
openings are in `resources/test_openings.jsonl` and the attempts in
`resources/test_steps/`. Results: `data/processed/alphas_A.csv` and
`summary_A.csv`. Files for the team: `reports/results_version_A.md` (same
content as here, with the reservations), `reports/tables_A.md` (every
configuration, period and factor model), figures
`reports/figures/A_cumulative_value.png`, `A_cash_share.png`, `A_costs.png`;
all produced by `scripts/reports/1_results_tables.py`.

Units in every table below: returns and alphas in % a year (monthly value
× 12); t-statistics in parentheses (Newey-West, 6 lags); costs in basis points
of the fund a month; turnover = purchases plus sales of a month in % of the
fund. "Gross" is the net return plus the costs paid that month, on the path of
the fund that paid them: it is not a strategy run without costs.

**Main result, as defined before the test.** Version A (market
characteristics), boosted trees, all sizes, first-day execution, order cap of
10 % of the ADV, net of half spread and price impact, before commissions,
1993–2025: **alpha against FF5 and momentum of −5.09 % a year (t = −5.13)**.

Table 1. Main configuration.

| | 1993–2025 | 1993–2008 | 2009–2025 |
|---|---|---|---|
| Excess return, gross | 9.00 | 5.74 | 12.07 |
| Excess return, net (t) | 4.76 (1.70) | −2.01 (−0.47) | 11.14 (3.68) |
| Volatility, net | 15.6 | 15.5 | 15.5 |
| Sharpe ratio, net | 0.31 | −0.13 | 0.72 |
| Market: excess return / Sharpe | 9.06 / 0.60 | 3.96 / 0.26 | 13.87 / 0.90 |
| Net return minus market (t) | −4.30 (−4.47) | −5.97 (−3.76) | −2.73 (−2.61) |
| Alpha net, CAPM | −3.81 (−3.74) | −5.64 (−3.50) | −2.24 (−1.91) |
| Alpha net, FF3 | −4.03 (−3.88) | −5.88 (−3.46) | −2.49 (−2.09) |
| Alpha net, FF5 | −4.37 (−4.12) | −6.44 (−3.48) | −2.54 (−2.26) |
| **Alpha net, FF5 + momentum** | **−5.09 (−5.13)** | −7.28 (−4.07) | −2.78 (−3.04) |
| Alpha gross, FF5 + momentum | −0.88 (−0.90) | 0.46 (0.26) | −1.85 (−2.05) |
| Alpha net + commission stress, FF5 + momentum | −6.96 (−6.59) | −10.13 (−5.57) | −3.76 (−3.94) |
| Half spread / price impact, bp a month | 21.4 / 13.8 | 42.0 / 22.6 | 2.1 / 5.6 |
| Costs, % a year | 4.23 | 7.75 | 0.93 |
| Turnover filled, % a month | 110 | 138 | 83 |
| Cash after the trades, mean % | 0.7 | 1.4 | 0.03 |
| Stocks held / effective stocks, median | 976 / 33 | 1,165 / 29 | 841 / 35 |
| Largest weight, maximum % of the fund | 35.7 | 33.8 | 35.7 |

Other numbers of the main configuration: conditional diagnostic (loadings
moving with the share invested) −4.78 % (t = −4.90); loadings of the net return
on FF5 and momentum: market 1.01, SMB −0.09, HML 0.07, RMW 0.04, CMA 0.01,
momentum 0.10, R² 0.87; value of 1 invested at the end of 1992: market 29.7,
fund after costs 7.1, and 28.6 for the gross index (the net return plus the
costs paid, on the positions really held; not a fund run without costs).

Table 2. Where the distance to the market comes from (main configuration,
points a year).

| | 1993–2025 | 1993–2008 | 2009–2025 |
|---|---|---|---|
| Fund before costs minus market | −0.07 | +1.78 | −1.80 |
| Costs (half spread and impact) | −4.23 | −7.75 | −0.93 |
| Fund after costs minus market | −4.30 | −5.97 | −2.73 |

Over the whole period the costs are 98 % of the distance. After 2009 they are
one third of it (34 %): the fund is already 1.8 point behind the market before
paying them. These shares are about the mean return against the market, not
about the factor-adjusted alpha. (−0.07 is computed on unrounded numbers;
9.00 − 9.06 from table 1 gives −0.06.)

Table 3. The ten configurations fixed at the freeze, alpha against FF5 and
momentum.

| Configuration | Gross, 1993–2025 | Net, 1993–2025 | Net + commissions | Net, 1993–2008 | Net, 2009–2025 | Costs bp | Turnover % | Net minus market |
|---|---|---|---|---|---|---|---|---|
| **Trees, all sizes, first day (main)** | −0.88 (−0.90) | **−5.09 (−5.13)** | −6.96 (−6.59) | −7.28 (−4.07) | −2.78 (−3.04) | 35.3 | 110 | −4.30 (−4.47) |
| Trees, large universe, first day | −0.71 (−0.67) | −4.64 (−4.32) | −6.25 (−5.56) | −7.06 (−3.59) | −2.18 (−2.58) | 32.9 | 111 | −3.77 (−3.54) |
| Ridge, all sizes, first day | 2.09 (1.22) | −4.01 (−2.28) | −7.04 (−3.92) | −7.39 (−3.08) | −0.32 (−0.15) | 51.5 | 130 | −2.78 (−1.53) |
| Ridge, large universe, first day | 2.41 (1.54) | −2.96 (−1.85) | −5.32 (−3.28) | −5.89 (−2.46) | 0.29 (0.15) | 45.3 | 137 | −1.48 (−0.85) |
| Trees, all sizes, close to close | −1.11 (−0.97) | −5.48 (−4.58) | −7.40 (−5.89) | −8.53 (−4.00) | −2.57 (−2.34) | 36.5 | 110 | −4.55 (−4.33) |
| Trees, large universe, close to close | −1.05 (−0.83) | −5.07 (−3.91) | −6.71 (−4.99) | −8.21 (−3.47) | −2.05 (−2.09) | 33.7 | 111 | −4.05 (−3.50) |
| Ridge, all sizes, close to close | 3.72 (1.82) | −2.50 (−1.24) | −5.57 (−2.74) | −4.39 (−1.49) | 0.23 (0.10) | 52.4 | 130 | −1.43 (−0.72) |
| Ridge, large universe, close to close | 3.57 (2.06) | −1.88 (−1.11) | −4.26 (−2.50) | −3.46 (−1.43) | 0.34 (0.16) | 46.0 | 136 | −0.34 (−0.19) |
| Trees, all sizes, first day, cap 1 % | −1.11 (−1.18) | −3.16 (−3.55) | −4.44 (−4.90) | −3.54 (−2.43) | −2.70 (−3.03) | 17.3 | 83 | −3.16 (−3.51) |
| Trees, large universe, first day, cap 1 % | −0.57 (−0.59) | −2.56 (−2.83) | −3.70 (−4.02) | −3.08 (−1.93) | −2.08 (−2.57) | 16.8 | 85 | −2.46 (−2.54) |

What the table says (measured):

- No configuration has a positive net alpha over 1993–2025, and none beats the
  market after costs.
- The two universes give the same answer. Close-to-close execution changes
  little for the trees.
- The ridge has a positive gross alpha. Against FF5 and momentum it is not
  significant on the first-day execution (t = 1.22 and 1.54) and reaches 2.06
  only close to close in the large universe, an execution that a real order
  cannot have. Against CAPM, FF3 and FF5 its t-statistic is above 2 in most
  cells (11 of the 16 gross cells of 1993–2025 in `reports/tables_A.md`, for
  example 2.08 and 2.51 against FF3 on the first day): the gross alpha
  shrinks as factors are added (all sizes, first day: 4.09 % against CAPM,
  3.49 % FF3, 2.55 % FF5, 2.09 % FF5 and momentum). Net, it is negative, significantly so in the
  all-sizes universe (t = −2.28), and near zero after 2009.
- The cap of 1 % is less negative only because the fund trades less and keeps
  12.4 % of cash on average.
- The commission stress removes a further 1.9 point a year from the main
  configuration.

**Mechanics measured** (main configuration). Costs through time, in bp a
month: 95 in 1993–1996, 85 in 1997–2000, 52 in 2001–2004, 26 in 2005–2008, 16
in 2009–2012, about 5 from 2013. Cash 8.9 % on average in 1993 (the fund starts
in cash), almost zero from 1997. The largest position is above 10 % of the fund
in 226 months of 396. 97.4 % of the amounts traded pay a quoted spread. The
tree forecasts are coarse: up to 931 stocks tie with a breakpoint, and the top
10 % equals the top 20 % in 34 months (43 in the large universe); the ridge
has no ties.

**Reading (interpretation, not measurement).** The answer to the question of
the project is no: the strategy is not worthwhile for a manager.

- Turnover destroys the result: about thirteen times the value of the fund is
  traded each year, and the costs take what separates the gross alpha from the
  net alpha.
- There is no gross alpha to protect in the main model: the fund behaves like
  the market (beta 1.01, R² 0.87).
- Value weights concentrate the fund in a few very large stocks (33 effective
  stocks), where a monthly forecast has least to say; this is probably why the
  two universes agree.
- Cash does not explain the result, and cheaper trading after 2009 does not
  rescue it (the gross alpha of the trees is then negative).
- The result agrees with the objection that machine-learning forecasts earn
  their returns in stocks that are hard to trade, at a turnover that costs
  erase (Avramov, Cheng and Metzker 2023; to check before citing).

**Sealed table, opened after the results were written.** Trees: depth 3 (the
deepest allowed) chosen in 19 years of 33, depth 2 in 12, depth 1 in 2; 50
trees in 11 years, 100 in 15, 200 in 7; only 6 years strictly inside the grid;
the worst setting of a year is on average 0.48 % above the best in validation
loss (almost flat). Ridge: penalty 1 in 17 years, 0.1 in 14, 0.01 in 2; never
at an edge. The grid is not extended. Reading: the tree model extracts little
more than the mean, whatever its size.

**Reservations to state with these results.** One main result named in
advance and many secondary numbers (a t near 2 among them is not evidence);
gross is not a costless strategy; the order cap of 10 % has no source; costs
are a model (measured spread, impact formula, all trades in one day a month,
no commission in the main number); value weights with no cap; coarse tree
forecasts, squared error, a grid that binds on depth; the model of year Y is
fitted on data up to Y − 13; Ken French factors only (D20 postponed, no
q-factors).

**Audit of the results by a separate agent (2026-11-13)** (blank context;
report: `Workspace/output/2026-11-13_AUDIT_AGENT_resultats_test_A.md`).
Verdict: ready with reservations, no blocking finding. Recomputed on its own:
the 361 rows of `alphas_A.csv` and the 30 rows of `summary_A.csv` (own
Newey-West, largest gap 1e-13); the ten configurations of the backtest with
its own monthly step (1e-15); the candidate flags from the forecasts (no
difference); the tables and figures (byte for byte); the 52 variants of
section 8.11 (1e-15, no look-ahead). One opening and one attempt per step;
every frozen file still has the hash of the freeze. Four findings in the text,
all corrected: cash in 1993 is 8.9 %, not 11 % (a column misread); the note of
results now refers to the exploration; the gross alpha of the ridge has a
t-statistic above 2 against CAPM, FF3 and FF5, which the text denied; the
side effect of trading every k months on cash is stated. Minor wording points
were corrected where cheap. Not verified by the agent: the forecasts themselves and the
citations.

**Lightened audit by Astra (2026-11-13)** (report:
`Workspace/output/2026-11-13_AUDIT_ALLEGE_resultats_test_A_pour_Claude.md`).
Verdict: yes, the step can be closed; no blocking finding; no new run needed.
The reading of the test candidates by the exploration script after the end of
the test is compatible with the freeze and leaves version B its status. Done
after it: table 2 computed on unrounded numbers (−0.07 instead of −0.06) with
the share of the costs; a paired measure of the patience rule added to 8.11;
the conclusion on the ridge limited to the patience rule; "gross" named a
reconstructed index. To keep in the report and on the slides: the 52 variants
were explored after the result of A was seen; a gross alpha of the trees that
is not significant does not show that the forecasts hold no information, nor
that predictability declined after 2009; an almost flat validation loss does
not compare the model with a constant forecast; the multiples of wealth come
from a fund of constant size. With one portfolio a GRS test is the test of
its alpha: not done, and not needed.

**Version B** (market and accounting characteristics) ran later the same day
through the same frozen scripts: section 8.12.

### 8.11 Exploration after the test: a patience rule (2026-11-13, not out of sample)

**Status.** Decided by Danny after the result of version A was known, to see
whether another strategy would be worth trying. Everything in this section was
run on 1993–2025 with the result of 8.10 known: it is an in-sample diagnostic
and must be presented as such, after the main result. It replaces nothing.

**Why.** The test shows a turnover of 110 % a month and costs of 4.2 % a year.
The question is whether the loss disappears when the fund trades less, and if
so, whether what remains is skill.

**What was varied** (`scripts/exploration/1_post_test_variants.py`; the frozen
monthly step is imported unchanged, and with the frozen parameters the script
reproduces the test month by month). Execution, order cap, costs and
regressions are those of the frozen chain.

- Patience p: a stock held is kept while it was in the top 20 % of the
  forecasts in at least one of the last p months (frozen rule: p = 1).
- Orders sent only every k months (frozen rule: k = 1). Side effect: an order
  capped or not filled waits k months, so the fund holds more cash in the
  1990s (ridge, k = 12: 80 %, 53 % and 46 % in 1993 to 1995). The patience
  rule does not have this effect.
- A cap of 5 % on target weights (frozen rule: none).

Table 4. Trees, all sizes, 1993–2025 (market excess return: 9.06 %).

| Rule | Net minus market | Alpha net, FF5 + mom. | Alpha gross, FF5 + mom. | Costs bp | Turnover % | Effective stocks |
|---|---|---|---|---|---|---|
| **Frozen rule (the test)** | −4.30 (−4.47) | −5.09 (−5.13) | −0.88 (−0.90) | 35.3 | 110 | 33 |
| Patience 3 months | −0.88 (−1.35) | −1.36 (−2.39) | −0.35 (−0.61) | 8.5 | 33 | 63 |
| Patience 6 months | −0.71 (−1.44) | −1.03 (−2.38) | −0.62 (−1.47) | 3.5 | 15 | 92 |
| **Patience 12 months** | −0.33 (−0.82) | −0.47 (−1.49) | −0.28 (−0.97) | 1.6 | 6 | 128 |
| Orders every 3 months | −1.06 (−1.26) | −1.96 (−2.43) | −0.61 (−0.75) | 11.1 | 37 | 32 |
| Orders every 6 months | −0.75 (−0.79) | −1.44 (−1.79) | −0.71 (−0.87) | 5.7 | 20 | 32 |
| Orders every 12 months | −0.98 (−1.19) | −1.53 (−1.93) | −1.13 (−1.44) | 2.9 | 11 | 28 |
| Weight cap of 5 % alone | −3.69 (−3.83) | −4.52 (−4.52) | −0.19 (−0.20) | 36.4 | 109 | 50 |

Table 5. Ridge, all sizes, 1993–2025.

| Rule | Net minus market | Alpha net, FF5 + mom. | Alpha gross, FF5 + mom. | Costs bp | Turnover % | Effective stocks |
|---|---|---|---|---|---|---|
| **Frozen rule (the test)** | −2.78 (−1.53) | −4.01 (−2.28) | 2.09 (1.22) | 51.5 | 130 | 28 |
| Patience 3 months | −1.03 (−0.78) | −2.01 (−1.65) | 0.05 (0.04) | 17.5 | 50 | 45 |
| Patience 6 months | −0.59 (−0.57) | −1.18 (−1.34) | −0.31 (−0.36) | 7.4 | 24 | 67 |
| Patience 12 months | −0.40 (−0.46) | −0.99 (−1.64) | −0.61 (−1.00) | 3.3 | 10 | 102 |
| Orders every 6 months | −1.34 (−0.84) | −1.71 (−1.30) | −0.64 (−0.48) | 8.4 | 24 | 21 |
| Orders every 12 months | 1.30 (0.89) | 1.75 (1.23) | 2.36 (1.60) | 4.2 | 11 | 20 |

All 52 variants (two models, two universes, three periods):
`reports/exploration/post_test_variants_A.csv`; note for the team:
`reports/exploration_post_test_A.md`.

**What it shows (measured).**

- With a patience of 12 months the tree portfolio is 0.33 point a year behind
  the market (t = −0.82) instead of 4.30; costs fall from 35 to 1.6 bp a month
  and turnover from 110 % to 6 % a month. The improvement is regular in p.
- No variant has a significant positive alpha. For the trees the net alpha
  stays between −0.5 % and −2 % once trading is slowed.
- The alpha before costs does not rise when trading slows; for the ridge
  under the patience rule it falls from 2.09 % to about zero.
- The weight cap alone changes little (net alpha of the trees −4.52 %).
- The only positive net alphas (ridge, orders once a year: 4 cells of 52, the
  largest 1.75 %, t = 1.23) are not significant, have a
  neighbour of the opposite sign at six months, and depends on the month in
  which the year starts.

**Reading (interpretation).** The patience rule brings the fund back to the
market by making it passive: it stops acting on most of the forecasts, holds
four times as many effective stocks and earns the market return less small
costs. Measured on the same 396 months (trees, patience of 12 months against
the frozen rule): the net return gains 3.97 points a year, of which 4.04
points are costs no longer paid and −0.07 point is gross return; the
volatility of the gap to the market falls from 5.9 % to 2.0 % a year; the
gross alpha differs by 0.60 point (t = 0.69). The gain is thus the costs no
longer paid; better selection is not established. Under the patience rule the
gross alpha of the ridge goes from 2.09 % to about zero (it stays at 2.36 %,
t = 1.60, with orders once a year, so this holds for the patience rule only).
A gap to the market that is not significant does not prove that the fund
equals the market, and the t-statistics of this section are descriptive: the
rules were chosen after the result was seen. Trying a further variant of this strategy is therefore not worthwhile;
a different one would need forecasts that last longer or trades that cost
less, and would need its own sample to be tested.

### 8.12 Out-of-sample test of version B (2026-11-13): the complement confirms A

Full note: `reports/results_version_B.md`; all numbers: `reports/tables_B.md`;
figures: `reports/figures/B_*.png`.

**What was run.** The forecasts of version B (194 characteristics: the 59
market ones and 135 accounting ones) finished at 16:38 local time, after 141
minutes of fitting (run `d78f1bbbbbef`). Their report shows the frozen
prediction script and the inputs, settings and calendar recorded in the freeze.
The three steps of the test were then run once each, with no retry (candidates
`feb21459bbc2`, backtest `ca7630c772f5`, alphas `db7e90ae9d97`), under freeze
`ee22d6708bdc` and after the three steps of A. No rule was changed between A
and B. The forecast file of B did not exist at the freeze, so its hash is in
the log of the openings of the test, not in the freeze record.

**Result (1993–2025, % a year, Newey-West t-statistics with 6 lags).**

| Main configuration (trees, all sizes, first day, cap 10 %) | Version A | Version B |
|---|---|---|
| Alpha against FF5 + momentum, net | −5.09 (−5.13) | −5.54 (−4.52) |
| Alpha against FF5 + momentum, gross | −0.88 (−0.90) | −1.17 (−1.01) |
| Alpha, net with the commission stress | −6.96 (−6.59) | −7.55 (−5.96) |
| Conditional diagnostic | −4.78 (−4.90) | −5.03 (−4.47) |
| Net excess return (market: 9.06) | 4.76 | 4.24 |
| Sharpe ratio, net (market: 0.60) | 0.31 | 0.27 |
| Half spread and impact, bp a month | 35.3 | 36.7 |
| Turnover filled, % a month | 110 | 110 |
| Effective number of stocks, median | 33 | 30 |
| Largest weight, maximum % of the fund | 35.7 | 43.4 |
| Value of 1 at the end of 2025, after costs (market: 29.7) | 7.1 | 6.0 |

- **Adding the accounting characteristics does not change the answer.** Against
  FF5 and momentum the net alpha of B is negative in all ten configurations
  (|t| of 2.40 or more); before costs no alpha of the trees differs from zero.
- **B is not better than A.** The monthly net return of B minus that of A is
  −0.52 % a year (t = −0.67) for the main configuration, and no difference is
  distinguishable from zero in any configuration (descriptive comparison, not
  fixed at the freeze). The two funds are nearly the same: correlation of the
  monthly net returns from 0.91 to 0.96.
- Over all periods and factor models, 1 of the 120 net cells of B is positive
  (ridge, large universe, close to close, CAPM, 1993–2008: 0.84 %, t = 0.32),
  against 13 of 120 in A (all ridge, none significant); with the commission
  stress all 240 are negative.
- Same mechanism as in A: costs of about 37 bp a month (4.4 % a year) are
  almost the whole distance between the gross and the net alpha; the return is
  the market's (beta 0.99, R² 0.86).
- In 36 formation months between December 2014 and November 2024, the
  threshold and the number of stocks of the top 10 % of the trees are identical
  in A and B, with the same settings chosen: in those months the trees of B
  appear to make no use of the accounting characteristics (the forecasts
  themselves were not compared).
- Settings chosen by validation (sealed table opened after the results): depth
  3, the deepest allowed, in 22 years of 33 (19 in A); the ridge chooses the
  smallest penalty of its grid in one year. The grids are not extended.

**Reading.** The reservation on restated Compustat accounts (D12) does not
rescue B: under the usual presumption that restated data flatter a backtest, a
point-in-time version B would be no better than what is shown; neither the
sign nor the size of that effect is measured. What the test does not say: that
accounting information is useless. It covers one use of it, a long-only,
value-weighted, monthly fund of USD 100 million.

**Audit.** A separate agent recomputed every alpha and t-statistic of both
versions from the monthly records with its own code (largest gap 4e-16), the
464 numbers of the tables of the note (two cells corrected: a double
rounding) and the 1,250 numbers of `tables_B.md` (no gap), and checked the
record of the test (one completed attempt per step, hashes equal to the files
on disk, code and inputs of the freeze unchanged). It found seven sentences
that were literally wrong or too strong (for example "negative in every cell
of both versions", "coarser forecasts", "forecasts committed before the
freeze"); all were rewritten before the note was sent. Astra did not audit the
results of B.

## 9. Limits to disclose in the report

1. Compustat accounts are in today's state; version B is exposed to
   restatements (D12). Example: Super Micro Computer.
2. Fiscal years closed before the listing are absent from our extract (7.8 % of
   eligible linked stock-months, 1.2 % of market equity).
3. No `conditionaltype`: the "regular trading" filter is a substitute (D2).
4. Costs before the 1990s are estimated (high-low), not observed; commissions
   before 1975 are not in the data yet (D15).
5. The 50 % cap on quoted spreads; the high-low estimator compresses size gaps.
6. NYSE breakpoints at the security level differ from Ken French's (companies).
7. Secondary share classes have no accounting data (1.75 % of market equity).
8. Delisting returns can rest on amounts paid later; −30 % imputation (D3).
9. The link table and the French factor files are today's vintages.
10. `eligible` does not guarantee execution: stale prices, zero volume.
11. The backtest rules rest on abstracts and summaries read on 2026-11-12:
    every quoted figure must be checked in the paper.
12. Companies with tracking stocks have no market-scaled characteristic (D26);
    characteristics with low coverage get a neutral rank and a flag (D18).
13. Results of the test (section 8.10; list in `reports/results_version_A.md`,
    section 7): one main result named in advance and many secondary numbers;
    the gross return is the net return plus the costs paid, not a costless
    strategy; the order cap of 10 % has no source; value weights with no cap
    (33 effective stocks); coarse tree forecasts and a grid that binds on
    depth; Ken French factors only (D20 postponed, no q-factors).
14. The patience rule and the other variants of section 8.11 were tried
    after the test, on the same years: a diagnostic, not a result.

## 10. Open items (2026-11-12)

Update of 2026-11-13: items 1, 3, 4 and most of 5 are done (signals,
predictions, portfolio, backtest, freeze, test of version A). Still open:
(the test of version B is done: section 8.12); the q-factors and the GRS
test (not done); robustness; factors rebuilt from our data (D20); a second
run of the predictions of A for reproducibility; the data dictionary for
the new tables; an audit of the test results and of the report scripts;
the report and the slides.

1. Backtest rules: **done**, final rules in section 8.4 (validated by Danny on
   2026-11-12). Cleaning: **closed** (step 9 rerun `86a807cdfece`, output
   identical byte for byte).
2. Obtain and check the Jones (2002) commission series; q and q5 factors from
   global-q.org.
3. Signal rules to freeze before any result: industry grouping (D8) and an
   "unknown industry" bucket, minimum coverage, momentum window and skipped
   month, security or company market equity for book-to-market, 12-month
   comparisons on the same `gvkey`, exact content of versions A and B,
   sensitivity tests (D3 at −55 %, 12-month lag, French breakpoints, costs).
4. Signals: **closed on 2026-11-13** (section 8.6). Next: choice of the
   models, then predictions.
5. Then: signals → portfolios → backtest with costs → alphas (CAPM, FF3, FF5,
   q, q5; t-tests, GRS) → robustness → freeze → single out-of-sample test →
   report (20 pages) and slides.
6. Housekeeping: `utils.py` lives in `scripts/data_cleaning/` (a future
   signals or backtest folder must import it from there or move it up);
   uncommitted changes on branch `project/data-cleaning-validation`.

## 11. Incidents and lessons

- **Git incident (2026-11-11).** Switching to the old local `main` (commit
  `ed8bc04`, which tracked `data/raw/manifest.json` and `data/raw/fred/`) and
  updating it made Git overwrite then delete these ignored files. Restored on
  2026-11-12 from `ed8bc04`; the six FRED files had to be restored a second
  time byte for byte (`git cat-file blob`) because of Windows line endings.
  WRDS and French hashes rechecked: intact. **Rule: before any `git checkout`
  or `git switch`, check with `git ls-tree` that the target branch tracks no
  file under `data/`.** Other files of the old `main` (`data/preview/`, `src/`,
  `tests/`, `results/`) were not restored: abandoned at the restart.
- **Reproducibility**: order-sensitive floating-point computations must be
  preceded by an explicit sort (section 6.4).
- **Checks must not take their population from the object under test** (final
  audit, finding 8).
- **A successful audit is not evidence of performance**, and a successful
  download does not certify that a series suits a backtest.

## 12. Sources to verify before citing

Read only as abstracts or summaries so far: Corwin and Schultz (2012); Shumway
(1997) (the −30 % figure is not confirmed); Shumway and Warther (1999); Fama
and French (2008); Gompers, Ishii and Metrick (2010); Holden and Jacobsen
(2014); Lyle, Siano and Yohn (2024); Freyberger et al. (NBER WP 30761);
Asparouhova, Bessembinder and Kalcheva (2013); Chen and Velikov (2023); Jones
(2002); Novy-Marx and Velikov (2016); Frazzini, Israel and Moskowitz (2018);
Hou, Xue and Zhang (2020); Avramov, Cheng and Metzker (2023); Gu, Kelly and Xiu
(2020); Bryzgalova, Lerner, Lettau and Pelger (2024); Akey, Robertson and
Simutin ("Noisy factors"); Asness and Frazzini (2013); Abdi and Ranaldo (2017);
Gao and Ritter (NASDAQ volume); Ferson and Schadt (1996); McLean and Pontiff
(2016); Lewellen (2015); Kozak, Nagel and Santosh (2020). Used in full through their code: Jensen, Kelly
and Pedersen (2023); Tidy Finance. Course example: Cooper, Gulen and Schill
(2008).

## 13. Map to the report sections

| Report section | Material |
|---|---|
| Data | Section 3; steps 1–3 (sample, universe, delistings); funnel and size table (steps 3–4) |
| Sample construction and biases | Steps 1–3 (survivorship), step 8 (look-ahead tests), section 5 |
| Variables | Steps 5, 7, 8, 9; data dictionary |
| Validation of the data | Market check 0.99999 (step 5); French breakpoints (step 4); HML 0.982 (6.1); reproducibility (6.4); audit trail (2.3) |
| Portfolio construction and costs | Section 8.2; spreads of step 9; size groups of step 4 |
| Factor models and alphas | Step 5 (factor table), D20 |
| Method (signals, models, portfolio, costs, freeze) | Sections 8.5 to 8.9 |
| **Results** | **Section 8.10 (tables 1 to 3); `reports/results_version_A.md`, `reports/tables_A.md`, `reports/figures/`** |
| Why it fails; what a slower strategy gives | Section 8.11 (tables 4 and 5), to present as done after the test |
| Robustness | D3 at −55 %, 12-month lag, French breakpoints, three universes, A against B, execution lag |
| Limitations | Section 9 |
| Appendix | Decision register (section 7); `CleaningSpec.md` |
