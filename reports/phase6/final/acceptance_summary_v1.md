# Phase 6 Subphase 9 Option A — Final user acceptance

Recorded 17 November 2026, Asia/Karachi.

**USER_ACCEPTED: Stages A–B TRAIN/VAL reporting only. Phase 6 remains PENDING_HELD_OUT_TEST_EVALUATION. TEST is unauthorized; Stage C is deferred. Phase 7 has not started.**

The explicit user approval was first written to the append-only progress event `reports/phase6/progress_events/subphase9_option_a_user_approval_v1.json`, followed by `reports/phase6/final/acceptance_v1.json` and `reports/phase6/progress_v20.json`. Historical reports retain their original technical/pending statuses; these records establish the later user acceptance.

## Accepted deliverables

- TRAIN/VAL reporting configuration, additive reporting/figure modules and tests.
- Exact fixed-grid, calibration, prevalence/mask, inductive, seed/factor, training-history, resource, campaign-context and detection-time tables, with provenance.
- All four research questions and six user-supplied contributions, distinguishing design intent, implementation, experimental support, missing evidence, later-phase responsibility, and permitted/prohibited paper claims.
- Eleven final publication figure sets (22 PNG/PDF files), captions, source manifest and numerical source evidence. Initial drafts remain preserved and are not substituted for final figure_manifest_v2 entries.
- Nineteen-sheet final research workbook v2 with independent cell/formula/table verification; the earlier formatting draft and all previous workbooks remain unchanged.
- Technical acceptance report, independent reconciliation, test evidence, limitations, discrepancy register, delivery hashes and this acceptance documentation.

## Verification and preservation

57 tests passed (26 new reporting and 31 existing temporal-contract tests). Independent saved-score checks cover all 20 detector/organization/TRAIN-VAL components, with exact confusion counts and AP/ROC/loss agreement within 1e-12. All 10 threshold artifacts and 10 paired organization/split cohorts reconcile. This is saved-evidence reporting, not repeated model inference or campaign evaluation.

The reporting preservation check recorded 12,254 unchanged pre-existing metadata paths, 241 critical accepted file hashes and 254 reporting-input hashes. Acceptance additionally rechecks the sealed reporting delivery and original numerical inputs without reading TEST payloads. The workbook's exporter post-save failure is documented; the final file passed 58,578 source-cell comparisons, 12 formula/cache checks and 21 native-table checks. No remaining numerical discrepancy was hidden or repaired by changing accepted evidence.

Primary frozen protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

Verified Git commit: `5de030316176a27889054d0e782cb1ad92171cb5`. Its protocol blob and the working file have the same SHA256. No protocol amendment was made.

## Scientific limits carried forward

- The accepted VAL inventory has **0/171 campaigns undetected by every targeted organization**, under both policies. It does not demonstrate federated recovery of campaigns missed everywhere locally.
- Detection anywhere, detection at all targeted organizations, organization-trial detection, local target-User coverage and detection time remain separate. Both policies detect 548/549 organization trials; User coverage is 13,733/36,000 locally and 15,111/36,000 with indicators.
- VAL selected models and calibrated thresholds; no held-out generalization result exists here. TRAIN frozen-threshold metrics are retrospective in-sample diagnostics.
- The 1% target belongs to eligible fixed-grid negative User-times, not operational event/campaign FPR. AP is tied-score average precision; macro and pooled summaries remain separate.
- Shared background, three temporal seed blocks, controlled-family confounding, evaluator-only credential reuse and RIP's diversity-per-attempt definition limit inference. No naive IID confidence interval or causal attribution claim is made.
- Temporal attribution, null/right-censored detection times, ambiguous-match rules and final-ten-minute operational coverage remain unchanged. Detected-only User-delay medians compare different detected populations, not a paired causal speedup.
- Indicators are locally alerted suspicious IPs, not oracle attacker lists, and zero simulated delay is not realistic network latency.
- Future federation transfers learned patterns through model updates; current local GraphSAGE does not reconstruct a cross-organization graph or IP relationships. Privacy, robustness, integrated ledger guarantees/overhead, production latency and cyber-physical effectiveness remain unsupported by this local evaluation.

## Next authorized action

The user may commit the curated accepted code, protocols, reports, figures, workbook and acceptance records. This documentation approval does not authorize TEST, Stage C, Phase 7 or any later implementation. After the user says **done**, stop and wait for further instructions.

Large private replay journals, raw records, graphs and model/prediction archives remain preserved locally. A curated Git commit contains reporting/code/public aggregate evidence and their hash references, not those private archives. It is not claimed to be a self-contained archive of every raw research artifact.
