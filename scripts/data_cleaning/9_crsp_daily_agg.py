"""Step 9 of CleaningSpec.md: monthly summaries of the daily CRSP file (reduced scope, D11).

Reference code (Resources/reference_code/):
- JKP aux_functions.py:
    gen_crsp_sf / prepare_crsp_sf -> daily rows with DlyDelFlg = 'Y' are not used
    prepare_daily     -> keep days with a market return; a return after a gap of
                         more than 14 days is set to null
    gen_aux_windows   -> the "_21d", "_126d", "_252d" windows are 1, 6 and 12
                         calendar months ending at the month end
    apply_group_filter-> minimum number of observations in the window
    rvol              -> std(ret_exc); null if raw returns are near-constant
                         (std <= 1e-6) or 90 % or more of them are zero
    capm              -> beta = cov(ret_exc, mktrf) / var(mktrf), same guards
    dolvol            -> mean of the daily dollar volume
    adj_trd_vol_NASDAQ-> Gao-Ritter NASDAQ volume adjustment (copied in step 3)

Deviations (see CleaningSpec.md):
- Market and risk-free returns come from the Ken French daily file (JKP builds
  its own market return and uses CRSP t30ret / 21).
- The windows are computed from monthly sums (count, sum, sum of squares, cross
  products): the same numbers as a direct computation, in one pass.
- Two spreads: the quoted spread from DlyBid / DlyAsk (course cost model), and
  JKP's high-low estimator (bidask_hl, Corwin and Schultz 2012), copied, because
  quotes barely exist before the 1990s.
- A value is given only for a month where the stock has daily rows.

Outputs (data/processed/):
- crsp_daily_min.parquet     the daily columns we use (intermediate, typed)
- crsp_daily_agg.parquet     one row per stock-month: rvol_21d, rvol_252d, beta_252d,
                             dolvol_21d, dolvol_126d, spread_quoted_21d, bidaskhl_21d and counts
- crsp_daily_agg_report.json checks, counts and output hashes (written last)
"""

from __future__ import annotations

import io
import json
import zipfile

import polars as pl

from utils import (PROCESSED, RAW, CheckError, adj_trd_vol_nasdaq, check, publish, read_raw_verified,
                   read_verified, sha256)

DAILY = RAW / "crsp_ciz_daily_stock.csv"
DAILY_MIN = PROCESSED / "crsp_daily_min.parquet"
FF_DAILY = RAW / "french" / "F-F_Research_Data_Factors_daily_CSV.zip"
PANEL = PROCESSED / "crsp_panel_acc.parquet"
PANEL_REPORT = PROCESSED / "accounting_availability_report.json"
STEP1_REPORT = PROCESSED / "crsp_monthly_report.json"

HEADER = ["PERMNO", "HdrCUSIP", "SecurityNm", "Ticker", "PERMCO", "YYYYMMDD", "DlyCalDt",
          "DlyDelFlg", "DlyPrc", "DlyPrcFlg", "DlyCap", "DlyRet", "DlyRetx", "DlyRetI", "DlyVol",
          "DlyLow", "DlyHigh", "DlyBid", "DlyAsk", "DlyPrcVol", "ShrOut", "DlyCumFacPr",
          "DlyCumFacShr"]
MAX_RET_GAP_DAYS = 14          # JKP: a return after a longer gap is not used
RET_MIN_STD = 1e-6             # JKP config: near-constant returns give no statistic
CONSTANT_MAX_ZERO_FRAC = 0.9   # JKP: too many zero returns give no statistic
MIN_OBS = {"21d": 15, "126d": 60, "252d": 120}   # JKP minimum observations
MIN_SPREAD_DAYS = 10           # minimum days with a valid quote in the month
MAX_SPREAD = 0.5               # a quoted spread above 50 % of the midpoint is not used
N_BATCHES = 60
CONVERT_VERSION = 2            # change it when convert_daily changes
SAMPLE_START = 196301
SUMS = ["n", "n_zero", "s_r", "s_rr", "s_m", "s_mm", "s_rm", "s_raw", "s_raw2",
        "n_dv", "s_dv", "n_sp", "s_sp"]


