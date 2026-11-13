"""Signals, script 3: the signal panel at the formation date, and the ranks.

Reference code (Resources/reference_code/jkp-data, commit b5695ea, aux_functions.py):
    add_me_data_and_compute_me_mev_mat_eqdur_vars -> mev, the *_me and *_mev
                                                     ratios, enterprise_value, eq_dur
    scale_me, scale_mev -> x / me_company and x / mev, denominator != 0
Ranks: Gu, Kelly and Xiu (2020), cross-sectional ranks mapped to [-1, 1].

What the script does (SignalSpec.md, section 4.3):
- One row per (permno, yyyymm) of the panel. The 59 market characteristics of
  script 1 are on the same key. The accounting characteristics of script 2 are
  keyed by fiscal year end and have no availability date: they are attached only
  through acc_datadate of the panel (rule D4: accounts 6 to 18 months old), never
  on the month of datadate. The join is many to one.
- The 23 characteristics that need a market value use the market value of the
  company at month t, never the one of the fiscal year end.
- Ranks by month over the eligible stocks only (rule D18), average rank for
  ties: s = 2 (r - 1) / (n - 1) - 1. A missing value gets 0 and a flag of 1.

Declared deviations from JKP for the 23 market-scaled characteristics:
- JKP sums the share classes that are present, even if one has no market
  equity, and uses price x shares. We use me_company of the panel (CRSP market
  cap) and only where me_company_complete is true.
- No currency conversion (fx = 1): our accounts are in USD only.
- Rule D26 (after the audit by Astra of 2026-11-13): when the CRSP company
  (permco) of the month has stocks linked to more than one Compustat company
  (tracking stocks, for instance the Liberty groups), me_company is the value of
  the whole and the accounts are those of one part: the 23 characteristics are
  missing. JKP has no such rule (it takes, by gvkey and month, the largest
  me_company among the main common stocks).
- Accounts reach a stock only through our links (D5). A secondary share class
  without a link keeps its market characteristics; its accounting
  characteristics stay missing and are never copied through permco.
Our extension to GKX: one missing flag per characteristic (GKX fill with the
monthly median and have no flag).

Choices of this script, with no effect on the values:
- The work is done by blocks of months, because the full table does not fit in
  memory (5.2 million rows x 194 columns). A block reads only its own months of
  the panel and of signals_price. Both outputs are sorted by (yyyymm, permno).
- signal_ranks has the eligible rows only: a rank exists only for a stock that
  can be bought. Ranks are stored as Float32 (the step between two ranks is
  above 1e-4), flags as Int8.
- The ranks are taken over all eligible stocks of the month, not inside
  industries (decision of the project owner, 2026-11-13: SignalSpec.md, section
  7, decision 3).

Inputs: data/processed/crsp_panel_acc.parquet, signals_price.parquet,
        signals_acc.parquet (hashes checked against the reports of their steps)
Outputs:
    signal_panel.parquet        raw values, one row per (permno, yyyymm)
    signal_ranks.parquet        ranks and missing flags, eligible rows
    signal_panel_report.json    checks, coverage and hashes (written last)

Run from Project/:  python scripts/signals/3_signal_panel.py
"""

from __future__ import annotations

import csv
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow.parquet as pq
from scipy.stats import rankdata

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import (PROCESSED, PROJECT, CheckError, check, check_unchanged, file_stamps,  # noqa: E402
                   read_verified, sha256)

PANEL = PROCESSED / "crsp_panel_acc.parquet"
PANEL_REPORT = PROCESSED / "accounting_availability_report.json"
PRICE = PROCESSED / "signals_price.parquet"
PRICE_REPORT = PROCESSED / "signals_price_report.json"
ACC = PROCESSED / "signals_acc.parquet"
ACC_REPORT = PROCESSED / "signals_acc_report.json"
SIGNAL_LIST = PROJECT / "resources" / "signal_list.csv"
DICTIONARY = PROJECT / "resources" / "data_dictionary.csv"
OUT_PANEL = PROCESSED / "signal_panel.parquet"
OUT_RANKS = PROCESSED / "signal_ranks.parquet"
OUT_REPORT = PROCESSED / "signal_panel_report.json"

KEYS = ["permno", "yyyymm", "eom"]
PANEL_COLS = KEYS + ["permco", "eligible", "me", "me_company", "me_company_complete", "gvkey", "acc_datadate",
                     "acc_age_months"]
BLOCK_YEARS = 5
SAMPLE_START = 196301
ACC_AGE_MIN, ACC_AGE_MAX = 6, 18        # rule D4
TEST_DATES = [197506, 199912, 201503]   # 1999-12 is a fiscal year end

# JKP me_vars and mev_vars restricted to our list: name -> item of script 2.
ME_VARS = {"at": "at_x", "be": "be_x", "sale": "sale_x", "gp": "gp_x", "ebitda": "ebitda_x",
           "ope": "ope_x", "ni": "ni_x", "nix": "nix_x", "debt": "debt_x", "netdebt": "netdebt_x",
           "cash": "che"}
