# SpikeIDS v5 real-data audit

`raw_source_audit_passed`: **true**
`data_acceptance_passed`: **false**

This pass binds exact local bytes, file roles, row counts, physical/selected column order, and every label mapping. It is not a claim that an upstream publisher excluded semantic duplicates or capture/device/time leakage.

| Dataset | Rows | Model features | Classes | Source files |
|---|---:|---:|---:|---:|
| nslkdd | 148517 | 41 | 5 | 2 |
| unsw | 257673 | 42 | 10 | 2 |
| cicids2017 | 2830743 | 76 | 15 | 8 |
| iot23 | 6046623 | 13 | 5 | 1 |

## Scope limits

- NSL-KDD and UNSW-NB15 preserve their declared official train/test roles; validation is drawn only from official training rows.
- CICIDS2017 and IoT-23 use a frozen exact-X-grouped target-64/16/20 protocol after exact-(X,label) deduplication; group constraints make the realized fractions approximate. This does not establish unseen-capture, unseen-device, or temporal generalization.
- The IoT-23 derivative was globally deduplicated upstream and lacks trustworthy group identifiers. Its source manifest records this limitation and `upstream_preprocessing_verified` remains false in the cache.
- The CIC MachineLearningCSV archive is byte-bound to all eight 79-column physical CSVs; the audited drop policy leaves 76 model features. GeneratedLabelledFlows is provenance only.
- Passing SHA checks establishes artifact identity, not an external trust root or physical attestation.

Sealed JSON evidence: `results/v5_data_audit_20260921_r6/data_audit.json`
