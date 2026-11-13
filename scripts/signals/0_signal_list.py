"""
Signal list: every JKP characteristic that our data can compute.

Description:
    A register of the 404 characteristics of the JKP library (Jensen, Kelly and
    Pedersen, 2023; code at commit b5695ea). Each one is either kept, with its
    inputs, or excluded, with the reason. A characteristic is kept when its JKP
    formula (annual US branch) can be computed from the admitted tables:
    crsp_panel_acc, compustat_annual, crsp_daily_agg, and the market and
    risk-free columns of ff_factors_monthly.

Steps:
    1) Read the JKP list (characteristics.csv) and its themes (themes.csv).
    2) Read the exclusions (resources/signal_exclusions.csv): "data" = an input
       is not in our data; "scope" = computable from other files, but outside
       the admitted tables (reduced step 9, decision D11).
    3) Check that kept and excluded names are disjoint and cover the 404.
    4) Check that every input column exists in the admitted tables.
    5) Version A = no accounting input; version B = at least one.
    6) Branch label of the accounting characteristics: "leaves_present" (every
       item of every JKP branch is in our extract), "first_choice" (the first
       choice of each JKP chain is in our extract, some fallback is not),
       "definitional_fallback" (the JKP first choice gp, xopr or ebitda is not
       in our extract; the Compustat definition is used).
    7) Write resources/signal_list.csv and print the counts.

Output:
    resources/signal_list.csv (characteristic, theme, version, branch, table,
    inputs, jkp_function).

Run from Project/:  python scripts/signals/0_signal_list.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
JKP = ROOT.parent / "Resources/reference_code/jkp-data/src/jkp/data/resources"
PROCESSED = ROOT / "data/processed"
OUT = ROOT / "resources/signal_list.csv"
EXCLUSIONS = ROOT / "resources/signal_exclusions.csv"

# Raw inputs of the JKP helper variables (add_helper_vars), in our column names.
# Only helpers whose JKP first choice, or a fallback that is a Compustat
# identity, is available. Helpers that need an item we do not have (dp, xrd,
# ivao, ivst, intan, invt, rect, ppent, ppegt, ap, txp, oancf, dv, sstk, prstkc,
# icapt, mib, pi, txt, spi, xido, emp, re) are absent on purpose.
H = {
    "at_x": ["at"],
    "sale_x": ["sale"],
    "be_x": ["be_x"],
    "pstk_x": ["pstk_x"],
    "debt_x": ["dltt", "dlc"],
    "netdebt_x": ["dltt", "dlc", "che"],
    "gp_x": ["sale", "cogs"],
    "opex_x": ["cogs", "xsga"],
    "ebitda_x": ["oibdp", "sale", "cogs", "xsga"],
    "ope_x": ["oibdp", "sale", "cogs", "xsga", "xint"],
    "ni_x": ["ib"],
    "nix_x": ["ni"],
    "fi_x": ["ni", "xint"],
    "ca_x": ["act"],
    "cl_x": ["lct"],
    "nca_x": ["at", "act"],
    "ncl_x": ["lt", "lct"],
    "coa_x": ["act", "che"],
    "col_x": ["lct", "dlc"],
    "cowc_x": ["act", "che", "lct", "dlc"],
    "ncol_x": ["lt", "lct", "dltt"],
    "ol_x": ["lt", "lct", "dltt", "dlc"],
    "nwc_x": ["act", "lct"],
    "fnl_x": ["dltt", "dlc", "pstk_x"],
    "me": ["me_company"],
    "mev": ["me_company", "dltt", "dlc", "che"],
}


def acc(function: str, *helpers_or_raw: str) -> tuple[str, list[str], str]:
    cols: list[str] = []
    for h in helpers_or_raw:
        cols += H.get(h, [h])
    return ("compustat_annual", sorted(set(cols)), function)


def panel(function: str, *cols: str) -> tuple[str, list[str], str]:
    return ("crsp_panel_acc", list(cols), function)


def daily(*cols: str) -> tuple[str, list[str], str]:
    return ("crsp_daily_agg", list(cols), "roll_apply_daily / bidask_hl (step 9)")


S: dict[str, tuple[str, list[str], str]] = {}

# ---- Price and trading signals (version A) -------------------------------
MOM = [(0, 1), (0, 2), (0, 3), (1, 3), (0, 6), (1, 6), (0, 9), (1, 9), (0, 12), (1, 12),
       (7, 12), (1, 18), (1, 24), (12, 24), (1, 36), (12, 36), (12, 48), (1, 48), (1, 60),
       (12, 60), (36, 60)]
for i, j in MOM:
    S[f"ret_{j}_{i}"] = panel("mom_rev_cols", "ret", "ret_signal_ok")
for a, b in [(1, 1), (2, 5), (6, 10), (11, 15), (16, 20)]:
    S[f"seas_{a}_{b}an"] = panel("seasonality", "ret", "ret_signal_ok")
    S[f"seas_{a}_{b}na"] = panel("seasonality", "ret", "ret_signal_ok")
for lag in [1, 3, 6, 12]:
    S[f"eqnpo_{lag}m"] = panel("eqnpo_cols", "ret", "ret_signal_ok", "me")
S["market_equity"] = panel("market_chars_monthly", "me")
S["prc"] = panel("gen_crsp_sf", "prc")
for c in ["rvol_21d", "rvol_252d", "beta_252d", "dolvol_126d", "bidaskhl_21d"]:
    S[c] = daily(c)
# 60 monthly returns against the market (at least 36). Market and risk-free
# from Ken French, as at step 9 (JKP builds its own market).
for c in ["beta_60m", "ivol_capm_60m"]:
    S[c] = ("crsp_panel_acc+ff_factors_monthly", ["ret", "ret_exc", "ret_signal_ok", "mkt_excess"],
            "prep_data_factor_regs / capm / market_beta")

# Daily characteristics added to step 9 on 2026-11-12 (decision of the project
# owner): extreme returns, high-low volatility, dollar-volume liquidity, price
# to the 12-month high, share changes and dividend yields.
for c in ["rmax1_21d", "rmax5_21d", "rvolhl_21d", "ami_126d", "dolvol_var_126d",
          "prc_highprc_252d"]:
    S[c] = daily(c)
S["rmax5_rvol_21d"] = ("crsp_daily_agg", ["rmax5_21d", "rvol_252d"], "finish_daily_chars")
# Share changes and dividend yields: monthly formulas that need the cumulative
# share factor, taken from the daily file on the date of the monthly row.
for lag in [1, 3, 6, 12]:
    S[f"chcsho_{lag}m"] = ("crsp_panel_acc+crsp_daily_agg", ["shrout", "cfacshr_mth"],
                           "chcsho_cols")
    S[f"div{lag}m_me"] = ("crsp_panel_acc+crsp_daily_agg",
                          ["ret", "retx", "ret_signal_ok", "prc", "shrout", "me", "cfacshr_mth"],
                          "prepare_crsp_sf (div_tot) / div_cols")

# ---- Accounting signals (version B) --------------------------------------
# Levels (Size theme)
S["assets"] = acc("create_acc_chars", "at_x")
S["sales"] = acc("create_acc_chars", "sale_x")
S["book_equity"] = acc("create_acc_chars", "be_x")
S["net_income"] = acc("create_acc_chars", "ni_x")
S["enterprise_value"] = acc("add_me_data_and_compute_me_mev_mat_eqdur_vars", "mev")

# Scaled by market equity and by market enterprise value
for name, h in [("at", "at_x"), ("be", "be_x"), ("sale", "sale_x"), ("gp", "gp_x"),
                ("ebitda", "ebitda_x"), ("ope", "ope_x"), ("ni", "ni_x"), ("nix", "nix_x"),
                ("debt", "debt_x"), ("netdebt", "netdebt_x"), ("cash", "che")]:
    S[f"{name}_me"] = acc("scale_me", h, "me")
for name, h in [("at", "at_x"), ("be", "be_x"), ("sale", "sale_x"), ("gp", "gp_x"),
                ("ebitda", "ebitda_x"), ("debt", "debt_x"), ("pstk", "pstk_x"),
                ("debtlt", "dltt"), ("debtst", "dlc"), ("cash", "che")]:
    S[f"{name}_mev"] = acc("scale_mev", h, "mev")

# Growth over 1 and 3 years (var_growth) and 2 years for capx
for name, h in [("at", "at_x"), ("ca", "ca_x"), ("nca", "nca_x"), ("lt", "lt"), ("cl", "cl_x"),
                ("ncl", "ncl_x"), ("be", "be_x"), ("pstk", "pstk_x"), ("debt", "debt_x"),
                ("sale", "sale_x"), ("cogs", "cogs"), ("sga", "xsga"), ("opex", "opex_x"),
                ("capx", "capx")]:
    for y in (1, 3):
        S[f"{name}_gr{y}"] = acc("var_growth", h)
S["capx_gr2"] = acc("var_growth", "capx")

# Change over 1 and 3 years scaled by assets (chg_to_assets)
for name, h in [("cash", "che"), ("debtst", "dlc"), ("debtlt", "dltt"), ("txditc", "txditc"),
                ("coa", "coa_x"), ("col", "col_x"), ("cowc", "cowc_x"), ("ncol", "ncol_x"),
                ("ol", "ol_x"), ("fnl", "fnl_x"), ("gp", "gp_x"), ("ebitda", "ebitda_x"),
                ("ope", "ope_x"), ("ni", "ni_x"), ("nix", "nix_x"), ("nwc", "nwc_x"),
                ("capx", "capx")]:
    for y in (1, 3):
        S[f"{name}_gr{y}a"] = acc("chg_to_assets", h, "at_x")
S["be_gr1a"] = acc("chg_to_assets", "be_x", "at_x")

# Ratios (add_accounting_misc_cols_1, financial_soundness_and_misc_ratios_exps,
# add_liq_and_efficiency_ratios, add_profit_scaled_by_lagged_vars)
RATIOS = {
    "capx_at": ("capx", "at_x"), "gp_sale": ("gp_x", "sale_x"),
    "ebitda_sale": ("ebitda_x", "sale_x"), "ni_sale": ("ni_x", "sale_x"),
    "nix_sale": ("ni", "sale_x"), "gp_at": ("gp_x", "at_x"), "ebitda_at": ("ebitda_x", "at_x"),
    "fi_at": ("fi_x", "at_x"), "ni_at": ("ni_x", "at_x"), "ope_be": ("ope_x", "be_x"),
    "ni_be": ("ni_x", "be_x"), "nix_be": ("nix_x", "be_x"), "debt_at": ("debt_x", "at_x"),
    "debt_be": ("debt_x", "be_x"), "int_debt": ("xint", "debt_x"),
    "ebitda_debt": ("ebitda_x", "debt_x"), "debtst_debt": ("dlc", "debt_x"),
    "debtlt_debt": ("dltt", "debt_x"), "int_debtlt": ("xint", "dltt"),
    "profit_cl": ("ebitda_x", "cl_x"), "cash_lt": ("che", "lt"), "cl_lt": ("cl_x", "lt"),
    "opex_at": ("opex_x", "at_x"), "nwc_at": ("nwc_x", "at_x"), "debtlt_be": ("dltt", "be_x"),
    "sale_be": ("sale_x", "be_x"), "sale_nwc": ("sale_x", "nwc_x"), "cash_at": ("che", "at_x"),
    "cash_cl": ("che", "cl_x"), "ca_cl": ("ca_x", "cl_x"), "at_be": ("at_x", "be_x"),
    "at_turnover": ("sale_x", "at_x"), "gp_atl1": ("gp_x", "at_x"), "ope_bel1": ("ope_x", "be_x"),
}
for name, (num, den) in RATIOS.items():
    S[name] = acc("safe_div / temp_rat_other", num, den)

# Other accounting signals
S["capex_abn"] = acc("compute_capex_abn", "capx", "sale_x")
S["dgp_dsale"] = acc("chg_to_exp", "gp_x", "sale_x")
S["dsale_dsga"] = acc("chg_to_exp", "sale_x", "xsga")
S["gpoa_ch5"] = acc("chg_var1_to_var2", "gp_x", "at_x")
S["roe_ch5"] = acc("chg_var1_to_var2", "ni_x", "be_x")
S["roa_ch5"] = acc("chg_var1_to_var2", "ni_x", "at_x")
S["gmar_ch5"] = acc("chg_var1_to_var2", "gp_x", "sale_x")
S["roe_be_std"] = acc("vola", "ni_x", "be_x")
S["ni_ar1"] = acc("earnings persistence", "ni_x", "at_x")
S["ni_ivol"] = acc("earnings persistence", "ni_x", "at_x")
S["eq_dur"] = acc("equity_duration_cd", "ni_x", "be_x", "sale_x", "me")

# Branch labels (audit of 2026-11-12, annex B1).
FALLBACK = set("""gp_me gp_mev gp_sale gp_at gp_atl1 gp_gr1a gp_gr3a dgp_dsale gpoa_ch5 gmar_ch5
opex_gr1 opex_gr3 opex_at ebitda_me ebitda_mev ebitda_debt ebitda_at ebitda_sale ebitda_gr1a
ebitda_gr3a ope_me ope_be ope_bel1 ope_gr1a ope_gr3a profit_cl""".split())
LEAVES = set("""enterprise_value debt_me netdebt_me cash_me debt_mev pstk_mev debtlt_mev debtst_mev
cash_mev lt_gr1 lt_gr3 pstk_gr1 pstk_gr3 debt_gr1 debt_gr3 cogs_gr1 cogs_gr3 sga_gr1 sga_gr3
capx_gr1 capx_gr3 capx_gr2 int_debt debtst_debt debtlt_debt int_debtlt cash_lt""".split())


def main() -> None:
    jkp_all = {r["characteristic"] for r in csv.DictReader(open(JKP / "characteristics.csv", encoding="utf-8"))}
    themes = {r["characteristic"]: r["theme"]
              for r in csv.DictReader(open(JKP / "themes/themes.csv", encoding="utf-8"))}
    schema = {t: set(pq.read_schema(PROCESSED / f"{t}.parquet").names)
              for t in ("crsp_panel_acc", "compustat_annual", "crsp_daily_agg", "ff_factors_monthly")}
    schema["compustat_annual"] |= {"me_company"}  # joined from the panel at the public date
    # Only the market and risk-free columns of the factor table are admitted.
    schema["ff_factors_monthly"] &= {"mkt_excess", "risk_free"}

    def columns_of(table: str) -> set[str]:
        return set().union(*(schema[t] for t in table.split("+")))

    excluded = {r["characteristic"]: r for r in csv.DictReader(open(EXCLUSIONS, encoding="utf-8"))}

    errors = []
    rows = []
    both = sorted(set(S) & set(excluded))
    if both:
        errors.append(f"kept and excluded at the same time: {both}")
    undecided = sorted(jkp_all - set(S) - set(excluded))
    if undecided:
        errors.append(f"JKP characteristics without a decision: {undecided}")
    unknown = sorted(set(excluded) - jkp_all)
    if unknown:
        errors.append(f"excluded names that are not JKP characteristics: {unknown}")
    for r in excluded.values():
        if r["exclusion_type"] not in ("data", "scope") or not r["reason"]:
            errors.append(f"{r['characteristic']}: exclusion without a valid type or reason")
    if not (FALLBACK | LEAVES) <= set(S):
        errors.append(f"branch labels on unknown names: {sorted((FALLBACK | LEAVES) - set(S))}")
    for name, (table, cols, function) in sorted(S.items()):
        if name not in jkp_all:
            errors.append(f"{name}: not a JKP characteristic")
        if name not in themes:
            errors.append(f"{name}: no JKP theme")
        missing = [c for c in cols if c not in columns_of(table)]
        if missing:
            errors.append(f"{name}: inputs missing from {table}: {missing}")
        version = "B" if table == "compustat_annual" else "A"
        if version == "A":
            branch = "market"
        elif name in FALLBACK:
            branch = "definitional_fallback"
        elif name in LEAVES:
            branch = "leaves_present"
        else:
            branch = "first_choice"
        rows.append([name, themes.get(name, ""), version, branch, table, ";".join(cols), function])
    if errors:
        sys.exit("SIGNAL LIST REJECTED:\n" + "\n".join(errors))

    tmp = OUT.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["characteristic", "theme", "version", "branch", "table", "inputs", "jkp_function"])
        w.writerows(sorted(rows, key=lambda r: (r[2], r[1], r[0])))
    tmp.replace(OUT)

    counts: dict[tuple[str, str], int] = {}
    for r in rows:
        counts[(r[2], r[1])] = counts.get((r[2], r[1]), 0) + 1
    n_theme_all: dict[str, int] = {}
    for name in jkp_all:
        t = themes.get(name, "(no theme)")
        n_theme_all[t] = n_theme_all.get(t, 0) + 1
    n_data = sum(1 for r in excluded.values() if r["exclusion_type"] == "data")
    n_scope = sum(1 for r in excluded.values() if r["exclusion_type"] == "scope")
    print(f"JKP characteristics: {len(jkp_all)} = {len(rows)} kept + {n_data} excluded (data) "
          f"+ {n_scope} excluded (scope)")
    for v in ("A", "B"):
        print(f"version {v}: {sum(n for (vv, _), n in counts.items() if vv == v)}")
    for b in ("market", "leaves_present", "first_choice", "definitional_fallback"):
        print(f"  branch {b}: {sum(1 for r in rows if r[3] == b)}")
    for t in sorted(n_theme_all):
        a = counts.get(("A", t), 0)
        b = counts.get(("B", t), 0)
        print(f"  {t:24s} A {a:3d}  B {b:3d}  of {n_theme_all[t]:3d} in JKP")


if __name__ == "__main__":
    main()
