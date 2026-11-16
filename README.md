# SHADOWNET — AI-Assisted Cross-Case Financial Fraud Intelligence

**The Missing Link:** connect separately reported financial incidents through direct account evidence and suspicious behavioural fingerprints.

SHADOWNET is a runnable investigation prototype. It builds directed transaction networks, detects shared-account links between cases, compares disconnected cases using an explainable 16-feature behavioural fingerprint, and ranks unusual transaction records with an optional Isolation Forest screen. Investigators can inspect the evidence, trace a selected case's money flow, compare fingerprints and test a new transaction scenario.

> **Responsible-use boundary:** SHADOWNET generates investigative leads, not fraud verdicts. A similarity score is not a probability of fraud. A shared identifier must be independently validated. The bundled reference dataset is simulated, uses fictional institutions and pseudonymous account identifiers, and is not private banking data.

## What the prototype demonstrates

### 1. Cross-case direct relationship discovery
- Accounts are represented as nodes and transfers as directed, timestamped edges.
- Cases are linked when the same account identifier occurs in both case records.
- Each direct link includes the shared identifier, the transaction IDs in which it occurs in each case, and its role (source and/or beneficiary).
- A shared identifier is presented as evidence of a record-level overlap, not proof of common beneficial ownership.

### 2. Suspicious Pattern Fingerprinting — the key differentiator
Each case is represented by a 16-feature behavioural vector:

| Feature family | Signals |
|---|---|
| Flow topology | Split-source share, maximum fan-out, maximum fan-in, pass-through share, network density, chain depth |
| Transaction tempo | Short-gap/burst share, median inter-transaction gap, gap variation |
| Amount behaviour | Amount coefficient of variation, rounded-amount share, top-recipient concentration |
| Reuse and timing | Frequently reused account share, consolidation share, night-time share, weekend share |

The comparison uses fixed, visible feature weights that sum to 1.0 and feature-specific distance functions. Bounded ratios use absolute difference; count and dispersion features use decaying distance; time gaps are compared on a log scale. Two cases can receive a behavioural link only when **no shared account identifier is present**, each case has at least five transactions, and the score meets the configured 90/100 threshold.

A comparison exposes all feature-level similarity values, strongest aligning features, notable differences and sample-size context. The score is a heuristic resemblance measure, not a calibrated risk probability.

### 3. Isolation Forest transaction triage
- An unsupervised Isolation Forest ranks transaction records that are relatively unusual within the loaded dataset.
- The model uses transaction amount, local hour, day of week, source/target activity, source-account time gap and payment channel indicators.
- The displayed index is a within-dataset percentile ranking (0–100), not a fraud probability or labelled prediction.
- Screening is disabled below 25 transactions to avoid presenting a tiny sample as a meaningful model run.

### 4. Investigator workflow
- Review nine reference cases across nine fictional institutions.
- Open the cross-case relationship graph.
- Click a solid green line to inspect shared-account evidence, or a dashed amber line to inspect behavioural alignment and differences.
- Open a case and trace its account-level money flow.
- Compare any two cases in the fingerprint workspace.
- Add a new sequence in Scenario Lab and rank it against existing cases.
- Import a CSV following the sample schema.

## AI and analytical scope (important for evaluation)

SHADOWNET uses three distinct analytical mechanisms, and the demo should describe them accurately:

1. **Graph analysis (NetworkX):** deterministic graph construction, shared canonical-account discovery and directed money-flow tracing.
2. **Suspicious Pattern Fingerprinting:** a transparent, hand-engineered 16-feature representation and weighted similarity comparison. The score is a heuristic measure of behavioural resemblance; it is not a trained fraud classifier or calibrated probability.
3. **Anomaly triage (scikit-learn Isolation Forest):** an unsupervised model that ranks transactions by relative unusualness within the currently loaded dataset. It does not predict confirmed fraud.

The current prototype does not use an LLM or generative AI. Its value is explainable cross-case graph analysis and transparent pattern comparison, with an unsupervised ML component for triage.

## Demonstration validation

