"""Step 9 of CleaningSpec.md: monthly summaries of the daily CRSP file (reduced scope, D11).

Reference code (Resources/reference_code/):
- JKP aux_functions.py:
    gen_crsp_sf / prepare_crsp_sf -> daily rows with DlyDelFlg = 'Y' are not used
    prepare_daily     -> keep days with a market return; a return after a gap of
                         more than 14 days is set to null
    gen_aux_windows   -> the "_21d", "_126d", "_252d" windows are 1, 6 and 12
                         calendar months ending at the month end
    apply_group_filter-> minimum number of observations in the window
    rvol              -> std(ret_exc); null if raw returns are near-constant
                         (std <= 1e-6) or 90 % or more of them are zero
    capm              -> beta = cov(ret_exc, mktrf) / var(mktrf), same guards
    dolvol            -> mean of the daily dollar volume
    adj_trd_vol_NASDAQ-> Gao-Ritter NASDAQ volume adjustment (copied in step 3)
    rmax              -> highest daily return of the month and mean of the five
                         highest, same guards as rvol
    compute_bidask_spread -> rvolhl_21d, the high-low volatility that comes out
                         of the same Corwin-Schultz computation as bidaskhl_21d
    ami               -> Amihud illiquidity: mean of |ret| / dollar volume x 1e6
    dolvol            -> dolvol_var: std / mean of the daily dollar volume
    prc_to_high       -> last split-adjusted price over the highest one, 12 months
    gen_crsp_sf       -> the monthly file carries the cumulative share factor; our
                         monthly export does not, so cfacshr_mth is taken from the
                         daily file on the date of the monthly row

Share factor (audit of 2026-11-12). The CRSP cumulative factor of the export is
today's vintage, written with 12 decimals: after many later reverse splits its
level is rounded, down to zero (PERMNO 12350), and a ratio of two levels is
lost. Every use of the factor here is a ratio, so the script builds a LOCAL
factor that only knows the past: 1 on the first daily row of the stock, then,
day after day, the ratio of the CRSP levels when both are at least 1e-6
(precise to 2e-6), and otherwise the dated split events of the distribution
file (type FRS: stock splits and stock dividends). See local_share_factor.

Deviations (see CleaningSpec.md):
- Market and risk-free returns come from the Ken French daily file (JKP builds
  its own market return and uses CRSP t30ret / 21).
- The windows are computed from monthly sums (count, sum, sum of squares, cross
  products): the same numbers as a direct computation, in one pass.
- Two spreads: the quoted spread from DlyBid / DlyAsk (course cost model), and
  JKP's high-low estimator (bidask_hl, Corwin and Schultz 2012), copied, because
  quotes barely exist before the 1990s.
- A value is given only for a month where the stock has daily rows.

Outputs (data/processed/):
- crsp_daily_min.parquet     the daily columns we use (intermediate, typed)
- crsp_daily_agg.parquet     one row per stock-month: rvol_21d, rvol_252d, beta_252d,
                             dolvol_21d, dolvol_126d, spread_quoted_21d, bidaskhl_21d,
                             rmax1_21d, rmax5_21d, rvolhl_21d, ami_126d,
                             dolvol_var_126d, prc_highprc_252d, cfacshr_mth and counts
- crsp_daily_agg_report.json checks, counts and output hashes (written last)
"""

from __future__ import annotations

import io
import json
import math
import uuid
import zipfile

import polars as pl

from utils import (PROCESSED, RAW, CheckError, adj_trd_vol_nasdaq, check, check_unchanged,
                   file_stamps, publish, read_raw_sized,
                   read_raw_verified,
                   read_verified, sha256)

DAILY = RAW / "crsp_ciz_daily_stock.csv"
DAILY_MIN = PROCESSED / "crsp_daily_min.parquet"
SEC = RAW / "crsp_ciz_security_history.csv"
FF_DAILY = RAW / "french" / "F-F_Research_Data_Factors_daily_CSV.zip"
PANEL = PROCESSED / "crsp_panel_acc.parquet"
PANEL_REPORT = PROCESSED / "accounting_availability_report.json"
STEP1_REPORT = PROCESSED / "crsp_monthly_report.json"
DISTRIBUTIONS = PROCESSED / "crsp_distributions.parquet"

HEADER = ["PERMNO", "HdrCUSIP", "SecurityNm", "Ticker", "PERMCO", "YYYYMMDD", "DlyCalDt",
          "DlyDelFlg", "DlyPrc", "DlyPrcFlg", "DlyCap", "DlyRet", "DlyRetx", "DlyRetI", "DlyVol",
          "DlyLow", "DlyHigh", "DlyBid", "DlyAsk", "DlyPrcVol", "ShrOut", "DlyCumFacPr",
          "DlyCumFacShr"]
MAX_RET_GAP_DAYS = 14          # JKP: a return after a longer gap is not used
RET_MIN_STD = 1e-6             # JKP config: near-constant returns give no statistic
CONSTANT_MAX_ZERO_FRAC = 0.9   # JKP: too many zero returns give no statistic
MIN_OBS = {"21d": 15, "126d": 60, "252d": 120}   # JKP minimum observations
MIN_SPREAD_DAYS = 10           # minimum days with a valid quote in the month
MAX_SPREAD = 0.5               # a quoted spread above 50 % of the midpoint is not used
N_BATCHES = 60
CONVERT_VERSION = 2            # change it when convert_daily changes
SAMPLE_START = 196301
SUMS = ["n", "n_zero", "s_r", "s_rr", "s_m", "s_mm", "s_rm", "s_raw", "s_raw2",
        "n_dv", "s_dv", "n_sp", "s_sp", "n_dvok", "n_ami", "s_ami", "n_pa"]
FACTOR_MIN_LEVEL = 1e-6        # below it, the 12 decimals of the export make a ratio of levels imprecise
# Changes of the CRSP factor between two precise levels that the dated events do
# not give within 1e-4: two without any event (PERMNO 30920 on 1963-11-12, 55555
# on 1991-06-17) and three extreme reverse splits whose event has only 6 decimals
# (for example 13013 on 2017-09-22). The CRSP level is followed for them. A
# larger count means the event rule no longer describes the file.
MAX_UNMATCHED_FACTOR_CHANGES = 5
AMI_SCALE = 1e6                # JKP ami: |ret| / dollar volume, times one million


def convert_daily(report: dict) -> None:
    """
    Description:
        One streaming pass over the 22 GB daily file: keep the columns we use.
    Steps:
        1) Check the size against the raw manifest, the hash against the one
           recorded at step 1, and the exact header.
        2) Read every field as text ("" is missing), cast strictly, write Parquet.
    Output:
        data/processed/crsp_daily_min.parquet (temp file, then rename).
    """
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    size = {f["filename"]: f["bytes"] for f in manifest["files"]}.get(DAILY.name)
    check(size == DAILY.stat().st_size, f"{DAILY.name}: size differs from the raw manifest")
    before = file_stamps([DAILY])
    digest = sha256(DAILY)
    step1 = json.loads(STEP1_REPORT.read_text(encoding="utf-8"))["inputs"][DAILY.name]
    check(digest == step1, f"{DAILY.name} is not the file read at step 1")
    report["inputs"][DAILY.name] = digest
    with DAILY.open(encoding="utf-8") as f:
        check(f.readline().rstrip("\r\n").split(",") == HEADER, f"Unexpected header in {DAILY.name}")

    # Skip the conversion when the Parquet on disk was built from this exact raw
    # file by this version of the conversion (its own hash is checked too).
    stamp = DAILY_MIN.with_name(DAILY_MIN.name + ".json")
    if DAILY_MIN.exists() and stamp.exists():
        old = json.loads(stamp.read_text(encoding="utf-8"))
        if (old.get("raw_sha256") == digest and old.get("version") == CONVERT_VERSION
                and old.get("parquet_sha256") == sha256(DAILY_MIN)):
            return
    num = lambda c: pl.col(c).cast(pl.Float64, strict=True)
    tmp = DAILY_MIN.with_name(f"{DAILY_MIN.name}.{uuid.uuid4().hex[:12]}.tmp")
    (
        pl.scan_csv(DAILY, infer_schema=False)
        .select(
            pl.col("PERMNO").cast(pl.Int64, strict=True).alias("permno"),
            pl.col("DlyCalDt").str.to_date("%Y-%m-%d", strict=True).alias("date"),
            pl.col("DlyDelFlg").alias("del_flag"),
            num("DlyPrc").alias("prc"), num("DlyRet").alias("ret"), num("DlyVol").alias("vol"),
            num("DlyBid").alias("bid"), num("DlyAsk").alias("ask"),
            pl.col("DlyPrcFlg").alias("prc_flag"),
            num("DlyHigh").alias("high"), num("DlyLow").alias("low"),
            num("DlyCumFacShr").alias("cfacshr"),
        )
        .sink_parquet(tmp, row_group_size=1_000_000)
    )
    # The file was hashed first and converted after: it must not have changed.
    check_unchanged(before)
    tmp.replace(DAILY_MIN)
    # Temp file then rename, so a stop cannot leave a half-written stamp.
    stamp_tmp = stamp.with_name(f"{stamp.name}.{uuid.uuid4().hex[:12]}.tmp")
    stamp_tmp.write_text(json.dumps({"raw_sha256": digest, "version": CONVERT_VERSION,
                                     "parquet_sha256": sha256(DAILY_MIN)}), encoding="utf-8")
    stamp_tmp.replace(stamp)


