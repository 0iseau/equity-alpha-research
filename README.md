# Equity Alpha Research

Long-only strategy on US stocks (Applied Investments, HEC Lausanne).

```text
Project/
├── ProjectWorkflow.md   # Steps of the project
├── CleaningSpec.md      # Data cleaning specification
├── scripts/
│   ├── data_download/   # Download of public data (FRED, Ken French)
│   └── data_cleaning/   # Cleaning, one script per step
├── resources/           # Reference tables and data dictionary
└── data/                # Local data, not published
```

CRSP/Compustat data (WRDS) stay local and are not published.
FRED/ALFRED data are collected with:

```powershell
python scripts/data_download/download_public_data.py --end 2025-12-31
```
