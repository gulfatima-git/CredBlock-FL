# Phase 6 Subphase 3 (6.2B): Five Independent Local GraphSAGE Models

**Technical acceptance gate: PASS; user acceptance pending.** Five independently trained local models have been verified on the complete accepted TRAIN/VAL inventory. TEST remains unopened.

Subphase 2 is USER_ACCEPTED in `reports/phase6/pipeline/acceptance_v1.json`. All accepted Phase 5 and Phase 6 Subphase 0/1/2 outputs remain unchanged.

## Full training results

AP is tied-score-grouped average precision (noninterpolated PR area). BCE is unweighted at the restored selected model. Precision/recall/F1 use nominal probability 0.5 as training diagnostics, not calibrated operating thresholds or 1% FPR results.

| Organization | Hidden width | Selected epoch | TRAIN eligible | VAL eligible | TRAIN BCE | VAL BCE | VAL AP | VAL precision @ .5 | VAL recall @ .5 | VAL F1 @ .5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Org1 | 16 | 9 | 75,438 | 55,386 | 0.32344249 | 0.32496989 | 0.74343562 | 0.61117670 | 0.96911076 | 0.74960782 |
| Org2 | 32 | 9 | 77,268 | 51,267 | 0.42121151 | 0.39409467 | 0.71919280 | 0.51627255 | 0.96921887 | 0.67369100 |
| Org3 | 32 | 12 | 82,914 | 58,005 | 0.41522109 | 0.44706838 | 0.65352706 | 0.46661177 | 0.97087227 | 0.63029629 |
| Org4 | 32 | 1 | 87,441 | 57,615 | 0.34549979 | 0.37920396 | 0.78255721 | 0.59595121 | 0.96996154 | 0.73829114 |
| Org5 | 16 | 4 | 91,512 | 63,645 | 0.55630501 | 0.57130642 | 0.70208559 | 0.39917904 | 0.96852330 | 0.56534845 |

Every organization used all 171 TRAIN and all 171 VAL branches, all three campaign seeds and all six accepted grid times per branch: 1,026 TRAIN and 1,026 VAL grids each. This is the full controlled replay inventory, not continuous labeled coverage of the entire calendar ranges. All eligible User-time examples are retained. Ambiguous recent roots remain masked; older context-only roots are omitted from supervised forward passes but remain available as graph context. The final-ten-minute grid coverage gap is unchanged.

## Model and selection protocol

PyG `SAGEConv` supplies two mean-aggregation layers with root transforms, ReLU and 0.1 dropout between layers, followed by a linear User-node binary-logit head. Layer two consumes layer-one hidden states using accepted destination-prefix routing. It never resets to the second packet's raw inspection features. Unit tests compare sampled output with a full-graph reference and verify gradients through both layers. No node-ID embeddings exist.

The predeclared candidates were hidden widths 16 and 32. Adam used learning rate 0.003 and weight decay 0.0001, with gradient clipping at norm 5.0. Each local trial started from fresh seeded weights; seeds were 63030 through 63034. Class weights were computed only from that organization's eligible TRAIN negative/positive ratio. Epochs were capped at 12, with VAL AP early-stopping patience 3 and minimum improvement 1e-6. Candidate selection used VAL AP, then lower VAL BCE, then candidate ID. No optimizer step used VAL.

The same grid and selection rule were used in every organization. Selected local hidden widths may differ. Later federation must fix a common architecture before averaging; there is no averaging or global initialization in this local-only subphase. The configurable model/batch interface is reusable without changing the accepted features or graph design.

The accepted fanouts [15,10], batch size 256, sampler seed 60201, eight-feature allowlist and exact-grid labels were reused unchanged. Fixed sampled neighborhoods were cached on disk and reused across epochs. There is no fitted preprocessing. Inputs are processed branch-by-branch with chronological anchors and grids, without mixing alternative worlds into one event stream. All fitting occurs after the TRAIN cutoff; diagnostic TRAIN scores are in-sample, not historical deployment claims.

## Reproducibility and checkpoints

Each selected configuration was retrained from the identical initialization seed over the complete local corpus, including early stopping. Every organization reproduced the selected epoch, canonical weight digest and complete VAL prediction CSV exactly. Container file hashes and numerical state digests are recorded separately. Safe `weights_only=True` loading reproduced stored VAL logits. Exact replay does not measure uncertainty across different initialization seeds.

| Organization | Seed | Parameters | Selected checkpoint |
|---|---:|---:|---|
| Org1 | 63030 | 817 | `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\training\final_v1\models\Org1.pt` |
| Org2 | 63031 | 2,657 | `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\training\final_v1\models\Org2.pt` |
| Org3 | 63032 | 2,657 | `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\training\final_v1\models\Org3.pt` |
| Org4 | 63033 | 2,657 | `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\training\final_v1\models\Org4.pt` |
| Org5 | 63034 | 817 | `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\training\final_v1\models\Org5.pt` |

