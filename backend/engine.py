from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Iterable
import math

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

REQUIRED_COLUMNS = {
    "transaction_id", "case_id", "bank", "timestamp",
    "source_account", "target_account", "amount"
}
OPTIONAL_COLUMNS = {"channel", "device_id", "ip_hash"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000
MAX_CASES = 250
DEFAULT_THRESHOLD = 90.0
MIN_FINGERPRINT_TRANSACTIONS = 5

FEATURES = [
    "split_source_share", "max_fan_out", "max_fan_in", "pass_through_share",
    "network_density", "chain_depth", "rapid_burst_share", "median_gap_hours",
    "gap_variation", "amount_cv", "rounded_amount_share", "top_recipient_share",
    "reused_account_share", "consolidation_share", "night_share", "weekend_share",
]
FEATURE_LABELS = {
    "split_source_share": "Sources sending to multiple recipients",
    "max_fan_out": "Maximum outgoing branches",
    "max_fan_in": "Maximum incoming branches",
    "pass_through_share": "Accounts that both receive and send",
    "network_density": "Network connection density",
    "chain_depth": "Longest directed money-flow path",
    "rapid_burst_share": "Transfers occurring within short intervals",
    "median_gap_hours": "Median time between transfers",
    "gap_variation": "Variation in transfer intervals",
    "amount_cv": "Variation in transfer amounts",
    "rounded_amount_share": "Share of rounded transfer amounts",
    "top_recipient_share": "Largest recipient's share of inflows",
    "reused_account_share": "Accounts appearing in multiple transfers",
    "consolidation_share": "Accounts receiving from multiple sources",
    "night_share": "Transfers during 22:00–05:00",
    "weekend_share": "Transfers on weekends",
}
DEFAULT_WEIGHTS = {
    "split_source_share": 0.08, "max_fan_out": 0.06, "max_fan_in": 0.05,
    "pass_through_share": 0.08, "network_density": 0.04, "chain_depth": 0.07,
    "rapid_burst_share": 0.08, "median_gap_hours": 0.06, "gap_variation": 0.05,
    "amount_cv": 0.08, "rounded_amount_share": 0.04, "top_recipient_share": 0.07,
    "reused_account_share": 0.06, "consolidation_share": 0.06, "night_share": 0.06,
    "weekend_share": 0.06,
}


class DataValidationError(ValueError):
    pass


def _clean_string(value: Any, field: str, row_no: int) -> str:
    value = str(value).strip() if value is not None else ""
    if not value or value.lower() in {"nan", "none", "null"}:
        raise DataValidationError(f"Row {row_no}: '{field}' cannot be empty.")
    if len(value) > 180:
        raise DataValidationError(f"Row {row_no}: '{field}' is too long (max 180 characters).")
    return value


def validate_transactions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise DataValidationError("The transaction file contains no records.")
    if len(frame) > MAX_ROWS:
        raise DataValidationError(f"The file exceeds the {MAX_ROWS:,}-record limit.")
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise DataValidationError("Missing required columns: " + ", ".join(sorted(missing)))
    if len(frame.columns) > 40:
        raise DataValidationError("The file contains too many columns.")

    result = frame.copy()
    for col in REQUIRED_COLUMNS - {"amount", "timestamp"}:
        result[col] = [_clean_string(v, col, i + 2) for i, v in enumerate(result[col])]
    for col in OPTIONAL_COLUMNS:
        if col not in result.columns:
            result[col] = "unknown"
        result[col] = result[col].fillna("unknown").astype(str).str.strip().replace("", "unknown")

    if result["transaction_id"].duplicated().any():
        dupes = result.loc[result["transaction_id"].duplicated(), "transaction_id"].head(5).tolist()
        raise DataValidationError(f"Transaction IDs must be unique. Duplicate(s): {', '.join(dupes)}")
    bank_counts = result.groupby("case_id")["bank"].nunique()
    invalid_cases = bank_counts[bank_counts > 1].index.tolist()
    if invalid_cases:
        raise DataValidationError("Each case must map to one institution. Conflicting case(s): " + ", ".join(invalid_cases[:5]))
    if result["case_id"].nunique() > MAX_CASES:
        raise DataValidationError(f"The file exceeds the {MAX_CASES}-case limit.")

    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    if result["timestamp"].isna().any():
        bad = int(result["timestamp"].isna().sum())
        raise DataValidationError(f"{bad} timestamp(s) could not be parsed. Use ISO-8601 timestamps.")
    result["amount"] = pd.to_numeric(result["amount"], errors="coerce")
    if result["amount"].isna().any() or not np.isfinite(result["amount"].to_numpy(dtype=float)).all():
        raise DataValidationError("Amounts must be finite numeric values.")
    if (result["amount"] <= 0).any():
        raise DataValidationError("Amounts must be greater than zero.")
    if (result["source_account"] == result["target_account"]).any():
        raise DataValidationError("Self-transfers are not accepted in this prototype.")
    result["amount"] = result["amount"].astype(float)
    result["timestamp"] = result["timestamp"].dt.tz_convert("UTC")
    result = result.sort_values(["case_id", "timestamp", "transaction_id"]).reset_index(drop=True)
    return result


def read_csv_bytes(raw: bytes) -> pd.DataFrame:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise DataValidationError("Upload exceeds the 5 MB limit.")
    try:
        frame = pd.read_csv(StringIO(raw.decode("utf-8-sig")))
    except UnicodeDecodeError as exc:
        raise DataValidationError("CSV must be UTF-8 encoded.") from exc
    except Exception as exc:
        raise DataValidationError(f"Could not read CSV: {exc}") from exc
    return validate_transactions(frame)


def canonicalize_accounts(frame: pd.DataFrame, alias_entries: list[dict[str, Any]] | None = None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply only explicitly operator-attested, provenance-tagged institution/account aliases."""
    result = frame.copy()
    mapping: dict[tuple[str, str], str] = {}
    audit: list[dict[str, Any]] = []
    for entry in alias_entries or []:
        if str(entry.get("mapping_status", "")).lower() != "operator_attested":
            continue
        institution = str(entry.get("institution", "")).strip()
        account_id = str(entry.get("account_id", "")).strip()
        canonical_id = str(entry.get("canonical_account_id", "")).strip()
        attested_by = str(entry.get("attested_by", "")).strip()
        source_reference = str(entry.get("source_reference", "")).strip()
        if not all([institution, account_id, canonical_id, attested_by, source_reference]):
            continue
        mapping[(institution.casefold(), account_id)] = canonical_id
        audit.append({
            "institution": institution, "account_id": account_id,
            "canonical_account_id": canonical_id, "mapping_status": "operator_attested",
            "attested_by": attested_by, "source_reference": source_reference,
        })
    if not mapping:
        result["canonical_source"] = result["source_account"]
        result["canonical_target"] = result["target_account"]
        return result, audit

    def resolve(bank: str, account: str) -> str:
        return mapping.get((str(bank).casefold(), str(account)), str(account))

    result["canonical_source"] = [resolve(b, a) for b, a in zip(result["bank"], result["source_account"])]
    result["canonical_target"] = [resolve(b, a) for b, a in zip(result["bank"], result["target_account"])]
    return result, audit


def _longest_dag_path(graph: nx.DiGraph) -> int:
    if graph.number_of_edges() == 0:
        return 0
    try:
        # Condense strongly connected components first. This avoids an expensive
        # all-pairs reachability scan when a transaction network contains cycles.
        dag = nx.condensation(graph)
        lengths: dict[int, int] = {n: 0 for n in dag.nodes}
        for node in nx.topological_sort(dag):
            for nxt in dag.successors(node):
                lengths[nxt] = max(lengths[nxt], lengths[node] + 1)
        return max(lengths.values(), default=0)
    except (nx.NetworkXError, nx.NetworkXUnfeasible):
        return 0


def extract_fingerprint(case_frame: pd.DataFrame) -> dict[str, float]:
    frame = case_frame.sort_values("timestamp").copy()
    accounts = set(frame["canonical_source"]) | set(frame["canonical_target"])
    graph = nx.DiGraph()
    graph.add_nodes_from(accounts)
    for row in frame.itertuples(index=False):
        graph.add_edge(row.canonical_source, row.canonical_target)
    indeg = dict(graph.in_degree())
    outdeg = dict(graph.out_degree())
    n_accounts = max(1, len(accounts))
    sources_split = sum(1 for d in outdeg.values() if d > 1)
    passthrough = sum(1 for node in accounts if indeg.get(node, 0) > 0 and outdeg.get(node, 0) > 0)
    reused = sum(1 for node in accounts if indeg.get(node, 0) + outdeg.get(node, 0) > 1)
    consolidation = sum(1 for d in indeg.values() if d > 1)
    total_edges = max(1, graph.number_of_edges())
    density = nx.density(graph) if graph.number_of_nodes() > 1 else 0.0

    timestamps = frame["timestamp"].sort_values().reset_index(drop=True)
    gaps = timestamps.diff().dropna().dt.total_seconds().to_numpy() / 3600.0
    if len(gaps):
        median_gap = float(np.median(gaps))
        gap_cv = float(np.std(gaps) / max(np.mean(gaps), 1e-9))
        rapid_share = float(np.mean(gaps <= 2.0))
    else:
        median_gap, gap_cv, rapid_share = 0.0, 0.0, 0.0

    amounts = frame["amount"].to_numpy(dtype=float)
    amount_cv = float(np.std(amounts) / max(np.mean(amounts), 1e-9)) if len(amounts) else 0.0
    rounded = float(np.mean(np.isclose(np.mod(amounts, 100.0), 0.0, atol=0.01))) if len(amounts) else 0.0
    inflow = frame.groupby("canonical_target")["amount"].sum()
    top_recipient_share = float(inflow.max() / max(inflow.sum(), 1e-9)) if len(inflow) else 0.0
    hours = frame["timestamp"].dt.hour
    night_share = float(((hours >= 22) | (hours < 5)).mean())
    weekend_share = float((frame["timestamp"].dt.dayofweek >= 5).mean())

    return {
        "split_source_share": float(sources_split / max(1, len(outdeg))),
        "max_fan_out": float(max(outdeg.values(), default=0)),
        "max_fan_in": float(max(indeg.values(), default=0)),
        "pass_through_share": float(passthrough / n_accounts),
        "network_density": float(density),
        "chain_depth": float(_longest_dag_path(graph)),
        "rapid_burst_share": rapid_share,
        "median_gap_hours": median_gap,
        "gap_variation": gap_cv,
        "amount_cv": amount_cv,
        "rounded_amount_share": rounded,
        "top_recipient_share": top_recipient_share,
        "reused_account_share": float(reused / n_accounts),
        "consolidation_share": float(consolidation / n_accounts),
        "night_share": night_share,
        "weekend_share": weekend_share,
    }


def _feature_similarity(name: str, a: float, b: float) -> float:
    if name in {"max_fan_out", "max_fan_in", "chain_depth"}:
        return math.exp(-1.3 * abs(math.log1p(max(a, 0.0)) - math.log1p(max(b, 0.0))))
    if name in {"median_gap_hours", "gap_variation", "amount_cv"}:
        return math.exp(-1.5 * abs(math.log1p(max(a, 0)) - math.log1p(max(b, 0))))
    return math.exp(-2.5 * abs(a - b))


def compare_fingerprints(fp_a: dict[str, float], fp_b: dict[str, float], weights: dict[str, float] | None = None) -> dict[str, Any]:
    active_weights = weights or DEFAULT_WEIGHTS
    total_w = sum(float(active_weights.get(f, 0)) for f in FEATURES)
    if total_w <= 0:
        raise DataValidationError("At least one fingerprint feature weight must be positive.")
    details = []
    score_sum = 0.0
    for name in FEATURES:
        sim = _feature_similarity(name, float(fp_a.get(name, 0)), float(fp_b.get(name, 0)))
        weight = float(active_weights.get(name, 0)) / total_w
        contribution = sim * weight
        score_sum += contribution
        details.append({
            "feature": name, "label": FEATURE_LABELS[name],
            "value_a": round(float(fp_a.get(name, 0)), 4),
            "value_b": round(float(fp_b.get(name, 0)), 4),
            "similarity": round(sim * 100, 1),
            "weight": round(weight, 4),
            "weighted_contribution": round(contribution * 100, 2),
            "difference": round(abs(float(fp_a.get(name, 0)) - float(fp_b.get(name, 0))), 4),
        })
    details.sort(key=lambda x: x["weighted_contribution"], reverse=True)
    score = round(score_sum * 100, 1)
    return {
        "score": score,
        "features": details,
        "strongest_alignments": [x for x in details if x["similarity"] >= 90][:5],
        "notable_differences": sorted(details, key=lambda x: x["similarity"])[:5],
        "interpretation": "Heuristic behavioural resemblance; not a fraud probability or proof of common control.",
    }


@dataclass
class AnalysisResult:
    transactions: pd.DataFrame
    cases: list[dict[str, Any]]
    direct_links: list[dict[str, Any]]
    fingerprint_links: list[dict[str, Any]]
    fingerprints: dict[str, dict[str, float]]
    validation_errors: list[str]


class SHADOWNETEngine:
    def __init__(self, frame: pd.DataFrame, aliases: list[dict[str, Any]] | None = None, threshold: float = DEFAULT_THRESHOLD, weights: dict[str, float] | None = None):
        self.raw_frame = validate_transactions(frame)
        self.aliases = aliases or []
        self.threshold = float(threshold)
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        if any((not math.isfinite(float(v)) or float(v) < 0 or float(v) > 1) for v in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise DataValidationError("Feature weights must be finite values between 0 and 1, with a positive total.")
        if not 50 <= self.threshold <= 100:
            raise DataValidationError("Similarity threshold must be between 50 and 100.")
        self.frame, self.alias_audit = canonicalize_accounts(self.raw_frame, self.aliases)
        self.result = self._analyse()

    @classmethod
    def from_csv_bytes(cls, raw: bytes, aliases: list[dict[str, Any]] | None = None, threshold: float = DEFAULT_THRESHOLD):
        return cls(read_csv_bytes(raw), aliases, threshold)

    def _analyse(self) -> AnalysisResult:
        cases: list[dict[str, Any]] = []
        fingerprints: dict[str, dict[str, float]] = {}
        case_frames = {case_id: grp.copy() for case_id, grp in self.frame.groupby("case_id", sort=True)}
        for case_id, group in case_frames.items():
            fp = extract_fingerprint(group)
            fingerprints[case_id] = fp
            accounts = sorted(set(group["canonical_source"]) | set(group["canonical_target"]))
            cases.append({
                "case_id": case_id,
                "bank": str(group["bank"].iloc[0]),
                "transaction_count": int(len(group)),
                "account_count": len(accounts),
                "total_amount": round(float(group["amount"].sum()), 2),
                "first_seen": group["timestamp"].min().isoformat(),
                "last_seen": group["timestamp"].max().isoformat(),
                "fingerprint": fp,
            })

        account_cases: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for case_id, group in case_frames.items():
            for row in group.itertuples(index=False):
                alias_index = {
                    (str(a["institution"]).casefold(), str(a["account_id"])): a
                    for a in self.alias_audit
                }
                for role, account, raw_account in [
                    ("source", row.canonical_source, row.source_account),
                    ("beneficiary", row.canonical_target, row.target_account),
                ]:
                    alias_record = alias_index.get((str(row.bank).casefold(), str(raw_account)))
                    account_cases.setdefault(str(account), {}).setdefault(case_id, []).append({
                        "transaction_id": row.transaction_id,
                        "role": role,
                        "timestamp": row.timestamp.isoformat(),
                        "amount": round(float(row.amount), 2),
                        "institution": str(row.bank),
                        "raw_account_id": str(raw_account),
                        "canonical_account_id": str(account),
                        "alias_mapped": alias_record is not None,
                        "attested_by": alias_record.get("attested_by") if alias_record else None,
                        "source_reference": alias_record.get("source_reference") if alias_record else None,
                    })
        direct_links = []
        for account_id, case_map in sorted(account_cases.items()):
            case_ids = sorted(case_map)
            if len(case_ids) < 2:
                continue
            for i in range(len(case_ids)):
                for j in range(i + 1, len(case_ids)):
                    a, b = case_ids[i], case_ids[j]
                    direct_links.append({
                        "link_id": f"DIRECT::{a}::{b}::{account_id}",
                        "type": "direct", "case_a": a, "case_b": b,
                        "bank_a": case_frames[a]["bank"].iloc[0], "bank_b": case_frames[b]["bank"].iloc[0],
                        "shared_account_id": account_id,
                        "evidence_a": case_map[a], "evidence_b": case_map[b],
                        "explanation": f"The canonical account identifier {account_id} appears in both case records.",
                    })

        direct_pairs = {frozenset((x["case_a"], x["case_b"])) for x in direct_links}
        fingerprint_links = []
        case_ids = sorted(case_frames)
        for i, case_a in enumerate(case_ids):
            for case_b in case_ids[i + 1:]:
                if frozenset((case_a, case_b)) in direct_pairs:
                    continue
                acc_a = set(case_frames[case_a]["canonical_source"]) | set(case_frames[case_a]["canonical_target"])
                acc_b = set(case_frames[case_b]["canonical_source"]) | set(case_frames[case_b]["canonical_target"])
                if acc_a & acc_b:
                    continue
                tx_a, tx_b = len(case_frames[case_a]), len(case_frames[case_b])
                if min(tx_a, tx_b) < MIN_FINGERPRINT_TRANSACTIONS:
                    continue
                comparison = compare_fingerprints(fingerprints[case_a], fingerprints[case_b], self.weights)
                if comparison["score"] >= self.threshold:
                    fingerprint_links.append({
                        "link_id": f"FINGERPRINT::{case_a}::{case_b}",
                        "type": "fingerprint", "case_a": case_a, "case_b": case_b,
                        "bank_a": case_frames[case_a]["bank"].iloc[0], "bank_b": case_frames[case_b]["bank"].iloc[0],
                        "score": comparison["score"], "comparison": comparison,
                        "explanation": "No account identifier is shared. The cases meet the minimum sample-size rule and exceed the configured behavioural similarity threshold.",
                    })
        return AnalysisResult(self.frame, cases, direct_links, fingerprint_links, fingerprints, [])

    def overview(self) -> dict[str, Any]:
        return {
            "case_count": self.frame["case_id"].nunique(),
            "institution_count": self.frame["bank"].nunique(),
            "transaction_count": len(self.frame),
            "account_count": len(set(self.frame["canonical_source"]) | set(self.frame["canonical_target"])),
            "direct_link_count": len(self.result.direct_links),
            "fingerprint_link_count": len(self.result.fingerprint_links),
            "threshold": self.threshold,
            "min_transactions_for_fingerprint": MIN_FINGERPRINT_TRANSACTIONS,
            "alias_mapping_count": len(self.alias_audit),
            "anomaly_screen_available": len(self.frame) >= 25,
            "data_mode": "SIMULATED REFERENCE DATA" if self.frame["case_id"].astype(str).str.startswith("CASE-").all() else "UPLOADED DATA",
        }

    def links(self, threshold: float | None = None) -> list[dict[str, Any]]:
        if threshold is None or float(threshold) == self.threshold:
            return self.result.direct_links + self.result.fingerprint_links
        if not 50 <= float(threshold) <= 100:
            raise DataValidationError("Threshold must be between 50 and 100.")
        temp = SHADOWNETEngine(self.raw_frame, self.aliases, float(threshold), self.weights)
        return temp.result.direct_links + temp.result.fingerprint_links

    def compare(self, case_a: str, case_b: str) -> dict[str, Any]:
        fps = self.result.fingerprints
        if case_a not in fps or case_b not in fps:
            raise DataValidationError("Select two valid case IDs from the loaded dataset.")
        if case_a == case_b:
            raise DataValidationError("Choose two different cases to compare.")
        frame_a = self.frame[self.frame["case_id"] == case_a]
        frame_b = self.frame[self.frame["case_id"] == case_b]
        accounts_a = set(frame_a["canonical_source"]) | set(frame_a["canonical_target"])
        accounts_b = set(frame_b["canonical_source"]) | set(frame_b["canonical_target"])
        shared = sorted(accounts_a & accounts_b)
        comparison = compare_fingerprints(fps[case_a], fps[case_b], self.weights)
        eligible = min(len(frame_a), len(frame_b)) >= MIN_FINGERPRINT_TRANSACTIONS
        return {
            "case_a": case_a, "case_b": case_b,
            "transactions_a": len(frame_a), "transactions_b": len(frame_b),
            "shared_account_ids": shared,
            "has_direct_overlap": bool(shared),
            "fingerprint_eligible": eligible and not shared,
            "meets_threshold": eligible and not shared and comparison["score"] >= self.threshold,
            "threshold": self.threshold,
            "comparison": comparison,
        }

    def case_detail(self, case_id: str) -> dict[str, Any]:
        if case_id not in self.result.fingerprints:
            raise DataValidationError("Case not found.")
        group = self.frame[self.frame["case_id"] == case_id].copy().sort_values("timestamp")
        txs = []
        for r in group.itertuples(index=False):
            txs.append({
                "transaction_id": r.transaction_id, "timestamp": r.timestamp.isoformat(),
                "source_account": r.canonical_source, "target_account": r.canonical_target,
                "original_source": r.source_account, "original_target": r.target_account,
                "amount": round(float(r.amount), 2), "channel": r.channel,
            })
        return {
            "case_id": case_id, "bank": str(group["bank"].iloc[0]),
            "transaction_count": len(group), "total_amount": round(float(group["amount"].sum()), 2),
            "transactions": txs, "fingerprint": self.result.fingerprints[case_id],
        }

    def case_graph(self, case_id: str) -> dict[str, Any]:
        detail = self.case_detail(case_id)
        nodes: dict[str, dict[str, Any]] = {}
        edges = []
        for tx in detail["transactions"]:
            for account, role in [(tx["source_account"], "source"), (tx["target_account"], "beneficiary")]:
                nodes.setdefault(account, {"id": account, "label": account, "role": role})
            edges.append({
                "id": tx["transaction_id"], "source": tx["source_account"], "target": tx["target_account"],
                "amount": tx["amount"], "timestamp": tx["timestamp"], "channel": tx["channel"],
            })
        return {"case_id": case_id, "nodes": list(nodes.values()), "edges": edges}

    def graph(self, threshold: float | None = None) -> dict[str, Any]:
        link_records = self.links(threshold)
        nodes = [{"id": c["case_id"], "label": c["case_id"], "bank": c["bank"], "transactions": c["transaction_count"]} for c in self.result.cases]
        return {"nodes": nodes, "links": link_records}

    def anomalies(self) -> dict[str, Any]:
        if len(self.frame) < 25:
            return {"available": False, "reason": "At least 25 transactions are required for the prototype anomaly screen.", "items": []}
        df = self.frame.copy()
        temp = pd.DataFrame({
            "log_amount": np.log1p(df["amount"].astype(float)),
            "hour": df["timestamp"].dt.hour,
            "weekday": df["timestamp"].dt.dayofweek,
            "source_activity": df.groupby("canonical_source")["transaction_id"].transform("count"),
            "target_activity": df.groupby("canonical_target")["transaction_id"].transform("count"),
            "channel_code": df["channel"].astype("category").cat.codes,
        })
        scaler = RobustScaler()
        x = scaler.fit_transform(temp)
        model = IsolationForest(n_estimators=160, contamination="auto", random_state=42)
        model.fit(x)
        raw = -model.score_samples(x)
        ranks = pd.Series(raw).rank(pct=True).to_numpy() * 100
        items = []
        for idx, row in df.iterrows():
            items.append({
                "transaction_id": row["transaction_id"], "case_id": row["case_id"],
                "bank": row["bank"], "amount": round(float(row["amount"]), 2),
                "timestamp": row["timestamp"].isoformat(), "relative_unusualness_index": round(float(ranks[idx]), 1),
            })
        items.sort(key=lambda x: x["relative_unusualness_index"], reverse=True)
        return {"available": True, "method": "Isolation Forest", "interpretation": "Within-dataset relative unusualness ranking; not a probability of fraud.", "items": items[:25]}

    def evaluate_scenario(self, transactions: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(transactions, list) or not 1 <= len(transactions) <= 100:
            raise DataValidationError("Scenario must contain between 1 and 100 transactions.")
        case_id = "SCENARIO-INPUT"
        prepared = []
        for i, tx in enumerate(transactions, 1):
            prepared.append({
                "transaction_id": f"SCENARIO-TX-{i:03d}", "case_id": case_id,
                "bank": "Scenario Input", "timestamp": tx.get("timestamp"),
                "source_account": tx.get("source_account"), "target_account": tx.get("target_account"),
                "amount": tx.get("amount"), "channel": tx.get("channel", "unknown"),
                "device_id": tx.get("device_id", "unknown"), "ip_hash": tx.get("ip_hash", "unknown"),
            })
        scenario_frame = validate_transactions(pd.DataFrame(prepared))
        scenario_frame["canonical_source"] = scenario_frame["source_account"]
        scenario_frame["canonical_target"] = scenario_frame["target_account"]
        scenario_fp = extract_fingerprint(scenario_frame)
        comparisons = []
        for case in self.result.cases:
            case_id_existing = case["case_id"]
            result = compare_fingerprints(scenario_fp, self.result.fingerprints[case_id_existing], self.weights)
            comparisons.append({
                "case_id": case_id_existing, "bank": case["bank"], "score": result["score"],
                "comparison": result,
            })
        comparisons.sort(key=lambda x: x["score"], reverse=True)
        eligible = len(scenario_frame) >= MIN_FINGERPRINT_TRANSACTIONS
        return {
            "transaction_count": len(scenario_frame), "fingerprint_eligible": eligible,
            "minimum_required": MIN_FINGERPRINT_TRANSACTIONS,
            "threshold": self.threshold,
            "fingerprint": scenario_fp,
            "nearest_matches": comparisons[:5] if eligible else [],
            "message": "Scenario is eligible for behavioural comparison." if eligible else f"Add at least {MIN_FINGERPRINT_TRANSACTIONS - len(scenario_frame)} more transactions before the prototype compares this scenario.",
            "interpretation": "Similarity identifies resemblance for investigator review; it does not establish fraud or common control.",
        }

    def validation_suite(self) -> dict[str, Any]:
        ids = {c["case_id"] for c in self.result.cases}
        checks: list[dict[str, Any]] = []

        def add(name: str, expected: str, actual: str, passed: bool, detail: str,
                evidence: dict[str, Any] | None = None):
            checks.append({
                "name": name, "expected": expected, "actual": actual,
                "passed": bool(passed), "detail": detail, "evidence": evidence or {},
            })

        # These deterministic checks target the named demonstration fixtures.
        direct = next((
            link for link in self.result.direct_links
            if {link["case_a"], link["case_b"]} == {"CASE-101", "CASE-102"}
        ), None)
        direct_ok = bool(direct and direct.get("evidence_a") and direct.get("evidence_b"))
        direct_evidence = {}
        if direct:
            direct_evidence = {
                "case_pair": f'{direct["case_a"]} ↔ {direct["case_b"]}',
                "shared_account_id": direct["shared_account_id"],
                "transactions_a": [x["transaction_id"] for x in direct["evidence_a"]],
                "transactions_b": [x["transaction_id"] for x in direct["evidence_b"]],
                "evidence_rows": len(direct["evidence_a"]) + len(direct["evidence_b"]),
            }
        add(
            "Known shared-account pair", "Direct link with transaction evidence",
            "Direct link found" if direct_ok else "No direct link", direct_ok,
            "Checks that the same canonical account identifier is cited in both case records.",
            direct_evidence,
        )

        disconnected = self.compare("CASE-201", "CASE-202") if {"CASE-201", "CASE-202"} <= ids else None
        high_match = bool(disconnected and not disconnected["has_direct_overlap"] and disconnected["meets_threshold"])
        disconnected_evidence = {}
        if disconnected:
            cmp = disconnected["comparison"]
            disconnected_evidence = {
                "case_pair": "CASE-201 ↔ CASE-202",
                "shared_account_ids": disconnected["shared_account_ids"],
                "score": cmp["score"], "threshold": disconnected["threshold"],
                "transactions_a": disconnected["transactions_a"],
                "transactions_b": disconnected["transactions_b"],
                "top_alignments": [x["label"] for x in cmp["strongest_alignments"][:3]],
            }
        add(
            "Disconnected high-match pair", "Fingerprint link without shared IDs",
            f'Eligible high match ({disconnected["comparison"]["score"]}/100)' if high_match else "No qualifying high match",
            high_match,
            "Checks behavioural comparison only when the two cases share no canonical account IDs.",
            disconnected_evidence,
        )

        benign = self.compare("CASE-301", "CASE-302") if {"CASE-301", "CASE-302"} <= ids else None
        benign_rejected = bool(benign and not benign["has_direct_overlap"] and not benign["meets_threshold"])
        benign_evidence = {}
        if benign:
            benign_evidence = {
                "case_pair": "CASE-301 ↔ CASE-302",
                "shared_account_ids": benign["shared_account_ids"],
                "score": benign["comparison"]["score"],
                "threshold": benign["threshold"],
                "transactions_a": benign["transactions_a"],
                "transactions_b": benign["transactions_b"],
            }
        add(
            "Benign look-alike pair", "Below configured link threshold",
            f'Rejected below threshold ({benign["comparison"]["score"]}/100)' if benign_rejected else "Unexpectedly linked",
            benign_rejected,
            "A near-look-alike pair is a negative control; it should not create a relationship at the configured threshold.",
            benign_evidence,
        )

        low_sample = self._low_sample_gate_check()
        low_evidence = {"transactions_supplied": 4, "minimum_required": MIN_FINGERPRINT_TRANSACTIONS,
                        "nearest_matches_returned": 0}
        add(
            "Low-sample / no-link case", "Fingerprint comparison blocked below 5 transactions",
            low_sample["actual"], low_sample["passed"], low_sample["detail"], low_evidence,
        )
        return {
            "total": len(checks), "passed": sum(1 for x in checks if x["passed"]),
            "failed": sum(1 for x in checks if not x["passed"]), "checks": checks,
            "dataset_mode": "SIMULATED REFERENCE DATA" if ids and all(x.startswith("CASE-") for x in ids) else "UPLOADED DATA",
        }

    def _low_sample_gate_check(self) -> dict[str, Any]:
        low_sample_rows = [
            {"timestamp": f"2026-11-01T0{hour}:00:00Z", "source_account": f"LOW-S{idx}",
             "target_account": f"LOW-T{idx}", "amount": 100 + idx * 10, "channel": "UPI"}
            for idx, hour in enumerate([1, 2, 4, 7], 1)
        ]
        evaluated = self.evaluate_scenario(low_sample_rows)
        passed = not evaluated["fingerprint_eligible"] and not evaluated["nearest_matches"]
        return {
            "actual": "Blocked by minimum sample-size gate" if passed else "Unexpectedly eligible",
            "passed": passed,
            "detail": "A four-transaction scenario is evaluated and must be blocked because fingerprint comparison requires at least five transactions.",
        }
