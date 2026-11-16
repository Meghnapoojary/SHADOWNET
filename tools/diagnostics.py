from __future__ import annotations
from pathlib import Path
import sys
import traceback
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

passed = 0
failed = 0

def check(label, fn):
    global passed, failed
    try:
        detail = fn()
        passed += 1
        print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))
    except Exception as exc:
        failed += 1
        print(f"[FAIL] {label} — {exc}")


def main() -> int:
    global failed
    print("SHADOWNET DIAGNOSTIC CHECK")
    print("=" * 58)
    print(f"Project folder: {ROOT}")

    required = [
        "backend/main.py", "backend/engine.py", "frontend/index.html",
        "frontend/app.js", "frontend/aurora-theme.css", "requirements.txt",
        "data/synthetic_transactions.csv", "start_shadownet.bat",
    ]
    for rel in required:
        check(f"Project file: {rel}", lambda rel=rel: "found" if (ROOT / rel).is_file() else (_ for _ in ()).throw(FileNotFoundError(rel)))

    def import_dependencies():
        import fastapi, uvicorn, pandas, networkx, sklearn, numpy, httpx
        return f"FastAPI {fastapi.__version__}; pandas {pandas.__version__}; NetworkX {networkx.__version__}"
    check("Python dependencies", import_dependencies)

    def unit_tests():
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError((result.stdout + "\n" + result.stderr)[-5000:])
        summary = (result.stdout + "\n" + result.stderr).strip().splitlines()[-1:]
        return summary[0] if summary else "unittest passed"
    check("Automated Python tests", unit_tests)

    node = shutil.which("node")
    if node:
        def js_syntax():
            result = subprocess.run([node, "--check", "frontend/app.js"], cwd=ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout)
            return "frontend/app.js syntax is valid"
        check("Frontend JavaScript syntax", js_syntax)
    else:
        print("[SKIP] Frontend JavaScript syntax — Node.js is not installed; the browser uses the app directly.")

    def source_dataset():
        import pandas as pd
        df = pd.read_csv(ROOT / "data/synthetic_transactions.csv")
        stats = (df.case_id.nunique(), df.bank.nunique(), len(df), len(set(df.source_account) | set(df.target_account)))
        if stats != (9, 9, 74, 83):
            raise AssertionError(f"expected (9 cases, 9 institutions, 74 transactions, 83 accounts), got {stats}")
        return "9 cases · 9 fictional institutions · 74 transactions · 83 distinct account IDs"
    check("Bundled reference data", source_dataset)

    try:
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        check("API health", lambda: f"HTTP {client.get('/api/health').status_code}" if client.get('/api/health').status_code == 200 else (_ for _ in ()).throw(RuntimeError("health endpoint did not return 200")))
        check("Built-in four validation scenarios", lambda: f"{client.get('/api/validation').json()['passed']}/4 passed" if client.get('/api/validation').json().get('passed') == 4 else (_ for _ in ()).throw(AssertionError(client.get('/api/validation').json())))

        def one_click_evaluator_load():
            response = client.post("/api/load-demo-sample", json={"dataset":"evaluator"})
            if response.status_code != 200:
                raise AssertionError(response.text)
            overview = response.json()["overview"]
            if (overview["case_count"], overview["transaction_count"]) != (11, 86):
                raise AssertionError(overview)
            if client.get("/api/validation").json()["passed"] != 4:
                raise AssertionError("built-in validation checks did not all pass after one-click load")
            return "one click loads the 11-case / 86-transaction evaluator dataset; 4/4 validations pass"
        check("One-click evaluator data loader", one_click_evaluator_load)

        demo_dir = ROOT / "demo_csvs"
        expected = {
            "00_full_reference_9cases_74transactions.csv": (9, 74, 2, 3),
            "01_direct_link_alpha_CASE-101_CASE-102.csv": (2, 16, 1, 0),
            "02_direct_link_beta_CASE-103_CASE-104.csv": (2, 16, 1, 0),
            "03_disconnected_fingerprint_cluster_CASE-201_202_203.csv": (3, 24, 0, 3),
            "04_benign_negative_control_CASE-301_CASE-302.csv": (2, 18, 0, 0),
            "05_low_sample_gate_custom_pair.csv": (2, 12, 0, 0),
            "06_alias_mapping_focus_CASE-101_CASE-301.csv": (2, 17, 0, 0),
            "07_evaluator_combined_with_low_sample.csv": (11, 86, 2, 3),
        }
        def all_csv_uploads():
            if not demo_dir.is_dir():
                raise FileNotFoundError("demo_csvs folder missing; re-extract the complete project ZIP")
            for filename, exp in expected.items():
                path = demo_dir / filename
                if not path.is_file():
                    raise FileNotFoundError(f"Missing {filename}")
                response = client.post("/api/upload", files={"file": (filename, path.read_bytes(), "text/csv")})
                if response.status_code != 200:
                    raise AssertionError(f"{filename}: HTTP {response.status_code}: {response.text}")
                ov = response.json()["overview"]
                got = (ov["case_count"], ov["transaction_count"], ov["direct_link_count"], ov["fingerprint_link_count"])
                if got != exp:
                    raise AssertionError(f"{filename}: expected {exp}, got {got}")
            return "all 8 transaction CSVs accepted with expected counts and link totals"
        check("All bundled CSV uploads", all_csv_uploads)

        def low_sample_pair():
            path = demo_dir / "07_evaluator_combined_with_low_sample.csv"
            response = client.post("/api/upload", files={"file": (path.name, path.read_bytes(), "text/csv")})
            if response.status_code != 200:
                raise AssertionError(response.text)
            result = client.get("/api/fingerprints/compare", params={"case_a":"LOW-DEMO-04", "case_b":"LOW-DEMO-08"})
            if result.status_code != 200:
                raise AssertionError(result.text)
            data = result.json()
            if data["fingerprint_eligible"] or data["transactions_a"] != 4 or data["transactions_b"] != 8:
                raise AssertionError(data)
            return "LOW-DEMO-04 (4 TX) is blocked against LOW-DEMO-08 (8 TX)"
        check("Low-sample CSV scenario", low_sample_pair)

        def alias_workflow():
            client.post("/api/reset-demo")
            payload = {
                "institution": "Lighthouse Credit", "account_id": "LIGHT-L1",
                "canonical_account_id": "NORTH-M1",
                "attested_by": "SHADOWNET demo operator (synthetic test)",
                "source_reference": "SYNTHETIC-ALIAS-TEST-001",
            }
            response = client.post("/api/aliases", json=payload)
            if response.status_code != 200:
                raise AssertionError(response.text)
            audit = client.get("/api/aliases").json()
            if audit["count"] != 1 or audit["items"][0]["mapping_status"] != "operator_attested":
                raise AssertionError(audit)
            links = client.get("/api/links").json()
            link = next((x for x in links if {x["case_a"], x["case_b"]} == {"CASE-101", "CASE-301"}), None)
            if not link:
                raise AssertionError("alias-based CASE-101 / CASE-301 relationship not created")
            evidence = link["evidence_a"] + link["evidence_b"]
            mapped = next((x for x in evidence if x["alias_mapped"]), None)
            if not mapped or mapped["attested_by"] != payload["attested_by"] or mapped["source_reference"] != payload["source_reference"]:
                raise AssertionError("alias provenance missing from graph evidence")
            return "alias applied, audit stored, graph evidence contains operator + source reference"
        check("Operator-attested alias workflow", alias_workflow)

        def index_rejected_helpfully():
            raw = b"filename,purpose,recommended_use,contents\nexample.csv,index,test,not transactions\n"
            response = client.post("/api/upload", files={"file": ("DATASET_INDEX.csv", raw, "text/csv")})
            if response.status_code != 422 or "dataset index" not in response.json().get("detail", "").lower():
                raise AssertionError(f"unexpected response: {response.status_code} {response.text}")
            return "clear message tells user to select a numbered transaction CSV"
        check("Dataset index error message", index_rejected_helpfully)

        def bad_extension_rejected():
            response = client.post("/api/upload", files={"file": ("example.xlsx", b"fake", "application/octet-stream")})
            if response.status_code != 415:
                raise AssertionError(f"expected HTTP 415, got {response.status_code}")
            return "non-CSV file rejected clearly"
        check("Wrong file type rejected", bad_extension_rejected)

        client.post("/api/reset-demo")
        check("Reset restores clean reference dataset", lambda: "9 cases · 74 transactions · 4/4 validations" if (lambda o,v: o["case_count"] == 9 and o["transaction_count"] == 74 and v["passed"] == 4)(client.get('/api/overview').json(), client.get('/api/validation').json()) else (_ for _ in ()).throw(AssertionError("reset verification failed")))

    except Exception as exc:
        failed += 1
        print(f"[FAIL] Diagnostics could not finish API checks — {exc}")
        traceback.print_exc()

    print("=" * 58)
    print(f"RESULT: {passed} passed · {failed} failed")
    if failed:
        print("Read the [FAIL] lines above. Save this report and share it for troubleshooting.")
        return 1
    print("SHADOWNET checks are healthy. You can now start the app with start_shadownet.bat.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
