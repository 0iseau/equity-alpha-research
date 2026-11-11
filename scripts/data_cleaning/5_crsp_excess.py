"""Step 5 of CleaningSpec.md: excess returns, and the Fama-French factor table.

Reference code (Resources/reference_code/):
- Tidy Finance, accessing-and-managing-financial-data.qmd: read the Ken French
  factor files, missing codes -99.99 / -999 -> null, percent / 100, rename
  Mkt-RF -> mkt_excess, RF -> risk_free. Copied.
- Tidy Finance, wrds-crsp-and-compustat.qmd: left join on the month, then
  ret_excess = ret - risk_free. Copied.
- JKP aux_functions.py: ret_exc = ret - coalesce(t30ret, rf) and ret_exc_lead1m
  (excess return of the next month). We have no CRSP t30ret, so rf only.

Deviations (see CleaningSpec.md):
- ret is the validated total return of steps 1-2 (delisting included), not MthRet.
- ret_exc_lead1 = ret_lead1 (step 3: row of month t+1, delisting month included)
  minus rf of month t+1. A missing return stays missing.
- No row is dropped here (Tidy Finance drops missing ret_excess; we keep them).

Outputs (data/processed/):
- ff_factors_monthly.parquet   yyyymm, FF3 factors, FF5 factors (_ff5), mom, risk_free
- crsp_panel_exc.parquet       crsp_panel + risk_free, ret_exc, ret_exc_lead1
- crsp_excess_report.json      checks, counts and output hashes (written last)
"""

from __future__ import annotations

import io
import zipfile

import polars as pl

from utils import PROCESSED, RAW, CheckError, check, publish, read_raw_verified, read_verified

PANEL = PROCESSED / "crsp_panel.parquet"
PANEL_REPORT = PROCESSED / "crsp_size_report.json"
FRENCH = RAW / "french"
FRENCH_MANIFEST = FRENCH / "manifest.json"
FF3 = FRENCH / "F-F_Research_Data_Factors_CSV.zip"
FF5 = FRENCH / "F-F_Research_Data_5_Factors_2x3_CSV.zip"
MOM = FRENCH / "F-F_Momentum_Factor_CSV.zip"
SAMPLE_START = 196301
FF5_START = 196307  # first month of the Fama-French five-factor file


