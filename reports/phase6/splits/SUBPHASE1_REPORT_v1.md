# Subphase 1: chronological train/validation/test design

**Technical exit gate: PASS; user acceptance pending.** The successful executable audit is `v2/summary.json`. Subphase 2 has not started.

## Completed work and evidence

- Preserved the accepted Phase 5 split boundaries and all 513 campaign assignments, across 2,565 isolated organization branches. Each organization has 171 instances and three campaign seeds per split.
- Verified 8,772 frozen input hashes before use and again after the audit. Accepted graph runtime/validator hashes and the accepted Subphase 0 contract hash match. No accepted Phase 5 source or output was edited.
- Checked the cutoffs, organization/branch identity, masks, positive evidence availability and expiry for all **3,454,398** stored sparse label states. Checked all replay/observation event timestamps against their branch bounds.
- Verified all **45 seven-day warm-up source views**, including source coverage and event counts. History remains observed context; no historical training labels were invented.
- Measured **zero** synthetic attacker-IP overlap for TRAIN/VAL, TRAIN/TEST and VAL/TEST. Synthetic IP counts were 14,293, 14,296 and 14,249 respectively. Raw IP values were not exported.
- Validated all **15,390** fixed-grid snapshots against their branch assignments and exact stored grid labels. Saved per-organization and pooled prevalence, eligible/masked/context counts, class imbalance and distinct organization-local User counts.
- Added fail-closed split-use, target-time and checkpoint guards with future-event/label prefix and exact expiry tests. These are policy components for later pipelines; no sampler/trainer implementation or integration is claimed.

## Frozen decisions for acceptance

The protocol is `configs/phase6/split_protocol_v1.json`, SHA256:

`9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`

It was pinned before querying TEST descriptive tables. The detailed rationale and exact boundaries are in `PROTOCOL_REVIEW_v1.md`.

- Primary unit: eligible local **User-time** at the existing ten-minute grid, keyed by variant/organization/User/time. TRAIN uses the same fixed-grid eligibility definition; sparse event/expiry transitions are not independent primary examples.
- Primary operating point: **1% empirical FPR**, calibrated on VAL independently per organization and detector in Subphase 5. Eligible clean-negative candidates are the denominator; ties cannot be split to exceed the integer FP budget. No threshold was fitted here.
- Scoring times: anchor plus 0, 10, 20, 30, 40 and 50 minutes. The final ten minutes have no endpoint primary grid score; later continuous-alert evaluation must report that coverage separately.
- Organization results and equal-weight organization macro metrics are primary; pooled counts are secondary. Repeated backgrounds and only three temporal blocks per split prohibit interpreting branch copies as independent natural events or using naive row-level IID confidence intervals.
- TRAIN fits learned state; VAL selects/tunes/calibrates; TEST remains reserved for locked final evaluation. This subphase performs only predeclared integrity, temporal/infrastructure and descriptive TEST audits, with no detector outcomes or TEST-driven choices.

## Descriptive pooled fixed-grid census

These are repeated benchmark User-time counts across all five organizations, not independent people or security events. Context-only exposure counts are implicit graph Users without recent evidence, not materialized training rows. The pooled distinct-User field in the CSV sums organization-local distinct counts without cross-organization identity matching.

| Split | Eligible User-times | Positive | Clean-negative candidates | Ambiguous | Context-only | Positive prevalence among eligible |
|---|---:|---:|---:|---:|---:|---:|
| TRAIN | 414,573 | 40,197 | 374,376 | 20,577 | 198,275,382 | 9.70% |
| VAL | 285,918 | 40,254 | 245,664 | 16,359 | 204,949,716 | 14.08% |
| TEST | 259,638 | 40,359 | 219,279 | 22,458 | 203,235,726 | 15.54% |

Clean-negative candidates do not certify benignness. Per-organization counts and imbalance ratios are in `v2/per_organization_prevalence.csv`; the full sparse-schedule census is separate in `v2/sparse_schedule_counts.csv`.

## Tests and execution history

Command: `.venv/Scripts/python.exe -B -m pytest tests/phase6 -q -p no:cacheprovider`

Final result: **65 passed, one warning**, in 16.59 seconds. The warning is the previously observed PyTorch TorchScript/Python 3.14 compatibility warning. The earlier run passed 64 tests; a DuckDB relation-view regression test was then added.

Successful audit command: `.venv/Scripts/python.exe -B -m src.phase6.audit_splits --output reports/phase6/splits/v2`

Result: exit code 0, `PASS_TECHNICAL_GATE_AWAITING_USER_ACCEPTANCE`. The first attempt `v1` failed because DuckDB cannot prepare a parameterized `CREATE VIEW`; its failure record is preserved. The implementation uses the relation API and the successful rerun retains the same preregistered protocol hash. No failed or untested check is counted as PASS.

## Files and research records

New implementation/configuration files:

- `configs/phase6/split_protocol_v1.json`
- `src/phase6/temporal_protocol.py`
- `src/phase6/audit_splits.py`
- `tests/phase6/test_temporal_protocol.py`
- `tests/phase6/test_split_audit.py`

New records: Subphase 0 `readiness/acceptance_v1.json`; this report and `PROTOCOL_REVIEW_v1.md`; failed attempt `splits/v1`; successful audit `splits/v2` including preregistration, frozen assignments, warm-up coverage, infrastructure intersections, per-organization/pooled prevalence, sparse counts, input/output hashes and summary; `splits/verification_v1.json`; and `reports/phase6/progress_v2.json`. No existing accepted files were modified and no model artifacts were produced. No external research workbook was available; these are the local research records.

## Pending work and next exact action

The accepted runtime's existing representative SQL feature/edge checks are reused. This is not a full graph-feature replay for all 2,565 branches. Actual sampler/trainer/preprocessing isolation must be integrated and tested in Subphases 2/3. Resource/training compatibility remains for those subphases.

Protocol acceptance is pending. A version-control commit of the frozen protocol is still required before later final TEST evaluation; a SHA256 pin is not represented as a Git commit. No final TEST evaluation is authorized now.

The next exact action is user review and acceptance of this protocol. After acceptance, begin only **Subphase 2 (6.2A): GraphSAGE input and feature pipeline**. GraphSAGE training remains Subphase 3; federation, DP and Fabric remain outside Phase 6.
