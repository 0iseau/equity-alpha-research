"""
Step 3 of CleaningSpec.md: security information and eligible universe.

Reference code (Resources/reference_code/):
- JKP jkp-data, aux_functions.py:
    gen_crsp_sf         -> join security info on [secinfostartdt, secinfoenddt];
                           common = EQTY & COM & NS & issuertype in (ACOR, CORP);
                           exch_main and crsp_nyse flags
    prepare_crsp_sf     -> NASDAQ volume adjustment, dolvol = |prc| * vol
    adj_trd_vol_NASDAQ  -> copied as is
    crsp_industry       -> sic = 0 -> null
    _parse_siccodes_file, ff_ind_class -> FF49 industries (resources/Siccodes49.txt)
- Tidy Finance, chapters/wrds-crsp-and-compustat.qmd: same share filters, plus
  usincflg = 'Y' and tradingstatusflg = 'A'; siccd from the security history.

Deviations (see CleaningSpec.md):
- Our export has no conditionaltype. JKP and TF use it for regular-way trading.
  We use tradingstatusflg = 'A' with primaryexch in (N, A, Q) instead (D2).
- Eligibility is set at the formation date t (end of month t). The return of
  month t+1 is always kept (ret_lead1), whatever the stock's status in t+1.
  JKP and TF filter in the same month, which would drop delisting months.
- No ×100 on dolvol: our volume is already in shares (see step 1).

Outputs (data/processed/):
- crsp_universe.parquet        crsp_monthly + security info + flags + ret_lead1
- crsp_universe_report.json    checks, counts and output hash (written last)
"""

from __future__ import annotations

import re

import polars as pl

from utils import (PROCESSED, PROJECT, RAW, CheckError, adj_trd_vol_nasdaq, check, publish,
                   read_verified, sha256)

SEC = RAW / "crsp_ciz_security_history.csv"
INDEX = RAW / "crsp_ciz_monthly_market_indexes.csv"
SICCODES = PROJECT / "resources" / "Siccodes49.txt"
PANEL = PROCESSED / "crsp_monthly.parquet"
PANEL_REPORT = PROCESSED / "crsp_monthly_report.json"
SAMPLE_START = 196301  # first month of the analysis sample (for summary counts only)


def read_security_history(report: dict) -> pl.DataFrame:
    # Security history, typed. Intervals must not overlap within a permno.
    sec = pl.read_csv(SEC, infer_schema=False).select(
        pl.col("permno").cast(pl.Int64, strict=True),
        pl.col("secinfostartdt").str.to_date("%Y-%m-%d", strict=True),
        pl.col("secinfoenddt").str.to_date("%Y-%m-%d", strict=True),
        "sharetype", "securitytype", "securitysubtype", "issuertype", "usincflg",
        "primaryexch", "tradingstatusflg", "shareclass", "cusip",
        pl.col("siccd").cast(pl.Int64, strict=True),
        pl.col("naics").cast(pl.Int64, strict=True),
    )
    for c in ["permno", "secinfostartdt", "secinfoenddt", "sharetype", "securitytype",
              "securitysubtype", "issuertype", "usincflg", "primaryexch", "tradingstatusflg"]:
        check(sec[c].null_count() == 0, f"Null values in security history column {c}")
    check(sec.filter(pl.col("secinfoenddt") < pl.col("secinfostartdt")).height == 0,
          "Security info interval ends before it starts")
    sec = sec.sort("permno", "secinfostartdt")
    overlap = sec.filter(
        pl.col("secinfostartdt") <= pl.col("secinfoenddt").shift(1).over("permno")
    ).height
    check(overlap == 0, f"{overlap} overlapping security info intervals")
    report["security_history_rows"] = sec.height
    # JKP crsp_industry: sic = 0 means unknown.
    return sec.with_columns(
        siccd=pl.when(pl.col("siccd") == 0).then(None).otherwise(pl.col("siccd"))
    )


def parse_siccodes(path) -> pl.DataFrame:
    """JKP _parse_siccodes_file, copied: SIC -> FF49 mapping from the Ken French file."""
    header_re = re.compile(r"^\s*(\d+)\s+\S+.*$")
    range_re = re.compile(r"^\s*(\d{4})-(\d{4})(?:\b.*)?$")
    result: dict[int, list[int]] = {}
    current_category: int | None = None
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip()
            header_match = header_re.match(line)
            if header_match:
                current_category = int(header_match.group(1))
                result[current_category] = []
                continue
            range_match = range_re.match(line)
            if range_match and current_category is not None:
                start, end = int(range_match.group(1)), int(range_match.group(2))
                result[current_category].extend(range(start, end + 1))
    rows = [{"ff49": ff, "sic": sics} for ff, sics in result.items()]
    mapping = (
        pl.DataFrame(rows, schema={"sic": pl.List(pl.Int64), "ff49": pl.Int32}, orient="row")
        .sort("ff49").explode("sic").drop_nulls()
    )
    # One industry per SIC code.
    check(mapping["sic"].is_unique().all(), "A SIC code maps to two FF49 industries")
    return mapping


