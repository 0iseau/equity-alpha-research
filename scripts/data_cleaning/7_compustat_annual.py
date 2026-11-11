"""Step 7 of CleaningSpec.md: annual accounting data, one row per firm and fiscal year end.

Reference code (Resources/reference_code/):
- Tidy Finance, wrds-crsp-and-compustat.qmd: filters indfmt = INDL, datafmt = STD,
  consol = C, curcd = USD; book equity; one report per firm and year.
- JKP aux_functions.py:
    load_raw_fund_table_and_filter -> INDL + STD + popsrc = D + consol = C
    add_helper_vars                -> negative at / sale / che set to null;
                                      pstk_x, txditc_x, seq_x, be_x. Copied.

Deviations (see CleaningSpec.md):
- USD rows only (Tidy Finance; decision D6). JKP converts currencies.
- Our WRDS export is a CRSP/Compustat merged file: one row per linked PERMNO.
  We drop LPERMNO / LPERMCO after checking that all other fields are identical,
  and link again ourselves with the step 6 table.
- No txdb / itcb in our export: txditc_x = txditc.
- Header fields (costat, fic, ipodate) are dropped: they describe the firm as of
  today, so they must not be used at a past date. ajex and prcc_f are not used.
- Other JKP helper variables are built at the signal step.

Outputs (data/processed/):
- compustat_annual.parquet       gvkey, datadate, fyear, fyr, sich, raw items,
                                 pstk_x, txditc_x, seq_x, be_x
- compustat_annual_report.json   checks, counts and output hashes (written last)
"""

from __future__ import annotations

import io

import polars as pl

from utils import PROCESSED, RAW, CheckError, check, publish, read_raw_sized, read_verified

FUNDA = RAW / "ccm_fundamentals_annual.csv"
CCM = PROCESSED / "ccm_links.parquet"
CCM_REPORT = PROCESSED / "ccm_links_report.json"

KEYS = ["GVKEY", "LPERMNO", "LPERMCO", "datadate", "fyear"]
FORMATS = {"indfmt": "INDL", "consol": "C", "popsrc": "D", "datafmt": "STD"}
ITEMS = ["act", "at", "capx", "ceq", "che", "cogs", "dlc", "dltt", "ib", "lct", "lt", "ni",
         "oibdp", "pstk", "pstkl", "pstkrv", "sale", "seq", "txditc", "xint", "xsga"]
OTHER = ["ajex", "curcd", "fyr", "costat", "fic", "sich", "prcc_f", "ipodate"]
COLUMNS = (KEYS + list(FORMATS) + ["ajex", "curcd", "fyr"] + ITEMS
           + ["costat", "fic", "sich", "prcc_f", "ipodate"])
# JKP add_helper_vars sets these to null when negative (we have no revt, dv).
NON_NEGATIVE = ["at", "sale", "che"]


def read_accounts(report: dict) -> pl.DataFrame:
    """
    Description:
        Read the raw annual accounts with strict checks, one row per gvkey-datadate.
    Steps:
        1) Read the bytes once (size checked against the raw manifest, hash recorded).
        2) Exact header; the four format filters must hold on every row (JKP, TF).
        3) Drop LPERMNO / LPERMCO; rows of one gvkey-datadate must then be identical.
        4) Cast: dates and numbers strictly; numbers must be finite.
    Output:
        All currencies, typed, one row per gvkey-datadate.
    """
    df = pl.read_csv(io.BytesIO(read_raw_sized(FUNDA, report)), infer_schema=False)
    check(sorted(df.columns) == sorted(COLUMNS), f"Unexpected columns in {FUNDA.name}")
    report["raw_rows"] = df.height
    for c in ["GVKEY", "LPERMNO", "datadate"]:
        check(df[c].null_count() == 0, f"Missing {c}")
    check(df["GVKEY"].str.contains(r"^\d{6}$").all(), "GVKEY is not 6 digits")
    for c, v in FORMATS.items():
        # A missing value is also wrong (a plain == would skip it).
        bad = df.filter(pl.col(c).ne_missing(pl.lit(v))).height
        check(bad == 0, f"{bad} rows where {c} is not {v}")

    # The export has one row per linked PERMNO. Before dropping the CRSP ids:
    # they must be whole numbers, and (GVKEY, datadate, LPERMNO) must be unique,
    # so that every removed row is a PERMNO copy and not a true duplicate.
    check(df["LPERMCO"].null_count() == 0, "Missing LPERMCO")
    df = df.with_columns(pl.col("LPERMNO", "LPERMCO").cast(pl.Int64, strict=True))
    check(df.select("GVKEY", "datadate", "LPERMNO").is_unique().all(),
          "Duplicate (GVKEY, datadate, LPERMNO) in the raw file")
    # All other fields must be the same across the copies.
    df = df.drop("LPERMNO", "LPERMCO").unique()
    check(df.select("GVKEY", "datadate").is_unique().all(),
          "Rows of one gvkey-datadate differ beyond LPERMNO")
    report["gvkey_datadate_rows"] = df.height
    report["rows_removed_as_permno_copies"] = report["raw_rows"] - df.height

    df = df.select(
        pl.col("GVKEY").alias("gvkey"),
        pl.col("datadate").str.to_date("%Y-%m-%d", strict=True),
        pl.col("fyear").cast(pl.Int32, strict=True),
        pl.col("fyr").cast(pl.Int32, strict=True),
        pl.col("curcd"),
        pl.col("sich").cast(pl.Int32, strict=True),
        *[pl.col(c).cast(pl.Float64, strict=True) for c in ITEMS],
    )
    for c in ITEMS:
        bad = df.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height
        check(bad == 0, f"{bad} non-finite values in {c}")
    return df


