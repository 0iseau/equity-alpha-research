"""Step 8 of CleaningSpec.md: which annual report is usable for each stock-month.

Reference code (Resources/reference_code/):
- JKP aux_functions.py, add_earnings_persistence_and_expand and expand:
    start_date = month_end(datadate + lag months)
    end_date   = min(month_end(next report's start_date - 1 month),
                     month_end(datadate + max_lag months))
    then one row per month from start_date to end_date (public_date). Copied.
- JKP merge: join on (gvkey, eom = public_date).

Deviations (see CleaningSpec.md, decision D4):
- lag = 6 months (course rule), not JKP's 4; max_lag = 18 months like JKP.
- The "next report" is the firm's next report in any currency, read from the raw
  file: a newer report replaces the old one even when we cannot use its values
  (non-USD rows are not in compustat_annual). Then nothing is available.
- Only keys are written here (gvkey, acc_datadate): accounting values stay in
  compustat_annual.parquet and are joined on (gvkey, datadate) at the signal step.

Outputs (data/processed/):
- acc_public.parquet               gvkey, public_date, datadate (one usable report per firm-month)
- crsp_panel_acc.parquet           crsp_panel_exc + gvkey, acc_datadate, acc_age_months
- accounting_availability_report.json   checks, counts and output hashes (written last)
"""

from __future__ import annotations

import io
import json

import polars as pl

from utils import PROCESSED, RAW, CheckError, check, publish, read_raw_sized, read_verified

PANEL = PROCESSED / "crsp_panel_exc.parquet"
PANEL_REPORT = PROCESSED / "crsp_excess_report.json"
CCM = PROCESSED / "ccm_links.parquet"
CCM_REPORT = PROCESSED / "ccm_links_report.json"
ACCOUNTS = PROCESSED / "compustat_annual.parquet"
ACCOUNTS_REPORT = PROCESSED / "compustat_annual_report.json"
FUNDA = RAW / "ccm_fundamentals_annual.csv"

LAG_TO_PUBLIC = 6    # months after datadate before a report is usable (course rule, D4)
MAX_DATA_LAG = 18    # months after datadate when a report stops being usable (JKP)
SAMPLE_START = 196301
TRUNCATION_DATES = [pl.date(1975, 6, 30), pl.date(1999, 12, 31), pl.date(2015, 3, 31)]


def months_between(later: pl.Expr, earlier: pl.Expr) -> pl.Expr:
    # Whole calendar months from one date to a later one.
    return ((later.dt.year() - earlier.dt.year()) * 12
            + later.dt.month() - earlier.dt.month()).cast(pl.Int32)


def read_report_calendar(report: dict) -> pl.DataFrame:
    # Every report of every firm, in any currency: (gvkey, datadate, usd).
    # Read from the raw file, because non-USD rows are not in compustat_annual.
    cal = (
        pl.read_csv(io.BytesIO(read_raw_sized(FUNDA, report)),
                    columns=["GVKEY", "datadate", "curcd"], infer_schema=False)
        .select(pl.col("GVKEY").alias("gvkey"),
                pl.col("datadate").str.to_date("%Y-%m-%d", strict=True),
                pl.col("curcd"),
                (pl.col("curcd") == "USD").fill_null(False).alias("usd"))
        .unique()
        # JKP practice: unique() does not keep the row order, so sort right after it.
        .sort("gvkey", "datadate")
    )
    check(cal.select("gvkey", "datadate").is_unique().all(), "Duplicate report in the calendar")
    report["report_calendar"] = {"reports": cal.height, "usd": int(cal["usd"].sum())}
    return cal


