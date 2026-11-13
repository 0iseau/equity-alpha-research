# Reply to the team: descriptive statistics and references (2026-11-13)

## 1. Descriptive statistics by decade (section Data)

Output of `scripts/reports/descriptive_stats.py`, run as sent, on
`data/processed/crsp_panel_acc.parquet`. Nothing was written or changed.

| Decade | Months | Stocks per month | EW excess return | EW volatility | VW excess return | VW volatility |
|---|---|---|---|---|---|---|
| 1960s | 84 | 2077 | 11.98 | 17.48 | 3.73 | 11.79 |
| 1970s | 120 | 4037 | 8.29 | 24.07 | 2.54 | 16.91 |
| 1980s | 120 | 5549 | 3.94 | 19.14 | 7.21 | 17.03 |
| 1990s | 120 | 6550 | 12.61 | 17.02 | 13.10 | 13.65 |
| 2000s | 120 | 5049 | 6.76 | 23.97 | -1.58 | 16.62 |
| 2010s | 120 | 3716 | 10.97 | 16.66 | 13.45 | 12.89 |
| 2020s | 71 | 3983 | 6.66 | 24.89 | 12.91 | 17.94 |

Returns and volatilities in % per year (excess return of month t+1).

To say under the table:

- A decade is the decade of the **formation month** t; the return is the one
  of t+1. The 1960s start in January 1963 (84 months) and the 2020s end with
  the formation month November 2025 (71 months): 755 months in all.
- "Stocks per month" counts the eligible stocks **that have a return in the
  following month** (4,707 eligible stock-months of 3,449,977 do not). The
  mean number of eligible stocks is the same to within 6 stocks: 2,077, 4,043,
  5,551, 6,550, 5,049, 3,716 and 3,978.
- Check made here, not by the script: the value-weighted return of this table
  has a correlation of 0.99999 with the market factor of Ken French over the
  755 months, and the same mean by decade to within 0.1 point (3.73, 2.54,
  7.23, 13.10, −1.56, 13.46 and 13.00 for Ken French).

## 2. References

**Bibliographic details: checked on Crossref on 2026-11-13** (title, journal,
volume, issue, pages, DOI).

| Reference | Details |
|---|---|
| Avramov, D., Cheng, S., and Metzker, L. (2023) | "Machine Learning vs. Economic Restrictions: Evidence from Stock Return Predictability." *Management Science*, 69(5), 2587–2619. doi:10.1287/mnsc.2022.4449 |
| Corwin, S. A., and Schultz, P. (2012) | "A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices." *The Journal of Finance*, 67(2), 719–760. doi:10.1111/j.1540-6261.2012.01729.x |
| Ferson, W. E., and Schadt, R. W. (1996) | "Measuring Fund Strategy and Performance in Changing Economic Conditions." *The Journal of Finance*, 51(2), 425–461. doi:10.1111/j.1540-6261.1996.tb02690.x |
| Gu, S., Kelly, B., and Xiu, D. (2020) | "Empirical Asset Pricing via Machine Learning." *The Review of Financial Studies*, 33(5), 2223–2273. doi:10.1093/rfs/hhaa009 |
| Hou, K., Xue, C., and Zhang, L. (2020) | "Replicating Anomalies." *The Review of Financial Studies*, 33(5), 2019–2133. doi:10.1093/rfs/hhy131 |
| Hou, K., Xue, C., and Zhang, L. (2015) | "Digesting Anomalies: An Investment Approach." *The Review of Financial Studies*, 28(3), 650–705. doi:10.1093/rfs/hhu068 |
| Hou, K., Mo, H., Xue, C., and Zhang, L. (2021) | "An Augmented q-Factor Model with Expected Growth." *Review of Finance*, 25(1), 1–41. doi:10.1093/rof/rfaa004 |
| Jensen, T. I., Kelly, B., and Pedersen, L. H. (2023) | "Is There a Replication Crisis in Finance?" *The Journal of Finance*, 78(5), 2465–2518. doi:10.1111/jofi.13249 |
| Jones, C. M. (2002) | "A Century of Stock Market Liquidity and Trading Costs." Working paper, Columbia University. SSRN, doi:10.2139/ssrn.313681 |
| McLean, R. D., and Pontiff, J. (2016) | "Does Academic Research Destroy Stock Return Predictability?" *The Journal of Finance*, 71(1), 5–32. doi:10.1111/jofi.12365 |
| Novy-Marx, R., and Velikov, M. (2016) | "A Taxonomy of Anomalies and Their Trading Costs." *The Review of Financial Studies*, 29(1), 104–147. doi:10.1093/rfs/hhv063 |
| Shumway, T. (1997) | "The Delisting Bias in CRSP Data." *The Journal of Finance*, 52(1), 327–340. doi:10.1111/j.1540-6261.1997.tb03818.x |
| Shumway, T., and Warther, V. A. (1999) | "The Delisting Bias in CRSP's Nasdaq Data and Its Implications for the Size Effect." *The Journal of Finance*, 54(6), 2361–2379. doi:10.1111/0022-1082.00192 |
| Scheuch, C., Voigt, S., Weiss, P., and Frey, C. (2024) | *Tidy Finance with Python.* 1st edition. Chapman and Hall/CRC. doi:10.1201/9781032684307 |
| Fama, E. F., and French, K. R. (2008) | "Dissecting Anomalies." *The Journal of Finance*, 63(4), 1653–1678. doi:10.1111/j.1540-6261.2008.01371.x (cited in the journal for NYSE breakpoints) |