MEV_VARS = {"at": "at_x", "be": "be_x", "sale": "sale_x", "gp": "gp_x", "ebitda": "ebitda_x",
            "debt": "debt_x", "pstk": "pstk_x", "debtlt": "dltt", "debtst": "dlc", "cash": "che"}
MARKET_SCALED = ([f"{n}_me" for n in ME_VARS] + [f"{n}_mev" for n in MEV_VARS]
                 + ["enterprise_value", "eq_dur"])
ITEMS = sorted(set(ME_VARS.values()) | set(MEV_VARS.values())
               | {"netdebt_x", "ed_cd", "ed_cd_w", "ed_constant", "ed_err"})

# Acceptance cases of SignalSpec.md, section 5 (recomputed by the auditor):
# PERMNO 12490, GVKEY 006066, formation of 2000-12, fiscal year 1999 attached.
ACCEPTANCE = [
    (12490, 200012, "ret_12_1", -0.1292730033), (12490, 200012, "ret_60_12", 3.8744844134),
    (12490, 200012, "seas_1_1an", 0.0405560000), (12490, 200012, "eqnpo_12m", 0.0317017933),
    (12490, 200012, "be_me", 0.1449682576), (12490, 200012, "at_gr1", 0.0162020906),
    (12490, 200012, "gp_at", 0.4353163038), (12490, 200012, "debt_at", 0.3240642322),
    (12490, 200012, "ni_ar1", 0.7395355973), (12490, 200012, "ni_ivol", 0.0057040279),
    (12490, 200012, "eq_dur", 17.7678775022),
    # First and last month where the accounts of fiscal year 1999 are attached.
    (12490, 200006, "at_gr1", 0.0162020906), (12490, 200105, "at_gr1", 0.0162020906),
]
# 15997 (Braves Group tracking stock, PERMCO 54311 with three Compustat
# companies in 2023-04): market-scaled values are missing (D26), the others stay.
ACCEPTANCE_MISSING = [(10028, 201309, "ret_12_1"), (15997, 202304, "debt_mev"), (15997, 202304, "be_me"),
                      (15997, 202304, "eq_dur"), (15997, 202304, "enterprise_value")]
ACCEPTANCE_PRESENT = [(15997, 202304, "debt_at"), (15997, 202304, "ret_12_1")]


def mi_date(name: str) -> pl.Expr:
    # Month index of a date column.
    return pl.col(name).dt.year().cast(pl.Int32) * 12 + pl.col(name).dt.month().cast(pl.Int32)


def mi_ym(ym: int) -> int:
    return ym // 100 * 12 + ym % 100


def read_checked(path: Path, report_path: Path, columns: list[str], report: dict) -> pl.DataFrame:
    # Same function as in 1_price_signals.py: read some columns of an earlier
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


def signal_names() -> tuple[list[str], list[str]]:
    rows = list(csv.DictReader(open(SIGNAL_LIST, encoding="utf-8")))
    return ([r["characteristic"] for r in rows if r["version"] == "A"],
            [r["characteristic"] for r in rows if r["version"] == "B"])


def check_inputs_allowed() -> None:
    # No panel column read here may be known only after the formation month.
    avail = {(r["table"], r["column"]): r["availability"]
             for r in csv.DictReader(open(DICTIONARY, encoding="utf-8"))}
    for c in PANEL_COLS:
        a = avail.get(("crsp_panel_acc", c))
        check(a is not None, f"crsp_panel_acc.{c} is not in the data dictionary")
        check(a not in ("t+1", "after_t", "today"), f"crsp_panel_acc.{c} has availability {a}")


def check_formation(panel: pl.DataFrame) -> None:
    """
    Description:
        The accounts attached to a panel row are 6 to 18 months old (rule D4).
        Stops the script otherwise; a 5-month lag is caught here.
    """
    c = pl.col
    check(panel.select(KEYS[:2]).is_unique().all(), "Duplicate stock-month in the panel")
    check(panel["eligible"].null_count() == 0 and panel["me_company_complete"].null_count() == 0,
          "A flag of the panel is missing")
    with_acc = panel.filter(c("acc_datadate").is_not_null())
    check(with_acc["gvkey"].null_count() == 0, "Accounts attached without a company id")
    age = with_acc.select(age=mi_date("eom") - mi_date("acc_datadate"), given=c("acc_age_months"))
    check(age.filter(c("age") != c("given")).height == 0, "acc_age_months is not eom - acc_datadate")
    bad = age.filter((c("age") < ACC_AGE_MIN) | (c("age") > ACC_AGE_MAX)).height
    check(bad == 0, f"{bad} rows have accounts that are not {ACC_AGE_MIN} to {ACC_AGE_MAX} months old")
    check(panel.filter(c("me_company") <= 0).height == 0, "Non-positive company market value")
    check(panel["permco"].null_count() == 0, "A stock-month has no CRSP company id")


