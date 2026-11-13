"""Backtest, step 2: the portfolio through time, with execution and costs.

Rules: ProjectJournal.md, section 8.4 (D13 to D23), and SignalSpec.md, section 6
("Portfolio construction", the six order rules validated on 2026-11-13, and the
commission rule D15). No reference code is copied: JKP and Tidy Finance do not
simulate a portfolio with fills and costs.

One month, for one model and one universe. The net asset value is 1 at the
end of month t; amounts are fractions of it; a fraction x is an order of
x times USD 100 million (constant nominal capital, D22).

1. Target, with the data of month t. The stocks to hold are: the stocks held
   that are in the top 20 %, and the stocks not held that are in the top 10 %
   and can start a purchase. Target weight: market equity of t over the sum of
   the stocks to hold. A stock held outside the top 20 %, outside the universe
   or no longer eligible has a target of zero. A stock held with every
   characteristic missing can be reduced, not increased.
2. Order = target - weight held, frozen with the data of t. Its size is capped
   at 10 % of the ADV (the smaller of dolvol_21d and dolvol_126d at t, both
   required: without them the order is zero). The cap was 1 % in the rules of
   2026-11-12; with one trading day a month it left 72 to 85 % of the fund in
   cash on the development years (mechanics only, no return looked at), so the
   project owner raised it to 10 % on 2026-11-13, before the freeze. The price
   impact of the course pays for the size of the order; 1 % is kept as the
   stress test.
3. First trading day of t+1. The book held earns the return of that day
   (ret_d1). An order is filled at that close only if a trade was possible
   (first_day_fills: trade price, volume, no delisting). Sales first; a sale
   cannot exceed what is held. Purchases are then paid with the cash available
   and, if it is short, all reduced by the same factor. Unfilled purchase:
   cash. Unfilled sale: position kept.
4. Costs on each fill: half spread (D14: quoted; else high-low if ranges were
   observed; else the mean of the eligible stocks of the same size group in t)
   and price impact lambda x sqrt(order / ADV) per dollar (D22; lambda 0.025
   for nano and micro, 0.015 for small, 0.010 for large and mega).
5. Rest of the month: a position earns (1 + ret) / (1 + ret_d1) - 1. Unknown
   return of a stock held: full write-off (D16). Cash earns the risk-free rate
   of the month. A stock with no row in the following month has left the
   panel: its value goes to cash (D17, delisting proceeds in the delisting
   month, which ret already holds).
6. Net return = net asset value at the end of t+1, minus 1. Gross return = net
   return + costs of the month. It is the return before the costs of that
   month on the book really held, not the return of a portfolio that never
   paid a cost (earlier costs have already reduced what was bought).

Precisions written after the audit by a separate agent (2026-11-13):
- "A trade was possible" means that CRSP records a closing trade price that
  day (flag TR). A close that is a bid-ask midpoint shows that the stock was
  quoted, perhaps traded during the day, but gives no price and no depth at
  which an order could be filled at the close: such a stock cannot be bought or
  sold in this simulation. Kept as the letter of D13 and reported.
- A stock with no size group pays the highest impact coefficient, and takes the
  highest group mean of the month when it has no spread of its own and no
  group. No eligible stock is in that case on the development years.
- The risk-free rate is paid on the cash held after the trades, for the whole
  month; the proceeds of a stock that leaves the panel earn nothing that month.
- A sale is frozen as an amount: when the price rises on the first day, a small
  remainder stays in the book. Positions above one millionth of the net asset
  value are counted apart.
- In the close-to-close comparison the number of shares of the commission
  stress uses the price of the first day of t+1, for lack of the closing price
  of t in the inputs; a trade without that price pays no commission (reported).
- The cap of 10 % of the ADV is a capacity scenario, not a proven capacity: the
  fill is tested on the presence of a trade and of a volume that day, not on
  the size of that volume, and no source validates a fill of that size at the
  last trade of the day. The result with a cap of 1 % is shown next to it.
- CRSP reports closing trade prices of the NASDAQ National Market from
  November 1982 and of the SmallCap Market from June 1992; before, the close is
  a bid-ask midpoint (flag BA) and the stock cannot be traded here.
- The target weights are value weights over all the stocks to hold, including
  those that cannot be bought: the book really held follows the volume as much
  as the market value. Concentration is reported (largest weight, effective
  number of stocks).

Comparisons run on the same code (D13, D22, D15): close-to-close execution
(trade at the close of t, always possible, full-month return); order cap at
1 % of the ADV; commission stress of 6 cents per share until 2004 and 4 cents
from 2005 (it is computed on the fills and does not change the path of the
main portfolio).

Before the strategy is frozen this script reads the development candidates
only (return months 1981-01 to 1992-12) and prints no return, no mean return
and no ratio of returns: only the mechanics (turnover, fills, cash, costs).
The test sample is refused unless the freeze record names this script.

Inputs:  portfolio_candidates_<version>_<sample>.parquet, crsp_panel_acc.parquet,
         crsp_daily_agg.parquet, first_day_fills.parquet (hashes checked)
Outputs: backtest_<version>_<sample>.parquet   one row per configuration and
             return month
         backtest_<version>_<sample>_report.json

Run from Project/:
    python scripts/backtest/2_backtest.py --selftest
    python scripts/backtest/2_backtest.py --version A --sample development
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import (PROCESSED, PROJECT, CheckError, check, check_unchanged, file_stamps,  # noqa: E402
                   publish, read_verified, sha256)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_guard  # noqa: E402

PANEL = PROCESSED / "crsp_panel_acc.parquet"
PANEL_REPORT = PROCESSED / "accounting_availability_report.json"
DAILY = PROCESSED / "crsp_daily_agg.parquet"
DAILY_REPORT = PROCESSED / "crsp_daily_agg_report.json"
FILLS = PROCESSED / "first_day_fills.parquet"
FILLS_REPORT = PROCESSED / "first_day_fills_report.json"
FREEZE = PROJECT / "resources" / "strategy_freeze.json"
SCRIPT = "scripts/backtest/2_backtest.py"

CAPITAL = 1e8                       # USD, constant nominal capital (D22)
CAP = 0.10                          # an order is at most 10 % of the ADV (D22, amended on 2026-11-13)
CAP_STRESS = 0.01                   # stress test: the former cap of 1 %
LAMBDA = {"nano": 0.025, "micro": 0.025, "small": 0.015, "large": 0.010, "mega": 0.010}
LAMBDA_UNKNOWN = 0.025              # a stock with no size group pays the highest coefficient
MODELS = ["gbrt", "ridge"]
UNIVERSES = ["all", "large"]
EXPECTED = {"development": (198012, 199211, 144), "test": (199212, 202511, 396)}
# Configurations: (name, model, universe, execution, cap). The first is the main one.
CONFIGS = ([(f"{m}_{u}_d1", m, u, "d1", CAP) for m in MODELS for u in UNIVERSES]
           + [(f"{m}_{u}_close", m, u, "close", CAP) for m in MODELS for u in UNIVERSES]
           + [(f"gbrt_{u}_d1_cap01", "gbrt", u, "d1", CAP_STRESS) for u in UNIVERSES])


def commission_per_share(return_month: int) -> float:
    # Stress of rule D15: USD 0.06 a share until 2004, 0.04 from 2005.
    return 0.06 if return_month // 100 <= 2004 else 0.04


def next_month(ym: int) -> int:
    return ym + 1 if ym % 100 < 12 else (ym // 100 + 1) * 100 + 1


def cost_rate(amount: np.ndarray, half_spread: np.ndarray, lam: np.ndarray, adv: np.ndarray
              ) -> tuple[np.ndarray, np.ndarray]:
    """Spread cost and impact cost of trades of `amount` (fractions of the capital)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        impact = np.where(amount > 0, lam * np.sqrt(amount * CAPITAL / adv), 0.0)
    return amount * half_spread, amount * impact


