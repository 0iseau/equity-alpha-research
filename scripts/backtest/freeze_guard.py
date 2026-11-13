"""The guard of the single out-of-sample test (after the audits by Astra of 2026-11-13).

Every script that reads the test sample (1993-2025) goes through three calls.

1. require_freeze(script, version, outputs), before anything is read. The test
   is refused unless:
   - the freeze record exists, with its identifier, its date and the
     declaration of the project owner;
   - every file listed in CODE has today the SHA-256 it had at the freeze: the
     five scripts, this guard, the shared utilities and the list of signals;
   - every input file listed at the freeze has the SHA-256 it had then (panel,
     daily summaries, first-day fills, factors, ranks);
   - the forecasts of the version come from the frozen prediction script, were
     made on the inputs, settings and calendar committed at the freeze, and are
     the file recorded at the freeze or at the first opening of the version;
   - the outputs of the script, their report included, do not exist.
   The opening is written to resources/test_openings.jsonl.
2. reserve(step, version, freeze), which creates exclusively the file of the
   attempt in resources/test_steps/. Two runs cannot hold the same step: the
   second one fails on the creation. A step that is completed is never run
   again, even if its output has disappeared. A step whose earlier attempt did
   not finish needs --retry, and the new attempt is numbered after it.
3. finish(reservation, report), after the publication: the SHA-256 of every
   output, report included, is written in the file of the attempt.

The data are read with read_frozen(path, expected): the bytes that are decoded
are the bytes whose SHA-256 is compared. The expected hash of the forecasts is
the one of the freeze (or of the first opening); the expected hash of a result
of an earlier step is the one written by finish() for that step.

A direct read of the parquet files is not prevented by this module: the rule
that nobody opens them before the freeze is a rule of conduct, written in the
freeze record.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import PROCESSED, PROJECT, CheckError, check, sha256  # noqa: E402,F401

FREEZE = PROJECT / "resources" / "strategy_freeze.json"
OPENINGS = PROJECT / "resources" / "test_openings.jsonl"
STEPS = PROJECT / "resources" / "test_steps"
PREDICTIONS_SCRIPT = "scripts/predictions/1_predictions.py"
CODE = [PREDICTIONS_SCRIPT, "scripts/portfolio/1_candidates.py", "scripts/backtest/1_first_day.py",
        "scripts/backtest/2_backtest.py", "scripts/backtest/3_alphas.py", "scripts/backtest/freeze_guard.py",
        "scripts/data_cleaning/utils.py",
        # read by the candidates script to know the characteristics of each version
        "resources/signal_list.csv"]
INPUTS = ["crsp_panel_acc.parquet", "crsp_daily_agg.parquet", "first_day_fills.parquet", "ff_factors_monthly.parquet",
          "signal_ranks.parquet"]
# What a prediction run commits to, whatever its version: read in its report.
COMMITMENTS = ["inputs", "settings", "calendar"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prediction_report(version: str) -> dict:
    path = PROCESSED / f"predictions_{version}_report.json"
    check(path.is_file(), f"{path.name} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def openings() -> list[dict]:
    if not OPENINGS.exists():
        return []
    return [json.loads(line) for line in OPENINGS.read_text(encoding="utf-8").splitlines() if line.strip()]


def require_freeze(script: str, version: str, outputs: list[Path]) -> dict:
    """See the header. Returns the identity of the freeze and the expected hash of the test forecasts."""
    check(FREEZE.is_file(), "The test sample is read only after the freeze (resources/strategy_freeze.json)")
    fr = json.loads(FREEZE.read_text(encoding="utf-8"))
    check(isinstance(fr, dict) and all(fr.get(k) for k in ("freeze_id", "frozen_at", "declared_by")),
          "The freeze record has no identifier, no date or no declaration of the project owner")
    check(script in CODE, f"{script} is not a script of the frozen chain")
    for code in CODE:
        check(fr.get("code_sha256", {}).get(code) == sha256(PROJECT / code),
              f"{code} is not the file recorded at the freeze")
    for name in INPUTS:
        check(fr.get("inputs_sha256", {}).get(name) == sha256(PROCESSED / name),
              f"{name} is not the file recorded at the freeze")
    rep = prediction_report(version)
    check(rep.get("script_sha256") == fr["code_sha256"][PREDICTIONS_SCRIPT],
          f"The forecasts of version {version} were not produced by the frozen prediction script")
    check(rep.get("version") == version, f"The prediction report of version {version} names another version")
    for key in COMMITMENTS:                                # same inputs, settings and calendar as committed at the freeze
        check(rep.get(key) == fr.get("prediction_commitments", {}).get(key),
              f"The forecasts of version {version} were not made with the {key} committed at the freeze")
    pred = rep["outputs"][f"predictions_{version}_test.parquet"]
    recorded = fr.get("predictions_test_sha256", {}).get(version)
    check(recorded is None or recorded == pred, f"The test forecasts of version {version} changed since the freeze")
    for o in openings():
        if o["version"] == version:
            check(o["freeze_id"] == fr["freeze_id"] and o["predictions_test_sha256"] == pred,
                  f"Version {version} was opened before with another freeze or other forecasts")
    for path in outputs:
        check(not path.exists(), f"{path.name} already exists: a result of the test is never overwritten")
    line = {"opened_at_utc": now(), "script": script, "version": version, "freeze_id": fr["freeze_id"],
            "script_sha256": sha256(PROJECT / script), "predictions_test_sha256": pred}
    with OPENINGS.open("a", encoding="utf-8") as f:        # written before the first read of the test sample
        f.write(json.dumps(line) + "\n")
    return {"freeze_id": fr["freeze_id"], "frozen_at": fr["frozen_at"], "sha256": sha256(FREEZE),
            "predictions_test_sha256": pred}


def attempts(step: str, version: str, freeze: dict) -> list[tuple[Path, dict]]:
    prefix = f"{freeze['freeze_id']}_{version}_{step}.attempt"
    found = sorted(STEPS.glob(prefix + "*.json"), key=lambda p: int(p.name[len(prefix):-5])) if STEPS.exists() else []
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in found]


def reserve(step: str, version: str, freeze: dict, retry: bool = False) -> Path:
    """Take the step for this run, exclusively (see the header). Returns the file of the attempt."""
    check(sha256(FREEZE) == freeze["sha256"], "The freeze record changed since it was checked")
    STEPS.mkdir(parents=True, exist_ok=True)
    earlier = attempts(step, version, freeze)
    check(all(rec["status"] != "done" for _, rec in earlier),
          f"The step {step} of version {version} is completed: it is never run again")
    check(not earlier or retry,
          f"An earlier attempt of the step {step} of version {version} did not finish: pass --retry, it will be recorded")
    path = STEPS / f"{freeze['freeze_id']}_{version}_{step}.attempt{len(earlier) + 1}.json"
    rec = {"status": "started", "step": step, "version": version, "freeze_id": freeze["freeze_id"],
           "freeze_sha256": freeze["sha256"], "predictions_test_sha256": freeze["predictions_test_sha256"],
           "started_at_utc": now(), "earlier_attempts": [p.name for p, _ in earlier]}
    try:
        with path.open("x", encoding="utf-8") as f:        # exclusive creation: a second run fails here
            f.write(json.dumps(rec, indent=2) + "\n")
    except FileExistsError:
        raise CheckError(f"Another run holds the step {step} of version {version}")
    return path


def completed_output(step: str, version: str, freeze: dict, name: str) -> str:
    """SHA-256 of an output of a completed earlier step, made under the same freeze record."""
    done = [rec for _, rec in attempts(step, version, freeze) if rec["status"] == "done"]
    check(len(done) == 1, f"The step {step} of version {version} is not completed under this freeze")
    check(done[0]["freeze_sha256"] == freeze["sha256"], f"The step {step} was run under another freeze record")
    check(name in done[0]["outputs_sha256"], f"{name} is not an output of the step {step}")
    return done[0]["outputs_sha256"][name]


def read_frozen(path: Path, expected: str) -> pl.DataFrame:
    """Read a parquet file of the test chain: the bytes decoded are the bytes whose hash is checked."""
    data = path.read_bytes()
    check(hashlib.sha256(data).hexdigest() == expected, f"{path.name} is not the file expected by the freeze")
    return pl.read_parquet(io.BytesIO(data))


def finish(reservation: Path, report_path: Path) -> None:
    """After publish(): record the hashes of the outputs listed in the report, and of the report itself."""
    rec = json.loads(reservation.read_text(encoding="utf-8"))
    check(rec["status"] == "started", f"{reservation.name} is not an attempt in progress")
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    outputs = dict(rep["outputs"])
    for name, digest in outputs.items():                   # the files on disk are the ones the report lists
        check(sha256(report_path.parent / name) == digest, f"{name} does not match its report after the publication")
    outputs[report_path.name] = sha256(report_path)
    rec.update(status="done", completed_at_utc=now(), run_id=rep["run_id"], outputs_sha256=outputs)
    tmp = reservation.with_name(reservation.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    tmp.replace(reservation)
