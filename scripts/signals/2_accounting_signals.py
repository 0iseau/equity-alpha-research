"""Signals, script 2: the accounting characteristics that need no market value.

Reference code (Resources/reference_code/jkp-data, commit b5695ea, aux_functions.py):
    add_helper_vars      -> month grid per company, helper variables (*_x)
    var_growth           -> x / x(-h) - 1, lagged base positive, count > h
    chg_to_assets        -> (x - x(-h)) / current assets, assets positive, count > h
    safe_div             -> guarded divisions; each ratio uses the mode of the JKP code
    add_accounting_misc_cols_1, financial_soundness_and_misc_ratios_exps,
    add_liq_and_efficiency_ratios, add_profit_scaled_by_lagged_vars -> the ratios
    mean_year, temp_rat_other -> at_turnover
    compute_capex_abn, chg_to_exp, chg_var1_to_var2, vola -> see each function below
    compute_earnings_persistence -> ni_ar1, ni_ivol
    equity_duration_cd   -> the components of eq_dur (finished in script 3)

How the JKP formulas are applied to our extract (SignalSpec.md, section 2):
- Annual US accounts in USD only (steps 7 and 8). A fiscal year in another
  currency is not in the table: a change across it is missing.
- When JKP writes a chain of choices, we use the first choice that our extract
  has; an item that is absent from our extract is unknown, never zero:
    at_x = at, sale_x = sale, ca_x = act, cl_x = lct, ni_x = ib, nix_x = ni
    (their JKP fallbacks need items we do not have).
- Three JKP first choices are absent (gp, xopr, ebitda). The Compustat
  definitions are used: gp_x = sale - cogs, opex_x = cogs + xsga,
  ebitda_x = coalesce(oibdp, sale_x - opex_x, gp_x - xsga) (the rest of the JKP
  chain). The 26 characteristics concerned are labelled "definitional_fallback"
  in resources/signal_list.csv.
- An item that is in our extract but empty on a row follows the JKP code,
  including its SAS-style sum of the two debt items.
- be_x, seq_x and pstk_x are read from step 7.

Project rule, with no equivalent in JKP (decision D25, after the audits of
2026-11-12): a fiscal year that ends less than 12 months after the previous
report of the company is a transition year (change of fiscal year end; 1,100
reports, all with a new fiscal-year-end month). Its income-statement and
cash-flow items cover less than 12 months and are not annual flows: they are set
to missing (FLOW_ITEMS). Every characteristic built on them is then missing for
that year, and so is a growth that would compare with it. Balance-sheet items
are kept. The previous report is looked up in the raw file, in any currency, as
at step 8.

Inputs: data/processed/compustat_annual.parquet (hash checked against step 7)
        data/raw/ccm_fundamentals_annual.csv (dates of all reports; size checked
        against the raw manifest, hash recorded)
Outputs:
    signals_acc.parquet        one row per (gvkey, datadate): 112 characteristics,
                               and the items that script 3 scales by market value
    signals_acc_report.json    checks, coverage and hashes (written last)

Run from Project/:  python scripts/signals/2_accounting_signals.py
"""

from __future__ import annotations

import csv
import io
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_cleaning"))
from utils import (PROCESSED, PROJECT, RAW, CheckError, check, publish, read_raw_sized,  # noqa: E402
                   read_verified, sha256)

ACCOUNTS = PROCESSED / "compustat_annual.parquet"
ACCOUNTS_REPORT = PROCESSED / "compustat_annual_report.json"
SIGNAL_LIST = PROJECT / "resources" / "signal_list.csv"
FUNDA = RAW / "ccm_fundamentals_annual.csv"
# Items measured over the fiscal year (income statement and cash flow).
FLOW_ITEMS = ["capx", "cogs", "ib", "ni", "oibdp", "sale", "xint", "xsga"]

ITEMS = ["act", "at", "capx", "che", "cogs", "dlc", "dltt", "ib", "lct", "lt", "ni", "oibdp",
         "sale", "txditc", "xint", "xsga", "pstk_x", "seq_x", "be_x"]
NI_AT_MIN_STD = 1e-6   # JKP config: earnings persistence needs a regressor that varies
TRUNCATION_DATES = [197506, 199912, 201503]

# Growth over 1 and 3 years (JKP growth_vars): name -> variable.
GROWTH = {"at": "at_x", "ca": "ca_x", "nca": "nca_x", "lt": "lt", "cl": "cl_x", "ncl": "ncl_x",
          "be": "be_x", "pstk": "pstk_x", "debt": "debt_x", "sale": "sale_x", "cogs": "cogs",
          "sga": "xsga", "opex": "opex_x", "capx": "capx"}
