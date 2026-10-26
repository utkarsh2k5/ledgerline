<p align="center">
  <img src="docs/banner.png" alt="Ledgerline: pension performance reporting that shows its working" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-17324d" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/FastAPI-backend-17324d" alt="FastAPI">
  <img src="https://img.shields.io/badge/React%20%2B%20TypeScript-frontend-17324d" alt="React + TypeScript">
  <img src="https://img.shields.io/badge/tests-60%20passing-0b7a3e" alt="60 tests passing">
  <img src="https://img.shields.io/badge/Postgres%20%7C%20SQLite-supported-2a78d6" alt="Postgres and SQLite">
  <img src="https://img.shields.io/badge/license-MIT-8a8984" alt="MIT license">
</p>

<p align="center">
  <b><a href="#try-it">Live demo</a></b> &nbsp;·&nbsp;
  <a href="#what-it-does">What it does</a> &nbsp;·&nbsp;
  <a href="#the-reports-it-produces">Sample reports</a> &nbsp;·&nbsp;
  <a href="#how-its-built">How it's built</a> &nbsp;·&nbsp;
  <a href="docs/DEVLOG.md">Dev log</a>
</p>

---

Investment consultants who look after **defined benefit (DB) pension schemes** send trustees a performance report every quarter. Most of the work isn't the analysis. It's chasing numbers that don't agree, pasting them into Word and PowerPoint, and then answering *"where did this figure come from?"*

