# Phase 6 Subphase 6 — technical acceptance supplement

**Technical checks passed for all five local inference loops; user acceptance remains pending.** Subphase 5 was recorded USER_ACCEPTED in a new append-only record. All prior evidence remains unchanged.

This supplement adds independent-process startup evidence and clarifies timer boundaries. The original acceptance report and hashed results remain intact.

| Organization | Events | User scores | Alerts | No-alert | Last 10-min events / scores | End-to-end p95 (s) | Sampling + scoring p95 (s) | Observed RSS peak (MiB) | Mid-restart journal commands | Cold startup + verification (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Org1 | 578 | 4438 | 122 | 4316 | 109 / 859 | 2.376632 | 0.173589 | 471.398 | 92 | 8.786658 |
| Org2 | 567 | 4859 | 468 | 4391 | 84 / 781 | 2.606036 | 0.189490 | 475.621 | 87 | 9.169410 |
| Org3 | 617 | 5749 | 482 | 5267 | 104 / 1246 | 2.678882 | 0.188831 | 480.949 | 12 | 9.509640 |
| Org4 | 626 | 5862 | 379 | 5483 | 112 / 1153 | 2.799706 | 0.194821 | 483.848 | 16 | 8.854251 |
| Org5 | 669 | 5474 | 615 | 4859 | 123 / 1046 | 2.899579 | 0.209082 | 487.238 | 38 | 9.004623 |

All ten full-hour executions finished with zero processing failures. Every restarted replay exactly reproduced the uninterrupted canonical score/alert digest and final graph checkpoint hash. Model weights remained unchanged. Five further fresh-Python startup audits loaded original sealed bundles, restored private copies and matched decisions, cursor, clock and graph; originals remained byte-identical. These audits scored no new observations. An independent read-only scan also verified every stored decision against the original sealed binary64 threshold and unrounded logit hex, with matching model/threshold identities.

Sampling + scoring includes accepted sampled-batch construction and forward passes. View + CSR setup is measured separately. End-to-end includes persistence/checkpoints; per-User latency entries share the timestamp scoring cost and must not be added together. Full-precision stage percentiles, CPU time, runtime, throughput, simulated serial-source lag and model fingerprints are in final_v1/summary.json. Shared-host resource measurements describe this representative workload only.

The automated suite passed 216 distinct tests: 196 Phase 6 regression tests including 24 inference tests, plus 20 accepted-runtime synthetic self-tests. One existing test that opens a TEST manifest was deliberately excluded; pre-access TEST guards passed. Unit tests include duplicate/order rejection, timestamp batches, exact 10-minute/7-day boundaries, checkpoint tampering, atomic scoring/storage failures, original bundle/schema mismatches, fallback and binary64 threshold boundaries. Warnings are documented in testing_results_v1.json.

Preservation was checked against 11,939 prior-file hashes, including all ten calibrated thresholds, both detector families, original VAL predictions, accepted sources, protocol and earlier workbooks. Frozen protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

Evidence locations:

- `final_v1/ACCEPTANCE_REPORT.md` and `final_v1/summary.json`: complete implementation, scientific scope and per-organization measurements.
- `v1/Org1` through `v1/Org5`: source/config snapshots, uninterrupted and restarted summary/latency records, artifact hashes, private local SQLite journals.
- `cold_start_v1/Org1` through `cold_start_v1/Org5`: independent-process startup summaries, hashes and private copied state.
- `testing_results_v1.json`, `preregistration_v1.json`, `LATENCY_AND_RECOVERY_SCOPE_v1.md`, `delivery_audit_v1.json`: test, source-pin, timing and preservation evidence.
- `configs/phase6/continuous_inference_v1.json`; `src/phase6/inference_registry.py`, `local_inference.py`, `inference_replay.py`, `run_continuous_inference.py`, `verify_inference_cold_start.py`; `tests/phase6/test_continuous_inference.py`: additive implementation and tests.
- `reports/phase6/progress_v7.json`: Subphase 5 USER_ACCEPTED, Subphase 6 technical pass pending acceptance; later subphases remain unstarted.

Limitations: one predeclared VAL hour per organization, not all variants, final TEST evaluation or production deployment. Operational User-score units differ from eligible fixed-grid User-windows; the calibrated 1% FPR does not automatically apply, and no operational FPR/recall or ground-truth detection time is claimed. Full final-ten-minute source and decision coverage is preserved for later authorized evaluation. A live producer still needs a complete-timestamp/watermark contract. Logical local privacy is demonstrated on one host; production tenant isolation, real alert transport, daemon operation, journal compaction, power-loss/OS-kill recovery and large-scale benchmarking remain unproven.

Next action: review and explicitly accept Subphase 6. Do not begin Subphase 7 yet. Record the frozen protocol in version control before any final TEST evaluation. No indicators, federation, differential privacy or blockchain were implemented.
