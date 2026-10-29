# Equity Alpha Research

This project studies long-only US stock portfolios for Applied Investments at HEC Lausanne.
We test whether simple trading rules can earn returns beyond those explained by market and factor exposure.
We also study risk, market regimes, and trading costs.

The monthly data audit is implemented in `src/audit_market_data.py`, with independent
real-data verification in `src/verify_market_audit.py`. Run offline checks with
`python -m unittest discover -s tests -v`. Audit outputs remain local under `results/`.
The current local protocol is `research_plan/CURRENT_AUDIT_PROTOCOL.md`; it supersedes
older data-permission restrictions. An audit completion is not a certification of
tradable strategy performance: unresolved payoffs and information timing are explicit.