def step(w: np.ndarray, cash: float, f: dict, r: dict, execution: str, cap: float) -> tuple[np.ndarray, float, dict]:
    """
    Description:
        One month of the portfolio (see the header, points 1 to 6).
    Inputs (arrays over all stocks):
        w, cash  weights held and cash at the end of month t; they sum to 1.
        f        data of month t: top10, top20, can_start (bool), me, adv (USD,
                 NaN if unknown), half_spread, lam.
        r        data of month t+1: ret, ret_d1 (NaN if unknown), fill_ok (bool),
                 prc_d1 (NaN if unknown), has_next (bool: the stock has a row in
                 t+2), rf, last (bool: t+1 is the last month of the panel),
                 return_month.
    Output:
        Weights and cash at the end of t+1 (they sum to 1), and the record of the month.
    """
    invested_before = float(w.sum())                       # share of the fund invested at the end of t
    held = w > 0
    hold = (held & f["top20"]) | (~held & f["top10"] & f["can_start"])
    me = np.where(hold, f["me"], 0.0)
    total = me.sum()
    target = me / total if total > 0 else np.zeros_like(w)
    delta = target - w
    frozen = held & ~f["can_start"]                       # every characteristic missing: no increase
    delta = np.where(frozen, np.minimum(delta, 0.0), delta)
    desired = np.abs(delta)
    limit = np.where(np.isfinite(f["adv"]) & (f["adv"] > 0), cap * f["adv"] / CAPITAL, 0.0)
    order = np.minimum(desired, limit)

    if execution == "d1":
        d1 = np.where(np.isfinite(r["ret_d1"]), r["ret_d1"], 0.0)
        can_fill = r["fill_ok"]
    else:                                                  # close-to-close: trade at the close of t
        d1 = np.zeros_like(w)
        can_fill = np.ones(w.size, bool)
    h1 = w * (1.0 + d1)                                    # the book held, after the first day

    # Sales first; a sale cannot exceed what is held.
    sell = np.where((delta < 0) & can_fill, np.minimum(order, h1), 0.0)
    sp_s, im_s = cost_rate(sell, f["half_spread"], f["lam"], f["adv"])
    cash1 = cash + sell.sum() - sp_s.sum() - im_s.sum()

    # Purchases, paid with the cash available; all reduced by one factor if it is short.
    buy0 = np.where((delta > 0) & can_fill, order, 0.0)

    def paid(phi: float) -> float:
        sp, im = cost_rate(phi * buy0, f["half_spread"], f["lam"], f["adv"])
        return float(phi * buy0.sum() + sp.sum() + im.sum())

    phi = 1.0
    available = max(cash1, 0.0)
    if paid(1.0) > available:
        lo, hi = 0.0, 1.0
        for _ in range(60):                                # the cost grows with phi: bisection
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if paid(mid) <= available else (lo, mid)
        phi = lo
    buy = phi * buy0
    sp_b, im_b = cost_rate(buy, f["half_spread"], f["lam"], f["adv"])
    cash2 = cash1 - buy.sum() - sp_b.sum() - im_b.sum()
    h2 = h1 - sell + buy

    # Rest of the month. Unknown return of a stock held: full write-off (D16).
    known = np.isfinite(r["ret"])
    check(not bool(((h1 > 0) | (buy > 0))[np.isfinite(r["ret_d1"]) & (r["ret_d1"] <= -1.0)].any()) or execution != "d1",
          f"{r['return_month']}: a stock held or bought loses everything on the first day; the rule does not say what follows")
    with np.errstate(divide="ignore", invalid="ignore"):
        growth = np.where(known & (1.0 + d1 > 0), (1.0 + r["ret"]) / (1.0 + d1), 0.0)
    h3 = h2 * growth
    writeoff = float(h2[~known].sum())
    writeoff_largest = float(h2[~known].max()) if (~known).any() else 0.0
    cash3 = cash2 * (1.0 + r["rf"])
    # A stock with no row in the following month has left the panel: its value is cash.
    gone = (h3 > 0) & ~r["has_next"] & (not r["last"])
    to_cash = float(h3[gone].sum())
    late_proceeds = float(h3[gone & r["late"]].sum())      # value credited now although the amount is dated later (D17)
    h3 = np.where(gone, 0.0, h3)
    cash3 += to_cash
    nav = float(h3.sum() + cash3)

    traded = sell + buy
    with np.errstate(divide="ignore", invalid="ignore"):
        shares = np.where((traded > 0) & np.isfinite(r["prc_d1"]) & (r["prc_d1"] > 0), traded * CAPITAL / r["prc_d1"], 0.0)
    cost_spread, cost_impact = float(sp_s.sum() + sp_b.sum()), float(im_s.sum() + im_b.sum())
    invested = float(h2.sum())
    no_adv = (desired > 0) & (limit == 0)
    sp = sp_s + sp_b
    rec = {
        "invested_before": invested_before,
        "cost_spread_quoted": float(sp[f["src"] == 0].sum()), "cost_spread_high_low": float(sp[f["src"] == 1].sum()),
        "cost_spread_group_mean": float(sp[f["src"] == 2].sum()),
        "ret_net": nav - 1.0, "ret_gross": nav - 1.0 + cost_spread + cost_impact, "rf": float(r["rf"]),
        "cost_spread": cost_spread, "cost_impact": cost_impact,
        "cost_commission_stress": float(shares.sum() * commission_per_share(r["return_month"]) / CAPITAL),
        "traded_without_a_price": float(traded[(traded > 0) & ~(np.isfinite(r["prc_d1"]) & (r["prc_d1"] > 0))].sum()),
        "turnover_desired": float(desired.sum()), "turnover_after_cap": float(order.sum()),
        "turnover_filled": float(traded.sum()),
        "filled_spread_quoted": float(traded[f["src"] == 0].sum()), "filled_spread_high_low": float(traded[f["src"] == 1].sum()),
        "filled_spread_group_mean": float(traded[f["src"] == 2].sum()),
        "purchases_scaled_by": phi, "cash_after_trades": float(cash2),
        "stocks_to_hold": int(hold.sum()), "stocks_held_after_trades": int((h2 > 0).sum()),
        "stocks_held_above_1e-6": int((h2 > 1e-6).sum()),
        "orders": int((desired > 0).sum()), "orders_capped": int((desired > limit).sum()),
        "orders_without_adv": int(no_adv.sum()),
        "orders_not_filled": int(((order > 0) & ~can_fill).sum()),
        "wanted_without_adv": float(desired[no_adv].sum()),
        "wanted_not_filled": float(order[(order > 0) & ~can_fill].sum()),
        "fills_without_first_day_return": int(((traded > 0) & ~np.isfinite(r["ret_d1"])).sum()) if execution == "d1" else 0,
        "largest_weight_after_trades": float(h2.max()) if h2.size else 0.0,
        "largest_weight_of_the_invested_part": float(h2.max() / invested) if invested > 0 else 0.0,
        "effective_stocks": float(invested ** 2 / (h2 ** 2).sum()) if invested > 0 else 0.0,
        "write_off": writeoff, "write_off_largest": writeoff_largest, "left_the_panel_to_cash": to_cash,
        "late_proceeds": late_proceeds,
        "weight_frozen_no_characteristic": float(w[frozen].sum()),
    }
    return h3 / nav, cash3 / nav, rec


