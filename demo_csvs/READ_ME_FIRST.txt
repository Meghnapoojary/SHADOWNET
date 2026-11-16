# SHADOWNET CSV demo files

Use the numbered transaction CSVs only. The app requires these columns: `transaction_id, case_id, bank, timestamp, source_account, target_account, amount`.

Recommended first upload: `07_evaluator_combined_with_low_sample.csv` (11 cases / 86 transactions). It includes the named examples used by the four built-in validation checks plus a custom low-sample pair. For a smaller starting point, use `00_full_reference_9cases_74transactions.csv` (9 cases / 74 transactions).

The 01–06 files focus on one demonstration at a time. If you upload one of those small files, the built-in four-case validation panel may not find its other named fixtures.

All data is fictional. Uploading replaces the currently loaded dataset; it does not append. Use **Reset demo** to restore the original 9-case reference dataset.