def read_exchange_history(report: dict) -> pl.DataFrame:
    # Security history: exchange and trading status by date interval (step 3 source).
    sec = pl.read_csv(io.BytesIO(read_raw_sized(SEC, report)), infer_schema=False).select(
        pl.col("permno").cast(pl.Int64, strict=True),
        pl.col("secinfostartdt").str.to_date("%Y-%m-%d", strict=True),
        pl.col("secinfoenddt").str.to_date("%Y-%m-%d", strict=True),
        "primaryexch", "tradingstatusflg",
    )
    check(sec.null_count().sum_horizontal().item() == 0, "Null values in the security history")
    sec = sec.sort("permno", "secinfostartdt")
    overlap = sec.filter(
        pl.col("secinfostartdt") <= pl.col("secinfoenddt").shift(1).over("permno")).height
    check(overlap == 0, f"{overlap} overlapping security info intervals")
    return sec


def add_daily_exchange(d: pl.DataFrame, sec: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        NASDAQ flag of each DAY, with the step 3 rule applied at the daily date.
    Steps:
        1) Interval of the security history that holds the date (bounds included).
        2) If the stock is active there, its exchange. Otherwise the exchange of
           the last active interval started on or before the date.
        3) is_nasdaq is null when no exchange is known.
    Output:
        Daily rows with is_nasdaq.
    """
    cols = d.columns
    s = sec.filter(pl.col("permno").is_in(d["permno"].unique().implode()))
    active = s.filter(pl.col("tradingstatusflg") == "A").select(
        "permno", pl.col("secinfostartdt").alias("start_active"),
        pl.col("primaryexch").alias("exch_last_active"))
    n = d.height
    d = (
        d.sort("date")
        .join_asof(s.sort("secinfostartdt"), left_on="date", right_on="secinfostartdt",
                   by="permno", strategy="backward", check_sortedness=False)
        .join_asof(active.sort("start_active"), left_on="date", right_on="start_active",
                   by="permno", strategy="backward", check_sortedness=False)
    )
    check(d.height == n, "Exchange join changed the row count")
    active_now = ((pl.col("secinfoenddt") >= pl.col("date"))
                  & (pl.col("tradingstatusflg") == "A")).fill_null(False)
    exch = pl.when(active_now).then(pl.col("primaryexch")).otherwise(pl.col("exch_last_active"))
    return d.with_columns(is_nasdaq=pl.when(exch.is_not_null()).then(exch == "Q")).select(
        cols + ["is_nasdaq"]).sort("permno", "date")


def read_share_events(report: dict) -> pl.DataFrame:
    """
    Description:
        Dated share events of step 1: splits and stock dividends (CRSP type FRS).
        The other event types that carry a share factor (mergers, spin-offs,
        offers) do not move the CRSP cumulative factor. Several FRS events with
        the same ex-date ADD UP in CRSP: the share count is multiplied by
        1 + sum(DisFacShr), not by the product of the (1 + DisFacShr) (8 days in
        the file, for example PERMNO 22605 on 1975-06-02). The run counts how many
        changes of the CRSP factor between two precise levels these events
        explain (entry daily_counts of the report) and stops if more than
        MAX_UNMATCHED_FACTOR_CHANGES are not explained.
    Output:
        permno, exdt, mult = 1 + sum of DisFacShr of the ex-date.
    """
    dist, run_id = read_verified(DISTRIBUTIONS, STEP1_REPORT)
    report["inputs"][DISTRIBUTIONS.name] = {"from_run": run_id}
    ev = dist.filter((pl.col("distype") == "FRS") & pl.col("disfacshr").is_not_null()
                     & (pl.col("disfacshr") != 0))
    check(ev["disexdt"].null_count() == 0, "A share event without an ex-date")
    check(ev.filter((pl.col("disfacshr") <= -1) | ~pl.col("disfacshr").is_finite()).height == 0,
          "A share event that removes every share")
    days = (ev.sort("permno", "disexdt", "disseqnbr")
            .group_by("permno", "disexdt", maintain_order=True)
            .agg(mult=1 + pl.col("disfacshr").sum(), n=pl.len()))
    check(days.filter(pl.col("mult") <= 0).height == 0, "Share events of one day remove every share")
    report["share_events"] = {"events": ev.height, "stocks": ev["permno"].n_unique(),
                              "ex_dates": days.height, "ex_dates_with_several_events": days.filter(pl.col("n") > 1).height}
    return days.select("permno", pl.col("disexdt").alias("exdt"), "mult").sort("permno", "exdt")


def local_share_factor(d: pl.DataFrame, events: pl.DataFrame, counts: dict) -> pl.DataFrame:
    """
    Description:
        Cumulative share factor that only uses the past (see the module docstring).
    Steps:
        1) Exact copies dropped; rows sorted by stock and date.
        2) Each ex-date goes to the first daily row on or after it; the
           multipliers of several ex-dates that land on one row are multiplied.
        3) Step of the day = level / previous level when both CRSP levels are at
           least FACTOR_MIN_LEVEL; otherwise 1 / product of the event multipliers
           of the day (1 without an event). The first row of a stock has step 1.
        4) cfacshr = cumulative product of the steps, missing where CRSP gives no
           factor that day. The CRSP level is kept in cfacshr_raw.
    Output:
        The daily rows, with the local factor in cfacshr.
    """
    n0 = d.height
    d = d.unique().sort("permno", "date")
    counts["exact_duplicate_rows"] += n0 - d.height
    check(d.select("permno", "date").is_unique().all(), "Conflicting duplicate (permno, date)")
    ev = events.filter(pl.col("permno").is_in(d["permno"].unique().implode()))
    rows = d.select("permno", pl.col("date").alias("row_date"))
    hit = (ev.sort("exdt").join_asof(rows.sort("row_date"), left_on="exdt", right_on="row_date",
                                     by="permno", strategy="forward", check_sortedness=False)
           .filter(pl.col("row_date").is_not_null()).sort("permno", "exdt")
           .group_by("permno", "row_date", maintain_order=True).agg(ev_mult=pl.col("mult").product()))
    n = d.height
    d = d.join(hit, left_on=["permno", "date"], right_on=["permno", "row_date"], how="left").sort("permno", "date")
    check(d.height == n, "The share event join changed the row count")
    f, prev = pl.col("cfacshr"), pl.col("cfacshr").shift(1).over("permno")
    d = d.with_columns(
        first=pl.int_range(pl.len()).over("permno") == 0,
        precise=((f >= FACTOR_MIN_LEVEL) & (prev >= FACTOR_MIN_LEVEL)).fill_null(False),
        prev_raw=prev,
    ).with_columns(
        step=pl.when(pl.col("first")).then(1.0).when(pl.col("precise")).then(f / pl.col("prev_raw"))
        .otherwise(1.0 / pl.col("ev_mult").fill_null(1.0)),
    )
    later = ~pl.col("first")
    counts["factor_rows_below_min_level"] += d.filter(f < FACTOR_MIN_LEVEL).height
    counts["factor_rows_exactly_zero"] += d.filter(f == 0).height
    counts["factor_steps_from_events"] += d.filter(later & ~pl.col("precise") & pl.col("ev_mult").is_not_null()).height
    counts["factor_stocks_using_events"] += d.filter(
        later & ~pl.col("precise") & pl.col("ev_mult").is_not_null())["permno"].n_unique()
    counts["factor_changes_between_precise_levels"] += d.filter(later & pl.col("precise") & (pl.col("step") != 1)).height
    # Diagnostic: precise level changes that the FRS events of the day do not give.
    unmatched = d.filter(
        later & pl.col("precise") & (pl.col("step") != 1)
        & (pl.col("ev_mult").is_null() | ((pl.col("step") * pl.col("ev_mult") - 1).abs() > 1e-4)))
    counts["precise_changes_not_matched_by_events"] += unmatched.height
    if "_unmatched" in counts:      # only the main run keeps the list
        counts["_unmatched"] += unmatched.select("permno", "date", "prev_raw", "cfacshr", "ev_mult").to_dicts()
    d = d.with_columns(g=pl.col("step").cum_prod().over("permno"))
    check(d.filter((pl.col("g") <= 0) | ~pl.col("g").is_finite()).height == 0, "Local share factor not positive")
    return d.with_columns(cfacshr_raw=f, cfacshr=pl.when(f.is_not_null()).then(pl.col("g"))).drop(
        "ev_mult", "first", "precise", "prev_raw", "step", "g")


def read_french_daily(report: dict) -> pl.DataFrame:
    # Ken French daily factors: date, market excess return and risk-free rate (decimals).
    data, digest = read_raw_verified(FF_DAILY, FF_DAILY.parent / "manifest.json")
    report["inputs"][FF_DAILY.name] = digest
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        lines = z.read(z.namelist()[0]).decode("latin-1").splitlines()
    header = ",Mkt-RF,SMB,HML,RF"
    check(header in lines, "Daily factor header not found")
    start = lines.index(header) + 1
    df = pl.read_csv(io.StringIO("\n".join(lines[start:lines.index("", start)])), has_header=False,
                     new_columns=["date", "mktrf", "smb", "hml", "rf"], infer_schema=False)
    df = df.select(
        pl.col("date").str.strip_chars().str.to_date("%Y%m%d", strict=True),
        *[pl.col(c).str.strip_chars().cast(pl.Float64, strict=True) for c in ["mktrf", "rf"]],
    )
    check(df["date"].null_count() == 0 and df["date"].is_unique().all() and df["date"].is_sorted(),
          "Daily factor dates are missing, duplicated or unsorted")
    df = df.with_columns(pl.col("mktrf", "rf").replace({-99.99: None, -999.0: None}) / 100)
    check(df.null_count().sum_horizontal().item() == 0, "Missing daily market or risk-free return")
    check(df.select(pl.col("mktrf", "rf").is_finite().all()).row(0) == (True, True), "Non-finite factor")
    report["french_daily"] = {"days": df.height, "first": df["date"].min(), "last": df["date"].max()}
    # First trading day of each month in the market calendar (for ret_d1).
    month = pl.col("date").dt.year() * 100 + pl.col("date").dt.month()
    return df.with_columns(first_of_month=pl.col("date") == pl.col("date").min().over(month))


def prepare_batch(d: pl.DataFrame, ff: pl.DataFrame, sec: pl.DataFrame, counts: dict) -> pl.DataFrame:
    """
    Description:
        Clean the daily rows of a group of stocks (JKP prepare_daily, reduced).
    Steps:
        1) Drop exact duplicate rows; (permno, date) must then be unique.
        2) Drop rows with DlyDelFlg = 'Y' (JKP).
        3) A return whose previous valid price is more than 14 days old is set to
           null: it is not a one-day return (project rule; JKP's CRSP branch does
           not apply its 14-day rule).
        4) Join the market and risk-free returns; every CRSP day must have one.
        5) ret_exc = ret - rf; dollar volume with the NASDAQ adjustment of the
           exchange of the DAY; quoted spread.
    Output:
        Daily rows with ret_exc, mktrf, dolvol_d, spread_d.
    """
    n0 = d.height
    # JKP practice: unique() does not keep the row order, so sort right after it.
    d = d.unique().sort("permno", "date")
    counts["exact_duplicate_rows"] += n0 - d.height
    check(d.select("permno", "date").is_unique().all(), "Conflicting duplicate (permno, date)")
    check(d["del_flag"].null_count() == 0 and set(d["del_flag"].unique()) <= {"N", "Y"},
          "Unknown DlyDelFlg")
    for c in ["prc", "ret", "vol", "bid", "ask", "high", "low", "cfacshr"]:
        check(d.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height == 0, f"Non-finite {c}")
    check(d.filter(pl.col("ret") < -1).height == 0, "Daily return below -100 %")
    counts["rows"] += d.height
    counts["delisting_rows_dropped"] += d.filter(pl.col("del_flag") == "Y").height

    d = (
        d.filter(pl.col("del_flag") == "N").sort("permno", "date")
        .with_columns(
            # Days since the previous row, and since the previous row WITH a price
            # (rows without a price can sit between two prices).
            gap_row=(pl.col("date") - pl.col("date").shift(1).over("permno")).dt.total_days(),
            gap=(pl.col("date") - pl.when(pl.col("prc").is_not_null()).then(pl.col("date"))
                 .forward_fill().shift(1).over("permno")).dt.total_days(),
        )
    )
    has_ret = pl.col("ret").is_not_null()
    counts["returns_after_row_gap_over_14d"] += d.filter(has_ret & (pl.col("gap_row") > MAX_RET_GAP_DAYS)).height
    counts["returns_dropped_after_long_gap"] += d.filter(has_ret & (pl.col("gap") > MAX_RET_GAP_DAYS)).height
    counts["returns_without_previous_price"] += d.filter(has_ret & pl.col("gap").is_null()).height
    d = (
        d.with_columns(
            ret_raw=pl.col("ret"),   # CRSP return, kept for the check against monthly returns
            ret=pl.when(pl.col("gap") <= MAX_RET_GAP_DAYS).then(pl.col("ret")),
            long_gap=has_ret & (pl.col("gap") > MAX_RET_GAP_DAYS),
            ym=(pl.col("date").dt.year() * 100 + pl.col("date").dt.month()).cast(pl.Int32),
        )
        .join(ff, on="date", how="left")
    )
    # Every CRSP trading day must be in the market calendar: a missing date would
    # silently drop that day for every stock and every measure.
    missing = d.filter(pl.col("mktrf").is_null())
    counts["rows_without_market_return"] += missing.height
    check(missing.height == 0, f"{missing.height} daily rows on dates missing from the market "
                               f"calendar, e.g. {missing['date'].min()}")
    d = add_daily_exchange(d.drop("gap_row"), sec)
    counts["rows_with_unknown_exchange"] += d.filter(pl.col("is_nasdaq").is_null()).height
    return d.with_columns(
        ret_exc=pl.col("ret") - pl.col("rf"),
        vol_adj=pl.col("vol"),
    ).with_columns(
        adj_trd_vol_nasdaq("date", "vol_adj", pl.col("is_nasdaq").fill_null(False)),
    ).with_columns(
        # Dollar volume; unknown when the exchange of the day is unknown.
        dolvol_d=pl.when(pl.col("is_nasdaq").is_not_null()).then(pl.col("prc").abs() * pl.col("vol_adj")),
        # Quoted spread over the midpoint; only with a valid, uncrossed quote.
        spread_d=pl.when((pl.col("bid") > 0) & (pl.col("ask") > pl.col("bid")))
        .then((pl.col("ask") - pl.col("bid")) / ((pl.col("ask") + pl.col("bid")) / 2)),
    ).with_columns(
        spread_d=pl.when(pl.col("spread_d") <= MAX_SPREAD).then(pl.col("spread_d")),
        # JKP prepare_daily: prc_adj = prc / adjfct (safe_div mode 1: factor != 0).
        prc_adj_d=pl.when(pl.col("cfacshr") != 0).then(pl.col("prc") / pl.col("cfacshr")),
    ).pipe(add_high_low_spread)


def add_high_low_spread(d: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Daily bid-ask spread from high and low prices (Corwin and Schultz, 2012),
        copied from JKP: bidask_hl, impute_high_low, adjust_overnight_returns and
        compute_bidask_spread. Column names follow JKP (id = permno, tvol = vol).
    Steps:
        1) JKP gen_crsp_sf: high / low valid only with a positive price; bidask
           flag when the price is a bid-ask average; prices divided by adjfct.
        2) impute_high_low: drop impossible high / low, carry the last valid range.
        3) adjust_overnight_returns: move today's range if yesterday's close is outside.
        4) compute_bidask_spread: spread from the 1-day and 2-day ranges; negative -> 0.
    Output:
        Daily rows with spread_hl_d (null when it cannot be computed).
    """
    col = pl.col
    sqrt2, const = 2 ** 0.5, 3 - 2 * 2 ** 0.5
    k2 = (8 / math.pi) ** 0.5
    df = d.with_columns(
        # JKP safe_div: no value when the adjustment factor is missing or zero.
        prc_high=pl.when((col("prc") > 0) & (col("high") > 0) & (col("cfacshr") > 0))
        .then(col("high") / col("cfacshr")),
        prc_low=pl.when((col("prc") > 0) & (col("low") > 0) & (col("cfacshr") > 0))
        .then(col("low") / col("cfacshr")),
        prc_adj=pl.when(col("cfacshr") > 0).then(col("prc") / col("cfacshr")),
        bidask=(col("prc_flag") == "BA").cast(pl.Int32),
    ).with_columns(
        # A range seen that day: a trade price, some volume, high above low.
        # (and a high / low ratio of at most 8, the filter of the estimator).
        hl_observed=((col("bidask") == 0) & (col("vol") > 0) & (col("prc_low") > 0)
                     & (col("prc_high") > col("prc_low"))
                     & (col("prc_high") / col("prc_low") <= 8)).fill_null(False),
    ).rename({"prc": "prc_unadj", "prc_adj": "prc", "vol": "tvol", "permno": "id"})

    # --- impute_high_low (JKP, copied) ---
    sc1 = ((col("bidask") == 1) | (col("tvol") == 0) | (col("prc_low") <= 0)
           | (col("prc_high") <= 0) | (col("prc_low") == col("prc_high")))
    sc2 = (col("prc_low") > 0) & (col("prc_high") > col("prc_low"))
    sc3 = (col("flag_replace")) & (
        (col("prc") >= col("prc_low_r")) & (col("prc") <= col("prc_high_r"))
        | (col("prc").is_null() & col("prc_low_r").is_null() & col("prc_high_r").is_null())
    )
    sc4 = (col("flag_replace")) & (col("prc") < col("prc_low_r"))
    sc5 = (col("flag_replace")) & (col("prc") > col("prc_high_r")).fill_null(True)
    sc6 = (col("prc_low") != 0) & (col("prc_high") / col("prc_low") > 8)
    df = (
        df.sort(["id", "date"])
        .with_columns(
            prc_high=pl.when(sc1).then(None).otherwise(col("prc_high")),
            prc_low=pl.when(sc1).then(None).otherwise(col("prc_low")),
            count=pl.cum_count("id").over("id"),
        )
        .with_columns(
            prc_low_r=(pl.when(col("count") == 1).then(None).otherwise(col("prc_low"))),
            prc_high_r=(pl.when(col("count") == 1).then(None).otherwise(col("prc_high"))),
        )
        .with_columns(
            prc_low_r=(pl.when(sc2).then(col("prc_low")).otherwise(col("prc_low_r"))),
            prc_high_r=(pl.when(sc2).then(col("prc_high")).otherwise(col("prc_high_r"))),
        )
        .sort(["id", "date"])
        .with_columns(
            flag_replace=col("prc_low_r").is_null(),
            prc_low_r=col("prc_low_r").forward_fill().over("id"),
            prc_high_r=col("prc_high_r").forward_fill().over("id"),
        )
        .with_columns(
            prc_low=(pl.when(sc3).then(col("prc_low_r")).when(sc4).then(col("prc"))
                     .when(sc5).then(col("prc_low_r") + (col("prc") - col("prc_high_r")))
                     .otherwise(col("prc_low"))),
            prc_high=(pl.when(sc3).then(col("prc_high_r"))
                      .when(sc4).then(col("prc_high_r") - (col("prc_low_r") - col("prc")))
                      .when(sc5).then(col("prc")).otherwise(col("prc_high"))),
        )
        .with_columns(
            prc_low=pl.when(sc6).then(None).otherwise(col("prc_low")),
            prc_high=pl.when(sc6).then(None).otherwise(col("prc_high")),
        )
    )

    # --- adjust_overnight_returns (JKP, copied) ---
    sc1 = (col("prc_l1") < col("prc_low")) & (col("prc_l1") > 0)
    sc2 = (col("prc_l1") > col("prc_high")) & (col("prc_l1") > 0)
    df = (
        df.sort(["id", "date"])
        .with_columns(
            prc_low_t=col("prc_low"),
            prc_high_t=col("prc_high"),
            prc_low_l1=col("prc_low").shift(1).over("id"),
            prc_high_l1=col("prc_high").shift(1).over("id"),
            prc_l1=col("prc").shift(1).over("id"),
        )
        .with_columns(
            prc_high_t=pl.when(sc1).then(col("prc_high") - (col("prc_low") - col("prc_l1")))
            .otherwise(col("prc_high_t")),
            prc_low_t=pl.when(sc1).then(col("prc_l1")).otherwise(col("prc_low_t")),
        )
        .with_columns(
            prc_high_t=pl.when(sc2).then(col("prc_l1")).otherwise(col("prc_high_t")),
            prc_low_t=pl.when(sc2).then(col("prc_low") + (col("prc_l1") - col("prc_high")))
            .otherwise(col("prc_low_t")),
        )
        .with_columns(
            prc_high_2d=pl.max_horizontal("prc_high_t", "prc_high_l1"),
            prc_low_2d=pl.min_horizontal("prc_low_t", "prc_low_l1"),
        )
    )

    # --- compute_bidask_spread (JKP, copied; the monthly mean is taken in month_sums) ---
    df = (
        df.with_columns(
            beta=(pl.when((col("prc_low_t") > 0) & (col("prc_low_l1") > 0))
                  .then(((col("prc_high_t") / col("prc_low_t")).log() ** 2)
                        + ((col("prc_high_l1") / col("prc_low_l1")).log() ** 2))),
            gamma=pl.when(col("prc_low_2d") > 0)
            .then((col("prc_high_2d") / col("prc_low_2d")).log() ** 2),
        )
        .with_columns(alpha=((sqrt2 - 1) * col("beta").sqrt()) / const - (col("gamma") / const).sqrt())
        .with_columns(
            spread=2 * (col("alpha").exp() - 1) / (1 + col("alpha").exp()),
            # JKP: sigma of the same estimator (rvolhl_21d is its monthly mean).
            sigma=(((col("beta") / 2).sqrt() - col("beta").sqrt()) / (k2 * const))
            + (col("gamma") / (k2 * k2 * const)).sqrt(),
        )
        .with_columns(
            spread_hl_d=pl.when(col("spread") < 0).then(pl.lit(0.0)).otherwise(col("spread")),
            sigma_hl_d=pl.when(col("sigma") < 0).then(pl.lit(0.0)).otherwise(col("sigma")),
        )
    )
    keep = [c for c in d.columns] + ["spread_hl_d", "sigma_hl_d", "hl_observed"]
    return df.rename({"prc": "prc_adj", "prc_unadj": "prc", "tvol": "vol", "id": "permno"}).select(keep)


