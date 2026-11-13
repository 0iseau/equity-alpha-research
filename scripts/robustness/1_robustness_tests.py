"""ROBUSTNESS TESTS OF VERSION A, RUN AFTER THE OUT-OF-SAMPLE TEST.

Design and status: RobustnessJournal.md, sections 0 and 1 (written before the
first run). The test of version A was read before these tests existed; they are
run on the same years and none of them is a new main result.

  Test 1  decile sorts of the forecasts, without costs (paper portfolios)
  Test 2  the frozen backtest with every cost multiplied by k
  Test 3  the frozen backtest with another capital

Tests 2 and 3 import the frozen monthly step (scripts/backtest/2_backtest.py)
unchanged; with k = 1 and USD 100 million they must reproduce the test month by
month. Every input of the test chain is read against its recorded SHA-256.

Run from Project/:  python scripts/robustness/1_robustness_tests.py
Outputs: reports/robustness/*.csv
"""
import hashlib
import importlib.util
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import statsmodels.api as sm
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
STEPS = ROOT / "resources" / "test_steps"
OUT = ROOT / "reports" / "robustness"
VERSION = "A"
FF5_MOM = ["mkt_excess_ff5", "smb_ff5", "hml_ff5", "rmw", "cma", "mom"]
PERIODS = {"1993-2025": (199301, 202512), "1993-2008": (199301, 200812), "2009-2025": (200901, 202512)}
KEYS = ["gbrt_all", "gbrt_large", "ridge_all", "ridge_large"]

spec = importlib.util.spec_from_file_location("frozen_backtest", ROOT / "scripts" / "backtest" / "2_backtest.py")
bt = importlib.util.module_from_spec(spec)
sys.modules["frozen_backtest"] = bt
spec.loader.exec_module(bt)


def stop(message: str) -> None:
    raise SystemExit(f"STOP: {message}")