def simulate(months: list[dict], n: int, execution: str, cap: float) -> list[dict]:
    """Run step() over the months, from an all-cash book. months[k] = {"f": ..., "r": ...}."""
    w, cash, out = np.zeros(n), 1.0, []
    for m in months:
        w, cash, rec = step(w, cash, m["f"], m["r"], execution, cap)
        check(abs(w.sum() + cash - 1.0) < 1e-9 and w.min() >= 0 and cash > -1e-9,
              f"{m['r']['return_month']}: weights and cash do not sum to 1, or one is negative")
        check(all(math.isfinite(v) for v in rec.values()), f"{m['r']['return_month']}: a number of the record is not finite")
        rec["yyyymm"] = m["r"]["return_month"]
        rec["cash_end"] = cash
        out.append(rec)
    return out


# --------------------------------------------------------------------- real data

def read_checked(path: Path, report_path: Path, report: dict) -> pl.LazyFrame:
    earlier = json.loads(report_path.read_text(encoding="utf-8"))
    expected = earlier.get("outputs", {}).get(path.name)
    check(expected is not None and sha256(path) == expected, f"{path.name} does not match {report_path.name}")
    report["inputs"][path.name] = {"sha256": expected, "from_run": earlier["run_id"]}
    return pl.scan_parquet(path)