def convert_daily(report: dict) -> None:
    """
    Description:
        One streaming pass over the 22 GB daily file: keep the columns we use.
    Steps:
        1) Check the size against the raw manifest, the hash against the one
           recorded at step 1, and the exact header.
        2) Read every field as text ("" is missing), cast strictly, write Parquet.
    Output:
        data/processed/crsp_daily_min.parquet (temp file, then rename).
    """
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    size = {f["filename"]: f["bytes"] for f in manifest["files"]}.get(DAILY.name)
    check(size == DAILY.stat().st_size, f"{DAILY.name}: size differs from the raw manifest")
    digest = sha256(DAILY)
    step1 = json.loads(STEP1_REPORT.read_text(encoding="utf-8"))["inputs"][DAILY.name]
    check(digest == step1, f"{DAILY.name} is not the file read at step 1")
    report["inputs"][DAILY.name] = digest
    with DAILY.open(encoding="utf-8") as f:
        check(f.readline().rstrip("\r\n").split(",") == HEADER, f"Unexpected header in {DAILY.name}")

    # Skip the conversion when the Parquet on disk was built from this exact raw
    # file by this version of the conversion (its own hash is checked too).
    stamp = DAILY_MIN.with_name(DAILY_MIN.name + ".json")
    if DAILY_MIN.exists() and stamp.exists():
        old = json.loads(stamp.read_text(encoding="utf-8"))
        if (old.get("raw_sha256") == digest and old.get("version") == CONVERT_VERSION
                and old.get("parquet_sha256") == sha256(DAILY_MIN)):
            return
    num = lambda c: pl.col(c).cast(pl.Float64, strict=True)
    tmp = DAILY_MIN.with_name(DAILY_MIN.name + ".tmp")
    (
        pl.scan_csv(DAILY, infer_schema=False)
        .select(
            pl.col("PERMNO").cast(pl.Int64, strict=True).alias("permno"),
            pl.col("DlyCalDt").str.to_date("%Y-%m-%d", strict=True).alias("date"),
            pl.col("DlyDelFlg").alias("del_flag"),
            num("DlyPrc").alias("prc"), num("DlyRet").alias("ret"), num("DlyVol").alias("vol"),
            num("DlyBid").alias("bid"), num("DlyAsk").alias("ask"),
            pl.col("DlyPrcFlg").alias("prc_flag"),
            num("DlyHigh").alias("high"), num("DlyLow").alias("low"),
            num("DlyCumFacShr").alias("cfacshr"),
        )
        .sink_parquet(tmp, row_group_size=1_000_000)
    )
    tmp.replace(DAILY_MIN)
    stamp.write_text(json.dumps({"raw_sha256": digest, "version": CONVERT_VERSION,
                                 "parquet_sha256": sha256(DAILY_MIN)}), encoding="utf-8")


def read_french_daily(report: dict) -> pl.DataFrame:
    # Ken French daily factors: date, market excess return and risk-free rate (decimals).
    data, digest = read_raw_verified(FF_DAILY, FF_DAILY.parent / "manifest.json")
    report["inputs"][FF_DAILY.name] = digest
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        lines = z.read(z.namelist()[0]).decode("latin-1").splitlines()
    header = ",Mkt-RF,SMB,HML,RF"
    check(header in lines, "Daily factor header not found")
    start = lines.index(header) + 1
    df = pl.read_csv(io.StringIO("\n".join(lines[start:lines.index("", start)])), has_header=False,
                     new_columns=["date", "mktrf", "smb", "hml", "rf"], infer_schema=False)
    df = df.select(
        pl.col("date").str.strip_chars().str.to_date("%Y%m%d", strict=True),
        *[pl.col(c).str.strip_chars().cast(pl.Float64, strict=True) for c in ["mktrf", "rf"]],
    )
    check(df["date"].null_count() == 0 and df["date"].is_unique().all() and df["date"].is_sorted(),
          "Daily factor dates are missing, duplicated or unsorted")
    df = df.with_columns(pl.col("mktrf", "rf").replace({-99.99: None, -999.0: None}) / 100)
    check(df.null_count().sum_horizontal().item() == 0, "Missing daily market or risk-free return")
    check(df.select(pl.col("mktrf", "rf").is_finite().all()).row(0) == (True, True), "Non-finite factor")
    report["french_daily"] = {"days": df.height, "first": df["date"].min(), "last": df["date"].max()}
    return df


