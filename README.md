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

## Use of artificial intelligence

AI tools were used in this project as programming and auditing assistants,
under human direction. The authors defined and decided:

- the project workflow and the sequence of steps;
- the choice of models;
- the decision to freeze the strategy before a single out-of-sample test;
- the methodological rules on point-in-time data, delisted stocks, portfolio
  construction, trading costs and factor models.

They also specified the controls that each step had to pass, reviewed their
results, and validated each step before the next one began. Audit findings
were assessed on their merits and corrected before a step was closed. The
audit reports are kept with the project files. No AI tool chose the research
question, changed a rule after results were seen, or decided what to report.
The text of this report was written with the assistance of AI tools, under the
supervision of the authors, who reviewed it and take full responsibility for
its content.
