"""Signals, script 1: the market characteristics (version A of the signal list).

Reference code (Resources/reference_code/jkp-data, commit b5695ea, aux_functions.py):
    expand, market_chars_monthly -> month grid per stock, count, return indices
    mom_rev_cols        -> ret_j_i = ri(t-i) / ri(t-j) - 1
    seasonality         -> seas_a_b an / na
    eqnpo_cols          -> ln(ri / ri_h) - ln(me / me_h)
    chcsho_cols         -> shares x share factor, change over h months
    prepare_crsp_sf     -> div_tot, the dividend per share of the month
    div_cols            -> dividends of h months over the market equity
    prep_data_factor_regs, capm, market_beta -> beta_60m, ivol_capm_60m
    finish_daily_chars  -> rmax5_rvol_21d = rmax5_21d / rvol_252d

Deviations from JKP (SignalSpec.md, section 4.1):
- One source of returns: ret_x = ret where ret_signal_ok is true, missing
  otherwise. The mask is applied on the source row, BEFORE any cumulative
  product. JKP masks after its indices are built, which would let a delisting
  return into an index. With one currency, JKP's two indices (ri, ri_x) are the
  same series here.
- ret and retx are masked the same way before the dividend per share.
- Decision D24 (after the audits of 2026-11-12): a missing month stays missing.
  JKP carries its return index over a month without a return (as if the return
  were zero) and sums the dividends of the months that exist. Here a momentum,
  reversal or net-payout window needs a usable return in EVERY month it
  compounds, and a dividend yield over h months needs the h monthly amounts (a
  known amount of zero counts). Otherwise the characteristic is missing.
- The market and the risk-free rate come from Ken French (JKP builds its own
  market). The winsorisation of the monthly excess return before the 60-month
  regression is done on our cross-section (all CRSP stocks of the panel); JKP's
  cross-section is its own universe.
- The share factor comes from the daily file on the date of the monthly row
  (cfacshr_mth, the local factor of step 9, built from past events only); it is
  only used as a ratio between two dates of a stock.
- The panel has no missing month inside a stock, and the script stops if one
  appears: JKP takes the previous ROW for the dividend per share and the grid
  takes the previous MONTH; with no gap the two are the same.

Inputs (data/processed/, hashes checked against the report of their step):
    crsp_panel_acc.parquet, crsp_daily_agg.parquet, ff_factors_monthly.parquet
Outputs:
    signals_price.parquet        one row per (permno, eom) of the panel
    signals_price_report.json    checks, coverage and hashes (written last)

Run from Project/:  python scripts/signals/1_price_signals.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import (PROCESSED, PROJECT, CheckError, check, check_unchanged, file_stamps,  # noqa: E402
                   publish, sha256)

PANEL = PROCESSED / "crsp_panel_acc.parquet"
PANEL_REPORT = PROCESSED / "accounting_availability_report.json"
DAILY = PROCESSED / "crsp_daily_agg.parquet"
DAILY_REPORT = PROCESSED / "crsp_daily_agg_report.json"
FACTORS = PROCESSED / "ff_factors_monthly.parquet"
FACTORS_REPORT = PROCESSED / "crsp_excess_report.json"
SIGNAL_LIST = PROJECT / "resources" / "signal_list.csv"
DICTIONARY = PROJECT / "resources" / "data_dictionary.csv"

PANEL_COLS = ["permno", "yyyymm", "eom", "ret", "retx", "ret_exc", "ret_signal_ok", "me", "prc",
              "shrout", "eligible"]
DAILY_READ = ["rvol_21d", "rvol_252d", "beta_252d", "dolvol_126d", "bidaskhl_21d", "rmax1_21d",
              "rmax5_21d", "rvolhl_21d", "ami_126d", "dolvol_var_126d", "prc_highprc_252d"]
DAILY_COLS = ["permno", "yyyymm", "cfacshr_mth"] + DAILY_READ

# JKP market_chars_monthly: [i, j] gives ret_j_i.
MOM = [(0, 1), (0, 2), (0, 3), (1, 3), (0, 6), (1, 6), (0, 9), (1, 9), (0, 12), (1, 12),
       (7, 12), (1, 18), (1, 24), (12, 24), (1, 36), (12, 36), (12, 48), (1, 48), (1, 60),
       (12, 60), (36, 60)]
SEAS = [(1, 1), (2, 5), (6, 10), (11, 15), (16, 20)]
LAGS = [1, 3, 6, 12]          # eqnpo, chcsho and dividend horizons
BETA_N, BETA_MIN = 60, 36     # JKP market_beta(..., 60, 36)
RET_MIN_STD = 1e-6            # JKP config: near-constant returns give no statistic
SMALL = 1e-5                  # JKP: eqnpo and dividend yields below this are set to 0
TINY = 1e-9                   # a share change below this is rounding of the share factor
SAMPLE_START = 196301
TRUNCATION_DATES = [197506, 199912, 201503]

# Acceptance cases recomputed by the auditor from the tables (audit of the
# signal list, 2026-11-12), tolerance 1e-8. 10028 has a missing month inside the
# momentum window (JKP convention: the index is carried over the gap).
# The cases of 12350 test the share factor where the CRSP level is exported as
# zero (November 2012) or with two digits only (February 2025, a 1-for-60 reverse
# split known from the dated event, whose factor has 6 decimals: tolerance 1e-5).
ACCEPTANCE = [
    (12350, 201211, "chcsho_1m", 0.0048579838),
    (12350, 201211, "div1m_me", 0.0),
    (10107, 201502, "chcsho_1m", 0.0),
    (10107, 201502, "div1m_me", 0.007113532497),
    (14593, 202008, "chcsho_1m", 0.0),
    (14593, 202008, "div1m_me", 0.001844562926),
    (10028, 201211, "seas_1_1an", -0.036129),
    (10107, 200103, "rmax5_rvol_21d", 1.3331031208),
    (12490, 200012, "ret_12_1", -0.1292730033),
    (12490, 200012, "ret_60_12", 3.8744844134),
    (12490, 200012, "seas_1_1an", 0.0405560000),
    (12490, 200012, "eqnpo_12m", 0.0317017933),
    (12490, 199905, "chcsho_1m", -0.0143735248),
    (12490, 199905, "div1m_me", 0.0011469246),
]
ACCEPTANCE_LOOSE = [(12350, 202502, "chcsho_1m", 0.05279795, 1e-5)]
# Must be missing: a month is missing in the window, outside the anniversary
# month (the anniversary mean exists, the mean of the other months does not).
# 10028, 2013-09: October 2012 has no return inside the momentum window. JKP
# gives -0.5128204249 (the index is carried over the gap); D24 makes it missing.
ACCEPTANCE_MISSING = [(10028, 201211, "seas_1_1na"), (10028, 201309, "ret_12_1")]


def read_checked(path: Path, report_path: Path, columns: list[str], report: dict) -> pl.DataFrame:
    """
    Description:
        Read some columns of an output of an earlier step, only if the file
        matches the report of that step.
    Steps:
        1) Size and modification time before; SHA-256 against the report.
        2) Read the columns; the file must not have changed meanwhile.
    Output:
        The table; the run id is recorded in the report.
    """
    earlier = json.loads(report_path.read_text(encoding="utf-8"))
    expected = earlier.get("outputs", {}).get(path.name)
    check(expected is not None, f"{path.name} is not listed in {report_path.name}")
    stamps = file_stamps([path])
    check(sha256(path) == expected, f"{path.name} does not match {report_path.name}: mixed runs?")
    df = pl.read_parquet(path, columns=columns)
    check_unchanged(stamps)
    report["inputs"][path.name] = {"sha256": expected, "from_run": earlier["run_id"]}
    return df


def lag(expr: pl.Expr, k: int) -> pl.Expr:
    # Value k months before, for the same stock. The grid is sorted by stock and
    # month with no missing month, so a plain shift is right when count > k.
    return pl.when(pl.col("count") > k).then(expr.shift(k))


def month_grid(panel: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Complete month grid per stock (JKP expand), with the masked returns.
    Steps:
        1) Month index mi; one row per stock and month from its first to its last.
        2) Left join of the panel; count = position in the grid, from 1.
        3) ret_x, retx_x, ret_exc_x: missing where ret_signal_ok is not true.
        4) ri: cumulative product of 1 + coalesce(ret_x, 0) (JKP ri and ri_x).
    Output:
        Grid sorted by (permno, mi).
    """
    p = panel.with_columns(mi=(pl.col("yyyymm") // 100 * 12 + pl.col("yyyymm") % 100).cast(pl.Int32))
    check(p.select("permno", "mi").is_unique().all(), "Duplicate stock-month in the panel")
    span = p.group_by("permno").agg(a=pl.col("mi").min(), b=pl.col("mi").max()).sort("permno")
    grid = (span.with_columns(mi=pl.int_ranges(pl.col("a"), pl.col("b") + 1, dtype=pl.Int32))
            .explode("mi").select("permno", "mi"))
    g = grid.join(p.with_columns(in_panel=pl.lit(True)), on=["permno", "mi"], how="left").sort("permno", "mi")
    check(g.height == grid.height, "The grid join changed the row count")
    check(g.height == p.height, f"{g.height - p.height} missing months inside stocks: the previous row "
                                f"is no longer the previous month")
    ok = pl.col("ret_signal_ok").fill_null(False)
    g = g.with_columns(
        in_panel=pl.col("in_panel").fill_null(False),
        count=pl.int_range(1, pl.len() + 1, dtype=pl.Int32).over("permno"),
        ret_x=pl.when(ok).then(pl.col("ret")),
        retx_x=pl.when(ok).then(pl.col("retx")),
        ret_exc_x=pl.when(ok).then(pl.col("ret_exc")),
    )
    # n_miss: months without a usable return so far (for the windows, D24).
    return g.with_columns(ri=(1 + pl.col("ret_x").fill_null(0.0)).cum_prod().over("permno"),
                          n_miss=pl.col("ret_x").is_null().cast(pl.Int32).cum_sum().over("permno"))


def momentum(i: int, j: int) -> pl.Expr:
    # JKP mom_rev_cols: return between months t-j and t-i from the index. D24: no
    # month without a usable return among the months compounded (t-j+1 to t-i).
    ok = ((lag(pl.col("ri"), j) != 0) & (pl.col("count") > j)
          & ((lag(pl.col("n_miss"), i) - lag(pl.col("n_miss"), j)) == 0))
    return pl.when(ok).then(lag(pl.col("ri"), i) / lag(pl.col("ri"), j) - 1).alias(f"ret_{j}_{i}")


def seasonality(a: int, b: int) -> list[pl.Expr]:
    # JKP seasonality: mean return of the anniversary months and of the other
    # months, years a to b back. Ordinary sums: one missing month gives no value.
    all_lags = list(range((a - 1) * 12, b * 12))
    ann_lags = list(range(a * 12 - 1, b * 12, 12))
    all_r, ann_r = pl.lit(0.0), pl.lit(0.0)
    for k in all_lags:
        all_r = all_r + pl.col("ret_x").shift(k)
    for k in ann_lags:
        ann_r = ann_r + pl.col("ret_x").shift(k)
    c1 = pl.col("count") >= b * 12      # then every lag stays inside the stock
    return [pl.when(c1).then(ann_r / len(ann_lags)).alias(f"seas_{a}_{b}an"),
            pl.when(c1).then((all_r - ann_r) / (len(all_lags) - len(ann_lags))).alias(f"seas_{a}_{b}na")]


def eqnpo(h: int) -> pl.Expr:
    # JKP eqnpo_cols: log growth of the return index minus log growth of market equity.
    ri_h, me_h = lag(pl.col("ri"), h), lag(pl.col("me"), h)
    # D24: a usable return in each of the h months.
    ok = ((pl.col("ri") > 0) & (ri_h > 0) & (pl.col("me") > 0) & (me_h > 0) & (pl.col("count") > h)
          & ((pl.col("n_miss") - lag(pl.col("n_miss"), h)) == 0))
    x = (pl.col("ri") / ri_h).log() - (pl.col("me") / me_h).log()
    return pl.when(ok).then(pl.when(x.abs() < SMALL).then(0.0).otherwise(x)).alias(f"eqnpo_{h}m")


def chcsho(h: int) -> pl.Expr:
    # JKP chcsho_cols: aux = shares x cumulative share factor (unchanged by a split).
    # The local share factor is a product of ratios, so an unchanged share count
    # can come out as 1e-14 instead of 0. A change below 1e-9 is set to 0 (project
    # rule): otherwise these values would leave the large tie at zero when ranked.
    aux_h = lag(pl.col("aux"), h)
    x = pl.when((aux_h != 0) & (pl.col("count") > h)).then(pl.col("aux") / aux_h - 1)
    return pl.when(x.abs() < TINY).then(0.0).otherwise(x).alias(f"chcsho_{h}m")


def dividends(h: int) -> pl.Expr:
    # JKP div_cols: dividend amounts of h months over the current market equity;
    # values below 1e-5 are set to 0. D24: the h monthly amounts must be known
    # (JKP takes the sum of those that exist).
    num = (pl.col("div1m") if h == 1
           else pl.col("div1m").rolling_sum(window_size=h, min_samples=h).over("permno"))
    x = pl.when((pl.col("count") >= h) & (pl.col("me") != 0)).then(num / pl.col("me"))
    return pl.when(x < SMALL).then(0.0).otherwise(x).alias(f"div{h}m_me")


def beta_60m(g: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Market beta and idiosyncratic volatility over 60 months (JKP market_beta).
    Steps:
        1) Base rows (prep_data_factor_regs): return known and not zero, excess
           return and market known.
        2) Excess return winsorised by month at the discrete 0.1 % and 99.9 %
           quantiles of the base rows.
        3) Sums over the last 60 months of the grid; at least 36 base rows; raw
           returns not near-constant (JKP capm and its guard).
        4) beta = cov / var(market); ivol = std of ret_exc - beta x market.
    Output:
        permno, mi, beta_60m, ivol_capm_60m (grid rows).
    """
    base = (pl.col("ret_x").is_not_null() & (pl.col("ret_x") != 0)
            & pl.col("ret_exc_x").is_not_null() & pl.col("mkt_excess").is_not_null())
    b = g.filter(base).select("permno", "mi", "ret_exc_x")
    n = pl.len()
    # DuckDB QUANTILE_DISC(x, q): the value at position ceil(q n), counted from 1.
    # Integer arithmetic, so that q n is never rounded.
    cut = b.group_by("mi").agg(
        lo=pl.col("ret_exc_x").sort().gather((n + 999) // 1000 - 1).first(),
        hi=pl.col("ret_exc_x").sort().gather((999 * n + 999) // 1000 - 1).first(),
    )
    d = g.select("permno", "mi", "ret_x", "ret_exc_x", "mkt_excess").join(cut, on="mi", how="left")
    d = d.sort("permno", "mi").with_columns(base=base).with_columns(
        r=pl.when(pl.col("base")).then(pl.max_horizontal("lo", pl.min_horizontal("ret_exc_x", "hi"))).otherwise(0.0),
        m=pl.when(pl.col("base")).then(pl.col("mkt_excess")).otherwise(0.0),
        raw=pl.when(pl.col("base")).then(pl.col("ret_x")).otherwise(0.0),
    )
    roll = lambda e: e.rolling_sum(window_size=BETA_N, min_samples=1).over("permno")
    d = d.with_columns(
        n=roll(pl.col("base").cast(pl.Float64)), s_r=roll(pl.col("r")), s_m=roll(pl.col("m")),
        s_rr=roll(pl.col("r") ** 2), s_mm=roll(pl.col("m") ** 2), s_rm=roll(pl.col("r") * pl.col("m")),
        s_raw=roll(pl.col("raw")), s_raw2=roll(pl.col("raw") ** 2),
    )
    var = lambda s1, s2: (pl.col(s2) - pl.col(s1) ** 2 / pl.col("n")) / (pl.col("n") - 1)
    cov = (pl.col("s_rm") - pl.col("s_r") * pl.col("s_m") / pl.col("n")) / (pl.col("n") - 1)
    ok = ((pl.col("n") > BETA_MIN - 0.5) & (var("s_raw", "s_raw2").clip(lower_bound=0).sqrt() > RET_MIN_STD)
          & (var("s_m", "s_mm") > 0))
    beta = cov / var("s_m", "s_mm")
    d = d.with_columns(beta_60m=pl.when(ok).then(beta)).with_columns(
        ivol_capm_60m=pl.when(ok).then(
            (var("s_r", "s_rr") - pl.col("beta_60m") ** 2 * var("s_m", "s_mm")).clip(lower_bound=0).sqrt()))
    return d.select("permno", "mi", "beta_60m", "ivol_capm_60m", pl.col("r").alias("ret_exc_w"),
                    pl.col("base").alias("beta_base"))


def compute(panel: pl.DataFrame, factors: pl.DataFrame, daily: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        All the market characteristics of the signal list, on the panel rows.
    Steps:
        1) Month grid and masked returns.
        2) Momentum and reversal, seasonality, equity net payout.
        3) Share changes and dividend yields from the share factor.
        4) Beta and idiosyncratic volatility over 60 months.
        5) Characteristics of step 9, and rmax5_21d / rvol_252d.
    Output:
        One row per (permno, yyyymm) of the panel, sorted.
    """
    g = month_grid(panel)
    g = g.join(daily, on=["permno", "yyyymm"], how="left")
    g = g.join(factors.select("yyyymm", "mkt_excess"), on="yyyymm", how="left").sort("permno", "mi")

    # Dividend per share of the month (JKP prepare_crsp_sf), on the panel rows:
    # (ret - retx) x previous price x factor / previous factor.
    cf_prev, prc_prev = lag(pl.col("cfacshr_mth"), 1), lag(pl.col("prc"), 1)
    g = g.with_columns(
        aux=pl.col("shrout") * pl.col("cfacshr_mth"),
        div_tot=pl.when(cf_prev != 0).then(
            (pl.col("ret_x") - pl.col("retx_x")) * prc_prev * (pl.col("cfacshr_mth") / cf_prev)),
    ).with_columns(div1m=pl.col("div_tot") * pl.col("shrout"))

    out = g.select(
        "permno", "yyyymm", "eom", "mi", "in_panel",
        *[momentum(i, j) for i, j in MOM],
        *[e for a, b in SEAS for e in seasonality(a, b)],
        *[eqnpo(h) for h in LAGS],
        *[chcsho(h) for h in LAGS],
        *[dividends(h) for h in LAGS],
        pl.col("me").alias("market_equity"), "prc",
        *DAILY_READ,
    )
    out = out.join(beta_60m(g).select("permno", "mi", "beta_60m", "ivol_capm_60m"),
                   on=["permno", "mi"], how="left")
    # JKP finish_daily_chars; a non-finite ratio is missing.
    ratio = pl.col("rmax5_21d") / pl.col("rvol_252d")
    out = out.with_columns(rmax5_rvol_21d=pl.when(ratio.is_finite()).then(ratio))
    return out.filter(pl.col("in_panel")).drop("in_panel", "mi").sort("permno", "yyyymm")