# Change over 1 and 3 years scaled by assets (JKP ch_asset_vars): name -> variable.
CHG_ASSETS = {"cash": "che", "debtst": "dlc", "debtlt": "dltt", "txditc": "txditc", "coa": "coa_x",
              "col": "col_x", "cowc": "cowc_x", "ncol": "ncol_x", "ol": "ol_x", "fnl": "fnl_x",
              "gp": "gp_x", "ebitda": "ebitda_x", "ope": "ope_x", "ni": "ni_x", "nix": "nix_x",
              "nwc": "nwc_x", "capx": "capx"}
# Ratios: name -> (numerator, denominator, safe_div mode of the JKP code).
# Mode 1: denominator != 0 (a negative one is allowed). Mode 3: denominator > 0.
# Mode 4: denominator 12 months before > 0 and count > 12.
RATIOS = {
    "capx_at": ("capx", "at_x", 1), "gp_sale": ("gp_x", "sale_x", 1),
    "ebitda_sale": ("ebitda_x", "sale_x", 1), "ni_sale": ("ni_x", "sale_x", 1),
    "nix_sale": ("ni", "sale_x", 1), "gp_at": ("gp_x", "at_x", 1), "ebitda_at": ("ebitda_x", "at_x", 1),
    "fi_at": ("fi_x", "at_x", 1), "ni_at": ("ni_x", "at_x", 1), "ope_be": ("ope_x", "be_x", 1),
    "ni_be": ("ni_x", "be_x", 1), "nix_be": ("nix_x", "be_x", 1), "debt_at": ("debt_x", "at_x", 1),
    "debt_be": ("debt_x", "be_x", 1), "int_debt": ("xint", "debt_x", 1),
    "ebitda_debt": ("ebitda_x", "debt_x", 1), "debtst_debt": ("dlc", "debt_x", 1),
    "debtlt_debt": ("dltt", "debt_x", 1), "int_debtlt": ("xint", "dltt", 1),
    "profit_cl": ("ebitda_x", "cl_x", 1), "cash_lt": ("che", "lt", 1), "cl_lt": ("cl_x", "lt", 1),
    "opex_at": ("opex_x", "at_x", 1), "nwc_at": ("nwc_x", "at_x", 1), "debtlt_be": ("dltt", "be_x", 1),
    "sale_be": ("sale_x", "be_x", 1), "at_be": ("at_x", "be_x", 1),
    "sale_nwc": ("sale_x", "nwc_x", 3), "cash_at": ("che", "at_x", 3), "cash_cl": ("che", "cl_x", 3),
    "ca_cl": ("ca_x", "cl_x", 3),
    "gp_atl1": ("gp_x", "at_x", 4), "ope_bel1": ("ope_x", "be_x", 4),
}
# Items passed to script 3, which divides them by the market value of month t.
FOR_SCRIPT_3 = ["at_x", "be_x", "sale_x", "gp_x", "ebitda_x", "ope_x", "ni_x", "nix_x", "debt_x",
                "netdebt_x", "che", "pstk_x", "dltt", "dlc", "ed_cd", "ed_cd_w", "ed_constant", "ed_err"]
# Version B characteristics finished in script 3 (they need the market value).
MARKET_SCALED = ([f"{n}_me" for n in ["at", "be", "sale", "gp", "ebitda", "ope", "ni", "nix", "debt",
                                      "netdebt", "cash"]]
                 + [f"{n}_mev" for n in ["at", "be", "sale", "gp", "ebitda", "debt", "pstk", "debtlt",
                                         "debtst", "cash"]]
                 + ["enterprise_value", "eq_dur"])

# Acceptance cases recomputed by the auditor (audit of the signal list, 2026-11-12):
# IBM, GVKEY 006066, fiscal year 1999. Tolerance 1e-8.
ACCEPTANCE = [
    ("006066", 199912, "at_gr1", 0.0162020906),
    ("006066", 199912, "gp_at", 0.4353163038),
    ("006066", 199912, "debt_at", 0.3240642322),
    ("006066", 199912, "ni_ar1", 0.7395355973),
    ("006066", 199912, "ni_ivol", 0.0057040279),
    ("006066", 199912, "ed_cd", 15139.416095),
    ("006066", 199912, "ed_cd_w", 59251.003745),
]


def lag(expr: pl.Expr, k: int) -> pl.Expr:
    # Value k months before, for the same company. The grid is sorted by company
    # and month with no missing month, so a plain shift is right when count > k.
    return pl.when(pl.col("count") > k).then(expr.shift(k))


def sum_sas(a: str, b: str) -> pl.Expr:
    # JKP sum_sas: if one of the two exists, the missing one counts as zero.
    return pl.when(pl.col(a).is_not_null() | pl.col(b).is_not_null()).then(
        pl.col(a).fill_null(0.0) + pl.col(b).fill_null(0.0))


def safe_div(num: str, den: str, mode: int) -> pl.Expr:
    n, d = pl.col(num), pl.col(den)
    if mode == 1:
        return pl.when(d != 0).then(n / d)
    if mode == 3:
        return pl.when(d > 0).then(n / d)
    if mode == 4:
        return pl.when((pl.col("count") > 12) & (lag(d, 12) > 0)).then(n / lag(d, 12))
    raise ValueError(mode)


