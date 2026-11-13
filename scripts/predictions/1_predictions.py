"""Predictions: expected excess return of month t+1 for every eligible stock-month.

Method: Gu, Kelly and Xiu (2020), "Empirical asset pricing via machine learning",
sample splitting of their section 2 (training sample that grows by one year,
validation window of fixed length that rolls, one fit per year). No reference
code is copied: JKP and Tidy Finance do not fit prediction models.

Rules (SignalSpec.md, section 6, rules of 2026-11-13, and section 7, decision 2):
- Target: ret_exc_lead1 of the panel, as it is. It is read as the target only.
- Inputs: the ranks and missing flags of signal_ranks.parquet. Version A: the
  59 market characteristics (118 inputs). Version B: all 194 (388 inputs).
- One fit on all eligible stocks, every stock-month with the same weight.
- Calendar. A row is dated by the month of its target return: the row of
  December 1992 belongs to the return year 1993. For the return year Y (1993 to
  2025): training on the return years 1963 to Y - 13, validation on Y - 12 to
  Y - 1. The model that predicts is the one fitted on the training sample with
  the values chosen on the validation sample; it is not fitted again on both
  (GKX). The model of year Y therefore does not learn from the returns of the
  twelve years before Y, which only choose its values.
- Training and validation rows: eligible stock-months with a known target.
  Predictions: every eligible stock-month, whether its next return is known or not.
- Date at which a target is known (after the audit by Astra of 2026-11-13). The
  return of a delisting month can rest on an amount paid later (delamtdt) or on
  a price of a later date (delnextdt). A target is known at the end of the
  latest of: its return month, the month of delamtdt, the month of delnextdt.
  The fit of the return year Y is made at the end of December Y - 1: it uses,
  in training and in validation, only the targets known by then. A target that
  becomes known later enters the later fits. The value of the target and the
  rows that are predicted do not change. A delisting return with no date of
  amount (among them the -30 % imputation of rule D3) is dated at its month.
- Main model: gradient-boosted trees, LightGBM. Squared error, learning rate
  0.03, depth in {1, 2, 3} with 2^depth leaves, trees in {50, 100, 200} read
  from one fit of 200, at least 0.1 % of the training rows per leaf, no
  sampling of rows or columns in the fit, no other penalty, every setting
  written below. The bins of the inputs are built from training rows only: all
  of them up to 500,000, a random sample of 500,000 with a fixed seed above
  (LightGBM's own default is 200,000; building them from every row needs more
  memory than the machine has).
- Robustness model: ridge regression, mean squared error + lambda x sum of the
  squared coefficients, constant not penalised, inputs as they are, lambda in
  {1e-4, ..., 100}.
- Choice of the values: mean over the validation months of the monthly mean
  squared error. Ties: smaller depth then fewer trees; larger lambda.
- The return years 1981 to 1992 also get predictions, from the models of the
  return year 1993 (fitted on 1963-1980). They are NOT out of sample (their
  values were chosen on these very years): they only serve to develop the
  portfolio and cost code, and are labelled "development".

What the script never shows. It computes no statistic that relates a prediction
to the return it predicts. The validation losses are needed to choose the
values, but from the return year 1994 on their window reaches into 1993-2025:
they would tell a reader how well the models predict in the test period. So
the values chosen and the validation losses of every year go to a separate
table, predictions_<version>_choices_sealed.parquet, which is not to be opened
before the strategy is frozen; the report and the screen show them for the
return year 1993 only (validation on 1981-1992).

Reproducibility: the fit of the trees is deterministic (fixed seed and threads).
The sums of the ridge depend on the number of threads of the linear algebra
library at the 17th decimal; the parquet outputs are expected to be identical
between two runs on this machine, which is checked after the run.

Inputs:  data/processed/signal_ranks.parquet (hash checked against the report
         of signals 3), crsp_panel_acc.parquet (hash checked against step 8)
Outputs: predictions_<version>_development.parquet   return years 1981-1992: the only
                                         file that the portfolio and cost code may
                                         read before the strategy is frozen
         predictions_<version>_test.parquet   return years 1993-2025
                                         both: permno, yyyymm, eom, return_year,
                                         sample, pred_gbrt, pred_ridge
         predictions_<version>_choices_sealed.parquet   (see above)
         predictions_<version>_report.json  settings, rows, hashes (written last)

Run from Project/:
    python scripts/predictions/1_predictions.py --selftest      (random numbers only)
    python scripts/predictions/1_predictions.py --version A --dry-run   (reads, checks, no fit)
    python scripts/predictions/1_predictions.py --version A
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import (PROCESSED, PROJECT, CheckError, check, check_unchanged, file_stamps,  # noqa: E402
                   publish, sha256)

PANEL = PROCESSED / "crsp_panel_acc.parquet"
PANEL_REPORT = PROCESSED / "accounting_availability_report.json"
RANKS = PROCESSED / "signal_ranks.parquet"
RANKS_REPORT = PROCESSED / "signal_panel_report.json"
SIGNAL_LIST = PROJECT / "resources" / "signal_list.csv"
DICTIONARY = PROJECT / "resources" / "data_dictionary.csv"
KEYS = ["permno", "yyyymm", "eom"]
TARGET = "ret_exc_lead1"


@dataclass(frozen=True)
class Calendar:
    first_train_year: int = 1963   # first return year of the training sample
    n_validation: int = 12         # return years in the validation window
    first_year: int = 1993         # first return year predicted out of sample
    last_year: int = 2025

    def train_years(self, y: int) -> tuple[int, int]:
        return self.first_train_year, y - self.n_validation - 1

    def validation_years(self, y: int) -> tuple[int, int]:
        return y - self.n_validation, y - 1


CALENDAR = Calendar()
DEPTHS = [1, 2, 3]
TREES = [50, 100, 200]
LEARNING_RATE = 0.03
MIN_LEAF_SHARE = 0.001
BIN_SAMPLE = 500_000               # training rows used to build the bins (all of them if fewer)
LAMBDAS = [1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0]
SEED = 0
THREADS = 8                        # fixed: part of the reproducibility of the fit
CHUNK = 200_000                    # rows per block in the sums of the ridge and in the predictions
ON_DISK_ABOVE = 3e9                # bytes: a larger input matrix is kept in a temporary file


def lgb_params(depth: int, n_train: int) -> dict:
    # Every setting that changes the fit is written: nothing rests on a default.
    return {
        "objective": "regression", "boosting": "gbdt", "tree_learner": "serial",
        "learning_rate": LEARNING_RATE, "max_depth": depth, "num_leaves": 2 ** depth,
        "min_data_in_leaf": max(1, math.ceil(MIN_LEAF_SHARE * n_train)),
        "min_sum_hessian_in_leaf": 0.0, "min_gain_to_split": 0.0,
        "lambda_l1": 0.0, "lambda_l2": 0.0, "max_delta_step": 0.0, "path_smooth": 0.0,
        "feature_fraction": 1.0, "feature_fraction_bynode": 1.0,
        "bagging_fraction": 1.0, "bagging_freq": 0, "data_sample_strategy": "bagging",
        "boost_from_average": True, "linear_tree": False, "extra_trees": False,
        "use_quantized_grad": False,
        "seed": SEED, "deterministic": True, "force_col_wise": True, "num_threads": THREADS,
        "verbosity": -1,
    }


def lgb_data_params(n_train: int) -> dict:
    # Settings of the binned data set, built from the training rows only.
    return {"max_bin": 255, "min_data_in_bin": 3, "bin_construct_sample_cnt": max(1, min(n_train, BIN_SAMPLE)),
            "enable_bundle": False, "feature_pre_filter": False, "use_missing": False,
            "zero_as_missing": False, "data_random_seed": SEED, "num_threads": THREADS, "verbosity": -1}


def monthly_mse(pred: np.ndarray, y: np.ndarray, month: np.ndarray) -> float:
    """Mean over the months of the mean squared error of the month."""
    m = month - month.min()
    err = (pred.astype(np.float64) - y.astype(np.float64)) ** 2
    count = np.bincount(m)
    total = np.bincount(m, weights=err)
    return float((total[count > 0] / count[count > 0]).mean())


def pick(candidates: list[tuple[float, object]]) -> tuple[float, object]:
    """
    The candidate with the smallest loss. The list is given in the order of
    preference, and a later candidate wins only with a strictly smaller loss:
    ties keep the earlier one.
    """
    best = candidates[0]
    for cand in candidates[1:]:
        if cand[0] < best[0]:
            best = cand
    return best


class RidgeSums:
    """Sums of the training sample of the ridge, grown one return year at a time."""

    def __init__(self, p: int):
        self.n, self.sx, self.sy = 0, np.zeros(p), 0.0
        self.sxx, self.sxy = np.zeros((p, p)), np.zeros(p)

    def add(self, X: np.ndarray, y: np.ndarray) -> None:
        for a in range(0, X.shape[0], CHUNK):
            xb = np.asarray(X[a:a + CHUNK], dtype=np.float64)
            yb = np.asarray(y[a:a + CHUNK], dtype=np.float64)
            self.n += xb.shape[0]
            self.sx += xb.sum(axis=0)
            self.sy += yb.sum()
            self.sxx += xb.T @ xb
            self.sxy += xb.T @ yb

    def solve(self, lam: float) -> tuple[np.ndarray, float]:
        # Centred normal equations: the constant is not penalised.
        mx, my = self.sx / self.n, self.sy / self.n
        a = self.sxx / self.n - np.outer(mx, mx) + lam * np.eye(len(mx))
        b = self.sxy / self.n - mx * my
        beta = np.linalg.solve(a, b)
        resid = float(np.abs(a @ beta - b).max())
        check(bool(np.isfinite(beta).all()) and resid < 1e-8, f"Ridge: the normal equations are not solved ({resid})")
        return beta, float(my - mx @ beta)


def predict_rows(fn, X: np.ndarray, idx: np.ndarray) -> np.ndarray:
    # Predictions of the rows idx, a block at a time (a block is copied, never the matrix).
    out = np.empty(idx.size)
    for a in range(0, idx.size, CHUNK):
        out[a:a + CHUNK] = fn(np.ascontiguousarray(X[idx[a:a + CHUNK]]))
    return out


def training_entry(month: np.ndarray, avail: np.ndarray, cal: Calendar) -> np.ndarray:
    """
    For each row, the last training year of the first fit that can use it. The
    fit of the return year Y trains on the return years up to Y - n_validation - 1
    and is made at the end of December Y - 1. A row of return year R whose
    target is known in calendar year K enters the training sample at the fit of
    max(R + n_validation + 1, K + 1), and stays in it. The value returned is
    that year minus (n_validation + 1): the training rows of the fit of Y are
    the rows whose value is at most Y - n_validation - 1.
    """
    return np.maximum((month + 1) // 12, avail // 12 - cal.n_validation)


def arrange(y: np.ndarray, month: np.ndarray, avail: np.ndarray, cal: Calendar) -> np.ndarray:
    """Order for fit_predict: rows with a known target first, by training entry then month; the others after."""
    return np.lexsort((month, training_entry(month, avail, cal), ~np.isfinite(y)))


def fit_predict(X: np.ndarray, y: np.ndarray, month: np.ndarray, avail: np.ndarray, cal: Calendar,
                log: bool = True) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    Description:
        The two models, one fit per return year.
    Inputs:
        X      float32 (rows, inputs), in the order of arrange(): the rows with
               a known target first, sorted by training entry. The training
               rows of a fit are then the first rows of X, read without a copy.
        y      target of each row; NaN where the next return is unknown.
        month  index of the month of the row (year x 12 + month - 1). The return
               year of a row is the year of the following month.
        avail  index of the month at the end of which the target is known
               (month + 1, or later for a late delisting amount).
    Steps, for each return year Y of the calendar:
        1) Training rows: target known at the end of December Y - 1, return
           years first_train_year to Y - 13. Validation rows: target known at
           that date, return years Y - 12 to Y - 1.
        2) Boosted trees: one fit of 200 trees per depth; validation loss at 50,
           100 and 200 trees. Ridge: one solution per lambda.
        3) Predict every row of return year Y with the values chosen.
        For the first Y, also predict the rows of its validation years
        ("development", not out of sample).
    Output:
        pred_gbrt, pred_ridge (NaN outside the predicted years), and the record
        of each year.
    """
    check(X.dtype == np.float32 and X.flags["C_CONTIGUOUS"], "X must be a C-contiguous float32 array")
    known = np.isfinite(y)
    nk = int(known.sum())
    check(bool(known[:nk].all()), "The rows with a known target must come first")
    ryear = (month + 1) // 12                      # return year of every row
    Xk, yk, mk, rk, ak = X[:nk], y[:nk], month[:nk], ryear[:nk], avail[:nk]
    sk = training_entry(mk, ak, cal)
    check(bool((np.diff(sk) >= 0).all()), "The rows with a known target are not sorted by training entry")
    check(bool((ak >= mk + 1).all()), "A target is dated before the end of its return month")
    check(int(rk.min()) >= cal.first_train_year, "A row is dated before the first training year")
    pred_g = np.full(X.shape[0], np.nan)
    pred_r = np.full(X.shape[0], np.nan)
    sums = RidgeSums(X.shape[1])
    in_sums = 0                                    # first rows of Xk already in the ridge sums
    records = []

    for year in range(cal.first_year, cal.last_year + 1):
        t0 = time.time()
        (t_lo, t_hi), (v_lo, v_hi) = cal.train_years(year), cal.validation_years(year)
        # The fit is made at the end of December Y - 1: only the targets known by
        # then are used. No look-ahead: the last usable target is the return of
        # December Y - 1 itself.
        first_pred_month = year * 12 - 1           # December of Y - 1
        tr = slice(0, int(np.searchsorted(sk, t_hi, "right")))
        in_val = (rk >= v_lo) & (rk <= v_hi)
        va = np.flatnonzero(in_val & (ak <= first_pred_month))
        n_tr, n_va = tr.stop, int(va.size)
        check(n_tr > 0 and n_va > 0, f"{year}: empty training or validation sample")
        check(int(va.min()) >= tr.stop, f"{year}: training and validation overlap")
        check(int(ak[tr].max()) <= first_pred_month and int(ak[va].max()) <= first_pred_month,
              f"{year}: a target is not known at the formation date")
        check(int(rk[tr].max()) <= t_hi, f"{year}: a training row is outside its sample")
        check(n_tr == int(((rk <= t_hi) & (ak <= first_pred_month)).sum()), f"{year}: the training rows are not the first rows")
        not_yet = {"training": int(((rk <= t_hi) & (ak > first_pred_month)).sum()),
                   "validation": int((in_val & (ak > first_pred_month)).sum())}
        target = np.flatnonzero(ryear == year)     # every row of the year, known target or not
        dev = np.flatnonzero((ryear >= v_lo) & (ryear <= v_hi)) if year == cal.first_year else None
        check(target.size > 0, f"{year}: no row to predict")
        check(int(month[target].min()) >= first_pred_month, f"{year}: a predicted row is dated before the fit")

        # --- boosted trees
        data = lgb.Dataset(Xk[tr], label=yk[tr], params=lgb_data_params(n_tr), free_raw_data=True)
        cands, losses_g, boosters, fitted = [], {}, {}, {}
        for depth in DEPTHS:                       # order of preference: smaller depth, then fewer trees
            boosters[depth] = lgb.train(lgb_params(depth, n_tr), data, num_boost_round=max(TREES))
            # LightGBM stops before 200 trees when no split is left that improves
            # the fit; the later trees would be empty, so reading "200 trees"
            # from such a fit is still the fit of 200 trees. Recorded below.
            fitted[depth] = boosters[depth].num_trees()
            check(1 <= fitted[depth] <= max(TREES), f"{year}: {fitted[depth]} trees fitted at depth {depth}")
            for k in TREES:
                def staged(block: np.ndarray, b=boosters[depth], k=k) -> np.ndarray:
                    return b.predict(block, num_iteration=k, num_threads=THREADS)

                loss = monthly_mse(predict_rows(staged, Xk, va), yk[va], mk[va])
                losses_g[f"depth{depth}_trees{k}"] = loss
                cands.append((loss, (depth, k)))
        _, (depth, k) = pick(cands)

        def trees(block: np.ndarray, b=boosters[depth], k=k) -> np.ndarray:
            return b.predict(block, num_iteration=k, num_threads=THREADS)

        pred_g[target] = predict_rows(trees, X, target)
        if dev is not None:
            pred_g[dev] = predict_rows(trees, X, dev)
        del data, boosters

        # --- ridge: add the rows that entered the training sample
        if tr.stop > in_sums:
            sums.add(Xk[in_sums:tr.stop], yk[in_sums:tr.stop])
            in_sums = tr.stop
        check(sums.n == n_tr, f"{year}: the ridge sums hold {sums.n} rows, the training sample {n_tr}")
        cands_r, losses_r, solutions = [], {}, {}
        for lam in sorted(LAMBDAS, reverse=True):  # order of preference: larger lambda
            solutions[lam] = sums.solve(lam)

            def line(block: np.ndarray, s=solutions[lam]) -> np.ndarray:
                return np.asarray(block, dtype=np.float64) @ s[0] + s[1]

            loss = monthly_mse(predict_rows(line, Xk, va), yk[va], mk[va])
            losses_r[f"lambda{lam:g}"] = loss
            cands_r.append((loss, lam))
        _, lam = pick(cands_r)

        def line(block: np.ndarray, s=solutions[lam]) -> np.ndarray:
            return np.asarray(block, dtype=np.float64) @ s[0] + s[1]

        pred_r[target] = predict_rows(line, X, target)
        if dev is not None:
            pred_r[dev] = predict_rows(line, X, dev)

        records.append({
            "return_year": year, "train_years": [t_lo, t_hi], "validation_years": [v_lo, v_hi],
            "train_rows": n_tr, "validation_rows": n_va, "predicted_rows": int(target.size),
            "targets_not_yet_known_at_the_fit": not_yet,
            "min_data_in_leaf": lgb_params(depth, n_tr)["min_data_in_leaf"],
            "gbrt_depth": depth, "gbrt_trees": k, "ridge_lambda": lam,
            "gbrt_trees_fitted_by_depth": {str(d): n for d, n in fitted.items()},
            "validation_loss_gbrt": losses_g, "validation_loss_ridge": losses_r,
            "seconds": round(time.time() - t0, 1)})
        if log:
            # The values chosen are shown for the first year only (see the header).
            shown = f" | trees: depth {depth}, {k} | ridge: lambda {lam:g}" if year == cal.first_year else ""
            print(f"  {year}: train {n_tr:,} rows ({t_lo}-{t_hi}), validation {n_va:,} ({v_lo}-{v_hi}), "
                  f"predicted {target.size:,}{shown} | {time.time() - t0:.0f} s", flush=True)
    return pred_g, pred_r, records


