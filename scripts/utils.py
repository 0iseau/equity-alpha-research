"""Shared helpers for the data pipeline: paths, safe writes, checks."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

PROJECT = Path(__file__).resolve().parents[1]
RAW = PROJECT / "data" / "raw"
PROCESSED = PROJECT / "data" / "processed"


class CheckError(Exception):
    """A data check failed. The script stops; nothing is written."""


def check(condition: bool, message: str) -> None:
    # Stop the script when a check fails.
    if not condition:
        raise CheckError(message)


def sha256(path: Path) -> str:
    # Fingerprint of a file, to trace which input made which output.
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_verified(path: Path, report_path: Path) -> tuple[pl.DataFrame, str]:
    """
    Description:
        Read an output of an earlier step, only if it matches its report.
    Steps:
        1) Read the earlier step's report (it is written last by publish).
        2) Check the file's SHA-256 against the report.
    Output:
        The table, and the run id it comes from.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    expected = report.get("outputs", {}).get(path.name)
    check(expected is not None, f"{path.name} is not listed in {report_path.name}")
    # Hash and read the same bytes, so no other run can slip in between.
    data = path.read_bytes()
    check(hashlib.sha256(data).hexdigest() == expected,
          f"{path.name} does not match {report_path.name}: mixed runs?")
    return pl.read_parquet(io.BytesIO(data)), report["run_id"]


def publish(outputs: dict[Path, pl.DataFrame], report: dict, report_path: Path) -> None:
    """
    Description:
        Write all outputs of one run, then the report last.
    Steps:
        1) Write every output to a temp file named with this run's id.
        2) Record each file's SHA-256 in the report.
        3) Rename the temp files to their final names.
        4) Write the report last: it lists the hashes of this run's files,
           so a mix of two runs can be detected.
    Output:
        Output files and the report in their final place.
    """
    run_id = uuid.uuid4().hex[:12]
    report["run_id"] = run_id
    report["outputs"] = {}
    temps = {}
    for path, df in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{run_id}.tmp")
        if path.suffix == ".csv":
            df.write_csv(tmp)
        else:
            df.write_parquet(tmp)
        temps[path] = tmp
        report["outputs"][path.name] = sha256(tmp)
    for path, tmp in temps.items():
        tmp.replace(path)

    report["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    tmp = report_path.with_name(f"{report_path.name}.{run_id}.tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(report_path)
