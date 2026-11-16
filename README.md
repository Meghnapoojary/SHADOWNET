# SHADOWNET

**The Missing Link — AI-Assisted Cross-Case Financial Fraud Intelligence**

SHADOWNET is an investigative prototype designed to reveal potential relationships between separately reported financial incidents. It combines transaction-network analysis, explainable behavioural fingerprinting and unsupervised anomaly screening to help investigators explore connections that may not be visible when cases are examined individually.

## Project overview

Financial activity connected to coordinated fraud may be distributed across multiple cases, accounts and intermediaries. SHADOWNET analyses transaction records across cases to surface possible relationships and make the supporting evidence easier to inspect.

## Core capabilities

- **Direct account-link discovery:** identifies account identifiers shared across separate cases and shows the related transaction evidence.
- **Suspicious Pattern Fingerprinting:** represents each case using 16 behavioural features covering transaction flow, timing, amounts, account reuse and activity patterns. It compares cases that do not share an account identifier.
- **Transaction anomaly screening:** uses Isolation Forest to rank transactions that appear unusual relative to the loaded dataset.
- **Interactive relationship graph:** visualises cases, accounts and money movement, distinguishing direct identifier links from behavioural similarities.
- **Case and evidence exploration:** lets investigators inspect transaction flows, compare case fingerprints and review the evidence behind surfaced relationships.
- **Scenario analysis:** evaluates a new transaction sequence against the currently loaded cases.
- **CSV data analysis:** accepts structured transaction records for analysis.

## Analytical approach

SHADOWNET uses three complementary techniques:

1. **Graph analysis (NetworkX)** to construct transaction networks, trace money flows and identify shared account identifiers.
2. **Behavioural fingerprint comparison** using a transparent, hand-engineered 16-feature representation and weighted similarity scoring.
3. **Isolation Forest (scikit-learn)** for unsupervised, dataset-relative anomaly ranking.

Fingerprint similarity is a heuristic measure of behavioural resemblance. It is not a calibrated fraud probability or a trained fraud-classification result.

## Technology

- Python
- FastAPI
- NetworkX
- Pandas and NumPy
- scikit-learn (Isolation Forest)
- HTML, CSS and JavaScript
- SVG-based interactive visualisation

## Responsible use

SHADOWNET is a decision-support prototype. Its outputs are investigative leads for human review, not proof of fraud, common ownership or criminal activity. Similar transaction patterns can occur in legitimate activity, and shared identifiers require independent verification.

The bundled demonstration records use simulated data, fictional institutions and pseudonymous account identifiers. They are not private banking records or a real-world accuracy benchmark.
