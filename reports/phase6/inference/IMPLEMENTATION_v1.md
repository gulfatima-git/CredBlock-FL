# Subphase 6 implementation and artifact index

Subphase 5 is USER_ACCEPTED in the new append-only `reports/phase6/calibration/acceptance_v1.json`. All paths below are project-relative. No accepted source, checkpoint, threshold, prediction or protocol is rewritten.

## New code and configuration

- `configs/phase6/continuous_inference_v1.json`: local batching, observable target policy, heartbeat/end coverage, SQLite recovery, failure behavior, privacy and operational-metric scope.
- `src/phase6/inference_registry.py`: original local GraphSAGE/threshold bundle validation, schema/config/protocol/source hashes, frozen parameters and last-usable-bundle fallback. No remote or federated adoption.
- `src/phase6/local_inference.py`: persistent in-place graph update, observed/expired-node affected-neighborhood discovery, accepted sampling/inference, exact binary64 decisions and organization-local transactional logs.
- `src/phase6/inference_replay.py`: frozen observable-only VAL hour and causal seven-day warm-up. No label or evaluator Parquet is opened.
- `src/phase6/run_continuous_inference.py`: uninterrupted and restart-repeat orchestration, performance/resource evidence, private-store audit and all-five acceptance gate.
- `tests/phase6/test_continuous_inference.py`: 24 tests; synthetic failures and boundary/recovery cases are distinct from real end-to-end evidence.
- `prepare_subphase6.py`: one-time append-only acceptance, preservation inventory and pre-replay registry/policy freeze.

## New evidence

- `reports/phase6/inference/accepted_inputs_before_subphase6_v1.json`: 11,939 prior accepted/support file hashes, including ten thresholds, calibration helper and full original prediction/model evidence, plus the prior Excel master.
- `reports/phase6/inference/preregistration_v1.json`: fixed observed-target/recovery policy, original model/threshold registry, implementation/configuration hashes and unchanged professor-design document hashes. Written before real replay outcomes.
- `reports/phase6/inference/testing_results_v1.json`: exact test commands, pass counts, warnings, deliberate TEST-opening test exclusion and real integration scope.
- `reports/phase6/inference/v1/Org1/` through `Org5/`: source/configuration identity, uninterrupted and independent restarted replay summaries, per-command latency records, input hashes and artifact manifests.
- Each run's `private/inference.sqlite`: local command journal, ingestion-token ledger, per-User scores/alerts, model/threshold/schema versions, processing errors, accepted-runtime graph checkpoints and source cursor. Keep these local to that organization. Aggregate reports omit User IDs and raw records.
- `reports/phase6/inference/final_v1/`: created only after all five component checks pass. Acceptance report, aggregate full-precision summary and artifact hashes.
- `reports/phase6/progress_v7.json`: new append-only progress after the gate; Subphase 5 USER_ACCEPTED, Subphase 6 technical pass awaiting acceptance, Subphase 7 NOT_STARTED.

## Reproduction

```powershell
.venv/Scripts/python.exe -B -m src.phase6.run_continuous_inference --organization Org1
```

Repeat for Org2–Org5. Every writer refuses an existing run path; preserve all previous evidence and use an explicitly versioned new run when another execution is authorized. Then verify and report:

```powershell
.venv/Scripts/python.exe -B -m src.phase6.run_continuous_inference --finalize
```

## Metric definitions and limits

The primary demonstration is `CFV1_SO_CS_027_SEED1001_VAL`, one complete observation hour per organization. It includes observations after minute 50 and a final flush at end-exclusive minus one microsecond. Ten-minute heartbeats score observable recent Users; event commands score affected surviving Users from graph changes and expirations. No label or campaign membership chooses Users. The opaque branch namespace only preserves accepted sampler determinism and provenance.

The same persistent RollingGraph is mutated before scoring; checkpoint/recovery creates a new process-local object only on restart. Its event-to-alert path never trains or recalibrates. Raw observed timestamps remain timezone-naive with complete tied batches. Model/threshold/config/schema/protocol identities must match at startup and recovery. Post-mutation processing failure requires restart from committed state; no-alert is reserved for successful scoring below threshold.

Per-command end-to-end latency includes persistence and periodic checkpoints. Scoring-stage latency in each decision row is shared by the timestamp's scored Users, not a separately measured single-User latency. The summary reports an amortized processing cost per input event. Heartbeat, graph, sampling/feature and model stage costs remain separately inspectable in the latency records. The hypothetical serialized-server finish lag uses source timestamps and observed processing times, not a measured live broker queue. First local alert offset is not ground-truth time-to-detection.

These operational score counts have no ground-truth FPR/recall interpretation here. The calibrated 1% grid FPR is not transferred to arbitrary event/heartbeat scoring. No TEST observations or labels are opened; the later final TEST/version-control gate remains intact. One full hour in each organization does not establish full-variant detection effectiveness, million-node scale, production availability or tenant security. The producer watermark, scheduler daemon, alert delivery, archive compaction, deployment, indicators, federation, DP and ledger integration remain outside this subphase.