Each component directory contains both candidate epoch logs/checkpoints, selected TRAIN metrics/predictions, VAL predictions with labels and masks, the exact repeat, full configuration snapshots, input/source hashes and cache manifests. Only tensors and primitive metadata are stored in model checkpoints. Raw local keys remain audit metadata outside model inputs.

## Resource measurements

CPU-only runs used two Torch threads per organization job. Up to five independent jobs overlapped under the recorded execution plan. Timings below include real concurrent host load; they are not exclusive-machine benchmarks. Selected trial time includes training, per-epoch validation, checkpointing and final validation export. All-trial time includes both candidates and the exact repeat; cache preparation is separate. RSS is whole-process memory, including runtime and residual caches.

| Organization | Cache prep seconds | Selected trial seconds | All trials seconds | Selected trial CPU seconds | Observed training RSS peak MiB |
|---|---:|---:|---:|---:|---:|
| Org1 | 2939.579 | 548.204 | 1351.407 | 646.672 | 377.824 |
| Org2 | 3111.435 | 619.820 | 1310.016 | 793.391 | 358.012 |
| Org3 | 2803.078 | 170.905 | 364.358 | 333.453 | 372.090 |
| Org4 | 2870.089 | 54.855 | 239.700 | 106.984 | 379.742 |
| Org5 | 3630.918 | 251.167 | 484.106 | 357.000 | 378.543 |

## Real inductive validation

An unseen User is absent from the union of all local TRAIN graph views. Unseen-IP context means at least one sampled root-neighbor IP was absent from that same TRAIN union. These flags are evaluator-only, never model inputs or fitting weights. IPs are context nodes, not classification targets. Missing subgroup AP means no positive labels, not a fabricated zero.

| Organization | Unseen-User eligible | Unseen-User AP | Unseen-IP-context eligible | Unseen-IP-context AP |
|---|---:|---:|---:|---:|
| Org1 | 46,989 | 0.75437645 | 45,240 | 0.76363969 |
| Org2 | 43,314 | 0.71498746 | 41,634 | 0.76033403 |
| Org3 | 49,848 | 0.64805889 | 46,890 | 0.70548593 |
| Org4 | 48,948 | 0.78141457 | 47,754 | 0.80112217 |
| Org5 | 54,531 | 0.69144051 | 52,245 | 0.75857279 |

## Tests, scope and execution history

The final automated non-TEST suite passed 96 tests, with one existing real-TEST-manifest test deliberately deselected (142 dependency warnings, 106.72 seconds). New TEST guards are tested before file access. The first attempt had 92 passes and three temporary-directory setup errors; a permitted rerun resolved the setup errors (95 passed). After warm-up reader buffers were released, both real TRAIN/VAL fork-equivalence tests passed again. A further regression test verifies that representative results cannot create a full acceptance report. Exact commands and the separate accepted-runtime self-test result are recorded in testing_results_v1.json.

The tiny optimizer/checkpoint test is a smoke test. `integration_v1` is representative training on one fixed TRAIN/VAL branch per organization, capped at three epochs; its results are not the full-data table above. Its development artifact manifest was corrected append-only because the final progress line was appended after the journal hash; numerical artifacts were unchanged.

The initial sequential full-data attempt was stopped during cache preparation, before any full-data model was trained, to change execution scheduling. Its partial cache is retained and is not accepted training evidence. The final execution plan uses queued isolated Org1/Org2 jobs and independent Org3-Org5 components; only the five verified full components supply this report. Redundant queued work is stopped after Org1/Org2 complete. No accepted artifact was overwritten.

Final verification checked 10,260 sampled cache files, all component artifact manifests, checkpoint/cache fingerprints, exact split/branch/grid coverage, independent model states, real inductive coverage, zero TEST branch inputs and 92 pre-existing accepted files. Shared raw organization sources were queried only for bounded past TRAIN/VAL warm-up and hashed for integrity; no TEST branch observations, labels or manifests were opened by training or model selection.

## Preservation and remaining limitations

Frozen protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`. Splits, grid definitions, evaluation units and the primary 1% FPR target were not amended. A version-control commit remains required before final TEST evaluation. No threshold calibration, continuous alerting, indicator sharing, federated learning, DP or blockchain component was implemented.

Repeated background data and three temporal blocks per split remain dependent. Clean-negative candidates do not certify benignness. Validation is used for selection and is not final held-out performance. The search covers two modest architectures and one initialization seed per organization; exact repeats do not supply initialization confidence intervals. Actual training uses retained real graphs; the prior million-node synthetic smoke is not million-node training evidence. Nominal precision uses a zero result for no predicted positives; undefined empty-subgroup metrics are marked N/A.

The next exact action is user review and acceptance of Subphase 3. Only then proceed to Subphase 4 (6.2C), the non-graph local comparator. This report does not complete Phase 6.
