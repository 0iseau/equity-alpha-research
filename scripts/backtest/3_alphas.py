"""Backtest, step 3: alphas of the portfolio against factor models.

Rules (ProjectJournal.md, section 8.4, D20 and D23; course brief): the alpha of
the long-only portfolio is the constant of a time-series regression of its
excess return on factor returns. Models: CAPM; Fama-French three factors;
Fama-French five factors; five factors and momentum (the main model). Factors:
the Ken French files of the project (ff_factors_monthly.parquet). t-statistics
with the Newey-West estimator, fixed lag of 6 months (D21 parameters). The
factors rebuilt from our own data (D20) are not done here.

For each configuration of the backtest and three definitions of the return:
gross of costs; net of half spread and price impact (the main number); net
with the commission stress (D15).

Reference: Tidy Finance estimates such regressions by ordinary least squares
with Newey-West errors; statsmodels is used here and checked in the self-test
against the formulas written out.

The conditional diagnostic is computed for the main configuration of whatever
version is run (A, and B when it comes), on the first period of the sample.

Before the strategy is frozen, the script can be run on the development sample
only to test that it works: it then writes nothing and prints no number. The
test sample is refused unless the freeze record names this script.

Inputs:  backtest_<version>_<sample>.parquet, ff_factors_monthly.parquet
Outputs (test sample only):
    alphas_<version>.csv     one row per configuration, return and factor model
    summary_<version>.csv    one row per configuration: returns, risk, turnover,
                             cash, costs
    alphas_<version>_report.json

Run from Project/:
    python scripts/backtest/3_alphas.py --selftest
    python scripts/backtest/3_alphas.py --version A --sample development   (silent check)
    python scripts/backtest/3_alphas.py --version A --sample test          (after the freeze)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import PROCESSED, PROJECT, CheckError, check, publish, read_verified, sha256  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_guard  # noqa: E402

FACTORS = PROCESSED / "ff_factors_monthly.parquet"
FACTORS_REPORT = PROCESSED / "crsp_excess_report.json"
FREEZE = PROJECT / "resources" / "strategy_freeze.json"
SCRIPT = "scripts/backtest/3_alphas.py"
HAC_LAGS = 6
MODELS = {
    "CAPM": ["mkt_excess"],
    "FF3": ["mkt_excess", "smb", "hml"],
    "FF5": ["mkt_excess_ff5", "smb_ff5", "hml_ff5", "rmw", "cma"],
    "FF5_MOM": ["mkt_excess_ff5", "smb_ff5", "hml_ff5", "rmw", "cma", "mom"],
}
MAIN_MODEL = "FF5_MOM"
MAIN_CONFIG = "gbrt_all_d1"
CONDITIONAL = "FF5_MOM_conditional"     # one diagnostic, for the main configuration on the whole test period
CONFIGS = ["gbrt_all_d1", "gbrt_large_d1", "ridge_all_d1", "ridge_large_d1", "gbrt_all_close", "gbrt_large_close",
           "ridge_all_close", "ridge_large_close", "gbrt_all_d1_cap01", "gbrt_large_d1_cap01"]
RETURNS = {"gross": "ret_gross", "net": "ret_net", "net_with_commission_stress": "__net_commission"}
PERIODS = {"development": {"1981-1992": (198101, 199212)},
           "test": {"1993-2025": (199301, 202512), "1993-2008": (199301, 200812), "2009-2025": (200901, 202512)}}


def months_between(lo: int, hi: int) -> list[int]:
    out, m = [], lo
    while m <= hi:
        out.append(m)
        m = m + 1 if m % 100 < 12 else (m // 100 + 1) * 100 + 1
    return out


def regress(y: np.ndarray, x: np.ndarray) -> dict:
    """OLS of y on a constant and x, Newey-West errors with HAC_LAGS lags (Bartlett kernel, no small-sample correction)."""
    z = np.column_stack([np.ones(len(y)), x])
    check(bool(np.isfinite(z).all() and np.isfinite(y).all()), "A regression has a value that is not finite")
    check(np.linalg.matrix_rank(z) == z.shape[1], "The regressors of a regression are collinear")
    fit = sm.OLS(y, sm.add_constant(x, has_constant="add")).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS, "use_correction": False})
    return {"alpha": float(fit.params[0]), "t_alpha": float(fit.tvalues[0]), "betas": [float(b) for b in fit.params[1:]],
            "t_betas": [float(t) for t in fit.tvalues[1:]], "r2": float(fit.rsquared), "months": int(fit.nobs)}


def mean_t(z: np.ndarray) -> tuple[float, float]:
    """Mean of a series and its Newey-West t-statistic (regression on a constant)."""
    fit = sm.OLS(z, np.ones((z.size, 1))).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS, "use_correction": False})
    return float(fit.params[0]), float(fit.tvalues[0])


def tables(bt: pl.DataFrame, factors: pl.DataFrame, periods: dict, configs: list[str] | None = None
           ) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The alpha table and the summary table (see the header)."""
    c = pl.col
    if configs is not None:
        check(sorted(bt["config"].unique().to_list()) == sorted(configs), "The configurations are not the ten expected")
    bt = bt.with_columns(__net_commission=c("ret_net") - c("cost_commission_stress"))
    df = bt.join(factors, on="yyyymm", how="left", validate="m:1")
    check(df["mkt_excess"].null_count() == 0 and df["mom"].null_count() == 0, "A month of the backtest has no factor")
    check(df.filter((c("rf") - c("risk_free")).abs() > 1e-12).height == 0,
          "The risk-free rate of the backtest is not the one of the factor file")
    alphas, summary = [], []
    for config in df["config"].unique(maintain_order=True).to_list():
        for period, (lo, hi) in periods.items():
            d = df.filter((c("config") == config) & c("yyyymm").is_between(lo, hi)).sort("yyyymm")
            # The exact calendar: every month of the period, once, in order (the lags of
            # the Newey-West estimator count months).
            check(d["yyyymm"].to_list() == months_between(lo, hi), f"{config} {period}: the months are not the calendar")
            for kind, col in RETURNS.items():
                y = (d[col] - d["rf"]).to_numpy()
                for model, cols in MODELS.items():
                    r = regress(y, d.select(cols).to_numpy())
                    alphas.append({"config": config, "period": period, "returns": kind, "factor_model": model,
                                   "alpha_monthly": r["alpha"], "alpha_annual": 12 * r["alpha"], "t_alpha": r["t_alpha"],
                                   "r2": r["r2"], "months": r["months"],
                                   **{f"beta_{i + 1}": (r["betas"][i] if i < len(r["betas"]) else None) for i in range(6)},
                                   "factors": ";".join(cols)})
            if config == MAIN_CONFIG and period == next(iter(periods)):
                # Conditional diagnostic (Ferson and Schadt 1996): the exposure of the fund
                # varies with the share invested. The six factors, and their products with
                # the share invested at the previous month end, centred on its mean.
                fx = d.select(MODELS[MAIN_MODEL]).to_numpy()
                inv = d["invested_before"].to_numpy()
                r = regress((d["ret_net"] - d["rf"]).to_numpy(), np.column_stack([fx, fx * (inv - inv.mean())[:, None]]))
                alphas.append({"config": config, "period": period, "returns": "net", "factor_model": CONDITIONAL,
                               "alpha_monthly": r["alpha"], "alpha_annual": 12 * r["alpha"], "t_alpha": r["t_alpha"],
                               "r2": r["r2"], "months": r["months"],
                               **{f"beta_{i + 1}": r["betas"][i] for i in range(6)},
                               "factors": ";".join(MODELS[MAIN_MODEL]) + ";each x invested share (centred)"})
            net = (d["ret_net"] - d["rf"]).to_numpy()
            gross = (d["ret_gross"] - d["rf"]).to_numpy()
            mkt = d["mkt_excess"].to_numpy()
            over, t_over = mean_t(net - mkt)
            mean_net, t_net = mean_t(net)
            summary.append({
                "config": config, "period": period, "months": d.height,
                "excess_return_gross_annual": 12 * float(gross.mean()), "excess_return_net_annual": 12 * mean_net,
                "t_excess_return_net": t_net, "volatility_net_annual": float(net.std(ddof=1) * np.sqrt(12)),
                "sharpe_net_annual": float(net.mean() / net.std(ddof=1) * np.sqrt(12)),
                "market_excess_return_annual": 12 * float(mkt.mean()),
                "market_sharpe_annual": float(mkt.mean() / mkt.std(ddof=1) * np.sqrt(12)),
                "net_minus_market_annual": 12 * over, "t_net_minus_market": t_over,
                "worst_month_net": float(d["ret_net"].min()),
                "cost_spread_bp_month": float(d["cost_spread"].mean() * 1e4),
                "cost_impact_bp_month": float(d["cost_impact"].mean() * 1e4),
                "cost_spread_quoted_bp_month": float(d["cost_spread_quoted"].mean() * 1e4),
                "cost_spread_high_low_bp_month": float(d["cost_spread_high_low"].mean() * 1e4),
                "cost_spread_group_mean_bp_month": float(d["cost_spread_group_mean"].mean() * 1e4),
                "invested_before_mean": float(d["invested_before"].mean()),
                "wanted_not_filled_month": float(d["wanted_not_filled"].mean()),
                "wanted_without_adv_month": float(d["wanted_without_adv"].mean()),
                "commission_stress_bp_month": float(d["cost_commission_stress"].mean() * 1e4),
                "turnover_desired_month": float(d["turnover_desired"].mean()),
                "turnover_after_cap_month": float(d["turnover_after_cap"].mean()),
                "turnover_filled_month": float(d["turnover_filled"].mean()),
                "cash_after_trades_mean": float(d["cash_after_trades"].mean()),
                "stocks_to_hold_median": float(d["stocks_to_hold"].median()),
                "stocks_held_median": float(d["stocks_held_after_trades"].median()),
                "share_of_orders_capped": float(d["orders_capped"].sum() / max(1, d["orders"].sum())),
                "share_of_orders_not_filled": float(d["orders_not_filled"].sum() / max(1, d["orders"].sum())),
                "largest_weight_max": float(d["largest_weight_after_trades"].max()),
                "largest_weight_of_the_invested_part_median": float(d["largest_weight_of_the_invested_part"].median()),
                "effective_stocks_median": float(d["effective_stocks"].median()),
                "stocks_held_above_1e-6_median": float(d["stocks_held_above_1e-6"].median()),
                "share_of_orders_without_adv": float(d["orders_without_adv"].sum() / max(1, d["orders"].sum())),
                "filled_share_spread_quoted": float(d["filled_spread_quoted"].sum() / max(1e-300, d["turnover_filled"].sum())),
                "filled_share_spread_high_low": float(d["filled_spread_high_low"].sum() / max(1e-300, d["turnover_filled"].sum())),
                "filled_share_spread_group_mean": float(d["filled_spread_group_mean"].sum() / max(1e-300, d["turnover_filled"].sum())),
                "write_off_largest_case": float(d["write_off_largest"].max()),
                "late_proceeds_total": float(d["late_proceeds"].sum()),
                "cash_first_year": float(d.head(12)["cash_after_trades"].mean()),
                "cash_last_year": float(d.tail(12)["cash_after_trades"].mean()),
                "write_off_total": float(d["write_off"].sum()), "write_off_max_month": float(d["write_off"].max()),
                "left_the_panel_to_cash_mean": float(d["left_the_panel_to_cash"].mean())})
    a, s = pl.DataFrame(alphas), pl.DataFrame(summary)
    num = [n for n, t in a.schema.items() if t == pl.Float64]
    check(a.select([c(n).is_nan().sum() for n in num]).sum_horizontal().item() == 0, "An estimate is not a number")
    return a, s