def month_sums(d: pl.DataFrame) -> pl.DataFrame:
    # Sums per stock-month, enough to rebuild std, covariance and means over any months.
    ok = pl.col("ret_exc").is_not_null()
    r, m = pl.col("ret_exc").filter(ok), pl.col("mktrf").filter(ok)
    raw = pl.col("ret").filter(ok)
    dv = pl.col("dolvol_d")
    # JKP ami: a zero dollar volume gives no ratio; rows of the return statistics only.
    ami_d = (pl.col("ret").abs() / pl.when(dv != 0).then(dv)).filter(ok)
    # JKP prc_to_high: adjusted prices on the rows of the return statistics.
    pa = pl.col("prc_adj_d").filter(ok)
    # JKP practice (capm): fix the row order before sums of floats, which depend on
    # the order of their terms, so that two runs give the same bytes.
    return d.sort("permno", "date").group_by("permno", "ym", maintain_order=True).agg(
        n=ok.sum().cast(pl.Int64), n_zero=(raw == 0).sum().cast(pl.Int64),
        s_r=r.sum(), s_rr=(r * r).sum(), s_m=m.sum(), s_mm=(m * m).sum(), s_rm=(r * m).sum(),
        s_raw=raw.sum(), s_raw2=(raw * raw).sum(),
        n_dv=pl.col("dolvol_d").count().cast(pl.Int64), s_dv=pl.col("dolvol_d").sum(),
        n_sp=pl.col("spread_d").count().cast(pl.Int64), s_sp=pl.col("spread_d").sum(),
        n_hl=pl.col("spread_hl_d").count().cast(pl.Int64), s_hl=pl.col("spread_hl_d").sum(),
        n_hl_obs=pl.col("hl_observed").sum().cast(pl.Int64),
        n_sig=pl.col("sigma_hl_d").count().cast(pl.Int64), s_sig=pl.col("sigma_hl_d").sum(),
        # JKP rmax: highest return and mean of the five highest of the month.
        rmax1=raw.max(), rmax5=raw.top_k(5).mean(),
        # JKP ami and dolvol (variability): sums for the 6-month windows.
        n_ami=ami_d.count().cast(pl.Int64), s_ami=ami_d.sum(),
        n_dvok=dv.filter(ok).count().cast(pl.Int64),
        # Mean and centred sum of squares of the month: the 6-month variance is
        # rebuilt from them without subtracting two large sums of squares.
        mean_dv=dv.mean(), m2_dv=((dv - dv.mean()) ** 2).sum(),
        min_dv=dv.min(), max_dv=dv.max(),
        # JKP prc_to_high: count, extremes and last adjusted price (rows are sorted
        # by date, so last() is the last day of the month with a return).
        n_pa=pa.count().cast(pl.Int64), max_pa=pa.max(), min_pa=pa.min(), last_pa=pa.last(),
        s_vol=pl.col("vol").sum(), s_vol_adj=pl.col("vol_adj").sum(),
        n_nasdaq_days=pl.col("is_nasdaq").sum().cast(pl.Int64),
        n_exch_days=pl.col("is_nasdaq").count().cast(pl.Int64),
        n_long_gap=pl.col("long_gap").sum().cast(pl.Int64),
        # For the check against CRSP monthly returns: all days of the month compounded.
        n_days=pl.len().cast(pl.Int64), n_ret_raw=pl.col("ret_raw").count().cast(pl.Int64),
        ret_cmp=(1 + pl.col("ret_raw")).product() - 1,
        # CRSP return of the first trading day of the month (market calendar). Null
        # if the stock has no row or no return that day. It lets the backtest start
        # a holding month at the close of its first day instead of the close of t.
        ret_d1=pl.col("ret_raw").filter(pl.col("first_of_month")).first(),
        last_date=pl.col("date").max(),
    )