def var_growth(var: str, h: int) -> pl.Expr:
    x = pl.col(var)
    return pl.when((lag(x, h) > 0) & (pl.col("count") > h)).then(x / lag(x, h) - 1)


def chg_to_assets(var: str, h: int) -> pl.Expr:
    x = pl.col(var)
    return pl.when((pl.col("at_x") > 0) & (pl.col("count") > h)).then((x - lag(x, h)) / pl.col("at_x"))


def mean_year(var: str) -> pl.Expr:
    # JKP mean_year: mean of the value and its 12-month lag, or the one available.
    x, x12 = pl.col(var), lag(pl.col(var), 12)
    return (pl.when(x.is_not_null() & x12.is_not_null()).then((x + x12) / 2)
            .when(x.is_not_null()).then(x).when(x12.is_not_null()).then(x12))


def chg_to_exp(var: str) -> pl.Expr:
    # JKP chg_to_exp: value over the mean of its two previous years, minus one.
    x, s = pl.col(var), lag(pl.col(var), 12) + lag(pl.col(var), 24)
    return pl.when((s > 0) & (pl.col("count") > 24)).then(x / (s / 2) - 1)


def chg_ratio(num: str, den: str, h: int) -> pl.Expr:
    # JKP chg_var1_to_var2: change of the ratio over h months, denominators positive.
    x = pl.when(pl.col(den) <= 0).then(None).otherwise(pl.col(num) / pl.col(den))
    return pl.when(pl.col("count") <= h).then(None).otherwise(x - lag(x, h))


def read_report_calendar(report: dict) -> pl.DataFrame:
    """
    Description:
        Every report of every company, in any currency, with the number of months
        since the previous one (step 8 reads the same raw file the same way).
    Output:
        gvkey, datadate, months_since_previous (missing for the first report).
    """
    cal = (pl.read_csv(io.BytesIO(read_raw_sized(FUNDA, report)), columns=["GVKEY", "datadate"],
                       infer_schema=False)
           .select(pl.col("GVKEY").alias("gvkey"), pl.col("datadate").str.to_date("%Y-%m-%d", strict=True))
           .unique().sort("gvkey", "datadate"))
    mi = pl.col("datadate").dt.year() * 12 + pl.col("datadate").dt.month()
    return cal.with_columns(months_since_previous=(mi - mi.shift(1).over("gvkey")).cast(pl.Int32))


def mask_transition_years(acc: pl.DataFrame, cal: pl.DataFrame) -> pl.DataFrame:
    # Decision D25: the flows of a fiscal year shorter than 12 months are missing.
    n = acc.height
    a = acc.join(cal, on=["gvkey", "datadate"], how="left")
    check(a.height == n, "The report calendar join changed the row count")
    short = (pl.col("months_since_previous") < 12).fill_null(False)
    return a.with_columns(short_year=short).with_columns(
        [pl.when(pl.col("short_year")).then(None).otherwise(pl.col(c)).alias(c) for c in FLOW_ITEMS]
    ).drop("months_since_previous")


