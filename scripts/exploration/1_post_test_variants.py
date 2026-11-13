"""POST-TEST EXPLORATION. Not out of sample, not part of the frozen test.

Written on 2026-11-13 AFTER the single out-of-sample test of version A was read
(freeze ee22d6708bdc; main result: alpha of -5.09 % a year, t = -5.13). Every
variant below was run on 1993-2025 with that result known: its numbers are
in-sample explorations of why the strategy fails, never a test.

What it does: runs the frozen monthly step (scripts/backtest/2_backtest.py,
imported unchanged, never edited) on the frozen candidates of version A, and
changes only what is passed to it:
  every    trade only every k-th month (counted from the first month, December
           1992); in the other months no order is sent;
  wcap     cap on a target weight (value weights, excess redistributed in
           proportion to market equity);
  patience a stock held is kept while it was in the top 20 % in at least one of
           the last p months (p = 1 is the frozen rule).
Execution (first day), order cap (10 % of the ADV), costs, returns and the
alpha regression are those of the frozen chain. The baseline (every 1, no cap,
patience 1) must reproduce backtest_A_test.parquet exactly, or the script stops.

Run from Project/:  python scripts/exploration/1_post_test_variants.py
Outputs: reports/exploration/post_test_variants_A.csv, post_test_variants_A_monthly.csv
"""
import importlib.util
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
STEPS = ROOT / "resources" / "test_steps"
OUT = ROOT / "reports" / "exploration"
VERSION = "A"
FF5_MOM = ["mkt_excess_ff5", "smb_ff5", "hml_ff5", "rmw", "cma", "mom"]
PERIODS = {"1993-2025": (199301, 202512), "1993-2008": (199301, 200812), "2009-2025": (200901, 202512)}

spec = importlib.util.spec_from_file_location("frozen_backtest", ROOT / "scripts" / "backtest" / "2_backtest.py")
bt = importlib.util.module_from_spec(spec)
sys.modules["frozen_backtest"] = bt
spec.loader.exec_module(bt)


def done_record(step: str) -> dict:
    done = [r for r in (json.loads(p.read_text(encoding="utf-8"))
                        for p in sorted(STEPS.glob(f"*_{VERSION}_{step}.attempt*.json"))) if r.get("status") == "done"]
    if len(done) != 1:
        raise SystemExit(f"{step}: {len(done)} completed attempts, expected 1")
    return done[0]


def capped_weights(me: np.ndarray, cap: float) -> np.ndarray:
    """Value weights with no weight above cap; the excess goes to the others in proportion to market equity."""
    w = me / me.sum()
    fixed = np.zeros(me.size, bool)
    for _ in range(200):
        over = (w > cap + 1e-15) & ~fixed
        if not over.any():
            return w
        fixed |= over
        free = ~fixed & (me > 0)
        if not free.any() or fixed.sum() * cap > 1:
            raise SystemExit("weight cap not feasible")
        w = np.where(fixed, cap, 0.0)
        w[free] = (1.0 - fixed.sum() * cap) * me[free] / me[free].sum()
    raise SystemExit("weight cap did not converge")


def simulate(months: list[dict], n: int, every: int, wcap: float | None, patience: int) -> pd.DataFrame:
    w, cash, out = np.zeros(n), 1.0, []
    recent: list[np.ndarray] = []
    for k, m in enumerate(months):
        f = dict(m["f"])
        recent = (recent + [m["f"]["top20"]])[-patience:]
        f["top20"] = np.logical_or.reduce(recent)
        if wcap is not None:
            held = w > 0
            hold = (held & f["top20"]) | (~held & f["top10"] & f["can_start"])   # as in the frozen step
            me = np.where(hold, f["me"], 0.0)
            if me.sum() > 0:
                f["me"] = np.where(hold, capped_weights(me, wcap), 0.0)
        trade = k % every == 0
        w, cash, rec = bt.step(w, cash, f, m["r"], "d1", bt.CAP if trade else 0.0)
        if abs(w.sum() + cash - 1.0) > 1e-9 or w.min() < 0 or cash < -1e-9:
            raise SystemExit(f"{m['r']['return_month']}: weights and cash do not sum to 1")
        rec["yyyymm"] = m["r"]["return_month"]
        out.append(rec)
    return pd.DataFrame(out)


def hac(y: np.ndarray, x: np.ndarray | None) -> tuple[float, float]:
    z = np.ones((y.size, 1)) if x is None else sm.add_constant(x, has_constant="add")
    fit = sm.OLS(y, z).fit(cov_type="HAC", cov_kwds={"maxlags": 6, "use_correction": False})
    return float(fit.params[0]), float(fit.tvalues[0])