def keep_usd(df: pl.DataFrame, report: dict) -> pl.DataFrame:
    """Tidy Finance filter curcd = 'USD' (decision D6); then check the keys."""
    report["rows_by_currency"] = {
        str(k): n for k, n in df["curcd"].value_counts().sort("count", descending=True).iter_rows()
    }
    per_firm = df.group_by("gvkey").agg(
        pl.col("curcd").drop_nulls().n_unique().alias("known"),   # known currencies only
        pl.col("curcd").is_null().any().alias("has_missing"),
        (pl.col("curcd") == "USD").any().alias("usd"),
    )
    usd = per_firm.filter("usd")
    report["gvkeys"] = {
        "all": per_firm.height,
        "with_usd_rows": usd.height,
        "usd_and_another_known_currency": usd.filter(pl.col("known") > 1).height,
        "usd_and_only_a_missing_currency": usd.filter((pl.col("known") == 1) & pl.col("has_missing")).height,
        "no_usd_rows": per_firm.filter(~pl.col("usd")).height,
    }
    df = df.filter(pl.col("curcd") == "USD").drop("curcd")
    report["usd_rows"] = df.height

    # Keys of the kept rows: fiscal year known and coherent with the date.
    check(df["fyear"].null_count() == 0 and df["fyr"].null_count() == 0, "Missing fyear or fyr")
    d = pl.col("datadate")
    check(df.filter(d != d.dt.month_end()).height == 0, "A datadate that is not a month end")
    check(df.filter(pl.col("fyr") != d.dt.month()).height == 0, "fyr differs from the datadate month")
    # Compustat rule: a year ending in January-May belongs to the fiscal year before.
    rule = pl.when(d.dt.month() >= 6).then(d.dt.year()).otherwise(d.dt.year() - 1)
    check(df.filter(pl.col("fyear") != rule).height == 0, "fyear differs from the Compustat rule")
    # One report per firm and fiscal year. Tidy Finance keeps the last report of
    # each calendar year of datadate instead; we keep every fiscal year end.
    check(df.select("gvkey", "fyear").is_unique().all(), "Two reports for one gvkey-fyear")
    per_year = df.group_by("gvkey", pl.col("datadate").dt.year()).len()
    report["extra_rows_vs_tidy_finance_calendar_year_rule"] = int((per_year["len"] - 1).sum())
    return df.sort("gvkey", "datadate")


def add_book_equity(df: pl.DataFrame, report: dict) -> pl.DataFrame:
    """
    Description:
        Book equity, copied from JKP add_helper_vars.
    Steps:
        1) at, sale, che: a negative value becomes null (JKP).
        2) pstk_x = coalesce(pstkrv, pstkl, pstk); txditc_x = txditc.
        3) seq_x = coalesce(seq, ceq + coalesce(pstk_x, 0), at - lt).
        4) be_x = seq_x + coalesce(txditc_x, 0) - coalesce(pstk_x, 0); null if <= 0.
    Output:
        Table with pstk_x, txditc_x, seq_x, be_x.
    """
    report["negative_set_to_null"] = {c: df.filter(pl.col(c) < 0).height for c in NON_NEGATIVE}
    df = (
        df.with_columns([
            pl.when(pl.col(c) >= 0).then(pl.col(c)).alias(c) for c in NON_NEGATIVE
        ])
        .with_columns(
            pstk_x=pl.coalesce(["pstkrv", "pstkl", "pstk"]),
            txditc_x=pl.col("txditc"),
        )
        .with_columns(
            seq_x=pl.coalesce(["seq", pl.col("ceq") + pl.coalesce(["pstk_x", 0.0]),
                               pl.col("at") - pl.col("lt")]),
            # Which formula gave seq_x (for the report only).
            seq_src=pl.when(pl.col("seq").is_not_null()).then(pl.lit("seq"))
            .when(pl.col("ceq").is_not_null()).then(pl.lit("ceq_plus_pstk"))
            .when((pl.col("at") - pl.col("lt")).is_not_null()).then(pl.lit("at_minus_lt"))
            .otherwise(pl.lit("missing")),
        )
        .with_columns(
            be_raw=pl.col("seq_x") + pl.coalesce(["txditc_x", 0.0]) - pl.coalesce(["pstk_x", 0.0]),
        )
        .with_columns(be_x=pl.when(pl.col("be_raw") > 0).then(pl.col("be_raw")))
    )
    report["seq_x_source"] = dict(df["seq_src"].value_counts().sort("seq_src").iter_rows())
    report["be_x"] = {"positive": df["be_x"].is_not_null().sum(),
                      "zero_or_negative_set_to_null": df.filter(pl.col("be_raw") <= 0).height,
                      "missing_inputs": df["be_raw"].null_count()}
    return df.drop("seq_src", "be_raw")