# --------------------------------------------------------------------- real data

def read_checked(path: Path, report_path: Path, columns: list[str], report: dict) -> pl.DataFrame:
    # Same function as in the signal scripts: read some columns of an earlier
    # output, only if the file matches the report of its step.
    earlier = json.loads(report_path.read_text(encoding="utf-8"))
    expected = earlier.get("outputs", {}).get(path.name)
    check(expected is not None, f"{path.name} is not listed in {report_path.name}")
    stamps = file_stamps([path])
    check(sha256(path) == expected, f"{path.name} does not match {report_path.name}: mixed runs?")
    df = pl.read_parquet(path, columns=columns)
    check_unchanged(stamps)
    report["inputs"][path.name] = {"sha256": expected, "from_run": earlier["run_id"]}
    return df


def input_names(version: str) -> list[str]:
    rows = list(csv.DictReader(open(SIGNAL_LIST, encoding="utf-8")))
    names = [r["characteristic"] for r in rows if r["version"] == "A" or version == "B"]
    check(len(names) == {"A": 59, "B": 194}[version], f"{len(names)} characteristics for version {version}")
    return names + [f"{n}_miss" for n in names]


def check_roles(cols: list[str]) -> None:
    # The inputs are predictors known at t; the target is an outcome of t+1.
    d = {(r["table"], r["column"]): r for r in csv.DictReader(open(DICTIONARY, encoding="utf-8"))}
    for c in cols:
        r = d.get(("signal_ranks", c))
        check(r is not None and r["roles"] == "predictor" and r["availability"] in ("t", "acc_6m"),
              f"signal_ranks.{c} is not a predictor known at t in the data dictionary")
    r = d.get(("crsp_panel_acc", TARGET))
    check(r is not None and r["roles"] == "outcome" and r["availability"] == "t+1",
          f"{TARGET} is not registered as an outcome of t+1")