Two things about the list:

- **Jones.** Crossref also lists an article with the same title and author in
  *Financial Management*, online on 2026-10-27 (doi:10.1111/fima.70074), with
  no volume or pages yet. If it is the published version, cite it instead of
  the working paper: to check on the journal's page.
- **Tidy Finance**: the middle initials of the authors were not checked.

## 3. What we make each paper say: **not checked in the papers**

Nobody has opened the articles for this note. The column "Status" is what is
known without reading them; each claim still has to be read in the paper by
whoever takes it.

| Reference | What the report says | Status |
|---|---|---|
| Hou, Xue and Zhang (2020) | "q-factors" | **Wrong reference.** The 2020 paper is "Replicating Anomalies" (in our project it supports NYSE breakpoints with value weights). The q-factor model is Hou, Xue and Zhang (2015); q5 is Hou, Mo, Xue and Zhang (2021). We do not use the q-factors: they are only named as not done. |
| Shumway (1997) | "delisting bias, imputation of −30 %" | **To check, and probably two papers.** The −30 % is the figure usually attributed to Shumway (1997) for NYSE and AMEX delistings for performance reasons; the −55 % for NASDAQ is usually attributed to Shumway and Warther (1999). Our journal already notes that the −30 % was never confirmed in the paper. |
| Avramov, Cheng and Metzker (2023) | "the gains of ML come mostly from small illiquid stocks and disappear with costs" | Plausible reading of the abstract; "disappear" may be too strong (the paper speaks of economic restrictions such as excluding microcaps and distressed stocks, and of high turnover). Our journal notes that they remove stocks below the NYSE 20th percentile of size; they do not use NYSE breakpoints on a forecast. |
| Corwin and Schultz (2012) | "spread estimator from high and low prices" | Matches the title. Check that our high-low column is their estimator (it comes from the JKP code). |
| Ferson and Schadt (1996) | "conditional regression" | Their conditioning variables are lagged public information. Ours is the share of the fund invested. Write "in the spirit of", not "the model of". |
| Gu, Kelly and Xiu (2020) | "trees and neural networks predict better than linear models" | Plausible reading of the abstract. They sort all stocks on the forecast and use a Huber loss; we use NYSE breakpoints and squared error (declared differences). |
| Jensen, Kelly and Pedersen (2023) | "most published factors replicate" | Plausible reading of the abstract. In the project the paper is used for its code and its list of 404 characteristics. |
| Jones (2002) | "commission series that stops in 2000" | Read on 2026-11-13 on the Columbia and NBER pages (journal, section 8.8); the end date is to confirm in the paper. |
| McLean and Pontiff (2016) | "anomaly returns fall after publication" | Plausible reading of the abstract. We must not write that this explains our result: a decline of predictability is **not measured** in the project. |
| Novy-Marx and Velikov (2016) | "high-turnover anomalies lose their profits after costs" | Plausible reading of the abstract; it is also the source for cost-mitigation rules such as a buy/hold buffer. |

## 4. The two other sources

**Commissions of 6 then 4 cents a share.** There is no verified source. It is
a **stress scenario set by us** before any result (journal, section 8.8), not
a data series, and it is not in the main result. Figures read on 2026-11-13,
none of them checked in a primary document: about 5 to 6 cents a share with a
traditional broker in 2000; a Greenwich Associates series of 4.7 cents in
2004, 4.0 in 2005 and 2.5 in 2017 (as reported by Markets Media). Suggested
wording: "a commission stress of 6 cents a share until 2004 and 4 cents
afterwards, an assumption of ours chosen above the institutional commission
rates reported in industry surveys". Cite a survey only if someone finds the
document.

**Course slides.** Suggested form: Goyal, A. (2026). *Trading costs.*
Lecture 3, Applied Investments, HEC Lausanne, University of Lausanne. Lecture
slides. The portfolio price impact formula is on slide 24, and the
coefficients (λ of 2.5, 1.5 and 1.0 for micro, small and large stocks, i.e.
25, 15 and 10 bp for an order of 1 % of the ADV) on slide 25. The exact form
required for course material is the professor's call.