def window_stats(s: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Statistics over 1, 6 and 12 calendar months ending at the month end (JKP).
    Steps:
        1) Month number mi; rolling sums over (mi - k, mi] for k = 6 and 12.
        2) std and beta from the sums; JKP minimum observations and guards.
    Output:
        One row per stock-month with the final columns.
    """
    s = s.with_columns(mi=(pl.col("ym") // 100 * 12 + pl.col("ym") % 100).cast(pl.Int64)).sort("permno", "mi")
    out = s
    for k in (6, 12):
        roll = (s.rolling(index_column="mi", period=f"{k}i", group_by="permno")
                .agg([pl.col(c).sum().alias(f"{c}_{k}") for c in SUMS]
                     + [(pl.col("m2_dv").sum()
                         + (pl.col("n_dv") * (pl.col("mean_dv") - (pl.col("n_dv") * pl.col("mean_dv")).sum()
                                              / pl.col("n_dv").sum()) ** 2).sum()).alias(f"m2_dv_{k}"),
                        pl.col("min_dv").min().alias(f"min_dv_{k}"),
                        pl.col("max_dv").max().alias(f"max_dv_{k}"),
                        pl.col("min_pa").min().alias(f"min_pa_{k}"),
                        pl.col("max_pa").max().alias(f"max_pa_{k}"),
                        # Last adjusted price of the window: the one of the latest
                        # month that has a return (months are sorted in the window).
                        pl.col("last_pa").filter(pl.col("n") > 0).last().alias(f"last_pa_{k}")]))
        out = out.join(roll, on=["permno", "mi"], how="left")

    def var(n, s1, s2):  # sample variance from count, sum and sum of squares
        return (pl.col(s2) - pl.col(s1) ** 2 / pl.col(n)) / (pl.col(n) - 1)

    def guarded(expr, sfx, min_obs):
        # JKP: enough observations, raw returns not near-constant, not mostly zero.
        n, raw_var = f"n{sfx}", var(f"n{sfx}", f"s_raw{sfx}", f"s_raw2{sfx}")
        ok = ((pl.col(n) >= min_obs) & (raw_var.clip(lower_bound=0).sqrt() > RET_MIN_STD)
              & (pl.col(f"n_zero{sfx}") / pl.col(n) < CONSTANT_MAX_ZERO_FRAC))
        return pl.when(ok).then(expr)

    cov12 = (pl.col("s_rm_12") - pl.col("s_r_12") * pl.col("s_m_12") / pl.col("n_12")) / (pl.col("n_12") - 1)
    dv_mean6 = pl.col("s_dv_6") / pl.col("n_dv_6")
    dv_std6 = (pl.col("m2_dv_6") / (pl.col("n_dv_6") - 1)).sqrt()
    return out.select(
        "permno", pl.col("ym").alias("yyyymm"), "last_date", "n_days", "n_ret_raw", "ret_cmp",
        "n_long_gap", "s_vol", "s_vol_adj", "n_nasdaq_days", "n_exch_days",
        "ret_d1",
        pl.col("n").alias("n_ret_21d"), pl.col("n_12").alias("n_ret_252d"),
        guarded(var("n", "s_r", "s_rr").clip(lower_bound=0).sqrt(), "", MIN_OBS["21d"]).alias("rvol_21d"),
        guarded(var("n_12", "s_r_12", "s_rr_12").clip(lower_bound=0).sqrt(), "_12", MIN_OBS["252d"])
        .alias("rvol_252d"),
        guarded(cov12 / var("n_12", "s_m_12", "s_mm_12"), "_12", MIN_OBS["252d"]).alias("beta_252d"),
        pl.when(pl.col("n_dv") >= MIN_OBS["21d"]).then(pl.col("s_dv") / pl.col("n_dv")).alias("dolvol_21d"),
        pl.when(pl.col("n_dv_6") >= MIN_OBS["126d"]).then(pl.col("s_dv_6") / pl.col("n_dv_6"))
        .alias("dolvol_126d"),
        pl.col("n_sp").alias("n_spread_21d"),
        pl.when(pl.col("n_sp") >= MIN_SPREAD_DAYS).then(pl.col("s_sp") / pl.col("n_sp"))
        .alias("spread_quoted_21d"),
        pl.col("n_hl").alias("n_spread_hl_21d"),
        # Days of the month with an observed range; 0 = the estimate rests only on
        # ranges carried from earlier days (JKP impute_high_low).
        pl.col("n_hl_obs").alias("n_hl_observed_21d"),
        # JKP bidaskhl_21d: monthly mean, more than 10 days (strictly, as in JKP).
        pl.when(pl.col("n_hl") > MIN_SPREAD_DAYS).then(pl.col("s_hl") / pl.col("n_hl"))
        .alias("bidaskhl_21d"),
        # JKP compute_bidask_spread: same day filter as bidaskhl_21d (count of the spread).
        pl.when((pl.col("n_hl") > MIN_SPREAD_DAYS) & (pl.col("n_sig") > 0))
        .then(pl.col("s_sig") / pl.col("n_sig")).alias("rvolhl_21d"),
        # JKP rmax: at least 15 returns, guards of the return statistics.
        guarded(pl.col("rmax1"), "", MIN_OBS["21d"]).alias("rmax1_21d"),
        guarded(pl.col("rmax5"), "", MIN_OBS["21d"]).alias("rmax5_21d"),
        # JKP ami: at least 60 returns and 60 dollar volumes on these rows; guards
        # of the return statistics; null when no ratio exists.
        pl.when((pl.col("n_dvok_6") >= MIN_OBS["126d"]) & (pl.col("n_ami_6") > 0))
        .then(guarded(pl.col("s_ami_6") / pl.col("n_ami_6") * AMI_SCALE, "_6", MIN_OBS["126d"]))
        .alias("ami_126d"),
        # JKP dolvol: std / mean of the daily dollar volume; null when the volume is
        # constant or its mean is zero.
        pl.when((pl.col("n_dv_6") >= MIN_OBS["126d"]) & (pl.col("min_dv_6") != pl.col("max_dv_6"))
                & (dv_mean6 != 0)).then(dv_std6 / dv_mean6).alias("dolvol_var_126d"),
        # JKP prc_to_high: at least 120 returns and 120 adjusted prices; null when
        # the adjusted price is constant.
        pl.when((pl.col("n_12") >= MIN_OBS["252d"]) & (pl.col("n_pa_12") >= MIN_OBS["252d"])
                & (pl.col("min_pa_12") != pl.col("max_pa_12")))
        .then(pl.col("last_pa_12") / pl.col("max_pa_12")).alias("prc_highprc_252d"),
    )


def check_direct(out: pl.DataFrame, ff: pl.DataFrame, sec: pl.DataFrame, events: pl.DataFrame,
                 report: dict) -> None:
    # Second route on a sample of stocks: compute every statistic directly from the
    # daily rows of each window (no sums), and compare.
    # The sample comes from the daily input, not from the output under test.
    sample = (pl.scan_parquet(DAILY_MIN).select("permno").unique().collect()["permno"].sort()
              .gather_every(400).to_list())
    tmp = {k: 0 for k in COUNTS}
    raw = pl.scan_parquet(DAILY_MIN).filter(pl.col("permno").is_in(sample)).collect()
    d = prepare_batch(local_share_factor(raw, events, tmp), ff, sec, tmp)
    # The vintage test also takes the stocks that have several events on one day.
    multi = (events.join(pl.read_parquet(DISTRIBUTIONS, columns=["permno", "disexdt", "distype", "disfacshr"])
                         .filter((pl.col("distype") == "FRS") & (pl.col("disfacshr") != 0))
                         .group_by("permno", "disexdt").agg(n=pl.len()).filter(pl.col("n") > 1),
                         left_on=["permno", "exdt"], right_on=["permno", "disexdt"])["permno"].unique().to_list())
    # ... and, apart, the stocks whose CRSP factor has a change that the dated
    # events do not give: there a later vintage can change the local factor.
    known = sorted({r["permno"] for r in report["unexplained_factor_changes"]})
    extra = pl.scan_parquet(DAILY_MIN).filter(pl.col("permno").is_in(multi + known)).collect()
    vintage_test(pl.concat([raw, extra]).unique(), events, ff, sec, known, report)
    d = d.with_columns(mi=(pl.col("ym") // 100 * 12 + pl.col("ym") % 100).cast(pl.Int64))
    months = d.select("permno", "mi").unique()
    # The stock-months of the sample must be exactly the published ones.
    pub = (out.filter(pl.col("permno").is_in(sample))
           .select("permno", (pl.col("yyyymm") // 100 * 12 + pl.col("yyyymm") % 100).cast(pl.Int64).alias("mi")))
    key_diff = pub.join(months, on=["permno", "mi"], how="anti").height \
        + months.join(pub, on=["permno", "mi"], how="anti").height
    check(key_diff == 0, f"{key_diff} stock-months differ between the output and the direct check")
    worst = {}
    names = {"rvol_21d": "rvol", "rvol_252d": "rvol", "beta_252d": "beta", "dolvol_21d": "dolvol",
             "dolvol_126d": "dolvol", "spread_quoted_21d": "spread", "bidaskhl_21d": "hl",
             "rvolhl_21d": "sig", "rmax1_21d": "rmax1", "rmax5_21d": "rmax5", "ami_126d": "ami",
             "dolvol_var_126d": "dvvar", "prc_highprc_252d": "prchigh"}
    for k, cols in [(1, ["rvol_21d", "dolvol_21d", "spread_quoted_21d", "bidaskhl_21d",
                         "rvolhl_21d", "rmax1_21d", "rmax5_21d"]),
                    (6, ["dolvol_126d", "ami_126d", "dolvol_var_126d"]),
                    (12, ["rvol_252d", "beta_252d", "prc_highprc_252d"])]:
        # Every daily row goes to the k windows (end months) that contain it.
        w = (d.with_columns(end=pl.int_ranges(pl.col("mi"), pl.col("mi") + k)).explode("end")
             .join(months.rename({"mi": "end"}), on=["permno", "end"], how="semi")
             .sort("permno", "end", "date"))
        ok = pl.col("ret_exc").is_not_null()
        r, m, raw = pl.col("ret_exc").filter(ok), pl.col("mktrf").filter(ok), pl.col("ret").filter(ok)
        n = ok.sum()
        min_obs = MIN_OBS[{1: "21d", 6: "126d", 12: "252d"}[k]]
        good = (n >= min_obs) & (raw.std() > RET_MIN_STD) & ((raw == 0).mean() < CONSTANT_MAX_ZERO_FRAC)
        dv = pl.col("dolvol_d")
        pa = pl.col("prc_adj_d").filter(ok)
        direct = w.group_by("permno", "end", maintain_order=True).agg(
            rvol=pl.when(good).then(r.std()),
            beta=pl.when(good).then(pl.cov(r, m) / m.var()),
            dolvol=pl.when(dv.count() >= min_obs).then(dv.mean()),
            spread=pl.when(pl.col("spread_d").count() >= MIN_SPREAD_DAYS).then(pl.col("spread_d").mean()),
            hl=pl.when(pl.col("spread_hl_d").count() > MIN_SPREAD_DAYS).then(pl.col("spread_hl_d").mean()),
            sig=pl.when(pl.col("spread_hl_d").count() > MIN_SPREAD_DAYS).then(pl.col("sigma_hl_d").mean()),
            rmax1=pl.when(good).then(raw.max()),
            rmax5=pl.when(good).then(raw.sort(descending=True).head(5).mean()),
            ami=pl.when(good & (dv.filter(ok).count() >= min_obs))
            .then((pl.col("ret").abs() / pl.when(dv != 0).then(dv)).filter(ok).mean() * AMI_SCALE),
            dvvar=pl.when((dv.count() >= min_obs) & (dv.min() != dv.max()) & (dv.mean() != 0))
            .then(dv.std() / dv.mean()),
            prchigh=pl.when((n >= min_obs) & (pa.count() >= min_obs) & (pa.min() != pa.max()))
            .then(pa.last() / pa.max()),
        )
        cmp = (out.with_columns(end=(pl.col("yyyymm") // 100 * 12 + pl.col("yyyymm") % 100).cast(pl.Int64))
               .join(direct, on=["permno", "end"], how="inner"))
        for c in cols:
            ref = pl.col(names[c])
            null_diff = cmp.filter(pl.col(c).is_null() != ref.is_null()).height
            # Relative gap, with a floor on the scale (a beta near zero has no relative gap).
            rel = cmp.select(((pl.col(c) - ref).abs() / ref.abs().clip(lower_bound=1e-3)).max()).item()
            worst[c] = {"rows": cmp.height, "values": cmp.filter(pl.col(c).is_not_null()).height,
                        "null_mismatch": null_diff, "max_rel_diff": rel}
            check(null_diff == 0 and (rel is None or rel < 1e-6),
                  f"Direct computation differs for {c}: {worst[c]}")
    report["direct_check_sample"] = {"stocks": len(sample), **worst}


def month_factor(d: pl.DataFrame, panel_keys: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Cumulative share factor on the date of the monthly CRSP row.
    Steps:
        1) Daily rows on a (permno, date) of the monthly panel; exact copies dropped.
        2) One factor per (permno, date), or the script stops.
    Output:
        permno, yyyymm, cfacshr_mth (missing when the daily file has no row that day).
    """
    f = (d.select("permno", "date", "cfacshr")
         .join(panel_keys, on=["permno", "date"], how="inner").unique().sort("permno", "date"))
    check(f.select("permno", "date").is_unique().all(), "Two share factors on the same day")
    check(f.select("permno", "yyyymm").is_unique().all(), "Two monthly rows for one stock-month")
    return f.select("permno", "yyyymm", pl.col("cfacshr").alias("cfacshr_mth"))


