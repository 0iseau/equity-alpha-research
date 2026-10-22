"""Download native FRED histories and ALFRED revision records (standard library only).

Run from anywhere: python src/download_public_data.py
See data/README.md for selection, timing rules, and limitations.
This collects data only; it does not construct signals or fit a model.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
import calendar
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import io
from http.client import HTTPException
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_END = "2025-12-31"  # Last month in the local CRSP market-index extract.
SERIES = {
    "VIXCLS": {
        "title": "Cboe VIX daily close", "start": "1990-01-02",
        "frequency": "daily close", "units": "index", "adjustment": "NSA",
        "role": "core candidate", "purpose": "Option-implied near-term equity uncertainty.",
        "caveats": "Current VIX methodology dates to 2003; earlier history is backcast. ALFRED starts later. A close cannot be used to trade at that same close.",
    },
    "BAA10Y": {
        "title": "Moody's Baa yield minus 10-year Treasury yield", "start": "1986-01-02",
        "frequency": "daily", "units": "percentage points", "adjustment": "NSA",
        "role": "core candidate", "purpose": "Credit conditions and compensation for corporate credit risk.",
        "caveats": "Contains credit, liquidity and maturity effects; not a pure default-risk measure. Observation date does not establish publication time.",
    },
    "T10Y3M": {
        "title": "10-year minus 3-month Treasury yield", "start": "1982-01-04",
        "frequency": "daily", "units": "percentage points", "adjustment": "NSA",
        "role": "core candidate", "purpose": "Yield-curve slope and monetary/business-cycle conditions.",
        "caveats": "Negative values are valid. Not a deterministic recession or equity-return forecast. Observation date is not publication time.",
    },
    "UNRATE": {
        "title": "Civilian unemployment rate", "start": "1948-01-01",
        "frequency": "monthly", "units": "percent", "adjustment": "SA",
        "role": "core candidate", "purpose": "Labour-market conditions; changes can help describe the business cycle.",
        "caveats": "Reference month is not release month; seasonal adjustments and historical definitions change. Do not substitute today's revisions for historical releases.",
    },
    "INDPRO": {
        "title": "Industrial production: total index", "start": "1919-01-01",
        "frequency": "monthly", "units": "index, currently 2017=100", "adjustment": "SA",
        "role": "core candidate", "purpose": "Real activity, complementary to the labour market.",
        "caveats": "Frequently revised and rebased; index bases differ across vintages. Growth must be calculated within one as-of vintage, not across releases.",
    },
    "CPIAUCSL": {
        "title": "Consumer price index: all urban consumers, all items", "start": "1947-01-01",
        "frequency": "monthly", "units": "index, currently 1982-84=100", "adjustment": "SA",
        "role": "core candidate", "purpose": "Inflation environment; a later 12-month change can distinguish inflationary stress.",
        "caveats": "SA history is revised. Vintage metadata include older units and a predecessor population concept before 1981; never pool those blindly. Derive inflation within one vintage.",
    },
    "NFCI": {
        "title": "Chicago Fed National Financial Conditions Index", "start": "1971-01-08",
        "frequency": "weekly, ending Friday", "units": "index", "adjustment": "NSA",
        "role": "optional comparison", "purpose": "Published composite benchmark for broad financial conditions.",
        "caveats": "Overlaps VIX/credit information; not an automatic extra predictor. History and estimated weights are revised. Historical start in 1971 does not mean it was available then; ALFRED begins in 2011.",
    },
}


def iso(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError(f"Not an ISO date: {value!r}")
    return parsed


def number(value: str) -> bool:
    """Missing observations are retained, never changed to zero."""
    if value in ("", "."):
        return False
    try:
        if not Decimal(value).is_finite():
            raise ValueError(f"Non-finite value: {value}")
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    return True


class DownloadForm(HTMLParser):
    """Read the official form; fail visibly if its schema changes."""

    def __init__(self):
        super().__init__()
        self.vintages: list[str] = []
        self.inputs: dict[str, str] = {}
        self.in_vintages = False
        self.vintage_name = ""

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and fields.get("name", "").startswith("form["):
            self.inputs[fields["name"]] = fields.get("value", "")
        if tag == "select":
            self.in_vintages = fields.get("id") == "form_selected_vintage_dates"
            if self.in_vintages:
                self.vintage_name = fields["name"]
        if tag == "option" and self.in_vintages:
            self.vintages.append(iso(fields["value"]).isoformat())

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_vintages = False


def fetch(url: str, fields=None) -> tuple[bytes, dict]:
    payload = urlencode(fields).encode("ascii") if fields is not None else None
    for attempt in range(4):
        try:
            request = Request(url, data=payload)
            with urlopen(request, timeout=120) as response:
                body = response.read()
                info = {
                    "url": response.url, "method": "POST" if payload is not None else "GET",
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "content_type": response.headers.get("Content-Type"),
                    "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                }
                return body, info
        except (URLError, OSError, HTTPException) as exc:
            if isinstance(exc, HTTPError) and exc.code < 500 and exc.code != 429:
                raise
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Unreachable")


def latest_stats(body: bytes, sid: str, start: str, end: str) -> dict:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    if reader.fieldnames != ["observation_date", sid]:
        raise ValueError(f"Unexpected FRED CSV header: {reader.fieldnames}")
    observed, valid, missing, previous = [], [], 0, ""
    for row in reader:
        d = row["observation_date"]
        iso(d)
        if not start <= d <= end or d <= previous:
            raise ValueError(f"Out-of-range, duplicate or unordered observation: {sid} {d}")
        previous = d
        observed.append(d)
        if number(row[sid]):
            valid.append(d)
        else:
            missing += 1
    if not valid:
        raise ValueError(f"No numeric observations: {sid}")
    return {"rows": len(observed), "numeric_observations": len(valid), "missing": missing,
            "first_valid": valid[0], "last_valid": valid[-1]}


def archive_stats(body: bytes, sid: str, start: str, end: str, vintages: list[str]) -> dict:
    """Validate revision intervals, including explicit missing/deletion records."""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupted ALFRED zip")
        csv_names = [n for n in archive.namelist() if n.endswith(".csv")]
        readmes = [n for n in archive.namelist() if n.lower().endswith("readme.txt")]
        if len(csv_names) != 1 or len(readmes) != 1:
            raise ValueError(f"Unexpected ALFRED archive members: {archive.namelist()}")
        metadata = archive.read(readmes[0]).decode("utf-8-sig")
        if f"Series ID: {sid}" not in metadata or "Observations by Real-Time Period" not in metadata:
            raise ValueError("ALFRED series/output identity mismatch")
        intervals: dict[str, list[tuple[str, str]]] = {}
        rows, missing, earliest, latest = 0, 0, "9999-12-31", "0001-01-01"
        with archive.open(csv_names[0]) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
            if reader.fieldnames != ["period_start_date", sid, "realtime_start_date", "realtime_end_date"]:
                raise ValueError(f"Unexpected ALFRED CSV header: {reader.fieldnames}")
            for row in reader:
                obs, rt_start, rt_end = row["period_start_date"], row["realtime_start_date"], row["realtime_end_date"]
                iso(obs)
                iso(rt_start)
                last = "9999-12-31" if rt_end in ("", ".") else iso(rt_end).isoformat()
                if not start <= obs <= end or rt_start > end or last < rt_start or obs > rt_start:
                    raise ValueError(f"Invalid ALFRED interval: {sid} {row}")
                # A real-time interval must intersect at least one requested vintage.
                position = bisect_left(vintages, rt_start)
                if position == len(vintages) or vintages[position] > last:
                    raise ValueError("ALFRED returned an interval outside selected vintages")
                intervals.setdefault(obs, []).append((rt_start, last))
                missing += not number(row[sid])
                earliest, latest = min(earliest, rt_start), max(latest, rt_start)
                rows += 1
        if rows == 0:
            raise ValueError(f"Empty ALFRED history: {sid}")
        for obs, periods in intervals.items():
            periods.sort()
            if any(right[0] <= left[1] for left, right in zip(periods, periods[1:])):
                raise ValueError(f"Overlapping revision intervals: {sid} {obs}")
        return {"revision_records": rows, "missing_records": missing,
                "observation_periods": len(intervals), "first_observation": min(intervals),
                "last_observation": max(intervals), "first_realtime_start": earliest,
                "last_realtime_start": latest, "data_member": csv_names[0],
                "metadata_member": readmes[0]}


def write_json(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def month_ends(first: str, end: str) -> list[str]:
    year, month = iso(first).year, iso(first).month
    result = []
    while (year, month) <= (iso(end).year, iso(end).month):
        last = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
        if first <= last <= end:
            result.append(last)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    # Include exact cutoff, even if it is not a calendar month-end.
    return sorted(set([first, *result, end]))


def snapshot_stats(body: bytes, sid: str, vintages: list[str], start: str, end: str) -> dict:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    columns = [f"{sid}_{v.replace('-', '')}" for v in vintages]
    if reader.fieldnames != ["observation_date", *columns]:
        raise ValueError(f"ALFRED ignored or changed a requested vintage: {reader.fieldnames}")
    counts = dict.fromkeys(columns, 0)
    last_valid = dict.fromkeys(columns)
    quarantined = []
    previous = ""
    for row in reader:
        obs = row["observation_date"]
        iso(obs)
        if not start <= obs <= end or obs <= previous:
            raise ValueError(f"Invalid snapshot observation date: {obs}")
        previous = obs
        for column, vintage in zip(columns, vintages):
            if number(row[column]):
                if obs > vintage:
                    # Preserve the source bytes, but explicitly quarantine provider
                    # records labelled after the requested information cutoff.
                    quarantined.append({"column": column, "observation_date": obs,
                                        "value": row[column], "vintage_date": vintage})
                    continue
                counts[column] += 1
                last_valid[column] = obs
    if not all(counts.values()):
        raise ValueError("An ALFRED snapshot is empty")
    return {"eligible_numeric_observations_by_vintage": counts,
            "last_eligible_observation_by_vintage": last_valid,
            "quarantined_future_observations": quarantined}


def collect(sid: str, spec: dict, end: str, folder: Path) -> dict:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode(
        {"id": sid, "cosd": spec["start"], "coed": end})
    body, latest = fetch(url)
    (folder / f"{sid}_latest.csv").write_bytes(body)
    latest.update(latest_stats(body, sid, spec["start"], end))
    latest["file"] = f"{sid}_latest.csv"
    latest["safe_for_historical_signals"] = False

    form_url = f"https://alfred.stlouisfed.org/series/downloaddata?seid={sid}"
    html, form_request = fetch(form_url)
    (folder / f"{sid}_download_form.html").write_bytes(html)
    form = DownloadForm()
    form.feed(html.decode("utf-8"))
    if not form.vintages or not form.vintage_name or form.vintages != sorted(set(form.vintages)):
        raise ValueError("ALFRED vintage selector missing, duplicated or unordered")
    selected = [v for v in form.vintages if v <= end]
    if not selected:
        raise ValueError(f"No archived vintage exists on/before {end}: {sid}")
    if spec["frequency"].startswith("daily"):
        # Market data have many thousands of daily revisions. Keep daily observations
        # inside month-end as-of snapshots; do not claim a daily vintage panel.
        requested = month_ends(form.vintages[0], end)
        batches = []
        for offset in range(0, len(requested), 12):
            chunk = requested[offset:offset + 12]
            url = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?" + urlencode(
                {"id": ",".join([sid] * len(chunk)), "vintage_date": ",".join(chunk)})
            body, batch = fetch(url)
            filename = f"{sid}_snapshots_{len(batches) + 1:03d}.csv"
            (folder / filename).write_bytes(body)
            batch.update(snapshot_stats(body, sid, chunk, spec["start"], end))
            batch.update({"file": filename, "selected_vintages": chunk})
            batches.append(batch)
            print(f"  monthly vintage batch {len(batches)}/{(len(requested) + 11) // 12} validated", flush=True)
            time.sleep(0.25)
        historical = {"first_archived_vintage": form.vintages[0],
                      "mode": "daily observations in month-end as-of snapshots, plus first archive date and cutoff",
                      "suitable_decision_grid": "Monthly decisions strictly after the snapshot date; not a daily information panel.",
                      "selected_vintage_count": len(requested), "selected_vintages": requested,
                      "batches": batches, "form_request": form_request,
                      "form_file": f"{sid}_download_form.html"}
        quarantined = sum(len(b["quarantined_future_observations"]) for b in batches)
        historical["quarantined_future_observation_count"] = quarantined
        if quarantined:
            print(f"  WARNING: {quarantined} future-dated cells quarantined in the manifest; raw files retain them.", flush=True)
        return {**spec, "source": f"https://fred.stlouisfed.org/series/{sid}",
                "latest": latest, "alfred": historical}
    fields = [(key, value) for key, value in form.inputs.items() if key not in {
        "form[obs_start_date]", "form[obs_end_date]", "form[entered_vintage_dates]"}]
    fields += [("form[units]", "lin"), ("form[obs_start_date]", spec["start"]),
               ("form[obs_end_date]", end), ("form[entered_vintage_dates]", ""),
               ("form[file_type]", "1"), ("form[file_format]", "csv"), ("form[download_data]", "")]
    batches = []
    for offset in range(0, len(selected), 50):
        chunk = selected[offset:offset + 50]
        posted = fields + [(form.vintage_name, v) for v in chunk]
        body, batch = fetch(form_url, posted)
        filename = f"{sid}_realtime_{len(batches) + 1:03d}.zip"
        (folder / filename).write_bytes(body)
        batch.update(archive_stats(body, sid, spec["start"], end, chunk))
        batch.update({"file": filename, "selected_vintages": chunk, "post_fields": posted})
        batches.append(batch)
        print(f"  archive batch {len(batches)}/{(len(selected) + 49) // 50} validated", flush=True)
        time.sleep(0.25)
    historical = {"first_archived_vintage": form.vintages[0],
                  "mode": "all archived revision vintages, exported as real-time intervals",
                  "selected_vintage_count": len(selected), "selected_vintages": selected,
                  "exported_records_including_batch_duplicates": sum(b["revision_records"] for b in batches),
                  "batches": batches, "form_request": form_request,
                  "form_file": f"{sid}_download_form.html"}
    return {**spec, "source": f"https://fred.stlouisfed.org/series/{sid}",
            "latest": latest, "alfred": historical}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", default=DEFAULT_END, help="Observation and vintage cutoff (YYYY-MM-DD).")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "data" / "raw" / "public")
    args = parser.parse_args()
    cutoff = iso(args.end)
    if cutoff > datetime.now(timezone.utc).date() or any(args.end < s["start"] for s in SERIES.values()):
        parser.error("Cutoff must not be in the future or precede a selected series' inception.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = args.output_dir.resolve() / f"fred_{args.end}_{stamp}"
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "running", "observation_and_vintage_cutoff": args.end,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "backtest_ready": False,
                "policy": "Native data only. Latest revisions are descriptive. ALFRED coverage is series-specific; metadata and publication timing must be checked before signal construction. No filling, aggregation, scaling, model fitting or alpha selection.",
                "series": {}, "errors": {}}
    write_json(folder / "manifest.json", manifest)
    print(f"Output: {folder}", flush=True)
    for sid, spec in SERIES.items():
        print(f"Collecting {sid} ...", flush=True)
        try:
            result = collect(sid, spec, args.end, folder)
            manifest["series"][sid] = result
            latest, alfred = result["latest"], result["alfred"]
            print(f"  {latest['numeric_observations']} values, {latest['first_valid']} to {latest['last_valid']}; "
                  f"{alfred['selected_vintage_count']} vintages; archive begins {alfred['first_archived_vintage']}", flush=True)
        except Exception as exc:
            manifest["errors"][sid] = f"{type(exc).__name__}: {exc}"
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        write_json(folder / "manifest.json", manifest)
        time.sleep(0.25)
    manifest["status"] = "failed" if manifest["errors"] else "complete"
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(folder / "manifest.json", manifest)
    print(f"Status: {manifest['status']}. Manifest: {folder / 'manifest.json'}", flush=True)
    return 1 if manifest["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