def availability_self_test() -> None:
    # Reference cases with dates written by hand (not built from the constants):
    # 6 months after the fiscal year end, replaced by the next report, 18 months at most.
    d = lambda s: pl.Series([s]).str.to_date()[0]
    cal = pl.DataFrame({
        "gvkey": ["A", "A", "A", "B", "C", "C", "D", "D"],
        "datadate": [d("2018-12-31"), d("2019-12-31"), d("2020-12-31"),   # A: yearly reports
                     d("2019-12-31"),                                       # B: no next report
                     d("2019-06-30"), d("2020-06-30"),                      # C: then a CAD report
                     d("2019-12-31"), d("2021-03-31")],                     # D: late next report
        "curcd": ["USD", "USD", "USD", "USD", "USD", "CAD", "USD", "USD"],
    }).with_columns(usd=pl.col("curcd") == "USD")
    got = (build_public(cal).group_by("gvkey", "datadate")
           .agg(pl.col("public_date").min().alias("first"), pl.col("public_date").max().alias("last"),
                pl.len().alias("n")))
    expected = {
        ("A", "2019-12-31"): ("2020-06-30", "2021-05-31", 12),   # formation of June; returns of July
        ("B", "2019-12-31"): ("2020-06-30", "2021-06-30", 13),   # 18 months, bound included
        ("C", "2019-06-30"): ("2019-12-31", "2020-11-30", 12),   # replaced by the CAD report
        ("D", "2019-12-31"): ("2020-06-30", "2021-06-30", 13),   # next report late: stops at 18 months
        ("D", "2021-03-31"): ("2021-09-30", "2022-09-30", 13),
    }
    for (g, dd), (first, last, n) in expected.items():
        row = got.filter((pl.col("gvkey") == g) & (pl.col("datadate") == d(dd)))
        check(row.height == 1 and row["first"][0] == d(first) and row["last"][0] == d(last)
              and row["n"][0] == n, f"Availability self-test failed for {g} {dd}: {row.to_dicts()}")
    # The CAD report of C is never usable, and nothing replaces it.
    check(got.filter((pl.col("gvkey") == "C") & (pl.col("datadate") == d("2020-06-30"))).height == 0,
          "Availability self-test: a non-USD report was expanded")


