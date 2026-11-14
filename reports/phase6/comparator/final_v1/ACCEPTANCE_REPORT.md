# Phase 6 Subphase 4 (6.2C): Non-Graph Local Comparator and Best-Local Selection

**Technical gate: PASS; user acceptance pending.** Subphase 3 is USER_ACCEPTED in the new append-only training/acceptance_v1.json record.

## Frozen design and fairness

The versioned preregistration was written before comparator training or comparison. Each organization independently fits a two-hidden-layer tabular MLP using the seven unchanged root User behavioral features. The constant node type is omitted. Distinct-IP counts describe only the User's own login history; no IP-node attributes, neighbor-user behavior, graph edges or neighborhood aggregation enters the comparator. Input projection reuses immutable accepted caches. No accepted pipeline, graph runtime, dataset, split, grid, mask or feature transform changed.

Two widths (16/32), two hidden transformations, dropout 0.1, Adam learning rate 0.003, weight decay 0.0001, maximum 12 epochs, patience 3, weighted TRAIN BCE and deterministic chronological minibatches match the accepted GraphSAGE search budget. Class weight uses only that local TRAIN split. No learned preprocessing is fitted. Seed base 64040 plus organization index; CPU two Torch threads, deterministic algorithms. Parameter counts differ because graph aggregation is removed.

Per-organization best-local rule: greatest VAL tied-score average precision, then lowest unweighted VAL BCE, then GraphSAGE on an exact tie. Candidate ties use candidate ID. Early stopping retains the earlier epoch unless AP improves by more than 1e-6. The primary 1% FPR target is unchanged; no final thresholds or fixed-FPR recall are computed here.

All five accepted GraphSAGE checkpoints were reloaded without retraining. Every full VAL logit matched the preserved original CSV exactly, together with ordered organization/branch/User/time keys, labels, masks and inductive flags. Both detectors use exactly the same eligible examples, metrics and evaluation unit.

## Exact full-data comparison

| Org | TRAIN eligible | VAL eligible | MLP width / epoch | GraphSAGE AP | MLP AP | GraphSAGE BCE | MLP BCE | Best local |
|---|---:|---:|---|---:|---:|---:|---:|---|
| Org1 | 75438 | 55386 | 16 / 8 | 0.743435620733 | 0.664224011469 | 0.324969891456 | 0.370689006286 | graphsage |
| Org2 | 77268 | 51267 | 16 / 2 | 0.719192799891 | 0.584792066090 | 0.394094665373 | 0.533623498337 | graphsage |
| Org3 | 82914 | 58005 | 32 / 3 | 0.653527055691 | 0.528775625830 | 0.447068378244 | 0.539229760216 | graphsage |
| Org4 | 87441 | 57615 | 16 / 3 | 0.782557214426 | 0.665935166869 | 0.379203955584 | 0.455626326945 | graphsage |
| Org5 | 91512 | 63645 | 32 / 9 | 0.702085587416 | 0.600009809640 | 0.571306415909 | 0.622859641728 | graphsage |

## Supporting nominal diagnostics and resources

Precision/recall/F1 below use nominal probability 0.5 only, not calibrated alert operating points. The complete unrounded values, TRAIN metrics and inductive subgroup metrics are saved in summary.json. Training RSS includes in-memory input arrays and host allocator overhead. Timings are observed on the shared host, not an exclusive benchmark. Preparation includes loading/hashing caches and recomputing GraphSAGE VAL scores.

| Org | MLP P@.5 | MLP R@.5 | MLP F1@.5 | Selected trial s | All trials+repeat s | Preparation s | Training RSS MiB | Whole-process peak MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Org1 | 0.540511915 | 0.955382215 | 0.690417136 | 107.767 | 303.799 | 42.838 | 407.148 | 412.773 |
| Org2 | 0.363109863 | 0.960092807 | 0.526932383 | 62.122 | 104.361 | 46.864 | 407.457 | 412.828 |
| Org3 | 0.391048739 | 0.963551402 | 0.556319978 | 87.099 | 198.146 | 32.084 | 410.961 | 417.938 |
| Org4 | 0.549938130 | 0.970065482 | 0.701940433 | 84.172 | 219.489 | 48.779 | 412.629 | 420.379 |
| Org5 | 0.421100967 | 0.958440920 | 0.585122354 | 178.020 | 481.422 | 46.329 | 413.934 | 422.289 |