def run(version: str, sample: str, retry: bool = False) -> None:
    check(sample in PERIODS, f"Unknown sample {sample}")
    reservation = None
    report: dict = {"script": SCRIPT, "version": version, "sample": sample, "inputs": {}}
    report["script_sha256"] = sha256(Path(__file__))
    if sample == "test":
        report["freeze"] = freeze_guard.require_freeze(
            SCRIPT, version, [PROCESSED / f"alphas_{version}.csv", PROCESSED / f"summary_{version}.csv",
                              PROCESSED / f"alphas_{version}_report.json"])
        expected = freeze_guard.completed_output("backtest", version, report["freeze"], f"backtest_{version}_test.parquet")
        reservation = freeze_guard.reserve("alphas", version, report["freeze"], retry)
    name = f"backtest_{version}_{sample}.parquet"
    if sample == "test":                                    # the bytes read are those recorded at the end of the backtest
        bt = freeze_guard.read_frozen(PROCESSED / name, expected)
        report["inputs"][name] = {"sha256": expected}
    else:
        bt, run_id = read_verified(PROCESSED / name, PROCESSED / f"backtest_{version}_{sample}_report.json")
        report["inputs"][name] = {"from_run": run_id}
    factors, f_run = read_verified(FACTORS, FACTORS_REPORT)
    report["inputs"][FACTORS.name] = {"from_run": f_run}
    check(factors["yyyymm"].is_unique().all(), "Duplicate month in the factor file")
    lo = min(v[0] for v in PERIODS[sample].values())
    hi = max(v[1] for v in PERIODS[sample].values())
    check((bt["yyyymm"].min(), bt["yyyymm"].max()) == (lo, hi), "The backtest does not cover the sample exactly")

    alphas, summary = tables(bt, factors, PERIODS[sample], CONFIGS)
    if sample == "development":
        # Not out of sample and never a result: nothing is written, no number is shown.
        print(f"development sample: {alphas.height} regressions and {summary.height} summary rows computed without "
              "error (the script does compute them); nothing is written and no number is shown before the freeze.")
        return
    report["hac_lags"] = HAC_LAGS
    report["main"] = {"config": "gbrt_all_d1", "returns": "net", "factor_model": MAIN_MODEL, "period": "1993-2025"}
    report["rows"] = {"alphas": alphas.height, "summary": summary.height}
    publish({PROCESSED / f"alphas_{version}.csv": alphas, PROCESSED / f"summary_{version}.csv": summary}, report,
            PROCESSED / f"alphas_{version}_report.json")
    if reservation is not None:
        freeze_guard.finish(reservation, PROCESSED / f"alphas_{version}_report.json")
    print(f"alphas_{version}.csv: {alphas.height} rows; summary_{version}.csv: {summary.height} rows. "
          f"Run {report['run_id']}.")