def load(version: str, sample: str, report: dict, expected_candidates: str | None = None) -> tuple[dict, int]:
    """
    Description:
        Everything the simulation needs, as arrays over the stocks of the sample.
    Output:
        {model_universe: list of months}, and the number of stocks.
    """
    c = pl.col
    lo, hi, n_months = EXPECTED[sample]
    name = f"portfolio_candidates_{version}_{sample}.parquet"
    if sample == "test":
        # The test candidates are read only by a run that holds the step: the hash
        # is the one recorded at the end of the candidates step.
        check(expected_candidates is not None, "The test candidates are read only through the freeze guard")
        cand = freeze_guard.read_frozen(PROCESSED / name, expected_candidates)
        report["inputs"][name] = {"sha256": expected_candidates}
    else:
        cand, run_id = read_verified(PROCESSED / name, PROCESSED / f"portfolio_candidates_{version}_{sample}_report.json")
        report["inputs"][name] = {"from_run": run_id}
    formation = cand["yyyymm"].unique().sort().to_list()
    check((formation[0], formation[-1], len(formation)) == (lo, hi, n_months), "The candidates are not the whole sample")
    ret_months = [next_month(m) for m in formation]
    after = next_month(ret_months[-1])                     # only to know which stocks still have a row

    stamps = file_stamps([PANEL, DAILY, FILLS])
    panel = (read_checked(PANEL, PANEL_REPORT, report).filter(c("yyyymm").is_between(lo, after))
             .select("permno", "yyyymm", "eom", "eligible", "ret", "me", "size_grp", "risk_free", "delamtdt").collect())
    # delamtdt is read only to report the proceeds credited before their date (D17): it changes no order.
    panel = panel.with_columns(late=(c("delamtdt") > c("eom")).fill_null(False)).drop("delamtdt", "eom")
    # The month after the last return month gives no return: only the presence of a row.
    panel = panel.with_columns(ret=pl.when(c("yyyymm") <= ret_months[-1]).then(c("ret")))
    daily = (read_checked(DAILY, DAILY_REPORT, report).filter(c("yyyymm").is_between(lo, ret_months[-1]))
             .select("permno", "yyyymm", "ret_d1", "dolvol_21d", "dolvol_126d", "spread_quoted_21d", "bidaskhl_21d",
                     "n_hl_observed_21d").collect())
    fills = (read_checked(FILLS, FILLS_REPORT, report).filter(c("yyyymm").is_between(lo, ret_months[-1]))
             .select("permno", "yyyymm", "fill_ok", "prc_d1").collect())
    check_unchanged(stamps)
    last_panel_month = pl.scan_parquet(PANEL).select(c("yyyymm").max()).collect().item()

    df = panel.join(daily, on=["permno", "yyyymm"], how="left", validate="1:1").join(
        fills, on=["permno", "yyyymm"], how="left", validate="1:1")
    check(df.height == panel.height, "A join changed the number of rows")
    # Half spread (D14): quoted; else high-low with observed ranges; else the mean
    # of the eligible stocks of the same size group and month that have one of the two.
    own = (pl.when(c("spread_quoted_21d").is_not_null()).then(c("spread_quoted_21d") / 2)
           .when(c("bidaskhl_21d").is_not_null() & (c("n_hl_observed_21d") > 0)).then(c("bidaskhl_21d") / 2))
    df = df.with_columns(__own=own)
    donors = (df.filter(c("eligible") & c("__own").is_not_null() & c("size_grp").is_not_null())
              .group_by("yyyymm", "size_grp").agg(__grp=c("__own").mean()))
    worst = donors.group_by("yyyymm").agg(__worst=c("__grp").max())
    df = df.join(donors, on=["yyyymm", "size_grp"], how="left").join(worst, on="yyyymm", how="left").with_columns(
        half_spread=pl.coalesce("__own", "__grp", "__worst"),
        spread_source=pl.when(c("spread_quoted_21d").is_not_null()).then(pl.lit("quoted"))
        .when(c("__own").is_not_null()).then(pl.lit("high_low")).otherwise(pl.lit("group_mean")),
        adv=pl.min_horizontal("dolvol_21d", "dolvol_126d").fill_null(float("nan")),
        lam=c("size_grp").replace_strict(LAMBDA, default=LAMBDA_UNKNOWN, return_dtype=pl.Float64),
        src=pl.when(c("spread_quoted_21d").is_not_null()).then(0).when(c("__own").is_not_null()).then(1).otherwise(2),
    ).with_columns(adv=pl.when(c("dolvol_21d").is_null() | c("dolvol_126d").is_null()).then(float("nan")).otherwise(c("adv")))
    check(df.filter(c("yyyymm") <= hi)["half_spread"].null_count() == 0, "A half spread is missing")
    check(df.filter((c("half_spread") < 0) | (c("adv") < 0)).height == 0, "A negative spread or ADV")

    permnos = df["permno"].unique().sort()
    n = permnos.len()
    df = df.with_columns(__i=c("permno").replace_strict(permnos, pl.Series(range(n)), return_dtype=pl.Int64)).sort("yyyymm", "__i")
    cand = cand.with_columns(__i=c("permno").replace_strict(permnos, pl.Series(range(n)), return_dtype=pl.Int64))
    by_month = {k[0]: v for k, v in df.partition_by("yyyymm", as_dict=True).items()}
    cand_by_month = {k[0]: v for k, v in cand.partition_by("yyyymm", as_dict=True).items()}
    rf = {int(k): float(v) for k, v in panel.group_by("yyyymm").agg(c("risk_free").first()).iter_rows()}
    check(all(panel.filter(c("yyyymm") == m)["risk_free"].n_unique() == 1 for m in (ret_months[0], ret_months[-1])),
          "Several risk-free rates in one month")

    def dense(frame: pl.DataFrame, col: str, fill, dtype=float) -> np.ndarray:
        a = np.full(n, fill, dtype=dtype)
        a[frame["__i"].to_numpy()] = frame[col].fill_null(fill).to_numpy() if frame[col].null_count() else frame[col].to_numpy()
        return a

    data = {f"{m}_{u}": [] for m in MODELS for u in UNIVERSES}
    for t, m in zip(formation, ret_months):
        ft, rt, ct = by_month[t], by_month[m], cand_by_month[t]
        nxt = by_month[next_month(m)]["__i"].to_numpy() if next_month(m) in by_month else np.empty(0, np.int64)
        has_next = np.zeros(n, bool)
        has_next[nxt] = True
        common_f = {"can_start": dense(ct, "can_start", False, bool), "me": dense(ft, "me", 0.0),
                    "adv": dense(ft, "adv", np.nan), "half_spread": dense(ft, "half_spread", 0.0),
                    "lam": dense(ft, "lam", LAMBDA_UNKNOWN), "src": dense(ft, "src", 2, np.int64)}
        r = {"ret": dense(rt, "ret", np.nan), "ret_d1": dense(rt, "ret_d1", np.nan),
             "fill_ok": dense(rt, "fill_ok", False, bool), "prc_d1": dense(rt, "prc_d1", np.nan),
             "has_next": has_next, "late": dense(rt, "late", False, bool), "rf": rf[m], "last": m >= last_panel_month, "return_month": m}
        for key in data:
            f = dict(common_f, top10=dense(ct, f"top10_{key}", False, bool), top20=dense(ct, f"top20_{key}", False, bool))
            data[key].append({"f": f, "r": r})

    el = df.filter(c("eligible") & (c("yyyymm") <= hi))
    report["cost_inputs_eligible"] = {
        "stock_months": el.height,
        "spread_source": {k: v for k, v in el["spread_source"].value_counts().sort("spread_source").iter_rows()},
        "without_adv": int(el["adv"].is_nan().sum()),
        "half_spread_median": float(el["half_spread"].median()), "half_spread_p95": float(el["half_spread"].quantile(0.95))}
    report["stocks"] = n
    report["return_months"] = [ret_months[0], ret_months[-1], len(ret_months)]
    return data, n


