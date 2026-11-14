# Phase 6 Subphase 0 readiness

Technical gate evidence is in `v1/input_inventory_v1.json`. User acceptance is required before Subphase 1. No model training or later subphase is authorized by this report.

## Authority and preservation

The controlling roadmap is `C:/Users/Gulso/Downloads/CredBlock_FL_Phase6_Implementation_Roadmap.md`, section 3. The original framework PDFs/diagrams were not supplied for independent inspection; the roadmap records their architecture. Direct workspace write access was verified with a temporary file, then the file was removed. Accepted Phase 5 sources, datasets and reports were not edited.

Final acceptance v2 supersedes the old conditional freeze/replay status flags. The installed rolling runtime and graph validator match its hashes. The inventory script verifies every frozen file's size and SHA256, all replay/label/observation schemas and branch manifest hashes, the campaign register's instance set, and all five representative checkpoint exports. It performs structural access checks on TEST files without outcome analysis or model selection.

## Contract and input interpretation

`configs/phase6_data_contract_v1.json` defines the proposed versioned contract. There are 513 separate campaign instances and 2,565 organization branches. Each branch has observations, replay evaluator data and sparse time-bounded User supervision. Historical warm-up is a bounded read-only view over original organization parquet sources, described by 45 history references. The input inventory records actual schemas, exact branch anchors/endpoints and manifest hashes, including split and seed.

All eight float32 features, their order, fixed transforms, local node keys, int64 bidirectional adjacency and exact temporal windows are preserved. Private node mappings never become numeric features. User labels join on organization, local User key and exact scoring time. Positive evidence expires after ten minutes; ambiguous and context-only states remain masked. IP nodes are unsupervised context. Do not infer benignness from background provenance.

The five packaged graphs/checkpoints are representative TRAIN/seed1001 examples at an endpoint, not the complete training corpus or starting states for earlier times. Checkpoints can resume only with compatible local organization, branch and chronological provenance. Sparse schedules include expiry transitions; a future loader must not carry an old positive beyond its expiry. That loader and sampling belong to later subphases.

## Validation

- Accepted runtime self-tests: 20 passed.
- Phase 6 schema/leakage tests: 33 passed, including exact real TRAIN observation/label joins for all five organizations, wrong-organization/time rejection, duplicate/invalid supervision rejection, IP masking and rejection of every enumerated evaluator column at runtime ingestion.
- Full frozen-byte verification and structural inventory results are recorded by the executable readiness audit in `v1/input_inventory_v1.json`.
- Graph output hash and private checkpoint mapping verification are recorded in `provenance_v1.json`.

The first inventory execution completed validation but failed at output-directory creation because a provenance file had been placed in the reserved directory during the run. That file was moved to the parent readiness directory and the audit was rerun. Only a successful saved inventory constitutes gate evidence.

## Limitations and next gate

No repository dependency specification/lockfile or research-results workbook was found. Actual package/device versions are captured in the inventory; this report and JSON records are the local research record. PyTorch emits a Python 3.14 TorchScript compatibility warning; training compatibility/resource readiness must be checked in its own subphase. No remote workbook was updated.

The full split/infrastructure audit, evaluation unit, FPR target, prevalence analysis and frozen experiment protocol belong to Subphase 1. They are not claimed complete here. User acceptance of the contract/readiness evidence is pending. The next exact action after acceptance is Subphase 1: chronological train/validation/test design.

## Progress tracker

| Subphase | Status |
|---|---|
| 0: readiness/data contract | Implemented and tested; technical audit evidence in v1; awaiting user acceptance |
| 1â€“9 | Not started |

Created files: `configs/phase6_data_contract_v1.json`, `src/phase6/readiness.py`, `tests/phase6/test_data_contract.py`, this report, and generated `v1/input_inventory_v1.json` / `provenance_v1.json`. Existing tracked files were not modified. No model artifacts were produced.

Reproduction: `.venv/Scripts/python.exe -B -m pytest tests/phase6/test_data_contract.py -q -p no:cacheprovider`. For a new inventory run, call `src.phase6.readiness.run()` with a new output directory; the default version refuses overwrite.
