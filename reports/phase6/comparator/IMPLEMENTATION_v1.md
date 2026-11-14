# Subphase 4 implementation and artifact index

Scope: 6.2C only. Subphase 3 acceptance is recorded in the new append-only `reports/phase6/training/acceptance_v1.json`. No earlier artifact was rewritten. All paths below are project-relative.

## New source and frozen scientific specification

- `configs/phase6/non_graph_comparator_v1.json`: feature schema, MLP family, two candidate widths, optimization budget, seeds, AP/BCE best-local selection and unchanged 1% FPR target.
- `src/phase6/comparator_data.py`: projection of the seven permitted raw root-User features, exact identity/mask/cutoff checks, immutable accepted-cache readers and audit tensors. No graph aggregation in comparator inputs.
- `src/phase6/non_graph_comparator.py`: tensor-only MLP, TRAIN-only masked optimization, VAL early stopping and selection, metric reuse, safe checkpoint loading, and exact selected-candidate retraining.
- `src/phase6/run_local_comparator.py`: representative/full execution, exact paired GraphSAGE checkpoint/CSV comparison, resource and provenance records, best-local records and five-organization final verification.
- `tests/phase6/test_non_graph_comparator.py`: 34 input, leakage, split, masks, identity, fairness, selection, repeat and representative-gate tests.
- `tests/phase6/test_comparator_behavioral_features.py`: two independent observed-event oracles. Other Users sharing an IP do not change the tabular User feature vector.
- `prepare_subphase4.py`: one-time append-only acceptance, preservation inventory and preregistration preparation; not a training entry point.

## New evidence

- `reports/phase6/comparator/accepted_inputs_before_subphase4_v1.json`: 11,691 pre-existing files, including every accepted Subphase 3 history, repeat, checkpoint and prediction file; byte hashes verified before final acceptance generation.
- `reports/phase6/comparator/preregistration_v1.json`: written before any comparator trial or comparison; pins configuration/source and the roadmap, implementation plan, framework and two professor diagrams.
- `reports/phase6/comparator/testing_results_v1.json`: exact automated commands, 152 distinct passing tests, the one deliberate TEST-opening test exclusion and representative evidence scope.
- `reports/phase6/comparator/representative_v1/Org1/`: one fixed real branch, maximum three epochs, exact repeat. This is not full comparison evidence.
- `reports/phase6/comparator/full_v1/Org1/` through `Org5/`: full independent runs, all candidates/epochs/checkpoints, exact repeated fits and prediction CSVs, selected TRAIN diagnostics, root-only tensors, snapshot configurations, feature schema, protocol, provenance, resource measurements and best-local records. Local IDs and row-level records are private local audit artifacts.
- `reports/phase6/comparator/final_v1/`: created only after all five full components pass; acceptance report, full-precision machine-readable summary, five standalone selected comparator checkpoints and artifact hashes.
- `reports/phase6/progress_v5.json`: new append-only progress record after the full gate; Subphase 3 USER_ACCEPTED, Subphase 4 technical gate passed awaiting user acceptance, Subphase 5 not started.

## Reproduction and limits

Run from the project root with its existing virtual environment. Never rerun into an existing output directory; all writers refuse overwrites. The accepted graph model and all graph caches are read-only. The preregistered core source/config hashes are checked at entry and completion of every run.

Full run entry point (each organization has its own output directory):

```powershell
.venv/Scripts/python.exe -B -m src.phase6.run_local_comparator --organization Org1 --mode full
```

Repeat with Org2–Org5. Then verify all five components and generate the final report:

```powershell
.venv/Scripts/python.exe -B -m src.phase6.run_local_comparator --finalize
```

Each trial has CPU two-thread Torch execution; exact library/platform versions, observed RSS/peak working set and elapsed/CPU times are recorded per organization. These measurements include the already accepted cache extraction/GraphSAGE verification separately from training. There is no GPU dependency or newly installed library. They do not establish minimum RAM requirements for future full-scale continuous deployment.

Validation AP selection is a ranking criterion, not a claim of best recall at 1% FPR. Threshold calibration and held-out TEST evaluation remain future steps. Both detector families are retained even when one loses. No new artifact implies an improvement from graph structure. No continuous inference, indicator sharing, federated training, privacy mechanism or blockchain component is introduced.