def build_block(panel: pl.DataFrame, price: pl.DataFrame, acc: pl.DataFrame, a_names: list[str],
                b_names: list[str], strict: bool = True) -> pl.DataFrame:
    """
    Description:
        Raw values of the 194 characteristics for the panel rows given.
    Steps:
        1) Market characteristics: same key as the panel, one to one.
        2) Accounting characteristics: (gvkey, acc_datadate) of the panel to
           (gvkey, datadate) of script 2, many to one.
        3) JKP add_me_data_and_compute_me_mev_mat_eqdur_vars with the company
           market value of month t (only if complete).
    Output:
        permno, yyyymm, eom, eligible, me, then the characteristics in the
        order of the signal list; sorted by (yyyymm, permno).
    """
    c = pl.col
    panel = panel.sort("yyyymm", "permno")
    price = price.sort("yyyymm", "permno")
    check(price.select(KEYS).equals(panel.select(KEYS)), "signals_price does not have the keys of the panel")
    j = panel.join(price.drop("eom"), on=["permno", "yyyymm"], how="left", validate="1:1")
    acc_b = [n for n in b_names if n not in MARKET_SCALED]
    right = acc.select("gvkey", "datadate", *acc_b, *ITEMS).with_columns(__acc=pl.lit(True))
    j = j.join(right, left_on=["gvkey", "acc_datadate"], right_on=["gvkey", "datadate"], how="left",
               validate="m:1")
    check(j.height == panel.height, "The join with the accounts changed the number of rows")
    check(j.filter(c("acc_datadate").is_null() & c("__acc").is_not_null()).height == 0,
          "Accounts attached to a row without acc_datadate")
    if strict:
        check(j.filter(c("acc_datadate").is_not_null() & c("__acc").is_null()).height == 0,
              "A row has an acc_datadate that is not in signals_acc")

    # Company market value of month t; JKP: non-positive me and mev are missing.
    # D26: not when the CRSP company carries several Compustat companies that
    # month (the block holds every stock of the month, so the count is complete).
    j = j.with_columns(__n_gvkey=c("gvkey").drop_nulls().n_unique().over("permco", "yyyymm"))
    j = j.with_columns(__me=pl.when(c("me_company_complete") & (c("me_company") > 0) & (c("__n_gvkey") <= 1))
                       .then(c("me_company")))
    j = j.with_columns(__mev=c("__me") + c("netdebt_x"))
    j = j.with_columns(__mev=pl.when(c("__mev") > 0).then(c("__mev")))
    eq_dur = c("ed_cd_w") / c("__me") + c("ed_constant") * (c("__me") - c("ed_cd")) / c("__me")
    j = j.with_columns(
        *[pl.when(c("__me") != 0).then(c(v) / c("__me")).alias(f"{n}_me") for n, v in ME_VARS.items()],
        *[pl.when(c("__mev") != 0).then(c(v) / c("__mev")).alias(f"{n}_mev") for n, v in MEV_VARS.items()],
        c("__mev").alias("enterprise_value"),
        pl.when((c("ed_err") == 1) | (eq_dur <= 0) | (c("__me") == 0)).then(None).otherwise(eq_dur)
        .alias("eq_dur"),
    )
    # A non-finite number (a division that overflows) is missing.
    j = j.with_columns([pl.when(c(n).is_finite()).then(c(n)).alias(n) for n in MARKET_SCALED])
    # A join does not promise the order of its rows: sort explicitly.
    return j.select(*KEYS, "eligible", "me", *a_names, *b_names).sort("yyyymm", "permno")


def rank_block(el: pl.DataFrame, names: list[str]) -> pl.DataFrame:
    """
    Description:
        Rule D18. By month, over the rows given (the eligible stocks): rank of
        the finite values with the average rank for ties, mapped to [-1, 1].
        Missing: 0 and flag 1. One value only: 0. All equal: 0.
    Output:
        permno, yyyymm, eom, then for each characteristic its rank (Float64) and
        `<name>_miss` (Int8), in the order of the rows given.
    """
    out = []
    for n in names:
        v = pl.when(pl.col(n).is_finite()).then(pl.col(n))
        cnt = v.count().over("yyyymm").cast(pl.Float64)
        r = v.rank("average").over("yyyymm")
        s = (pl.when(v.is_null()).then(0.0).when(cnt >= 2).then(2 * (r - 1) / (cnt - 1) - 1)
             .otherwise(0.0))
        out += [s.cast(pl.Float64).alias(n), v.is_null().cast(pl.Int8).alias(f"{n}_miss")]
    return el.select(*KEYS, *out)


