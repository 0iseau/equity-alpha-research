"""Step 6 of CleaningSpec.md: CRSP-Compustat links (permno-month -> gvkey).

Reference code (Resources/reference_code/):
- Tidy Finance, wrds-crsp-and-compustat.qmd:
    ccm_linking_table -> linktype in (LU, LC) and linkprim in (P, C); an open
                         end date means the link is still active. Copied.
    ccm_links         -> inner join on permno, keep date in [linkdt, linkenddt],
                         one gvkey per (permno, date). Copied.
- JKP aux_functions.py, gen_crsp_sf: same date window on the CRSP date (caldt);
  an open end is +infinity. JKP also takes LS and does not filter linkprim.

Deviations (see CleaningSpec.md, decision D5):
- Tidy Finance filter, not JKP: LS and the J / N link flags are left out. The
  report counts what they would add.
- The link is tested on the CRSP row date (JKP), not on a calendar month date.
  The row date is our `date` column: MthCalDt on a CRSP row (last trading day
  of the month in the CRSP calendar), delistingdt on an added delisting row (D9).
- Fail-closed: overlapping links for one permno or one gvkey stop the script.

Outputs (data/processed/):
- ccm_link_table.parquet   kept links: permno, gvkey, linkdt, linkenddt (null = open), ...
- ccm_links.parquet        one row per linked stock-month: permno, yyyymm, eom, date, gvkey, ...
- ccm_links_report.json    checks, counts and output hashes (written last)
"""

from __future__ import annotations

import io

import polars as pl

from utils import PROCESSED, RAW, CheckError, check, publish, read_raw_sized, read_verified

LINKS = RAW / "ccm_link_history.csv"
FUNDA = RAW / "ccm_fundamentals_annual.csv"
PANEL = PROCESSED / "crsp_panel_exc.parquet"
PANEL_REPORT = PROCESSED / "crsp_excess_report.json"
SAMPLE_START = 196301

COLUMNS = ["gvkey", "conm", "tic", "LINKPRIM", "LIID", "LINKTYPE", "LPERMNO", "LPERMCO",
           "LINKDT", "LINKENDDT", "ipodate", "FYRC"]
LINKTYPES = {"LC", "LU", "LS", "LX", "LD", "LN", "NR", "NU"}
LINKPRIMS = {"P", "C", "J", "N"}
NO_LINK = ["NR", "NU"]          # link types without a CRSP security
FAR = pl.date(9999, 12, 31)     # stands for an open end date in comparisons


def read_links(report: dict) -> pl.DataFrame:
    """
    Description:
        Read the raw CCM link history with strict checks.
    Steps:
        1) Read the bytes once; size must match the raw manifest; record the hash.
        2) Exact header; known link types and flags.
        3) Cast: dates strictly; LINKENDDT 'E' (still active) -> null.
        4) Keys: (gvkey, LIID, LINKDT) unique; LPERMNO missing only for NR / NU.
    Output:
        All raw links, typed, lower-case columns.
    """
    df = pl.read_csv(io.BytesIO(read_raw_sized(LINKS, report)), infer_schema=False)
    check(df.columns == COLUMNS, f"Unexpected columns in {LINKS.name}: {df.columns}")
    report["raw_link_rows"] = df.height
    for c in ["gvkey", "LINKPRIM", "LIID", "LINKTYPE", "LINKDT", "LINKENDDT"]:
        check(df[c].null_count() == 0, f"Missing {c}")
    check(set(df["LINKTYPE"].unique()) <= LINKTYPES, "Unknown LINKTYPE")
    check(set(df["LINKPRIM"].unique()) <= LINKPRIMS, "Unknown LINKPRIM")
    check(df["gvkey"].str.contains(r"^\d{6}$").all(), "gvkey is not 6 digits")
    # A link type without a CRSP security has no permno; all others have one.
    bad = df.filter(pl.col("LPERMNO").is_null() != pl.col("LINKTYPE").is_in(NO_LINK)).height
    check(bad == 0, f"{bad} rows where LPERMNO does not agree with LINKTYPE")

    df = df.select(
        pl.col("gvkey"),
        pl.col("LPERMNO").cast(pl.Int64, strict=True).alias("permno"),
        pl.col("LPERMCO").cast(pl.Int64, strict=True).alias("permco"),
        pl.col("LINKTYPE").alias("linktype"),
        pl.col("LINKPRIM").alias("linkprim"),
        pl.col("LIID").alias("liid"),
        pl.col("LINKDT").str.to_date("%Y-%m-%d", strict=True).alias("linkdt"),
        # 'E' means the link is still active: open end, kept as null.
        pl.when(pl.col("LINKENDDT") != "E").then(pl.col("LINKENDDT"))
        .str.to_date("%Y-%m-%d", strict=True).alias("linkenddt"),
    )
    check(df.select("gvkey", "liid", "linkdt").is_unique().all(), "Duplicate (gvkey, LIID, LINKDT)")
    check(df.filter(pl.col("linkenddt") < pl.col("linkdt")).height == 0, "Link ends before it starts")
    report["raw_links_by_type_and_flag"] = {
        f"{t}/{p}": n for t, p, n in
        df.group_by("linktype", "linkprim").len().sort("linktype", "linkprim").iter_rows()
    }
    return df


