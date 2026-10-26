# Fact catalogue

Every number Ledgerline can show is a *fact* with a stable id. Report specs refer to facts by id, and the builder refuses to render an id that doesn't exist. `{FUND}` is a mandate code (`GEQ`, `EME`, `DGF`, `PRP`, `CRD`, `LDI`) or `TOTAL`; `{P}` is a period (`3m`, `ytd`, `1y`, `3y`); `{YYYY-MM}` is a month.

| Fact id | Meaning | Built from |
|---|---|---|
| `ret.{FUND}.{YYYY-MM}` | Monthly return used for reporting | Custodian rows (Modified Dietz) or a resolved reconciliation break |
| `bench.{FUND}.{YYYY-MM}` | Monthly benchmark return | Benchmark file row |
| `wp.{FUND}.{YYYY-MM}` | Portfolio weight at start of month | Custodian opening market values |
| `wb.{FUND}` | Strategic (benchmark) weight | Scheme configuration |
| `ret.TOTAL.{YYYY-MM}` / `bench.TOTAL.{YYYY-MM}` | Total fund / benchmark monthly return | Σ weight × return |
| `perf.{FUND}.{P}.ret` / `.bench` / `.excess` | Period return, benchmark, relative return (annualised over 1y) | Chain-linked monthly facts |
| `risk.{FUND}.{3y|1y}.vol` / `.te` / `.ir` / `.sharpe` / `.maxdd` | Risk statistics | Monthly returns |
| `mv.{FUND}.end` | Closing market value | Custodian row |
| `alloc.{FUND}.actual` / `.deviation` | Actual weight and deviation from strategy | Market values, `wb.{FUND}` |
| `flows.TOTAL.{P}` | Net cash flow over the period | Custodian rows |
| `attr.{P}.{FUND}.allocation` / `.selection` / `.interaction` / `.total` | Brinson-Fachler effects, linked across months | Monthly returns, weights |
| `attr.{P}.TOTAL.*` | Totals of the above (sum exactly to the compounded excess return) | Mandate effects |
| `funding.liabilities` | Present value of projected benefits | Actuarial cashflows, bootstrapped curve |
| `funding.assets` / `.ratio` / `.surplus` | Funding position | Market values, liabilities |
| `funding.liab_duration` / `.liab_pv01` / `.asset_pv01` / `.hedge_ratio` | Interest-rate sensitivity and hedging | Curve, cashflows, mandate durations |
| `funding.stress.{i}.ratio` / `.change` | Stress-test results (0: rates −100bp, 1: +100bp, 2: equities −20%, 3: combined) | Shifted curve, shocked assets |
| `funding.sim.median_10y` / `.prob_full_10y` | Monte Carlo projection outputs | Simulation (seeded) |
| `recon.open_material` / `.open_minor` / `.overrides` | Reconciliation status | Break table |