def run(version: str, sample: str, retry: bool = False) -> None:
    check(sample in EXPECTED, f"Unknown sample {sample}")
    reservation, expected = None, None
    report: dict = {"script": SCRIPT, "version": version, "sample": sample, "inputs": {}}
    report["script_sha256"] = sha256(Path(__file__))
    if sample == "test":
        report["freeze"] = freeze_guard.require_freeze(
            SCRIPT, version, [PROCESSED / f"backtest_{version}_test.parquet", PROCESSED / f"backtest_{version}_test_report.json"])
        expected = freeze_guard.completed_output("candidates", version, report["freeze"],
                                                 f"portfolio_candidates_{version}_test.parquet")
        reservation = freeze_guard.reserve("backtest", version, report["freeze"], retry)
    data, n = load(version, sample, report, expected)

    frames, mechanics = [], {}
    for name, model, universe, execution, cap in CONFIGS:
        recs = simulate(data[f"{model}_{universe}"], n, execution, cap)
        t = pl.DataFrame(recs).with_columns(
            version=pl.lit(version), config=pl.lit(name), model=pl.lit(model), universe=pl.lit(universe),
            execution=pl.lit(execution), cap=pl.lit(cap), yyyymm=pl.col("yyyymm").cast(pl.Int32))
        frames.append(t)
        # Mechanics only: nothing here is a return of the strategy.
        skip = t.slice(12)                                 # after the first year, when the book is built
        mechanics[name] = {
            "turnover_desired_mean": float(skip["turnover_desired"].mean()),
            "turnover_after_cap_mean": float(skip["turnover_after_cap"].mean()),
            "turnover_filled_mean": float(skip["turnover_filled"].mean()),
            "cash_after_trades_mean": float(skip["cash_after_trades"].mean()),
            "cash_after_trades_max": float(t["cash_after_trades"].max()),
            "stocks_to_hold_median": float(skip["stocks_to_hold"].median()),
            "stocks_held_median": float(skip["stocks_held_after_trades"].median()),
            "share_of_orders_capped": float(skip["orders_capped"].sum() / max(1, skip["orders"].sum())),
            "share_of_orders_not_filled": float(skip["orders_not_filled"].sum() / max(1, skip["orders"].sum())),
            "largest_weight_max": float(t["largest_weight_after_trades"].max()),
            "largest_weight_of_the_invested_part_median": float(skip["largest_weight_of_the_invested_part"].median()),
            "effective_stocks_median": float(skip["effective_stocks"].median()),
            "stocks_held_above_1e-6_median": float(skip["stocks_held_above_1e-6"].median()),
            "share_of_orders_without_adv": float(skip["orders_without_adv"].sum() / max(1, skip["orders"].sum())),
            "share_of_filled_by_spread_source": {
                k: float(skip[f"filled_spread_{k}"].sum() / max(1e-300, skip["turnover_filled"].sum()))
                for k in ("quoted", "high_low", "group_mean")},
            "fills_without_first_day_return": int(t["fills_without_first_day_return"].sum()),
            "late_proceeds_total": float(t["late_proceeds"].sum()),
            "cash_after_trades_by_year": {str(int(y)): round(float(v), 4) for y, v in t.group_by(
                (pl.col("yyyymm") // 100).alias("y")).agg(pl.col("cash_after_trades").mean()).sort("y").iter_rows()},
            "cost_spread_bp_per_month": float(skip["cost_spread"].mean() * 1e4),
            "cost_impact_bp_per_month": float(skip["cost_impact"].mean() * 1e4),
            "commission_stress_bp_per_month": float(skip["cost_commission_stress"].mean() * 1e4),
            "months_with_a_write_off": int((t["write_off"] > 0).sum()), "write_off_max": float(t["write_off"].max()),
            "months_purchases_scaled": int((t["purchases_scaled_by"] < 1).sum())}
    out = pl.concat(frames)
    first = ["version", "config", "model", "universe", "execution", "cap", "yyyymm"]
    out = out.select(*first, pl.exclude(first)).sort("config", "yyyymm")
    check(out.select("config", "yyyymm").is_unique().all(), "Duplicate month in a configuration")
    report["configurations"] = [cfg[0] for cfg in CONFIGS]
    report["mechanics_after_the_first_year"] = mechanics
    report["note"] = ("Development years: these returns are not out of sample and are never a result. "
                      "No return statistic is computed or printed by this script.")
    publish({PROCESSED / f"backtest_{version}_{sample}.parquet": out}, report,
            PROCESSED / f"backtest_{version}_{sample}_report.json")
    if reservation is not None:
        freeze_guard.finish(reservation, PROCESSED / f"backtest_{version}_{sample}_report.json")
    print(f"backtest_{version}_{sample}: {len(CONFIGS)} configurations, {out['yyyymm'].n_unique()} months.")
    for name in ("gbrt_all_d1", "gbrt_large_d1", "gbrt_all_close", "gbrt_all_d1_cap01"):
        k = mechanics[name]
        print(f"  {name}: {k['stocks_to_hold_median']:.0f} stocks to hold, {k['stocks_held_median']:.0f} held; turnover a "
              f"month {k['turnover_desired_mean']:.1%} wanted, {k['turnover_after_cap_mean']:.1%} after the cap, "
              f"{k['turnover_filled_mean']:.1%} filled; cash {k['cash_after_trades_mean']:.1%}; largest weight "
              f"{k['largest_weight_max']:.1%}, {k['effective_stocks_median']:.0f} effective stocks; costs a month "
              f"{k['cost_spread_bp_per_month']:.1f} bp spread, {k['cost_impact_bp_per_month']:.1f} bp impact, "
              f"{k['commission_stress_bp_per_month']:.1f} bp commission stress")
    print(f"Run {report['run_id']}. Report saved. No return was printed.")


# ------------------------------------------------------------------ synthetic tests

def _f(n, **kw):
    base = {"top10": np.zeros(n, bool), "top20": np.zeros(n, bool), "can_start": np.ones(n, bool), "me": np.ones(n),
            "adv": np.full(n, 1e15), "half_spread": np.zeros(n), "lam": np.zeros(n), "src": np.zeros(n, np.int64)}
    base.update({k: np.asarray(v) for k, v in kw.items()})
    return base


def _r(n, **kw):
    base = {"ret": np.zeros(n), "ret_d1": np.zeros(n), "fill_ok": np.ones(n, bool), "prc_d1": np.full(n, 10.0),
            "has_next": np.ones(n, bool), "late": np.zeros(n, bool), "rf": 0.0, "last": False, "return_month": 200002}
    base.update({k: (np.asarray(v) if isinstance(v, (list, np.ndarray)) else v) for k, v in kw.items()})
    return base


def selftest() -> None:
    """Months written by hand, then random books: no project data is read."""
    close = lambda a, b: abs(a - b) < 1e-9  # noqa: E731
    # The numbers of the rules, written here again.
    check(CAP == 0.10 and CAP_STRESS == 0.01 and CAPITAL == 1e8, "selftest: the cap or the capital is not the one of the rules")
    check(LAMBDA == {"nano": 0.025, "micro": 0.025, "small": 0.015, "large": 0.010, "mega": 0.010}, "selftest: lambda")
    check(commission_per_share(200412) == 0.06 and commission_per_share(200501) == 0.04 and commission_per_share(199301) == 0.06
          and commission_per_share(202512) == 0.04, "selftest: commission schedule")

    # 1) First purchase, paid with all the cash. Half spread 1 %: phi x 1.01 = 1.
    #    First-day return 2 %, month 10 %: the position earns 1.10 / 1.02 - 1.
    w, cash, rec = step(np.zeros(1), 1.0, _f(1, top10=[True], half_spread=[0.01]),
                        _r(1, ret=[0.10], ret_d1=[0.02]), "d1", CAP)
    b = 1 / 1.01
    check(close(rec["turnover_filled"], b) and close(rec["cost_spread"], 0.01 * b) and close(rec["cash_after_trades"], 0.0),
          f"selftest 1: purchase {rec}")
    check(close(rec["ret_net"], b * 1.10 / 1.02 - 1) and close(w[0], 1.0) and close(cash, 0.0), f"selftest 1: return {rec}")
    check(close(rec["ret_gross"], rec["ret_net"] + 0.01 * b), "selftest 1: gross return")
    # Commission stress: b x 100 M / price 10 = shares, x 0.06 / 100 M.
    check(close(rec["cost_commission_stress"], b / 10.0 * 0.06), f"selftest 1: commission {rec}")
    #    The same month in 2005: 4 cents a share. Without a price: no commission, and the amount is reported.
    _, _, rec5 = step(np.zeros(1), 1.0, _f(1, top10=[True], half_spread=[0.01]),
                      _r(1, ret=[0.10], ret_d1=[0.02], return_month=200502), "d1", CAP)
    check(close(rec5["cost_commission_stress"], b / 10.0 * 0.04), f"selftest 1: commission of 2005 {rec5}")
    _, _, recp = step(np.zeros(1), 1.0, _f(1, top10=[True], half_spread=[0.01]),
                      _r(1, ret=[0.10], ret_d1=[0.02], prc_d1=[np.nan]), "d1", CAP)
    check(recp["cost_commission_stress"] == 0 and close(recp["traded_without_a_price"], b), f"selftest 1: no price {recp}")
    #    No first-day return but a fill: the position earns the whole month, and the case is counted.
    _, _, recd = step(np.zeros(1), 1.0, _f(1, top10=[True]), _r(1, ret=[0.10], ret_d1=[np.nan]), "d1", CAP)
    check(close(recd["ret_net"], 0.10) and recd["fills_without_first_day_return"] == 1, f"selftest 1: no first-day return {recd}")
    #    Spread source of the fill, concentration of the book.
    check(rec["invested_before"] == 0 and close(rec["cost_spread_quoted"], 0.01 * b) and rec["cost_spread_high_low"] == 0,
          f"selftest 1: invested share and cost by source {rec}")
    check(close(rec["filled_spread_quoted"], b) and rec["filled_spread_high_low"] == 0 and close(rec["effective_stocks"], 1.0)
          and close(rec["largest_weight_of_the_invested_part"], 1.0), f"selftest 1: sources and concentration {rec}")

    # 2) The same order with no trade on the first day: all cash, which earns the risk-free rate.
    w, cash, rec = step(np.zeros(1), 1.0, _f(1, top10=[True]), _r(1, ret=[0.10], fill_ok=[False], rf=0.004), "d1", CAP)
    check(close(rec["ret_net"], 0.004) and w[0] == 0 and rec["orders_not_filled"] == 1, f"selftest 2: {rec}")
    #    Close-to-close: the order is filled and earns the whole month.
    w, cash, rec = step(np.zeros(1), 1.0, _f(1, top10=[True]), _r(1, ret=[0.10], ret_d1=[0.02], fill_ok=[False]), "close", CAP)
    check(close(rec["ret_net"], 0.10), f"selftest 2: close-to-close {rec}")

    # 3) A sale capped by the ADV. Held 100 %, outside the top 20 %. ADV 3 billion:
    #    1 % = 30 million = 0.3 of the capital. Impact 0.01 x sqrt(0.01) = 0.001 per dollar.
    #    Month -50 %, risk-free 1 %.
    w, cash, rec = step(np.ones(1), 0.0, _f(1, adv=[3e9], lam=[0.01]), _r(1, ret=[-0.5], rf=0.01), "d1", 0.01)
    check(close(rec["turnover_desired"], 1.0) and close(rec["turnover_after_cap"], 0.3) and rec["orders_capped"] == 1
          and close(rec["invested_before"], 1.0),
          f"selftest 3: cap {rec}")
    check(close(rec["cost_impact"], 0.0003) and close(rec["cash_after_trades"], 0.2997), f"selftest 3: impact {rec}")
    nav = 0.7 * 0.5 + 0.2997 * 1.01
    check(close(rec["ret_net"], nav - 1) and close(w[0], 0.35 / nav) and close(cash, 0.2997 * 1.01 / nav), f"selftest 3: {rec}")
    #    With a cap of 0.5 %, half as much is sold.
    _, _, rec05 = step(np.ones(1), 0.0, _f(1, adv=[3e9], lam=[0.01]), _r(1, ret=[-0.5], rf=0.01), "d1", 0.005)
    check(close(rec05["turnover_after_cap"], 0.15), "selftest 3: stress cap")
    #    Without an ADV the order is zero and the position is kept.
    _, _, rec0 = step(np.ones(1), 0.0, _f(1, adv=[np.nan]), _r(1), "d1", CAP)
    check(rec0["turnover_filled"] == 0 and rec0["stocks_held_after_trades"] == 1, "selftest 3: no ADV")

    # 4) Unknown return of a stock held: full write-off.
    w, cash, rec = step(np.array([0.6, 0.4]), 0.0, _f(2, top20=[True, True], me=[6.0, 4.0]),
                        _r(2, ret=[np.nan, 0.0]), "d1", CAP)
    check(close(rec["write_off"], 0.6) and close(rec["write_off_largest"], 0.6) and close(rec["ret_net"], -0.6)
          and close(w[1], 1.0) and close(rec["effective_stocks"], 1 / (0.36 + 0.16)), f"selftest 4: {rec}")
    # 5) A stock with no row in the following month: its value goes to cash.
    w, cash, rec = step(np.array([0.6, 0.4]), 0.0, _f(2, top20=[True, True], me=[6.0, 4.0]),
                        _r(2, ret=[0.5, 0.0], has_next=[False, True]), "d1", CAP)
    check(close(rec["left_the_panel_to_cash"], 0.9) and close(cash, 0.9 / 1.3) and w[0] == 0 and rec["late_proceeds"] == 0,
          f"selftest 5: {rec}")
    _, _, recl = step(np.array([0.6, 0.4]), 0.0, _f(2, top20=[True, True], me=[6.0, 4.0]),
                      _r(2, ret=[0.5, 0.0], has_next=[False, True], late=[True, False]), "d1", CAP)
    check(close(recl["late_proceeds"], 0.9), f"selftest 5: late proceeds {recl}")
    #    Not on the last month of the panel.
    w, cash, rec = step(np.array([0.6, 0.4]), 0.0, _f(2, top20=[True, True], me=[6.0, 4.0]),
                        _r(2, ret=[0.5, 0.0], has_next=[False, False], last=True), "d1", CAP)
    check(rec["left_the_panel_to_cash"] == 0 and close(w[0], 0.9 / 1.3), "selftest 5: last month")

    # 6) Buffer and value weights. Three stocks, market equity 50, 30, 20.
    #    A is held and in the top 20 % only: kept. B is not held and in the top
    #    20 % only: not bought. C is not held and in the top 10 %: bought.
    #    Target: A 50 / 70, C 20 / 70.
    w, cash, rec = step(np.array([0.5, 0.0, 0.0]), 0.5,
                        _f(3, top10=[False, False, True], top20=[True, True, True], me=[50.0, 30.0, 20.0]), _r(3), "d1", CAP)
    check(close(w[0], 50 / 70) and w[1] == 0 and close(w[2], 20 / 70) and rec["stocks_to_hold"] == 2, f"selftest 6: {w}")
    #    A stock with every characteristic missing: not bought; if held, kept, never increased.
    w, cash, rec = step(np.zeros(2), 1.0, _f(2, top10=[True, True], top20=[True, True], can_start=[False, True]), _r(2), "d1", CAP)
    check(w[0] == 0 and close(w[1], 1.0), f"selftest 6: can_start {w}")
    w, cash, rec = step(np.array([0.2, 0.0]), 0.8, _f(2, top20=[True, False], can_start=[False, True]), _r(2), "d1", CAP)
    check(close(w[0], 0.2) and close(cash, 0.8) and close(rec["weight_frozen_no_characteristic"], 0.2), f"selftest 6: frozen {w}")
    #    A sale larger than the position after a fall on the first day: sells what is there.
    w, cash, rec = step(np.array([1.0]), 0.0, _f(1), _r(1, ret=[-0.5], ret_d1=[-0.5]), "d1", CAP)
    check(close(rec["turnover_filled"], 0.5) and close(rec["ret_net"], -0.5) and w[0] == 0, f"selftest 6: sale {rec}")

    # 7) Purchases larger than the cash: all reduced by one factor. The sale of A is
    #    capped at 0.1; B and C want 0.5 each; cash 0.1: each gets 0.05.
    w, cash, rec = step(np.array([1.0, 0.0, 0.0]), 0.0,
                        _f(3, top10=[False, True, True], top20=[False, True, True], adv=[1e9, 1e15, 1e15]), _r(3), "d1", 0.01)
    check(close(rec["purchases_scaled_by"], 0.1) and close(w[1], 0.05) and close(w[2], 0.05) and close(w[0], 0.9),
          f"selftest 7: {w} {rec}")

    #    The same with a price impact: the cost is not proportional to the amount, the
    #    factor is no longer 0.1. Cash 0.1, two purchases x each at lambda 0.02 and
    #    ADV 1e9: 2 x (1 + 0.02 sqrt(x 1e8 / 1e9)) = 0.1.
    w, cash, rec = step(np.array([1.0, 0.0, 0.0]), 0.0,
                        _f(3, top10=[False, True, True], top20=[False, True, True], adv=[1e9, 1e9, 1e9], lam=[0.0, 0.02, 0.02]),
                        _r(3), "d1", 0.01)
    x = (rec["turnover_filled"] - 0.1) / 2                 # each purchase, the sale being 0.1
    check(close(2 * x * (1 + 0.02 * math.sqrt(x * 1e8 / 1e9)), 0.1) and close(w[1], w[2]) and x < 0.05 and close(cash, 0.0)
          and close(rec["purchases_scaled_by"], x / 0.1), f"selftest 7: funding with a price impact {w} {cash} {rec}")
    check(close(rec["orders_without_adv"], 0) and rec["orders_capped"] == 3, f"selftest 7: counts {rec}")
    #    An order without ADV is counted apart.
    _, _, reca = step(np.zeros(2), 1.0, _f(2, top10=[True, True], adv=[np.nan, 1e15]), _r(2), "d1", CAP)
    check(reca["orders_without_adv"] == 1 and close(reca["wanted_without_adv"], 0.5), f"selftest 7: no ADV {reca}")

    # 8) Random books over 30 months: the accounts hold, and no month depends on a later one.
    rng = np.random.default_rng(7)
    n = 60

    def month(k: int) -> dict:
        t10 = rng.uniform(size=n) < 0.15
        f = _f(n, top10=t10, top20=t10 | (rng.uniform(size=n) < 0.15), can_start=rng.uniform(size=n) < 0.95,
               me=rng.lognormal(3, 1.5, n), adv=np.where(rng.uniform(size=n) < 0.9, rng.lognormal(18, 2, n), np.nan),
               half_spread=rng.uniform(0, 0.03, n), lam=rng.choice([0.025, 0.015, 0.010], n), src=rng.integers(0, 3, n))
        ret = rng.normal(0.01, 0.1, n)
        ret[rng.uniform(size=n) < 0.02] = np.nan
        r = _r(n, ret=ret, ret_d1=np.where(rng.uniform(size=n) < 0.9, rng.normal(0, 0.02, n), np.nan),
               fill_ok=rng.uniform(size=n) < 0.85, prc_d1=rng.lognormal(3, 1, n), has_next=rng.uniform(size=n) < 0.98,
               rf=0.003, return_month=200001 + k)
        return {"f": f, "r": r}

    months = [month(k) for k in range(30)]
    base = simulate(months, n, "d1", CAP)
    check(all(q["cost_spread"] >= 0 and q["cost_impact"] >= 0 and q["turnover_filled"] <= q["turnover_after_cap"] + 1e-12
              and q["turnover_after_cap"] <= q["turnover_desired"] + 1e-12 and q["cash_after_trades"] > -1e-9 for q in base),
          "selftest 8: an account does not hold")
    # Later months changed: the earlier records are the same, to the last digit.
    later = [dict(m) for m in months]
    for k in range(20, 30):
        later[k] = month(100 + k)
    again = simulate(later, n, "d1", CAP)
    check(base[:20] == again[:20] and base[20:] != again[20:], "selftest 8: a month depends on a later month")
    # The orders of t use nothing of t+1: other returns and fills of one month
    # leave its orders as they were, and change its result.
    k = 12
    other = [dict(m) for m in months]
    other[k] = {"f": months[k]["f"], "r": _r(n, ret=rng.normal(0, 0.1, n), ret_d1=rng.normal(0, 0.02, n),
                                              fill_ok=rng.uniform(size=n) < 0.5, rf=0.003, return_month=200001 + k)}
    alt = simulate(other, n, "d1", CAP)
    same_orders = all(base[k][x] == alt[k][x] for x in ("turnover_desired", "turnover_after_cap", "orders", "orders_capped",
                                                         "stocks_to_hold"))
    check(same_orders and base[k]["ret_net"] != alt[k]["ret_net"], "selftest 8: the orders of t use data of t+1")
    # Close-to-close and the stress cap run on the same months.
    c2c, c05 = simulate(months, n, "close", CAP), simulate(months, n, "d1", CAP_STRESS)
    check(all(q["orders_not_filled"] == 0 for q in c2c), "selftest 8: an order is not filled at the close")
    check(sum(q["turnover_after_cap"] for q in c05) < sum(q["turnover_after_cap"] for q in base), "selftest 8: stress cap")
    print("selftest passed: eight hand-written months (purchase, no fill, cap, write-off, exit to cash, buffer,")
    print("  funding of purchases) and random books (accounts, no dependence on later months).")
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