def store_ranks(r: pl.DataFrame, names: list[str]) -> pl.DataFrame:
    return r.with_columns([pl.col(n).cast(pl.Float32) for n in names])


def check_rank_rule() -> None:
    # Cases written by hand (SignalSpec.md, section 4.3), and the special values.
    nan, inf = float("nan"), float("inf")
    toy = pl.DataFrame({
        "permno": list(range(1, 15)), "eom": [date(2000, 1, 31)] * 14,
        "yyyymm": [1] * 4 + [2] * 2 + [3] * 2 + [4] * 3 + [5] * 3,
        "x": [2.0, 2.0, 5.0, None, 7.0, None, None, None, 4.0, 4.0, 4.0, 1.0, nan, inf],
    }, schema_overrides={"yyyymm": pl.Int32})
    got = rank_block(toy, ["x"])
    check(got["x"].to_list() == [-0.5, -0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
          f"Rank rule, hand cases: {got['x'].to_list()}")
    check(got["x_miss"].to_list() == [0, 0, 0, 1, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1],
          f"Rank rule, flags of the hand cases: {got['x_miss'].to_list()}")
    # The stock id never breaks a tie: reversing the ids changes nothing.
    rev = rank_block(toy.with_columns(permno=15 - pl.col("permno")), ["x"])
    check(rev["x"].to_list() == got["x"].to_list(), "The stock id changes a rank")


class BlockWriter:
    # Writes a table block by block to a temporary file named with the run id.
    def __init__(self, path: Path, run_id: str):
        self.path, self.tmp, self.writer = path, path.with_name(f"{path.name}.{run_id}.tmp"), None

    def write(self, df: pl.DataFrame) -> None:
        table = df.to_arrow()
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.tmp, table.schema, compression="zstd")
        check(table.schema.equals(self.writer.schema), f"{self.path.name}: the schema changes between blocks")
        self.writer.write_table(table)

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None


def blocks(panel: pl.DataFrame) -> list[tuple[int, int]]:
    y0, y1 = panel["yyyymm"].min() // 100, panel["yyyymm"].max() // 100
    return [(y * 100 + 1, min(y + BLOCK_YEARS - 1, y1) * 100 + 12) for y in range(y0, y1 + 1, BLOCK_YEARS)]


class PriceReader:
    # The only access to signals_price. With a limit, the months after it do not
    # exist for the reader, and asking for one stops the script.
    def __init__(self, limit: int | None = None):
        self.limit = limit

    def rows(self, lo: int, hi: int) -> pl.DataFrame:
        check(self.limit is None or hi <= self.limit,
              f"signals_price: months up to {hi} are requested, the source ends at {self.limit}")
        scan = pl.scan_parquet(PRICE)
        if self.limit is not None:
            scan = scan.filter(pl.col("yyyymm") <= self.limit)
        return scan.filter(pl.col("yyyymm").is_between(lo, hi)).collect()


def produce_block(panel: pl.DataFrame, acc: pl.DataFrame, lo: int, hi: int, a_names: list[str],
                  b_names: list[str], reader: PriceReader) -> tuple[pl.DataFrame, pl.DataFrame]:
    # The production path of one block: raw values, then ranks of the eligible rows.
    part = panel.filter(pl.col("yyyymm").is_between(lo, hi))
    raw = build_block(part, reader.rows(lo, hi), acc, a_names, b_names)
    return raw, rank_block(raw.filter(pl.col("eligible")), a_names + b_names)


