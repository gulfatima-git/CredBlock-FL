# Phase 6 Subphase 6 (6.4): Continuous Local Inference

**Technical gate: PASS; user acceptance pending.** Subphase 5 USER_ACCEPTED is recorded append-only in calibration/acceptance_v1.json.

## Implemented local event-to-alert workflow

Each organization has its own hash-verified original GraphSAGE model, sealed threshold and SQLite store. Complete timestamp batches update the same accepted seven-day RollingGraph object before feature export and scoring. An additive adjacency index selects surviving User nodes in pre/post two-hop closures of endpoints changed by observations or ten-minute/seven-day expiration. Ten-minute heartbeats and a final-hour flush additionally score observable recent Users. Labels, target membership, attacker metadata and credentials are absent from the service and replay loader. The accepted sampler/schema/transforms/fanouts/seed are unchanged. No optimization or recalibration occurs.

The exact binary64 helper compares unrounded logits against the original frozen threshold. Every decision logs local User, timestamp, trigger, exact logit/threshold encoding, model/schema/threshold versions, alert/no-alert, processing status and scoring-stage latency. Commands record graph/feature/model costs; external per-command measurements include persistence and checkpoint costs. Failure records never become no-alert decisions.

SQLite WAL with synchronous FULL commits input commands/tokens, decisions and state digest atomically. Accepted-runtime graph checkpoints are saved periodically and at final flush. Restart validates org/stream/bundle/config/source identities, restores a hashed checkpoint, replays committed commands without duplicating alert records, restores input cursor and verifies state. Failed post-mutation processing faults the client until recovery. Invalid registry candidates are rejected while retaining the last usable original bundle. This is local hash validation, not federated/Fabric adoption.

## Per-organization real full-hour evidence

| Organization | Events | Timestamp commands | User scores | Alerts | No-alert | Final-ten-minute events | End-to-end p95 (s) | Model p95 (s) | RSS peak MiB | Exact restart repeat |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Org1 | 578 | 585 | 4438 | 122 | 4316 | 109 | 2.376632 | 0.173589 | 471.398 | Yes |
| Org2 | 567 | 574 | 4859 | 468 | 4391 | 84 | 2.606036 | 0.189490 | 475.621 | Yes |
| Org3 | 617 | 624 | 5749 | 482 | 5267 | 104 | 2.678882 | 0.188831 | 480.949 | Yes |
| Org4 | 626 | 633 | 5862 | 379 | 5483 | 112 | 2.799706 | 0.194821 | 483.848 | Yes |
| Org5 | 669 | 676 | 5474 | 615 | 4859 | 123 | 2.899579 | 0.209082 | 487.238 | Yes |

All five primary runs and five independent restart repeats consume the entire observation hour, including events after minute 50, and flush at the last microsecond before the exclusive end. Source counts, final graph bytes and canonical score/alert records match exactly between uninterrupted and restarted execution. The restart point deliberately falls after a checkpoint so committed journal replay is exercised.

Full precision measurements, p50/p95/p99/max graph/feature/scoring/end-to-end costs, observed replay throughput, hypothetical serialized-server backlog, first local alert offset, final-ten-minute score counts, recovery costs and redacted alert/no-alert examples are in summary.json. Private per-User decision and raw-event journals remain in each organization directory. All processing failures in valid real replay are zero. Synthetic failure, schema and restart cases are recorded separately in automated test evidence.

## Evidence scope and research boundaries

The predeclared demonstration is one full frozen VAL branch (CFV1_SO_CS_027_SEED1001_VAL) in every organization, not all 513 alternative worlds, million-node operational benchmarking, TEST evaluation or deployed live traffic. The independent repeat restarts midway and verifies exact recovery. Sampling and target selection are deterministic functions of observable graph history, clock and local namespace. The namespace is used only by the accepted sampling policy and source audit, not as a numeric feature or target-selection oracle.

Operational scoring units are event/heartbeat-triggered local User scores. They are distinct from the accepted eligible fixed-grid User-windows. No operational FPR/recall is calculated or claimed, and calibrated 1% VAL grid FPR does not imply 1% on arbitrary event scoring. Positives/labels are not opened here. Local first-alert offset is not ground-truth time-to-detection; later offline evaluation can join complete private logs, including the final ten minutes, under its own authorized protocol.

The replay adapter buffers a complete timestamp group; a real live producer still needs a completeness/watermark contract. Earlier/repeated timestamps and duplicate tokens fail before graph mutation. The proof adapter is VAL-only and rejects TEST before source access; deployment and authorization of other replay periods require a later explicit protocol/adapter decision. SQLite storage and process boundaries are logically organization-local on one research host, not production tenant security. The command/decision journal is retained for audit and has no production archival/compaction policy yet.

Feature export and CSR construction still scan the accepted retained graph. Observed shared-host CPU/memory/throughput on the representative graph do not establish million-node or production scalability. Event-driven sampling may vary with timestamp by the accepted policy; the affected-node policy does not promise rescoring every otherwise unchanged User on every event. No external alert-delivery system, real-time scheduler daemon, indicator sharing, federation, DP or blockchain is implemented.

## Tests, provenance and preservation

See ../testing_results_v1.json and ../preregistration_v1.json for exact commands, scientific policy and source pins. Unit tests cover duplicate/out-of-order data, complete tied timestamps, label/metadata rejection, causal views, expiration boundaries, neighborhood targets, graph identity, startup/model/schema mismatch, retained fallback, atomic failures, tampered checkpoints and committed-journal restart. Real integration and its resource evidence are distinct from synthetic tests.

All 11939 inventoried prior accepted/support artifacts remain byte-identical, including all ten threshold JSONs, comparison and calibration results, original validation predictions, both model families, binary64 helper, feature schema and frozen protocol. Protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

A version-control commit of the frozen protocol remains required before any later final TEST evaluation; this subphase does not certify that commit. Review and explicitly accept Subphase 6 before Subphase 7.