def new_signals(out: pl.DataFrame, panel: pl.DataFrame, report: dict) -> None:
    """
    Description:
        Checks of the columns added for the signal step (2026-11-12).
    Steps:
        1) Ranges: rmax1 >= rmax5; 0 < prc_highprc <= 1; finite values.
        2) cfacshr_mth: a split must leave shares x factor unchanged, and the price
           divided by the factor must move like the return without dividends.
        3) Reference cases, computed apart from the raw daily rows.
    Output:
        Entries in the report; CheckError on a failure.
    """
    for c in ["rmax1_21d", "rmax5_21d", "cfacshr_mth"]:
        check(out.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height == 0, f"Non-finite {c}")
    check(out.filter(pl.col("rmax1_21d").is_null() != pl.col("rmax5_21d").is_null()).height == 0,
          "rmax1 and rmax5 do not exist together")
    check(out.filter(pl.col("rmax5_21d") > pl.col("rmax1_21d") + 1e-12).height == 0,
          "Mean of the five highest returns above the highest one")
    check(out.filter(pl.col("rmax1_21d").is_null() != pl.col("rvol_21d").is_null()).height == 0,
          "rmax1 and rvol_21d have different guards")
    # JKP allows a last price of zero, so the ratio can be 0 (none is in our data).
    check(out.filter((pl.col("prc_highprc_252d") < 0) | (pl.col("prc_highprc_252d") > 1 + 1e-12)).height == 0,
          "Price to 12-month high outside [0, 1]")
    report["prc_highprc_252d_equal_to_zero"] = out.filter(pl.col("prc_highprc_252d") == 0).height
    check(out.filter(pl.col("rvolhl_21d").is_null() != pl.col("bidaskhl_21d").is_null()).height == 0,
          "rvolhl_21d and bidaskhl_21d do not exist together")
    check(out.filter(pl.col("cfacshr_mth") <= 0).height == 0, "Share factor not positive")

    # Share factor against the monthly panel, on consecutive months of a stock.
    j = (panel.select("permno", "yyyymm", "eligible", "prc", "retx", "shrout", "del_flag")
         .join(out.select("permno", "yyyymm", "cfacshr_mth"), on=["permno", "yyyymm"], how="left")
         .sort("permno", "yyyymm")
         .with_columns(mi=pl.col("yyyymm") // 100 * 12 + pl.col("yyyymm") % 100))
    prev = lambda c: pl.col(c).shift(1).over("permno")
    j = j.with_columns(
        consecutive=(pl.col("mi") - prev("mi")) == 1,
        cf_prev=prev("cfacshr_mth"), prc_prev=prev("prc"), shr_prev=prev("shrout"),
    ).filter(pl.col("consecutive") & (pl.col("del_flag") == "N") & (pl.col("yyyymm") >= SAMPLE_START)
             & (pl.col("cfacshr_mth") > 0) & (pl.col("cf_prev") > 0)
             & (pl.col("prc") > 0) & (pl.col("prc_prev") > 0) & pl.col("retx").is_not_null())
    implied = (pl.col("prc") / pl.col("cfacshr_mth")) / (pl.col("prc_prev") / pl.col("cf_prev")) - 1
    j = j.with_columns(gap=(implied - pl.col("retx")).abs(),
                       changed=pl.col("cfacshr_mth") != pl.col("cf_prev"),
                       # What the gap would be with no factor at all.
                       gap_raw=((pl.col("prc") / pl.col("prc_prev") - 1) - pl.col("retx")).abs())
    ch = j.filter(pl.col("changed"))
    share = lambda g, c: g.filter(pl.col(c) <= 1e-3).height / g.height
    report["cfacshr_mth"] = {
        "known": int(out["cfacshr_mth"].is_not_null().sum()), "rows": out.height,
        "months_compared": j.height, "share_adjusted_price_matches_retx": share(j, "gap"),
        "months_with_a_factor_change": ch.height,
        "of_which_adjusted_price_matches_retx": share(ch, "gap"),
        "of_which_unadjusted_price_matches_retx": share(ch, "gap_raw"),
    }
    # The factor must explain the price moves of split months: with it, most split
    # months match the return without dividends; without it, almost none do.
    check(share(j, "gap") > 0.99, f"Adjusted prices do not follow retx: {report['cfacshr_mth']}")
    check(share(ch, "gap") > 0.90 and share(ch, "gap_raw") < 0.10,
          f"The share factor does not explain split months: {report['cfacshr_mth']}")
    e = panel.filter(pl.col("eligible") & (pl.col("yyyymm") >= SAMPLE_START)).select(
        "permno", "yyyymm").join(out, on=["permno", "yyyymm"], how="left")
    report["coverage_new_columns_eligible_from_1963"] = {
        c: round(e[c].is_not_null().mean(), 4)
        for c in ["rmax1_21d", "rmax5_21d", "rvolhl_21d", "ami_126d", "dolvol_var_126d",
                  "prc_highprc_252d", "cfacshr_mth"]}

    # IBM (12490): 2-for-1 split in May 1999. The local factor halves (its level
    # depends on the first daily row of the stock; only the ratio has a meaning).
    ibm = out.filter((pl.col("permno") == 12490) & pl.col("yyyymm").is_in([199904, 199905])).sort("yyyymm")
    check(ibm.height == 2 and abs(ibm["cfacshr_mth"][0] / ibm["cfacshr_mth"][1] - 2) < 1e-12,
          f"Reference 12490 (split of May 1999) failed: {ibm['cfacshr_mth'].to_list()}")
    # 12350: the CRSP factor is exported as zero from 2010 to 2024 (eleven later
    # reverse splits), with no share event before May 2016: the local factor is 1.
    z = out.filter((pl.col("permno") == 12350) & (pl.col("yyyymm") <= 201604))["cfacshr_mth"]
    check(z.len() > 0 and z.null_count() == 0 and (z == 1.0).all(), "Reference 12350 (factor before 2016) failed")

    # Reference cases. Those of 14593, 12490 and 10107 (2015) were computed apart
    # from the raw daily rows, with a script that shares no code with this one;
    # those of 37022, 10002, 10107 (2001) and 12350 were recomputed by the auditor
    # from the raw daily CSV (audit of 2026-11-12).
    seen = {}
    for permno, yyyymm, column, expected, tol in REFERENCE_CASES:
        got = out.filter((pl.col("permno") == permno) & (pl.col("yyyymm") == yyyymm))[column].to_list()
        seen[f"{permno}_{yyyymm}_{column}"] = got
        check(len(got) == 1 and got[0] is not None and abs(got[0] - expected) <= tol * max(1.0, abs(expected)),
              f"Reference {permno} {yyyymm} {column} failed: {got}, expected {expected}")
    report["reference_new_columns"] = seen


REFERENCE_CASES = [
    (12350, 201211, "prc_highprc_252d", 0.4462151394, 1e-9),
    (12350, 201211, "rvolhl_21d", 0.0691384712, 1e-9),
    (37022, 197812, "rmax1_21d", 0.016000, 1e-9), (37022, 197812, "rmax5_21d", 0.0110876, 1e-9),
    (37022, 197812, "rvolhl_21d", 0.0090037613, 1e-9), (37022, 197812, "ami_126d", 3.2320529726, 1e-9),
    (37022, 197812, "dolvol_var_126d", 2.2035250156, 1e-9),
    (37022, 197812, "prc_highprc_252d", 0.9924242424, 1e-9),
    (10002, 199404, "rmax1_21d", 0.060000, 1e-9), (10002, 199404, "rmax5_21d", 0.0466416, 1e-9),
    (10002, 199404, "rvolhl_21d", 0.0015023953, 1e-9), (10002, 199404, "ami_126d", 13.1899783174, 1e-9),
    (10002, 199404, "dolvol_var_126d", 2.9052004361, 1e-9),
    (10002, 199404, "prc_highprc_252d", 0.8928571429, 1e-9),
    (10107, 200103, "rmax1_21d", 0.078652, 1e-9), (10107, 200103, "rmax5_21d", 0.0486532, 1e-9),
    (10107, 200103, "rvolhl_21d", 0.0260801364, 1e-9), (10107, 200103, "ami_126d", 0.0000193197798, 1e-9),
    (10107, 200103, "dolvol_var_126d", 0.3954426771, 1e-9),
    (10107, 200103, "prc_highprc_252d", 0.6017881706, 1e-9),
    # Apple (14593), August 2020: 4-for-1 split on the last day of the month, the
    # adjusted price ends the month at its 12-month high.
    (14593, 202008, "rmax1_21d", 0.051532, 1e-9),
    (14593, 202008, "rmax5_21d", 0.035753, 1e-9),
    (14593, 202008, "ami_126d", 1.5167500297332397e-06, 1e-9),
    (14593, 202008, "dolvol_var_126d", 0.45903242628845725, 1e-9),
    (14593, 202008, "prc_highprc_252d", 1.0, 1e-9),
    # IBM (12490), May 1999 (NYSE): split inside the 12-month window.
    (12490, 199905, "rmax1_21d", 0.090909, 1e-9),
    (12490, 199905, "rmax5_21d", 0.0464482, 1e-9),
    (12490, 199905, "ami_126d", 1.9902019765966455e-05, 1e-9),
    (12490, 199905, "dolvol_var_126d", 0.5595022563201937, 1e-9),
    (12490, 199905, "prc_highprc_252d", 0.943089430894309, 1e-9),
    # Microsoft (10107), March 2015: no split in the window.
    (10107, 201503, "rmax1_21d", 0.019307, 1e-9),
    (10107, 201503, "rmax5_21d", 0.0116144, 1e-9),
    (10107, 201503, "ami_126d", 6.52933729593014e-06, 1e-9),
    (10107, 201503, "dolvol_var_126d", 0.44688720690071526, 1e-9),
    (10107, 201503, "prc_highprc_252d", 0.8194920378955856, 1e-9),
]


def vintage_test(raw: pl.DataFrame, events: pl.DataFrame, ff: pl.DataFrame, sec: pl.DataFrame,
                 known: list[int], report: dict) -> None:
    """
    Description:
        Later vintages of the CRSP file, simulated on a sample: the levels of the
        cumulative share factor are divided by 1e7 (many fall below the precision
        limit) or by 1e13 (most are rounded to exactly zero, so that only the
        dated events are left), and rounded to 12 decimals.
    Steps:
        1) Local factor from the true levels and from the simulated ones.
        2) The columns that use the factor (high-low spread and volatility, price
           to the 12-month high) are rebuilt from both.
        3) Regular stocks: same missing values everywhere, every local factor
           within 1e-4, every column within 1e-3. A failure stops the script.
        4) The stocks of `known` have a change of the CRSP factor that the dated
           events do not give (see MAX_UNMATCHED_FACTOR_CHANGES). A later vintage
           can change their local factor: the effect is measured and reported, it
           is a declared limit.
    Output:
        Entry "vintage_test" in the report; CheckError on a failure.
    """
    cols = ["bidaskhl_21d", "rvolhl_21d", "prc_highprc_252d", "n_hl_observed_21d"]

    def build(frame: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
        tmp = {k: 0 for k in COUNTS}
        f = local_share_factor(frame, events, tmp)
        stats = window_stats(month_sums(prepare_batch(f, ff, sec, tmp))).select("permno", "yyyymm", *cols)
        return f.select("permno", "date", "cfacshr"), stats, tmp

    fa, sa, _ = build(raw)
    is_known = pl.col("permno").is_in(known)
    res = {}
    for name, scale in [("divided_by_1e7", 1e-7), ("divided_by_1e13", 1e-13)]:
        fb, sb, tmp2 = build(raw.with_columns((pl.col("cfacshr") * scale).round(12)))
        j = fa.join(fb.rename({"cfacshr": "sim"}), on=["permno", "date"])
        j = j.with_columns(null_diff=pl.col("cfacshr").is_null() != pl.col("sim").is_null(),
                           gap=(pl.col("sim") / pl.col("cfacshr") - 1).abs())
        k = sa.join(sb, on=["permno", "yyyymm"], suffix="_sim")
        check(j.height == fa.height and k.height == sa.height, "The vintage test lost rows")

        def summary(jj: pl.DataFrame, kk: pl.DataFrame) -> dict:
            stocks = jj.group_by("permno").agg(worst=pl.col("gap").max())
            out = {"stocks": stocks.height, "rows": jj.height,
                   "factor_null_mismatch": jj.filter(pl.col("null_diff")).height,
                   "factor_stocks_within_1e-4": stocks.filter(pl.col("worst").fill_null(0) <= 1e-4).height,
                   "factor_max_gap": jj["gap"].max()}
            for c in cols:
                # Floats on both sides (one column is a count of days).
                a, b = pl.col(c).cast(pl.Float64), pl.col(f"{c}_sim").cast(pl.Float64)
                rel = (a - b).abs() / a.abs().clip(lower_bound=1e-12)
                out[c] = {"null_mismatch": kk.filter(a.is_null() != b.is_null()).height,
                          "values_moved_by_more_than_1e-3": kk.filter(rel > 1e-3).height,
                          "max_rel_gap": kk.select(rel.max()).item()}
            return out

        regular = summary(j.filter(~is_known), k.filter(~is_known))
        res[name] = {
            "simulated_rows_below_min_level": tmp2["factor_rows_below_min_level"],
            "simulated_rows_exactly_zero": tmp2["factor_rows_exactly_zero"],
            "steps_taken_from_events": tmp2["factor_steps_from_events"],
            "regular_stocks": regular,
            "stocks_with_an_unexplained_factor_change": summary(j.filter(is_known), k.filter(is_known)),
        }
        check(regular["factor_null_mismatch"] == 0, f"A later vintage ({name}) changes which factors are missing")
        check(regular["factor_stocks_within_1e-4"] == regular["stocks"],
              f"The local factor depends on the vintage ({name}): {regular}")
        for c in cols:
            check(regular[c]["null_mismatch"] == 0 and regular[c]["values_moved_by_more_than_1e-3"] == 0,
                  f"{c} depends on the vintage ({name}): {regular[c]}")
    check(res["divided_by_1e13"]["simulated_rows_exactly_zero"] > 0, "The extreme vintage simulates no zero")
    report["vintage_test"] = res


COUNTS = ["rows", "exact_duplicate_rows", "factor_rows_below_min_level", "factor_rows_exactly_zero",
          "factor_steps_from_events", "factor_stocks_using_events",
          "factor_changes_between_precise_levels", "precise_changes_not_matched_by_events",
          "delisting_rows_dropped", "returns_dropped_after_long_gap",
          "returns_after_row_gap_over_14d", "returns_without_previous_price",
          "rows_without_market_return", "rows_with_unknown_exchange"]


def checks(out: pl.DataFrame, panel: pl.DataFrame, report: dict) -> None:
    check(out.select("permno", "yyyymm").is_unique().all(), "Duplicate stock-month")
    # Only data of month t or before: the last daily date used is inside the month.
    check(out.filter((pl.col("last_date").dt.year() * 100 + pl.col("last_date").dt.month())
                     != pl.col("yyyymm")).height == 0, "A daily date outside its month")
    for c in ["rvol_21d", "rvol_252d", "dolvol_21d", "dolvol_126d", "spread_quoted_21d", "bidaskhl_21d",
              "rvolhl_21d", "ami_126d", "dolvol_var_126d", "prc_highprc_252d"]:
        check(out.filter(pl.col(c) < 0).height == 0, f"Negative {c}")
        check(out.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height == 0, f"Non-finite {c}")
    check(out.filter(pl.col("beta_252d").is_not_null() & ~pl.col("beta_252d").is_finite()).height == 0,
          "Non-finite beta")

    new_signals(out, panel, report)

    # First-day return: a real return, and consistent with the month. On months
    # with a return every day, (1 + ret_d1) x (rest of the month) = the compounded
    # month, so the rest of the month must be a valid return too.
    check(out.filter(pl.col("ret_d1") < -1).height == 0, "First-day return below -100 %")
    check(out.filter(pl.col("ret_d1").is_not_null() & ~pl.col("ret_d1").is_finite()).height == 0,
          "Non-finite first-day return")
    full = out.filter((pl.col("n_ret_raw") == pl.col("n_days")) & (pl.col("ret_d1") > -1))
    rest = (1 + pl.col("ret_cmp")) / (1 + pl.col("ret_d1")) - 1
    check(full.filter((rest < -1 - 1e-9) | ~rest.is_finite()).height == 0,
          "Return after the first day is not a valid return")
    report["ret_d1"] = {"known": int(out["ret_d1"].is_not_null().sum()), "rows": out.height}
    # Reference: Apple (14593), August 2020. First trading day August 3: +2.52 %.
    ref = out.filter((pl.col("permno") == 14593) & (pl.col("yyyymm") == 202008))["ret_d1"]
    report["reference_14593_202008_ret_d1"] = ref.to_list()
    check(ref.len() == 1 and ref[0] is not None and abs(ref[0] - 0.0252) < 0.0005,
          f"Reference 14593 (ret_d1) failed: {ref.to_list()}")
    # Independent source cases, recomputed by the auditor from the raw daily CSV
    # (audit of the backtest rules, 2026-11-12). They test that the day chosen is
    # the first day of the MARKET calendar, not the first row of the stock:
    # 10000, 1986-01: market open on the 2nd, first row of the stock on the 7th;
    # 37022, 1978-12: row on the 1st without a return (suspension);
    # 10050, 1978-06 and 65788, 1974-10: bid-ask close on the first day;
    # 12964, 2013-07: delisting month added by D9; 12085, 2014-02: flag V.
    d1_cases = [(10000, 198601, None), (37022, 197812, None), (10050, 197806, 0.0),
                (12964, 201307, -0.754254), (65788, 197410, -0.30), (12085, 201402, -0.009456)]
    d1_seen = {}
    for permno, yyyymm, expected in d1_cases:
        got = out.filter((pl.col("permno") == permno) & (pl.col("yyyymm") == yyyymm))["ret_d1"].to_list()
        d1_seen[f"{permno}_{yyyymm}"] = got
        ok = len(got) == 1 and (got[0] is None if expected is None
                                else got[0] is not None and abs(got[0] - expected) < 5e-7)
        check(ok, f"Reference {permno} {yyyymm} (ret_d1) failed: {got}, expected {expected}")
    report["reference_ret_d1_source_cases"] = d1_seen

    # Audit reference cases (step 9 audit).
    # 62500, March 2000: NYSE until the 20th, NASDAQ from the 21st. The volume must
    # be adjusted day by day (29.1 million USD a day; 17.1 with a monthly flag).
    ref = out.filter((pl.col("permno") == 62500) & (pl.col("yyyymm") == 200003))["dolvol_21d"]
    report["reference_62500_200003_dolvol_21d"] = ref.to_list()
    check(ref.len() == 1 and abs(ref[0] - 29_143_056) < 1_000, f"Reference 62500 failed: {ref.to_list()}")
    # 37022, December 1978: a +103 % return after weeks without a price must not
    # enter the volatility (1.05 % a day; 23.65 % with it).
    ref = out.filter((pl.col("permno") == 37022) & (pl.col("yyyymm") == 197812))["rvol_21d"]
    report["reference_37022_197812_rvol_21d"] = ref.to_list()
    check(ref.len() == 1 and ref[0] is not None and abs(ref[0] - 0.0105) < 0.0005,
          f"Reference 37022 failed: {ref.to_list()}")
    report["stock_months_with_a_dropped_long_gap_return"] = out.filter(pl.col("n_long_gap") > 0).height
    # High-low spread resting only on carried ranges.
    report["high_low_months_without_observed_range"] = out.filter(
        pl.col("bidaskhl_21d").is_not_null() & (pl.col("n_hl_observed_21d") == 0)).height

    # Cross-step check of the monthly adjusted volume of step 3. On months where
    # the daily rows add up to the monthly raw volume:
    #  - no exchange transfer: the monthly adjusted volume = the sum of the daily ones;
    #  - transfer flagged at step 3: the monthly value must be missing.
    v = (panel.select("permno", "yyyymm", "vol", "vol_adj", "vol_exch_transfer")
         .join(out.select("permno", "yyyymm", "s_vol", "s_vol_adj", "n_nasdaq_days", "n_exch_days"),
               on=["permno", "yyyymm"])
         .filter((pl.col("vol") == pl.col("s_vol")) & (pl.col("yyyymm") <= 200312)))
    mixed = (pl.col("n_nasdaq_days") > 0) & (pl.col("n_nasdaq_days") < pl.col("n_exch_days"))
    bad = v.filter(pl.col("vol_adj").is_not_null()
                   & ((pl.col("vol_adj") - pl.col("s_vol_adj")).abs()
                      > 1e-6 * pl.col("vol_adj").abs().clip(lower_bound=1.0)))
    report["monthly_vs_daily_adjusted_volume"] = {
        "months_compared": v.height, "differences": bad.height,
        "months_with_a_transfer_in_the_daily_rows": v.filter(mixed).height,
        "of_which_flagged_at_step_3": v.filter(mixed & pl.col("vol_exch_transfer")).height,
    }
    check(bad.height == 0, f"{bad.height} months where the monthly adjusted volume of step 3 "
                           f"differs from the sum of the daily ones")
    # Not flagged at step 3 but mixed in the daily rows: allowed only if the values
    # agree (checked above), e.g. all the volume traded on one side.
    report["monthly_vs_daily_adjusted_volume"]["mixed_not_flagged_but_equal"] = v.filter(
        mixed & pl.col("vol_adj").is_not_null()).height

    j = panel.select("permno", "yyyymm", "eom", "eligible", "me", "ret_crsp", "del_flag", "size_grp"
                     ).join(out, on=["permno", "yyyymm"], how="left")
    # Independent check of the daily file: daily returns compounded over the month
    # against the CRSP monthly return (normal months with a return on every day).
    c = j.filter((pl.col("del_flag") == "N") & pl.col("ret_crsp").is_not_null()
                 & (pl.col("n_ret_raw") == pl.col("n_days")) & (pl.col("yyyymm") >= SAMPLE_START))
    diff = (pl.col("ret_cmp") - pl.col("ret_crsp")).abs()
    report["daily_vs_monthly_return"] = {
        "rows": c.height, "share_within_0.0001": c.filter(diff <= 1e-4).height / c.height,
        "share_within_0.01": c.filter(diff <= 1e-2).height / c.height,
        "corr": c.select(pl.corr("ret_cmp", "ret_crsp")).item(),
    }
    check(report["daily_vs_monthly_return"]["corr"] > 0.99, "Daily and monthly returns disagree")

    e = j.filter(pl.col("eligible") & (pl.col("yyyymm") >= SAMPLE_START))
    e = e.with_columns(
        spread_any=pl.coalesce("spread_quoted_21d", "bidaskhl_21d"),
        # Usable by the cost rule: a quoted spread, or a high-low spread that rests
        # on at least one range observed in the month (not only carried ranges).
        spread_rule=pl.coalesce(
            "spread_quoted_21d",
            pl.when(pl.col("n_hl_observed_21d") > 0).then(pl.col("bidaskhl_21d"))),
    )
    cols = ["rvol_21d", "rvol_252d", "beta_252d", "dolvol_126d", "spread_quoted_21d",
            "bidaskhl_21d", "spread_any", "spread_rule"]
    cov = lambda g: {c: {"n": round(g[c].is_not_null().mean(), 4),
                         "me": round(g.filter(pl.col(c).is_not_null())["me"].sum() / g["me"].sum(), 4)}
                     for c in cols}
    report["coverage_eligible_from_1963"] = {"rows": e.height, **cov(e)}
    report["coverage_by_decade"] = {
        str(d): cov(g) for (d,), g in e.with_columns(decade=pl.col("yyyymm") // 1000 * 10)
        .sort("decade").group_by("decade", maintain_order=True)}
    report["medians_eligible"] = {c: e[c].median() for c in cols}
    report["spread_median_by_size_grp"] = {
        str(s): g["spread_quoted_21d"].median()
        for (s,), g in e.sort("size_grp").group_by("size_grp", maintain_order=True)}
    # The two spread measures on stock-months that have both (no quote is needed
    # for the high-low one, so it covers the years before quotes exist).
    both = e.filter(pl.col("spread_quoted_21d").is_not_null() & pl.col("bidaskhl_21d").is_not_null())
    rank_corr = both.group_by("yyyymm").agg(
        pl.corr("spread_quoted_21d", "bidaskhl_21d", method="spearman").alias("c"),
        pl.len().alias("k")).filter(pl.col("k") >= 100)["c"].fill_nan(None).mean()
    report["quoted_vs_high_low_spread"] = {
        "rows": both.height, "mean_monthly_rank_corr": rank_corr,
        "median_quoted": both["spread_quoted_21d"].median(),
        "median_high_low": both["bidaskhl_21d"].median(),
    }
    report["high_low_spread_median_by_size_grp"] = {
        str(s): g["bidaskhl_21d"].median()
        for (s,), g in e.sort("size_grp").group_by("size_grp", maintain_order=True)}
    check(rank_corr > 0.3, f"High-low spread unrelated to the quoted spread: {rank_corr}")
    # Sanity: the value-weighted beta of the market must be close to 1.
    b = e.filter(pl.col("beta_252d").is_not_null()).group_by("yyyymm").agg(
        ((pl.col("me") * pl.col("beta_252d")).sum() / pl.col("me").sum()).alias("vw_beta"))
    report["vw_beta"] = {"mean": b["vw_beta"].mean(), "min": b["vw_beta"].min(), "max": b["vw_beta"].max()}
    check(0.95 < b["vw_beta"].mean() < 1.05, f"Value-weighted beta far from 1: {report['vw_beta']}")
    check(report["coverage_eligible_from_1963"]["rvol_252d"]["me"] > 0.9, "Low volatility coverage")


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/9_crsp_daily_agg.py", "inputs": {}}
    panel, run_id = read_verified(PANEL, PANEL_REPORT)
    report["inputs"][PANEL.name] = {"from_run": run_id}
    ff = read_french_daily(report)
    convert_daily(report)

    # Exchange history, to apply the NASDAQ volume adjustment day by day.
    sec = read_exchange_history(report)
    events = read_share_events(report)

    permnos = pl.scan_parquet(DAILY_MIN).select("permno").unique().collect()["permno"].sort()
    report["daily_stocks"] = permnos.len()
    counts = {k: 0 for k in COUNTS}
    counts["_unmatched"] = []
    parts, factors = [], []
    panel_keys = panel.select("permno", "date", "yyyymm")
    step = -(-permnos.len() // N_BATCHES)
    for i in range(0, permnos.len(), step):
        lo, hi = permnos[i], permnos[min(i + step, permnos.len()) - 1]
        d = pl.scan_parquet(DAILY_MIN).filter(pl.col("permno").is_between(lo, hi)).collect()
        d = local_share_factor(d, events, counts)
        factors.append(month_factor(d, panel_keys))
        parts.append(month_sums(prepare_batch(d, ff, sec, counts)))
    report["unexplained_factor_changes"] = counts.pop("_unmatched")
    report["daily_counts"] = counts
    check(counts["precise_changes_not_matched_by_events"] <= MAX_UNMATCHED_FACTOR_CHANGES,
          f"{counts['precise_changes_not_matched_by_events']} changes of the CRSP share factor are not "
          f"explained by the dated events (at most {MAX_UNMATCHED_FACTOR_CHANGES} known cases)")
    sums = pl.concat(parts)
    check(sums.select("permno", "ym").is_unique().all(), "A stock-month in two batches")
    out = window_stats(sums)
    n_out = out.height
    out = out.join(pl.concat(factors), on=["permno", "yyyymm"], how="left")
    check(out.height == n_out, "The share factor join changed the row count")
    report["rows"] = out.height

    check_direct(out, ff, sec, events, report)
    checks(out, panel, report)
    out = out.drop("ret_cmp", "n_ret_raw", "n_long_gap", "s_vol", "s_vol_adj", "n_nasdaq_days",
                   "n_exch_days")
    report["inputs"][DAILY_MIN.name] = sha256(DAILY_MIN)
    publish({PROCESSED / "crsp_daily_agg.parquet": out}, report, PROCESSED / "crsp_daily_agg_report.json")
    print(f"crsp_daily_agg: {counts['rows']:,} daily rows -> {out.height:,} stock-months. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
