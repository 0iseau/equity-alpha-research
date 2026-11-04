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

Cleaning includes : 
- Units identification and differentiation
- Consistency in dates and missing data
- Price and return quality : inconsistencies
- Identities of equities : distinction organisation - security and links
- Entries, exits and bankruptcies
- Data horizons : annual, montly, ...
- Data definition (sense, obs. freq., ...)
- Distinguish duplicates, separate events, and conflicting values

## Data disponibility at different dates

RULE OF DISPONIBLITY
Attach flags to every data, differenciating their usage and rules.
- **availabilty rule** - when can we use the info ?
    - annual accounts : 6m lag
    - market close 
    - macro vintage
    - effective interval
    - event
- **role** - How de we use the info ?
    - identifier
    - universe (of availables at date t)
    - predictor ("x")
    - outcome ("y")
    - benchmark
    - execution_cost (bid, ask, ...)

QUALITY VERIFICATION
ALl datasets are processed after checking for these problems
**quality checks** - What needs attention in the info ?
    - missing (missing value != 0)
    - duplicate
    - conflict
    - ambiguous_link
    - source (what is used to compute other data)

For each value, we assign 1 flag from "availability" and "role" categories, defining their disponibility and usage. We then control the values through every quality check.
