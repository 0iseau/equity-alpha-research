"""Step 4 of CleaningSpec.md: NYSE size breakpoints and size groups.

Reference code (Resources/reference_code/):
- JKP jkp-data, aux_functions.py:
    nyse_size_cutoffs            -> SQL aggregates (QUANTILE_DISC at 1/20/50/80 %) copied;
                                    the NYSE filter uses our step-3 eligibility instead
    classify_stocks_size_groups  -> nano / micro / small / large / mega, copied
    market_returns, portfolio    -> me_cap = min(me, NYSE p80) (capped weights)
- Tidy Finance (size sorts): NYSE breakpoints from NYSE stocks of the filtered sample.

Deviations (see CleaningSpec.md):
- NYSE sample = our eligible NYSE stocks (step 3: common, main exchange,
  US-incorporated, me known, no delisting in the month). JKP does not require
  US incorporation; Tidy Finance does.
- No "mega" fallback when a month has no breakpoint (JKP keeps it to match SAS):
  here a month with eligible stocks and no breakpoint stops the script.
- Size groups are only labels (decision D7): no stock is removed.

Outputs (data/processed/):
- nyse_cutoffs.parquet     one row per month: n, nyse_p1, nyse_p20, nyse_p50, nyse_p80
- crsp_panel.parquet       crsp_universe + size_grp + me_cap
- crsp_size_report.json    checks, counts and output hashes (written last)
"""

from __future__ import annotations

import io
import zipfile

import polars as pl

from utils import PROCESSED, RAW, CheckError, check, publish, read_raw_verified, read_verified

UNIVERSE = PROCESSED / "crsp_universe.parquet"
UNIVERSE_REPORT = PROCESSED / "crsp_universe_report.json"
FRENCH_BP = RAW / "french" / "ME_Breakpoints_CSV.zip"
SAMPLE_START = 196301


def nyse_size_cutoffs(df: pl.DataFrame) -> pl.DataFrame:
    """JKP nyse_size_cutoffs: NYSE market equity percentiles by month.

    Aggregates copied from JKP. JKP filters on obs_main, exch_main, primary_sec and
    common; here crsp_nyse already means eligible (step 3) and on the NYSE.
    """
    return df.lazy().sql("""
            SELECT
                eom,
                COUNT(*)                    AS n,
                QUANTILE_DISC(me, 0.01)     AS nyse_p1,
                QUANTILE_DISC(me, 0.20)     AS nyse_p20,
                QUANTILE_DISC(me, 0.50)     AS nyse_p50,
                QUANTILE_DISC(me, 0.80)     AS nyse_p80
            FROM self
            WHERE  crsp_nyse = TRUE
                AND me IS NOT NULL
            GROUP BY eom
            ORDER BY eom
            """).collect()


def classify_size(df: pl.DataFrame, cutoffs: pl.DataFrame) -> pl.DataFrame:
    """JKP classify_stocks_size_groups, without the 'mega' fallback; plus me_cap (JKP)."""
    return (
        df.join(cutoffs.drop("n"), how="left", on="eom")
        .with_columns(
            size_grp=pl.when(pl.col("me").is_null()).then(None)
            .when(pl.col("nyse_p80").is_null()).then(None)
            .when(pl.col("me") >= pl.col("nyse_p80")).then(pl.lit("mega"))
            .when(pl.col("me") >= pl.col("nyse_p50")).then(pl.lit("large"))
            .when(pl.col("me") >= pl.col("nyse_p20")).then(pl.lit("small"))
            .when(pl.col("me") >= pl.col("nyse_p1")).then(pl.lit("micro"))
            .otherwise(pl.lit("nano")),
            # Capped value weight: market equity capped at the NYSE 80th percentile.
            # min_horizontal skips nulls, so we require both values first.
            me_cap=pl.when(pl.col("me").is_not_null() & pl.col("nyse_p80").is_not_null())
            .then(pl.min_horizontal(pl.col("me"), pl.col("nyse_p80"))),
        )
        .drop("nyse_p1", "nyse_p20", "nyse_p50", "nyse_p80")
    )


def read_french_breakpoints(report: dict) -> pl.DataFrame:
    # Ken French ME breakpoints: yyyymm, n, then every 5th NYSE percentile ($ millions).
    # Read the zip only if its bytes match the download manifest.
    data, digest = read_raw_verified(FRENCH_BP, FRENCH_BP.parent / "manifest.json")
    report["inputs"][FRENCH_BP.name] = digest
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read("ME_Breakpoints.csv").decode("latin-1")
    rows = [l for l in text.splitlines() if l[:6].isdigit() and "," in l]
    cols = ["yyyymm", "n"] + [f"p{5 * i}" for i in range(1, 21)]
    df = pl.read_csv(io.StringIO("\n".join(rows)), has_header=False, new_columns=cols,
                     infer_schema=False)
    # Values are padded with spaces: strip, then cast strictly.
    num = lambda c, t: pl.col(c).str.strip_chars().cast(t, strict=True)
    return df.select(
        num("yyyymm", pl.Int32),
        num("n", pl.Int64).alias("ff_n"), num("p20", pl.Float64).alias("ff_p20"),
        num("p50", pl.Float64).alias("ff_p50"), num("p80", pl.Float64).alias("ff_p80"),
    )


