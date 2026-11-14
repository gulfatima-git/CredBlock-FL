# Subphase 5 implementation and artifact index

All paths below are project-relative. Subphase 4 acceptance is append-only in `reports/phase6/comparator/acceptance_v1.json`. GraphSAGE remains best-local for Org1–Org5; no model fitting or selection occurs here.

## New implementation

- `configs/phase6/fpr_calibration_v1.json`: exact 1/100 target, negative-only denominator, score domain, integer and tie rules, sample-size behavior and reproducibility policy.
- `src/phase6/fpr_calibration.py`: negative-only calibration, pure threshold decisions/metrics, canonical seals and frozen-artifact loader. The loader accepts no calibration data and cannot recalculate thresholds.
- `src/phase6/run_fpr_calibration.py`: accepted full VAL CSV readers, paired cohort/hash checks, locked-model lineage, ten-threshold verification, reporting and append-only progress.
- `tests/phase6/test_fpr_calibration.py`: 40 tests including threshold boundaries, tied-score groups, exact integer arithmetic, no eligible negatives, small samples, leakage/split isolation, artifact loading and cohort fairness.
- `prepare_subphase5.py`: one-time acceptance, preservation inventory and preregistration; no real threshold calculation.

## Frozen semantics

The accepted model logits are float32 outputs saved as lossless decimal strings. Parse them into binary64. For N eligible negative VAL User-windows, use budget `N // 100`. Let `b` be the negative logit at zero-based index budget in descending order. The threshold is `nextafter(b, +infinity)` in binary64, and the decision is binary64 `score >= threshold`. This includes all negatives strictly above b, excludes the whole b tie group, and leaves a boundary certificate showing that the immediately lower representable threshold exceeds budget. If there is no finite qualifying threshold, an explicit no-alert sentinel is saved; JSON infinity is never used.

The decision helper promotes score arrays to binary64. Do not directly compare a float32 Torch tensor to the stored Python scalar: scalar downcasting can round the threshold back down to an excluded tie and breach the budget. Hexadecimal threshold encoding is authoritative and checked against the round-trip decimal value. The rounded probability column is not used.

With 1–99 negatives the allowed budget is zero; freeze a conservative threshold and flag finite-sample resolution, rather than falsely claim an exactly achieved 1% rate. No eligible negatives is an error. Positives and masked roots never enter the threshold-calibration function. Eligible positives are used only to report recall and precision after the threshold is fixed.

## New evidence

- `reports/phase6/calibration/accepted_inputs_before_subphase5_v1.json`: 11,907 prior accepted/support file hashes, covering original checkpoints, full predictions, histories, repeat runs, comparison records and scientific configuration/source artifacts.
- `reports/phase6/calibration/preregistration_v1.json`: calibration source/configuration hashes frozen before real threshold calculation, with original design-document hashes and protocol reference.
- `reports/phase6/calibration/testing_results_v1.json`: 192 distinct passing automated tests, deliberate TEST-opening test exclusion and scope of real integration verification.
- `reports/phase6/calibration/v1/thresholds/`: ten sealed organization/detector thresholds, with model version and checkpoint hashes, schema/configuration/calibration-source/protocol hashes, original prediction hash, VAL period, negative denominator and operating metrics.
- `reports/phase6/calibration/v1/summary.json`: full-precision thresholds/results, subgroup metrics, macro/pooled summaries, input preservation, resources and test evidence.
- `reports/phase6/calibration/v1/input_sha256.json`, `best_local_locked.json`, configuration/protocol/preregistration snapshots and `artifact_sha256.json`.
- `reports/phase6/calibration/v1/ACCEPTANCE_REPORT.md`: technical acceptance report, all ten operating points, reproducibility and limitations.
- `reports/phase6/progress_v6.json`: append-only status after the full gate; Subphase 4 USER_ACCEPTED, Subphase 5 technical gate passed awaiting user acceptance, Subphase 6 NOT_STARTED.

## Execution

```powershell
.venv/Scripts/python.exe -B -m src.phase6.run_fpr_calibration
```

The real runner refuses an existing output directory before opening inputs. Each threshold is repeated using reversed and seeded-permuted negatives. Every frozen artifact is reloaded and all decisions/operating metrics are independently reproduced from the accepted full VAL predictions. Both model families remain preserved regardless of threshold-based recall. No TEST access or post-threshold model reselection is supported.

The primary denominator remains dependent benchmark User-windows, not independent people or campaigns. Empirical VAL control is not a held-out or population FPR guarantee. The fixed grid's excluded hour-end remains unchanged. No continuous event-driven detection, indicator-sharing, federation, DP or blockchain implementation occurs in this subphase. The original protocol must still be recorded in version control before any later authorized final TEST evaluation; this run does not certify that commit.
