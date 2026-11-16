import sys
from pathlib import Path
import unittest
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import SHADOWNETEngine, DataValidationError, read_csv_bytes, compare_fingerprints, DEFAULT_WEIGHTS


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = pd.read_csv(ROOT / "data" / "synthetic_transactions.csv")
        cls.engine = SHADOWNETEngine(cls.frame)

    def test_reference_dataset_counts(self):
        summary = self.engine.overview()
        self.assertEqual(summary["case_count"], 9)
        self.assertEqual(summary["institution_count"], 9)
        self.assertEqual(summary["transaction_count"], 74)

    def test_known_direct_links_have_evidence(self):
        links = self.engine.result.direct_links
        self.assertEqual(len(links), 2)
        self.assertTrue(all(x["evidence_a"] and x["evidence_b"] for x in links))
        self.assertEqual({x["shared_account_id"] for x in links}, {"X-SHARED-ALPHA", "X-SHARED-BETA"})

    def test_disconnected_triplet_creates_three_pairwise_fingerprint_links(self):
        links = self.engine.result.fingerprint_links
        pairs = {frozenset((x["case_a"], x["case_b"])) for x in links}
        expected = {
            frozenset(("CASE-201", "CASE-202")),
            frozenset(("CASE-201", "CASE-203")),
            frozenset(("CASE-202", "CASE-203")),
        }
        self.assertEqual(pairs, expected)
        for link in links:
            cmp = self.engine.compare(link["case_a"], link["case_b"])
            self.assertFalse(cmp["has_direct_overlap"])
            self.assertTrue(cmp["meets_threshold"])

    def test_benign_lookalike_is_negative_control(self):
        result = self.engine.compare("CASE-301", "CASE-302")
        self.assertFalse(result["has_direct_overlap"])
        self.assertLess(result["comparison"]["score"], 90)
        self.assertFalse(result["meets_threshold"])

    def test_low_sample_scenario_is_not_compared(self):
        rows = [
            {"timestamp": f"2026-11-01T0{h}:00:00Z", "source_account": f"A{i}",
             "target_account": f"B{i}", "amount": 100+i, "channel": "UPI"}
            for i, h in enumerate([1, 2, 3, 4], 1)
        ]
        result = self.engine.evaluate_scenario(rows)
        self.assertFalse(result["fingerprint_eligible"])
        self.assertEqual(result["nearest_matches"], [])

    def test_validation_suite_all_four_pass(self):
        result = self.engine.validation_suite()
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["passed"], 4)
        self.assertEqual(result["failed"], 0)

    def test_fingerprint_exposes_all_sixteen_features(self):
        result = self.engine.compare("CASE-201", "CASE-202")
        self.assertEqual(len(result["comparison"]["features"]), 16)
        self.assertTrue(result["comparison"]["strongest_alignments"])
        self.assertTrue(result["comparison"]["notable_differences"])

    def test_operator_attested_alias_requires_explicit_provenance(self):
        entries = [
            {"institution": "Pioneer Digital Bank", "account_id": "PIONEER-A", "canonical_account_id": "ALIAS-ONE",
             "mapping_status": "operator_attested", "attested_by": "Demo authority", "source_reference": "TEST-RECORD-01"},
            {"institution": "Summit Commercial", "account_id": "SUMMIT-A", "canonical_account_id": "ALIAS-ONE",
             "mapping_status": "operator_attested", "attested_by": "Demo authority", "source_reference": "TEST-RECORD-02"},
        ]
        engine = SHADOWNETEngine(self.frame, aliases=entries)
        alias_links = [x for x in engine.result.direct_links if x["shared_account_id"] == "ALIAS-ONE"]
        self.assertTrue(alias_links)
        self.assertEqual(len(engine.alias_audit), 2)

    def test_operator_attested_alias_evidence_includes_original_id_and_provenance(self):
        entries = [{
            "institution": "Lighthouse Credit", "account_id": "LIGHT-L1",
            "canonical_account_id": "NORTH-M1", "mapping_status": "operator_attested",
            "attested_by": "SHADOWNET demo operator (synthetic test)",
            "source_reference": "SYNTHETIC-ALIAS-TEST-001",
        }]
        engine = SHADOWNETEngine(self.frame, aliases=entries)
        link = next(x for x in engine.result.direct_links if {x["case_a"], x["case_b"]} == {"CASE-101", "CASE-301"})
        evidence = link["evidence_a"] + link["evidence_b"]
        mapped = [x for x in evidence if x["alias_mapped"]]
        self.assertTrue(mapped)
        self.assertTrue(all(x["raw_account_id"] == "LIGHT-L1" for x in mapped))
        self.assertTrue(all(x["canonical_account_id"] == "NORTH-M1" for x in mapped))
        self.assertTrue(all(x["source_reference"] == "SYNTHETIC-ALIAS-TEST-001" for x in mapped))
        self.assertTrue(all(x["attested_by"] == "SHADOWNET demo operator (synthetic test)" for x in mapped))

    def test_validation_suite_includes_observable_evidence(self):
        result = self.engine.validation_suite()
        self.assertEqual(result["passed"], 4)
        checks = {x["name"]: x for x in result["checks"]}
        self.assertEqual(checks["Known shared-account pair"]["evidence"]["shared_account_id"], "X-SHARED-ALPHA")
        self.assertEqual(checks["Disconnected high-match pair"]["evidence"]["shared_account_ids"], [])
        self.assertLess(checks["Benign look-alike pair"]["evidence"]["score"], 90)
        self.assertEqual(checks["Low-sample / no-link case"]["evidence"]["transactions_supplied"], 4)

    def test_non_attested_alias_is_ignored(self):
        entries = [{"institution": "Pioneer Digital Bank", "account_id": "PIONEER-A", "canonical_account_id": "ALIAS-ONE",
                    "mapping_status": "pending", "attested_by": "", "source_reference": ""}]
        engine = SHADOWNETEngine(self.frame, aliases=entries)
        self.assertEqual(engine.alias_audit, [])
        self.assertEqual(len(engine.result.direct_links), 2)

    def test_weight_changes_are_used_in_comparison(self):
        weights = DEFAULT_WEIGHTS.copy()
        weights["night_share"] = 0.20
        weights["weekend_share"] = 0.0
        changed = SHADOWNETEngine(self.frame, weights=weights)
        baseline = self.engine.compare("CASE-101", "CASE-103")["comparison"]["score"]
        adjusted = changed.compare("CASE-101", "CASE-103")["comparison"]["score"]
        self.assertNotEqual(baseline, adjusted)

    def test_csv_validation_rejects_duplicate_transaction_ids(self):
        bad = self.frame.copy()
        bad.loc[1, "transaction_id"] = bad.loc[0, "transaction_id"]
        with self.assertRaises(DataValidationError):
            SHADOWNETEngine(bad)

    def test_csv_validation_rejects_self_transfer(self):
        bad = self.frame.copy()
        bad.loc[0, "target_account"] = bad.loc[0, "source_account"]
        with self.assertRaises(DataValidationError):
            SHADOWNETEngine(bad)

    def test_csv_validation_rejects_invalid_amount(self):
        bad = self.frame.copy()
        bad.loc[0, "amount"] = -4
        with self.assertRaises(DataValidationError):
            SHADOWNETEngine(bad)

    def test_case_graph_has_directed_transaction_edges(self):
        data = self.engine.case_graph("CASE-201")
        self.assertEqual(len(data["edges"]), 8)
        self.assertTrue(all(x["source"] != x["target"] for x in data["edges"]))

    def test_scenario_example_matches_reference_fingerprint(self):
        rows = self.frame[self.frame.case_id == "CASE-201"].sort_values("timestamp")
        payload = [{"timestamp": r.timestamp, "source_account": f"NEW-{r.source_account}",
                    "target_account": f"NEW-{r.target_account}", "amount": r.amount, "channel": r.channel}
                   for r in rows.itertuples(index=False)]
        result = self.engine.evaluate_scenario(payload)
        self.assertTrue(result["fingerprint_eligible"])
        self.assertGreaterEqual(result["nearest_matches"][0]["score"], 99.9)


if __name__ == "__main__":
    unittest.main()