def checks(df: pl.DataFrame, cutoffs: pl.DataFrame, report: dict) -> None:
    # Breakpoints must be ordered.
    bad = cutoffs.filter(~((pl.col("nyse_p1") <= pl.col("nyse_p20"))
                           & (pl.col("nyse_p20") <= pl.col("nyse_p50"))
                           & (pl.col("nyse_p50") <= pl.col("nyse_p80")))).height
    check(bad == 0, f"{bad} months with unordered NYSE breakpoints")
    # Every month with eligible stocks must have breakpoints.
    e = df.filter("eligible")
    no_bp = e.filter(pl.col("size_grp").is_null()).height
    check(no_bp == 0, f"{no_bp} eligible rows without a size group")
    c = cutoffs.filter(pl.col("eom").dt.year() * 100 + pl.col("eom").dt.month() >= SAMPLE_START)
    report["nyse_stocks_per_month_from_1963"] = {"min": c["n"].min(), "max": c["n"].max()}
    check(c["n"].min() >= 500, "A sample month with fewer than 500 NYSE stocks")

    # Size groups: NYSE shares should be about 1/19/30/30/20 %; all eligible shares.
    s = e.filter(pl.col("yyyymm") >= SAMPLE_START)
    report["size_grp_share_nyse_from_1963"] = {
        k: round(v, 4) for k, v in s.filter("crsp_nyse")["size_grp"]
        .value_counts(normalize=True).iter_rows()
    }
    report["size_grp_share_eligible_from_1963"] = {
        k: round(v, 4) for k, v in s["size_grp"].value_counts(normalize=True).iter_rows()
    }
    tot = s.group_by("eom").agg(pl.col("me").sum().alias("tot"))
    sh = (s.group_by("eom", "size_grp").agg(pl.col("me").sum()).join(tot, on="eom")
          .group_by("size_grp").agg((pl.col("me") / pl.col("tot")).mean().alias("w")))
    report["size_grp_mean_me_share_from_1963"] = {
        r["size_grp"]: round(r["w"], 4) for r in sh.to_dicts()
    }
    # me_cap on the full panel: null if me or p80 is missing, else exactly min(me, p80).
    p = df.select("eom", "me", "me_cap").join(cutoffs.select("eom", "nyse_p80"), on="eom", how="left")
    known = pl.col("me").is_not_null() & pl.col("nyse_p80").is_not_null()
    bad_null = p.filter(~known & pl.col("me_cap").is_not_null()).height
    # ne_missing: a null me_cap with both values known also counts as wrong.
    bad_min = p.filter(known & pl.col("me_cap").ne_missing(pl.min_horizontal("me", "nyse_p80"))).height
    report["me_cap_null_rows"] = p["me_cap"].null_count()
    check(bad_null == 0, f"{bad_null} rows with me_cap but no me or no p80")
    check(bad_min == 0, f"{bad_min} rows with me_cap different from min(me, p80)")

    # Independent check against Ken French NYSE breakpoints.
    ff = read_french_breakpoints(report)
    check(ff["yyyymm"].is_unique().all(), "Duplicate months in Ken French breakpoints")
    ours = cutoffs.with_columns(
        yyyymm=(pl.col("eom").dt.year() * 100 + pl.col("eom").dt.month()).cast(pl.Int32)
    ).filter(pl.col("yyyymm") >= SAMPLE_START)
    # Every sample month must be in the Ken French file.
    missing = ours.join(ff, on="yyyymm", how="anti").height
    check(missing == 0, f"{missing} sample months missing in Ken French breakpoints")
    cmp = ours.join(ff, on="yyyymm")
    # Each compared bound must be a finite number above zero (needed for the logs).
    for c in ["nyse_p20", "nyse_p50", "nyse_p80", "ff_p20", "ff_p50", "ff_p80"]:
        bad = cmp.filter(~(pl.col(c).is_finite() & (pl.col(c) > 0)).fill_null(False)).height
        check(bad == 0, f"{bad} months with a missing or non-positive {c}")
    out = {"months": cmp.height}
    for p in ["p20", "p50", "p80"]:
        rel = (pl.col(f"nyse_{p}") / pl.col(f"ff_{p}") - 1).abs()
        out[p] = {
            "corr_log": cmp.select(pl.corr(pl.col(f"nyse_{p}").log(), pl.col(f"ff_{p}").log())).item(),
            "median_abs_rel_diff": cmp.select(rel.median()).item(),
            "p95_abs_rel_diff": cmp.select(rel.quantile(0.95)).item(),
        }
    out["n_ratio_median"] = cmp.select((pl.col("n") / pl.col("ff_n")).median()).item()
    report["vs_ken_french_breakpoints_from_1963"] = out
    check(out["p50"]["corr_log"] > 0.99, f"NYSE median far from Ken French: {out['p50']}")


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/4_crsp_size.py"}
    df, run_id = read_verified(UNIVERSE, UNIVERSE_REPORT)
    report["inputs"] = {UNIVERSE.name: {"from_run": run_id}}

    cutoffs = nyse_size_cutoffs(df)
    df = classify_size(df, cutoffs)
    checks(df, cutoffs, report)

    publish(
        {PROCESSED / "nyse_cutoffs.parquet": cutoffs, PROCESSED / "crsp_panel.parquet": df},
        report, PROCESSED / "crsp_size_report.json",
    )
    print(f"crsp_size: {cutoffs.height} months of NYSE breakpoints; panel {df.height:,} rows. "
          "Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
