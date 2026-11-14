# Phase 6 Subphase 2 (6.2A): GraphSAGE input and feature pipeline

**Technical exit gate: PASS; Subphase 2 user acceptance pending.** Subphase 1 is recorded as **USER_ACCEPTED** in a new append-only `reports/phase6/splits/acceptance_v1.json`. The successful Subphase 1 v2 evidence, accepted Subphase 0 outputs, accepted Phase 5 runtime and frozen split protocol are preserved.

Frozen protocol SHA256:

`9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`

No split assignments, grid offsets, evaluation units or the 1% FPR target were amended. A protocol commit in version control remains a prerequisite before final TEST evaluation. No final TEST evaluation, model training, learned preprocessing, federation, differential privacy or blockchain component was run or implemented.

## Implemented

The new pipeline wraps `src.organization.rolling_graph_v1.OrganizationGraphRuntime` and reuses the accepted Subphase 1 split, exact-label and checkpoint policy. It loads frozen observations and seven-day warm-up sources with verified hashes, advances one persistent local runtime chronologically, consumes complete tied timestamp batches and exposes only approved fixed-grid as-of views. Exact-grid supervision is loaded separately and validated by organization, local User key, branch, split and time.

The feature allowlist specifies the eight existing ordered float32 features, source fields, node applicability, aggregation windows, availability, missing-value behavior and inference justification. No feature was added to the accepted runtime. Counts use fixed log1p transforms and the accepted failure ratio; no scaler/encoder is fitted.

Sorted CSR supports deterministic uniform neighbor sampling without replacement. Per-layer blocks preserve the true retained bipartite User-IP edges. Fanouts `[15,10]`, two layers, batch size 256 and seed 60201 are versioned pipeline defaults; they are not a validation-selected model architecture. All hops are sampled from the same immutable graph as of root scoring time, using seven-day retention and ten-minute features. Layer-specific destination-prefix routing supports GraphSAGE without adding temporal-GNN components.

PyG packets contain exactly `x`, `edge_index` and `num_nodes`. Root labels/masks, private local keys, row routing and evaluator provenance remain separate. Only User roots are targets; IP nodes remain context. New Users and IPs use observed features and neighborhood structure without a learned ID vocabulary. Full-grid target joining occurs once per batch iterator, and the default iterator covers all active User roots without label-dependent selection.

See `src/phase6/INPUT_PIPELINE_v1.md` for the public interface, block alignment and future forward-pass contract. Later layers consume prior hidden state rather than resetting to their raw inspection features. No GraphSAGE model class was introduced in this subphase.

## Validation and measurements

Final command:

`.venv/Scripts/python.exe -B -m pytest tests/phase6 -q -p no:cacheprovider`

Result: **85 passed, one warning**, in 42.73 seconds. Tests cover deterministic sampling across calls/instances/root partitions, changed seeds, exact block chaining, full-neighbor reference sets, mask/label separation, invalid/IP targets, cross-scope supervision, future snapshot isolation, expiry, new User and IP handling, monotonic real-data grid loading and rejection of TEST fitting. The warning is the existing PyTorch/Python 3.14 TorchScript compatibility warning.

Successful final benchmark command:

`.venv/Scripts/python.exe -B -m src.phase6.validate_input_pipeline --output reports/phase6/pipeline/v2`

Result: exit code 0, **30/30 independent SQL feature/edge checks** over six approved grids for all five organizations in `CFV1_SO_CS_027_SEED1001_TRAIN`. Each organization produced a separate example model batch, root supervision file, private routing file and provenance record. The independent oracle may read future rows to check exclusion; runtime/model inputs consume only observations available by the scoring time. TRAIN is the only real split used for batch/resource validation. A TEST manifest was read in a rejection unit test; no TEST outcomes or model-selection operation was used.

| Organization | Real graph node range | Mean snapshot/CSR time, ms | Mean batch/supervision time, ms |
|---|---:|---:|---:|
| Org1 | 67,092-67,198 | 498.80 | 846.41 |
| Org2 | 70,754-70,873 | 500.62 | 48.40 |
| Org3 | 74,684-74,868 | 881.76 | 85.12 |
| Org4 | 77,481-77,631 | 1,205.25 | 105.49 |
| Org5 | 81,136-81,331 | 588.93 | 53.49 |

These are input-pipeline timings, not detector inference latency. The first Org1 batch includes a cold PyG import (4.855 seconds); the remaining Org1 batches are about 42-49 ms. Reported means intentionally retain that cold-start cost. The benchmark demonstration roots are selected using observable recent activity, not labels; the production-facing iterator supports every active User. Exact per-grid counts, tensor sizes, retained events and whole-process RSS are in `v2/representative_checks.json`.