Ledgerline is my attempt at automating that properly. It takes the raw files (custodian valuations, fund manager packs, index returns, the actuary's cashflows, a gilt curve), reconciles them, explains performance, and produces the report in Word, PowerPoint and an interactive web version. **Every number in the output can be traced back to the spreadsheet cell it came from.**

<p align="center">
  <img src="docs/gifs/lineage.gif" alt="Clicking a figure to trace it back to the custodian's file" width="88%">
  <br><sub>Click any figure, follow it down to the row in the custodian's CSV.</sub>
</p>

> The scheme, its managers and all data are made up (the generator is in `backend/app/seed`). The data has deliberate problems in it so the reconciliation has something to catch.

## By the numbers

| | |
|---:|:---|
| **216** | fund-months reconciled between custodian and managers. **6** differences found, **5** big enough to block the report |
| **973** | figures computed per quarter, each with its formula, inputs and source. **887** of them are stored with the quarterly report |
| **1.25 s** | to produce the full quarterly pack: 8-page Word report, 17-slide deck and interactive HTML |
| **0.2 s** | for all analytics: returns, risk, attribution, funding position and stress tests |
| **8 ms** | for a 10,000-path Monte Carlo of the funding ratio (vectorised NumPy) |
| **0.0 bps** | unexplained in attribution after Carino linking (a plain sum leaves a gap, shown in the app) |
| **60** | automated tests, including 4 property-based tests that check ~460 random portfolios per run |
| **2** | databases it's tested on (SQLite, Postgres). The same data gives the same report fingerprint on both |

<sub>Timings measured in a small cloud container; your laptop will probably be faster.</sub>

## What it does

### 1. Checks the data before trusting it

Real source files are messy: `(0.40)` for negatives, `"1.23%"` stored as text, `n/a`, title rows above the header, months written as `Oct-23`. Each source has an adapter that cleans it and a data contract that rejects anything wrong, row by row. Uploads are versioned by a hash of the cleaned data, so re-saving the same file isn't a new version, and nothing is ever overwritten.

<p align="center"><img src="docs/gifs/data-contracts.gif" alt="A broken file is rejected with row-level errors, then a correction clears two differences" width="88%"></p>

### 2. Reconciles custodian vs manager

The custodian's valuations give one return (Modified Dietz); the fund manager reports another. Within 5 bps they match. Above 25 bps, or if a figure is missing, the report is blocked until someone decides which is right and writes down why. A corrected file supersedes old differences automatically.

<p align="center"><img src="docs/screenshots/03-reconciliation.png" alt="Reconciliation screen" width="88%"></p>

### 3. Explains performance with attribution that adds up

Brinson-Fachler splits the fund's relative return into **allocation** (holding more or less of an asset class than the strategy) and **selection** (each manager vs its own benchmark). Monthly effects don't simply add up over a year because returns compound, so they're linked with the **Carino** or **GRAP** method. The app lets you switch to a naive sum to see the gap it leaves.

<p align="center"><img src="docs/gifs/attribution.gif" alt="Switching between naive sum and Carino linking" width="88%"></p>

### 4. Writes the commentary with AI, then fact-checks it

Gemini drafts the trustee commentary from a sheet of computed figures. Before it's used, a verifier checks **every number at the precision written**, any explicit signs, whether "outperformed" or "lagged" matches the actual sign, and surplus/deficit claims. A failed draft gets one retry with the errors fed back; after that a rule-based paragraph is used instead. Nothing unchecked reaches the report.

```text
Draft 1  "…returned 4.67%, ahead of the benchmark return of 4.32% by 0.25%."
         ✗ '4.67%' does not match any computed figure at the precision written
         ✗ '0.25%' is described as positive but the fund's 3-month excess return is negative
Draft 2  "…returned 4.06%, behind the benchmark return of 4.32% by 0.25%."   ✓ verified
```

### 5. Tracks the funding position

For a DB scheme, returns only matter relative to the pensions promised. Ledgerline bootstraps a zero curve from gilt par yields, values the liabilities, and works out the funding ratio, liability duration, PV01 and how much of the interest-rate risk is hedged. It also runs stress tests (rates ±1%, equities −20%) and a 10-year Monte Carlo.

<p align="center"><img src="docs/screenshots/06-funding.png" alt="Funding position, stress tests and Monte Carlo fan chart" width="88%"></p>

### 6. Generates reports from a YAML spec, and can prove they're reproducible

A report layout is a YAML file listing sections and figure ids, so a new client format is a new file rather than new code. The same intermediate document renders to Word, PowerPoint and HTML. Each report gets a content fingerprint. **"Re-run from today's data"** rebuilds it and either confirms it's identical or lists exactly which figures moved.

<p align="center"><img src="docs/screenshots/09-reports.png" alt="Reports page" width="88%"></p>

## The reports it produces

These are real outputs from `python -m app.cli demo`, in [`sample_output/`](sample_output/).

**Word** (8 pages)
<p align="center"><img src="docs/screenshots/12-word-report.png" alt="Generated Word report" width="100%"></p>

**PowerPoint** (17 slides)
<p align="center"><img src="docs/screenshots/13-powerpoint-report.png" alt="Generated PowerPoint deck" width="100%"></p>

**Interactive HTML**: a single file a trustee can open in a browser and click to trace any figure.
<p align="center"><img src="docs/screenshots/14-interactive-html-report.png" alt="Interactive HTML report with lineage panel" width="88%"></p>

<details>
<summary><b>More screenshots</b></summary>
<br>

| | |
|---|---|
| ![Start page](docs/screenshots/01-start-page.png) | ![Start page, dark](docs/screenshots/01b-start-page-dark.png) |
| ![Overview](docs/screenshots/02-overview.png) | ![Overview, dark](docs/screenshots/02b-overview-dark.png) |
| ![Lineage](docs/screenshots/07-lineage-trace.png) | ![Lineage, dark](docs/screenshots/07b-lineage-dark.png) |
| ![Attribution](docs/screenshots/04-attribution.png) | ![Naive sum residual](docs/screenshots/05-attribution-naive-sum.png) |
| ![Funding, dark](docs/screenshots/06b-funding-dark.png) | ![Attribution, dark](docs/screenshots/04b-attribution-dark.png) |
| ![Validation errors](docs/screenshots/08-data-validation.png) | ![Audit trail](docs/screenshots/10-audit-trail.png) |
| ![Mobile start page](docs/screenshots/11-mobile-start.png) | ![Mobile](docs/screenshots/11-mobile.png) |

</details>

## Light and dark

The whole app, charts included, has a light and a dark theme. It follows your system setting and remembers if you switch.

<p align="center"><img src="docs/light-dark.png" alt="The overview page in light and dark mode" width="88%"></p>

## Try it

### Live demo

**Live:** `https://ledgerline.onrender.com` *(update after deploying)*. It runs on a free instance, so the first load after a quiet spell takes about a minute, and the demo data resets on every restart.

There's no sign-up or password. The start page has three buttons, one per role, and you can switch roles from the sidebar at any time:

| Role | What it can do |
|---|---|
| **Analyst** (start here) | Upload files, resolve data differences, generate reports |
| **Admin** | Everything above, plus release a report while differences are still open (it gets a warning banner) |
| **Trustee** | Read-only: dashboards, tracing figures, downloading finished reports |

<p align="center"><img src="docs/screenshots/01-start-page.png" alt="Start page with one-click role access" width="88%"></p>

**Things to try:** click a headline figure; upload `data/sample/examples_with_errors/custodian_with_errors.csv` on the Data page; upload `custodian_correction_PRP_2026-07.csv` and watch two differences disappear; resolve the rest; generate a report and hit *Re-run from today's data*.

### Deploy your own (free, ~10 minutes)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/utkarsh2k5/ledgerline)

1. Fork or push this repo to GitHub.
2. Get a free Gemini API key at [Google AI Studio](https://aistudio.google.com/apikey).
3. On [Render](https://render.com): **New → Blueprint**, pick the repo. `render.yaml` sets everything up and asks for `GEMINI_API_KEY`. Paste the key there, **not** in the code.
4. Wait for the build, then open the URL.

The root `Dockerfile` builds the React app and serves it from FastAPI, so it's one free web service. The free Gemini tier is enough: each report makes one call (two if the first draft fails the check). If the quota runs out, reports still generate with the rule-based commentary and the reason is logged.

### Run it locally

```bash
# backend (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m app.seed
uvicorn app.main:app --reload                         # API docs at http://localhost:8000/docs

# frontend (Node 18+), in a second terminal
cd frontend
npm install
npm run dev                                           # http://localhost:5173
```

Open http://localhost:5173 and pick a role. One-click role access is controlled by `DEMO_MODE` (on by default); turn it off for anything that isn't a demo.

To use Gemini locally: `cp backend/.env.example backend/.env`, set `AI_PROVIDER=gemini` and `GEMINI_API_KEY`. Without a key it runs fully offline. Setting `AI_PROVIDER=mock-hallucinate` makes the first draft deliberately wrong, so you can watch the fact-checker reject it.

**Full stack with Postgres and a separate worker:** `docker compose up --build`, then open http://localhost:8080.

## How it's built

```mermaid
flowchart LR
  subgraph Sources
    C[Custodian CSV]
    M[Manager Excel]
    B[Benchmarks]
    A[Actuary cashflows]
    Y[Gilt curve]
  end
  Sources --> AD[Adapters + data contracts] --> V[(Versioned datasets)]
  V --> R[Reconciliation] --> G[Golden returns]
  G --> AN[Analytics: returns, risk,<br/>Brinson-Fachler + Carino,<br/>funding & stress]
  AN --> FB[(Facts: value + formula<br/>+ inputs + source)]
  FB --> AI[Gemini draft] --> VF{Fact-checker}
  VF -- pass --> IR
  VF -- fail twice --> T[Rule-based text] --> IR
  SPEC[YAML spec] --> IR[Report document + fingerprint]
  IR --> W[Word] & P[PowerPoint] & H[HTML]
```

| Layer | Tools |
|---|---|
| API | FastAPI, Pydantic, JWT auth with analyst / admin / viewer roles |
| Data | SQLAlchemy 2, PostgreSQL or SQLite, Pandas |
| Maths | NumPy, SciPy (IRR), hand-written attribution, curve bootstrapping and Monte Carlo |
| Documents | python-docx, python-pptx, matplotlib, Jinja2 |
| AI | Gemini REST API behind a small provider interface (swappable), plus an offline mock |
| Frontend | React 18, TypeScript, React Router, Chart.js, plain CSS |
| Quality | pytest, Hypothesis, GitHub Actions on SQLite and Postgres |
| Ops | Docker, docker-compose, Render blueprint |

**A few decisions worth explaining**

- **Numbers are never passed around bare.** Everything the analytics produce is a *fact* with an id, value, formula, inputs and sources. Lineage, report diffs, the fingerprint and the AI fact-checker all come from that one idea.
- **Fingerprint the content, not the file.** Word and PowerPoint files embed timestamps, so comparing bytes is useless. The fingerprint hashes the report's structure plus every displayed value.
- **Job queue in the database, not Celery + Redis.** A few report jobs a day doesn't justify another service. Postgres `FOR UPDATE SKIP LOCKED` lets several workers share the queue safely.
- **The LLM never decides a number.** It rewrites a list of computed figures into prose, and the output is checked mechanically.

The [dev log](docs/DEVLOG.md) has the problems I hit along the way, like a date parser that read `Oct-23` as the year 1 and a hedge ratio stuck at 99.9%, and what changed because of them.

## Tests

```bash
cd backend && pytest                                            # 60 tests, ~25 s
TEST_DATABASE_URL=postgresql+psycopg://user:pass@host/db pytest # same suite on Postgres
```

- **Property-based:** attribution effects add up to fund minus benchmark for any portfolio; Carino- and GRAP-linked effects add up to the compounded difference over 1–24 months; reconciliation flags a difference if and only if it's over tolerance.
- **Known answers:** a textbook attribution example, Modified Dietz, par bonds pricing at 100 on the bootstrapped curve, a fully hedged scheme not moving when rates do.
- **Fact-checker:** invented numbers, wrong precision, wrong signs, wrong direction words and false surplus claims are all caught; a model that keeps getting it wrong always ends in the fallback.
- **End to end:** blocked report → upload a correction → resolve → generate → open the Word and PowerPoint files and find the right figures → re-run is identical → restated data is detected.

## Project layout

```
backend/app/
  ingestion/   adapters for each file type, data contracts, versioned loader, real-data fetchers
  recon/       custodian vs manager reconciliation, resolutions, golden-source returns
  analytics/   returns & risk, attribution, facts/lineage, the engine that builds them
  funding/     curve bootstrap, liability valuation & stress tests, Monte Carlo
  ai/          Gemini / offline providers, commentary prompt, fact-checker
  reporting/   YAML specs, report document + fingerprint, Word / PowerPoint / HTML renderers
  jobs/        database job queue and worker
  api/         REST endpoints
backend/report_specs/   quarterly_trustee_report.yaml, trustee_summary.yaml
frontend/src/           React app
data/sample/            generated source files, a correction and a deliberately broken file
sample_output/          reports from the demo run
docs/                   screenshots, GIFs, dev log, fact catalogue
```

## What it doesn't do (yet)

- Liability cashflows come from the actuary as an input; there's no membership modelling. The Monte Carlo uses first-order duration approximations and is labelled as illustrative.
- Attribution is by mandate / asset class, not individual securities, and there's no currency attribution.
- The fact-checker handles numbers, signs, direction and surplus/deficit claims. It can't judge a sentence like "because equities rallied".
- Demo authentication only; a real deployment would use the firm's single sign-on.

## License

MIT. Sample data is synthetic.

---

<p align="center">Made by <a href="https://github.com/utkarsh2k5">Utkarsh</a></p>
