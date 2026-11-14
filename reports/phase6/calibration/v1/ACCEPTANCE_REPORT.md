# Phase 6 Subphase 5 (6.3): Fixed-FPR Threshold Calibration

**Technical gate: PASS; user acceptance pending.** Subphase 4 is USER_ACCEPTED in the new append-only comparator/acceptance_v1.json record.

## Frozen operating rule

The primary target remains 1% empirical FPR on eligible y=0 VAL User-windows. Each organization and detector is calibrated separately using negative logits only. FP budget is exact integer division N_negative // 100. Masks, fixed-grid User-time identities, alternative branches and split bounds are unchanged. Positives are used only after the threshold is fixed to calculate operating metrics.

Decision: **binary64 logit >= binary64 threshold**. Promote model scores before comparison using the supplied helper. Thresholds are the immediate binary64 successor of the first disallowed negative-score boundary; all equal-score ties stay together. Lowering a threshold by one binary64 ULP admits more negatives than permitted. The probability column is not used because sigmoid rounding can merge distinct logits. Authoritative hexadecimal encodings are saved beside round-trip decimal values. An explicit no-alert sentinel handles the case with no qualifying finite threshold.

With fewer than 100 eligible negatives, the protocol permits only zero FPs and flags the target as unresolvable at resolution 1/N. Zero eligible negatives is an error, not a fabricated threshold. Undefined metrics are null. No extra FPR sensitivity targets were introduced.

## Full validation calibration

| Organization | Detector | Authoritative logit threshold | FP / N negative | FP budget | Achieved FPR | Recall | Precision | F1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Org1 | graphsage | 4.680909156799317 | 456 / 45771 | 457 | 0.009962640100 | 0.281643265731 | 0.855878634640 | 0.423820330229 |
| Org1 | tabular_mlp | 2.8987755775451665 | 399 / 45771 | 457 | 0.008717310087 | 0.252002080083 | 0.858610914245 | 0.389643804776 |
| Org2 | graphsage | 4.575629711151124 | 399 / 44802 | 448 | 0.008905852417 | 0.342614075793 | 0.847360367253 | 0.487939200352 |
| Org2 | tabular_mlp | 3.297644376754761 | 399 / 44802 | 448 | 0.008905852417 | 0.212064965197 | 0.774576271186 | 0.332969034608 |
| Org3 | graphsage | 4.7278175354003915 | 513 / 51585 | 515 | 0.009944751381 | 0.359968847352 | 0.818342776204 | 0.500000000000 |
| Org3 | tabular_mlp | 4.258240222930909 | 513 / 51585 | 515 | 0.009944751381 | 0.217289719626 | 0.731132075472 | 0.335014409222 |
| Org4 | graphsage | 3.2125992774963383 | 456 / 47994 | 479 | 0.009501187648 | 0.424695977549 | 0.899603698811 | 0.576996399068 |
| Org4 | tabular_mlp | 3.3542437553405766 | 456 / 47994 | 479 | 0.009501187648 | 0.251740983266 | 0.841556636553 | 0.387551004080 |
| Org5 | graphsage | 3.673063755035401 | 456 / 55512 | 555 | 0.008214440121 | 0.293864502644 | 0.839775122980 | 0.435376628108 |
| Org5 | tabular_mlp | 3.942832946777344 | 513 / 55512 | 555 | 0.009241245136 | 0.263371449650 | 0.806779661017 | 0.397107897664 |

All ten thresholds satisfy their integer budgets. Full TP/FP/TN/FN counts, negative-score tie sizes, unused budgets, 1/N resolution, unchanged AP/BCE, campaign-seed and unseen-node-context breakdowns, per-organization macro and pooled results are in summary.json. **GraphSAGE remains the accepted best-local detector for Org1–Org5, irrespective of calibrated recall.**

## Provenance and reproducibility

thresholds/ contains ten sealed JSON artifacts keyed by organization/detector. Each records the selected model version/checkpoint hash, source/configuration/protocol/schema hashes, accepted prediction hash, declared VAL period and observed grid range, denominator definition, boundary and tie policy, metrics, locked best-local record and reproducibility evidence. input_sha256.json records every model, prediction and selection input. Original model/configuration files remain authoritative and unchanged; no models were trained.

Each calibration reproduced identically with reversed negatives and a fixed random permutation. All ten sealed artifacts were reloaded through an API with no prediction/label/recalibration parameters; decisions and every confusion-derived metric reproduced exactly on the accepted full VAL files. Calibration guards reject TRAIN and TEST before file access. Existing output directories are rejected before inputs are opened. Model selection is not called by this subsystem.

11907 inventoried prior accepted/support files were verified byte-identical, including both model families, full predictions, histories, repeats, selected model records and prior acceptance evidence.

## Tests and limitations

See ../testing_results_v1.json for exact commands and scope. Unit tests cover integer budgets, tied boundaries, maximal permissiveness, binary32 downcast protection, no-alert sentinel, empty negatives, small samples, masking, no positives, reproducibility, seals and identity checks, TEST-before-I/O guards, paired-cohort checks and overwrite rejection. The actual full run independently verifies all ten thresholds and loaders; synthetic tests alone are not calibration evidence.

These achieved rates are empirical VAL rates, not population guarantees or held-out TEST performance. VAL was already used for model selection, and alternate branches share background across only three temporal blocks per split. Clean-negative candidates do not certify benignness. No IID confidence intervals are claimed. Ties and integer budgets can yield an FPR below 1%; no tie splitting or post-hoc model reselection is permitted. The frozen grid excludes the exclusive hour end, so the final ten minutes have no endpoint primary score. Continuous event-driven FPR is outside this subphase.

The threshold domain is logit, not rounded probability. Future consumers must use the provided binary64 comparison helper and verify model/configuration/protocol identity when loading. Threshold files and their manifests are integrity records, not external signatures. Fixed thresholds do not imply continuous inference has been implemented.

Frozen protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`. Its version-control gate remains required before any later authorized final TEST evaluation; this subphase does not certify a commit.

No TEST branch outcomes were accessed, no continuous inference, indicator sharing, federation, DP or blockchain component was implemented. Next action: explicit user acceptance of Subphase 5. Subphase 6 remains NOT_STARTED.