## Artifacts and reproducibility

- Org1: selected comparator `reports/phase6/comparator/final_v1/models/Org1.pt`; all candidate epochs/checkpoints, repeated fit and predictions, configuration/schema/protocol snapshots, resource measurements, paired provenance and best-local record: `reports/phase6/comparator/full_v1/Org1/`.
- Org2: selected comparator `reports/phase6/comparator/final_v1/models/Org2.pt`; all candidate epochs/checkpoints, repeated fit and predictions, configuration/schema/protocol snapshots, resource measurements, paired provenance and best-local record: `reports/phase6/comparator/full_v1/Org2/`.
- Org3: selected comparator `reports/phase6/comparator/final_v1/models/Org3.pt`; all candidate epochs/checkpoints, repeated fit and predictions, configuration/schema/protocol snapshots, resource measurements, paired provenance and best-local record: `reports/phase6/comparator/full_v1/Org3/`.
- Org4: selected comparator `reports/phase6/comparator/final_v1/models/Org4.pt`; all candidate epochs/checkpoints, repeated fit and predictions, configuration/schema/protocol snapshots, resource measurements, paired provenance and best-local record: `reports/phase6/comparator/full_v1/Org4/`.
- Org5: selected comparator `reports/phase6/comparator/final_v1/models/Org5.pt`; all candidate epochs/checkpoints, repeated fit and predictions, configuration/schema/protocol snapshots, resource measurements, paired provenance and best-local record: `reports/phase6/comparator/full_v1/Org5/`.

Every selected candidate was independently retrained from its fixed seed; selected epoch, tensor-state digest, every VAL score and the full VAL prediction CSV reproduced exactly. Final verification safely reloads all five models and independently recomputes every saved VAL score. Both model families remain preserved regardless of the winner.

The full inventory is 171 TRAIN + 171 VAL branches and 1026 grid times per split per organization; 414573 TRAIN and 285918 paired eligible VAL User-times in total. All 10260 original cache files were hash-verified. 11691 pre-existing accepted/support artifacts remained byte-identical.

## Tests and evidence scope

See ../testing_results_v1.json for exact commands, pass counts and exclusions. Tiny synthetic training checks are smoke tests. representative_v1/Org1 is one predetermined real TRAIN/VAL branch, capped at three epochs, and cannot satisfy the full gate. Only the five completed full_v1 components supply the comparison table and final gate. Tests check input allowlisting, independence from graph edges/context, labels/metadata isolation, masks, chronological guards, same-example fairness, metric ties, selection, and exact repetition.

## Limitations and next action

VAL selects candidates and best-local models; these are not final TEST performance estimates. Repeated backgrounds and only three temporal blocks per split are dependent. Clean-negative candidates do not prove benignness. AP is average precision with tied scores grouped, not trapezoidal PR-AUC. Two modest architectures and one initialization per organization do not exhaust tabular methods or provide initialization confidence intervals. This is an eligible comparator, not a claim of globally optimal local detection. Accepted GraphSAGE metrics were already visible before this new preregistration. Root tabular arrays are local private audit artifacts, never a cross-organization identity index. No million-node training-scale claim is inferred.

Best-local selection by AP does not assert the same ordering at the later 1% FPR operating point. Preserve the recorded choice and both families for Subphase 5 calibration without choosing from TEST outcomes. No TEST branch files/outcomes were opened, no final thresholds were calibrated, and no continuous inference, indicator sharing, federation, DP or blockchain was implemented.

Frozen protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`. Its version-control gate remains required before final TEST evaluation; this subphase does not certify a commit.

Next exact action: user review and acceptance of Subphase 4. Subphase 5 has not started.