def allocate(shape: tuple[int, int], folder: Path | None) -> np.ndarray:
    # The input matrix: in memory, or in a temporary file when it is large (the
    # system then keeps in memory only the part being read).
    if folder is None:
        return np.empty(shape, dtype=np.float32)
    return np.memmap(folder / "inputs.float32", dtype=np.float32, mode="w+", shape=shape)


def load(version: str, cal: Calendar, report: dict, folder: Path | None
         ) -> tuple[pl.DataFrame, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    """
    Description:
        Keys, inputs and target of the eligible stock-months whose return year is
        between the first training year and the last predicted year, arranged
        for fit_predict (known targets first).
    Output:
        keys (permno, yyyymm, eom), X float32, y (NaN if unknown), month index,
        month at which the target is known, and the file stamps of signal_ranks
        to check before publishing.
    """
    c = pl.col
    cols = input_names(version)
    check_roles(cols)
    lo = (cal.first_train_year - 1) * 100 + 12     # December before the first return year
    hi = cal.last_year * 100 + 11                  # November of the last return year
    panel = read_checked(PANEL, PANEL_REPORT, ["permno", "yyyymm", "eom", "eligible", TARGET, "delamtdt",
                                               "delnextdt"], report)
    # Month at which each target is known: the dates of the row of month t + 1
    # of the same stock. delamtdt and delnextdt are read as dates of knowledge
    # of a target only; they are never an input of a model.
    mi = (c("yyyymm") // 100 * 12 + c("yyyymm") % 100 - 1).cast(pl.Int64)
    following = panel.select(
        "permno", (mi - 1).alias("__m"), mi.alias("__return_month"),
        (c("delamtdt").dt.year().cast(pl.Int64) * 12 + c("delamtdt").dt.month() - 1).alias("__amount_month"),
        (c("delnextdt").dt.year().cast(pl.Int64) * 12 + c("delnextdt").dt.month() - 1).alias("__price_month"))
    panel = panel.filter(c("eligible") & c("yyyymm").is_between(lo, hi)).with_columns(mi.alias("__m"))
    n_rows = panel.height
    panel = panel.join(following, on=["permno", "__m"], how="left", validate="1:1").sort("yyyymm", "permno")
    check(panel.height == n_rows, "The join with the following month changed the number of rows")
    check(panel.filter(c(TARGET).is_not_null() & c("__return_month").is_null()).height == 0,
          "A known target has no row for its return month")
    panel = panel.with_columns(__avail=pl.max_horizontal(c("__m") + 1, "__amount_month", "__price_month"))

    earlier = json.loads(RANKS_REPORT.read_text(encoding="utf-8"))
    stamps = file_stamps([RANKS])
    check(sha256(RANKS) == earlier["outputs"][RANKS.name], f"{RANKS.name} does not match its report")
    report["inputs"][RANKS.name] = {"sha256": earlier["outputs"][RANKS.name], "from_run": earlier["run_id"]}
    report["inputs"][SIGNAL_LIST.name] = sha256(SIGNAL_LIST)
    report["inputs"][DICTIONARY.name] = sha256(DICTIONARY)
    schema = pl.read_parquet_schema(RANKS)
    check(set(cols) <= set(schema), f"signal_ranks lacks {sorted(set(cols) - set(schema))[:5]}")
    scan = pl.scan_parquet(RANKS).filter(c("yyyymm").is_between(lo, hi))
    keys = scan.select(KEYS).collect()
    check(keys.equals(panel.select(KEYS)), "signal_ranks does not hold the eligible rows of the panel, in order")

    y = panel[TARGET].to_numpy().astype(np.float64)    # null -> NaN
    check(bool(np.isfinite(y[~np.isnan(y)]).all()), "A target is infinite")
    month = panel["__m"].to_numpy().astype(np.int64)
    avail = panel["__avail"].to_numpy().astype(np.int64)
    order = arrange(y, month, avail, cal)
    late = np.isfinite(y) & (avail > month + 1)
    report["targets_known_after_their_return_month"] = {
        "rows": int(late.sum()), "known_in_a_later_calendar_year": int((late & (avail // 12 > (month + 1) // 12)).sum()),
        "longest_delay_in_months": int((avail - month - 1)[np.isfinite(y)].max())}

    half = len(cols) // 2                          # ranks first, then their flags
    X = allocate((keys.height, len(cols)), folder)
    for a in range(0, len(cols), 24):              # a few columns at a time: the table is large
        part = scan.select(cols[a:a + 24]).collect()
        check(part.height == keys.height, "A block of columns has another number of rows")
        for j, name in enumerate(part.columns, start=a):
            check(part[name].null_count() == 0, f"{name}: missing value in signal_ranks")
            v = part[name].to_numpy().astype(np.float32)
            check(bool(np.isfinite(v).all()), f"{name}: a value is not finite")
            if j < half:
                check(float(np.abs(v).max()) <= 1.0, f"{name}: a rank is outside [-1, 1]")
            else:
                check(bool(np.isin(v, (0.0, 1.0)).all()), f"{name}: a missing flag is not 0 or 1")
            X[:, j] = v[order]
        del part
    report["rows"] = {"eligible_stock_months": keys.height, "with_a_known_target": int(np.isfinite(y).sum()),
                      "first_month": lo, "last_month": hi, "inputs": len(cols)}
    return keys[order], X, y[order], month[order], avail[order], stamps


def calendar_table(y: np.ndarray, month: np.ndarray, avail: np.ndarray, cal: Calendar) -> list[dict]:
    # Counted with plain masks, apart from fit_predict: the two must agree.
    ryear, known = (month + 1) // 12, np.isfinite(y)
    out = []
    for year in range(cal.first_year, cal.last_year + 1):
        (t_lo, t_hi), (v_lo, v_hi) = cal.train_years(year), cal.validation_years(year)
        usable = known & (avail <= year * 12 - 1)  # target known at the end of December Y - 1
        out.append({"return_year": year, "train_years": [t_lo, t_hi], "validation_years": [v_lo, v_hi],
                    "train_rows": int((usable & (ryear >= t_lo) & (ryear <= t_hi)).sum()),
                    "validation_rows": int((usable & (ryear >= v_lo) & (ryear <= v_hi)).sum()),
                    "targets_not_yet_known": int((known & ~usable & (ryear <= v_hi)).sum()),
                    "predicted_rows": int((ryear == year).sum()),
                    "predicted_rows_with_unknown_target": int(((ryear == year) & ~known).sum())})
    return out


def choices_table(records: list[dict]) -> pl.DataFrame:
    # One row per year, model and candidate value: its validation loss, and whether it was chosen.
    rows = []
    for r in records:
        for name, loss in r["validation_loss_gbrt"].items():
            fitted = r["gbrt_trees_fitted_by_depth"][name[5]]          # "depth<d>_trees<k>"
            rows.append((r["return_year"], "gbrt", name, loss, name == f"depth{r['gbrt_depth']}_trees{r['gbrt_trees']}",
                         fitted, r["seconds"]))
        for name, loss in r["validation_loss_ridge"].items():
            rows.append((r["return_year"], "ridge", name, loss, name == f"lambda{r['ridge_lambda']:g}", None,
                         r["seconds"]))
    out = pl.DataFrame(rows, schema=["return_year", "model", "value", "validation_loss", "chosen",
                                     "trees_fitted_at_this_depth", "seconds_of_the_year"], orient="row")
    check(out.filter(pl.col("chosen")).height == 2 * len(records), "Not exactly one value chosen per model and year")
    return out.with_columns(pl.col("return_year").cast(pl.Int32))


def run(version: str, dry_run: bool) -> None:
    check(lgb.__version__.startswith("4.7"), f"LightGBM {lgb.__version__}: the settings were checked on 4.7")
    report: dict = {"script": "scripts/predictions/1_predictions.py", "version": version, "inputs": {}}
    report["script_sha256"] = sha256(Path(__file__))
    cal = CALENDAR
    n_inputs = len(input_names(version))
    # Rows are not known yet: 3.5 million is the order of magnitude of the panel.
    folder = Path(tempfile.mkdtemp(prefix="predictions_")) if 3.5e6 * n_inputs * 4 > ON_DISK_ABOVE else None
    X = None
    try:
        keys, X, y, month, avail, stamps = load(version, cal, report, folder)
        table = calendar_table(y, month, avail, cal)
        print(f"version {version}: {X.shape[0]:,} eligible stock-months, {X.shape[1]} inputs, "
              f"{report['rows']['with_a_known_target']:,} with a known target "
              f"({X.nbytes / 1e9:.1f} GB, {'in a temporary file' if folder else 'in memory'}).")
        print(f"  targets known after their return month: {report['targets_known_after_their_return_month']}")
        if dry_run:
            for r in (table[0], table[len(table) // 2], table[-1]):
                print("  ", r)
            print("dry run: inputs read and checked, no model fitted, nothing written.")
            return

        pred_g, pred_r, records = fit_predict(X, y, month, avail, cal)
    finally:
        if folder is not None:                     # close and delete the temporary file
            if X is not None:
                X._mmap.close()
            del X
            shutil.rmtree(folder, ignore_errors=True)
    check_unchanged(stamps)
    for r, t in zip(records, table):
        check(all(r[k] == t[k] for k in ("train_rows", "validation_rows", "predicted_rows")),
              f"{r['return_year']}: the rows used differ from the calendar table")

    ryear = (month + 1) // 12
    dev_lo = cal.validation_years(cal.first_year)[0]
    keep = ryear >= dev_lo
    check(bool(np.isfinite(pred_g[keep]).all() and np.isfinite(pred_r[keep]).all()), "A prediction is missing")
    check(bool(np.isnan(pred_g[~keep]).all() and np.isnan(pred_r[~keep]).all()),
          "A training-only row has a prediction")
    out = keys.with_columns(
        return_year=pl.Series(ryear.astype(np.int32)),
        sample=pl.Series(np.where(ryear >= cal.first_year, "test", "development")),
        pred_gbrt=pl.Series(pred_g), pred_ridge=pl.Series(pred_r),
    ).filter(pl.Series(keep)).sort("yyyymm", "permno")
    check(out.select("permno", "yyyymm").is_unique().all(), "Duplicate stock-month in the predictions")

    report["calendar"] = {"first_train_year": cal.first_train_year, "validation_years": cal.n_validation,
                          "first_year": cal.first_year, "last_year": cal.last_year}
    report["settings"] = {"lightgbm": lgb.__version__, "numpy": np.__version__, "polars": pl.__version__,
                          "lgb_params_depth1_example": lgb_params(1, 1000), "lgb_data_params_example": lgb_data_params(1000),
                          "depths": DEPTHS, "trees": TREES, "lambdas": LAMBDAS, "min_leaf_share": MIN_LEAF_SHARE,
                          "bin_sample": BIN_SAMPLE}
    # In clear: the rows and the time of every year, and the whole record of the
    # first year only. The values chosen and the losses of all years are sealed.
    plain = ("return_year", "train_years", "validation_years", "train_rows", "validation_rows", "predicted_rows",
             "targets_not_yet_known_at_the_fit")
    report["years"] = [{k: r[k] for k in plain} for r in records]
    report["first_year_record"] = records[0]
    report["minutes_of_fitting"] = round(sum(r["seconds"] for r in records) / 60, 1)
    report["sealed"] = ("The values chosen, the validation losses, the trees fitted and the time of every year are "
                        f"in predictions_{version}_choices_sealed.parquet: not to be opened, not even its metadata, "
                        "before the strategy is frozen. Before the freeze, the portfolio and cost code reads "
                        f"predictions_{version}_development.parquet only.")
    development, test = out.filter(pl.col("sample") == "development"), out.filter(pl.col("sample") == "test")
    check(development.height + test.height == out.height and development["return_year"].max() < cal.first_year
          and test["return_year"].min() >= cal.first_year, "The development and test rows are not separated")
    report["predictions"] = {"rows": out.height, "development_rows": development.height, "test_rows": test.height}
    publish({PROCESSED / f"predictions_{version}_development.parquet": development,
             PROCESSED / f"predictions_{version}_test.parquet": test,
             PROCESSED / f"predictions_{version}_choices_sealed.parquet": choices_table(records)},
            report, PROCESSED / f"predictions_{version}_report.json")
    print(f"predictions_{version}: {out.height:,} stock-months ({report['predictions']['test_rows']:,} test, "
          f"{report['predictions']['development_rows']:,} development), "
          f"{report['minutes_of_fitting']:.0f} minutes of fitting.")
    print(f"Run {report['run_id']}. Report saved. The choices of 1994-{cal.last_year} are sealed.")


# ------------------------------------------------------------------ synthetic tests

def synthetic(seed: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Calendar]:
    """A small panel of random numbers: 6 training years, 3 validation years, 4 predicted years."""
    cal = Calendar(first_train_year=2001, n_validation=3, first_year=2010, last_year=2013)
    rng = np.random.default_rng(seed)
    months = np.arange(2000 * 12 + 11, 2013 * 12 + 11)        # December 2000 to November 2013
    n_stocks, p = 400, 12
    month = np.repeat(months, n_stocks)
    X = rng.uniform(-1, 1, size=(month.size, p)).astype(np.float32)
    X[:, p // 2:] = (X[:, p // 2:] > 0.5).astype(np.float32)   # the last columns are 0/1 flags
    # Planted relation: linear in column 0, a threshold in column 1, an interaction with flag 6.
    y = 0.03 * X[:, 0] + 0.02 * (X[:, 1] > 0.3) - 0.02 * X[:, 2] * X[:, 6] + 0.05 * rng.standard_normal(month.size)
    y[rng.uniform(size=y.size) < 0.01] = np.nan                # some unknown targets
    # Some targets are known late: by 1 to 70 months (the longest reach the training years).
    avail = month + 1
    late = rng.uniform(size=y.size) < 0.02
    avail = avail + np.where(late, rng.integers(1, 71, size=y.size), 0)
    return X, y, month, avail, cal


def fp(X: np.ndarray, y: np.ndarray, month: np.ndarray, avail: np.ndarray, cal: Calendar
       ) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    # fit_predict for rows in any order: arrange, fit, give the predictions back in the order received.
    order = arrange(y, month, avail, cal)
    g, r, rec = fit_predict(np.ascontiguousarray(X[order]), y[order], month[order], avail[order], cal, log=False)
    back_g, back_r = np.empty_like(g), np.empty_like(r)
    back_g[order], back_r[order] = g, r
    return back_g, back_r, rec


def naive(X: np.ndarray, y: np.ndarray, month: np.ndarray, avail: np.ndarray, cal: Calendar
          ) -> tuple[np.ndarray, np.ndarray, list[tuple]]:
    """
    The same rules written a second time, the slow and plain way: boolean masks,
    one new fit for each depth and number of trees, the ridge by least squares
    on an augmented system, losses by a loop over the months. Every number of
    the rules is written here again, not read from the constants above.
    """
    ryear, known = (month + 1) // 12, np.isfinite(y)
    pg, pr, chosen = np.full(y.size, np.nan), np.full(y.size, np.nan), []

    def loss_by_month(pred: np.ndarray, mask: np.ndarray) -> float:
        per_month = [np.mean((pred[month[mask] == m] - y[mask][month[mask] == m]) ** 2)
                     for m in np.unique(month[mask])]
        return float(np.mean(per_month))

    for year in range(cal.first_year, cal.last_year + 1):
        ready = known & (avail <= year * 12 - 1)                # target known at the end of December Y - 1
        tr = ready & (ryear >= cal.first_train_year) & (ryear <= year - cal.n_validation - 1)
        va = ready & (ryear >= year - cal.n_validation) & (ryear <= year - 1)
        out = (ryear == year) | ((ryear >= year - cal.n_validation) & (ryear <= year - 1) & (year == cal.first_year))
        n = int(tr.sum())
        xtr, ytr = np.ascontiguousarray(X[tr]), y[tr]
        best = None
        for depth in (1, 2, 3):
            for k in (50, 100, 200):
                params = {"objective": "regression", "learning_rate": 0.03, "max_depth": depth, "num_leaves": 2 ** depth,
                          "min_data_in_leaf": max(1, math.ceil(0.001 * n)), "min_sum_hessian_in_leaf": 0.0,
                          "lambda_l2": 0.0, "seed": 0, "deterministic": True, "force_col_wise": True,
                          "num_threads": 8, "verbosity": -1}
                dparams = {"max_bin": 255, "min_data_in_bin": 3, "bin_construct_sample_cnt": min(n, 500_000),
                           "enable_bundle": False, "feature_pre_filter": False, "use_missing": False,
                           "data_random_seed": 0, "verbosity": -1}
                model = lgb.train(params, lgb.Dataset(xtr, label=ytr, params=dparams), num_boost_round=k)
                loss = loss_by_month(model.predict(X[va]), va)
                if best is None or loss < best[0]:
                    best = (loss, depth, k, model)
        pg[out] = best[3].predict(X[out])
        xc, yc = X[tr].astype(np.float64), ytr.astype(np.float64)
        mx, my = xc.mean(axis=0), yc.mean()
        best_r = None
        for lam in (100.0, 10.0, 1.0, 0.1, 0.01, 0.001, 0.0001):
            aug_x = np.vstack([xc - mx, math.sqrt(n * lam) * np.eye(X.shape[1])])
            aug_y = np.concatenate([yc - my, np.zeros(X.shape[1])])
            beta = np.linalg.lstsq(aug_x, aug_y, rcond=None)[0]
            const = my - mx @ beta
            loss = loss_by_month(X[va].astype(np.float64) @ beta + const, va)
            if best_r is None or loss < best_r[0]:
                best_r = (loss, lam, beta, const)
        pr[out] = X[out].astype(np.float64) @ best_r[2] + best_r[3]
        chosen.append((best[1], best[2], best_r[1]))
    return pg, pr, chosen


def selftest() -> None:
    """Tests on random numbers only: no project data is read."""
    from sklearn.linear_model import Ridge

    X, y, month, avail, cal = synthetic()
    ryear, known = (month + 1) // 12, np.isfinite(y)
    g, r, rec = fp(X, y, month, avail, cal)
    pred_rows = ryear >= cal.validation_years(cal.first_year)[0]
    check(bool(np.isfinite(g[pred_rows]).all() and np.isfinite(r[pred_rows]).all()), "selftest: missing prediction")
    check(bool(np.isnan(g[~pred_rows]).all()), "selftest: a training-only row is predicted")
    check(bool(np.isfinite(g[pred_rows & ~known]).all()), "selftest: rows with an unknown target are not predicted")
    print(f"selftest: {X.shape[0]:,} rows, {len(rec)} years fitted.")

    # 1) The models find a planted relation (the test of a working pipeline).
    signal = 0.03 * X[:, 0] + 0.02 * (X[:, 1] > 0.3) - 0.02 * X[:, 2] * X[:, 6]
    oos = ryear >= cal.first_year
    cg, cr = np.corrcoef(g[oos], signal[oos])[0, 1], np.corrcoef(r[oos], signal[oos])[0, 1]
    check(cg > 0.8 and cr > 0.6, f"selftest: planted relation not found (trees {cg:.2f}, ridge {cr:.2f})")
    print(f"  planted relation: correlation of the predictions with it, trees {cg:.2f}, ridge {cr:.2f}")

    # 2) Against the same rules written a second time, the plain way: same values
    #    chosen, same predictions. This is the test of the fit on the training
    #    sample only, of the choice of the values and of their use.
    ng, nr, nchosen = naive(X, y, month, avail, cal)
    mine = [(q["gbrt_depth"], q["gbrt_trees"], q["ridge_lambda"]) for q in rec]
    check(mine == nchosen, f"selftest: values chosen {mine}, plain version {nchosen}")
    gap_g = float(np.nanmax(np.abs(g - ng)))
    gap_r = float(np.nanmax(np.abs(r - nr)))
    check(np.array_equal(np.isnan(g), np.isnan(ng)) and gap_g < 1e-12 and gap_r < 1e-9,
          f"selftest: predictions differ from the plain version (trees {gap_g}, ridge {gap_r})")
    check(sum(q["targets_not_yet_known_at_the_fit"]["training"] for q in rec) > 0
          and sum(q["targets_not_yet_known_at_the_fit"]["validation"] for q in rec) > 0,
          "selftest: no late target in the training or validation years, the test is too easy")
    check(len(set(mine)) > 1 or mine[0] != (1, 50, 100.0), "selftest: the choices are all the first candidate")
    print(f"  against the plain version: same choices {mine}; gaps trees {gap_g:.1e}, ridge {gap_r:.1e}")

    # 3) Same inputs, same outputs; an input matrix kept in a file gives the same.
    g2, r2, _ = fp(X, y, month, avail, cal)
    check(np.array_equal(g, g2, equal_nan=True) and np.array_equal(r, r2, equal_nan=True), "selftest: two runs differ")
    folder = Path(tempfile.mkdtemp(prefix="predictions_selftest_"))
    try:
        order = arrange(y, month, avail, cal)
        Xd = allocate(X.shape, folder)
        Xd[:] = X[order]
        gd, rd, _ = fit_predict(Xd, y[order], month[order], avail[order], cal, log=False)
        check(np.array_equal(gd, g[order], equal_nan=True) and np.array_equal(rd, r[order], equal_nan=True),
              "selftest: the matrix in a temporary file gives other predictions")
        Xd._mmap.close()
        del Xd
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    # 4) No look-ahead in the targets: changing every target of the return years
    #    >= Y leaves the predictions of the years <= Y unchanged.
    for year in (cal.first_year, cal.first_year + 2):
        y3 = y.copy()
        y3[ryear >= year] = y3[ryear >= year] * -3.0 + 0.1
        g3, r3, _ = fp(X, y3, month, avail, cal)
        upto = pred_rows & (ryear <= year)
        check(np.array_equal(g[upto], g3[upto]) and np.array_equal(r[upto], r3[upto]),
              f"selftest: targets of {year} and later change the predictions up to {year}")
        # The test can fail: the predictions of the following year do change.
        nxt = ryear == year + 1
        if nxt.any():
            check(not np.array_equal(g[nxt], g3[nxt]) and not np.array_equal(r[nxt], r3[nxt]),
                  "selftest: the target test cannot detect a change")
    # 5) No look-ahead in the rows: dropping every row after the return year Y
    #    leaves the predictions up to Y unchanged.
    year = cal.first_year + 1
    cut = ryear <= year
    cal4 = Calendar(cal.first_train_year, cal.n_validation, cal.first_year, year)
    g4, r4, _ = fp(X[cut], y[cut], month[cut], avail[cut], cal4)
    check(np.array_equal(g[cut], g4, equal_nan=True) and np.array_equal(r[cut], r4, equal_nan=True),
          "selftest: later rows change earlier predictions")
    # 6) The edges of the samples, one month at a time, for the first year Y.
    #    Last training month (return of December Y - 13): it is in the fit, so
    #    the predictions of Y change. Last validation month (return of December
    #    Y - 1): it only enters the choice of the values, so the validation
    #    losses change. Return of January Y: used by nothing in year Y.
    first = ryear == cal.first_year
    y5 = y.copy()
    last = month == ((cal.train_years(cal.first_year)[1] + 1) * 12 - 2)   # row of November, return of December Y - 13
    y5[last] = y5[last] + 0.5
    g5, r5, _ = fp(X, y5, month, avail, cal)
    check(not np.array_equal(r[first], r5[first]) and not np.array_equal(g[first], g5[first]),
          "selftest: the last training month is not used for year Y")
    y7 = y.copy()
    lastv = month == (cal.first_year * 12 - 2)                 # row of November Y - 1, return of December Y - 1
    y7[lastv] = y7[lastv] + 0.5
    _, _, rec7 = fp(X, y7, month, avail, cal)
    check(rec7[0]["validation_loss_gbrt"] != rec[0]["validation_loss_gbrt"]
          and rec7[0]["validation_loss_ridge"] != rec[0]["validation_loss_ridge"],
          "selftest: the return of December Y - 1 is not in the validation sample of year Y")
    y6 = y.copy()
    jan = month == (cal.first_year * 12 - 1)                   # row of December Y - 1, return of January Y
    y6[jan] = y6[jan] + 0.5
    g6, r6, _ = fp(X, y6, month, avail, cal)
    check(np.array_equal(g[first], g6[first]) and np.array_equal(r[first], r6[first]),
          "selftest: the return of January Y changes the predictions of year Y")
    # 6b) Late targets (test of the audit by Astra). Changing every target that
    #     is not yet known at the fit of year Y changes nothing up to Y: neither
    #     the values chosen, nor the predictions. With the dates of knowledge
    #     removed (every target known at its month), the same change does move
    #     them: the test can fail.
    year = cal.first_year + 1
    pending = known & (avail > year * 12 - 1) & (ryear <= year - 1)
    check(int(pending.sum()) > 20, "selftest: too few late targets")
    y8 = y.copy()
    y8[pending] = y8[pending] - 0.9
    g8, r8, rec8 = fp(X, y8, month, avail, cal)
    upto = pred_rows & (ryear <= year)
    same_choice = all((a["gbrt_depth"], a["gbrt_trees"], a["ridge_lambda"], a["validation_loss_gbrt"])
                      == (b["gbrt_depth"], b["gbrt_trees"], b["ridge_lambda"], b["validation_loss_gbrt"])
                      for a, b in zip(rec, rec8) if a["return_year"] <= year)
    check(same_choice and np.array_equal(g[upto], g8[upto]) and np.array_equal(r[upto], r8[upto]),
          "selftest: a target not yet known changes a fit made before it is known")
    g9, r9, _ = fp(X, y, month, month + 1, cal)
    g10, r10, _ = fp(X, y8, month, month + 1, cal)
    check(not np.array_equal(r9[upto], r10[upto]) and not np.array_equal(g9[upto], g10[upto]),
          "selftest: the late-target test cannot detect a change")
    check(not np.array_equal(r[ryear == cal.last_year], r8[ryear == cal.last_year]),
          "selftest: a late target never enters a later fit")
    print("  look-ahead tests on targets, rows and late targets: passed, and each one can fail")

    # 7) Ridge against scikit-learn (alpha = lambda x rows), on the first training sample.
    t_lo, t_hi = cal.train_years(cal.first_year)
    tr = known & (ryear >= t_lo) & (ryear <= t_hi)
    sums = RidgeSums(X.shape[1])
    sums.add(X[tr], y[tr])
    gap = 0.0
    for lam in LAMBDAS:
        beta, const = sums.solve(lam)
        ref = Ridge(alpha=lam * tr.sum(), fit_intercept=True, solver="cholesky").fit(X[tr].astype(np.float64), y[tr])
        gap = max(gap, float(np.abs(beta - ref.coef_).max()), abs(const - float(ref.intercept_)))
    check(gap < 1e-9, f"selftest: ridge differs from scikit-learn by {gap}")
    print(f"  ridge against scikit-learn: largest gap {gap:.1e}")

    # 8) Trees: leaf size and depth against the numbers of the rules, written here.
    n_tr = int(tr.sum())
    data = lgb.Dataset(np.ascontiguousarray(X[tr]), label=y[tr], params=lgb_data_params(n_tr))
    for depth in (1, 2, 3):
        model = lgb.train(lgb_params(depth, n_tr), data, num_boost_round=200)
        frame = model.trees_to_dataframe()
        leaves = frame[frame["left_child"].isna()]
        check(int(leaves["count"].min()) >= math.ceil(0.001 * n_tr), "selftest: a leaf is below 0.1 % of the rows")
        check(int(leaves.groupby("tree_index").size().max()) <= 2 ** depth, "selftest: a tree has too many leaves")
        check(int(frame["node_depth"].max()) <= depth + 1, "selftest: a tree is deeper than its limit")
        check(abs(model.params["learning_rate"] - 0.03) < 1e-15, "selftest: the learning rate is not 0.03")
    print(f"  trees: leaves of at least {math.ceil(0.001 * n_tr)} rows, depth and leaf limits respected")

    # 9) The monthly loss: a month with few rows weighs as much as a large one.
    loss = monthly_mse(np.array([1.0, 1.0, 1.0, 0.0]), np.zeros(4), np.array([5, 5, 5, 6]))
    check(abs(loss - 0.5) < 1e-15, f"selftest: monthly loss {loss}, expected 0.5")
    # 10) Ties, on losses written by hand. Trees: candidates in the order smaller
    #     depth, then fewer trees. Ridge: larger lambda first.
    check(pick([(1.0, "a"), (1.0, "b"), (1.0, "c")])[1] == "a", "selftest: a tie does not keep the first candidate")
    check(pick([(1.0, "a"), (0.5, "b"), (0.5, "c")])[1] == "b", "selftest: the smallest loss is not chosen")
    check(pick([(1.0, "a"), (2.0, "b"), (0.9, "c")])[1] == "c", "selftest: the smallest loss is not chosen")
    yc = np.where(np.isfinite(y), 0.01, np.nan)                 # a constant target: the trees all predict it
    _, _, recc = fp(X, yc, month, avail, cal)
    check(all(q["gbrt_depth"] == 1 and q["gbrt_trees"] == 50 for q in recc), "selftest: equal trees, not the simplest")
    print("  monthly loss and tie rules: passed")
    print("selftest passed. No project data was read.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=["A", "B"])
    ap.add_argument("--dry-run", action="store_true", help="read and check the inputs, fit nothing")
    ap.add_argument("--selftest", action="store_true", help="tests on random numbers only")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    check(args.version is not None, "Give --version A or --version B (or --selftest)")
    run(args.version, args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
