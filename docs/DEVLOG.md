# Dev log

Things that broke or looked wrong while building Ledgerline, and what changed because of them. Kept because the fixes explain a lot of the code.

### Manager pack loaded as 216 "duplicates"
The manager Excel has month headers like `Oct-23`. pandas' date guesser read that as *23 October, year 1*, so every column landed on the same date and the uniqueness check rejected all 216 cells. Fix: try explicit month formats (`%b-%y`, `%b %Y`, `%Y-%m`, …) before falling back to guessing, and treat years outside 1990–2100 as invalid. (`ingestion/adapters.py`)

### Bad dates reported as "empty"
A row with `not a date` in the month column came back as *'month' is empty*, because the adapter turned it into NaT before the contract saw it. The adapter now keeps the raw text when parsing fails, so the error says *'month' is not a date: 'not a date'* and points at the row.

### Hedge ratio of 99.9% for a perfectly hedged scheme
Test case: one asset worth exactly the liabilities, with the same duration. Hedge ratio came out at 99.89%. Asset PV01 was `value × duration × 1bp` (symmetric), while liability PV01 used a one-sided bump, which picks up a little convexity. Switched the liability side to a central difference and the test passes at 100%. (`funding/liabilities.py`)

### Allocation effect of +3.3% in one year
The first version of the sample data never rebalanced, so after three years of equity gains the weights had drifted miles from strategy and the allocation effect was implausibly large. Added quarterly rebalancing halfway back to target, which is what schemes actually do. Allocation effect is now +0.21% over the year, which looks like a real scheme.

### Funding ratio projected to fall
The Monte Carlo median ended *below* today's funding ratio. Not a bug in the maths: an underfunded scheme paying the same pension out of assets and liabilities loses ratio mechanically. Real schemes have a deficit recovery plan, so the simulation now includes sponsor contributions that clear the deficit over 10 years. Median 10-year funding ratio went from 90% to about 97%.

### LLM commentary vs reproducibility
"Re-run this report and prove it's identical" doesn't work if the commentary is regenerated, because LLM output isn't deterministic. The re-run now reuses the stored commentary text but re-checks every number in it against the freshly computed figures. Side effect: if source data is restated, the check flags that the published commentary no longer matches, which is exactly what you'd want to know.

### Keeping the fact-checker from crying wolf
A naive "every number must be a computed figure" rule would reject "three years", "Q3 2026" or "100% funded". The verifier skips years, quarter labels, period lengths and the 100% threshold, and the prompt asks for periods in words. Numbers are compared *at the precision written*: "4.1%" matches 0.04064, "4.2%" doesn't. All of this is pinned down in `tests/test_verifier.py`.

### 409 response crashed with a TypeError
The "report blocked" response includes the open breaks, which contain `date` objects. FastAPI's `HTTPException` detail isn't run through the JSON encoder, so it threw. Wrapped it in `jsonable_encoder`.

### Pages crashing on first load
Every page fetched `/schemes/{id}/…` immediately, before the scheme list had loaded, so `scheme.id` was null. The layout now waits for the scheme before rendering pages.

### Fan chart drew the wrong band on top
Chart.js draws the *first* dataset on top, so the light 5–95% band covered the 25–75% band and the median. Fixed with explicit `order` on each dataset.

### Report polish
- Word: chart headings duplicated the section title; skipped when they match.
- matplotlib legends sat on top of bars; moved above the plot.
- PowerPoint: a paragraph after a chart became its own near-empty slide; it's now the subtitle on the chart slide.

### Fonts disappeared offline
The UI loaded IBM Plex from Google Fonts. Behind a proxy (or offline) it fell back to the system font. Font files are now bundled with `@fontsource`.

### SQLite and Postgres give the same fingerprint
Not a bug, but worth recording: running the full demo on both databases produces identical report fingerprints, which was a good end-to-end check that nothing depends on database-specific ordering or float handling.