The Validation & Data Controls view runs four reproducible checks and displays the observed evidence for each: (1) known shared-account pair with transaction references; (2) disconnected high-match pair with no shared account IDs and a feature-alignment summary; (3) benign look-alike negative control that remains below threshold; and (4) a four-transaction scenario rejected by the five-transaction minimum. The synthetic alias workflow can be applied from the UI and inspected in the alias audit table and graph Evidence Inspector. Its operator/provenance fields are simulated and are **not externally authenticated**.

The bundled demo dataset contains 9 reported cases across 9 fictional institutions, 74 transactions and 83 pseudonymous account identifiers. On the default threshold of 90/100, the reference build surfaces 2 direct identifier-overlap relationships and 3 disconnected fingerprint relationships. These are fixture outputs, not real-world precision, recall, accuracy or fraud-detection rates.

## Architecture

```text
React-free HTML/CSS/JavaScript investigation UI
                  │ REST / JSON
                  ▼
             FastAPI service
                  │
       ┌──────────┼───────────┐
       ▼          ▼           ▼
  NetworkX    Fingerprint  Isolation Forest
  graph       comparison  transaction triage
       └──────────┼───────────┘
                  ▼
    Evidence-rich case / link / scenario APIs
                  │
                  ▼
       Interactive SVG investigation UI
```

The interface is a lightweight browser client served by FastAPI; no separate Node build is required. The graph uses SVG so the relationship types and money-flow directions remain directly inspectable.

## Run locally

For a click-by-click walkthrough of every navigation area, alias mapping, all four validation cases and the five-minute evaluator demo, see [`QUICK_START.md`](QUICK_START.md).

**Requirements:** Python 3.10 or newer.

### Windows (one-click launcher)

Double-click `start_shadownet.bat`. It creates a virtual environment, installs dependencies and starts the local server at `http://127.0.0.1:8000`.

For manual setup, use PowerShell:

```powershell
cd SHADOWNET
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

### macOS / Linux

```bash
cd SHADOWNET
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000`.

API documentation is available at `http://127.0.0.1:8000/docs`.

## Beginner quick start (Windows)

1. Extract the whole ZIP to a normal folder. Do not run it from the ZIP preview.
2. Double-click `start_shadownet.bat` and keep the black terminal window open.
3. The browser opens after the API health check succeeds. If it does not, visit `http://127.0.0.1:8000`.
4. Open **Validation & Data**.
5. For the easiest route, click **Load evaluator demo · 11 cases / 86 transactions**. This loads the included sample without using the file picker.
6. Click **Run all validations**. The four built-in checks should show 4/4.
7. To practise manual upload, choose `demo_csvs/07_evaluator_combined_with_low_sample.csv`, wait for the green Ready message, then click **Validate and analyse file**.

To check the project without reading error logs, stop the server with Ctrl+C and double-click `CHECK_SHADOWNET.bat`. It writes `SHADOWNET_DIAGNOSTIC_REPORT.txt` with a PASS/FAIL result for the dependencies, dataset, API, every bundled CSV, alias workflow and validation checks.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The Windows `CHECK_SHADOWNET.bat` runs the API/data smoke checks as well as the project test suite, and saves a report.

The test suite checks dataset validation, direct-link evidence and alias provenance, disconnected fingerprint matches, negative controls, minimum sample-size blocking, feature explanation, Isolation Forest execution, case detail APIs and new-scenario evaluation. The Validation & Data Controls view exposes the four required deterministic scenarios with observed evidence. The alias audit table displays the operator, original ID, canonical ID and source reference. The graph Evidence Inspector displays direct-link transaction evidence and all 16 fingerprint feature comparisons.

## CSV input schema

Required columns:

```text
transaction_id,case_id,bank,timestamp,source_account,target_account,amount
```

Optional columns (default to `unknown` if omitted):

```text
channel,device_id,ip_hash
```

- `transaction_id` must be unique across the uploaded dataset.
- Each `case_id` must map to one `bank` in the input file.
- Timestamps must be parseable ISO-8601 values. The bundled synthetic timestamps have no explicit offset and are interpreted as UTC by the application; for external datasets, include an explicit timezone offset.
- Amounts must be finite and positive.
- Self-transfers are rejected.
- Upload limit: 5 MB, 20,000 records and 250 cases.

### Upload troubleshooting