def read_hashed(name: str, expected: str) -> pl.DataFrame:
    data = (PROCESSED / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        stop(f"{name} does not have the recorded SHA-256")
    return pl.read_parquet(io.BytesIO(data))


def done_record(step: str) -> dict:
    done = [r for r in (json.loads(p.read_text(encoding="utf-8"))
                        for p in sorted(STEPS.glob(f"*_{VERSION}_{step}.attempt*.json"))) if r.get("status") == "done"]
    if len(done) != 1:
        stop(f"{step}: {len(done)} completed attempts, expected 1")
    return done[0]


def hac(y: np.ndarray, x: np.ndarray | None = None) -> tuple[float, float]:
    """Intercept and its Newey-West t-statistic (6 lags, Bartlett, no small-sample correction), as in the test."""
    z = np.ones((y.size, 1)) if x is None else sm.add_constant(x, has_constant="add")
    fit = sm.OLS(y, z).fit(cov_type="HAC", cov_kwds={"maxlags": 6, "use_correction": False})
    return float(fit.params[0]), float(fit.tvalues[0])


def disc_quantile(v: np.ndarray, q: float) -> float:
    """Discrete quantile of the project: the value of rank ceil(q x n) among the n values sorted upwards."""
    s = np.sort(v)
    return float(s[math.ceil(q * s.size) - 1])


# ------------------------------------------------------------------ test 1

def test_1(factors: pd.DataFrame) -> None:
    freeze = json.loads((ROOT / "resources" / "strategy_freeze.json").read_text(encoding="utf-8"))
    pred = read_hashed(f"predictions_{VERSION}_test.parquet", freeze["predictions_test_sha256"][VERSION])
    cand = read_hashed(f"portfolio_candidates_{VERSION}_test.parquet",
                       done_record("candidates")["outputs_sha256"][f"portfolio_candidates_{VERSION}_test.parquet"])
    bp_ref = read_hashed(f"portfolio_breakpoints_{VERSION}_test.parquet",
                         done_record("candidates")["outputs_sha256"][f"portfolio_breakpoints_{VERSION}_test.parquet"])
    lo, hi = int(pred["yyyymm"].min()), int(pred["yyyymm"].max())
    if (lo, hi, pred["yyyymm"].n_unique()) != (199212, 202511, 396):
        stop("the forecasts are not the 396 formation months of the test")
    panel = (pl.scan_parquet(PROCESSED / "crsp_panel_acc.parquet").filter(pl.col("yyyymm").is_between(lo, hi))
             .select("permno", "yyyymm", "ret_exc_lead1").collect())
    df = (pred.select("permno", "yyyymm", "pred_gbrt", "pred_ridge")
          .join(cand.select("permno", "yyyymm", "me", "nyse", "universe_large"), on=["permno", "yyyymm"], how="inner",
                validate="1:1")
          .join(panel, on=["permno", "yyyymm"], how="left", validate="1:1").sort("yyyymm", "permno"))
    if df.height != pred.height or df.height != cand.height:
        stop("forecasts, candidates and panel do not have the same stock-months")
    if df.select(pl.col("pred_gbrt").is_null().any() | pl.col("pred_ridge").is_null().any() | pl.col("me").is_null().any()).item():
        stop("a forecast or a market equity is missing")
    ref90 = {(r["yyyymm"], r["model"], r["universe"]): r["breakpoint_90"] for r in bp_ref.iter_rows(named=True)}

    monthly, ics = [], []
    n_missing = 0
    for (ym,), g in df.group_by("yyyymm", maintain_order=True):
        ret = g["ret_exc_lead1"].to_numpy().astype(float)
        me, nyse, large = g["me"].to_numpy(), g["nyse"].to_numpy(), g["universe_large"].to_numpy()
        valid = np.isfinite(ret)
        n_missing += int((~valid).sum())
        ret_month = bt.next_month(int(ym))
        for model in ("gbrt", "ridge"):
            p = g[f"pred_{model}"].to_numpy()
            for universe, member in (("all", np.ones(p.size, bool)), ("large", large)):
                ok = member & valid
                rho = spearmanr(p[ok], ret[ok]).statistic if ok.sum() > 2 and np.unique(p[ok]).size > 1 else np.nan
                ics.append({"yyyymm": ret_month, "model": model, "universe": universe, "rank_ic": rho, "stocks": int(ok.sum())})
                for bp_name, base in (("nyse", member & nyse), ("all_stocks", member)):
                    cuts = np.array([disc_quantile(p[base], q / 10) for q in range(1, 10)])
                    if bp_name == "nyse" and cuts[8] != ref90[(int(ym), model, universe)]:
                        stop(f"{ym} {model} {universe}: the 90th percentile differs from the one of the test")
                    group = 1 + (p[:, None] >= cuts[None, :]).sum(axis=1)
                    for weighting in ("equal", "value"):
                        row = {"yyyymm": ret_month, "model": model, "universe": universe, "breakpoints": bp_name,
                               "weighting": weighting}
                        for d in range(1, 11):
                            s = ok & (group == d)
                            w = np.ones(s.sum()) if weighting == "equal" else me[s]
                            row[f"g{d}"] = float(np.sum(w * ret[s]) / w.sum()) if s.any() and w.sum() > 0 else np.nan
                            row[f"n{d}"] = int(s.sum())
                        monthly.append(row)
    m = pd.DataFrame(monthly)
    ic = pd.DataFrame(ics)

    sorts, spreads = [], []
    for keys, t in m.groupby(["model", "universe", "breakpoints", "weighting"], sort=True):
        t = t.sort_values("yyyymm")
        for period, (a, b) in PERIODS.items():
            s = t[(t.yyyymm >= a) & (t.yyyymm <= b)]
            base = dict(zip(["model", "universe", "breakpoints", "weighting"], keys), period=period)
            row = dict(base)
            for d in range(1, 11):
                row[f"g{d}_excess_return_annual"] = 12 * s[f"g{d}"].mean()
                row[f"g{d}_months_empty"] = int(s[f"g{d}"].isna().sum())
                row[f"g{d}_stocks_median"] = float(s[f"n{d}"].median())
            sorts.append(row)
            both = s[s.g1.notna() & s.g10.notna()]
            fx = factors.loc[both.yyyymm, FF5_MOM].to_numpy()
            hl = (both.g10 - both.g1).to_numpy()
            mean_hl, t_hl = hac(hl)
            a_hl, ta_hl = hac(hl, fx)
            a_top, ta_top = hac(both.g10.to_numpy(), fx)
            mean_top, t_top = hac(both.g10.to_numpy())
            spreads.append(dict(base, months=len(both), months_without_a_bottom_or_top_group=len(s) - len(both),
                                top_excess_return_annual=12 * mean_top, t_top=t_top,
                                bottom_excess_return_annual=12 * both.g1.mean(),
                                top_minus_bottom_annual=12 * mean_hl, t_top_minus_bottom=t_hl,
                                alpha_ff5mom_top_minus_bottom_annual=12 * a_hl, t_alpha_top_minus_bottom=ta_hl,
                                alpha_ff5mom_top_annual=12 * a_top, t_alpha_top=ta_top,
                                top_stocks_median=float(both.n10.median()), bottom_stocks_median=float(both.n1.median())))
    ic_rows = []
    for (model, universe), t in ic.groupby(["model", "universe"], sort=True):
        t = t.sort_values("yyyymm")
        for period, (a, b) in PERIODS.items():
            s = t[(t.yyyymm >= a) & (t.yyyymm <= b) & t.rank_ic.notna()]
            mean, tv = hac(s.rank_ic.to_numpy())
            ic_rows.append({"model": model, "universe": universe, "period": period, "months": len(s),
                            "rank_ic_mean": mean, "t_rank_ic": tv, "share_of_months_positive": float((s.rank_ic > 0).mean())})
    pd.DataFrame(sorts).to_csv(OUT / "decile_sorts_A.csv", index=False, lineterminator="\n")
    sp = pd.DataFrame(spreads)
    sp.to_csv(OUT / "decile_spreads_A.csv", index=False, lineterminator="\n")
    icf = pd.DataFrame(ic_rows)
    icf.to_csv(OUT / "rank_ic_A.csv", index=False, lineterminator="\n")
    m.to_csv(OUT / "decile_sorts_A_monthly.csv", index=False, lineterminator="\n")

    print(f"\nTEST 1. {df.height:,} stock-months; {n_missing:,} without a next-month return, left out of the sorts.")
    show = sp[sp.period == "1993-2025"].drop(columns=["period"]).copy()
    for c in [c for c in show.columns if c.endswith("_annual")]:
        show[c] = (100 * show[c]).round(2)
    print(show.round(2).to_string(index=False))
    print(icf.round(4).to_string(index=False))
    full = pd.DataFrame(sorts)
    full = full[full.period == "1993-2025"]
    cols = [f"g{d}_excess_return_annual" for d in range(1, 11)]
    print((100 * full.set_index(["model", "universe", "breakpoints", "weighting"])[cols]).round(1).to_string())


# ------------------------------------------------------------ tests 2 and 3

def simulate(months: list[dict], n: int, cost_mult: float, capital: float) -> pd.DataFrame:
    """The frozen step, month after month, with the costs multiplied and another capital."""
    frozen_capital = bt.CAPITAL
    bt.CAPITAL = capital
    try:
        w, cash, out = np.zeros(n), 1.0, []
        for m in months:
            f = dict(m["f"])
            f["half_spread"] = m["f"]["half_spread"] * cost_mult
            f["lam"] = m["f"]["lam"] * cost_mult
            w, cash, rec = bt.step(w, cash, f, m["r"], "d1", bt.CAP)
            if abs(w.sum() + cash - 1.0) > 1e-9 or w.min() < 0 or cash < -1e-9:
                stop(f"{m['r']['return_month']}: weights and cash do not sum to 1")
            rec["yyyymm"] = m["r"]["return_month"]
            out.append(rec)
    finally:
        bt.CAPITAL = frozen_capital
    return pd.DataFrame(out)


def stats(t: pd.DataFrame, factors: pd.DataFrame, period: str) -> dict:
    a, b = PERIODS[period]
    s = ((t.yyyymm >= a) & (t.yyyymm <= b)).to_numpy()
    fx = factors.loc[t.yyyymm]
    net = (t.ret_net - t.rf).to_numpy()[s]
    alpha, t_alpha = hac(net, fx[FF5_MOM].to_numpy()[s])
    gap, t_gap = hac(net - fx["mkt_excess"].to_numpy()[s])
    mean, t_mean = hac(net)
    return {"period": period, "excess_return_net_annual": 12 * mean, "t_excess_return_net": t_mean,
            "net_minus_market_annual": 12 * gap, "t_net_minus_market": t_gap,
            "alpha_ff5mom_net_annual": 12 * alpha, "t_alpha_net": t_alpha,
            "cost_bp_month": 1e4 * (t.cost_spread + t.cost_impact)[s].mean(),
            "turnover_filled_month": t.turnover_filled[s].mean(), "cash_after_trades_mean": t.cash_after_trades[s].mean(),
            "share_of_orders_capped": t.orders_capped[s].sum() / max(1, t.orders[s].sum()),
            "effective_stocks_median": t.effective_stocks[s].median()}


def tests_2_and_3(factors: pd.DataFrame) -> None:
    expected = done_record("candidates")["outputs_sha256"][f"portfolio_candidates_{VERSION}_test.parquet"]
    data, n = bt.load(VERSION, "test", {"inputs": {}}, expected)
    frozen = read_hashed(f"backtest_{VERSION}_test.parquet",
                         done_record("backtest")["outputs_sha256"][f"backtest_{VERSION}_test.parquet"]).to_pandas()
    base = {}
    for key in KEYS:
        base[key] = simulate(data[key], n, 1.0, 1e8)
        ref = frozen[frozen.config == f"{key}_d1"].sort_values("yyyymm")
        if not (np.array_equal(base[key].yyyymm.to_numpy(), ref.yyyymm.to_numpy())
                and np.array_equal(base[key].ret_net.to_numpy(), ref.ret_net.to_numpy())):
            stop(f"{key}: k = 1 and USD 100 million do not reproduce the frozen backtest")
    print("\nTESTS 2 AND 3. k = 1 and USD 100 million reproduce the frozen backtest exactly (4 configurations).")

    rows2, rows3 = [], []
    for key in KEYS:
        for k in (0.0, 0.25, 0.5, 1.0, 2.0):
            t = base[key] if k == 1.0 else simulate(data[key], n, k, 1e8)
            for period in PERIODS:
                rows2.append({"model_universe": key, "cost_multiplier": k, **stats(t, factors, period)})
        for capital in (1e7, 1e8, 1e9):
            t = base[key] if capital == 1e8 else simulate(data[key], n, 1.0, capital)
            for period in PERIODS:
                rows3.append({"model_universe": key, "capital_usd": capital, **stats(t, factors, period)})
    r2, r3 = pd.DataFrame(rows2), pd.DataFrame(rows3)

    even = []
    for (key, period), t in r2.groupby(["model_universe", "period"], sort=True):
        t = t.sort_values("cost_multiplier")
        k, a = t.cost_multiplier.to_numpy(), t.alpha_ff5mom_net_annual.to_numpy()
        cross = [k[i] + (k[i + 1] - k[i]) * a[i] / (a[i] - a[i + 1]) for i in range(len(k) - 1) if a[i] > 0 >= a[i + 1]]
        even.append({"model_universe": key, "period": period, "alpha_at_zero_cost_annual": a[0],
                     "break_even_cost_multiplier": cross[0] if cross else np.nan,
                     "note": "" if cross else ("alpha negative at zero cost" if a[0] <= 0 else "alpha positive up to k = 2")})
    ev = pd.DataFrame(even)
    r2.to_csv(OUT / "cost_multiplier_A.csv", index=False, lineterminator="\n")
    ev.to_csv(OUT / "cost_break_even_A.csv", index=False, lineterminator="\n")
    r3.to_csv(OUT / "capital_A.csv", index=False, lineterminator="\n")

    def show(frame: pd.DataFrame) -> str:
        x = frame[frame.period == "1993-2025"].drop(columns=["period"]).copy()
        for c in [c for c in x.columns if c.endswith("_annual") or c in ("turnover_filled_month", "cash_after_trades_mean",
                                                                         "share_of_orders_capped")]:
            x[c] = (100 * x[c]).round(2)
        return x.round(2).to_string(index=False)

    print("Test 2, 1993-2025:\n" + show(r2))
    x = ev.copy()
    x["alpha_at_zero_cost_annual"] = (100 * x.alpha_at_zero_cost_annual).round(2)
    print(x.round(2).to_string(index=False))
    print("Test 3, 1993-2025:\n" + show(r3))


def main() -> None:
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_columns", 60)
    OUT.mkdir(parents=True, exist_ok=True)
    factors = pd.read_parquet(PROCESSED / "ff_factors_monthly.parquet").set_index("yyyymm")
    which = sys.argv[1:] or ["1", "23"]
    if "1" in which:
        test_1(factors)
    if "23" in which:
        tests_2_and_3(factors)
    # Trace: the hash of every output and of the inputs read without a recorded hash.
    report = {"script": "scripts/robustness/1_robustness_tests.py",
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "status": "run after the out-of-sample test of version A; not out of sample",
              "tests_run": which,
              "inputs_sha256": {n: hashlib.sha256((PROCESSED / n).read_bytes()).hexdigest()
                                for n in ("ff_factors_monthly.parquet", "crsp_panel_acc.parquet")},
              "outputs_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(OUT.glob("*.csv"))}}
    (OUT / "robustness_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
