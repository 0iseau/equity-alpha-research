# Equity Alpha Research

Long-only strategy on US stocks built on machine-learning forecasts
(Applied Investments, HEC Lausanne, 2026).

**Result.** The strategy was frozen, then tested once out of sample on
1993–2025: no alpha. Net of trading costs, the alpha against the five
Fama-French factors and momentum is −5.09 % a year (t = −5.13).

| Where | What |
|---|---|
| `ProjectJournal.md` | What was done and why; results in sections 8.10 to 8.12 |
| `RobustnessJournal.md` | Robustness tests run after the test |
| `reports/` | Notes, tables and figures |
| `scripts/` | Code, one folder per step |
| `resources/strategy_freeze.json` | The frozen rules |

CRSP and Compustat data (WRDS) are not published; `data/` stays local.
