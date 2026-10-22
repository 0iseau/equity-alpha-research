# FRED data snapshots

Six original FRED CSV responses are included here, without cleaning or aggregation.
They were retrieved on 2026-10-22 with observations bounded by 2025-12-31.
`manifest.json` records each source, retrieval time, SHA-256 hash and actual coverage.

These are **current revised histories**, not historical information sets. Later
revisions remain in the files even though observations stop in 2025. Use the local
ALFRED archives for historical signals; see [the data notes](../../README.md).
Run `python src/download_public_data.py` from the project root to download the full
collection into a new local run folder. It does not overwrite these fixed snapshots.

## Sources and attribution

Data obtained via FRED, Federal Reserve Bank of St. Louis, on 2026-10-22:

| File | Original source | FRED series |
| --- | --- | --- |
| VIXCLS_latest.csv | Chicago Board Options Exchange | [CBOE Volatility Index: VIX](https://fred.stlouisfed.org/series/VIXCLS) |
| T10Y3M_latest.csv | Federal Reserve Bank of St. Louis | [10-year minus 3-month Treasury yield](https://fred.stlouisfed.org/series/T10Y3M) |
| UNRATE_latest.csv | U.S. Bureau of Labor Statistics | [Unemployment rate](https://fred.stlouisfed.org/series/UNRATE) |
| INDPRO_latest.csv | Board of Governors of the Federal Reserve System (US) | [Industrial production](https://fred.stlouisfed.org/series/INDPRO) |
| CPIAUCSL_latest.csv | U.S. Bureau of Labor Statistics | [Consumer price index](https://fred.stlouisfed.org/series/CPIAUCSL) |
| NFCI_latest.csv | Federal Reserve Bank of Chicago | [National Financial Conditions Index](https://fred.stlouisfed.org/series/NFCI) |

Original VIX notice displayed by FRED: "Copyright, 2016, Chicago Board Options
Exchange, Inc. Reprinted with permission." FRED labels VIXCLS, T10Y3M and NFCI
"Copyrighted: Citation Required" and the three federal macro series
"Public Domain: Citation Requested". Attribution and source notices apply to the
data; inclusion here does not assign ownership of them to this project.
See the [FRED terms](https://fred.stlouisfed.org/legal/) and each linked series.

[BAA10Y](https://fred.stlouisfed.org/series/BAA10Y) is inventoried but its values
are not published: its series-specific Moody's notice requires prior written
consent for redistribution. Private CRSP/Compustat exports and complete ALFRED
vintage archives are not included in this folder.