def join_security_info(panel: pl.DataFrame, sec: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Attach the security info valid on each row's date (JKP gen_crsp_sf, TF).
    Steps:
        1) As-of join: last interval that starts on or before the date.
        2) Keep it only if the date is also on or before the interval end.
    Output:
        Panel with security fields (null if no valid interval).
    """
    info_cols = [c for c in sec.columns if c not in ("permno",)]
    joined = panel.sort("permno", "date").join_asof(
        sec, left_on="date", right_on="secinfostartdt", by="permno", strategy="backward",
        check_sortedness=False,  # both sides are sorted by permno, then date
    )
    inside = pl.col("secinfoenddt") >= pl.col("date")
    joined = joined.with_columns(
        [pl.when(inside).then(pl.col(c)).otherwise(None).alias(c) for c in info_cols]
    )
    # Exchange of the last ACTIVE interval that started on or before the date.
    # Used only for the volume adjustment of delisting months (the volume was
    # traded while listed), never for eligibility.
    active = sec.filter(pl.col("tradingstatusflg") == "A").select(
        "permno", pl.col("secinfostartdt").alias("start_active"),
        pl.col("primaryexch").alias("primaryexch_last_active"),
    )
    joined = joined.join_asof(
        active, left_on="date", right_on="start_active", by="permno", strategy="backward",
        check_sortedness=False,
    ).drop("start_active")
    check(joined.height == panel.height, "Security info join changed the row count")
    no_info = joined.filter(pl.col("secinfostartdt").is_null())
    report["rows_without_security_info"] = {
        "all": no_info.height,
        "by_del_flag": dict(no_info["del_flag"].fill_null("D9").value_counts().iter_rows()),
    }
    # Expected only in delisting months: the security history ends at the
    # delisting date, before the month-end date of the monthly row.
    bad = no_info.filter(pl.col("del_flag") == "N").height
    check(bad == 0, f"{bad} non-delisting rows have no security info")
    return joined


def add_flags(df: pl.DataFrame, mapping: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Universe flags at each date, volume adjustment, dollar volume, industry.
    Steps:
        1) JKP common: EQTY & COM & NS & issuertype in (ACOR, CORP).
        2) exch_main: primaryexch in (N, A, Q) and tradingstatusflg = 'A'
           (substitute for JKP's conditionaltype = 'RW', absent from our export).
        3) us_inc: usincflg = 'Y' (TF).
        4) eligible = common & exch_main & us_inc & me known at the date
           & no delisting during the month (MthDelFlg = 'N').
        5) crsp_nyse: eligible and primaryexch = 'N' (for NYSE breakpoints, step 4).
        6) JKP: NASDAQ volume adjustment, dolvol = |prc| * vol (USD).
        7) JKP: FF49 industry from siccd.
    Output:
        Panel with flags, vol_adj, dolvol, sic, ff49.
    """
    common = (
        (pl.col("securitytype") == "EQTY")
        & (pl.col("securitysubtype") == "COM")
        & (pl.col("sharetype") == "NS")
        & pl.col("issuertype").is_in(["ACOR", "CORP"])
    )
    exch_main = pl.col("primaryexch").is_in(["N", "A", "Q"]) & (pl.col("tradingstatusflg") == "A")
    us_inc = pl.col("usincflg") == "Y"
    df = df.with_columns(
        common=common.fill_null(False),
        exch_main=exch_main.fill_null(False),
        us_inc=us_inc.fill_null(False),
    ).with_columns(
        # A stock that delists during month t cannot be bought at the end of t.
        eligible=pl.col("common") & pl.col("exch_main") & pl.col("us_inc")
        & pl.col("me").is_not_null() & (pl.col("del_flag") == "N").fill_null(False)
    ).with_columns(
        crsp_nyse=pl.col("eligible") & (pl.col("primaryexch") == "N"),
    )

    # NASDAQ volume: exchange at the date if active there; otherwise (delisting
    # month) the last active interval, where the volume was traded.
    active_now = (pl.col("tradingstatusflg") == "A").fill_null(False)
    vol_exch = pl.when(active_now).then(pl.col("primaryexch")).otherwise(
        pl.col("primaryexch_last_active"))
    nasdaq_vol = (vol_exch == "Q").fill_null(False)
    df = df.with_columns(vol_adj=pl.col("vol")).with_columns(
        adj_trd_vol_nasdaq("date", "vol_adj", nasdaq_vol)
    ).with_columns(dolvol=pl.col("prc").abs() * pl.col("vol_adj"))
    report["nasdaq_vol_adjusted_from_last_active_interval"] = df.filter(
        ~active_now & nasdaq_vol & (pl.col("vol_adj") != pl.col("vol"))
    ).height
    # Audit reference case: PERMNO 10003, Dec 1995, delisted on Dec 15 (NASDAQ).
    ref = df.filter((pl.col("permno") == 10003) & (pl.col("yyyymm") == 199512))
    report["vol_reference_10003_199512"] = ref.select("vol", "vol_adj", "dolvol").to_dicts()
    check(ref.height == 1 and abs(ref["vol_adj"].item() - 73190.5) < 0.01,
          "Reference case 10003 (Dec 1995): NASDAQ volume not adjusted")

    # Execution flags for the backtest (eligible is the universe filter only):
    # last price older than the date, or no volume in the month.
    df = df.with_columns(
        prc_age_days=(pl.col("date") - pl.col("prc_date")).dt.total_days(),
        zero_volume=(pl.col("vol") == 0),
    )

    df = df.rename({"siccd": "sic"}).join(mapping, on="sic", how="left")

    # How many rows each filter removes (sample months, native rows).
    s = df.filter((pl.col("yyyymm") >= SAMPLE_START) & ~pl.col("delist_row_added"))
    report["filter_counts_from_1963"] = {
        "rows": s.height,
        "common": s["common"].sum(),
        "common_exch_main": (s["common"] & s["exch_main"]).sum(),
        "common_exch_main_us_inc": (s["common"] & s["exch_main"] & s["us_inc"]).sum(),
        "eligible": s["eligible"].sum(),
    }
    e = df.filter("eligible")
    report["eligible_rows"] = e.height
    report["eligible_sic_missing"] = e["sic"].null_count()
    report["eligible_ff49_missing"] = e["ff49"].null_count()
    report["eligible_cusip_missing"] = e["cusip"].null_count()
    return df


