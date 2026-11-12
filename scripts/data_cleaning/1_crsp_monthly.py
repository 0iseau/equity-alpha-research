"""Steps 1-2 of CleaningSpec.md: monthly CRSP panel, one row per stock and month.

Reference code (Resources/reference_code/):
- JKP jkp-data, aux_functions.py:
    gen_crsp_sf      -> column choice, bidask flag, shrout in millions
    prepare_crsp_sf  -> delisting-return adjustment (CIZ flags), me_company
- Tidy Finance, chapters/wrds-crsp-and-compustat.qmd:
    mktcap = 0 -> null, mktcap_lag from a one-month shifted join

Deviations from the references (see CleaningSpec.md):
- No security-info or link join here (steps 3 and 6).
- me = MthCap / 1000, not prc * shrout (JKP): in 180 rows the last price is older
  than the share count, and only MthCap uses the shares at the price date.
- Volume stays in shares. JKP scales monthly vol by 100, but in our export MthVol
  equals the sum of DlyVol.
- NASDAQ volume adjustment and dollar volume move to step 3 (they need the exchange).
- A row is added when a stock delists in the month after its last CRSP row (D9).
  Its return = daily returns from the last month-end to the delisting date,
  compounded with the delisting return. JKP's join drops these returns.
- No "ret = 0" fill (JKP): when a part of the holding return is unknown, ret stays
  missing and ret_status says why. ret_crsp keeps the raw MthRet.
- No div_tot: our export has no MthCumFacShr. Dividends stay in the distributions table.

Outputs (data/processed/):
- crsp_monthly.parquet          one row per permno and month
- crsp_distributions.parquet    one row per distribution event
- crsp_d9_reconciliation.csv    one row per added delisting month
- crsp_monthly_report.json      checks, counts and output hashes (written last)
"""

from __future__ import annotations

import polars as pl

from utils import (PROCESSED, RAW, CheckError, check, check_unchanged, file_stamps, publish,
                   sha256)

SRC = RAW / "crsp_ciz_monthly_stock.csv"
DAILY = RAW / "crsp_ciz_daily_stock.csv"
DELIST = RAW / "crsp_ciz_delistings.csv"
INDEX = RAW / "crsp_ciz_monthly_market_indexes.csv"

KEY = ["PERMNO", "YYYYMM"]
# Columns with one true value per stock and month.
STOCK_COLS = [
    "PERMCO", "MthCalDt", "MthCompFlg", "MthCompSubFlg", "MthPrc", "MthPrcFlg", "MthPrcDt",
    "MthDtFlg", "MthDelFlg", "MthCap", "MthPrevPrc", "MthPrevPrcFlg", "MthPrevDt",
    "MthPrevDtFlg", "MthPrevCap", "MthRet", "MthRetx", "MthRetFlg", "MthDisCnt", "MthVol",
    "MthVolFlg", "MthPrcVol", "MthFacShrFlg", "MthPrcVolMissCnt", "ShrStartDt", "ShrEndDt",
    "ShrOut",
]
# Name fields: they can change inside a month, we keep the last one.
DESC_COLS = ["HdrCUSIP", "SecurityNm", "Ticker", "NASDCompno", "NASDIssuno"]
# Market index columns repeated on every row: dropped (the index file has them).
MARKET_COLS = ["vwretd", "vwretx", "ewretd", "ewretx", "sprtrn"]
NUM_COLS = ["MthPrc", "MthCap", "MthPrevPrc", "MthPrevCap", "MthRet", "MthRetx", "MthVol",
            "MthPrcVol", "ShrOut"]
DATE_COLS = ["MthCalDt", "MthPrcDt", "MthPrevDt", "ShrStartDt", "ShrEndDt"]

# Flag values we know (CRSP CIZ guide). Any other value, or a null, stops the script.
KNOWN_FLAGS = {
    "MthDelFlg": {"A", "P", "M", "G", "N", "V"},
    "MthRetFlg": {"CR", "NT", "NS", "DE", "MP", "IP", "GP"},
    "MthPrcFlg": {"TR", "BA", "MP"},
}
# Delisting flags where MthRet already holds the delisting return (JKP).
INCLUDED_FLAGS = ["A", "P", "V"]

