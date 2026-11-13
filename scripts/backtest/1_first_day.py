"""Backtest, step 1: could an order be filled on the first trading day of the month?

Rule D13 (ProjectJournal.md, section 8.4): an order formed with the data of
month t is filled at the close of the first trading day of month t+1 only if,
that day, the stock has a trade price (prc_flag = TR), a positive volume, and
no delisting on or before it. A known first-day return does not prove that a
trade was possible; this table is the proof used by the backtest.

The first trading day of a month is the first date of the daily file in that
month, all stocks together (market calendar), as for ret_d1 at step 9.

No return is read here. The closing price of the day is kept, unadjusted, only
to convert an amount traded into a number of shares (commission stress, D15).

Input:  data/processed/crsp_daily_min.parquet (hash checked against its json)
Output: first_day_fills.parquet   one row per stock present on the first
            trading day of a month: permno, yyyymm, date, fill_ok, prc_d1
        first_day_fills_report.json

Run from Project/:  python scripts/backtest/1_first_day.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import PROCESSED, CheckError, check, check_unchanged, file_stamps, publish, sha256  # noqa: E402

DAILY = PROCESSED / "crsp_daily_min.parquet"
DAILY_JSON = PROCESSED / "crsp_daily_min.parquet.json"


def main() -> None:
    c = pl.col
    report: dict = {"script": "scripts/backtest/1_first_day.py", "inputs": {}}
    report["script_sha256"] = sha256(Path(__file__))
    expected = json.loads(DAILY_JSON.read_text(encoding="utf-8"))["parquet_sha256"]
    stamps = file_stamps([DAILY])
    check(sha256(DAILY) == expected, "crsp_daily_min.parquet does not match its json")
    report["inputs"][DAILY.name] = {"sha256": expected}

    scan = pl.scan_parquet(DAILY)
    ym = (c("date").dt.year() * 100 + c("date").dt.month()).cast(pl.Int32)
    first = scan.select(ym.alias("yyyymm"), "date").group_by("yyyymm").agg(c("date").min()).sort("yyyymm").collect()
    check(first["yyyymm"].is_unique().all() and first.height >= 780, f"{first.height} months in the daily file")
    rows = (scan.filter(c("date").is_in(first["date"].implode()))
            .select("permno", ym.alias("yyyymm"), "date", "prc_flag", "del_flag", "vol", "prc").collect())
    check_unchanged(stamps)
    # The raw daily file holds exact duplicate rows (step 9 drops them the same
    # way): drop them, then a stock must have one row a day.
    n0 = rows.height
    rows = rows.unique().sort("yyyymm", "permno")
    report["exact_duplicate_rows_dropped"] = n0 - rows.height
    check(rows.select("permno", "yyyymm").is_unique().all(), "A stock has two rows on a first trading day")
    check(rows.join(first, on=["yyyymm", "date"], how="anti").height == 0, "A row is not on a first trading day")

    report["flags_on_first_days"] = {
        "prc_flag": {str(k): v for k, v in rows["prc_flag"].value_counts().sort("prc_flag").iter_rows()},
        "del_flag": {str(k): v for k, v in rows["del_flag"].value_counts().sort("del_flag").iter_rows()}}
    # del_flag = N: no delisting on that row. A stock delisted before the day has
    # no row and is therefore not in the table: the backtest reads "no row" as
    # "not filled".
    out = rows.select(
        "permno", "yyyymm", "date",
        fill_ok=((c("prc_flag") == "TR") & (c("vol") > 0) & (c("del_flag") == "N")).fill_null(False),
        prc_d1=pl.when(c("prc").abs() > 0).then(c("prc").abs()),
    ).sort("yyyymm", "permno")
    check(out["fill_ok"].null_count() == 0, "fill_ok is missing on a row")
    # Hand checks of the rule on the rows themselves.
    j = rows.join(out, on=["permno", "yyyymm"])
    check(j.filter(c("fill_ok") & ((c("prc_flag") != "TR") | (c("vol") <= 0) | c("vol").is_null()
                                   | (c("del_flag") != "N"))).height == 0, "A fill breaks the rule D13")
    check(j.filter(~c("fill_ok") & (c("prc_flag") == "TR") & (c("vol") > 0) & (c("del_flag") == "N")).height == 0,
          "A row that meets D13 is not a fill")
    check(out.filter(c("fill_ok") & c("prc_d1").is_null()).height == 0, "A fill has no price")

    by_decade = (out.with_columns(decade=c("yyyymm") // 1000 * 10).group_by("decade")
                 .agg(rows=pl.len(), fills=c("fill_ok").sum()).sort("decade"))
    report["rows"] = out.height
    report["months"] = [int(first["yyyymm"][0]), int(first["yyyymm"][-1]), first.height]
    report["share_fill_ok_by_decade"] = {str(r["decade"]): round(r["fills"] / r["rows"], 4) for r in by_decade.to_dicts()}
    publish({PROCESSED / "first_day_fills.parquet": out}, report, PROCESSED / "first_day_fills_report.json")
    print(f"first_day_fills: {out.height:,} stock-months, {first.height} months "
          f"({first['yyyymm'][0]} to {first['yyyymm'][-1]}).")
    print("Share of rows where an order can be filled, by decade:", report["share_fill_ok_by_decade"])
    print("Flags on first days:", report["flags_on_first_days"])
    print(f"Run {report['run_id']}. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