def main() -> None:
    expected = done_record("candidates")["outputs_sha256"][f"portfolio_candidates_{VERSION}_test.parquet"]
    data, n = bt.load(VERSION, "test", {"inputs": {}}, expected)
    factors = pd.read_parquet(PROCESSED / "ff_factors_monthly.parquet").set_index("yyyymm")

    # The baseline must be the frozen result, month by month.
    frozen = pd.read_parquet(io.BytesIO((PROCESSED / f"backtest_{VERSION}_test.parquet").read_bytes()))
    for key in ("gbrt_all", "ridge_all"):
        base = simulate(data[key], n, 1, None, 1)
        ref = frozen[frozen.config == f"{key}_d1"].sort_values("yyyymm")
        if not (np.array_equal(base.yyyymm.to_numpy(), ref.yyyymm.to_numpy())
                and np.array_equal(base.ret_net.to_numpy(), ref.ret_net.to_numpy())):
            raise SystemExit(f"{key}: the baseline does not reproduce the frozen backtest")
    print("Baseline reproduces the frozen backtest exactly (gbrt_all_d1, ridge_all_d1).")

    variants = ([(e, c, 1) for e in (1, 3, 6, 12) for c in (None, 0.05)]
                + [(1, None, p) for p in (3, 6, 12)] + [(3, None, 3), (3, 0.05, 3)])
    rows, monthly = [], []
    for key in ("gbrt_all", "gbrt_large", "ridge_all", "ridge_large"):
        for every, wcap, patience in variants:
            t = simulate(data[key], n, every, wcap, patience)
            fx = factors.loc[t.yyyymm]
            t["variant"] = f"{key}|every{every}|wcap{wcap}|patience{patience}"
            monthly.append(t[["variant", "yyyymm", "ret_net", "ret_gross", "rf", "cost_spread", "cost_impact",
                              "turnover_filled", "cash_after_trades", "effective_stocks"]])
            for period, (lo, hi) in PERIODS.items():
                s = ((t.yyyymm >= lo) & (t.yyyymm <= hi)).to_numpy()
                net, gross = (t.ret_net - t.rf).to_numpy()[s], (t.ret_gross - t.rf).to_numpy()[s]
                x = fx[FF5_MOM].to_numpy()[s]
                a_net, t_net = hac(net, x)
                a_gross, t_gross = hac(gross, x)
                d, t_d = hac(net - fx["mkt_excess"].to_numpy()[s], None)
                rows.append({
                    "model_universe": key, "every_months": every, "weight_cap": wcap, "patience_months": patience,
                    "period": period, "post_test_exploration": True,
                    "excess_return_gross_annual": 12 * gross.mean(), "excess_return_net_annual": 12 * net.mean(),
                    "sharpe_net_annual": np.sqrt(12) * net.mean() / net.std(ddof=1),
                    "market_excess_return_annual": 12 * fx["mkt_excess"].to_numpy()[s].mean(),
                    "net_minus_market_annual": 12 * d, "t_net_minus_market": t_d,
                    "alpha_ff5mom_gross_annual": 12 * a_gross, "t_alpha_gross": t_gross,
                    "alpha_ff5mom_net_annual": 12 * a_net, "t_alpha_net": t_net,
                    "cost_bp_month": 1e4 * (t.cost_spread + t.cost_impact)[s].mean(),
                    "turnover_filled_month": t.turnover_filled[s].mean(),
                    "cash_after_trades_mean": t.cash_after_trades[s].mean(),
                    "effective_stocks_median": t.effective_stocks[s].median(),
                    "largest_weight_max": t.largest_weight_after_trades[s].max()})
    OUT.mkdir(parents=True, exist_ok=True)
    res = pd.DataFrame(rows)
    res.to_csv(OUT / f"post_test_variants_{VERSION}.csv", index=False, lineterminator="\n")
    pd.concat(monthly).to_csv(OUT / f"post_test_variants_{VERSION}_monthly.csv", index=False, lineterminator="\n")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    show = res[res.period == "1993-2025"].copy()
    for c in [c for c in show.columns if c.endswith("_annual") or c in ("turnover_filled_month", "cash_after_trades_mean",
                                                                       "largest_weight_max")]:
        show[c] = (100 * show[c]).round(2)
    print(show.drop(columns=["period", "post_test_exploration", "market_excess_return_annual"]).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