# JKP prepare_crsp_sf: CIZ reasons for a "bad" delisting (legacy dlstcd 520-584).
BAD_DELIST_REASONS = [
    "MVOT", "MTMK", "SHLD", "LP", "INSC", "INSF", "CORQ", "DERE",
    "BKPY", "OFFRE", "DELQ", "FARG", "EQRQ", "DEEX", "FING",
]
# Reference cases from the audit (2026-11-11): expected D9 returns.
REFERENCE_D9 = {65788: -0.227349, 12964: -0.7982}


def gen_mmyy(var: str) -> pl.Expr:
    # Month index year*12+month, as in JKP gen_MMYY_column.
    return (pl.col(var).dt.year() * 12 + pl.col(var).dt.month()).cast(pl.Int32)


def read_header() -> list[str]:
    # Check the raw columns before reading the data.
    header = pl.read_csv(SRC, n_rows=0).columns
    check(len(header) == len(set(header)), "Duplicate column names in the monthly file")
    dis_cols = [c for c in header if c.startswith("Dis")]
    expected = set(KEY + STOCK_COLS + DESC_COLS + MARKET_COLS + dis_cols)
    check(set(header) == expected, f"Unexpected columns: {sorted(set(header) ^ expected)}")
    return dis_cols


def build_panel(lf: pl.LazyFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        One row per stock and month from the raw rows (one raw row per distribution).
    Steps:
        1) Check that every stock-level column has one value per stock and month.
        2) Keep that value, and the last name fields of the month.
        3) Check flags, cast types, check keys, dates and numbers.
    Output:
        Panel with raw CRSP columns, typed.
    """
    raw = lf.select(["row", *KEY, *STOCK_COLS, *DESC_COLS]).collect()
    report["raw_rows"] = raw.height

    # Stock-level values must be the same on all rows of a stock-month.
    n_keys = raw.select(KEY).unique().height
    n_distinct = raw.select(KEY + STOCK_COLS).unique().height
    check(n_keys == n_distinct, f"{n_distinct - n_keys} stock-months have conflicting stock fields")

    panel = (
        raw.sort("row")
        .group_by(KEY, maintain_order=True)
        .agg([pl.col(c).first() for c in STOCK_COLS] + [pl.col(c).last() for c in DESC_COLS])
    )
    report["stock_months"] = panel.height

    # Flags: no null and no unknown value.
    for flag, known in KNOWN_FLAGS.items():
        check(panel[flag].null_count() == 0, f"Null {flag} values")
        seen = set(panel[flag].unique().to_list())
        check(seen <= known, f"Unknown {flag} values: {sorted(seen - known)}")
        report[f"{flag}_counts"] = dict(panel[flag].value_counts().iter_rows())

    # Cast types. strict=True: a non-numeric value stops the script.
    panel = panel.with_columns(
        [pl.col(c).cast(pl.Float64, strict=True) for c in NUM_COLS]
        + [pl.col(c).str.to_date("%Y-%m-%d", strict=True) for c in DATE_COLS]
        + [pl.col(c).cast(pl.Int64, strict=True) for c in ["PERMNO", "PERMCO", "MthDisCnt"]]
        + [pl.col("YYYYMM").cast(pl.Int32, strict=True)]
    )

    # Keys and the calendar date are required.
    for c in ["PERMNO", "PERMCO", "YYYYMM", "MthCalDt"]:
        check(panel[c].null_count() == 0, f"Null values in required column {c}")
    # The calendar date must sit in the YYYYMM month.
    bad_month = panel.filter(
        pl.col("MthCalDt").dt.year() * 100 + pl.col("MthCalDt").dt.month() != pl.col("YYYYMM")
    ).height
    check(bad_month == 0, f"{bad_month} rows have MthCalDt outside YYYYMM")
    # Numbers must be finite; prices, caps and shares positive when present.
    for c in NUM_COLS:
        check(panel.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height == 0,
              f"Non-finite values in {c}")
    for c in ["MthPrc", "ShrOut"]:
        check(panel.filter(pl.col(c) <= 0).height == 0, f"Non-positive values in {c}")
    check(panel.filter(pl.col("MthCap") < 0).height == 0, "Negative MthCap")
    check(panel.filter(pl.col("MthRet") < -1).height == 0, "MthRet below -100%")
    return panel


def read_delistings(report: dict) -> pl.DataFrame:
    # Delisting file, typed. One record per permno (checked).
    dl = pl.read_csv(DELIST, infer_schema=False).select(
        pl.col("permno").cast(pl.Int64, strict=True).alias("PERMNO"),
        pl.col("delistingdt").str.to_date("%Y-%m-%d", strict=True),
        pl.col("delret").cast(pl.Float64, strict=True),
        "delactiontype", "delstatustype", "delreasontype", "delpaymenttype", "delretmisstype",
        pl.col("delamtdt").str.to_date("%Y-%m-%d", strict=True),
        pl.col("delnextdt").str.to_date("%Y-%m-%d", strict=True),
    )
    check(dl["PERMNO"].null_count() == 0 and dl["delistingdt"].null_count() == 0,
          "Delisting records without permno or date")
    check(dl["PERMNO"].is_unique().all(), "More than one delisting record per permno")
    dr = pl.col("delret")
    check(dl.filter(dr.is_not_null() & (~dr.is_finite() | (dr < -1))).height == 0,
          "Invalid delret values in the delisting file")
    report["delist_file_first_date"] = dl["delistingdt"].min()
    return dl.with_columns(merge_aux=gen_mmyy("delistingdt"))


def pre_delisting_returns(d9: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Return from the last month-end to the delisting date, from daily data.
    Steps:
        1) Read all daily rows of the D9 stocks; check flags, unique dates, returns.
        2) Keep DlyDelFlg = 'N' rows (the 'Y' row holds the delisting return)
           after the last monthly date, up to the delisting date.
        3) Compound the available daily returns. CRSP bridges days with a
           missing price: the next return covers the gap.
        4) Break: a day with a price but no return means CRSP did not link that
           price to the previous one. The chain is cut, so the part is unknown.
    Output:
        permno, ret_pre_delist (null if unknown), day counts, pre_delist_break.
    """
    daily = (
        pl.scan_csv(DAILY, infer_schema=False)
        .select("PERMNO", "DlyCalDt", "DlyDelFlg", "DlyRet", "DlyPrc")
        .with_columns(pl.col("PERMNO").cast(pl.Int64, strict=True))
        .filter(pl.col("PERMNO").is_in(d9["PERMNO"].to_list()))
        .with_columns(
            pl.col("DlyCalDt").str.to_date("%Y-%m-%d", strict=True),
            pl.col("DlyRet").cast(pl.Float64, strict=True),
            pl.col("DlyPrc").cast(pl.Float64, strict=True),
        )
        .collect(engine="streaming")
    )
    # Checks before any filter: known flags, one row per day, valid returns.
    check(daily["DlyDelFlg"].null_count() == 0, "Null DlyDelFlg in daily rows of D9 stocks")
    flags = set(daily["DlyDelFlg"].unique().to_list())
    check(flags <= {"N", "Y"}, f"Unknown DlyDelFlg values: {sorted(flags - {'N', 'Y'})}")
    check(daily["DlyCalDt"].null_count() == 0, "Null daily dates in D9 stocks")
    # The daily file repeats some days (exact copies on these columns): keep one.
    # Two different rows for the same day stop the script.
    n_raw = daily.height
    # JKP practice: unique() does not keep the row order, so sort right after it.
    daily = daily.unique().sort("PERMNO", "DlyCalDt")
    check(daily.select("PERMNO", "DlyCalDt").is_duplicated().sum() == 0,
          "Conflicting rows for the same permno-day in daily rows of D9 stocks")
    report["d9_daily_exact_copies_dropped"] = n_raw - daily.height
    ret = pl.col("DlyRet")
    check(daily.filter(ret.is_not_null() & (~ret.is_finite() | (ret < -1))).height == 0,
          "Invalid daily returns in D9 stocks")

    window = (
        daily.filter(pl.col("DlyDelFlg") == "N")
        .join(d9.select("PERMNO", "last_date", "delistingdt"), on="PERMNO")
        .filter((pl.col("DlyCalDt") > pl.col("last_date"))
                & (pl.col("DlyCalDt") <= pl.col("delistingdt")))
        # Fixed order: a product of floats depends on the order of its terms, and
        # unique() above does not keep the row order.
        .sort("PERMNO", "DlyCalDt")
    )
    pre = window.group_by("PERMNO", maintain_order=True).agg(
        pl.len().alias("window_days"),
        ret.is_not_null().sum().alias("window_days_with_ret"),
        (pl.col("DlyPrc").is_not_null() & ret.is_null()).any().alias("pre_delist_break"),
        ((ret + 1).product() - 1).alias("ret_pre_delist"),
    )
    # Unknown part: no daily return, or a break in the chain of prices.
    pre = pre.with_columns(
        ret_pre_delist=pl.when((pl.col("window_days_with_ret") > 0) & ~pl.col("pre_delist_break"))
        .then(pl.col("ret_pre_delist"))
        .otherwise(None)
    )
    return d9.select("PERMNO").join(pre, on="PERMNO", how="left")