def block_stats(raw: pl.DataFrame, ranks: pl.DataFrame, names: list[str], stats: dict) -> None:
    """Checks on one block, and the sums that the report needs."""
    c = pl.col
    nonfinite = raw.select([(c(n).is_not_null() & ~c(n).is_finite()).sum().alias(n) for n in names]).row(0)
    check(sum(nonfinite) == 0, "A raw value is not finite")
    el = raw.filter(c("eligible"))
    check(ranks.select(KEYS).equals(el.select(KEYS)), "The ranks are not on the eligible rows")
    # Ranks: in [-1, 1]; flag 1 exactly where the value is missing, with rank 0;
    # by month the ranks sum to zero (average ranks are symmetric).
    worst = ranks.select(pl.max_horizontal([c(n).abs().max() for n in names])).item()
    check(worst is None or worst <= 1.0, f"A rank is outside [-1, 1]: {worst}")
    flags = ranks.select([c(f"{n}_miss").sum() for n in names]).row(0)
    nulls = el.select([c(n).null_count() for n in names]).row(0)
    check(flags == nulls, "The missing flags do not match the missing values")
    check(ranks.select([((c(f"{n}_miss") == 1) & (c(n) != 0)).sum() for n in names]).sum_horizontal().item() == 0,
          "A missing value has a rank that is not zero")
    if ranks.height:
        sums = ranks.group_by("yyyymm").agg([c(n).sum().abs() for n in names])
        check(sums.select(pl.max_horizontal(names).max()).item() < 1e-6, "The ranks of a month do not sum to zero")
        stats["distinct"].append(el.group_by("yyyymm").agg(
            [c(n).drop_nulls().n_unique().alias(n) for n in names]).sort("yyyymm"))
    s = el.filter(c("yyyymm") >= SAMPLE_START).with_columns(decade=c("yyyymm") // 1000 * 10)
    if s.height:
        stats["coverage"].append(s.group_by("decade").agg(
            pl.len().alias("__rows"), c("me").sum().alias("__me"),
            *[c(n).is_not_null().sum().alias(n) for n in names],
            *[pl.when(c(n).is_not_null()).then(c("me")).sum().alias(f"{n}__me") for n in names]).sort("decade"))
    stats["rows"] += raw.height
    stats["eligible_rows"] += el.height


def stored(path: Path, lo: int, hi: int) -> pl.DataFrame:
    return pl.scan_parquet(path).filter(pl.col("yyyymm").is_between(lo, hi)).collect()


def checks(panel: pl.DataFrame, acc: pl.DataFrame, a_names: list[str], b_names: list[str], tmp_panel: Path,
           tmp_ranks: Path, report: dict) -> None:
    c = pl.col
    names = a_names + b_names
    keys = pl.scan_parquet(tmp_panel).select(KEYS).collect()
    check(keys.equals(panel.sort("yyyymm", "permno").select(KEYS)), "The output keys are not the panel keys")
    rkeys = pl.scan_parquet(tmp_ranks).select(KEYS).collect()
    check(rkeys.equals(panel.filter(c("eligible")).sort("yyyymm", "permno").select(KEYS)),
          "The keys of the ranks are not the eligible rows of the panel")
    del keys, rkeys

    # Acceptance cases, read back from the file that will be published.
    def cell(permno: int, ym: int, name: str) -> list:
        return (pl.scan_parquet(tmp_panel).filter((c("permno") == permno) & (c("yyyymm") == ym))
                .select(name).collect()[name].to_list())

    seen = {}
    for permno, ym, name, expected in ACCEPTANCE:
        got = cell(permno, ym, name)
        seen[f"{permno}_{ym}_{name}"] = got
        check(len(got) == 1 and got[0] is not None and abs(got[0] - expected) < 1e-8 * max(1.0, abs(expected)),
              f"Acceptance case {permno} {ym} {name} failed: {got}, expected {expected}")
    for permno, ym, name in ACCEPTANCE_MISSING:
        got = cell(permno, ym, name)
        seen[f"{permno}_{ym}_{name}"] = got
        check(got == [None], f"Acceptance case {permno} {ym} {name} should be missing: {got}")
    for permno, ym, name in ACCEPTANCE_PRESENT:
        got = cell(permno, ym, name)
        seen[f"{permno}_{ym}_{name}_is_known"] = got
        check(len(got) == 1 and got[0] is not None, f"Case {permno} {ym} {name} should be known: {got}")
    # Dating of the join. Fiscal year 1999 of GVKEY 006066 is usable from
    # 2000-06 to 2001-05: the month before and the month after carry other accounts.
    for ym in (200005, 200106):
        got = cell(12490, ym, "at_gr1")
        seen[f"12490_{ym}_at_gr1"] = got
        check(len(got) == 1 and got[0] is not None and abs(got[0] - 0.0162020906) > 1e-6,
              f"The accounts of fiscal year 1999 are attached in {ym}")
    # Negative tests: a momentum window or a market value of another month would
    # not give the acceptance values.
    got = cell(12490, 200011, "ret_12_1")
    check(len(got) == 1 and got[0] is not None and abs(got[0] - (-0.1292730033)) > 1e-6,
          "The acceptance case does not date the momentum window")
    me_fy = panel.filter((c("permno") == 12490) & (c("yyyymm") == 199912))["me_company"][0]
    be = acc.filter((c("gvkey") == "006066") & (c("datadate") == date(1999, 12, 31)))["be_x"][0]
    check(be is not None and me_fy is not None and abs(be / me_fy - 0.1449682576) > 1e-6, "be_me cannot be told from book equity over the fiscal-year-end value")
    # Currency hole (GVKEY 008644): the growth of assets at 1995-12 stays missing
    # on every stock-month that carries these accounts.
    hole = panel.filter((c("gvkey") == "008644") & (c("acc_datadate") == date(1995, 12, 31))).select("permno", "yyyymm")
    if hole.height:
        vals = (pl.scan_parquet(tmp_panel).filter(c("permno").is_in(hole["permno"].unique().sort().to_list()))
                .select("permno", "yyyymm", "at_gr1").collect().join(hole, on=["permno", "yyyymm"]))
        check(vals.height == hole.height and vals["at_gr1"].null_count() == vals.height,
              "Growth across a missing fiscal year is not missing in the panel")
    seen["008644_199512_at_gr1_stock_months_all_missing"] = hole.height
    report["acceptance_cases"] = seen

    # A 5-month accounting lag must be caught by check_formation.
    row = panel.filter((c("permno") == 12490) & (c("yyyymm") == 200012))
    wrong = row.with_columns(acc_datadate=pl.lit(date(2000, 7, 31)), acc_age_months=pl.lit(5, dtype=pl.Int32))
    try:
        check_formation(wrong)
        caught = False
    except CheckError:
        caught = True
    check(caught, "A 5-month accounting lag is not caught")

    # Tests at three dates.
    tests = {}
    empty_acc = acc.clear()
    for T in TEST_DATES:
        # (0) Sources that end at T (test asked by the audit of Astra). The
        # production path runs on the block that holds T with: the panel up to
        # T, a reader of signals_price for which later months do not exist, and
        # the accounts closed at T - 6 months at the latest. Keys, values, ranks
        # and flags up to T must be those of the file.
        b_lo = next(a for a, b in blocks(panel) if a <= T <= b)
        nxt = T + 1 if T % 100 < 12 else (T // 100 + 1) * 100 + 1
        reader = PriceReader(limit=T)
        raw, rk = produce_block(panel.filter(c("yyyymm") <= T),
                                acc.filter(mi_date("datadate") <= mi_ym(T) - ACC_AGE_MIN),
                                b_lo, T, a_names, b_names, reader)
        ref = stored(tmp_panel, b_lo, T)
        bounded = (raw.select(ref.columns).equals(ref)
                   and store_ranks(rk, names).equals(stored(tmp_ranks, b_lo, T)))
        check(bounded, f"Signals of {b_lo}-{T} change when the sources end at {T}")
        del raw, rk, ref
        # Witness: the bounded reader refuses month T + 1.
        try:
            reader.rows(T, nxt)
            refused = False
        except CheckError:
            refused = True
        check(refused, "The bounded reader gives a month after its limit")
        # Witness: market characteristics moved one month back (the values of
        # T + 1 put at T) must change month T.
        at_t = panel.filter(c("yyyymm") == T)
        later = PriceReader().rows(nxt, nxt).drop("yyyymm", "eom")
        shifted = at_t.select(KEYS).join(later, on="permno", how="left").sort("yyyymm", "permno")
        moved_a = build_block(at_t, shifted, acc, a_names, b_names).select(*KEYS, *a_names)
        check(not moved_a.equals(stored(tmp_panel, T, T).select(*KEYS, *a_names)),
              "A one-month shift of the market characteristics is not detected")
        del at_t, later, shifted, moved_a

        # Tests on the twelve months to T.
        lo = T // 100 * 100 + 1 if T % 100 == 12 else (T // 100 - 1) * 100 + T % 100 + 1
        part = panel.filter(c("yyyymm").is_between(lo, T))
        price = pl.scan_parquet(PRICE).filter(c("yyyymm") <= T).filter(c("yyyymm") >= lo).collect()
        ref = stored(tmp_panel, lo, T)
        ref_r = stored(tmp_ranks, lo, T)

        # (1) The 6-month rule: every fiscal year that ended less than 6 months
        # before T is hidden. The bound is exact for month T; for the earlier
        # months of the window, check_formation is the test.
        cut = build_block(part, price, acc.filter(mi_date("datadate") <= mi_ym(T) - ACC_AGE_MIN), a_names, b_names)
        same = cut.select(ref.columns).equals(ref)
        same_r = store_ranks(rank_block(cut.filter(c("eligible")), names), names).equals(ref_r)
        check(same and same_r, f"Signals up to {T} change when the accounts closed less than 6 months before are hidden")
        # The test must be able to fail: hiding one more month of accounts changes the rows.
        cut7 = build_block(part, price, acc.filter(mi_date("datadate") <= mi_ym(T) - ACC_AGE_MIN - 1), a_names,
                           b_names, strict=False)
        check(not cut7.select(ref.columns).equals(ref), "The truncation test cannot detect hidden accounts")

        # (2) Version A does not depend on the accounts: no account and no link.
        bare = build_block(part.with_columns(gvkey=pl.lit(None, dtype=pl.String),
                                             acc_datadate=pl.lit(None, dtype=pl.Date),
                                             acc_age_months=pl.lit(None, dtype=pl.Int32)),
                           price, empty_acc, a_names, b_names)
        a_flags = [f"{n}_miss" for n in a_names]
        bare_r = store_ranks(rank_block(bare.filter(c("eligible")), names), names)
        same_a = (bare.select(*KEYS, *a_names).equals(ref.select(*KEYS, *a_names))
                  and bare_r.select(*KEYS, *a_names, *a_flags).equals(ref_r.select(*KEYS, *a_names, *a_flags)))
        check(same_a, f"Version A changes at {T} when the accounts and links are removed")
        check(bare.select([c(n).null_count() for n in b_names]).row(0) == (bare.height,) * len(b_names),
              "An accounting characteristic exists without accounts")

        # (3) Ranks do not depend on the stocks that are not eligible.
        full = ref.join(part.select("permno", "yyyymm", "eligible"), on=["permno", "yyyymm"],
                        validate="1:1").sort("yyyymm", "permno")
        check(full.height == ref.height, "A row of the file is not in the panel")
        moved = full.with_columns([pl.when(c("eligible")).then(c(n)).otherwise(c(n).fill_null(1.0) * -7.0 + 3.0)
                                   .alias(n) for n in names])
        same_e = store_ranks(rank_block(moved.filter(c("eligible")), names), names).equals(ref_r)
        check(same_e, f"Ranks at {T} change when stocks that are not eligible change")
        # The test must be able to fail: the same change on eligible stocks moves the ranks.
        moved2 = full.with_columns([(c(n).fill_null(1.0) * -7.0 + 3.0).alias(n) for n in names])
        check(not store_ranks(rank_block(moved2.filter(c("eligible")), names), names).equals(ref_r),
              "The eligibility test cannot detect a change")

        # (4) Second route for the ranks of month T: numpy and scipy.
        el = full.filter(c("eligible") & (c("yyyymm") == T)).sort("permno")
        rr = ref_r.filter(c("yyyymm") == T).sort("permno")
        gap = 0.0
        for n in names:
            x = el[n].to_numpy().astype(float)
            ok = np.isfinite(x)
            s = np.zeros(len(x))
            if ok.sum() >= 2:
                s[ok] = 2 * (rankdata(x[ok], method="average") - 1) / (ok.sum() - 1) - 1
            gap = max(gap, float(np.abs(s - rr[n].to_numpy()).max()))
            check(bool(((~ok).astype(np.int8) == rr[f"{n}_miss"].to_numpy()).all()), f"Second route, flags of {n} at {T}")
        check(gap < 1e-6, f"Second route for the ranks at {T}: largest gap {gap}")
        tests[str(T)] = {"identical_when_all_sources_end_at_T": bounded, "months_of_that_test": f"{b_lo}-{T}",
                         "reader_refuses_the_next_month": refused, "months": f"{lo}-{T}", "rows": ref.height, "eligible_rows": ref_r.height,
                         "identical_when_accounts_closed_less_than_6_months_before_are_hidden": same and same_r, "version_a_identical_without_accounts": same_a,
                         "ranks_identical_when_ineligible_change": same_e, "second_route_largest_gap": gap}
        del part, price, ref, ref_r, cut, cut7, bare, bare_r, full, moved, moved2
    report["tests_at_three_dates"] = tests


def main() -> None:
    report: dict = {"script": "scripts/signals/3_signal_panel.py", "inputs": {}}
    check_inputs_allowed()
    check_rank_rule()
    a_names, b_names = signal_names()
    names = a_names + b_names
    report["inputs"][SIGNAL_LIST.name] = sha256(SIGNAL_LIST)
    panel = read_checked(PANEL, PANEL_REPORT, PANEL_COLS, report)
    acc, acc_run = read_verified(ACC, ACC_REPORT)
    report["inputs"][ACC.name] = {
        "sha256": json.loads(ACC_REPORT.read_text(encoding="utf-8"))["outputs"][ACC.name], "from_run": acc_run}
    report["inputs"][DICTIONARY.name] = sha256(DICTIONARY)
    report["script_sha256"] = sha256(Path(__file__))
    price_report = json.loads(PRICE_REPORT.read_text(encoding="utf-8"))
    price_stamps = file_stamps([PRICE])
    check(sha256(PRICE) == price_report["outputs"][PRICE.name], f"{PRICE.name} does not match its report")
    report["inputs"][PRICE.name] = {"sha256": price_report["outputs"][PRICE.name], "from_run": price_report["run_id"]}

    # The columns are exactly the names of the signal list.
    price_cols = [x for x in pl.read_parquet_schema(PRICE) if x not in KEYS]
    check(sorted(price_cols) == sorted(a_names), "signals_price does not hold exactly the version A names")
    acc_b = [n for n in b_names if n not in MARKET_SCALED]
    check(set(MARKET_SCALED) <= set(b_names) and len(MARKET_SCALED) == 23, "The 23 market-scaled names are not in the list")
    check(set(acc_b) <= set(acc.columns) and not set(MARKET_SCALED) & set(acc.columns),
          f"signals_acc lacks {sorted(set(acc_b) - set(acc.columns))}")
    check(set(ITEMS) <= set(acc.columns), "signals_acc lacks an item needed for the market-scaled ratios")
    check(len(names) == len(set(names)) == 194, f"{len(names)} names instead of 194")
    check(acc.select("gvkey", "datadate").is_unique().all(), "Duplicate fiscal year in signals_acc")
    check_formation(panel)

    run_id = uuid.uuid4().hex[:12]
    w_panel, w_ranks = BlockWriter(OUT_PANEL, run_id), BlockWriter(OUT_RANKS, run_id)
    stats: dict = {"rows": 0, "eligible_rows": 0, "coverage": [], "distinct": []}
    try:
        for lo, hi in blocks(panel):
            raw, ranks = produce_block(panel, acc, lo, hi, a_names, b_names, PriceReader())
            block_stats(raw, ranks, names, stats)
            w_panel.write(raw.drop("eligible", "me"))
            w_ranks.write(store_ranks(ranks, names))
            print(f"  {lo}-{hi}: {raw.height:,} rows, {ranks.height:,} eligible", flush=True)
            del raw, ranks
        w_panel.close()
        w_ranks.close()
        check(stats["rows"] == panel.height, "Rows written differ from the panel")
        checks(panel, acc, a_names, b_names, w_panel.tmp, w_ranks.tmp, report)
        check_unchanged(price_stamps)

        c = pl.col
        el = panel.filter(c("eligible"))
        report["rows"] = {"signal_panel": stats["rows"], "signal_ranks": stats["eligible_rows"]}
        report["characteristics"] = {"version_a": len(a_names), "version_b_added": len(b_names),
                                     "market_scaled": len(MARKET_SCALED)}
        report["company_market_value"] = {
            "eligible_rows_incomplete": el.filter(~c("me_company_complete")).height,
            "of_which_with_accounts": el.filter(~c("me_company_complete") & c("acc_datadate").is_not_null()).height,
            "eligible_rows_with_accounts": el.filter(c("acc_datadate").is_not_null()).height,
            "eligible_rows_without_link": el.filter(c("gvkey").is_null()).height,
            "eligible_rows_with_accounts_in_a_crsp_company_with_several_gvkey_d26": panel.with_columns(
                n=c("gvkey").drop_nulls().n_unique().over("permco", "yyyymm")).filter(
                c("eligible") & (c("n") > 1) & c("acc_datadate").is_not_null()).height,
            "company_months_with_accounts_on_several_stocks": panel.filter(c("acc_datadate").is_not_null())
            .group_by("gvkey", "yyyymm").len().filter(c("len") > 1).height}
        cov = pl.concat(stats["coverage"]).group_by("decade").sum().sort("decade")
        tot = cov.drop("decade").sum()
        report["coverage_eligible_from_1963"] = {"rows": tot["__rows"][0], **{
            n: {"n": round(tot[n][0] / tot["__rows"][0], 4), "me": round(tot[f"{n}__me"][0] / tot["__me"][0], 4)}
            for n in names}}
        report["coverage_by_decade_count"] = {
            str(r["decade"]): {n: round(r[n] / r["__rows"], 3) for n in names} for r in cov.to_dicts()}
        dist = pl.concat(stats["distinct"]).filter(c("yyyymm") >= SAMPLE_START)
        report["distinct_values_by_month_from_1963"] = {
            n: {"min": int(dist[n].min()), "median": float(dist[n].median())} for n in names}
        report["declared"] = {
            "rank_universe": "all eligible stocks of the month, not inside industries (decision of 2026-11-13)",
            "sort_order": "yyyymm, permno", "rank_dtype": "Float32", "signal_ranks_rows": "eligible only"}

        # Publish as utils.publish does: hashes, final names, the report last.
        report["run_id"] = run_id
        report["outputs"] = {w.path.name: sha256(w.tmp) for w in (w_panel, w_ranks)}
        for w in (w_panel, w_ranks):
            w.tmp.replace(w.path)
        report["created_at_utc"] = datetime.now(timezone.utc).isoformat()
        tmp = OUT_REPORT.with_name(f"{OUT_REPORT.name}.{run_id}.tmp")
        tmp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(OUT_REPORT)
    finally:
        # After a failed check no temporary file is left. As in utils.publish, the
        # two renames are not one atomic step: if the second fails, the files no
        # longer match the report, which read_verified detects downstream.
        for w in (w_panel, w_ranks):
            w.close()
            w.tmp.unlink(missing_ok=True)

    low = sorted(names, key=lambda n: report["coverage_eligible_from_1963"][n]["n"])[:3]
    print(f"signal_panel: {stats['rows']:,} stock-months, {len(names)} characteristics "
          f"({len(a_names)} A, {len(b_names)} B, of which {len(MARKET_SCALED)} market-scaled).")
    print(f"signal_ranks: {stats['eligible_rows']:,} eligible stock-months, ranks and flags.")
    print("Lowest coverage (eligible, from 1963): "
          + ", ".join(f"{n} {report['coverage_eligible_from_1963'][n]['n']:.1%}" for n in low))
    print(f"Run {run_id}. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