def prepare_batch(d: pl.DataFrame, ff: pl.DataFrame, nasdaq: pl.DataFrame, counts: dict) -> pl.DataFrame:
    """
    Description:
        Clean the daily rows of a group of stocks (JKP prepare_daily, reduced).
    Steps:
        1) Drop exact duplicate rows; (permno, date) must then be unique.
        2) Drop rows with DlyDelFlg = 'Y' (JKP).
        3) A return after a gap of more than 14 days is set to null (JKP).
        4) Join the market and risk-free returns; keep days with a market return (JKP).
        5) ret_exc = ret - rf; dollar volume with the NASDAQ adjustment; quoted spread.
    Output:
        Daily rows with ret_exc, mktrf, dolvol_d, spread_d.
    """
    n0 = d.height
    d = d.unique()
    counts["exact_duplicate_rows"] += n0 - d.height
    check(d.select("permno", "date").is_unique().all(), "Conflicting duplicate (permno, date)")
    check(d["del_flag"].null_count() == 0 and set(d["del_flag"].unique()) <= {"N", "Y"},
          "Unknown DlyDelFlg")
    for c in ["prc", "ret", "vol", "bid", "ask", "high", "low", "cfacshr"]:
        check(d.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height == 0, f"Non-finite {c}")
    check(d.filter(pl.col("ret") < -1).height == 0, "Daily return below -100 %")
    counts["rows"] += d.height
    counts["delisting_rows_dropped"] += d.filter(pl.col("del_flag") == "Y").height

    d = (
        d.filter(pl.col("del_flag") == "N").sort("permno", "date")
        .with_columns(gap=(pl.col("date") - pl.col("date").shift(1).over("permno")).dt.total_days())
    )
    counts["returns_dropped_after_long_gap"] += d.filter(
        pl.col("ret").is_not_null() & (pl.col("gap") > MAX_RET_GAP_DAYS)).height
    d = (
        d.with_columns(
            ret_raw=pl.col("ret"),   # CRSP return, kept for the check against monthly returns
            ret=pl.when(pl.col("gap") <= MAX_RET_GAP_DAYS).then(pl.col("ret")),
            ym=(pl.col("date").dt.year() * 100 + pl.col("date").dt.month()).cast(pl.Int32),
        )
        .join(ff, on="date", how="left")
    )
    counts["rows_without_market_return"] += d.filter(pl.col("mktrf").is_null()).height
    d = d.filter(pl.col("mktrf").is_not_null()).join(nasdaq, on=["permno", "ym"], how="left")
    counts["rows_with_unknown_exchange"] += d.filter(pl.col("is_nasdaq").is_null()).height
    return d.with_columns(
        ret_exc=pl.col("ret") - pl.col("rf"),
        vol_adj=pl.col("vol"),
    ).with_columns(
        adj_trd_vol_nasdaq("date", "vol_adj", pl.col("is_nasdaq").fill_null(False)),
    ).with_columns(
        # Dollar volume; unknown when the exchange of the month is unknown.
        dolvol_d=pl.when(pl.col("is_nasdaq").is_not_null()).then(pl.col("prc").abs() * pl.col("vol_adj")),
        # Quoted spread over the midpoint; only with a valid, uncrossed quote.
        spread_d=pl.when((pl.col("bid") > 0) & (pl.col("ask") > pl.col("bid")))
        .then((pl.col("ask") - pl.col("bid")) / ((pl.col("ask") + pl.col("bid")) / 2)),
    ).with_columns(
        spread_d=pl.when(pl.col("spread_d") <= MAX_SPREAD).then(pl.col("spread_d")),
    ).pipe(add_high_low_spread)