The structural capacity smoke used **1,020,000 synthetic nodes and 2,040,000 directed edges**. CSR construction took 0.660 seconds; one 256-User batch took 0.182 seconds. Full view tensors were 65,280,000 bytes; CSR was 24,480,008 bytes; sampled model tensors were 57,504 bytes. Whole-process RSS was 720,805,888 bytes and process peak RSS was 765,566,976 bytes. These memory figures include Python, PyTorch, retained objects and preceding benchmark activity; they are not isolated per-graph memory. The synthetic graph has degree two and does not establish throughput on real million-node traffic or high-degree adversarial graphs.

## Preservation, provenance and research records

The final validator verified the hashes of all read frozen inputs/configurations and the **29-file pre-change preservation baseline**. That baseline includes accepted Subphase 0/1 reports and successful v2 audit files, the split/data contracts, prior Phase 6 code/tests and the rolling runtime. It passed unchanged. Accepted Phase 5 files were read only. Configuration, source, architecture-source and output hashes are saved with the final benchmark.

Original architecture sources were located and inspected this time: `CredBlock_Implementation_Plan.pdf` (especially pages 9-10), `CredBlock-FL_Final_Framework_Explained.pdf` (especially pages 2-3), and the original detection-mechanism and workflow PNGs, all in Downloads. Their hashes are in `v2/input_provenance.json`. They confirm one persistent local graph shared by periodic training and continuous scoring, User targets, IP context and GraphSAGE with temporal features. No later-phase loop was implemented.

A new research-results workbook was created at `outputs/phase6_subphase2_v1/CredBlock_FL_Phase6_Input_Pipeline_v1.xlsx`. The original Phase 5 research workbook in the research folder was preserved. The new workbook contains measured inputs, formula-based organization summaries, acceptance status and provenance. Rendered summary/detail ranges were visually checked. Its 25 cached summary values agree with independent calculations, it contains zero Excel error cells, and a saved/reopened copy recalculates correctly in Artifact Tool under a temporary input change followed by restoration. Native Excel recalculation was not tested. The exporter returned code 1 despite completing the export; this anomaly is retained here, and archive/content/recalculation verification succeeded independently. No online workbook was modified.

## Execution history and limitations

The first focused test run had 18 passes and one incorrect expiry-test assertion: it expected one edge in every layer, although an earlier context block legitimately includes both retained directions. The assertion was corrected to the exact retained edge sets. The complete suite then passed 84 tests. A further unlabeled split-boundary guard and regression test brought the final suite to 85 passes. Both resource runs passed; `v1` is the initial development benchmark, and `v2` is the final source-pinned run with per-organization memory measurements. No failed check is presented as a pass.

Real integration remains representative: one TRAIN branch/seed across five organizations, not all 2,565 branches or held-out predictive evaluation. Inductive input representation is tested; trained predictive inductive performance remains Subphase 3. Resource values are host observations, not guarantees. Later training must preserve this exact split/grid/FPR/evaluation-unit protocol, use TRAIN/VAL-only selection and archive schema/preprocessing/sampler state with each model run.

## Files created

- `reports/phase6/splits/acceptance_v1.json`
- `configs/phase6/feature_allowlist_v1.json`
- `configs/phase6/neighbor_sampling_v1.json`
- `src/phase6/input_pipeline.py`
- `src/phase6/validate_input_pipeline.py`
- `src/phase6/INPUT_PIPELINE_v1.md`
- `tests/phase6/test_input_pipeline.py`
- `reports/phase6/pipeline/accepted_inputs_before_subphase2_v1.json`, final benchmark `v2`, retained development benchmark `v1`, this report, workbook verification/support records and final `verification_v1.json`
- `reports/phase6/progress_v3.json`
- New Phase 6 research-results workbook under `outputs/phase6_subphase2_v1`

Existing accepted files were not modified. Only new Subphase 2 draft files were iterated; workbook draft backups were retained before layout edits.

## Progress and next action

Subphases 0 and 1: USER_ACCEPTED. Subphase 2: technical gate passed, awaiting explicit user acceptance. Subphases 3-9: not started. The next exact action is review/acceptance of these input-pipeline outputs; only then begin Subphase 3 (6.2B), five independent local GraphSAGE models. Final TEST evaluation remains unavailable until the frozen protocol is recorded in version control and the later model/threshold gates are complete.