def add_delisting_months(panel: pl.DataFrame, dl: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Add a row for delistings that happen in the month after the last CRSP row
        (decision D9). Not in JKP: their join drops these delisting returns.
    Steps:
        1) Find delistings with no CRSP row in the delisting month.
        2) Check that each one is exactly one month after the stock's last row.
        3) Add a row for that month: date = delisting date, CRSP values null.
        4) Attach the pre-delisting return from daily data.
    Output:
        Panel with extra rows (delist_row_added = True) and ret_pre_delist.
    """
    months = panel.select(
        "PERMNO", "PERMCO", "Ticker", "HdrCUSIP", "MthCalDt", merge_aux=gen_mmyy("MthCalDt")
    )
    no_row = dl.join(months.select("PERMNO", "merge_aux"), on=["PERMNO", "merge_aux"], how="anti")
    last = months.group_by("PERMNO").agg(pl.all().sort_by("merge_aux").last())
    no_row = no_row.join(last, on="PERMNO", how="left", suffix="_last")

    report["delistings_stock_not_in_file"] = no_row["merge_aux_last"].null_count()
    no_row = no_row.filter(pl.col("merge_aux_last").is_not_null())
    other_gap = no_row.filter(pl.col("merge_aux") != pl.col("merge_aux_last") + 1).height
    check(other_gap == 0, f"{other_gap} delistings are not in the month after the last CRSP row")

    d9 = no_row.select(
        "PERMNO", "PERMCO", "Ticker", "HdrCUSIP", "delistingdt",
        pl.col("MthCalDt").alias("last_date"),
    )
    pre = pre_delisting_returns(d9, report)
    added = d9.join(pre, on="PERMNO", how="left").select(
        "PERMNO", "PERMCO", "Ticker", "HdrCUSIP",
        (pl.col("delistingdt").dt.year() * 100 + pl.col("delistingdt").dt.month())
        .cast(pl.Int32).alias("YYYYMM"),
        pl.col("delistingdt").alias("MthCalDt"),
        "ret_pre_delist", "window_days", "window_days_with_ret", "pre_delist_break",
    )
    report["delisting_months_added"] = added.height
    report["d9_pre_delisting_breaks"] = added["pre_delist_break"].fill_null(False).sum()
    report["d9_pre_delisting_return_known"] = added["ret_pre_delist"].is_not_null().sum()
    panel = pl.concat(
        [panel.with_columns(delist_row_added=pl.lit(False)),
         added.with_columns(delist_row_added=pl.lit(True))],
        how="diagonal_relaxed",
    )
    return panel.sort("PERMNO", "YYYYMM")


def add_market_equity(panel: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Market equity in USD millions, company market equity, lagged market equity.
    Steps:
        1) JKP gen_crsp_sf: shrout = ShrOut / 1000 (millions).
        2) me = MthCap / 1000 (CRSP market cap, USD millions). JKP uses prc * shrout;
           we keep CRSP's value because it uses the shares at the price date (see check).
        3) Tidy Finance: me = 0 -> null.
        4) JKP prepare_crsp_sf: me_company = sum of me over permco and month.
           me_company_complete = all share classes of the month have me.
        5) Tidy Finance: me_lag1 = me of the previous calendar month (null if a gap).
    Output:
        Panel with shrout, me, me_company, me_company_complete, me_lag1.
    """
    panel = panel.with_columns(
        shrout=pl.col("ShrOut") / 1000,
        merge_aux=gen_mmyy("MthCalDt"),
        me=pl.col("MthCap") / 1000,
    )
    panel = panel.with_columns(me=pl.when(pl.col("me") == 0).then(None).otherwise(pl.col("me")))

    # Compare with the JKP formula prc * shares (both in USD thousands here).
    # A gap is fine only if it is rounding, or if the last price is older than the
    # current share count (CRSP then uses the shares at the price date).
    native = panel.filter(~pl.col("delist_row_added"))
    gap = (pl.col("MthPrc") * pl.col("ShrOut") - pl.col("MthCap")).abs()
    # Rounding limit: MthCap has 2 decimals, MthPrc has 6 (half a unit x shares).
    rounding = gap <= 0.0051 + pl.col("ShrOut") * 0.0000005
    stale_price = pl.col("MthPrcDt") < pl.col("ShrStartDt")
    diff = native.filter(pl.col("MthCap").is_not_null()).select(
        (~rounding).sum().alias("gap_rows"),
        (~rounding & stale_price).sum().alias("gap_stale_price"),
        (~rounding & ~stale_price).sum().alias("gap_unexplained"),
    ).row(0, named=True)
    diff["null_mismatch"] = native.select(
        ((pl.col("MthPrc") * pl.col("ShrOut")).is_null() != pl.col("MthCap").is_null()).sum()
    ).item()
    report["me_vs_prc_times_shrout"] = diff
    check(diff["gap_unexplained"] == 0, f"MthCap differs from prc * shrout: {diff}")
    check(diff["null_mismatch"] == 0, f"MthCap and prc * shrout missing on different rows: {diff}")

    # JKP: null when no permno of the company has me in that month.
    # The sum is dated at the month end (eom): rows of one month can have other dates.
    grp = ["PERMCO", "merge_aux"]
    panel = panel.with_columns(
        me_company=pl.when(pl.col("me").count().over(grp) != 0)
        .then(pl.col("me").fill_null(0.0).sum().over(grp))
        .otherwise(None),
        me_company_complete=pl.col("me").count().over(grp) == pl.len().over(grp),
    )
    report["company_months_partial_me"] = (
        panel.filter(pl.col("me_company").is_not_null() & ~pl.col("me_company_complete"))
        .select(grp).unique().height
    )

    # Tidy Finance: shift the month by one and join back.
    lag = panel.select(
        "PERMNO", (pl.col("merge_aux") + 1).alias("merge_aux"), pl.col("me").alias("me_lag1")
    )
    panel = panel.join(lag, on=["PERMNO", "merge_aux"], how="left")
    report["me_lag1_non_null"] = panel["me_lag1"].is_not_null().sum()
    return panel