def add_next_month_return(df: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Return of month t+1 for a position formed at the end of month t.
    Steps:
        1) Month index from eom; the next row of the stock must be month t+1.
        2) ret_lead1 = that row's ret; ret_lead1_status = its ret_status.
           The status of the stock in t+1 is not used: a stock that delists in
           t+1 keeps its delisting return.
    Output:
        Panel with ret_lead1, ret_lead1_status.
    """
    m = (pl.col("eom").dt.year() * 12 + pl.col("eom").dt.month()).cast(pl.Int32)
    df = df.with_columns(m=m).sort("permno", "m")
    nxt = df.select(
        "permno", (pl.col("m") - 1).alias("m"),
        pl.col("ret").alias("ret_lead1"), pl.col("ret_status").alias("ret_lead1_status"),
        pl.col("eligible").alias("eligible_lead1"),
        # t+1 is a delisting month: delisting flag, or an added D9 row.
        ((pl.col("del_flag") != "N").fill_null(False) | pl.col("delist_row_added"))
        .alias("delisting_lead1"),
    )
    df = df.join(nxt, on=["permno", "m"], how="left").with_columns(
        ret_lead1_status=pl.col("ret_lead1_status").fill_null("no_next_row")
    ).drop("m")

    e = df.filter("eligible")
    # Unknown t+1 return: share of eligible market cap per formation month.
    unk = (
        e.filter(pl.col("ret_lead1_status") != "no_next_row")
        .group_by("eom")
        .agg((pl.col("me").filter(pl.col("ret_lead1").is_null()).sum() / pl.col("me").sum())
             .alias("w"))
    )
    report["eligible_me_share_with_unknown_lead1"] = {
        "months_with_any": unk.filter(pl.col("w") > 0).height,
        "mean": unk["w"].mean(), "max": unk["w"].max(),
    }
    report["eligible_lead1_status"] = dict(e["ret_lead1_status"].value_counts().iter_rows())
    # No next row: expected only in the last month of the data.
    last_month = df["yyyymm"].max()
    early_end = e.filter((pl.col("ret_lead1_status") == "no_next_row")
                         & (pl.col("yyyymm") != last_month))
    report["eligible_no_next_row_before_last_month"] = early_end.select(
        "permno", "yyyymm", "del_flag", "ret_flag").to_dicts()
    # Months kept thanks to the formation-date rule (not eligible in t+1).
    kept = e.filter(
        pl.col("ret_lead1_status").ne("no_next_row") & ~pl.col("eligible_lead1").fill_null(False)
    )
    dl = e.filter(pl.col("delisting_lead1").fill_null(False))
    report["eligible_t_next_row_not_eligible"] = {
        "rows": kept.height, "with_numeric_return": kept["ret_lead1"].is_not_null().sum(),
    }
    report["eligible_t_next_is_delisting_month"] = {
        "rows": dl.height, "with_numeric_return": dl["ret_lead1"].is_not_null().sum(),
    }
    return df.drop("eligible_lead1", "delisting_lead1")


def checks(df: pl.DataFrame, report: dict) -> None:
    check(df.select("permno", "yyyymm").is_duplicated().sum() == 0, "Duplicate permno-month")
    # An eligible row must have its security info and a positive me.
    e = df.filter("eligible")
    check(e["secinfostartdt"].null_count() == 0, "Eligible row without security info")
    check(e.filter(pl.col("me") <= 0).height == 0, "Eligible row with non-positive me")
    check(e.filter(pl.col("crsp_nyse") & (pl.col("primaryexch") != "N")).height == 0,
          "crsp_nyse flag on a non-NYSE row")

    # Eligible stocks per month vs the CRSP index count, from 1963.
    idx = pl.read_csv(INDEX, infer_schema=False).select(
        pl.col("mthcaldt").str.to_date("%Y-%m-%d").dt.month_end().alias("eom"),
        pl.col("vwretd").cast(pl.Float64),
        pl.col("vwtotcnt").cast(pl.Int64),
    )
    n = e.group_by("eom").agg(pl.len().alias("n_eligible"),
                              pl.col("crsp_nyse").sum().alias("n_nyse"))
    nm = n.join(idx, on="eom").filter(pl.col("eom").dt.year() >= 1963).sort("eom")
    report["eligible_per_month_from_1963"] = {
        "min": nm["n_eligible"].min(), "max": nm["n_eligible"].max(),
        "mean": nm["n_eligible"].mean(),
        "nyse_min": nm["n_nyse"].min(),
        "share_of_crsp_index_count_mean": (nm["n_eligible"] / nm["vwtotcnt"]).mean(),
    }
    check(nm.height >= 750, "Fewer than 750 sample months with eligible stocks")
    check(nm["n_nyse"].min() > 0, "A sample month with no NYSE stock")

    # Value-weighted return of month t+1 over eligible stocks at t vs the CRSP index.
    vw = (
        e.filter(pl.col("ret_lead1").is_not_null())
        .group_by("eom")
        .agg(((pl.col("ret_lead1") * pl.col("me")).sum() / pl.col("me").sum()).alias("vw"))
        .with_columns(eom=pl.col("eom").dt.offset_by("1mo").dt.month_end())
        .join(idx, on="eom")
        .filter(pl.col("eom").dt.year() >= 1963)
    )
    corr = vw.select(pl.corr("vw", "vwretd")).item()
    report["eligible_vw_vs_crsp_index_from_1963"] = {
        "months": vw.height, "corr": corr,
        "mean_diff": (vw["vw"] - vw["vwretd"]).mean(),
        "max_abs_diff": (vw["vw"] - vw["vwretd"]).abs().max(),
    }
    check(corr > 0.99, f"Eligible VW return far from the CRSP index: corr = {corr}")


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/3_crsp_universe.py"}
    panel, run_id = read_verified(PANEL, PANEL_REPORT)
    report["inputs"] = {
        PANEL.name: {"from_run": run_id},
        SEC.name: sha256(SEC), INDEX.name: sha256(INDEX), SICCODES.name: sha256(SICCODES),
    }
    sec = read_security_history(report)
    mapping = parse_siccodes(SICCODES)

    df = join_security_info(panel, sec, report)
    df = add_flags(df, mapping, report)
    df = add_next_month_return(df, report)
    checks(df, report)

    # Historical CUSIP from the security history; header CUSIP kept apart.
    df = df.drop("secinfoenddt").sort("permno", "date")
    publish({PROCESSED / "crsp_universe.parquet": df}, report,
            PROCESSED / "crsp_universe_report.json")
    print(f"crsp_universe: {df.height:,} rows, {report['eligible_rows']:,} eligible stock-months. "
          "Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