def month_index(yyyymm: pl.Expr) -> pl.Expr:
    # Number of months since year 0, to count and compare months.
    return (yyyymm // 100) * 12 + yyyymm % 100


def read_french_monthly(path, header: str, report: dict) -> pl.DataFrame:
    """
    Description:
        Monthly block of a Ken French factor file (Tidy Finance cleaning).
    Steps:
        1) Read the zip only if its bytes match the download manifest.
        2) The monthly block starts after the exact header line and ends at
           the first blank line (the annual block comes after).
        3) Months must be real, unique and consecutive.
        4) -99.99 / -999 -> null, then percent / 100 (Tidy Finance).
        5) Every value left must be a finite number.
    Output:
        DataFrame with yyyymm (Int32) and lower-case factor columns.
    """
    data, digest = read_raw_verified(path, FRENCH_MANIFEST)
    report["inputs"][path.name] = digest
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        check(len(names) == 1, f"{path.name}: expected one file, got {names}")
        lines = z.read(names[0]).decode("latin-1").splitlines()
    check(header in lines, f"{path.name}: header {header!r} not found")
    start = lines.index(header) + 1
    end = lines.index("", start)
    cols = ["yyyymm"] + [c.lower() for c in header.split(",")[1:]]
    df = pl.read_csv(io.StringIO("\n".join(lines[start:end])), has_header=False,
                     new_columns=cols, infer_schema=False)
    # Values are padded with spaces: strip, then cast strictly.
    df = df.select(
        pl.col("yyyymm").str.strip_chars().cast(pl.Int32, strict=True),
        *[pl.col(c).str.strip_chars().cast(pl.Float64, strict=True) for c in cols[1:]],
    )
    ym = pl.col("yyyymm")
    check(df["yyyymm"].null_count() == 0, f"{path.name}: a row without a month")
    bad = df.filter(~((ym % 100).is_between(1, 12) & (ym // 100).is_between(1900, 2100))).height
    check(bad == 0, f"{path.name}: {bad} rows that are not real months")
    check(df["yyyymm"].is_unique().all(), f"{path.name}: duplicate months")
    check((df.select(month_index(ym))["yyyymm"].diff().drop_nulls() == 1).all(),
          f"{path.name}: months not consecutive")
    df = df.with_columns(pl.exclude("yyyymm").replace({-99.99: None, -999.0: None}) / 100)
    for c in cols[1:]:
        bad = df.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height
        check(bad == 0, f"{path.name}: {bad} non-finite values in {c}")
    return df


def build_factors(last_month: int, report: dict) -> pl.DataFrame:
    """
    Description:
        FF3 (with RF), FF5 factors and momentum in one monthly table.
    Steps:
        1) Read the three files.
        2) RF must be present and equal in FF3 and FF5 on every common month.
        3) Keep each model's own factors (Tidy Finance): FF3 columns, FF5 columns.
        4) Every factor must be present on every month where we will use it.
    Output:
        One row per month; returns in decimals.
    """
    ff3 = read_french_monthly(FF3, ",Mkt-RF,SMB,HML,RF", report)
    ff5 = read_french_monthly(FF5, ",Mkt-RF,SMB,HML,RMW,CMA,RF", report)
    mom = read_french_monthly(MOM, ",Mom", report)

    both = ff3.join(ff5, on="yyyymm", suffix="_5")
    check(both.height == ff5.height, "FF5 months missing in FF3")
    # Null-aware: a missing RF on either side is a difference.
    bad = both.filter(pl.col("rf").is_null() | pl.col("rf_5").is_null()
                      | ((pl.col("rf") - pl.col("rf_5")).abs() > 1e-9)).height
    check(bad == 0, f"{bad} common months where FF5 RF is missing or differs from FF3 RF")
    # Mkt-RF differs a little between the two files: report it, stop if large.
    d_mkt = (pl.col("mkt-rf") - pl.col("mkt-rf_5")).abs()
    report["ff5_vs_ff3_mkt_excess"] = {
        "max_abs_diff": both.select(d_mkt.max()).item(),
        "months_diff_above_0.0001": both.filter(d_mkt > 0.0001 + 1e-9).height,
        "months": both.height,
    }
    check(both.select(d_mkt.max()).item() < 0.002, "FF5 Mkt-RF far from FF3")
    out = (
        ff3.rename({"mkt-rf": "mkt_excess", "rf": "risk_free"})
        .join(ff5.select("yyyymm", mkt_excess_ff5="mkt-rf", smb_ff5="smb", hml_ff5="hml",
                         rmw="rmw", cma="cma"), on="yyyymm", how="left")
        .join(mom, on="yyyymm", how="left")
        .select("yyyymm", "mkt_excess", "smb", "hml", "mkt_excess_ff5", "smb_ff5", "hml_ff5",
                "rmw", "cma", "mom", "risk_free")
    )

    # Each factor must be there on every month of its use: sample start (FF5: its
    # own start) to the last month of the panel.
    report["factors"] = {}
    for c in out.columns[1:]:
        first = FF5_START if c in {"mkt_excess_ff5", "smb_ff5", "hml_ff5", "rmw", "cma"} \
            else SAMPLE_START
        expected = (last_month // 100 * 12 + last_month % 100) - (first // 100 * 12 + first % 100) + 1
        have = out.filter(pl.col("yyyymm").is_between(first, last_month)
                          & pl.col(c).is_not_null()).height
        ok = out.filter(pl.col(c).is_not_null())["yyyymm"]
        report["factors"][c] = {"first": ok.min(), "last": ok.max(), "months": ok.len(),
                                "required_from": first, "required_to": last_month}
        check(have == expected, f"{c}: {have} months of {expected} from {first} to {last_month}")
    rf = out["risk_free"]
    report["risk_free"] = {"min": rf.min(), "max": rf.max(), "nulls": rf.null_count()}
    # Monthly T-bill return: never missing, between -0.1 % and 2 %.
    check(rf.null_count() == 0, "Missing risk-free rate")
    check(rf.min() > -0.001 and rf.max() < 0.02, f"Risk-free rate out of range: {report['risk_free']}")
    return out


def add_excess_returns(df: pl.DataFrame, ff: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        ret_exc for month t and ret_exc_lead1 for month t+1 (TF, JKP).
    Steps:
        1) Month t from eom; it must equal yyyymm.
        2) Left join rf of month t, then ret_exc = ret - rf (TF).
        3) Left join rf of month t+1, then ret_exc_lead1 = ret_lead1 - rf_lead1.
    Output:
        Panel with risk_free, ret_exc, ret_exc_lead1.
    """
    n = df.height
    ym = lambda e: (e.dt.year() * 100 + e.dt.month()).cast(pl.Int32)
    check(df.filter(ym(pl.col("eom")) != pl.col("yyyymm")).height == 0, "eom and yyyymm differ")
    rf = ff.select("yyyymm", "risk_free")
    df = (
        df.with_columns(yyyymm_lead1=ym(pl.col("eom").dt.offset_by("1mo").dt.month_end()))
        .join(rf, on="yyyymm", how="left")
        .join(rf.rename({"yyyymm": "yyyymm_lead1", "risk_free": "risk_free_lead1"}),
              on="yyyymm_lead1", how="left")
        .with_columns(
            ret_exc=pl.col("ret") - pl.col("risk_free"),
            ret_exc_lead1=pl.col("ret_lead1") - pl.col("risk_free_lead1"),
        )
        .drop("yyyymm_lead1", "risk_free_lead1")
    )
    check(df.height == n, "Row count changed")
    # rf must exist for every row with a return (no silent loss).
    check(df.filter(pl.col("ret").is_not_null() & pl.col("ret_exc").is_null()).height == 0,
          "A return without a risk-free rate")
    check(df.filter(pl.col("ret_lead1").is_not_null() & pl.col("ret_exc_lead1").is_null())
          .height == 0, "A t+1 return without a risk-free rate")
    # Missing stays missing: ret_exc is null exactly when ret is null.
    check((df["ret"].is_null() == df["ret_exc"].is_null()).all(), "ret_exc null pattern differs")
    check((df["ret_lead1"].is_null() == df["ret_exc_lead1"].is_null()).all(),
          "ret_exc_lead1 null pattern differs")
    report["ret_exc_null"] = df["ret_exc"].null_count()
    report["ret_exc_lead1_null"] = df["ret_exc_lead1"].null_count()
    report["ret_exc_lead1_null_eligible"] = df.filter("eligible")["ret_exc_lead1"].null_count()
    return df


def checks(df: pl.DataFrame, ff: pl.DataFrame, report: dict) -> None:
    # 1) Risk-free rate of each row = the source series of the same month.
    by_month = df.group_by("yyyymm").agg(pl.col("risk_free").n_unique().alias("k"),
                                         pl.col("risk_free").first().alias("rf_panel"))
    bad = (by_month.join(ff.select("yyyymm", "risk_free"), on="yyyymm", how="left")
           .filter((pl.col("k") != 1) | pl.col("rf_panel").ne_missing(pl.col("risk_free"))).height)
    check(bad == 0, f"{bad} months where the panel risk-free rate differs from the source")

    # 2) Stock by stock: ret_exc_lead1 of month t = ret_exc of the same stock's row
    #    in month t+1, nulls included. With no row in t+1, it must be null.
    m = (pl.col("eom").dt.year() * 12 + pl.col("eom").dt.month()).cast(pl.Int32)
    nxt = df.select("permno", (m - 1).alias("m"), pl.col("ret_exc").alias("ret_exc_next"))
    j = df.select("permno", m.alias("m"), "ret_exc_lead1").join(nxt, on=["permno", "m"], how="left")
    check(j.height == df.height, "Duplicate stock-months in the lead check")
    bad = j.filter(pl.col("ret_exc_lead1").ne_missing(pl.col("ret_exc_next"))).height
    report["lead_check_rows"] = j.height
    check(bad == 0, f"{bad} rows where ret_exc_lead1 differs from next month's ret_exc")

    # 3) Market check: VW excess return in t+1 of eligible stocks (weights me at t)
    #    against the Fama-French market excess return of month t+1. This places the
    #    market month; it cannot tell which month's rf was used (check 2 does).
    e = df.filter(pl.col("eligible") & pl.col("ret_exc_lead1").is_not_null()
                  & (pl.col("yyyymm") >= SAMPLE_START))
    vw = (
        e.group_by("eom")
        .agg(((pl.col("me") * pl.col("ret_exc_lead1")).sum() / pl.col("me").sum()).alias("vw"))
        .with_columns(yyyymm=(pl.col("eom").dt.offset_by("1mo").dt.year() * 100
                              + pl.col("eom").dt.offset_by("1mo").dt.month()).cast(pl.Int32))
        .join(ff.select("yyyymm", "mkt_excess"), on="yyyymm")
        .sort("yyyymm")
    )
    out = {
        "months": vw.height,
        "corr": vw.select(pl.corr("vw", "mkt_excess")).item(),
        # Same with FF shifted by one month: must be much lower.
        "corr_shifted_one_month": vw.select(pl.corr("vw", pl.col("mkt_excess").shift(1))).item(),
        "mean_diff": vw.select((pl.col("vw") - pl.col("mkt_excess")).mean()).item(),
        "mean_abs_diff": vw.select((pl.col("vw") - pl.col("mkt_excess")).abs().mean()).item(),
    }
    report["vw_lead1_vs_ff_mkt_excess_from_1963"] = out
    check(out["corr"] > 0.99, f"VW excess return far from FF Mkt-RF: {out}")
    check(out["corr_shifted_one_month"] < 0.5, f"Market month check failed: {out}")


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/5_crsp_excess.py", "inputs": {}}
    df, run_id = read_verified(PANEL, PANEL_REPORT)
    report["inputs"][PANEL.name] = {"from_run": run_id}

    ff = build_factors(df["yyyymm"].max(), report)
    df = add_excess_returns(df, ff, report)
    checks(df, ff, report)

    publish(
        {PROCESSED / "ff_factors_monthly.parquet": ff,
         PROCESSED / "crsp_panel_exc.parquet": df},
        report, PROCESSED / "crsp_excess_report.json",
    )
    print(f"crsp_excess: {ff.height} factor months; panel {df.height:,} rows. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