1. Start the app with `start_shadownet.bat` and open `http://127.0.0.1:8000`. Do not open `frontend/index.html` directly from File Explorer.
2. Extract the CSV demo ZIP first. Do not select the ZIP itself.
3. Select a transaction file such as `00_full_reference_9cases_74transactions.csv` or `07_evaluator_combined_with_low_sample.csv`.
4. Do **not** upload `DATASET_INDEX.csv`; it is only a catalogue of the files and does not contain transaction records.
5. The uploader checks the seven required column headers before sending the file and displays the missing columns if the schema is wrong.
6. Uploading replaces the active in-memory dataset. Use **Reset demo** to restore the bundled reference data.

For a direct cross-case link, the same canonical account identifier must appear in both case records. If a real-world institution tokenises the same account differently, a governed identity-resolution process would be required before SHADOWNET could compare those identifiers. The prototype does not infer that two different IDs are the same account.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Service and loaded-data status |
| GET | `/api/overview` | Counts, threshold and anomaly-screen status |
| GET | `/api/cases` | Case summaries and per-case signal aggregates |
| GET | `/api/cases/{case_id}` | Transactions, fingerprint and relationships |
| GET | `/api/links` | Direct and behavioural relationship records |
| GET | `/api/graph` | Case, account and transaction graph data |
| GET | `/api/anomalies` | Isolation Forest status and case ranking |
| GET | `/api/fingerprints/compare?case_a=...&case_b=...` | Explainable two-case comparison |
| POST | `/api/scenario/evaluate` | Compare a new transaction sequence with the loaded cases |
| POST | `/api/upload` | Validate and analyse a user-selected CSV upload |
| POST | `/api/load-demo-sample` | One-click load the bundled evaluator or reference CSV |
| POST | `/api/reset-demo` | Restore the reference dataset |
| GET | `/api/export/sample` | Download the example CSV schema and records |

## Deployment

The repository includes a `Dockerfile` and a Render Blueprint (`render.yaml`) for hosted deployment. Follow [`DEPLOY_TO_RENDER.md`](DEPLOY_TO_RENDER.md) for the click-by-click instructions. The service must use one application worker because the currently selected dataset is held in process memory. Uploading a CSV replaces the active dataset for that running process; it is not a multi-tenant data store. The public prototype has no authentication, so keep the hosted demo on the bundled synthetic data and never upload confidential financial information.

For a real institutional deployment, add authentication, role-based access control, per-tenant data isolation, encryption at rest and in transit, audit retention, secure identity mapping, rate limits, async jobs, and a governed model-validation programme. Do not upload confidential or personally identifiable financial data to this public prototype.

## Known limitations

1. The supplied records are simulated, not a bank-confirmed fraud dataset. Demo links illustrate intended analysis logic, not externally validated detection performance.
2. Direct account links depend on stable canonical account identifiers. Cross-bank tokenisation differences require an authorised identity-resolution layer.
3. Fingerprint weights and threshold are transparent heuristic settings, not learned parameters. They need validation against labelled, representative data before operational use.
4. Isolation Forest is unsupervised and dataset-relative. Its index is not a probability and can change when the data population changes.
5. A similar topology or transfer tempo can occur in legitimate activity. Investigators must review source documents and contextual evidence.
6. The application does not block payments, freeze accounts, identify people or declare criminal conduct.
7. Uploaded data replaces the active in-memory dataset in this single-process prototype. It is not designed for concurrent multi-user investigations.

## Demonstration

Follow `DEMO_SCRIPT.md` for the recommended five-minute walkthrough, including the alias-mapping demonstration, Evidence Inspector and all four validation scenarios. The built-in synthetic alias is explicitly labelled as a simulated operator-attestation workflow; it is not bank-verified evidence.

## Project layout

```text
SHADOWNET/
├── backend/
│   ├── main.py                 # FastAPI endpoints
│   └── engine.py               # Validation, graph analysis and fingerprint engine
├── data/
│   └── synthetic_transactions.csv
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── aurora-theme.css       # High-contrast Aurora Command Centre theme + motion
│   └── app.js
├── tests/
│   ├── test_engine.py
│   └── test_api.py
├── docs/
├── requirements.txt
├── Dockerfile
├── render.yaml
├── DEMO_SCRIPT.md
├── QUICK_START.md
├── .gitignore
├── Dockerfile
├── render.yaml
└── README.md
```