def adjust_delisting(panel: pl.DataFrame, dl: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Delisting returns, from JKP prepare_crsp_sf (monthly branch).
    Steps:
        1) Join the delisting file on (permno, delisting month).
        2) JKP: impute delret = -0.30 for bad delistings with no delret.
        3) JKP: compound ret with delret, unless MthDelFlg is A/P/V (already in MthRet).
           The base return is MthRet, or ret_pre_delist on added D9 rows.
        4) Not JKP: no "ret = 0" fill. If the base or delret is unknown, ret is
           missing and ret_status says why.
    Output:
        Panel with ret (total holding return), ret_crsp (raw MthRet), ret_status.
    """
    panel = panel.join(dl, on=["PERMNO", "merge_aux"], how="left")
    has_record = pl.col("delistingdt").is_not_null()
    matched = panel.select(has_record.sum()).item()
    report["delist_records"] = dl.height
    report["delist_records_matched_to_a_month"] = matched
    check(dl.height - matched == report["delistings_stock_not_in_file"],
          "Some delistings of stocks in the file did not find their month")
    # A delisting record must never land on a flag-N month (it would double count).
    on_n = panel.filter((pl.col("MthDelFlg") == "N") & has_record).height
    report["delist_record_on_flag_N_month"] = on_n
    check(on_n == 0, f"{on_n} delisting records on a flag-N month")

    # Reverse check: delisting flags without a delisting record.
    flagged = pl.col("MthDelFlg").is_in(["A", "P", "M", "G", "V"])
    orphans = panel.filter(flagged & ~has_record)
    first_record = report["delist_file_first_date"]
    late = orphans.filter(pl.col("MthCalDt") >= first_record).height
    report["delist_flag_without_record"] = {
        "rows": orphans.height,
        "by_flag": dict(orphans["MthDelFlg"].value_counts().iter_rows()),
        "last_date": orphans["MthCalDt"].max(),
        "after_delist_file_start": late,
    }
    check(late == 0, f"{late} delisting flags without record after the delisting file starts")

    c1 = pl.col("delret").is_null()
    # CIZ replacement for legacy "dlstcd == 500".
    c2 = (
        (pl.col("delreasontype") == "UNAV")
        & (pl.col("delactiontype") == "GDR")
        & (pl.col("delpaymenttype") == "PRCF")
        & (pl.col("delstatustype") == "VCL")
    )
    # CIZ replacement for legacy "dlstcd between 520 and 584".
    c3 = (
        (pl.col("delactiontype") == "GDR")
        & (pl.col("delpaymenttype") == "PRCF")
        & (pl.col("delstatustype") == "VCL")
        & pl.col("delreasontype").is_in(BAD_DELIST_REASONS)
    )
    c4 = c1 & (c2 | c3)
    # Compound unless MthDelFlg says the delisting return is already in MthRet.
    # Null flag = added D9 row (checked: native rows have no null flag).
    needs_compound = ~pl.col("MthDelFlg").is_in(INCLUDED_FLAGS).fill_null(False)
    # Delisting months that need a terminal return: M/G flags and D9 rows.
    delist_month = pl.col("MthDelFlg").is_in(["M", "G"]).fill_null(False) | pl.col("delist_row_added")

    panel = panel.with_columns(
        ret_crsp=pl.col("MthRet"),
        delret_raw=pl.col("delret"),
        delret_imputed=(needs_compound & c4).fill_null(False),
        # Base return: MthRet, or the daily-based return on D9 rows.
        ret_base=pl.when(pl.col("delist_row_added")).then(pl.col("ret_pre_delist"))
        .otherwise(pl.col("MthRet")),
    )
    panel = panel.with_columns(
        delret=pl.when(pl.col("delret_imputed")).then(pl.lit(-0.3)).otherwise(pl.col("delret"))
    )
    known_base = pl.col("ret_base").is_not_null()
    known_del = pl.col("delret").is_not_null()
    panel = panel.with_columns(
        ret=pl.when(~delist_month).then(pl.col("ret_base"))
        .when(known_base & known_del)
        .then((pl.col("ret_base") + 1) * (pl.col("delret") + 1) - 1)
        .otherwise(None),
        # Flag V: CRSP says a part of the delisting distributions is unknown. The
        # return is kept as delivered (JKP), but its status says it is partial.
        ret_status=pl.when(~delist_month & known_base & (pl.col("MthDelFlg") == "V").fill_null(False))
        .then(pl.lit("crsp_partial_delisting"))
        .when(~delist_month & known_base).then(pl.lit("crsp"))
        .when(~delist_month).then(pl.lit("missing_crsp"))
        .when(~known_base).then(pl.lit("missing_pre_delisting"))
        .when(~known_del & has_record).then(pl.lit("missing_delret"))
        .when(~known_del).then(pl.lit("missing_delist_record"))
        .when(pl.col("delist_row_added") & pl.col("delret_imputed"))
        .then(pl.lit("daily_plus_delret_imputed"))
        .when(pl.col("delist_row_added")).then(pl.lit("daily_plus_delret"))
        .when(pl.col("delret_imputed")).then(pl.lit("crsp_plus_delret_imputed"))
        .otherwise(pl.lit("crsp_plus_delret")),
    )
    check(panel.filter(needs_compound.not_() & delist_month).height == 0,
          "A/P/V month marked as needing a terminal return")

    # Status priority when several parts are missing: pre-delisting part first.
    # Report the overlap so both reasons stay visible.
    report["missing_pre_delisting_and_no_record"] = panel.filter(
        delist_month & pl.col("ret_base").is_null() & ~has_record
    ).height
    report["delret_imputed_minus_30pct"] = panel["delret_imputed"].sum()
    report["ret_status_counts"] = dict(panel["ret_status"].value_counts().iter_rows())
    report["delisting_crosstab"] = (
        panel.filter(delist_month | flagged | has_record)
        .group_by(
            pl.col("MthDelFlg").fill_null("D9").alias("del_flag"),
            has_record.alias("has_record"),
            "delret_imputed",
            "ret_status",
        )
        .len()
        .sort("del_flag", "ret_status")
        .to_dicts()
    )
    return panel


def d9_reconciliation(panel: pl.DataFrame, report: dict) -> pl.DataFrame:
    # One row per added delisting month: parts of the return and the reason if missing.
    rec = panel.filter("delist_row_added").select(
        pl.col("PERMNO").alias("permno"),
        pl.col("YYYYMM").alias("yyyymm"),
        pl.col("delistingdt"),
        pl.lit("daily_n_rows").alias("pre_delist_source"),
        "window_days", "window_days_with_ret", "pre_delist_break", "ret_pre_delist",
        "delret_raw", "delret_imputed", pl.col("delret").alias("delret_used"),
        "ret", "ret_status",
    ).sort("permno")
    # The audit's reference cases must match.
    for permno, expected in REFERENCE_D9.items():
        got = rec.filter(pl.col("permno") == permno)["ret"].item()
        report.setdefault("d9_reference_cases", {})[str(permno)] = {"expected": expected, "got": got}
        check(got is not None and abs(got - expected) < 5e-4,
              f"D9 reference case {permno}: expected {expected}, got {got}")
    return rec


def build_distributions(lf: pl.LazyFrame, dis_cols: list[str], report: dict) -> pl.DataFrame:
    # One row per distribution event; key = permno, ex-date, sequence number.
    dis = (
        lf.select(KEY + dis_cols)
        .filter(pl.any_horizontal(pl.col(dis_cols).is_not_null()))
        .unique()
        .collect()
        # JKP practice: unique() does not keep the row order, so sort right after it.
        .sort("PERMNO", "DisExDt", "DisSeqNbr")
    )
    check(dis["DisExDt"].null_count() == 0, "Distribution rows with no ex-date")
    n_events = dis.select("PERMNO", "DisExDt", "DisSeqNbr").unique().height
    check(n_events == dis.height, f"{dis.height - n_events} events have conflicting details")
    dis = dis.with_columns(
        [pl.col(c).cast(pl.Int64, strict=True) for c in ["PERMNO", "DisSeqNbr", "DisPERMNO", "DisPERMCO"]]
        + [pl.col(c).cast(pl.Float64, strict=True) for c in ["DisDivAmt", "DisFacPr", "DisFacShr"]]
        + [pl.col(c).str.to_date("%Y-%m-%d", strict=True)
           for c in ["DisExDt", "DisDeclareDt", "DisRecordDt", "DisPayDt"]]
        + [pl.col("YYYYMM").cast(pl.Int32, strict=True)]
    ).sort("PERMNO", "DisExDt", "DisSeqNbr")
    # Lower-case names, as in the panel.
    dis = dis.rename({c: c.lower() for c in dis.columns})
    report["distribution_events"] = dis.height
    return dis


def final_columns(panel: pl.DataFrame) -> pl.DataFrame:
    # JKP-style names; raw CRSP flags kept for later checks.
    return panel.select(
        pl.col("PERMNO").alias("permno"),
        pl.col("PERMCO").alias("permco"),
        pl.col("YYYYMM").alias("yyyymm"),
        pl.col("MthCalDt").alias("date"),
        pl.col("MthCalDt").dt.month_end().alias("eom"),
        "ret", "ret_status", "ret_crsp", "ret_pre_delist",
        pl.col("MthRetx").alias("retx"),
        pl.col("MthRetFlg").alias("ret_flag"),
        pl.col("MthDelFlg").alias("del_flag"),
        pl.col("MthPrc").alias("prc"),
        pl.col("MthPrcFlg").alias("prc_flag"),
        # JKP gen_crsp_sf: BA -> 1, TR -> 0, else null.
        pl.when(pl.col("MthPrcFlg") == "BA").then(1)
        .when(pl.col("MthPrcFlg") == "TR").then(0)
        .otherwise(None).cast(pl.Int8).alias("bidask"),
        pl.col("MthPrcDt").alias("prc_date"),
        "shrout", "me", "me_company", "me_company_complete", "me_lag1",
        pl.col("MthVol").alias("vol"),
        pl.col("MthCompFlg").alias("comp_flag"),
        pl.col("MthDisCnt").alias("dis_cnt"),
        "delistingdt", "delret", "delret_raw", "delret_imputed", "delretmisstype",
        "delactiontype", "delstatustype", "delreasontype", "delpaymenttype",
        "delamtdt", "delnextdt", "delist_row_added",
        pl.col("Ticker").alias("ticker"),
        # Header CUSIP: today's code, not the historical one (use step 3 for that).
        pl.col("HdrCUSIP").alias("hdr_cusip"),
    ).sort("permno", "date")


def final_checks(out: pl.DataFrame, report: dict) -> None:
    check(out.select("permno", "yyyymm").is_duplicated().sum() == 0, "Duplicate permno-month")
    low = out.filter(pl.col("ret") < -1).height
    check(low == 0, f"{low} returns below -100%")
    check(out.filter(pl.col("ret").is_not_null() & ~pl.col("ret").is_finite()).height == 0,
          "Non-finite returns")
    # N/A/P/V months must keep the raw CRSP return exactly.
    changed = out.filter(
        pl.col("del_flag").is_in(["N", *INCLUDED_FLAGS]) & ~pl.col("ret").eq_missing(pl.col("ret_crsp"))
    ).height
    check(changed == 0, f"{changed} N/A/P/V months have a return different from MthRet")
    check(out.filter(pl.col("del_flag").is_null() & ~pl.col("delist_row_added")).height == 0,
          "Null delisting flag outside added D9 rows")

    report["ret_missing"] = out["ret"].null_count()
    report["months"] = {"first": out["yyyymm"].min(), "last": out["yyyymm"].max()}
    report["stocks"] = out["permno"].n_unique()
    report["stocks_per_decade_end"] = dict(
        out.filter(pl.col("yyyymm") % 1000 == 912)
        .group_by("yyyymm").len().sort("yyyymm").iter_rows()
    )
    # Flag extreme values; nothing is deleted.
    report["ret_above_300pct"] = out.filter(pl.col("ret") > 3).height
    report["largest_returns"] = (
        out.sort("ret", descending=True, nulls_last=True).head(10)
        .select("permno", "yyyymm", "ret", "prc", "ret_flag", "del_flag").to_dicts()
    )

    # Sanity check: our value-weighted return of all securities vs the CRSP index.
    idx = pl.read_csv(INDEX, infer_schema=False).select(
        pl.col("mthcaldt").str.to_date("%Y-%m-%d").dt.month_end().alias("eom"),
        pl.col("vwretd").cast(pl.Float64),
    )
    vw = (
        out.filter(pl.col("ret").is_not_null() & pl.col("me_lag1").is_not_null())
        .group_by("eom")
        .agg(((pl.col("ret") * pl.col("me_lag1")).sum() / pl.col("me_lag1").sum()).alias("vw"))
        .join(idx, on="eom", how="inner")
    )
    corr = vw.select(pl.corr("vw", "vwretd")).item()
    report["vw_vs_crsp_index"] = {
        "months": vw.height,
        "corr": corr,
        "mean_diff": (vw["vw"] - vw["vwretd"]).mean(),
        "max_abs_diff": (vw["vw"] - vw["vwretd"]).abs().max(),
    }
    check(corr > 0.99, f"Value-weighted return far from the CRSP index: corr = {corr}")


def main() -> None:
    stamps = file_stamps([SRC, DAILY, DELIST, INDEX])
    report: dict = {
        "script": "scripts/data_cleaning/1_crsp_monthly.py",
        "inputs": {p.name: sha256(p) for p in [SRC, DAILY, DELIST, INDEX]},
    }
    dis_cols = read_header()
    # All columns read as text; types are cast later with strict checks.
    lf = pl.scan_csv(SRC, infer_schema=False).with_row_index("row")

    dl = read_delistings(report)
    panel = build_panel(lf, report)
    panel = add_delisting_months(panel, dl, report)
    panel = add_market_equity(panel, report)
    panel = adjust_delisting(panel, dl, report)
    rec = d9_reconciliation(panel, report)
    out = final_columns(panel)
    final_checks(out, report)
    dis = build_distributions(lf, dis_cols, report)

    # The raw files were hashed first and read after: they must not have changed.
    check_unchanged(stamps)
    publish(
        {
            PROCESSED / "crsp_monthly.parquet": out,
            PROCESSED / "crsp_distributions.parquet": dis,
            PROCESSED / "crsp_d9_reconciliation.csv": rec,
        },
        report,
        PROCESSED / "crsp_monthly_report.json",
    )
    print(f"crsp_monthly: {out.height:,} rows, {report['stocks']:,} stocks; "
          f"distributions: {dis.height:,} events. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
