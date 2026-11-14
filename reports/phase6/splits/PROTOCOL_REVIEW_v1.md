# Phase 6 Subphase 1 protocol for review

This subphase fixes the chronological experiment design. It does not implement a sampler, train a detector, calibrate thresholds or generate predictions. Subphase 0 was explicitly accepted; its append-only acceptance record is `reports/phase6/readiness/acceptance_v1.json`.

## Chronology and local state

All organizations retain the accepted half-open split bounds:

| Split | Inclusive start | Exclusive end |
|---|---|---|
| TRAIN | 2020-02-03 00:00 | 2020-10-01 00:00 |
| VAL | 2020-10-01 00:00 | 2020-12-01 00:00 |
| TEST | 2020-12-01 00:00 | 2021-03-01 00:00 |

These are calendar assignment boundaries, not claims of continuous labeled coverage. Phase 5 supplies only three one-hour replay blocks per split, repeated across controlled alternatives:

| Split | Seed 1001 start | Seed 1002 start | Seed 1003 start |
|---|---|---|---|
| TRAIN | Mar 1, 2020 13:00 | Mar 2, 2020 09:00 | Mar 3, 2020 21:00 |
| VAL | Oct 6, 2020 07:00 | Oct 6, 2020 19:00 | Oct 6, 2020 23:00 |
| TEST | Dec 12, 2020 06:00 | Dec 12, 2020 21:00 | Dec 13, 2020 17:00 |

Every replay ends exactly one hour after its start. Source timestamps remain timezone-naive. The full per-instance/organization assignments are saved by the audit. Each branch has its own persistent organization-local graph and seven-day causal warm-up, with tied timestamps consumed atomically. Graph snapshots are tensor views of that persistent state. Alternative branches never inherit one another's synthetic events. Earlier observed raw background may be context across a calendar boundary where it remains inside the seven-day window; that does not authorize fitting learned preprocessing on held-out data.

## Primary unit and threshold operating point

The primary unit is one eligible local User at a fixed grid time, keyed by variant, organization, User and scoring timestamp. Reuse Phase 5 grid offsets 0, 10, 20, 30, 40 and 50 minutes. Each label describes evidence in `(t-10 minutes,t]`, not a future bucket. The exact exclusive replay endpoint has no exported snapshot, so the last ten minutes have no endpoint primary grid score. This limitation is explicit; later continuous event-driven alert evaluation must remain separate from the grid FPR denominator.

All active Users are scoring candidates without consulting campaign membership or labels. Only eligible positive or clean-negative states enter supervised loss and primary metrics. Ambiguous, context-only, missing-label and IP states remain excluded. The full sparse event/expiry schedule is not an extra pool of independent training or evaluation examples. Exact expiry must be processed; old positive labels cannot persist indefinitely.

The predeclared primary validation FPR target is **1% per organization and detector**, with denominator equal to eligible negative User-grid examples. This research budget allows at most one false-positive decision per 100 eligible negative User-windows; it was fixed before detector outcomes. It is not a daily alert probability or deployment guarantee. Local calibration will use VAL only, preserve tied scores and obey `FP <= floor(0.01 * N_negative)`. Realized FPR, denominator and finite-sample resolution must be reported. No threshold is fitted in this subphase.

Per-organization results and equal-weight organization macro metrics are primary; pooled confusion counts are secondary. Report undefined organization metrics explicitly. Break down results by campaign seed and factor/family. Repeated backgrounds and only three temporal blocks per split limit uncertainty estimates: no IID confidence intervals over repeated rows or alternative branches.

## TEST and learned-state controls

TRAIN alone may fit learned preprocessing or model parameters. VAL controls hyperparameters, early stopping, comparator/model selection and threshold calibration. Existing fixed feature transforms require no learned statistics. Any later fitted state must carry its fit split, organization, cutoff, schema and hash.

TEST access in this subphase is confined to predeclared read-only integrity, temporal/infrastructure and descriptive prevalence checks. No scores, model outcomes or TEST-driven design choices are produced. `require_use` is a fail-closed policy guard for future pipeline entry points, not a claim that an unimplemented trainer is already isolated. Final TEST evaluation requires later model/threshold locking, explicit protocol acceptance and a version-control commit of the protocol before execution. No final TEST evaluation is authorized now.

## Evidence and preservation

The executable audit checks every branch's generation/replay assignments and file hashes; all stored event/label cutoffs; label evidence onset/expiry and masks; seven-day warm-up source coverage; synthetic attacker-IP intersections; fixed-grid coverage and label partitions; local distinct User counts and primary/sparse class counts. It reuses accepted Phase 5 representative feature/edge SQL-oracle evidence rather than claiming a new full graph-feature replay. No cross-organization User or credential index is created.

The initial audit attempt `v1` failed at DuckDB view creation after manifest verification. Its error record is retained. The corrected audit uses the relation API and a regression test. The successful run, if its `summary.json` records PASS, is under `v2`.

Frozen Phase 5 inputs and the accepted Subphase 0 contract are preserved. The new protocol is `configs/phase6/split_protocol_v1.json`; policy guards and the audit are `src/phase6/temporal_protocol.py` and `src/phase6/audit_splits.py`. New tests are `tests/phase6/test_temporal_protocol.py` and `tests/phase6/test_split_audit.py`. Generated CSV/JSON records document assignments, warm-up, intersections, class balance, input hashes and provenance. No research workbook was found; these are the local research records.

## Next exact action

Review the successful audit and accept this protocol, including the User-grid unit, 1% FPR budget and coverage/dependence limitations. Only after explicit acceptance begin Subphase 2 (6.2A GraphSAGE input and feature pipeline). Model training remains Subphase 3. Version-control commit is still required before later final TEST evaluation.