def count_overlaps(links: pl.DataFrame, by: str) -> int:
    # Links of one permno (or one gvkey) must not overlap in time.
    x = links.with_columns(end=pl.col("linkenddt").fill_null(FAR)).sort(by, "linkdt", "end")
    # Latest end date among the earlier links of the same group.
    x = x.with_columns(prev_end=pl.col("end").cum_max().shift(1).over(by))
    return x.filter(pl.col("linkdt") <= pl.col("prev_end")).height


def filter_links(raw: pl.DataFrame, report: dict) -> pl.DataFrame:
    """Tidy Finance filter: linktype in (LU, LC) and linkprim in (P, C). Decision D5."""
    links = raw.filter(pl.col("linktype").is_in(["LU", "LC"]) & pl.col("linkprim").is_in(["P", "C"]))
    report["kept_links"] = {"rows": links.height, "permnos": links["permno"].n_unique(),
                            "gvkeys": links["gvkey"].n_unique()}
    # One gvkey per permno and one permno per gvkey at any date.
    for by in ["permno", "gvkey"]:
        n = count_overlaps(links, by)
        check(n == 0, f"{n} overlapping links for the same {by}")
    return links.sort("permno", "linkdt")


def link_months(panel: pl.DataFrame, links: pl.DataFrame) -> pl.DataFrame:
    # Tidy Finance ccm_links: join on permno, keep the row date inside the link window.
    return (
        panel.select("permno", "yyyymm", "eom", "date")
        .join(links.select("permno", "gvkey", "linktype", "linkprim", "liid", "linkdt", "linkenddt"),
              how="inner", on="permno")
        .filter((pl.col("date") >= pl.col("linkdt"))
                & (pl.col("date") <= pl.col("linkenddt").fill_null(FAR)))
        .select("permno", "yyyymm", "eom", "date", "gvkey", "linktype", "linkprim", "liid")
        .sort("permno", "eom")
    )


