"""Signals: extend resources/data_dictionary.csv to the four signal tables.

The rows of signals_price, signals_acc, signal_panel and signal_ranks are
generated from resources/signal_list.csv and from the columns of the tables, so
that the dictionary cannot drift from the register of the 194 characteristics.
The rows of the other tables are kept byte for byte. The script can be run again:
it replaces the rows it wrote.

Availability and roles (codes of scripts/data_cleaning/check_data_dictionary.py):
- market characteristics (version A): known at the end of month t, predictor;
- accounting characteristics (version B): usable from 6 months after the fiscal
  year end (acc_6m); predictor in signal_panel and signal_ranks only. In
  signals_acc they are keyed by fiscal year end, with no availability date, and
  reach a stock-month only through acc_datadate of the panel: there, every
  column is a transform_input (after the audit of 2026-11-13);
- the 18 items that signals_acc passes to script 3: transform_input (never a
  predictor by themselves);
- ranks and missing flags: the availability of their characteristic, predictor.

Run from Project/:  python scripts/signals/signal_dictionary.py
then:               python scripts/data_cleaning/check_data_dictionary.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import PROCESSED, PROJECT, CheckError, check  # noqa: E402

DICTIONARY = PROJECT / "resources" / "data_dictionary.csv"
SIGNAL_LIST = PROJECT / "resources" / "signal_list.csv"
HEADER = ["table", "column", "meaning", "unit", "source", "availability", "roles"]
SIGNAL_TABLES = ["signals_price", "signals_acc", "signal_panel", "signal_ranks"]

KEY_ROWS = {
    "permno": ("CRSP security id", "id"), "yyyymm": ("Month t", "yyyymm"),
    "eom": ("Last calendar day of month t", "date"), "gvkey": ("Compustat firm key", "id"),
    "datadate": ("Fiscal year end", "date"),
}
# Items of signals_acc that only script 3 uses: name -> (meaning, unit).
ITEMS = {
    "at_x": ("Total assets", "USD millions"), "be_x": ("Book equity", "USD millions"),
    "sale_x": ("Sales", "USD millions"), "gp_x": ("Gross profit", "USD millions"),
    "ebitda_x": ("Operating income before depreciation", "USD millions"),
    "ope_x": ("Operating profit to equity holders", "USD millions"),
    "ni_x": ("Income before extraordinary items", "USD millions"), "nix_x": ("Net income", "USD millions"),
    "debt_x": ("Total debt", "USD millions"), "netdebt_x": ("Debt minus cash", "USD millions"),
    "che": ("Cash and short-term investments", "USD millions"), "pstk_x": ("Preferred stock", "USD millions"),
    "dltt": ("Long-term debt", "USD millions"), "dlc": ("Debt in current liabilities", "USD millions"),
    "ed_cd": ("Equity duration: discounted projected dividends", "USD millions"),
    "ed_cd_w": ("Equity duration: discounted projected dividends weighted by their year", "USD millions"),
    "ed_constant": ("Equity duration: weight of the terminal value", "number"),
    "ed_err": ("Equity duration: 1 if a projected book equity is negative", "0/1"),
}
# JKP functions of the 23 characteristics that script 3 scales by the market value.
MARKET_VALUE_FUNCTIONS = {"scale_me", "scale_mev", "equity_duration_cd",
                          "add_me_data_and_compute_me_mev_mat_eqdur_vars"}
ITEM_RULE = ("Item of the fiscal year, only an input of the market-scaled characteristics of "
             "3_signal_panel.py: never rank it, never use its level or its missing flag")


def main() -> None:
    sig = list(csv.DictReader(open(SIGNAL_LIST, encoding="utf-8")))
    info = {r["characteristic"]: r for r in sig}
    check(len(info) == len(sig) == 194, f"{len(sig)} rows in the signal list instead of 194")

    def characteristic(table: str, name: str, source: str, what: str, unit: str) -> list[str]:
        r = info[name]
        meaning = f"{what} of the JKP characteristic {name} (theme: {r['theme']}; JKP {r['jkp_function']})"
        if r["version"] == "B" and table != "signals_acc":
            meaning += "; accounts attached through acc_datadate of the panel"
        if r["version"] == "B" and table == "signals_acc":
            meaning += "; never joined on the month of datadate, only through acc_datadate of the panel"
        if r["jkp_function"] in MARKET_VALUE_FUNCTIONS and r["version"] == "B":
            meaning += ("; also uses the company market value of month t (me_company, only if complete and "
                        "if the CRSP company is linked to one Compustat company that month)")
        return [table, name, meaning, unit, source, "t" if r["version"] == "A" else "acc_6m",
                "transform_input" if table == "signals_acc" else "predictor"]

    rows = []
    for table, source in zip(SIGNAL_TABLES, ["signals 1", "signals 2", "signals 3", "signals 3"]):
        for col in pl.read_parquet_schema(PROCESSED / f"{table}.parquet"):
            if col in KEY_ROWS:
                rows.append([table, col, KEY_ROWS[col][0], KEY_ROWS[col][1], source, "key", "identifier"])
            elif table == "signals_acc" and col in ITEMS:
                rows.append([table, col, f"{ITEMS[col][0]}. {ITEM_RULE}", ITEMS[col][1], source, "acc_6m",
                             "transform_input"])
            elif table == "signal_ranks" and col in info:
                rows.append(characteristic(table, col, source, "Rank by month over the eligible stocks (0 if "
                                           "missing)", "rank in [-1, 1]"))
            elif table == "signal_ranks" and col.endswith("_miss") and col[:-5] in info:
                rows.append(characteristic(table, col[:-5], source, "Missing flag", "0/1"))
                rows[-1][1] = col
            elif col in info:
                rows.append(characteristic(table, col, source, "Raw value", "number"))
            else:
                raise CheckError(f"{table}.{col} is neither a key, an item nor a characteristic of the list")
    # Every characteristic of the list is in the panel and in the ranks.
    for table in ("signal_panel", "signal_ranks"):
        have = {r[1] for r in rows if r[0] == table}
        check(set(info) <= have, f"{table} lacks {sorted(set(info) - have)}")

    # Keep the rows of the other tables as they are; the signal rows are at the end.
    text = DICTIONARY.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)
    check(lines[0] == ",".join(HEADER) and lines[-1] == "", "Unexpected dictionary header or ending")
    is_signal = [any(line.startswith(f"{t},") for t in SIGNAL_TABLES) for line in lines[1:-1]]
    kept = is_signal.index(True) if True in is_signal else len(is_signal)
    check(all(is_signal[kept:]), "A row of another table comes after the signal rows")
    buf = io.StringIO()
    csv.writer(buf, lineterminator=eol).writerows(rows)
    new = eol.join(lines[:kept + 1]) + eol + buf.getvalue()
    tmp = DICTIONARY.with_name(DICTIONARY.name + ".tmp")
    tmp.write_bytes(new.encode("utf-8"))
    tmp.replace(DICTIONARY)
    print(f"data dictionary: {kept} rows kept, {len(rows)} rows written for {len(SIGNAL_TABLES)} signal tables.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