def book_equity_self_test() -> None:
    # Small table with book equity worked out by hand: the three sources of
    # seq_x, missing adjustments, negative inputs and the zero boundary.
    n = None
    rows = [
        # seq, ceq, pstk, pstkl, pstkrv, at, lt, txditc, sale, che -> seq_x, be_x
        (100.0, 90.0, 10.0, n, n, 500.0, 400.0, 5.0, 1.0, 1.0, 100.0, 95.0),   # seq; pstk_x = pstk
        (100.0, n, 10.0, 12.0, 15.0, n, n, n, 1.0, 1.0, 100.0, 85.0),          # pstkrv first; no txditc
        (n, 80.0, 10.0, n, n, 500.0, 400.0, 5.0, 1.0, 1.0, 90.0, 85.0),        # ceq + pstk_x
        (n, 80.0, n, n, n, 500.0, 400.0, n, 1.0, 1.0, 80.0, 80.0),             # ceq + 0; no adjustment
        (n, n, 10.0, n, n, 500.0, 430.0, 5.0, 1.0, 1.0, 70.0, 65.0),           # at - lt
        (n, n, n, n, n, 500.0, n, 5.0, 1.0, 1.0, n, n),                        # nothing: missing
        (10.0, n, 15.0, n, n, n, n, 5.0, 1.0, 1.0, 10.0, n),                   # be = 0: missing
        (10.0, n, 20.0, n, n, n, n, 5.0, 1.0, 1.0, 10.0, n),                   # be < 0: missing
        (50.0, n, n, n, n, 100.0, 50.0, n, -3.0, -2.0, 50.0, 50.0),            # negative sale, che
    ]
    cols = ["seq", "ceq", "pstk", "pstkl", "pstkrv", "at", "lt", "txditc", "sale", "che",
            "exp_seq_x", "exp_be_x"]
    t = pl.DataFrame(rows, schema={c: pl.Float64 for c in cols}, orient="row")
    out = add_book_equity(t, {})
    bad = out.filter(pl.col("seq_x").ne_missing(pl.col("exp_seq_x"))
                     | pl.col("be_x").ne_missing(pl.col("exp_be_x"))).height
    check(bad == 0, f"Book equity self-test failed on {bad} rows")
    check(out["sale"][-1] is None and out["che"][-1] is None, "Negative sale / che not set to null")