def month_grid(acc: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Month grid per company between its first and last fiscal year end (JKP
        add_helper_vars); months without accounts have every item missing.
    Output:
        Grid sorted by (gvkey, mi), with count (from 1) and data_available.
    """
    a = acc.with_columns(mi=(pl.col("datadate").dt.year() * 12 + pl.col("datadate").dt.month()).cast(pl.Int32))
    check(a.select("gvkey", "mi").is_unique().all(), "Two fiscal year ends in one month")
    span = a.group_by("gvkey").agg(lo=pl.col("mi").min(), hi=pl.col("mi").max()).sort("gvkey")
    grid = (span.with_columns(mi=pl.int_ranges(pl.col("lo"), pl.col("hi") + 1, dtype=pl.Int32))
            .explode("mi").select("gvkey", "mi"))
    g = grid.join(a.with_columns(data_available=pl.lit(True)), on=["gvkey", "mi"], how="left").sort("gvkey", "mi")
    check(g.height == grid.height, "The grid join changed the row count")
    return g.with_columns(data_available=pl.col("data_available").fill_null(False),
                          count=pl.int_range(1, pl.len() + 1, dtype=pl.Int32).over("gvkey"))


def helpers(g: pl.DataFrame) -> pl.DataFrame:
    # JKP add_helper_vars, in its order. See the module docstring for the branches.
    c = pl.col
    return (
        g.with_columns(
            at_x=c("at"), sale_x=c("sale"), ca_x=c("act"), cl_x=c("lct"), ni_x=c("ib"), nix_x=c("ni"),
            debt_x=sum_sas("dltt", "dlc"),
            opex_x=c("cogs") + c("xsga"),
        ).with_columns(
            gp_x=c("sale_x") - c("cogs"),
            ncl_x=c("lt") - c("cl_x"),
            coa_x=c("ca_x") - c("che"),
            col_x=c("cl_x") - c("dlc").fill_null(0.0),
            ncol_x=c("lt") - c("cl_x") - c("dltt"),
            fnl_x=c("debt_x") + c("pstk_x").fill_null(0.0),
            nwc_x=c("ca_x") - c("cl_x"),
            netdebt_x=c("debt_x") - c("che").fill_null(0.0),
            nca_x=c("at_x") - c("ca_x"),
        ).with_columns(
            ebitda_x=pl.coalesce(c("oibdp"), c("sale_x") - c("opex_x"), c("gp_x") - c("xsga")),
            cowc_x=c("coa_x") - c("col_x"),
            ol_x=c("col_x") + c("ncol_x"),
            fi_x=c("nix_x") + c("xint"),
        ).with_columns(ope_x=c("ebitda_x") - c("xint"))
    )


def earnings_persistence() -> list[pl.Expr]:
    """
    Description:
        JKP compute_earnings_persistence(5, 5): regression with a constant of
        ni_x / at_x on its value 12 months before, on the five yearly pairs that
        end at the fiscal year end (six aligned balance sheets).
    Output:
        ni_ar1 (slope) and ni_ivol (sample standard deviation of the residuals).
    """
    x = pl.when(pl.col("at_x") > 0).then(pl.col("ni_x") / pl.col("at_x"))
    ys = [lag(x, 12 * k) for k in range(5)]
    ls = [lag(x, 12 * k + 12) for k in range(5)]
    my, ml = sum(ys) / 5, sum(ls) / 5
    sxx = sum((l - ml) ** 2 for l in ls)
    sxy = sum((l - ml) * (y - my) for l, y in zip(ls, ys))
    slope = sxy / sxx
    ok = (sxx / 4).sqrt() > NI_AT_MIN_STD
    resid2 = sum((y - (my + slope * (l - ml))) ** 2 for l, y in zip(ls, ys))
    return [pl.when(ok & slope.is_finite()).then(slope).alias("ni_ar1"),
            pl.when(ok).then((resid2 / 4).sqrt()).alias("ni_ivol")]


def equity_duration(g: pl.DataFrame, horizon: int = 10, r: float = 0.12, roe_mean: float = 0.12,
                    roe_ar1: float = 0.57, g_mean: float = 0.06, g_ar1: float = 0.24) -> pl.DataFrame:
    """
    Description:
        JKP equity_duration_cd: dividends projected over ten years from an AR(1)
        return on equity and an AR(1) sales growth (JKP parameters).
    Output:
        ed_cd, ed_cd_w, ed_constant, ed_err. Script 3 turns them into eq_dur.
    """
    c = pl.col
    roe_c, g_c = roe_mean * (1 - roe_ar1), g_mean * (1 - g_ar1)
    d = g.with_columns(
        __roe0=pl.when((c("count") > 12) & (lag(c("be_x"), 12) > 1)).then(c("ni_x") / lag(c("be_x"), 12)),
        __g0=pl.when((c("count") > 12) & (lag(c("sale_x"), 12) > 1)).then(c("sale_x") / lag(c("sale_x"), 12) - 1),
        __be0=c("be_x"),
    )
    for t in range(1, horizon + 1):
        d = d.with_columns((g_c + g_ar1 * c(f"__g{t - 1}")).alias(f"__g{t}"),
                           (roe_c + roe_ar1 * c(f"__roe{t - 1}")).alias(f"__roe{t}"))
    for t in range(1, horizon + 1):
        d = d.with_columns((c(f"__be{t - 1}") * (1 + c(f"__g{t}"))).alias(f"__be{t}"),
                           (c(f"__be{t - 1}") * (c(f"__roe{t}") - c(f"__g{t}"))).alias(f"__cd{t}"))
    err = pl.any_horizontal([c(f"__be{t}") < 0 for t in range(1, horizon + 1)])
    d = d.with_columns(
        ed_constant=pl.lit(horizon + (1 + r) / r),
        ed_cd_w=sum(t * c(f"__cd{t}") / ((1 + r) ** t) for t in range(1, horizon + 1)),
        ed_cd=sum(c(f"__cd{t}") / ((1 + r) ** t) for t in range(1, horizon + 1)),
        ed_err=pl.when(err).then(1.0).otherwise(0.0),
    )
    return d.drop([x for x in d.columns if x.startswith("__")])


def compute(acc: pl.DataFrame, cal: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        The accounting characteristics, on the fiscal year ends of the table.
    Steps:
        1) Month grid, helper variables.
        2) Levels, growth rates, changes scaled by assets, ratios.
        3) at_turnover, capex_abn, changes against expectations, 5-year changes
           of ratios, volatility of the return on equity, earnings persistence.
        4) Components of the equity duration.
    Output:
        One row per (gvkey, datadate), sorted.
    """
    c = pl.col
    acc = mask_transition_years(acc.select("gvkey", "datadate", *ITEMS), cal)
    g = helpers(month_grid(acc.select("gvkey", "datadate", *ITEMS)))
    g = equity_duration(g)
    capex_sale = pl.when(c("sale_x") > 0).then(c("capx") / c("sale_x"))
    past = lag(capex_sale, 12) + lag(capex_sale, 24) + lag(capex_sale, 36)
    my = mean_year("at_x")
    roe = pl.when(c("be_x") > 0).then(c("ni_x") / c("be_x"))
    roes = pl.concat_list([lag(roe, 12 * k) for k in range(5)]).list.drop_nulls()
    out = g.select(
        "gvkey", "datadate", "data_available",
        c("at_x").alias("assets"), c("sale_x").alias("sales"),
        c("be_x").alias("book_equity"), c("ni_x").alias("net_income"),
        *[var_growth(v, 12 * y).alias(f"{n}_gr{y}") for n, v in GROWTH.items() for y in (1, 3)],
        var_growth("capx", 24).alias("capx_gr2"),
        *[chg_to_assets(v, 12 * y).alias(f"{n}_gr{y}a") for n, v in CHG_ASSETS.items() for y in (1, 3)],
        chg_to_assets("be_x", 12).alias("be_gr1a"),
        *[safe_div(num, den, mode).alias(n) for n, (num, den, mode) in RATIOS.items()],
        pl.when((c("count") > 12) & (my != 0)).then(c("sale_x") / my).alias("at_turnover"),
        pl.when((past != 0) & (c("count") > 36)).then(capex_sale / (past / 3) - 1).alias("capex_abn"),
        (chg_to_exp("gp_x") - chg_to_exp("sale_x")).alias("dgp_dsale"),
        (chg_to_exp("sale_x") - chg_to_exp("xsga")).alias("dsale_dsga"),
        chg_ratio("gp_x", "at_x", 60).alias("gpoa_ch5"), chg_ratio("ni_x", "be_x", 60).alias("roe_ch5"),
        chg_ratio("ni_x", "at_x", 60).alias("roa_ch5"), chg_ratio("gp_x", "sale_x", 60).alias("gmar_ch5"),
        pl.when((c("count") > 48) & (roes.list.len() >= 5)).then(roes.list.std()).alias("roe_be_std"),
        *earnings_persistence(),
        *FOR_SCRIPT_3,
    )
    # A non-finite number (a division that overflows) is missing.
    num = [n for n, t in out.schema.items() if t == pl.Float64]
    out = out.with_columns([pl.when(c(n).is_finite()).then(c(n)).alias(n) for n in num])
    return out.filter(c("data_available")).drop("data_available").sort("gvkey", "datadate")


def second_route(acc: pl.DataFrame, cal: pl.DataFrame, out: pl.DataFrame, report: dict) -> None:
    """
    Description:
        Second route on a sample of companies: each fiscal year is recomputed
        with plain Python, looking the earlier years up by date (no grid, no
        shift), from the raw items.
    Output:
        Entry "second_route" in the report; CheckError on a difference.
    """
    firms = sorted(set(acc["gvkey"].unique().sort().gather_every(150).to_list())
                   | {"006066", "008644", "001076"})
    # Transition years, found here from the list of report dates of each company.
    dates: dict[str, list] = {}
    for g_, d_ in cal.filter(pl.col("gvkey").is_in(firms)).select("gvkey", "datadate").iter_rows():
        dates.setdefault(g_, []).append(d_.year * 12 + d_.month)
    short_years = {(g_, m) for g_, ms in dates.items() for a_, m in zip(sorted(ms), sorted(ms)[1:]) if m - a_ < 12}
    nan = float("nan")
    names = ["at_gr1", "at_gr3", "capx_gr2", "debt_gr1", "cash_gr1a", "ol_gr1a", "gp_gr1a", "be_gr1a",
             "gp_at", "nix_sale", "sale_nwc", "cash_at", "debt_at", "int_debt", "at_turnover", "gp_atl1",
             "ope_bel1", "capex_abn", "dgp_dsale", "roe_ch5", "roe_be_std", "ni_ar1", "ni_ivol",
             "ed_cd", "ed_cd_w", "ebitda_x", "netdebt_x"]
    isn = lambda v: v != v
    rows = []
    for (gvkey,), s in acc.filter(pl.col("gvkey").is_in(firms)).sort("gvkey", "datadate").group_by(
            "gvkey", maintain_order=True):
        recs = {}
        for d in s.to_dicts():
            v = {k: (nan if d[k] is None else float(d[k])) for k in ITEMS}
            if (gvkey, d["datadate"].year * 12 + d["datadate"].month) in short_years:
                for k in FLOW_ITEMS:
                    v[k] = nan
            debt = nan if isn(v["dltt"]) and isn(v["dlc"]) else (0.0 if isn(v["dltt"]) else v["dltt"]) + (
                0.0 if isn(v["dlc"]) else v["dlc"])
            gp = v["sale"] - v["cogs"]
            ebitda = v["oibdp"]
            if isn(ebitda):
                ebitda = v["sale"] - (v["cogs"] + v["xsga"])
            if isn(ebitda):
                ebitda = gp - v["xsga"]
            col_ = v["lct"] - (0.0 if isn(v["dlc"]) else v["dlc"])
            v.update(debt=debt, gp=gp, ebitda=ebitda, ope=ebitda - v["xint"],
                     ol=col_ + (v["lt"] - v["lct"] - v["dltt"]), nwc=v["act"] - v["lct"],
                     netdebt=debt - (0.0 if isn(v["che"]) else v["che"]),
                     capex_sale=(v["capx"] / v["sale"]) if v["sale"] > 0 else nan,
                     ni_at=(v["ib"] / v["at"]) if v["at"] > 0 else nan,
                     roe=(v["ib"] / v["be_x"]) if v["be_x"] > 0 else nan)
            v["_date"] = d["datadate"]
            recs[d["datadate"].year * 12 + d["datadate"].month] = v
        first = min(recs)
        for mi, v in recs.items():
            cnt = mi - first + 1
            L = lambda key, k: recs[mi - k][key] if (cnt > k and (mi - k) in recs) else nan
            gr = lambda key, k: (v[key] / L(key, k) - 1) if (cnt > k and L(key, k) > 0) else nan
            ca = lambda key, k: ((v[key] - L(key, k)) / v["at"]) if (cnt > k and v["at"] > 0) else nan
            rec = {"gvkey": gvkey, "datadate": v["_date"]}
            rec["at_gr1"], rec["at_gr3"], rec["capx_gr2"] = gr("at", 12), gr("at", 36), gr("capx", 24)
            rec["debt_gr1"] = gr("debt", 12)
            rec["cash_gr1a"], rec["ol_gr1a"], rec["gp_gr1a"] = ca("che", 12), ca("ol", 12), ca("gp", 12)
            rec["be_gr1a"] = ca("be_x", 12)
            rec["gp_at"] = v["gp"] / v["at"] if v["at"] != 0 else nan
            rec["nix_sale"] = v["ni"] / v["sale"] if v["sale"] != 0 else nan
            rec["sale_nwc"] = v["sale"] / v["nwc"] if v["nwc"] > 0 else nan
            rec["cash_at"] = v["che"] / v["at"] if v["at"] > 0 else nan
            rec["debt_at"] = v["debt"] / v["at"] if v["at"] != 0 else nan
            rec["int_debt"] = v["xint"] / v["debt"] if v["debt"] != 0 else nan
            # at_turnover: sales over the mean of the assets of this year and the one before.
            a0, a1 = v["at"], L("at", 12)
            m = (a0 + a1) / 2 if not isn(a0) and not isn(a1) else (a0 if not isn(a0) else a1)
            rec["at_turnover"] = v["sale"] / m if (cnt > 12 and m != 0) else nan
            rec["gp_atl1"] = v["gp"] / L("at", 12) if (cnt > 12 and L("at", 12) > 0) else nan
            rec["ope_bel1"] = v["ope"] / L("be_x", 12) if (cnt > 12 and L("be_x", 12) > 0) else nan
            p3 = L("capex_sale", 12) + L("capex_sale", 24) + L("capex_sale", 36)
            rec["capex_abn"] = v["capex_sale"] / (p3 / 3) - 1 if (cnt > 36 and p3 != 0) else nan

            def ce(key):
                tot = L(key, 12) + L(key, 24)
                return v[key] / (tot / 2) - 1 if (cnt > 24 and tot > 0) else nan

            rec["dgp_dsale"] = ce("gp") - ce("sale")
            rec["roe_ch5"] = (v["roe"] - L("roe", 60)) if cnt > 60 else nan
            past = [x for x in [v["roe"]] + [L("roe", 12 * k) for k in range(1, 5)] if not isn(x)]
            rec["roe_be_std"] = float(np.std(past, ddof=1)) if (cnt > 48 and len(past) >= 5) else nan
            ys = [v["ni_at"]] + [L("ni_at", 12 * k) for k in range(1, 5)]
            ls = [L("ni_at", 12 * k + 12) for k in range(5)]
            ar1, ivol = nan, nan
            if not any(isn(x) for x in ys + ls) and np.std(ls, ddof=1) > NI_AT_MIN_STD:
                slope, intercept = np.polyfit(ls, ys, 1)
                ar1 = float(slope)
                ivol = float(np.std(np.array(ys) - (intercept + slope * np.array(ls)), ddof=1))
            rec["ni_ar1"], rec["ni_ivol"] = ar1, ivol
            # Equity duration: ten years of projected dividends.
            roe0 = v["ib"] / L("be_x", 12) if (cnt > 12 and L("be_x", 12) > 1) else nan
            g0 = v["sale"] / L("sale", 12) - 1 if (cnt > 12 and L("sale", 12) > 1) else nan
            be, roe_t, g_t, cd, cdw = v["be_x"], roe0, g0, 0.0, 0.0
            for t in range(1, 11):
                g_t = 0.06 * (1 - 0.24) + 0.24 * g_t
                roe_t = 0.12 * (1 - 0.57) + 0.57 * roe_t
                div = be * (roe_t - g_t)
                be = be * (1 + g_t)
                cd += div / 1.12 ** t
                cdw += t * div / 1.12 ** t
            rec["ed_cd"], rec["ed_cd_w"] = cd, cdw
            rec["ebitda_x"], rec["netdebt_x"] = v["ebitda"], v["netdebt"]
            rows.append({k: (None if isinstance(x, float) and (x != x or math.isinf(x)) else x)
                         for k, x in rec.items()})

    direct = pl.DataFrame(rows, schema={"gvkey": pl.String, "datadate": pl.Date,
                                        **{n: pl.Float64 for n in names}})
    cmp = out.select("gvkey", "datadate", *names).join(direct, on=["gvkey", "datadate"], how="inner", suffix="_d")
    check(cmp.height == direct.height, "The second route lost rows")
    res = {}
    for n in names:
        a, b = pl.col(n), pl.col(f"{n}_d")
        null_diff = cmp.filter(a.is_null() != b.is_null()).height
        rel = cmp.select(((a - b).abs() / b.abs().clip(lower_bound=1e-3)).max()).item()
        res[n] = {"values": cmp.filter(a.is_not_null()).height, "null_mismatch": null_diff, "max_rel_diff": rel}
        check(null_diff == 0 and (rel is None or rel < 1e-8), f"Second route differs for {n}: {res[n]}")
    report["second_route"] = {"companies": len(firms), "rows": cmp.height, **res}


def checks(out: pl.DataFrame, acc: pl.DataFrame, cal: pl.DataFrame, report: dict) -> None:
    c = pl.col
    wanted = [r["characteristic"] for r in csv.DictReader(open(SIGNAL_LIST, encoding="utf-8"))
              if r["version"] == "B"]
    built = [x for x in out.columns if x not in ("gvkey", "datadate") and x not in FOR_SCRIPT_3]
    have = set(built) | set(MARKET_SCALED)
    check(have == set(wanted) and len(built) == len(set(built)),
          f"Columns differ from the signal list: missing {sorted(set(wanted) - have)}, "
          f"extra {sorted(have - set(wanted))}")
    check(not set(built) & set(MARKET_SCALED), "A market-scaled characteristic is built here")
    check(out.select("gvkey", "datadate").equals(acc.select("gvkey", "datadate").sort("gvkey", "datadate")),
          "The output keys are not the keys of the accounts table")
    for n in built + FOR_SCRIPT_3:
        check(out.filter(c(n).is_not_null() & ~c(n).is_finite()).height == 0, f"Non-finite {n}")

    ym = (c("datadate").dt.year() * 100 + c("datadate").dt.month())
    seen = {}
    for gvkey, when, name, expected in ACCEPTANCE:
        got = out.filter((c("gvkey") == gvkey) & (ym == when))[name].to_list()
        seen[f"{gvkey}_{when}_{name}"] = got
        check(len(got) == 1 and got[0] is not None and abs(got[0] - expected) < 1e-8 * max(1.0, abs(expected)),
              f"Acceptance case {gvkey} {when} {name} failed: {got}, expected {expected}")
    # Currency hole: GVKEY 008644 has its 1994 accounts in CAD, so the growth of
    # assets at the end of 1995 has no base 12 months before (a comparison with
    # the last USD accounts, of 1992, would give +8.62).
    hole = out.filter((c("gvkey") == "008644") & (ym == 199512))["at_gr1"].to_list()
    seen["008644_199512_at_gr1"] = hole
    check(hole == [None], f"Growth across a missing fiscal year is not missing: {hole}")
    # Negative tests: the acceptance value is not the one of the year before, and
    # a wrong lag (neighbouring row instead of 12 months) would not give it.
    prev = out.filter((c("gvkey") == "006066") & (ym == 199812))["at_gr1"][0]
    check(abs(prev - 0.0162020906) > 1e-6, "The acceptance case does not date the growth of assets")
    report["acceptance_cases"] = seen

    # SAS-style sum of the two debt items (JKP): with one item missing, debt is
    # the other one; a strict sum would be missing on these rows.
    j = out.select("gvkey", "datadate", "debt_x").join(acc.select("gvkey", "datadate", "dltt", "dlc"),
                                                       on=["gvkey", "datadate"])
    one = j.filter(c("dltt").is_null() != c("dlc").is_null())
    check(one.filter(c("debt_x").is_null()).height == 0, "Debt is missing although one item exists")
    check(one.filter((c("debt_x") - pl.coalesce("dltt", "dlc")).abs() > 1e-9).height == 0,
          "Debt with one item differs from that item")
    check(j.filter(c("dltt").is_null() & c("dlc").is_null() & c("debt_x").is_not_null()).height == 0,
          "Debt exists although both items are missing")
    report["debt_sas_sum"] = {"rows_with_one_item_only": one.height,
                              "rows_with_no_item": j.filter(c("dltt").is_null() & c("dlc").is_null()).height}

    # Evidence on the definitional fallbacks: sale - cogs - xsga against oibdp.
    k = acc.filter(c("sale").is_not_null() & c("cogs").is_not_null() & c("xsga").is_not_null()
                   & c("oibdp").is_not_null()).with_columns(gap=(c("sale") - c("cogs") - c("xsga") - c("oibdp")).abs())
    report["joint_identity_sale_cogs_xsga_oibdp"] = {
        # 0.001 is the rounding unit of the items (USD thousands): a gap of exactly
        # one unit is rounding, so the count starts strictly above it.
        "rows": k.height, "gaps_of_one_rounding_unit_or_less": k.filter(c("gap") <= 1e-3 + 1e-9).height,
        "gaps_above_0.001": k.filter(c("gap") > 1e-3 + 1e-9).height,
        "gaps_above_1": k.filter(c("gap") > 1).height,
        "rows_where_oibdp_is_missing_and_the_fallback_is_used": acc.filter(
            c("oibdp").is_null() & c("sale").is_not_null() & c("cogs").is_not_null()
            & c("xsga").is_not_null()).height}

    # Transition years (D25). GVKEY 001076 closes a 9-month year in December 1995
    # (previous report in March 1995): its flows are missing, and the growth of
    # sales of 1996 has no comparable base (it would be +53.9 %).
    short = cal.filter(pl.col("months_since_previous") < 12).join(
        acc.select("gvkey", "datadate"), on=["gvkey", "datadate"], how="inner")
    tr = out.join(short.select("gvkey", "datadate"), on=["gvkey", "datadate"], how="inner")
    for n in ["sales", "net_income", "gp_at", "capx_at", "sale_gr1", "ni_at"]:
        check(tr[n].null_count() == tr.height, f"{n} is known in a transition year")
    check(tr["assets"].null_count() < tr.height, "Balance-sheet items are masked in transition years")
    case = out.filter((c("gvkey") == "001076") & ym.is_in([199512, 199612])).sort("datadate")
    check(case.height == 2 and case["sales"].to_list()[0] is None and case["sale_gr1"].to_list() == [None, None]
          and case["at_gr1"].to_list()[1] is not None,
          f"Reference 001076 (transition year) failed: {case.select('datadate', 'sales', 'sale_gr1', 'at_gr1')}")
    report["transition_years"] = {
        "reports_less_than_12_months_after_the_previous_one": cal.filter(pl.col("months_since_previous") < 12).height,
        "of_which_in_the_usd_table": short.height,
        "sale_gr1_known": int(out["sale_gr1"].is_not_null().sum()),
    }

    second_route(acc, cal, out, report)

    # Truncation: hide every fiscal year after T, rebuild, the past must be identical.
    trunc = {}
    for T in TRUNCATION_DATES:
        cut = compute(acc.filter(ym <= T), cal.filter(ym <= T))
        ref = out.filter(ym <= T)
        same = cut.equals(ref)
        trunc[str(T)] = {"rows": ref.height, "identical": same}
        check(same, f"Accounting signals up to {T} change when later fiscal years are hidden")
    report["truncation_test"] = trunc

    report["share_known"] = {n: round(out[n].is_not_null().mean(), 4) for n in built}
    report["medians"] = {n: out[n].median() for n in built}


def main() -> None:
    report: dict = {"script": "scripts/signals/2_accounting_signals.py", "inputs": {}}
    acc, run_id = read_verified(ACCOUNTS, ACCOUNTS_REPORT)
    report["inputs"][ACCOUNTS.name] = {"from_run": run_id}
    report["inputs"][SIGNAL_LIST.name] = sha256(SIGNAL_LIST)
    cal = read_report_calendar(report)
    check(acc.join(cal, on=["gvkey", "datadate"], how="anti").height == 0,
          "A fiscal year of the accounts table is not in the raw file")
    out = compute(acc, cal)
    report["rows"] = out.height
    report["characteristics"] = out.width - 2 - len(FOR_SCRIPT_3)
    checks(out, acc, cal, report)
    publish({PROCESSED / "signals_acc.parquet": out}, report, PROCESSED / "signals_acc_report.json")
    print(f"signals_acc: {out.height:,} fiscal years, {report['characteristics']} characteristics. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
