# Scope of the Subphase 4 comparison

This comparison is designed to select an eligible local baseline without TEST outcomes. It does not assert that one model family is universally best.

Both detectors receive the same root User behavioral information. GraphSAGE additionally uses the accepted IP/node neighborhoods; the tabular model receives no neighborhood attributes, edges or aggregation. The User's own distinct-IP counts are retained as standard observable behavioral features, not an aggregation of other nodes' attributes. Independent observed-event tests establish that other Users sharing those IPs do not alter the tabular feature vector.

The two candidate widths, network depth, optimizer/loss policy, maximum epochs, patience, masks, chronological minibatches and evaluation examples are matched. Parameter counts are not matched because GraphSAGE has additional neighborhood branches. This is a fair, declared-budget detector comparison, not strict causal isolation of topology at identical parameter count. No claim of graph-specific causal gain follows from AP differences alone.

VAL is reused for candidate/epoch selection and best-local selection, so reported selected-model VAL metrics are optimistic relative to a future held-out assessment. Highest AP does not guarantee greatest recall at the fixed 1% FPR point. This subphase neither calibrates that operating point nor changes the predeclared AP-based local selection rule. All models and predictions remain available for the explicitly accepted next subphase.

The organizations are simulated non-IID partitions of one RBA source dataset, and campaign observations are synthetic injections. Multiple alternative branches share background traffic, and the three seeds supply only three temporal blocks per split. Counts are benchmark User-times, not independent people or independent trials. Clean-negative candidates are not certified benign. No independent-company deployment claim, initialization confidence interval, or general detection-effectiveness conclusion follows from software test passes.

Resource numbers measure the actual implementation on a shared host. The comparator extracts seven-column root arrays once and trains from RAM; the accepted GraphSAGE training streamed sampled-block cache files across epochs. Input preparation and GraphSAGE VAL verification are measured separately. Therefore the previously measured GraphSAGE and newly measured MLP times are not an exclusive, input-I/O-matched architectural speed benchmark. Process peak working set includes library/runtime and data buffers; it is not model-tensor memory alone or a proven minimum hardware requirement.

All these limitations preserve the original framework and evaluation unit. No TEST outcomes, final threshold calibration, continuous inference, immediate indicator sharing, federation, DP or blockchain component is needed or authorized here. Subphase 5 remains unstarted pending explicit user acceptance of Subphase 4.
