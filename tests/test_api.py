import sys
from pathlib import Path
import unittest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.main import app


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.client.post("/api/reset-demo")

    def test_health_and_overview(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        data = self.client.get("/api/overview").json()
        self.assertEqual(data["case_count"], 9)
        self.assertEqual(data["direct_link_count"], 2)
        self.assertEqual(data["fingerprint_link_count"], 3)

    def test_validation_endpoint(self):
        data = self.client.get("/api/validation").json()
        self.assertEqual(data["passed"], 4)
        self.assertEqual(data["failed"], 0)

    def test_graph_endpoint_separates_link_types(self):
        data = self.client.get("/api/graph").json()
        self.assertEqual(len(data["nodes"]), 9)
        self.assertEqual(sum(x["type"] == "direct" for x in data["links"]), 2)
        self.assertEqual(sum(x["type"] == "fingerprint" for x in data["links"]), 3)

    def test_case_detail_endpoint(self):
        data = self.client.get("/api/cases/CASE-201").json()
        self.assertEqual(data["transaction_count"], 8)
        self.assertEqual(len(data["fingerprint"]), 16)

    def test_threshold_updates_reanalyse_links(self):
        r = self.client.put("/api/settings", json={"threshold": 95, "weights": None})
        self.assertEqual(r.status_code, 200)
        overview = self.client.get("/api/overview").json()
        self.assertEqual(overview["threshold"], 95)
        self.assertEqual(overview["fingerprint_link_count"], 3)

    def test_alias_endpoint_requires_provenance(self):
        bad = self.client.post("/api/aliases", json={"institution":"Pioneer Digital Bank","account_id":"PIONEER-A","canonical_account_id":"ALIAS-X","attested_by":"","source_reference":""})
        self.assertEqual(bad.status_code, 422)
        good = self.client.post("/api/aliases", json={"institution":"Pioneer Digital Bank","account_id":"PIONEER-A","canonical_account_id":"ALIAS-X","attested_by":"Demo authority","source_reference":"TEST-ALIAS-001"})
        self.assertEqual(good.status_code, 200)


    def test_alias_endpoint_rejects_account_not_in_named_institution(self):
        response = self.client.post("/api/aliases", json={
            "institution": "Lighthouse Credit", "account_id": "DOES-NOT-EXIST",
            "canonical_account_id": "NORTH-M1", "attested_by": "Demo operator",
            "source_reference": "SYNTHETIC-TEST-002",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("was not found", response.json()["detail"])

    def test_alias_application_is_visible_in_audit_and_graph_evidence(self):
        payload = {
            "institution": "Lighthouse Credit", "account_id": "LIGHT-L1",
            "canonical_account_id": "NORTH-M1", "attested_by": "SHADOWNET demo operator (synthetic test)",
            "source_reference": "SYNTHETIC-ALIAS-TEST-001",
        }
        response = self.client.post("/api/aliases", json=payload)
        self.assertEqual(response.status_code, 200)
        audit = self.client.get("/api/aliases").json()
        self.assertEqual(audit["count"], 1)
        self.assertEqual(audit["items"][0]["source_reference"], "SYNTHETIC-ALIAS-TEST-001")
        self.assertEqual(audit["items"][0]["mapping_status"], "operator_attested")
        links = self.client.get("/api/links").json()
        alias_link = next(x for x in links if {x["case_a"], x["case_b"]} == {"CASE-101", "CASE-301"})
        evidence = alias_link["evidence_a"] + alias_link["evidence_b"]
        self.assertTrue(any(x["alias_mapped"] and x["raw_account_id"] == "LIGHT-L1" for x in evidence))
        mapped = next(x for x in evidence if x["alias_mapped"])
        self.assertEqual(mapped["attested_by"], "SHADOWNET demo operator (synthetic test)")
        self.assertEqual(self.client.get("/api/validation").json()["passed"], 4)

    def test_validation_endpoint_exposes_evidence_for_all_four_scenarios(self):
        data = self.client.get("/api/validation").json()
        self.assertEqual(data["passed"], 4)
        self.assertTrue(all(check.get("evidence") for check in data["checks"]))

    def test_scenario_endpoint_blocks_small_sample(self):
        rows = [{"timestamp":f"2026-11-01T0{i}:00:00Z","source_account":f"A{i}","target_account":f"B{i}","amount":100+i} for i in range(1,5)]
        data = self.client.post("/api/scenario/evaluate", json={"transactions":rows})
        self.assertEqual(data.status_code, 200)
        self.assertFalse(data.json()["fingerprint_eligible"])
        self.assertEqual(data.json()["nearest_matches"], [])


    def test_one_click_evaluator_sample_loads_full_fixture_set(self):
        response = self.client.post("/api/load-demo-sample", json={"dataset": "evaluator"})
        self.assertEqual(response.status_code, 200)
        overview = response.json()["overview"]
        self.assertEqual((overview["case_count"], overview["transaction_count"]), (11, 86))
        self.assertEqual(self.client.get("/api/validation").json()["passed"], 4)
        low = self.client.get("/api/fingerprints/compare", params={"case_a":"LOW-DEMO-04", "case_b":"LOW-DEMO-08"}).json()
        self.assertFalse(low["fingerprint_eligible"])

    def test_one_click_reference_sample_restores_original_counts(self):
        self.client.post("/api/load-demo-sample", json={"dataset": "evaluator"})
        response = self.client.post("/api/load-demo-sample", json={"dataset": "reference"})
        self.assertEqual(response.status_code, 200)
        overview = response.json()["overview"]
        self.assertEqual((overview["case_count"], overview["transaction_count"], overview["account_count"]), (9, 74, 83))

    def test_one_click_sample_rejects_unknown_dataset(self):
        response = self.client.post("/api/load-demo-sample", json={"dataset": "../../private"})
        self.assertEqual(response.status_code, 422)

    def test_frontend_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("SHADOWNET", r.text)


if __name__ == "__main__":
    unittest.main()
