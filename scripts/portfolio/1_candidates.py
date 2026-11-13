"""Portfolio, step 1: the candidates of each month (top decile of the forecasts).

This step uses the information of month t only. It says which stocks may be
bought or kept; it holds no position and reads no return. The weights really
held are computed by the backtest, because they depend on the orders that were
filled (rules D13 and D21).

Reference code: the NYSE breakpoints follow the convention already used at step
4 of the cleaning (JKP nyse_size_cutoffs: discrete quantile over the eligible
NYSE stocks, a stock at or above the value is in the group).

Rules (SignalSpec.md, section 6, "Portfolio construction", decided by the
project owner on 2026-11-13 before any result):
- Two universes (D19): all eligible stocks; eligible stocks at or above the
  NYSE 20th percentile of market equity (size groups small, large and mega).
- Breakpoints of the forecast: the 90th and 80th percentiles of the forecasts
  of the eligible NYSE stocks of the universe, month by month. Discrete
  quantile: with n NYSE stocks sorted from the lowest forecast, the value of
  rank ceil(q x n).
  Why NYSE stocks: with breakpoints over all stocks the top decile is made of
  the smallest stocks (most of the names, a few per cent of the market value),
  which a fund of USD 100 million cannot hold (Fama and French 2008; Hou, Xue
  and Zhang 2020; Avramov, Cheng and Metzker 2023 for the same criticism of
  machine-learning forecasts). GKX sort on all stocks: a declared difference.
- top10: forecast at or above the 90th percentile. top20: at or above the 80th.
  Stocks tied with the breakpoint are all in: no tie is broken here.
- Buffer (D21), applied by the backtest on the book really held: a stock not
  held is bought when it is in top10; a stock held is kept while it is in top20.
- A stock with no observed characteristic at all (every missing flag at 1)
  cannot start a purchase (D18): can_start is false for it.
- One set of flags for each model (pred_gbrt, pred_ridge) and each universe.

Before the strategy is frozen this script reads the development file only
(return years 1981-1992). The test file is refused unless the freeze is
recorded in resources/strategy_freeze.json.

Inputs:  predictions_<version>_<sample>.parquet (hash checked against the
         report of the predictions), crsp_panel_acc.parquet, signal_ranks.parquet
Outputs: portfolio_candidates_<version>_<sample>.parquet
             permno, yyyymm, eom, me, nyse, universe_large, can_start,
             top10_<model>_<universe>, top20_<model>_<universe>
         portfolio_breakpoints_<version>_<sample>.parquet
             one row per month, model and universe: NYSE stocks used, the two
             breakpoints, distinct forecast values, stocks tied with each
             breakpoint, stocks and NYSE stocks in top10 and top20
         portfolio_candidates_<version>_<sample>_report.json

Run from Project/:
    python scripts/portfolio/1_candidates.py --selftest
    python scripts/portfolio/1_candidates.py --version A --sample development
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import (PROCESSED, PROJECT, CheckError, check, check_unchanged, file_stamps,  # noqa: E402
                   publish, read_verified, sha256)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backtest"))
import freeze_guard  # noqa: E402

PANEL = PROCESSED / "crsp_panel_acc.parquet"
PANEL_REPORT = PROCESSED / "accounting_availability_report.json"
RANKS = PROCESSED / "signal_ranks.parquet"
RANKS_REPORT = PROCESSED / "signal_panel_report.json"
SIGNAL_LIST = PROJECT / "resources" / "signal_list.csv"
FREEZE = PROJECT / "resources" / "strategy_freeze.json"
KEYS = ["permno", "yyyymm", "eom"]
MODELS = {"gbrt": "pred_gbrt", "ridge": "pred_ridge"}
UNIVERSES = ["all", "large"]              # large: at or above the NYSE 20th percentile of market equity
LARGE_GROUPS = ["small", "large", "mega"]
Q_BUY, Q_KEEP = 0.90, 0.80
MIN_NYSE = 100                            # fewer NYSE stocks in a month stops the script
# Months and return years that each sample must hold, whole.
EXPECTED = {"development": {"first_month": 198012, "last_month": 199211, "months": 144, "years": (1981, 1992)},
            "test": {"first_month": 199212, "last_month": 202511, "months": 396, "years": (1993, 2025)}}


def breakpoint_disc(values: np.ndarray, q: float) -> float:
    """Discrete quantile: the value of rank ceil(q x n) among the n values sorted upwards."""
    v = np.sort(values)
    return float(v[math.ceil(q * v.size) - 1])


def flags(month: np.ndarray, pred: np.ndarray, nyse: np.ndarray, member: np.ndarray
          ) -> tuple[np.ndarray, np.ndarray, list[tuple]]:
    """
    Description:
        top10 and top20 of one model in one universe.
    Inputs:
        month   month of each row, sorted upwards.
        pred    forecast of each row.
        nyse    True for an eligible NYSE stock.
        member  True if the row is in the universe.
    Output:
        top10, top20 (False outside the universe), and one record per month:
        NYSE stocks used, the two breakpoints, and what shows the effect of
        equal forecasts (distinct values, stocks tied with each breakpoint,
        stocks and NYSE stocks in each group).
    """
    check(bool((np.diff(month) >= 0).all()), "The rows are not sorted by month")
    check(bool(np.isfinite(pred).all()), "A forecast is not finite")
    top10, top20, table = np.zeros(pred.size, bool), np.zeros(pred.size, bool), []
    starts = np.flatnonzero(np.r_[True, np.diff(month) != 0])
    for a, b in zip(starts, np.r_[starts[1:], pred.size]):
        rows = slice(a, b)
        base = pred[rows][nyse[rows] & member[rows]]
        check(base.size >= MIN_NYSE, f"{int(month[a])}: {base.size} NYSE stocks for the breakpoints")
        p90, p80 = breakpoint_disc(base, Q_BUY), breakpoint_disc(base, Q_KEEP)
        top10[rows] = member[rows] & (pred[rows] >= p90)
        top20[rows] = member[rows] & (pred[rows] >= p80)
        inside, ny = member[rows], nyse[rows] & member[rows]
        table.append({
            "yyyymm": int(month[a]), "nyse_stocks": int(base.size), "breakpoint_90": p90, "breakpoint_80": p80,
            "universe_stocks": int(inside.sum()),
            "distinct_forecasts": int(np.unique(pred[rows][inside]).size),
            "tied_with_breakpoint_90": int((inside & (pred[rows] == p90)).sum()),
            "tied_with_breakpoint_80": int((inside & (pred[rows] == p80)).sum()),
            "top10_stocks": int(top10[rows].sum()), "top20_stocks": int(top20[rows].sum()),
            "top10_nyse_stocks": int((top10[rows] & ny).sum()), "top20_nyse_stocks": int((top20[rows] & ny).sum())})
    return top10, top20, table


def build(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """
    Description:
        The flags of every model and universe.
    Input:
        permno, yyyymm, eom, me, nyse, size_grp, can_start, pred_gbrt, pred_ridge;
        one row per eligible stock-month.
    Output:
        The candidate table, sorted by (yyyymm, permno); the table of the
        breakpoints by month, model and universe; counts for the report.
    """
    check(df.select("permno", "yyyymm").is_unique().all(), "Duplicate stock-month")
    df = df.sort("yyyymm", "permno")
    month = df["yyyymm"].to_numpy()
    nyse = df["nyse"].to_numpy()
    member = {"all": np.ones(df.height, bool), "large": df["size_grp"].is_in(LARGE_GROUPS).to_numpy()}
    out = df.select(*KEYS, "me", "nyse", pl.Series("universe_large", member["large"]), "can_start")
    stats, tables = {}, []
    for model, col in MODELS.items():
        pred = df[col].to_numpy()
        for u in UNIVERSES:
            t10, t20, table = flags(month, pred, nyse, member[u])
            check(bool((~t10 | t20).all()), f"{model} {u}: a stock is in top10 and not in top20")
            out = out.with_columns(pl.Series(f"top10_{model}_{u}", t10), pl.Series(f"top20_{model}_{u}", t20))
            t = pl.DataFrame(table).with_columns(model=pl.lit(model), universe=pl.lit(u))
            tables.append(t)
            share10 = t["top10_nyse_stocks"] / t["nyse_stocks"]
            share20 = t["top20_nyse_stocks"] / t["nyse_stocks"]
            stats[f"{model}_{u}"] = {
                "months": t.height, "nyse_stocks_min": int(t["nyse_stocks"].min()),
                "nyse_stocks_median": float(t["nyse_stocks"].median()),
                "top10_stocks_min": int(t["top10_stocks"].min()), "top10_stocks_median": float(t["top10_stocks"].median()),
                "top10_stocks_max": int(t["top10_stocks"].max()),
                "top10_share_of_the_universe_median": float((t["top10_stocks"] / t["universe_stocks"]).median()),
                "top10_nyse_share_median": float(share10.median()), "top10_nyse_share_max": float(share10.max()),
                "top20_nyse_share_max": float(share20.max()),
                "distinct_forecasts_min": int(t["distinct_forecasts"].min()),
                "distinct_forecasts_median": float(t["distinct_forecasts"].median()),
                "tied_with_breakpoint_90_max": int(t["tied_with_breakpoint_90"].max()),
                "tied_with_breakpoint_90_share_of_the_universe_max": float(
                    (t["tied_with_breakpoint_90"] / t["universe_stocks"]).max()),
                "top10_share_of_the_universe_max": float((t["top10_stocks"] / t["universe_stocks"]).max()),
                "months_where_the_two_breakpoints_are_equal": int((t["breakpoint_90"] == t["breakpoint_80"]).sum()),
                "months_where_top10_equals_top20": int((t["top10_stocks"] == t["top20_stocks"]).sum())}
    bp = pl.concat(tables).select("yyyymm", "model", "universe", pl.exclude("yyyymm", "model", "universe")).with_columns(
        pl.col("yyyymm").cast(pl.Int32)).sort("model", "universe", "yyyymm")
    return out, bp, stats


# --------------------------------------------------------------------- real data

def run(version: str, sample: str, retry: bool = False) -> None:
    c = pl.col
    reservation = None
    check(sample in EXPECTED, f"Unknown sample {sample}")
    report: dict = {"script": "scripts/portfolio/1_candidates.py", "version": version, "sample": sample, "inputs": {}}
    report["script_sha256"] = sha256(Path(__file__))
    if sample == "test":
        # Code, inputs and forecasts must be those of the freeze; the outputs must
        # not exist; the opening is logged before anything is read (freeze_guard.py).
        report["freeze"] = freeze_guard.require_freeze(
            "scripts/portfolio/1_candidates.py", version,
            [PROCESSED / f"portfolio_candidates_{version}_test.parquet", PROCESSED / f"portfolio_breakpoints_{version}_test.parquet",
             PROCESSED / f"portfolio_candidates_{version}_test_report.json"])
        reservation = freeze_guard.reserve("candidates", version, report["freeze"], retry)
    name = f"predictions_{version}_{sample}.parquet"
    pred_report = PROCESSED / f"predictions_{version}_report.json"
    if sample == "test":                                    # the bytes read are the bytes of the freeze
        pred = freeze_guard.read_frozen(PROCESSED / name, report["freeze"]["predictions_test_sha256"])
        report["inputs"][name] = {"sha256": report["freeze"]["predictions_test_sha256"]}
    else:
        pred, run_id = read_verified(PROCESSED / name, pred_report)
        report["inputs"][name] = {"from_run": run_id,
                                  "sha256": json.loads(pred_report.read_text(encoding="utf-8"))["outputs"][name]}
    check(pred.select("permno", "yyyymm").is_unique().all(), "Duplicate stock-month in the forecasts")
    check(pred["sample"].unique().to_list() == [sample], "The forecast file holds another sample")
    # The sample must be whole: its first and last months and every month between.
    want = EXPECTED[sample]
    years = (pred["return_year"].min(), pred["return_year"].max())
    lo, hi = pred["yyyymm"].min(), pred["yyyymm"].max()
    check(years == want["years"], f"Return years {years}, expected {want['years']} for the sample {sample}")
    # Row by row: the return year is the year of the month after the formation month.
    check(pred.filter(pl.col("return_year") != (pl.col("yyyymm") // 100 + (pl.col("yyyymm") % 100 == 12).cast(pl.Int32))
                      ).height == 0, "A return year is not the year of the month after its formation month")
    check((lo, hi, pred["yyyymm"].n_unique()) == (want["first_month"], want["last_month"], want["months"]),
          f"Months {lo} to {hi} ({pred['yyyymm'].n_unique()}), expected {want['first_month']} to "
          f"{want['last_month']} ({want['months']})")

    earlier = json.loads(PANEL_REPORT.read_text(encoding="utf-8"))
    stamps = file_stamps([PANEL, RANKS])
    check(sha256(PANEL) == earlier["outputs"][PANEL.name], "The panel does not match its report")
    report["inputs"][PANEL.name] = {"sha256": earlier["outputs"][PANEL.name], "from_run": earlier["run_id"]}
    # Columns of month t only; no return is read.
    panel = (pl.scan_parquet(PANEL).filter(c("eligible") & c("yyyymm").is_between(lo, hi))
             .select("permno", "yyyymm", "me", c("crsp_nyse").alias("nyse"), "size_grp").collect())

    # A stock can start a purchase if at least one characteristic of the version is observed.
    earlier = json.loads(RANKS_REPORT.read_text(encoding="utf-8"))
    check(sha256(RANKS) == earlier["outputs"][RANKS.name], "signal_ranks does not match its report")
    report["inputs"][RANKS.name] = {"sha256": earlier["outputs"][RANKS.name], "from_run": earlier["run_id"]}
    names = [r["characteristic"] for r in csv.DictReader(open(SIGNAL_LIST, encoding="utf-8"))
             if r["version"] == "A" or version == "B"]
    check(len(names) == {"A": 59, "B": 194}[version], f"{len(names)} characteristics for version {version}")
    known = (pl.scan_parquet(RANKS).filter(c("yyyymm").is_between(lo, hi))
             .select("permno", "yyyymm",
                     n_observed=pl.sum_horizontal([(c(f"{n}_miss") == 0).cast(pl.Int32) for n in names])).collect())
    check_unchanged(stamps)

    df = pred.join(panel, on=["permno", "yyyymm"], how="left", validate="1:1").join(
        known, on=["permno", "yyyymm"], how="left", validate="1:1")
    check(df.height == pred.height, "A join changed the number of rows")
    check(df.height == panel.height, "The forecast rows are not exactly the eligible stock-months of the period")
    for col in ("me", "nyse", "size_grp", "n_observed", "pred_gbrt", "pred_ridge"):
        check(df[col].null_count() == 0, f"{col} is missing on a forecast row")
    check(df.filter(c("me") <= 0).height == 0 and df.filter(~c("pred_gbrt").is_finite() | ~c("pred_ridge").is_finite()).height == 0,
          "A market equity is not positive or a forecast is not finite")
    df = df.with_columns(can_start=c("n_observed") > 0)

    out, bp, stats = build(df)
    check(out.select(KEYS).equals(pred.sort("yyyymm", "permno").select(KEYS)), "The keys are not those of the forecasts")
    check(bp.height == want["months"] * len(MODELS) * len(UNIVERSES), "The breakpoint table has a month missing")
    # Each month alone gives the same flags: no row of another month is used.
    for ym in (lo, out["yyyymm"].unique().sort()[out["yyyymm"].n_unique() // 2], hi):
        alone, _, _ = build(df.filter(c("yyyymm") == ym))
        check(alone.equals(out.filter(c("yyyymm") == ym)), f"The flags of {ym} depend on other months")
    # Second route for one month, by a plain sort in Python.
    ym = out["yyyymm"].unique().sort()[out["yyyymm"].n_unique() // 3]
    m = df.filter(c("yyyymm") == ym).sort("permno")
    for model, col in MODELS.items():
        base = sorted(m.filter(c("nyse"))[col].to_list())
        cut = base[math.ceil(0.9 * len(base)) - 1]
        ref = [v >= cut for v in m[col].to_list()]
        check(ref == out.filter(c("yyyymm") == ym).sort("permno")[f"top10_{model}_all"].to_list(),
              f"Second route for {model} at {ym} failed")

    report["rows"] = out.height
    report["months"] = [int(lo), int(hi)]
    report["cannot_start_a_purchase"] = int((~out["can_start"]).sum())
    report["by_model_and_universe"] = stats
    target = PROCESSED / f"portfolio_candidates_{version}_{sample}.parquet"
    publish({target: out, PROCESSED / f"portfolio_breakpoints_{version}_{sample}.parquet": bp}, report,
            PROCESSED / f"portfolio_candidates_{version}_{sample}_report.json")
    if reservation is not None:
        freeze_guard.finish(reservation, PROCESSED / f"portfolio_candidates_{version}_{sample}_report.json")
    print(f"{target.name}: {out.height:,} stock-months, {lo} to {hi}; "
          f"{report['cannot_start_a_purchase']} stock-months cannot start a purchase.")
    for key, s in stats.items():
        print(f"  {key}: top 10 % holds {s['top10_stocks_median']:.0f} stocks in the median month "
              f"({s['top10_stocks_min']} to {s['top10_stocks_max']}), {s['top10_share_of_the_universe_median']:.1%} of "
              f"the universe; NYSE share at most {s['top10_nyse_share_max']:.1%}; distinct forecasts at least "
              f"{s['distinct_forecasts_min']}; at most {s['tied_with_breakpoint_90_max']} stocks tied with the "
              f"breakpoint; top 10 % = top 20 % in {s['months_where_top10_equals_top20']} months")
    print(f"Run {report['run_id']}. Report saved.")


# ------------------------------------------------------------------ synthetic tests

def selftest() -> None:
    """Hand-written cases and random numbers: no project data is read."""
    global MIN_NYSE
    keep, MIN_NYSE = MIN_NYSE, 1
    try:
        # 1) The discrete quantile, by hand: ten values, rank ceil(0.9 x 10) = 9 and ceil(0.8 x 10) = 8.
        v = np.array([5.0, 1, 9, 3, 7, 2, 10, 4, 8, 6])
        check(breakpoint_disc(v, 0.9) == 9.0 and breakpoint_disc(v, 0.8) == 8.0, "selftest: discrete quantile")
        check(breakpoint_disc(np.arange(1.0, 1301), 0.9) == 1170.0, "selftest: discrete quantile with 1,300 values")

        # 2) One month by hand. NYSE forecasts 1..10: breakpoints 9 and 8. Stocks
        #    off the NYSE do not move the breakpoints but are judged against them.
        month = np.full(14, 200001)
        pred = np.array([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 9.5, 8.0, 0.5, 100.0])
        nyse = np.array([True] * 10 + [False] * 4)
        t10, t20, table = flags(month, pred, nyse, np.ones(14, bool))
        got = [(r["yyyymm"], r["nyse_stocks"], r["breakpoint_90"], r["breakpoint_80"]) for r in table]
        check(got == [(200001, 10, 9.0, 8.0)], f"selftest: breakpoints {got}")
        check((table[0]["tied_with_breakpoint_90"], table[0]["top10_stocks"], table[0]["top10_nyse_stocks"],
               table[0]["distinct_forecasts"]) == (1, 4, 2, 13), f"selftest: diagnostics of the month {table[0]}")
        check(t10.tolist() == [False] * 8 + [True, True, True, False, False, True], f"selftest: top10 {t10.tolist()}")
        check(t20.tolist() == [False] * 7 + [True, True, True, True, True, False, True], f"selftest: top20 {t20.tolist()}")
        # A tie with the breakpoint is in, whatever its position.
        tied = np.array([1.0, 2, 3, 4, 5, 6, 7, 9, 9, 9, 9, 8.0, 0.5, 100.0])
        t10b, _, tb = flags(month, tied, nyse, np.ones(14, bool))
        check(tb[0]["breakpoint_90"] == 9.0 and int(t10b.sum()) == 5 and tb[0]["tied_with_breakpoint_90"] == 4,
              "selftest: stocks tied with the breakpoint are not all in")

        # 3) The universe: stocks outside it neither move the breakpoints nor get a flag.
        member = np.array([True] * 5 + [False] * 5 + [True] * 4)
        t10c, t20c, tc = flags(month, pred, nyse, member)
        check((tc[0]["nyse_stocks"], tc[0]["breakpoint_90"], tc[0]["breakpoint_80"], tc[0]["universe_stocks"])
              == (5, 5.0, 4.0, 9), f"selftest: breakpoints of the universe {tc}")
        check(not t10c[5:10].any() and t10c[4] and t10c[10] and t20c[3], "selftest: flags of the universe")

        # 4) Random numbers through build(): two months, both models, both universes.
        rng = np.random.default_rng(3)
        n = 600
        df = pl.DataFrame({
            "permno": np.tile(np.arange(n), 2), "yyyymm": np.repeat([200001, 200002], n).astype(np.int32),
            "eom": [None] * (2 * n), "me": rng.lognormal(5, 2, 2 * n),
            "nyse": rng.uniform(size=2 * n) < 0.4,
            "size_grp": rng.choice(["nano", "micro", "small", "large", "mega"], 2 * n),
            "can_start": np.ones(2 * n, bool),
            "pred_gbrt": np.round(rng.standard_normal(2 * n), 1),      # rounded: many ties, as with trees
            "pred_ridge": rng.standard_normal(2 * n)})
        out, bp, stats = build(df)
        check(bp.height == 2 * 2 * 2, "selftest: rows of the breakpoint table")
        # Columns passed through, and the names of the rules written here again.
        j = out.join(df.select("permno", "yyyymm", pl.col("me").alias("me0"), pl.col("nyse").alias("nyse0"), "size_grp"),
                     on=["permno", "yyyymm"])
        check(j.height == out.height and j.filter((pl.col("me") != pl.col("me0")) | (pl.col("nyse") != pl.col("nyse0"))
                                                  ).height == 0, "selftest: me or nyse is not passed as it is")
        check(j.filter(pl.col("universe_large") != pl.col("size_grp").is_in(["small", "large", "mega"])).height == 0,
              "selftest: universe_large is not the size groups small, large and mega")
        # Rows given in another order: same table.
        mixed, _, _ = build(df.sample(fraction=1.0, shuffle=True, seed=5))
        check(mixed.equals(out), "selftest: the order of the rows changes the result")
        for ym in (200001, 200002):
            part = df.filter(pl.col("yyyymm") == ym).sort("permno")
            res = out.filter(pl.col("yyyymm") == ym).sort("permno")
            for model, col in (("gbrt", "pred_gbrt"), ("ridge", "pred_ridge")):
                for u in ("all", "large"):
                    inside = [u == "all" or g in ("small", "large", "mega") for g in part["size_grp"].to_list()]
                    base = sorted(p_ for p_, ny, ins in zip(part[col].to_list(), part["nyse"].to_list(), inside) if ny and ins)
                    for q, name in ((0.9, "top10"), (0.8, "top20")):
                        cut = base[math.ceil(q * len(base)) - 1]
                        ref = [ins and p_ >= cut for p_, ins in zip(part[col].to_list(), inside)]
                        check(ref == res[f"{name}_{model}_{u}"].to_list(), f"selftest: {name} {model} {u} {ym}")
        # 5) Changing the rows of another month, or the forecasts of stocks off
        #    the NYSE that stay below the breakpoint, changes nothing.
        other = df.with_columns(pred_ridge=pl.when(pl.col("yyyymm") == 200002).then(-pl.col("pred_ridge"))
                                .otherwise(pl.col("pred_ridge")))
        out2, _, _ = build(other)
        same = out.filter(pl.col("yyyymm") == 200001).equals(out2.filter(pl.col("yyyymm") == 200001))
        check(same and not out.equals(out2), "selftest: a month depends on another month, or the test cannot fail")
        # The NYSE flag matters: with every stock treated as NYSE the flags change.
        out3, _, _ = build(df.with_columns(nyse=pl.lit(True)))
        check(not out.equals(out3), "selftest: the NYSE flag has no effect")
        # A stock off the NYSE whose forecast changes moves no other stock's flags.
        off = (~pl.col("nyse")) & (pl.col("permno") == df.filter(~pl.col("nyse"))["permno"][0])
        out4, _, _ = build(df.with_columns(pred_ridge=pl.when(off).then(99.0).otherwise(pl.col("pred_ridge"))))
        others = pl.col("permno") != df.filter(~pl.col("nyse"))["permno"][0]
        check(out4.filter(others).equals(out.filter(others)), "selftest: a stock off the NYSE moves the breakpoints")
        # Forecasts all equal: every stock of the universe is in, and the table says so.
        flat, bpf, _ = build(df.with_columns(pred_gbrt=pl.lit(0.5)))
        check(bool(flat["top10_gbrt_all"].all()) and bpf.filter((pl.col("model") == "gbrt"))["distinct_forecasts"].max() == 1,
              "selftest: equal forecasts are not all in, or not reported")
        # 6) Too few NYSE stocks stops the script.
        MIN_NYSE = keep
        try:
            flags(month, pred, nyse, np.ones(14, bool))
            stopped = False
        except CheckError:
            stopped = True
        check(stopped, "selftest: a month with ten NYSE stocks is accepted")
    finally:
        MIN_NYSE = keep
    print("selftest passed: discrete quantile, hand cases, ties, universes, independence of the months.")
    print("No project data was read.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=["A", "B"])
    ap.add_argument("--sample", choices=["development", "test"], default="development")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--retry", action="store_true", help="test sample only: run again a step whose attempt did not finish")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    check(args.version is not None, "Give --version A or --version B (or --selftest)")
    run(args.version, args.sample, args.retry)


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