def signal_names() -> list[str]:
    rows = list(csv.DictReader(open(SIGNAL_LIST, encoding="utf-8")))
    return [r["characteristic"] for r in rows if r["version"] == "A"]


def check_inputs_allowed() -> None:
    # No column read here may be known only after the formation month.
    avail = {(r["table"], r["column"]): r["availability"]
             for r in csv.DictReader(open(DICTIONARY, encoding="utf-8"))}
    for table, cols in [("crsp_panel_acc", PANEL_COLS), ("crsp_daily_agg", DAILY_COLS),
                        ("ff_factors_monthly", ["yyyymm", "mkt_excess"])]:
        for c in cols:
            a = avail.get((table, c))
            check(a is not None, f"{table}.{c} is not in the data dictionary")
            check(a not in ("t+1", "after_t", "today"), f"{table}.{c} has availability {a}")


def second_route(panel: pl.DataFrame, factors: pl.DataFrame, daily: pl.DataFrame, out: pl.DataFrame,
                 report: dict) -> None:
    """
    Description:
        Second route on a sample of stocks: each characteristic is recomputed
        month by month with plain numpy slices, with no shift and no rolling sum.
    Steps:
        1) Sample: every 250th stock of the panel, plus the acceptance stocks.
        2) Loop on the months of each stock; apply the JKP conditions directly.
        3) Same missing values and same numbers (relative gap below 1e-8).
    Output:
        Entry "second_route" in the report; CheckError on a difference.
    """
    stocks = sorted(set(panel["permno"].unique().sort().gather_every(250).to_list()) | {12490, 10028})
    p = (panel.filter(pl.col("permno").is_in(stocks))
         .join(daily.select("permno", "yyyymm", "cfacshr_mth"), on=["permno", "yyyymm"], how="left")
         .join(factors.select("yyyymm", "mkt_excess"), on="yyyymm", how="left").sort("permno", "yyyymm"))
    # Winsorisation bounds of the 60-month regression, from the whole cross-section.
    okb = (pl.col("ret_signal_ok") & pl.col("ret").is_not_null() & (pl.col("ret") != 0)
           & pl.col("ret_exc").is_not_null())
    full = panel.filter(okb).join(factors.select("yyyymm", "mkt_excess"), on="yyyymm", how="inner").filter(
        pl.col("mkt_excess").is_not_null())
    bounds = {}
    for (ym,), grp in full.select("yyyymm", "ret_exc").group_by("yyyymm"):
        v = np.sort(grp["ret_exc"].to_numpy())
        k = len(v)
        bounds[ym] = (v[-(-k // 1000) - 1], v[-(-(999 * k) // 1000) - 1])

    names = ["ret_1_0", "ret_12_1", "ret_12_7", "ret_60_12", "ret_60_36", "seas_1_1an", "seas_1_1na",
             "seas_2_5an", "seas_2_5na", "seas_16_20na", "eqnpo_12m", "chcsho_12m", "chcsho_1m",
             "div1m_me", "div12m_me", "beta_60m", "ivol_capm_60m"]
    rows = []
    nan = float("nan")
    for (permno,), s in p.group_by("permno", maintain_order=True):
        ym = s["yyyymm"].to_numpy()
        ok = s["ret_signal_ok"].fill_null(False).to_numpy()
        f = lambda c: s[c].cast(pl.Float64).fill_null(nan).to_numpy()
        ret, retx, rexc = np.where(ok, f("ret"), nan), np.where(ok, f("retx"), nan), np.where(ok, f("ret_exc"), nan)
        me, prc, shr, cf, mkt = f("me"), f("prc"), f("shrout"), f("cfacshr_mth"), f("mkt_excess")
        gross = 1 + np.where(np.isnan(ret), 0.0, ret)
        T = len(ym)
        for t in range(T):
            cnt = t + 1
            rec = {"permno": permno, "yyyymm": int(ym[t])}

            def mom(i, j):
                # Product of the gross returns of months t-j+1 .. t-i; no value if
                # the index was already zero at t-j (a -100 % return before).
                if cnt <= j or np.isnan(ret[t - j + 1:t - i + 1]).any() or np.prod(gross[:t - j + 1]) == 0:
                    return nan
                return np.prod(gross[t - j + 1:t - i + 1]) - 1

            def seas(a, b, kind):
                if cnt < 12 * b:
                    return nan
                lags_all = list(range((a - 1) * 12, b * 12))
                lags_ann = list(range(a * 12 - 1, b * 12, 12))
                all_sum = sum(ret[t - k] for k in lags_all)
                ann_sum = sum(ret[t - k] for k in lags_ann)
                return ann_sum / len(lags_ann) if kind == "an" else (all_sum - ann_sum) / (
                    len(lags_all) - len(lags_ann))

            rec["ret_1_0"], rec["ret_12_1"], rec["ret_12_7"] = mom(0, 1), mom(1, 12), mom(7, 12)
            rec["ret_60_12"], rec["ret_60_36"] = mom(12, 60), mom(36, 60)
            rec["seas_1_1an"], rec["seas_1_1na"] = seas(1, 1, "an"), seas(1, 1, "na")
            rec["seas_2_5an"], rec["seas_2_5na"] = seas(2, 5, "an"), seas(2, 5, "na")
            rec["seas_16_20na"] = seas(16, 20, "na")

            # Equity net payout over 12 months.
            v = nan
            if cnt > 12 and me[t] > 0 and me[t - 12] > 0 and not np.isnan(ret[t - 11:t + 1]).any():
                ri_now, ri_then = np.prod(gross[:t + 1]), np.prod(gross[:t - 12 + 1])
                if ri_now > 0 and ri_then > 0:
                    v = np.log(np.prod(gross[t - 11:t + 1])) - np.log(me[t] / me[t - 12])
                    v = 0.0 if abs(v) < SMALL else v
            rec["eqnpo_12m"] = v

            for h in (1, 12):
                v = nan
                if cnt > h and shr[t - h] * cf[t - h] != 0:
                    v = (shr[t] * cf[t]) / (shr[t - h] * cf[t - h]) - 1
                    v = 0.0 if abs(v) < TINY else v
                rec[f"chcsho_{h}m"] = v

            def div_amount(u):
                # Dividend amount of month u: per share (ret - retx) x previous
                # price x factor / previous factor, times the shares.
                if u < 1 or not cf[u - 1] != 0:
                    return nan
                return (ret[u] - retx[u]) * prc[u - 1] * (cf[u] / cf[u - 1]) * shr[u]

            for h in (1, 12):
                v = nan
                if cnt >= h and not np.isnan(me[t]) and me[t] != 0:
                    amounts = [div_amount(u) for u in range(t - h + 1, t + 1)]
                    if not any(np.isnan(x) for x in amounts):
                        v = sum(amounts) / me[t]
                        v = 0.0 if v < SMALL else v
                rec[f"div{h}m_me"] = v

            # Beta and idiosyncratic volatility over 60 months.
            lo_t = max(t - BETA_N + 1, 0)
            idx = [u for u in range(lo_t, t + 1)
                   if not np.isnan(ret[u]) and ret[u] != 0 and not np.isnan(rexc[u]) and not np.isnan(mkt[u])]
            b_val, iv = nan, nan
            if len(idx) >= BETA_MIN and np.std(ret[idx], ddof=1) > RET_MIN_STD:
                r = np.array([min(max(rexc[u], bounds[int(ym[u])][0]), bounds[int(ym[u])][1]) for u in idx])
                m = mkt[idx]
                b_val = np.cov(r, m, ddof=1)[0, 1] / np.var(m, ddof=1)
                iv = np.std(r - m * b_val, ddof=1)
            rec["beta_60m"], rec["ivol_capm_60m"] = b_val, iv
            rows.append(rec)

    direct = pl.DataFrame(rows).with_columns(pl.col("yyyymm").cast(pl.Int32))
    direct = direct.with_columns([pl.col(c).fill_nan(None) for c in names])
    cmp = out.select("permno", "yyyymm", *names).join(direct, on=["permno", "yyyymm"], how="inner", suffix="_d")
    check(cmp.height == direct.height, "The second route lost rows")
    res = {}
    for c in names:
        a, b = pl.col(c), pl.col(f"{c}_d")
        null_diff = cmp.filter(a.is_null() != b.is_null()).height
        rel = cmp.select(((a - b).abs() / b.abs().clip(lower_bound=1e-3)).max()).item()
        res[c] = {"values": cmp.filter(a.is_not_null()).height, "null_mismatch": null_diff, "max_rel_diff": rel}
        check(null_diff == 0 and (rel is None or rel < 1e-8), f"Second route differs for {c}: {res[c]}")
    report["second_route"] = {"stocks": len(stocks), "rows": cmp.height, **res}


def checks(out: pl.DataFrame, panel: pl.DataFrame, factors: pl.DataFrame, daily: pl.DataFrame,
           report: dict) -> None:
    names = signal_names()
    built = [c for c in out.columns if c not in ("permno", "yyyymm", "eom")]
    check(sorted(built) == sorted(names),
          f"Columns differ from the signal list: missing {sorted(set(names) - set(built))}, "
          f"extra {sorted(set(built) - set(names))}")
    check(out.select("permno", "yyyymm").equals(panel.select("permno", "yyyymm").sort("permno", "yyyymm")),
          "The output keys are not the panel keys")
    for c in built:
        check(out.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height == 0, f"Non-finite {c}")

    # Acceptance cases; each must also tell its column from its neighbours.
    seen = {}
    for permno, ym, c, expected in ACCEPTANCE:
        row = out.filter((pl.col("permno") == permno) & (pl.col("yyyymm") == ym))
        got = row[c].to_list()
        seen[f"{permno}_{ym}_{c}"] = got
        check(len(got) == 1 and got[0] is not None and abs(got[0] - expected) < 1e-8,
              f"Acceptance case {permno} {ym} {c} failed: {got}, expected {expected}")
    for permno, ym, c, expected, tol in ACCEPTANCE_LOOSE:
        got = out.filter((pl.col("permno") == permno) & (pl.col("yyyymm") == ym))[c].to_list()
        seen[f"{permno}_{ym}_{c}"] = got
        check(len(got) == 1 and got[0] is not None and abs(got[0] - expected) < tol,
              f"Acceptance case {permno} {ym} {c} failed: {got}, expected {expected}")
    for permno, ym, c in ACCEPTANCE_MISSING:
        got = out.filter((pl.col("permno") == permno) & (pl.col("yyyymm") == ym))[c].to_list()
        seen[f"{permno}_{ym}_{c}"] = got
        check(got == [None], f"Acceptance case {permno} {ym} {c} should be missing: {got}")
    report["acceptance_cases"] = seen
    # The 60-month regression leaves out a month with a zero return, even when
    # its excess return is known (JKP): PERMNO 10000, February 1987.
    z = panel.filter((pl.col("permno") == 10000) & (pl.col("yyyymm") == 198702))
    check(z.height == 1 and z["ret"][0] == 0 and z["ret_exc"][0] is not None,
          "Reference row 10000 1987-02 (zero return) not found")
    # Negative test: a momentum window shifted by one month does not pass the case.
    row = out.filter((pl.col("permno") == 12490) & (pl.col("yyyymm") == 200012))
    for wrong in ("ret_12_0", "ret_9_1", "ret_18_1"):
        check(abs(row[wrong][0] - (-0.1292730033)) > 1e-6, f"{wrong} cannot be told from ret_12_1")
    prev = out.filter((pl.col("permno") == 12490) & (pl.col("yyyymm") == 200011))["ret_12_1"][0]
    check(abs(prev - (-0.1292730033)) > 1e-6, "The acceptance case does not date the momentum window")

    # A masked return never enters a signal of its own month: the one-month
    # return is missing exactly where the masked return is.
    j = out.select("permno", "yyyymm", "ret_1_0").join(
        panel.select("permno", "yyyymm", "ret", "ret_signal_ok"), on=["permno", "yyyymm"])
    masked = j.filter(~pl.col("ret_signal_ok"))
    check(masked.filter(pl.col("ret_1_0").is_not_null()).height == 0, "A masked return is in ret_1_0")
    usable = j.filter(pl.col("ret_signal_ok") & pl.col("ret").is_not_null())
    first = usable.filter(pl.col("ret_1_0").is_null()).height
    report["ret_1_0"] = {"masked_rows": masked.height, "usable_returns": usable.height,
                         "usable_but_missing_first_month_or_dead_index": first}
    ok = usable.filter(pl.col("ret_1_0").is_not_null())
    check(ok.filter((pl.col("ret_1_0") - pl.col("ret")).abs() > 1e-12).height == 0,
          "ret_1_0 differs from the monthly return")

    second_route(panel, factors, daily, out, report)

    # Truncation: hide every month after T, rebuild, the past must be identical.
    cols = [c for c in built if c not in DAILY_READ and c != "rmax5_rvol_21d"]
    trunc = {}
    for T in TRUNCATION_DATES:
        cut = compute(panel.filter(pl.col("yyyymm") <= T), factors.filter(pl.col("yyyymm") <= T),
                      daily.filter(pl.col("yyyymm") <= T)).select("permno", "yyyymm", *cols)
        ref = out.filter(pl.col("yyyymm") <= T).select("permno", "yyyymm", *cols)
        same = cut.equals(ref)
        trunc[str(T)] = {"rows": ref.height, "identical": same}
        check(same, f"Signals up to {T} change when later months are hidden")
        del cut, ref
    report["truncation_test"] = trunc

    # Perturbations. (1) A masked return is replaced: nothing may change.
    # (2) Every share factor is doubled: only ratios are used, nothing may change.
    sample = panel["permno"].unique().sort().gather_every(20)
    ps = panel.filter(pl.col("permno").is_in(sample.implode()))
    ds = daily.filter(pl.col("permno").is_in(sample.implode()))
    base = compute(ps, factors, ds)
    # beta_60m uses month-wide winsorisation bounds, so its sample value is not
    # the published one; the comparison is between two runs on the same sample.
    p1 = ps.with_columns(
        ret=pl.when(pl.col("ret_signal_ok")).then(pl.col("ret")).otherwise(0.5),
        retx=pl.when(pl.col("ret_signal_ok")).then(pl.col("retx")).otherwise(0.5),
        ret_exc=pl.when(pl.col("ret_signal_ok")).then(pl.col("ret_exc")).otherwise(0.5))
    same1 = compute(p1, factors, ds).equals(base)
    same2 = compute(ps, factors, ds.with_columns(pl.col("cfacshr_mth") * 2)).equals(base)
    report["perturbation_tests"] = {
        "stocks": sample.len(), "rows": base.height,
        "masked_returns_replaced_identical": same1, "share_factor_doubled_identical": same2,
        "masked_rows_in_the_sample": ps.filter(~pl.col("ret_signal_ok")).height}
    check(same1, "A masked return changes a signal")
    check(same2, "The level of the share factor changes a signal")
    # The test must be able to fail: without the mask, the signals do change.
    p3 = p1.with_columns(ret_signal_ok=pl.lit(True))
    check(not compute(p3, factors, ds).equals(base), "The perturbation test cannot detect an unmasked return")

    # D24 on every row: no momentum or net-payout value when a month of its
    # window has no usable return.
    w = (panel.sort("permno", "yyyymm")
         .with_columns(miss=(~(pl.col("ret_signal_ok") & pl.col("ret").is_not_null())).cast(pl.Int32))
         .with_columns(miss12=pl.col("miss").rolling_sum(12, min_samples=1).over("permno"),
                       miss60=pl.col("miss").rolling_sum(60, min_samples=1).over("permno"))
         .select("permno", "yyyymm", "miss", "miss12", "miss60")
         .join(out.select("permno", "yyyymm", "ret_1_0", "ret_12_0", "ret_12_1", "ret_60_1", "eqnpo_1m",
                          "eqnpo_12m"), on=["permno", "yyyymm"]))
    bad = {
        "ret_1_0": w.filter(pl.col("ret_1_0").is_not_null() & (pl.col("miss") > 0)).height,
        "eqnpo_1m": w.filter(pl.col("eqnpo_1m").is_not_null() & (pl.col("miss") > 0)).height,
        "ret_12_0": w.filter(pl.col("ret_12_0").is_not_null() & (pl.col("miss12") > 0)).height,
        "eqnpo_12m": w.filter(pl.col("eqnpo_12m").is_not_null() & (pl.col("miss12") > 0)).height,
        "ret_12_1": w.filter(pl.col("ret_12_1").is_not_null() & (pl.col("miss12") - pl.col("miss") > 0)).height,
        "ret_60_1": w.filter(pl.col("ret_60_1").is_not_null() & (pl.col("miss60") - pl.col("miss") > 0)).height,
    }
    report["values_with_a_missing_month_in_the_window"] = bad
    check(sum(bad.values()) == 0, f"A window with a missing month gives a value: {bad}")

    # Coverage among eligible stock-months since 1963.
    e = out.join(panel.select("permno", "yyyymm", "eligible", "me"), on=["permno", "yyyymm"]).filter(
        pl.col("eligible") & (pl.col("yyyymm") >= SAMPLE_START))
    report["coverage_eligible_from_1963"] = {"rows": e.height, **{
        c: {"n": round(e[c].is_not_null().mean(), 4),
            "me": round(e.filter(pl.col(c).is_not_null())["me"].sum() / e["me"].sum(), 4)} for c in built}}
    dec = e.with_columns(decade=pl.col("yyyymm") // 1000 * 10).sort("decade")
    report["coverage_by_decade_count"] = {
        str(d): {c: round(grp[c].is_not_null().mean(), 3) for c in built}
        for (d,), grp in dec.group_by("decade", maintain_order=True)}
    report["medians_eligible"] = {c: e[c].median() for c in built}


def main() -> None:
    report: dict = {"script": "scripts/signals/1_price_signals.py", "inputs": {}}
    check_inputs_allowed()
    report["inputs"][SIGNAL_LIST.name] = sha256(SIGNAL_LIST)
    panel = read_checked(PANEL, PANEL_REPORT, PANEL_COLS, report)
    daily = read_checked(DAILY, DAILY_REPORT, DAILY_COLS, report)
    factors = read_checked(FACTORS, FACTORS_REPORT, ["yyyymm", "mkt_excess"], report)
    check(factors["yyyymm"].is_unique().all(), "Duplicate month in the factor table")
    check(daily.select("permno", "yyyymm").is_unique().all(), "Duplicate stock-month in the daily table")

    out = compute(panel, factors, daily)
    report["rows"] = out.height
    report["signals"] = out.width - 3
    checks(out, panel, factors, daily, report)
    publish({PROCESSED / "signals_price.parquet": out}, report, PROCESSED / "signals_price_report.json")
    print(f"signals_price: {out.height:,} stock-months, {out.width - 3} characteristics. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
