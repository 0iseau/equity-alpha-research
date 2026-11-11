# Project workflow - alpha discovery in long onyl US equities

## General workflow
Raw data -> Cleaning -> Data disponibility at different dates -> signals -> predictions -> porfolio building -> backtest with costs -> factor model(s) -> alpha estimation
-> stat tests and robustness -> strat. freeze and final oos test -> allocation decision

## Raw data

| Data source | Purpose in the project | Main contents |
|---|---|---|
| Monthly stock data (`crsp_ciz_monthly_stock.csv`) | Calculate monthly stock and portfolio returns. | Prices, returns, market capitalizations, trading volumes, dividends, other distributions |
| Daily stock data (`crsp_ciz_daily_stock.csv`) | Assess liquidity and estimate trading costs. | Prices, returns, trading volumes, bid and ask quotes, daily highs and lows |
| Security history (`crsp_ciz_security_history.csv`) | Identify which stocks were eligible for investment at each date. | Security identifiers, share types, exchanges, industries, trading status, effective dates |
| Delistings (`crsp_ciz_delistings.csv`) | Account for stocks that left the market and avoid survivorship bias. | Delisting dates, reasons, prices, payments, delisting returns |
| Annual financial statements (`ccm_fundamentals_annual.csv`) | Measure company characteristics and construct investment signals. | Fiscal year-end dates, assets, debt, cash, equity, sales, earnings, capital expenditures |
| CRSP–Compustat links (`ccm_link_history.csv`) | Match each company’s financial statements to the correct stock at each date. | Company and security identifiers, link types, link start and end dates |
| Monthly market indices (`crsp_ciz_monthly_market_indexes.csv`) | Compare portfolio returns with US equity market benchmarks. | Value-weighted and equal-weighted market returns, S&P Composite index levels and returns |
| FRED / ALFRED macroeconomic data (`data/raw/public/`) | Describe economic conditions using historical releases where available. | VIX, Baa–Treasury yield spread, 10-year–3-month Treasury spread, unemployment rate, industrial production, consumer price index, financial conditions index |

## Cleaning

Reference: Jensen, Kelly & Pedersen (2023) and Tidy Finance. Details in `CleaningSpec.md`.

Rules for every step:
- Raw data never changes
- Missing stays missing (missing != 0)
- Stop on any problem, no silent fix
- Each step saves a table and a check report

Steps:
1. **Monthly stock panel** - one row per stock and month, distributions in a separate table
2. **Delisting returns** - check the delisting month return is counted, once
3. **Eligible universe** - common US stocks on NYSE, AMEX, NASDAQ, judged at the formation date
4. **Size groups** - NYSE breakpoints, keep all sizes (micro-caps removed later only if costs exceed their alpha, rule fixed in advance)
5. **Excess returns** - return minus risk-free rate
6. **CRSP-Compustat links** - match each stock to its company accounts, within valid link dates
7. **Annual accounts** - one row per company and year, USD only, book equity
8. **Daily data** - monthly summaries: volatility, liquidity, spreads, beta
9. **Extreme values** - flag, do not delete

## Data disponibility at different dates

Rule: a signal formed at the end of month t only uses info known at that date. The return is measured in month t+1.

When can we use the info?
- **Market data** - at the end of the month
- **Annual accounts** - 6 months after fiscal year end, valid up to 18 months
- **Daily data** - summarised inside month t
- **Links and stock status** - only within their valid dates

How do we use the info?
- One data dictionary per table: meaning, unit, source, availability date, role(s)
- A variable can have several roles (e.g. market cap: universe, signal, weight)

Check:
- Automatic test: no data used before its availability date
