"""Download public files from the Ken French Data Library (standard library only).

Files: NYSE size breakpoints, FF3 factors with the risk-free rate, FF5 factors,
momentum. They are saved unchanged (zip) in data/raw/french/, with a manifest
(URL, time, SHA-256). Run: python scripts/download_french_data.py

Raw data never changes: if a file already exists with other bytes (a new
vintage), the script stops before writing anything.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FILES = [
    "ME_Breakpoints_CSV.zip",               # NYSE size percentiles, monthly
    "F-F_Research_Data_Factors_CSV.zip",    # Mkt-RF, SMB, HML, RF
    "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "F-F_Momentum_Factor_CSV.zip",
]
OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "french"
MANIFEST = OUT / "manifest.json"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    old = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"] if MANIFEST.exists() else {}

    # 1) Download everything in memory first.
    bodies = {}
    for name in FILES:
        # Generic client name; no personal data in the request.
        req = Request(BASE + name, headers={"User-Agent": "research-data-client"})
        with urlopen(req, timeout=120) as r:
            bodies[name] = r.read()

    # 2) Stop if any existing file would change (keep the vintage already used).
    for name, body in bodies.items():
        path = OUT / name
        if path.exists() and path.read_bytes() != body:
            raise SystemExit(f"{name}: a new vintage is online. Move the old file to keep "
                             "it, then rerun. Nothing was written.")

    # 3) Write new files (temp then rename); keep old manifest entries for same bytes.
    manifest = {"source": BASE, "files": {}}
    for name, body in bodies.items():
        path = OUT / name
        if path.exists() and name in old:
            manifest["files"][name] = old[name]
            print(f"{name}: unchanged")
            continue
        tmp = OUT / (name + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        manifest["files"][name] = {
            "url": BASE + name,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        print(f"{name}: {len(body):,} bytes")

    # 4) Manifest last, temp then rename.
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp.replace(MANIFEST)


if __name__ == "__main__":
    main()