def selftest() -> None:
    """Random numbers only: the estimates against the formulas written out."""
    rng = np.random.default_rng(11)
    n = 396
    x = rng.normal(0.005, 0.04, size=(n, 3))
    e = np.zeros(n)
    for t in range(1, n):                                   # autocorrelated errors, so that the lags matter
        e[t] = 0.4 * e[t - 1] + rng.normal(0, 0.02)
    y = 0.004 + x @ np.array([1.0, 0.3, -0.2]) + e
    r = regress(y, x)
    # Ordinary least squares and Newey-West written out (Bartlett weights, lag 6, no correction).
    z = np.column_stack([np.ones(n), x])
    b = np.linalg.solve(z.T @ z, z.T @ y)
    u = y - z @ b
    s = (z * u[:, None]).T @ (z * u[:, None])
    for lag in range(1, HAC_LAGS + 1):
        g = (z[lag:] * u[lag:, None]).T @ (z[:-lag] * u[:-lag, None])
        s += (1 - lag / (HAC_LAGS + 1)) * (g + g.T)
    cov = np.linalg.inv(z.T @ z) @ s @ np.linalg.inv(z.T @ z)
    check(abs(r["alpha"] - b[0]) < 1e-12 and max(abs(np.array(r["betas"]) - b[1:])) < 1e-12, "selftest: coefficients")
    check(abs(r["t_alpha"] - b[0] / np.sqrt(cov[0, 0])) < 1e-8, f"selftest: t-statistic {r['t_alpha']}")
    check(abs(r["alpha"] - 0.004) < 0.004 and abs(r["betas"][0] - 1.0) < 0.1, "selftest: planted values not found")
    # The lags matter: the t-statistic without them is another number.
    plain = sm.OLS(y, sm.add_constant(x)).fit()
    check(abs(plain.tvalues[0] - r["t_alpha"]) > 1e-3, "selftest: the Newey-West correction has no effect")
    m, t = mean_t(e + 0.001)
    check(abs(m - (e + 0.001).mean()) < 1e-14, "selftest: mean")

    # The tables, on a synthetic backtest of two configurations.
    ym = np.array([y_ * 100 + m_ for y_ in range(1993, 2026) for m_ in range(1, 13)], dtype=np.int32)
    fac = pl.DataFrame({"yyyymm": ym, "mkt_excess": x[:, 0], "smb": x[:, 1], "hml": x[:, 2], "mkt_excess_ff5": x[:, 0],
                        "smb_ff5": x[:, 1], "hml_ff5": x[:, 2], "rmw": rng.normal(0, 0.02, n), "cma": rng.normal(0, 0.02, n),
                        "mom": rng.normal(0, 0.04, n), "risk_free": np.full(n, 0.003)})
    rows = []
    inv = np.clip(0.5 + 0.4 * np.sin(np.arange(n) / 40), 0, 1)
    for config, shift in (("gbrt_all_d1", 0.0), ("b", 0.002)):
        rows.append(pl.DataFrame({
            "config": [config] * n, "yyyymm": ym, "ret_net": y + shift + 0.003, "ret_gross": y + shift + 0.003 + 0.001,
            "rf": np.full(n, 0.003), "cost_spread": np.full(n, 0.0006), "cost_impact": np.full(n, 0.0004),
            "cost_commission_stress": np.full(n, 0.0002), "turnover_desired": np.full(n, 1.0),
            "turnover_after_cap": np.full(n, 0.6), "turnover_filled": np.full(n, 0.5), "cash_after_trades": np.full(n, 0.1),
            "stocks_to_hold": np.full(n, 100), "stocks_held_after_trades": np.full(n, 120), "orders": np.full(n, 50),
            "orders_capped": np.full(n, 10), "orders_not_filled": np.full(n, 5),
            "largest_weight_after_trades": np.full(n, 0.05), "write_off": np.zeros(n), "left_the_panel_to_cash": np.zeros(n),
            "largest_weight_of_the_invested_part": np.full(n, 0.06), "effective_stocks": np.full(n, 40.0),
            "stocks_held_above_1e-6": np.full(n, 110), "orders_without_adv": np.full(n, 5),
            "filled_spread_quoted": np.full(n, 0.3), "filled_spread_high_low": np.full(n, 0.15),
            "filled_spread_group_mean": np.full(n, 0.05), "write_off_largest": np.zeros(n), "late_proceeds": np.zeros(n),
            "invested_before": inv, "cost_spread_quoted": np.full(n, 0.0001), "cost_spread_high_low": np.full(n, 0.0004),
            "cost_spread_group_mean": np.full(n, 0.0001), "wanted_not_filled": np.full(n, 0.1),
            "wanted_without_adv": np.full(n, 0.05)}))
    a, sm_ = tables(pl.concat(rows), fac, PERIODS["test"])
    check(a.height == 2 * 3 * 3 * 4 + 1 and sm_.height == 2 * 3, f"selftest: {a.height} alpha rows, {sm_.height} summary rows")
    # The conditional diagnostic: one row, for the main configuration; its formula written out.
    cond = a.filter(pl.col("factor_model") == CONDITIONAL)
    f6 = fac.select(MODELS[MAIN_MODEL]).to_numpy()
    zc = np.column_stack([np.ones(n), f6, f6 * (inv - inv.mean())[:, None]])
    bc = np.linalg.lstsq(zc, y, rcond=None)[0]
    check(cond.height == 1 and cond["config"][0] == "gbrt_all_d1" and abs(cond["alpha_monthly"][0] - bc[0]) < 1e-10,
          "selftest: conditional diagnostic")
    # A month replaced by a copy of the next one keeps 396 rows but is not the calendar: refused.
    broken = pl.concat(rows).with_columns(yyyymm=pl.when((pl.col("yyyymm") == 199907) & (pl.col("config") == "b"))
                                          .then(199908).otherwise(pl.col("yyyymm")).cast(pl.Int32))
    try:
        tables(broken, fac, PERIODS["test"])
        refused = False
    except Exception:
        refused = True
    check(refused, "selftest: a broken calendar is accepted")
    pick = lambda cfg, kind: a.filter((pl.col("config") == {"a": "gbrt_all_d1"}.get(cfg, cfg)) & (pl.col("period") == "1993-2025")  # noqa: E731
                                      & (pl.col("returns") == kind) & (pl.col("factor_model") == "FF3"))["alpha_monthly"][0]
    check(abs(pick("a", "net") - r["alpha"]) < 1e-12, "selftest: the net alpha is not the regression of net - rf")
    check(abs(pick("b", "net") - pick("a", "net") - 0.002) < 1e-12, "selftest: a shift of the return is not in the alpha")
    check(abs(pick("a", "gross") - pick("a", "net") - 0.001) < 1e-12, "selftest: gross and net alphas")
    check(abs(pick("a", "net") - pick("a", "net_with_commission_stress") - 0.0002) < 1e-12, "selftest: commission stress")
    row = sm_.filter((pl.col("config") == "gbrt_all_d1") & (pl.col("period") == "1993-2025")).to_dicts()[0]
    check(abs(row["excess_return_net_annual"] - 12 * y.mean()) < 1e-12 and abs(row["cost_spread_bp_month"] - 6.0) < 1e-9
          and abs(row["share_of_orders_capped"] - 0.2) < 1e-12, f"selftest: summary {row}")
    print("selftest passed: coefficients and Newey-West t-statistics against the formulas written out,")
    print("  alpha and summary tables on a synthetic backtest. No project data was read.")


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