def checks(df: pl.DataFrame, report: dict) -> None:
    check(df.select("gvkey", "datadate").is_unique().all(), "Duplicate gvkey-datadate")

    # be_x again by a second route (explicit branches, no coalesce): every value
    # and every null must match, on all rows.
    has = lambda c: pl.col(c).is_not_null()
    pstk2 = (pl.when(has("pstkrv")).then(pl.col("pstkrv"))
             .when(has("pstkl")).then(pl.col("pstkl")).otherwise(pl.col("pstk")))
    seq2 = (pl.when(has("seq")).then(pl.col("seq"))
            .when(has("ceq")).then(pl.col("ceq") + pstk2.fill_null(0.0))
            .otherwise(pl.col("at") - pl.col("lt")))
    be2 = seq2 + pl.col("txditc").fill_null(0.0) - pstk2.fill_null(0.0)
    again = df.select(
        "pstk_x", "txditc_x", "seq_x", "be_x", "txditc",
        pstk2=pstk2, seq2=seq2, be2=pl.when(be2 > 0).then(be2),
    )
    bad = again.filter(pl.col("pstk_x").ne_missing(pl.col("pstk2"))
                       | pl.col("txditc_x").ne_missing(pl.col("txditc"))
                       | pl.col("seq_x").ne_missing(pl.col("seq2"))
                       | pl.col("be_x").ne_missing(pl.col("be2"))).height
    check(bad == 0, f"{bad} rows where book equity differs from its formula")
    report["rows"] = df.height
    report["gvkeys_out"] = df["gvkey"].n_unique()
    report["datadate_range"] = [df["datadate"].min(), df["datadate"].max()]
    for c in NON_NEGATIVE:
        check(df.filter(pl.col(c) < 0).height == 0, f"Negative {c} left")
    check(df.filter(pl.col("be_x") <= 0).height == 0, "be_x not positive")
    # Missing stays missing: no raw item gained or lost a value, except the three above.
    report["null_share"] = {c: round(df[c].null_count() / df.height, 4)
                            for c in ["at", "sale", "seq", "ceq", "lt", "txditc", "be_x"]}

    # Accounting identities, on rows with all terms (sanity of units and columns).
    # Balance sheet: at >= lt + seq roughly (the gap is minority interest).
    a = df.filter(pl.col("at").is_not_null() & pl.col("lt").is_not_null()
                  & pl.col("seq").is_not_null() & (pl.col("at") > 0))
    gap = ((pl.col("at") - pl.col("lt") - pl.col("seq")) / pl.col("at")).abs()
    report["identity_at_lt_seq"] = {"rows": a.height,
                                    "share_within_1pct": a.filter(gap <= 0.01).height / a.height,
                                    "share_within_10pct": a.filter(gap <= 0.10).height / a.height}
    check(report["identity_at_lt_seq"]["share_within_10pct"] > 0.95, "at = lt + seq fails too often")
    # Equity: seq = ceq + pstk.
    b = df.filter(pl.col("seq").is_not_null() & pl.col("ceq").is_not_null()
                  & pl.col("pstk").is_not_null() & (pl.col("at") > 0))
    gap = ((pl.col("seq") - pl.col("ceq") - pl.col("pstk")) / pl.col("at")).abs()
    report["identity_seq_ceq_pstk"] = {"rows": b.height,
                                       "share_within_1pct": b.filter(gap <= 0.01).height / b.height}
    check(report["identity_seq_ceq_pstk"]["share_within_1pct"] > 0.95, "seq = ceq + pstk fails too often")

    # Rows and book equity by decade of the fiscal year end.
    dec = (df.with_columns(decade=pl.col("datadate").dt.year() // 10 * 10)
           .group_by("decade").agg(pl.len().alias("rows"), pl.col("gvkey").n_unique().alias("gvkeys"),
                                   pl.col("be_x").is_not_null().mean().alias("be_share"))
           .sort("decade"))
    report["by_decade"] = {str(r["decade"]): {"rows": r["rows"], "gvkeys": r["gvkeys"],
                                              "be_share": round(r["be_share"], 4)}
                           for r in dec.to_dicts()}
    # Months between two reports of a firm: 12 is the norm.
    gap = df.with_columns(prev=pl.col("datadate").shift(1).over("gvkey")).drop_nulls("prev").select(
        mo=(pl.col("datadate").dt.year() - pl.col("prev").dt.year()) * 12
        + pl.col("datadate").dt.month() - pl.col("prev").dt.month())["mo"]
    report["months_between_reports"] = {"12": (gap == 12).sum(), "under_12": (gap < 12).sum(),
                                        "over_12": (gap > 12).sum()}
    check((gap > 0).all(), "Reports of a firm are not strictly ordered")


def link_coverage(df: pl.DataFrame, report: dict) -> None:
    # How many linked firms (step 6) have at least one USD report? No timing here:
    # the availability of accounts at each date is step 8.
    ccm, run_id = read_verified(CCM, CCM_REPORT)
    report["inputs"][CCM.name] = {"from_run": run_id}
    linked = ccm.group_by("gvkey").agg(pl.len().alias("months"))
    have = linked.join(df.select("gvkey").unique(), on="gvkey", how="semi")
    report["linked_gvkeys"] = {
        "all": linked.height, "with_usd_accounts": have.height,
        "linked_stock_months": int(linked["months"].sum()),
        "linked_stock_months_with_usd_accounts": int(have["months"].sum()),
    }
    check(have["months"].sum() / linked["months"].sum() > 0.95,
          "Less than 95 % of linked stock-months belong to a firm with accounts")


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/7_compustat_annual.py", "inputs": {}}
    book_equity_self_test()
    df = read_accounts(report)
    df = keep_usd(df, report)
    df = add_book_equity(df, report)
    checks(df, report)
    link_coverage(df, report)

    publish({PROCESSED / "compustat_annual.parquet": df}, report,
            PROCESSED / "compustat_annual_report.json")
    print(f"compustat_annual: {df.height:,} firm-years, {df['gvkey'].n_unique():,} firms. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
