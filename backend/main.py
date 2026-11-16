from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import (
    DEFAULT_THRESHOLD, DEFAULT_WEIGHTS, DataValidationError, SHADOWNETEngine,
    FEATURES, FEATURE_LABELS, read_csv_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "synthetic_transactions.csv"
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="SHADOWNET API",
    description="Explainable cross-case financial investigation prototype. Outputs are investigative leads, not fraud verdicts.",
    version="2.0.0",
)
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
_lock = RLock()
_aliases: list[dict[str, Any]] = []
_threshold = DEFAULT_THRESHOLD
_weights = DEFAULT_WEIGHTS.copy()
_data_mode = "SIMULATED REFERENCE DATA"
_active_frame: pd.DataFrame | None = None
_engine: SHADOWNETEngine


def _load_default_frame() -> pd.DataFrame:
    return pd.read_csv(DATA_FILE)


def _rebuild(frame: pd.DataFrame | None = None) -> None:
    global _engine, _active_frame
    if frame is not None:
        _active_frame = frame.copy()
    raw = _active_frame if _active_frame is not None else _load_default_frame()
    _engine = SHADOWNETEngine(raw, aliases=_aliases, threshold=_threshold, weights=_weights)


_rebuild()


def _translate_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


class ScenarioPayload(BaseModel):
    transactions: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class AliasPayload(BaseModel):
    institution: str = Field(min_length=2, max_length=120)
    account_id: str = Field(min_length=2, max_length=180)
    canonical_account_id: str = Field(min_length=2, max_length=180)
    attested_by: str = Field(min_length=2, max_length=120)
    source_reference: str = Field(min_length=3, max_length=240)


class SettingsPayload(BaseModel):
    threshold: float = Field(ge=50, le=100)
    weights: dict[str, float] | None = None


class DemoDatasetPayload(BaseModel):
    dataset: Literal["evaluator", "reference"] = "evaluator"


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
def health():
    with _lock:
        return {"status": "ok", "service": "SHADOWNET", "version": "2.0.0", "loaded": True, "data_mode": _data_mode}


@app.get("/api/overview")
def overview():
    with _lock:
        data = _engine.overview()
        data["data_mode"] = _data_mode
        data["link_count"] = data["direct_link_count"] + data["fingerprint_link_count"]
        data["weights"] = _weights
        return data


@app.get("/api/cases")
def cases():
    with _lock:
        return sorted(_engine.result.cases, key=lambda x: x["case_id"])


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str):
    with _lock:
        try:
            return _engine.case_detail(case_id)
        except DataValidationError as exc:
            raise _translate_error(exc)


@app.get("/api/cases/{case_id}/graph")
def case_graph(case_id: str):
    with _lock:
        try:
            return _engine.case_graph(case_id)
        except DataValidationError as exc:
            raise _translate_error(exc)


@app.get("/api/links")
def links(threshold: float | None = None):
    with _lock:
        try:
            return _engine.links(threshold)
        except DataValidationError as exc:
            raise _translate_error(exc)


@app.get("/api/graph")
def graph(threshold: float | None = None):
    with _lock:
        try:
            return _engine.graph(threshold)
        except DataValidationError as exc:
            raise _translate_error(exc)


@app.get("/api/fingerprints/compare")
def compare(case_a: str, case_b: str):
    with _lock:
        try:
            return _engine.compare(case_a, case_b)
        except DataValidationError as exc:
            raise _translate_error(exc)


@app.post("/api/scenario/evaluate")
def evaluate_scenario(payload: ScenarioPayload):
    with _lock:
        try:
            return _engine.evaluate_scenario(payload.transactions)
        except DataValidationError as exc:
            raise _translate_error(exc)


@app.get("/api/anomalies")
def anomalies():
    with _lock:
        return _engine.anomalies()


@app.get("/api/validation")
def validation():
    with _lock:
        data = _engine.validation_suite()
        data["dataset_mode"] = _data_mode
        return data


@app.get("/api/aliases")
def get_aliases():
    with _lock:
        return {"count": len(_engine.alias_audit), "items": _engine.alias_audit,
                "policy": "Only explicit operator-attested mappings with an operator and source reference are applied. The original ID must exist in the named institution in the active dataset. SHADOWNET does not independently authenticate the source or infer aliases from string similarity."}


@app.post("/api/aliases")
def add_alias(payload: AliasPayload):
    global _aliases
    with _lock:
        record = payload.model_dump()
        record["mapping_status"] = "operator_attested"
        # Require the original ID to exist in the named institution in the active dataset.
        source_rows = _engine.raw_frame[
            (_engine.raw_frame["bank"].astype(str).str.casefold() == record["institution"].casefold())
            & (
                (_engine.raw_frame["source_account"].astype(str) == record["account_id"])
                | (_engine.raw_frame["target_account"].astype(str) == record["account_id"])
            )
        ]
        if source_rows.empty:
            raise HTTPException(status_code=422, detail=(
                f"Account ID '{record['account_id']}' was not found in institution '{record['institution']}' "
                "in the currently loaded dataset. Load the matching transaction CSV first."
            ))
        if record["account_id"] == record["canonical_account_id"]:
            raise HTTPException(status_code=422, detail="Original account ID and canonical ID must be different.")
        # A source account in one institution must have a deterministic mapping.
        key = (record["institution"].casefold(), record["account_id"])
        for old in _aliases:
            if (old["institution"].casefold(), old["account_id"]) == key:
                if old["canonical_account_id"] != record["canonical_account_id"]:
                    raise HTTPException(status_code=409, detail="This institution/account pair already maps to a different canonical ID.")
                return {"status": "already_exists", "mapping": old}
        _aliases.append(record)
        try:
            _rebuild()
        except Exception as exc:
            _aliases.pop()
            _rebuild()
            raise _translate_error(exc)
        return {"status": "operator_attested_mapping_added", "mapping": record, "overview": _engine.overview()}