def checks(panel: pl.DataFrame, raw: pl.DataFrame, links: pl.DataFrame, ccm: pl.DataFrame,
           report: dict) -> None:
    # 1) No duplicate: one gvkey per stock-month, one stock per gvkey at any date.
    check(ccm.select("permno", "eom").is_unique().all(), "Duplicate (permno, month) links")
    check(ccm.select("gvkey", "date").is_unique().all(), "Duplicate (gvkey, date) links")
    check(ccm.join(panel.select("permno", "eom"), on=["permno", "eom"], how="anti").height == 0,
          "A linked stock-month is not in the panel")
    report["linked_stock_months"] = ccm.height

    # 1b) Second route, to catch a lost link: for every panel row, take the last
    #     kept link that started on or before the row date, and keep it if it has
    #     not ended. (Links of one permno do not overlap, so this is the only
    #     candidate.) The result must be exactly the published table.
    expected = (
        panel.select("permno", "eom", "date", "permco").sort("date")
        .join_asof(links.select("permno", "gvkey", "linkdt", "linkenddt",
                                pl.col("permco").alias("link_permco")).sort("linkdt"),
                   left_on="date", right_on="linkdt", by="permno", strategy="backward",
                   check_sortedness=False)
        .filter(pl.col("gvkey").is_not_null()
                & (pl.col("date") <= pl.col("linkenddt").fill_null(FAR)))
    )
    key = ["permno", "eom", "gvkey"]
    missing = expected.join(ccm, on=key, how="anti").height
    extra_rows = ccm.join(expected, on=key, how="anti").height
    report["expected_link_check"] = {"expected": expected.height, "missing": missing,
                                     "unexpected": extra_rows}
    check(expected.height == ccm.height and missing == 0 and extra_rows == 0,
          f"Published links differ from expected links: {report['expected_link_check']}")
    # The CRSP company of the link must be the company of the panel row.
    bad = expected.filter(pl.col("permco").ne_missing(pl.col("link_permco"))).height
    check(bad == 0, f"{bad} linked rows where the link PERMCO differs from the panel PERMCO")
    # Two stocks of one gvkey in the same month, on different dates: an old stock
    # that delists and its successor. Allowed, but never two eligible stocks.
    two = ccm.join(panel.select("permno", "eom", "eligible"), on=["permno", "eom"])
    report["gvkey_months_with_two_stocks"] = (
        two.group_by("gvkey", "eom").len().filter(pl.col("len") > 1).height)
    check(two.filter("eligible").select("gvkey", "eom").is_unique().all(),
          "Two eligible stocks for one gvkey in the same month")

    # 2) Coverage of eligible stock-months since 1963, by count and by market equity.
    e = (panel.filter(pl.col("eligible") & (pl.col("yyyymm") >= SAMPLE_START))
         .select("permno", "eom", "yyyymm", "me", "size_grp")
         .join(ccm.select("permno", "eom", "gvkey"), on=["permno", "eom"], how="left")
         .with_columns(linked=pl.col("gvkey").is_not_null()))
    cov = lambda g: {"n": g["linked"].mean(),
                     "me": g.filter("linked")["me"].sum() / g["me"].sum()}
    report["coverage_eligible_from_1963"] = {"rows": e.height, **cov(e)}
    report["coverage_by_decade"] = {
        str(d): cov(g) for (d,), g in
        e.with_columns(decade=pl.col("yyyymm") // 1000 * 10).sort("decade")
        .group_by("decade", maintain_order=True)
    }
    report["coverage_by_size_grp"] = {
        str(s): cov(g)["n"] for (s,), g in e.sort("size_grp").group_by("size_grp", maintain_order=True)
    }
    by_month = (e.group_by("eom").agg((pl.col("me").filter("linked").sum() / pl.col("me").sum())
                                      .alias("w")))
    report["coverage_me_per_month"] = {"min": by_month["w"].min(), "mean": by_month["w"].mean()}
    # Most of the eligible market must be linked: over the sample and in every month.
    check(report["coverage_eligible_from_1963"]["me"] > 0.9, "Less than 90 % of market equity linked")
    check(by_month["w"].min() > 0.8, f"A sample month with only {by_month['w'].min():.1%} linked")

    # 3) What the left-out links would add (sensitivity for decision D5).
    def extra(types: list[str], prims: list[str]) -> dict:
        alt = raw.filter(pl.col("linktype").is_in(types) & pl.col("linkprim").is_in(prims))
        a = (e.filter(~pl.col("linked")).select("permno", "eom", "me")
             .join(panel.select("permno", "eom", "date"), on=["permno", "eom"])
             .join(alt.select("permno", "linkdt", "linkenddt"), on="permno", how="inner")
             .filter((pl.col("date") >= pl.col("linkdt"))
                     & (pl.col("date") <= pl.col("linkenddt").fill_null(FAR)))
             .unique(["permno", "eom"]))
        return {"stock_months": a.height, "permnos": a["permno"].n_unique(),
                "me_share": a["me"].sum() / e["me"].sum()}
    report["left_out_links_eligible_from_1963"] = {
        "LC_LU_with_J_or_N": extra(["LC", "LU"], ["J", "N"]),
        "LS_any_flag": extra(["LS"], ["P", "C", "J", "N"]),
    }

    # 4) Consistency with the WRDS export of annual accounts, which WRDS merged with
    #    this same link table: every (gvkey, permno, datadate) of that file must
    #    fall inside one raw link window. This tests our reading of the link dates
    #    only; it says nothing on which accounts exist for a linked month.
    f = (pl.read_csv(io.BytesIO(read_raw_sized(FUNDA, report)),
                     columns=["GVKEY", "LPERMNO", "datadate"], infer_schema=False)
         .select(pl.col("GVKEY").alias("gvkey"),
                 pl.col("LPERMNO").cast(pl.Int64, strict=True).alias("permno"),
                 pl.col("datadate").str.to_date("%Y-%m-%d", strict=True))
         .with_row_index("i"))
    inside = lambda t: (
        f.join(t.select("gvkey", "permno", "linkdt", "linkenddt"), on=["gvkey", "permno"])
        .filter((pl.col("datadate") >= pl.col("linkdt"))
                & (pl.col("datadate") <= pl.col("linkenddt").fill_null(FAR)))["i"].n_unique()
    )
    n_raw, n_kept = inside(raw.filter(pl.col("permno").is_not_null())), inside(links)
    report["wrds_merged_accounts_check"] = {"rows": f.height, "inside_a_raw_link": n_raw,
                                            "inside_a_kept_link": n_kept}
    check(n_raw == f.height, f"{f.height - n_raw} WRDS-merged account rows outside every raw link")


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/6_ccm_links.py", "inputs": {}}
    panel, run_id = read_verified(PANEL, PANEL_REPORT)
    report["inputs"][PANEL.name] = {"from_run": run_id}

    raw = read_links(report)
    links = filter_links(raw, report)
    ccm = link_months(panel, links)
    checks(panel, raw, links, ccm, report)

    publish(
        {PROCESSED / "ccm_link_table.parquet": links, PROCESSED / "ccm_links.parquet": ccm},
        report, PROCESSED / "ccm_links_report.json",
    )
    print(f"ccm_links: {links.height:,} links kept; {ccm.height:,} linked stock-months. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