def add_high_low_spread(d: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Daily bid-ask spread from high and low prices (Corwin and Schultz, 2012),
        copied from JKP: bidask_hl, impute_high_low, adjust_overnight_returns and
        compute_bidask_spread. Column names follow JKP (id = permno, tvol = vol).
    Steps:
        1) JKP gen_crsp_sf: high / low valid only with a positive price; bidask
           flag when the price is a bid-ask average; prices divided by adjfct.
        2) impute_high_low: drop impossible high / low, carry the last valid range.
        3) adjust_overnight_returns: move today's range if yesterday's close is outside.
        4) compute_bidask_spread: spread from the 1-day and 2-day ranges; negative -> 0.
    Output:
        Daily rows with spread_hl_d (null when it cannot be computed).
    """
    col = pl.col
    sqrt2, const = 2 ** 0.5, 3 - 2 * 2 ** 0.5
    df = d.with_columns(
        # JKP safe_div: no value when the adjustment factor is missing or zero.
        prc_high=pl.when((col("prc") > 0) & (col("high") > 0) & (col("cfacshr") > 0))
        .then(col("high") / col("cfacshr")),
        prc_low=pl.when((col("prc") > 0) & (col("low") > 0) & (col("cfacshr") > 0))
        .then(col("low") / col("cfacshr")),
        prc_adj=pl.when(col("cfacshr") > 0).then(col("prc") / col("cfacshr")),
        bidask=(col("prc_flag") == "BA").cast(pl.Int32),
    ).rename({"prc": "prc_unadj", "prc_adj": "prc", "vol": "tvol", "permno": "id"})

    # --- impute_high_low (JKP, copied) ---
    sc1 = ((col("bidask") == 1) | (col("tvol") == 0) | (col("prc_low") <= 0)
           | (col("prc_high") <= 0) | (col("prc_low") == col("prc_high")))
    sc2 = (col("prc_low") > 0) & (col("prc_high") > col("prc_low"))
    sc3 = (col("flag_replace")) & (
        (col("prc") >= col("prc_low_r")) & (col("prc") <= col("prc_high_r"))
        | (col("prc").is_null() & col("prc_low_r").is_null() & col("prc_high_r").is_null())
    )
    sc4 = (col("flag_replace")) & (col("prc") < col("prc_low_r"))
    sc5 = (col("flag_replace")) & (col("prc") > col("prc_high_r")).fill_null(True)
    sc6 = (col("prc_low") != 0) & (col("prc_high") / col("prc_low") > 8)
    df = (
        df.sort(["id", "date"])
        .with_columns(
            prc_high=pl.when(sc1).then(None).otherwise(col("prc_high")),
            prc_low=pl.when(sc1).then(None).otherwise(col("prc_low")),
            count=pl.cum_count("id").over("id"),
        )
        .with_columns(
            prc_low_r=(pl.when(col("count") == 1).then(None).otherwise(col("prc_low"))),
            prc_high_r=(pl.when(col("count") == 1).then(None).otherwise(col("prc_high"))),
        )
        .with_columns(
            prc_low_r=(pl.when(sc2).then(col("prc_low")).otherwise(col("prc_low_r"))),
            prc_high_r=(pl.when(sc2).then(col("prc_high")).otherwise(col("prc_high_r"))),
        )
        .sort(["id", "date"])
        .with_columns(
            flag_replace=col("prc_low_r").is_null(),
            prc_low_r=col("prc_low_r").forward_fill().over("id"),
            prc_high_r=col("prc_high_r").forward_fill().over("id"),
        )
        .with_columns(
            prc_low=(pl.when(sc3).then(col("prc_low_r")).when(sc4).then(col("prc"))
                     .when(sc5).then(col("prc_low_r") + (col("prc") - col("prc_high_r")))
                     .otherwise(col("prc_low"))),
            prc_high=(pl.when(sc3).then(col("prc_high_r"))
                      .when(sc4).then(col("prc_high_r") - (col("prc_low_r") - col("prc")))
                      .when(sc5).then(col("prc")).otherwise(col("prc_high"))),
        )
        .with_columns(
            prc_low=pl.when(sc6).then(None).otherwise(col("prc_low")),
            prc_high=pl.when(sc6).then(None).otherwise(col("prc_high")),
        )
    )

    # --- adjust_overnight_returns (JKP, copied) ---
    sc1 = (col("prc_l1") < col("prc_low")) & (col("prc_l1") > 0)
    sc2 = (col("prc_l1") > col("prc_high")) & (col("prc_l1") > 0)
    df = (
        df.sort(["id", "date"])
        .with_columns(
            prc_low_t=col("prc_low"),
            prc_high_t=col("prc_high"),
            prc_low_l1=col("prc_low").shift(1).over("id"),
            prc_high_l1=col("prc_high").shift(1).over("id"),
            prc_l1=col("prc").shift(1).over("id"),
        )
        .with_columns(
            prc_high_t=pl.when(sc1).then(col("prc_high") - (col("prc_low") - col("prc_l1")))
            .otherwise(col("prc_high_t")),
            prc_low_t=pl.when(sc1).then(col("prc_l1")).otherwise(col("prc_low_t")),
        )
        .with_columns(
            prc_high_t=pl.when(sc2).then(col("prc_l1")).otherwise(col("prc_high_t")),
            prc_low_t=pl.when(sc2).then(col("prc_low") + (col("prc_l1") - col("prc_high")))
            .otherwise(col("prc_low_t")),
        )
        .with_columns(
            prc_high_2d=pl.max_horizontal("prc_high_t", "prc_high_l1"),
            prc_low_2d=pl.min_horizontal("prc_low_t", "prc_low_l1"),
        )
    )

    # --- compute_bidask_spread (JKP, copied; the monthly mean is taken in month_sums) ---
    df = (
        df.with_columns(
            beta=(pl.when((col("prc_low_t") > 0) & (col("prc_low_l1") > 0))
                  .then(((col("prc_high_t") / col("prc_low_t")).log() ** 2)
                        + ((col("prc_high_l1") / col("prc_low_l1")).log() ** 2))),
            gamma=pl.when(col("prc_low_2d") > 0)
            .then((col("prc_high_2d") / col("prc_low_2d")).log() ** 2),
        )
        .with_columns(alpha=((sqrt2 - 1) * col("beta").sqrt()) / const - (col("gamma") / const).sqrt())
        .with_columns(spread=2 * (col("alpha").exp() - 1) / (1 + col("alpha").exp()))
        .with_columns(spread_hl_d=pl.when(col("spread") < 0).then(pl.lit(0.0)).otherwise(col("spread")))
    )
    keep = [c for c in d.columns] + ["spread_hl_d"]
    return df.rename({"prc": "prc_adj", "prc_unadj": "prc", "tvol": "vol", "id": "permno"}).select(keep)


def month_sums(d: pl.DataFrame) -> pl.DataFrame:
    # Sums per stock-month, enough to rebuild std, covariance and means over any months.
    ok = pl.col("ret_exc").is_not_null()
    r, m = pl.col("ret_exc").filter(ok), pl.col("mktrf").filter(ok)
    raw = pl.col("ret").filter(ok)
    return d.group_by("permno", "ym").agg(
        n=ok.sum().cast(pl.Int64), n_zero=(raw == 0).sum().cast(pl.Int64),
        s_r=r.sum(), s_rr=(r * r).sum(), s_m=m.sum(), s_mm=(m * m).sum(), s_rm=(r * m).sum(),
        s_raw=raw.sum(), s_raw2=(raw * raw).sum(),
        n_dv=pl.col("dolvol_d").count().cast(pl.Int64), s_dv=pl.col("dolvol_d").sum(),
        n_sp=pl.col("spread_d").count().cast(pl.Int64), s_sp=pl.col("spread_d").sum(),
        n_hl=pl.col("spread_hl_d").count().cast(pl.Int64), s_hl=pl.col("spread_hl_d").sum(),
        # For the check against CRSP monthly returns: all days of the month compounded.
        n_days=pl.len().cast(pl.Int64), n_ret_raw=pl.col("ret_raw").count().cast(pl.Int64),
        ret_cmp=(1 + pl.col("ret_raw")).product() - 1,
        last_date=pl.col("date").max(),
    )


def window_stats(s: pl.DataFrame) -> pl.DataFrame:
    """
    Description:
        Statistics over 1, 6 and 12 calendar months ending at the month end (JKP).
    Steps:
        1) Month number mi; rolling sums over (mi - k, mi] for k = 6 and 12.
        2) std and beta from the sums; JKP minimum observations and guards.
    Output:
        One row per stock-month with the final columns.
    """
    s = s.with_columns(mi=(pl.col("ym") // 100 * 12 + pl.col("ym") % 100).cast(pl.Int64)).sort("permno", "mi")
    out = s
    for k in (6, 12):
        roll = (s.rolling(index_column="mi", period=f"{k}i", group_by="permno")
                .agg([pl.col(c).sum().alias(f"{c}_{k}") for c in SUMS]))
        out = out.join(roll, on=["permno", "mi"], how="left")

    def var(n, s1, s2):  # sample variance from count, sum and sum of squares
        return (pl.col(s2) - pl.col(s1) ** 2 / pl.col(n)) / (pl.col(n) - 1)

    def guarded(expr, sfx, min_obs):
        # JKP: enough observations, raw returns not near-constant, not mostly zero.
        n, raw_var = f"n{sfx}", var(f"n{sfx}", f"s_raw{sfx}", f"s_raw2{sfx}")
        ok = ((pl.col(n) >= min_obs) & (raw_var.clip(lower_bound=0).sqrt() > RET_MIN_STD)
              & (pl.col(f"n_zero{sfx}") / pl.col(n) < CONSTANT_MAX_ZERO_FRAC))
        return pl.when(ok).then(expr)

    cov12 = (pl.col("s_rm_12") - pl.col("s_r_12") * pl.col("s_m_12") / pl.col("n_12")) / (pl.col("n_12") - 1)
    return out.select(
        "permno", pl.col("ym").alias("yyyymm"), "last_date", "n_days", "n_ret_raw", "ret_cmp",
        pl.col("n").alias("n_ret_21d"), pl.col("n_12").alias("n_ret_252d"),
        guarded(var("n", "s_r", "s_rr").clip(lower_bound=0).sqrt(), "", MIN_OBS["21d"]).alias("rvol_21d"),
        guarded(var("n_12", "s_r_12", "s_rr_12").clip(lower_bound=0).sqrt(), "_12", MIN_OBS["252d"])
        .alias("rvol_252d"),
        guarded(cov12 / var("n_12", "s_m_12", "s_mm_12"), "_12", MIN_OBS["252d"]).alias("beta_252d"),
        pl.when(pl.col("n_dv") >= MIN_OBS["21d"]).then(pl.col("s_dv") / pl.col("n_dv")).alias("dolvol_21d"),
        pl.when(pl.col("n_dv_6") >= MIN_OBS["126d"]).then(pl.col("s_dv_6") / pl.col("n_dv_6"))
        .alias("dolvol_126d"),
        pl.col("n_sp").alias("n_spread_21d"),
        pl.when(pl.col("n_sp") >= MIN_SPREAD_DAYS).then(pl.col("s_sp") / pl.col("n_sp"))
        .alias("spread_quoted_21d"),
        pl.col("n_hl").alias("n_spread_hl_21d"),
        # JKP bidaskhl_21d: monthly mean, more than 10 days (strictly, as in JKP).
        pl.when(pl.col("n_hl") > MIN_SPREAD_DAYS).then(pl.col("s_hl") / pl.col("n_hl"))
        .alias("bidaskhl_21d"),
    )


def check_direct(out: pl.DataFrame, ff: pl.DataFrame, nasdaq: pl.DataFrame, report: dict) -> None:
    # Second route on a sample of stocks: compute every statistic directly from the
    # daily rows of each window (no sums), and compare.
    sample = out.select("permno").unique().sort("permno").gather_every(400)["permno"].to_list()
    d = prepare_batch(pl.scan_parquet(DAILY_MIN).filter(pl.col("permno").is_in(sample)).collect(),
                      ff, nasdaq, {k: 0 for k in COUNTS})
    d = d.with_columns(mi=(pl.col("ym") // 100 * 12 + pl.col("ym") % 100).cast(pl.Int64))
    months = d.select("permno", "mi").unique()
    worst = {}
    for k, cols in [(1, ["rvol_21d", "dolvol_21d", "spread_quoted_21d", "bidaskhl_21d"]),
                    (6, ["dolvol_126d"]), (12, ["rvol_252d", "beta_252d"])]:
        # Every daily row goes to the k windows (end months) that contain it.
        w = (d.with_columns(end=pl.int_ranges(pl.col("mi"), pl.col("mi") + k)).explode("end")
             .join(months.rename({"mi": "end"}), on=["permno", "end"], how="semi"))
        ok = pl.col("ret_exc").is_not_null()
        r, m, raw = pl.col("ret_exc").filter(ok), pl.col("mktrf").filter(ok), pl.col("ret").filter(ok)
        n = ok.sum()
        min_obs = MIN_OBS[{1: "21d", 6: "126d", 12: "252d"}[k]]
        good = (n >= min_obs) & (raw.std() > RET_MIN_STD) & ((raw == 0).mean() < CONSTANT_MAX_ZERO_FRAC)
        direct = w.group_by("permno", "end").agg(
            rvol=pl.when(good).then(r.std()),
            beta=pl.when(good).then(pl.cov(r, m) / m.var()),
            dolvol=pl.when(pl.col("dolvol_d").count() >= min_obs).then(pl.col("dolvol_d").mean()),
            spread=pl.when(pl.col("spread_d").count() >= MIN_SPREAD_DAYS).then(pl.col("spread_d").mean()),
            hl=pl.when(pl.col("spread_hl_d").count() > MIN_SPREAD_DAYS).then(pl.col("spread_hl_d").mean()),
        )
        cmp = (out.with_columns(end=(pl.col("yyyymm") // 100 * 12 + pl.col("yyyymm") % 100).cast(pl.Int64))
               .join(direct, on=["permno", "end"], how="inner"))
        for c in cols:
            ref = pl.col({"rvol": "rvol", "beta": "beta", "dolv": "dolvol", "spre": "spread", "bida": "hl"}[c[:4]])
            null_diff = cmp.filter(pl.col(c).is_null() != ref.is_null()).height
            # Relative gap, with a floor on the scale (a beta near zero has no relative gap).
            rel = cmp.select(((pl.col(c) - ref).abs() / ref.abs().clip(lower_bound=1e-3)).max()).item()
            worst[c] = {"rows": cmp.height, "null_mismatch": null_diff, "max_rel_diff": rel}
            check(null_diff == 0 and (rel is None or rel < 1e-6),
                  f"Direct computation differs for {c}: {worst[c]}")
    report["direct_check_sample"] = {"stocks": len(sample), **worst}


COUNTS = ["rows", "exact_duplicate_rows", "delisting_rows_dropped", "returns_dropped_after_long_gap",
          "rows_without_market_return", "rows_with_unknown_exchange"]


def checks(out: pl.DataFrame, panel: pl.DataFrame, report: dict) -> None:
    check(out.select("permno", "yyyymm").is_unique().all(), "Duplicate stock-month")
    # Only data of month t or before: the last daily date used is inside the month.
    check(out.filter((pl.col("last_date").dt.year() * 100 + pl.col("last_date").dt.month())
                     != pl.col("yyyymm")).height == 0, "A daily date outside its month")
    for c in ["rvol_21d", "rvol_252d", "dolvol_21d", "dolvol_126d", "spread_quoted_21d", "bidaskhl_21d"]:
        check(out.filter(pl.col(c) < 0).height == 0, f"Negative {c}")
        check(out.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height == 0, f"Non-finite {c}")
    check(out.filter(pl.col("beta_252d").is_not_null() & ~pl.col("beta_252d").is_finite()).height == 0,
          "Non-finite beta")

    j = panel.select("permno", "yyyymm", "eom", "eligible", "me", "ret_crsp", "del_flag", "size_grp"
                     ).join(out, on=["permno", "yyyymm"], how="left")
    # Independent check of the daily file: daily returns compounded over the month
    # against the CRSP monthly return (normal months with a return on every day).
    c = j.filter((pl.col("del_flag") == "N") & pl.col("ret_crsp").is_not_null()
                 & (pl.col("n_ret_raw") == pl.col("n_days")) & (pl.col("yyyymm") >= SAMPLE_START))
    diff = (pl.col("ret_cmp") - pl.col("ret_crsp")).abs()
    report["daily_vs_monthly_return"] = {
        "rows": c.height, "share_within_0.0001": c.filter(diff <= 1e-4).height / c.height,
        "share_within_0.01": c.filter(diff <= 1e-2).height / c.height,
        "corr": c.select(pl.corr("ret_cmp", "ret_crsp")).item(),
    }
    check(report["daily_vs_monthly_return"]["corr"] > 0.99, "Daily and monthly returns disagree")

    e = j.filter(pl.col("eligible") & (pl.col("yyyymm") >= SAMPLE_START))
    e = e.with_columns(spread_any=pl.coalesce("spread_quoted_21d", "bidaskhl_21d"))
    cols = ["rvol_21d", "rvol_252d", "beta_252d", "dolvol_126d", "spread_quoted_21d",
            "bidaskhl_21d", "spread_any"]
    cov = lambda g: {c: {"n": round(g[c].is_not_null().mean(), 4),
                         "me": round(g.filter(pl.col(c).is_not_null())["me"].sum() / g["me"].sum(), 4)}
                     for c in cols}
    report["coverage_eligible_from_1963"] = {"rows": e.height, **cov(e)}
    report["coverage_by_decade"] = {
        str(d): cov(g) for (d,), g in e.with_columns(decade=pl.col("yyyymm") // 1000 * 10)
        .sort("decade").group_by("decade", maintain_order=True)}
    report["medians_eligible"] = {c: e[c].median() for c in cols}
    report["spread_median_by_size_grp"] = {
        str(s): g["spread_quoted_21d"].median()
        for (s,), g in e.sort("size_grp").group_by("size_grp", maintain_order=True)}
    # The two spread measures on stock-months that have both (no quote is needed
    # for the high-low one, so it covers the years before quotes exist).
    both = e.filter(pl.col("spread_quoted_21d").is_not_null() & pl.col("bidaskhl_21d").is_not_null())
    rank_corr = both.group_by("yyyymm").agg(
        pl.corr("spread_quoted_21d", "bidaskhl_21d", method="spearman").alias("c"),
        pl.len().alias("k")).filter(pl.col("k") >= 100)["c"].fill_nan(None).mean()
    report["quoted_vs_high_low_spread"] = {
        "rows": both.height, "mean_monthly_rank_corr": rank_corr,
        "median_quoted": both["spread_quoted_21d"].median(),
        "median_high_low": both["bidaskhl_21d"].median(),
    }
    report["high_low_spread_median_by_size_grp"] = {
        str(s): g["bidaskhl_21d"].median()
        for (s,), g in e.sort("size_grp").group_by("size_grp", maintain_order=True)}
    check(rank_corr > 0.3, f"High-low spread unrelated to the quoted spread: {rank_corr}")
    # Sanity: the value-weighted beta of the market must be close to 1.
    b = e.filter(pl.col("beta_252d").is_not_null()).group_by("yyyymm").agg(
        ((pl.col("me") * pl.col("beta_252d")).sum() / pl.col("me").sum()).alias("vw_beta"))
    report["vw_beta"] = {"mean": b["vw_beta"].mean(), "min": b["vw_beta"].min(), "max": b["vw_beta"].max()}
    check(0.95 < b["vw_beta"].mean() < 1.05, f"Value-weighted beta far from 1: {report['vw_beta']}")
    check(report["coverage_eligible_from_1963"]["rvol_252d"]["me"] > 0.9, "Low volatility coverage")


def main() -> None:
    report: dict = {"script": "scripts/data_cleaning/9_crsp_daily_agg.py", "inputs": {}}
    panel, run_id = read_verified(PANEL, PANEL_REPORT)
    report["inputs"][PANEL.name] = {"from_run": run_id}
    ff = read_french_daily(report)
    convert_daily(report)

    # NASDAQ flag of each stock-month, as in step 3 (exchange where the volume traded).
    active = (pl.col("tradingstatusflg") == "A").fill_null(False)
    exch = pl.when(active).then(pl.col("primaryexch")).otherwise(pl.col("primaryexch_last_active"))
    nasdaq = panel.select("permno", pl.col("yyyymm").alias("ym"),
                          (exch == "Q").fill_null(False).alias("is_nasdaq"))

    permnos = pl.scan_parquet(DAILY_MIN).select("permno").unique().collect()["permno"].sort()
    report["daily_stocks"] = permnos.len()
    counts = {k: 0 for k in COUNTS}
    parts = []
    step = -(-permnos.len() // N_BATCHES)
    for i in range(0, permnos.len(), step):
        lo, hi = permnos[i], permnos[min(i + step, permnos.len()) - 1]
        d = pl.scan_parquet(DAILY_MIN).filter(pl.col("permno").is_between(lo, hi)).collect()
        parts.append(month_sums(prepare_batch(d, ff, nasdaq, counts)))
    report["daily_counts"] = counts
    sums = pl.concat(parts)
    check(sums.select("permno", "ym").is_unique().all(), "A stock-month in two batches")
    out = window_stats(sums)
    report["rows"] = out.height

    check_direct(out, ff, nasdaq, report)
    checks(out, panel, report)
    out = out.drop("ret_cmp", "n_ret_raw")
    report["inputs"][DAILY_MIN.name] = sha256(DAILY_MIN)
    publish({PROCESSED / "crsp_daily_agg.parquet": out}, report, PROCESSED / "crsp_daily_agg_report.json")
    print(f"crsp_daily_agg: {counts['rows']:,} daily rows -> {out.height:,} stock-months. Report saved.")


if __name__ == "__main__":
    try:
        main()
    except CheckError as e:
        raise SystemExit(f"CHECK FAILED: {e}")