@app.get("/api/settings")
def get_settings():
    with _lock:
        return {
            "threshold": _threshold,
            "weights": _weights,
            "features": [{"key": key, "label": FEATURE_LABELS[key], "weight": _weights[key]} for key in FEATURES],
            "min_transactions": 5,
        }


@app.put("/api/settings")
def update_settings(payload: SettingsPayload):
    global _threshold, _weights
    with _lock:
        proposed_weights = _weights.copy()
        if payload.weights is not None:
            unknown = set(payload.weights) - set(FEATURES)
            if unknown:
                raise HTTPException(status_code=422, detail="Unknown fingerprint feature(s): " + ", ".join(sorted(unknown)))
            proposed_weights.update({k: float(v) for k, v in payload.weights.items()})
            if any(not (0 <= v <= 1) for v in proposed_weights.values()) or sum(proposed_weights.values()) <= 0:
                raise HTTPException(status_code=422, detail="Feature weights must be between 0 and 1, with a positive total.")
        _threshold = float(payload.threshold)
        _weights = proposed_weights
        _rebuild()
        return {"status": "updated", "threshold": _threshold, "weights": _weights,
                "note": "Threshold and feature weights are active immediately and trigger a full re-analysis."}


@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...)):
    global _engine, _data_mode, _active_frame
    filename = (file.filename or "upload.csv").lower()
    if not filename.endswith(".csv"):
        raise HTTPException(status_code=415, detail="Upload a CSV file.")
    raw = await file.read(5 * 1024 * 1024 + 1)
    if not raw:
        raise HTTPException(status_code=422, detail="The selected CSV is empty. Choose a transaction data file.")
    with _lock:
        try:
            frame = read_csv_bytes(raw)
            candidate = SHADOWNETEngine(frame, aliases=_aliases, threshold=_threshold, weights=_weights)
        except DataValidationError as exc:
            detail = str(exc)
            if "Missing required columns" in detail and ("purpose" in raw[:2048].decode("utf-8-sig", errors="ignore").lower() or "recommended_use" in raw[:2048].decode("utf-8-sig", errors="ignore").lower()):
                detail = ("This is the dataset index, not transaction data. Do not upload DATASET_INDEX.csv. "
                          "Choose 00_full_reference_9cases_74transactions.csv or "
                          "07_evaluator_combined_with_low_sample.csv from the extracted demo pack.")
            raise _translate_error(DataValidationError(detail))
        except Exception as exc:
            raise _translate_error(exc)
        _engine = candidate
        _active_frame = frame.copy()
        _data_mode = "UPLOADED DATA"
        return {"status": "analysed", "filename": file.filename, "overview": _engine.overview(),
                "links": len(_engine.result.direct_links) + len(_engine.result.fingerprint_links)}


@app.post("/api/load-demo-sample")
def load_demo_sample(payload: DemoDatasetPayload):
    """Load a bundled synthetic CSV from the project folder for a one-click demo."""
    global _engine, _data_mode, _active_frame, _aliases, _threshold, _weights
    filenames = {
        "evaluator": "07_evaluator_combined_with_low_sample.csv",
        "reference": "00_full_reference_9cases_74transactions.csv",
    }
    path = ROOT / "demo_csvs" / filenames[payload.dataset]
    if not path.is_file():
        raise HTTPException(status_code=500, detail=f"Bundled demo sample is missing: {path.name}")
    with _lock:
        try:
            frame = read_csv_bytes(path.read_bytes())
            candidate = SHADOWNETEngine(frame, aliases=[], threshold=DEFAULT_THRESHOLD, weights=DEFAULT_WEIGHTS)
        except Exception as exc:
            raise _translate_error(exc)
        _aliases = []
        _threshold = DEFAULT_THRESHOLD
        _weights = DEFAULT_WEIGHTS.copy()
        _active_frame = frame.copy()
        _engine = candidate
        _data_mode = "SIMULATED EVALUATOR DATA" if payload.dataset == "evaluator" else "SIMULATED REFERENCE DATA"
        summary = _engine.overview()
        summary["data_mode"] = _data_mode
        return {"status": "demo_sample_loaded", "dataset": payload.dataset,
                "filename": path.name, "overview": summary,
                "links": len(_engine.result.direct_links) + len(_engine.result.fingerprint_links),
                "note": "This is bundled fictional sample data. Loading it replaces the active dataset and clears session aliases/settings."}


@app.post("/api/reset-demo")
def reset_demo():
    global _data_mode, _aliases, _threshold, _weights, _active_frame
    with _lock:
        _aliases = []
        _threshold = DEFAULT_THRESHOLD
        _weights = DEFAULT_WEIGHTS.copy()
        _active_frame = _load_default_frame()
        _rebuild()
        _data_mode = "SIMULATED REFERENCE DATA"
        return {"status": "demo_restored", "overview": _engine.overview()}


@app.get("/api/export/sample")
def export_sample():
    return FileResponse(DATA_FILE, media_type="text/csv", filename="shadownet_synthetic_reference_data.csv")


@app.exception_handler(DataValidationError)
async def validation_exception_handler(request, exc: DataValidationError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})
