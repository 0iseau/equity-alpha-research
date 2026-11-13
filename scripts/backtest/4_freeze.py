"""Backtest, step 4: record the freeze of the strategy.

Rule (principle 7 of the project; SignalSpec.md, section 6, rules 7 and 8): the
rules are fixed before any result is seen, the strategy is frozen, then there
is one out-of-sample test. This script writes resources/strategy_freeze.json:
the rules, the SHA-256 of every code file and of every input file of the test,
the forecasts of each version that exists, the versions of the libraries. The
scripts that read the test sample check all of it (freeze_guard.py).

The record is created once (exclusive creation: an existing record is never
replaced). It is meant to be committed and tagged at once, so that it is
anchored in the history of the repository. A new freeze after the test has
been opened would be a new trial, to be declared as such.

Run from Project/, by decision of the project owner only:
    python scripts/backtest/4_freeze.py --declared-by "<name>"
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_guard as guard  # noqa: E402
from freeze_guard import PROCESSED, PROJECT, CheckError, check, sha256  # noqa: E402

DOCUMENTS = ["SignalSpec.md", "ProjectJournal.md"]
# Reports of the development runs that must exist: the code was run on 1981-1992 before the freeze.
DEVELOPMENT_REPORTS = ["predictions_A_report.json", "portfolio_candidates_A_development_report.json",
                       "first_day_fills_report.json", "backtest_A_development_report.json"]

RULES = {
    "samples": "test = return months 1993-01 to 2025-12; development = 1981-01 to 1992-12 (not out of sample, never a "
               "result). Each sample starts from a book that is all cash.",
    "main_result": "version A, boosted trees, all sizes, first-day execution, order cap of 10 % of the ADV, net of half "
                   "spread and price impact and before commissions, 1993-2025: alpha against the five Fama-French "
                   "factors and momentum (Ken French files), Newey-West t-statistic with 6 lags",
    "versions": "A (market characteristics) is the main conclusion; B (market and accounting characteristics) is a "
                "complement, run later through the same frozen scripts; its forecasts must come from the frozen "
                "prediction script. No rule is reopened after A is seen.",
    "models": "gradient-boosted trees (main), ridge regression (robustness); both reported whatever they give",
    "universes": "all eligible stocks (main); eligible stocks at or above the NYSE 20th percentile of market equity",
    "selection": "bought if in the top 10 % of the forecasts (NYSE breakpoints, discrete quantile) and at least one "
                 "characteristic observed; kept while in the top 20 %; stocks tied with a breakpoint are all in; a "
                 "stock held with every characteristic missing can be reduced, not increased (D18); a stock held "
                 "that leaves the universe or is no longer eligible has a target of zero",
    "weights": "value weights (market equity of t) over the stocks to hold; no cap on a weight; concentration reported",
    "execution": "orders frozen with the data of t; filled at the close of the first trading day of t+1 only if CRSP "
                 "records a closing trade price (TR), a positive volume and no delisting (D13); sales before "
                 "purchases; a sale cannot exceed what is held; purchases paid with the cash available and all "
                 "reduced by one factor if it is short; unfilled purchase: cash; unfilled sale: position kept",
    "capacity": "constant nominal capital of USD 100 million; order capped at 10 % of the ADV, the smaller of "
                "dolvol_21d and dolvol_126d at t, both required (without them the order is zero). The cap of 10 % is a "
                "capacity scenario: no source validates a fill of that size at the last trade of the day; the result "
                "with a cap of 1 % is shown next to it.",
    "costs": "half spread on each amount filled (D14: quoted; else high-low if ranges were observed; else the mean "
             "of the eligible stocks of the same size group and month; the highest group mean of the month if the "
             "stock has no size group or its group has no donor) and price impact lambda x sqrt(amount filled / ADV) "
             "per dollar, on the amount really filled after any reduction of the purchases, lambda 0.025 nano and micro, 0.015 small, 0.010 large and mega, "
             "0.025 without a size group (D22). No commission in the main result (D15).",
    "returns": "the book held earns the first-day return; a position earns (1 + ret) / (1 + ret_d1) - 1 for the rest "
               "of the month; unknown return of a stock held: full write-off (D16); a stock with no row the following "
               "month leaves the panel and its value goes to cash (D17); cash after the trades earns the risk-free "
               "rate of the month; gross return = net return + costs of the month",
    "configurations": ["gbrt_all_d1 (main)", "gbrt_large_d1", "ridge_all_d1", "ridge_large_d1", "gbrt_all_close",
                       "gbrt_large_close", "ridge_all_close", "ridge_large_close", "gbrt_all_d1_cap01",
                       "gbrt_large_d1_cap01"],
    "comparisons": "secondary and fixed here: the ten configurations (two models, two universes, close-to-close "
                   "execution, order cap of 1 %); commission stress of USD 0.06 a share until December 2004 and 0.04 "
                   "from January 2005 on the same fills; gross against net; sub-periods 1993-2008 and 2009-2025; "
                   "version A against version B",
    "evaluation": "regression of the excess return (over the risk-free rate) on CAPM, FF3, FF5 and FF5 + momentum, Ken "
                  "French factors, Newey-West with 6 lags and no small-sample correction; mean of the return minus the "
                  "market (FF3 market factor) with the same t-statistic; one conditional diagnostic for the main "
                  "configuration on 1993-2025: the six factors and their products with the share of the fund invested "
                  "at the previous month end, centred on its mean (computed the same way for version B when it is run)",
    "factors_rebuilt_from_our_data": "rule D20 is postponed: not part of this test; if done later it is secondary",
    "sealed": "predictions_<version>_choices_sealed.parquet is opened after the test results are written, to report "
              "the values chosen at the edge of their grid",
}
# Trials made on the development years before the freeze (rule 8).
TRIALS = [
    "2026-11-13: with the order cap of 1 % of the ADV (rule of 2026-11-12) the fund stayed 72 to 85 % in cash on "
    "1981-1992. Caps of 0.5, 1, 5, 10, 25 and 100 % were compared on the cash share, the turnover and the costs. The "
    "simulator produced monthly returns for these runs, as it always does; no statistic of performance was computed, "
    "printed or looked at to choose the cap. The project owner chose 10 %, with 1 % as the stress test.",
    "2026-11-13: the alpha script was run on the development backtest to check that it runs; it computes its "
    "regressions and writes and prints none of them.",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--declared-by", required=True, help="name of the project owner who declares the freeze")
    args = ap.parse_args()
    check(not guard.FREEZE.exists(), "The freeze is already recorded: it is created once")
    check(not guard.OPENINGS.exists() and not guard.STEPS.exists(), "A log of openings or of steps exists without a freeze")
    for name in DEVELOPMENT_REPORTS:
        check((PROCESSED / name).exists(), f"{name} is missing: the code must have run on the development years")
    for name in ("portfolio_candidates", "backtest"):
        for v in ("A", "B"):
            check(not (PROCESSED / f"{name}_{v}_test.parquet").exists(), f"A test output of {name} already exists")
    git = lambda *a: subprocess.run(["git", *a], cwd=PROJECT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    code = {c: sha256(PROJECT / c) for c in guard.CODE}
    # What every prediction run must have used: read in the report of version A, whose
    # forecasts exist. Version B, still being computed, is held to the same inputs,
    # settings and calendar when it is opened.
    rep_a = guard.prediction_report("A")
    check(rep_a.get("script_sha256") == code[guard.PREDICTIONS_SCRIPT] and rep_a.get("version") == "A",
          "The forecasts of version A were not produced by the prediction script as it is today")
    commitments = {k: rep_a[k] for k in guard.COMMITMENTS}
    predictions = {"A": rep_a["outputs"]["predictions_A_test.parquet"]}
    check(sha256(PROCESSED / "predictions_A_test.parquet") == predictions["A"],
          "predictions_A_test.parquet does not match its report")      # the bytes are hashed, the file is not decoded
    import lightgbm
    import numpy
    import polars
    import statsmodels
    record = {
        "freeze_id": uuid.uuid4().hex[:12],
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "declared_by": args.declared_by,
        "statement": "The rules below are frozen. No statistic of the returns of the strategy has been computed or "
                     "seen on 1993-2025, and the test and sealed files have not been opened. The test sample is "
                     "opened once per version, by the code and on the inputs hashed here.",
        "git_commit": git("rev-parse", "HEAD"), "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "uncommitted_changes": git("status", "--porcelain"),
        "code_sha256": code,
        "inputs_sha256": {n: sha256(PROCESSED / n) for n in guard.INPUTS},
        "predictions_test_sha256": predictions,
        "prediction_commitments": commitments,
        "documents_sha256": {d: sha256(PROJECT / d) for d in DOCUMENTS},
        "development_runs": {n: json.loads((PROCESSED / n).read_text(encoding="utf-8"))["run_id"] for n in DEVELOPMENT_REPORTS},
        "libraries": {"python": platform.python_version(), "numpy": numpy.__version__, "polars": polars.__version__,
                      "statsmodels": statsmodels.__version__, "lightgbm": lightgbm.__version__},
        "rules": RULES,
        "trials_on_the_development_years": TRIALS,
    }
    with guard.FREEZE.open("x", encoding="utf-8") as f:     # exclusive creation: never replaces a record
        f.write(json.dumps(record, indent=2) + "\n")
    print(f"Freeze {record['freeze_id']} recorded by {args.declared_by} at {record['frozen_at']}: "
          f"{len(code)} files of code, {len(record['inputs_sha256'])} inputs, forecasts of version A; version B is "
          "held to the same prediction script, inputs, settings and calendar.")
    if record["uncommitted_changes"]:
        print("Note: the working tree has uncommitted changes; commit and tag the record to anchor it.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