def add_public_window(cal: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        The months when each report is the firm's usable report (JKP, copied).
    Steps:
        1) start_date = month_end(datadate + LAG_TO_PUBLIC months).
        2) next_start_date = start_date of the firm's next report.
        3) end_date = min(month_end(next_start_date - 1 month),
                          month_end(datadate + MAX_DATA_LAG months)).
    Output:
        Calendar with start_date and end_date.
    """
    return (
        cal.sort(["gvkey", "datadate"])
        .with_columns(start_date=pl.col("datadate").dt.offset_by(f"{LAG_TO_PUBLIC}mo").dt.month_end())
        .sort(["gvkey", "datadate"])
        .with_columns(next_start_date=pl.col("start_date").shift(-1).over(["gvkey"]))
        .with_columns(
            end_date=pl.min_horizontal(
                (pl.col("next_start_date").dt.offset_by("-1mo").dt.month_end()),
                (pl.col("datadate").dt.offset_by(f"{MAX_DATA_LAG}mo").dt.month_end()),
            )
        )
        .drop("next_start_date")
    )


def expand_public(windows: pl.DataFrame) -> pl.DataFrame:
    # JKP expand: one row per month from start_date to end_date (month ends).
    # Only USD reports are expanded: the others have no values we can use.
    out = (
        windows.filter("usd")
        .with_columns(pl.date_ranges(start="start_date", end="end_date", interval="1mo")
                      .alias("public_date"))
        .explode("public_date")
        .drop_nulls("public_date")
        .with_columns(pl.col("public_date").dt.month_end())
        .select("gvkey", "public_date", "datadate")
        .sort(["gvkey", "public_date"])
    )
    # JKP keeps the first row of a duplicate key; here a duplicate is an error.
    check(out.select("gvkey", "public_date").is_unique().all(), "Two usable reports for one firm-month")
    return out


def build_public(cal: pl.DataFrame) -> pl.DataFrame:
    return expand_public(add_public_window(cal))


def attach(panel: pl.DataFrame, ccm: pl.DataFrame, public: pl.DataFrame) -> pl.DataFrame:
    # Left joins: every panel row is kept, with or without a link or a report.
    n = panel.height
    out = (
        panel.join(ccm.select("permno", "eom", "gvkey"), on=["permno", "eom"], how="left")
        .join(public.rename({"public_date": "eom", "datadate": "acc_datadate"}),
              on=["gvkey", "eom"], how="left")
        .with_columns(acc_age_months=months_between(pl.col("eom"), pl.col("acc_datadate")))
    )
    check(out.height == n, "Row count changed in the joins")
    return out


def check_no_look_ahead(df: pl.DataFrame, ccm: pl.DataFrame, windows: pl.DataFrame,
                        report: dict) -> None:
    # 0) The firm key of every row is the one of the input link table (nulls included).
    keys = (df.select("permno", "eom", "gvkey")
            .join(ccm.select("permno", "eom", pl.col("gvkey").alias("gvkey_in")),
                  on=["permno", "eom"], how="left"))
    bad = keys.filter(pl.col("gvkey").ne_missing(pl.col("gvkey_in"))).height
    check(bad == 0 and keys.height == df.height, f"{bad} rows where gvkey differs from ccm_links")
    # The age of the report, on every row: whole months from datadate to eom, null
    # exactly when there is no report (written with month numbers, another route).
    num = lambda c: pl.col(c).dt.year() * 12 + pl.col(c).dt.month()
    bad = df.filter(pl.col("acc_age_months").cast(pl.Int64)
                    .ne_missing((num("eom") - num("acc_datadate")).cast(pl.Int64))).height
    check(bad == 0, f"{bad} rows with a wrong acc_age_months")

    has = df.filter(pl.col("acc_datadate").is_not_null())
    report["rows_with_accounts"] = has.height
    check(has["gvkey"].null_count() == 0, "A report without a link")

    # 1) The automatic test: the report is public on or before the formation date.
    public_on = pl.col("acc_datadate").dt.offset_by(f"{LAG_TO_PUBLIC}mo").dt.month_end()
    late = has.filter(public_on > pl.col("eom")).height
    check(late == 0, f"LOOK-AHEAD: {late} rows use a report before it is public")
    report["acc_age_months"] = {"min": has["acc_age_months"].min(), "max": has["acc_age_months"].max()}
    check(has["acc_age_months"].min() >= LAG_TO_PUBLIC, "A report younger than the lag")
    check(has["acc_age_months"].max() <= MAX_DATA_LAG, "A report older than the maximum age")

    # 2) Second route: for each linked row, take the firm's last report (any
    #    currency) that is public at the formation date. It is the expected report
    #    if it is in USD and not too old; otherwise nothing is expected.
    linked = df.filter(pl.col("gvkey").is_not_null()).select("permno", "eom", "gvkey", "acc_datadate")
    exp = (
        linked.sort("eom")
        .join_asof(windows.select("gvkey", "start_date", "usd", "curcd",
                                  pl.col("datadate").alias("last_dd")).sort("start_date"),
                   left_on="eom", right_on="start_date", by="gvkey", strategy="backward",
                   check_sortedness=False)
        .with_columns(
            expected=pl.when(pl.col("usd")
                             & (months_between(pl.col("eom"), pl.col("last_dd")) <= MAX_DATA_LAG))
            .then(pl.col("last_dd"))
        )
    )
    bad = exp.filter(pl.col("acc_datadate").ne_missing(pl.col("expected"))).height
    report["second_route_check"] = {"linked_rows": linked.height, "differences": bad}
    check(bad == 0, f"{bad} rows where the report differs from the last public report")
    # Linked rows whose newest public report (6 to 18 months old) is not in USD:
    # nothing is usable. Split by the currency of that report.
    blocked = exp.filter(pl.col("last_dd").is_not_null() & ~pl.col("usd")
                         & (months_between(pl.col("eom"), pl.col("last_dd")) <= MAX_DATA_LAG))
    # Among them: rows where the firm's older USD report would still be usable
    # (at most 18 months old) if non-USD reports did not replace it.
    usd_only = build_public(windows.filter("usd").select("gvkey", "datadate", "curcd", "usd"))
    lost = blocked.join(usd_only.rename({"public_date": "eom"}), on=["gvkey", "eom"], how="inner")
    lost_elig = lost.join(df.filter(pl.col("eligible") & (pl.col("yyyymm") >= SAMPLE_START))
                          .select("permno", "eom"), on=["permno", "eom"], how="semi")
    report["linked_rows_whose_last_public_report_is_not_usd"] = {
        "last_report_cad": blocked.filter(pl.col("curcd") == "CAD").height,
        "last_report_currency_unknown": blocked.filter(pl.col("curcd").is_null()).height,
        "older_usd_report_set_aside": lost.height,
        "older_usd_report_set_aside_eligible_from_1963": lost_elig.height,
    }


def check_truncation(cal: pl.DataFrame, public: pl.DataFrame, report: dict) -> None:
    # Truncation test: hide every report that is not public yet at date T and
    # rebuild. What we see up to T must be exactly the same.
    out = {}
    for t in TRUNCATION_DATES:
        known = cal.filter(pl.col("datadate").dt.offset_by(f"{LAG_TO_PUBLIC}mo").dt.month_end() <= t)
        then = build_public(known).filter(pl.col("public_date") <= t)
        now = public.filter(pl.col("public_date") <= t)
        key = ["gvkey", "public_date", "datadate"]
        diff = then.join(now, on=key, how="anti").height + now.join(then, on=key, how="anti").height
        out[str(pl.select(t).item())] = {"rows": now.height, "differences": diff}
        check(diff == 0 and then.height == now.height,
              f"LOOK-AHEAD: the past changes when reports after {out} are hidden")
    report["truncation_test"] = out


def coverage(df: pl.DataFrame, accounts: pl.DataFrame, cal: pl.DataFrame, report: dict) -> None:
    # Coverage at the formation date, eligible stock-months from 1963.
    acc = accounts.select("gvkey", pl.col("datadate").alias("acc_datadate"),
                          pl.col("be_x").is_not_null().alias("has_be"),
                          pl.col("at").is_not_null().alias("has_at"))
    # A report "12 months before" exists in USD (needed by growth and change signals).
    prev = accounts.select("gvkey", pl.col("datadate").dt.offset_by("12mo").dt.month_end()
                           .alias("acc_datadate"), pl.lit(True).alias("has_prev"))
    first_link = df.filter(pl.col("gvkey").is_not_null()).group_by("permno").agg(
        pl.col("eom").min().alias("first_linked"))
    e = (
        df.filter(pl.col("eligible") & (pl.col("yyyymm") >= SAMPLE_START))
        .select("permno", "eom", "yyyymm", "me", "size_grp", "gvkey", "acc_datadate")
        .join(acc, on=["gvkey", "acc_datadate"], how="left")
        .join(prev, on=["gvkey", "acc_datadate"], how="left")
        .join(first_link, on="permno", how="left")
        .with_columns(
            linked=pl.col("gvkey").is_not_null(),
            report=pl.col("acc_datadate").is_not_null(),
            be=pl.col("has_be").fill_null(False),
            at=pl.col("has_at").fill_null(False),
            two_reports=pl.col("acc_datadate").is_not_null() & pl.col("has_prev").fill_null(False),
            link_age=months_between(pl.col("eom"), pl.col("first_linked")),
        )
    )
    flags = ["linked", "report", "at", "be", "two_reports"]

    def cov(g: pl.DataFrame) -> dict:
        tot = g["me"].sum()
        return {"rows": g.height,
                **{f: {"n": round(g[f].mean(), 4),
                       "me": round(g.filter(f)["me"].sum() / tot, 4)} for f in flags}}

    report["coverage_eligible_from_1963"] = cov(e)
    report["coverage_by_decade"] = {
        str(d): cov(g) for (d,), g in
        e.with_columns(decade=pl.col("yyyymm") // 1000 * 10).sort("decade")
        .group_by("decade", maintain_order=True)
    }
    report["coverage_by_size_grp"] = {
        str(s): cov(g) for (s,), g in e.sort("size_grp").group_by("size_grp", maintain_order=True)
    }
    # Among linked rows: by months since the stock's first linked month.
    age = (e.filter("linked").with_columns(
        bucket=pl.when(pl.col("link_age") < 6).then(pl.lit("00-05"))
        .when(pl.col("link_age") < 18).then(pl.lit("06-17"))
        .when(pl.col("link_age") < 36).then(pl.lit("18-35")).otherwise(pl.lit("36+"))))
    report["coverage_linked_by_months_since_first_link"] = {
        str(b): cov(g) for (b,), g in age.sort("bucket").group_by("bucket", maintain_order=True)
    }
    by_month = e.group_by("eom").agg((pl.col("me").filter("be").sum() / pl.col("me").sum()).alias("w"))
    report["be_coverage_me_per_month"] = {"min": by_month["w"].min(), "mean": by_month["w"].mean()}
    # Most of the eligible market must have a usable book equity in the sample.
    check(report["coverage_eligible_from_1963"]["be"]["me"] > 0.85,
          "Less than 85 % of eligible market equity has a usable book equity")
    check(by_month["w"].min() > 0.6, f"A sample month with only {by_month['w'].min():.1%} book equity")

    # Age of the report in use (months since datadate).
    report["acc_age_distribution_eligible"] = dict(
        e.filter("report").join(
            e.filter("report").select("permno", "eom",
                                      months_between(pl.col("eom"), pl.col("acc_datadate")).alias("a")),
            on=["permno", "eom"])["a"].value_counts().sort("a").iter_rows())


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/8_accounting_availability.py", "inputs": {},
                    "lag_to_public_months": LAG_TO_PUBLIC, "max_data_lag_months": MAX_DATA_LAG}
    availability_self_test()
    panel, panel_run = read_verified(PANEL, PANEL_REPORT)
    ccm, ccm_run = read_verified(CCM, CCM_REPORT)
    accounts, acc_run = read_verified(ACCOUNTS, ACCOUNTS_REPORT)
    report["inputs"].update({PANEL.name: {"from_run": panel_run}, CCM.name: {"from_run": ccm_run},
                             ACCOUNTS.name: {"from_run": acc_run}})
    # The links must have been built on this panel, and the accounts on these links.
    ccm_in = json.loads(CCM_REPORT.read_text(encoding="utf-8"))["inputs"]
    acc_in = json.loads(ACCOUNTS_REPORT.read_text(encoding="utf-8"))["inputs"]
    check(ccm_in[PANEL.name]["from_run"] == panel_run, "ccm_links was built on another panel run")
    check(acc_in[CCM.name]["from_run"] == ccm_run, "compustat_annual was built on another links run")

    cal = read_report_calendar(report)
    # Same raw file as step 7: the hash of the bytes read here must be the one
    # recorded there (a changed non-USD date would not show in the USD keys).
    check(report["inputs"][FUNDA.name] == acc_in[FUNDA.name],
          f"{FUNDA.name} is not the file used by compustat_annual")
    # The calendar must hold exactly the USD reports of compustat_annual.
    usd = cal.filter("usd").select("gvkey", "datadate")
    check(usd.height == accounts.height
          and usd.join(accounts, on=["gvkey", "datadate"], how="anti").height == 0,
          "The report calendar and compustat_annual disagree on USD reports")

    windows = add_public_window(cal)
    public = expand_public(windows)
    report["acc_public_rows"] = public.height
    df = attach(panel, ccm, public)

    check_no_look_ahead(df, ccm, windows, report)
    check_truncation(cal, public, report)
    coverage(df, accounts, cal, report)

    publish(
        {PROCESSED / "acc_public.parquet": public, PROCESSED / "crsp_panel_acc.parquet": df},
        report, PROCESSED / "accounting_availability_report.json",
    )
    print(f"accounting_availability: {public.height:,} firm-months with a usable report; "
          f"panel {df.height:,} rows, {report['rows_with_accounts']:,} with accounts. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
