# Phase 6 controlled interruption and recovery verification

Technical status: **PASS — saved-state recovery verification**. Production continuation remains **NOT AUTHORIZED**. Phase 6 remains IN_PROGRESS; Phase 7 remains UNSTARTED. This is neither final TEST acceptance nor a v4 execution approval.

## Authorization, prechecks and actual interruption

The explicit user authorization is preserved in user_authorization_record.json. Worker 22264, launcher 12092 and parent PowerShell 12764 were matched by creation time, command line and parent relationships. No duplicate evaluator was present. The inspected console contained those three processes plus the self-protected sender. Sixty-nine explicitly scoped reviewed source/configuration/evidence hashes and the v4 release identity matched before delivery.

Exactly one CTRL_C_EVENT was sent at 2026-11-18T13:33:49.091231+05:00. The API reported success. Worker and launcher exited by 13:33:53.600867+05:00 with observed Windows status 0xC000013A. The parent shell was subsequently absent in independent process queries. The original execution session recorded KeyboardInterrupt at the graph detection-view stage before the following prediction call, and session exit code 1. This was an arbitrary recoverable interruption, not a graceful or campaign-boundary shutdown. No retry, forced termination, suspension or evaluator launch occurred.

Evidence: live_preflight.json, live_recipient_scope.json, signal_attempt.json, signal_delivery_result.json, process_exit_observations.json, independent_exit_check.json and original_traceback_observation.json. The one-attempt marker must never be reused to send another event.

## Forensic preservation and SQLite

After independently establishing process absence and acquiring the original read-only execution lease, a separate forensic snapshot was sealed at reports/phase6/v2_forensic_v1/physical. It contains 51,690 files totaling 431,955,187 bytes and 30 database sets. Original and snapshot file hashes matched; every copied file was set read-only. This is hash-sealed, read-only preservation, not hardware WORM storage.

The first capture attempt failed when a second handle tried to read the byte-locked execution.lock. It had copied 51,688 files; only execution.lock and required_inventory.json remained. The failed attempt and diagnosis are preserved. A disposable fixture reproduced the Windows reader conflict. The additive second capture used the owning read-only lease handle, verified the existing copies, and added the missing two files without overwriting originals or prior copies. Final capture passed. This failure was not concealed or classified as source corruption.

All 30 forensic SQLite databases passed integrity_check. The complete inventory contains no nonempty WAL; database_derivations.json records every WAL/SHM presence or absence. No original database was opened through SQLite, checkpointed, repaired or deleted. Therefore the current production evidence establishes self-contained post-exit databases; it does not establish actual recovery of a nonempty production WAL. Reviewed WAL-aware support remains backed by its separate synthetic evidence. Sidecars that may have existed before process exit cannot be claimed to have been byte-captured before normal SQLite cleanup.

Targeted post-audit checks reconfirmed all 69 reviewed file hashes and all 30 original/snapshot database hashes. All ten selected model/threshold pairs match original identities, without model deserialization. Snapshot flags, full capture hashes, lock preservation and database derivations have separate evidence files.

## Completed campaigns independently verified

**5/171 campaigns are complete and independently verified.** There are 166 incomplete campaigns, consisting of one partially executed campaign and 165 not yet started. Completed campaigns retain their original completion provenance:

- CFV1_RA_CS_004_SEED1001_TEST
- CFV1_RA_CS_004_SEED1002_TEST
- CFV1_RA_CS_004_SEED1003_TEST
- CFV1_RA_CS_005_SEED1001_TEST
- CFV1_RA_CS_005_SEED1002_TEST

Each completed campaign passed the independent saved-evidence validator, including completion artifacts, all-five-organization coverage, fixed-grid metrics, operational sharing decisions, temporal attribution and censoring. Evidence is in completed_audits/<variant>/summary.json. Successful recovery is not a claim that all 171 scientific evaluations are complete.

## Reusable partial campaign

Variant: CFV1_RA_CS_005_SEED1003_TEST. It is explicitly NOT COMPLETE. Its incomplete state must not be reported as full-horizon detection or non-detection.

| Organization | Committed commands | Input events | Saved local scores | Grid bundles | Grid rows | Latest checkpoint sequence | Last committed time |
|---|---:|---:|---:|---:|---:|---:|---|
| Org1 | 271 | 267 | 2236 | 8 | 520 | 200 | 2020-12-13T17:33:39.445000 |
| Org2 | 270 | 266 | 2274 | 8 | 526 | 200 | 2020-12-13T17:33:40.595000 |
| Org3 | 395 | 391 | 3438 | 8 | 698 | 300 | 2020-12-13T17:33:40.072000 |
| Org4 | 393 | 389 | 3723 | 8 | 768 | 300 | 2020-12-13T17:33:31.688000 |
| Org5 | 361 | 357 | 3638 | 8 | 694 | 300 | 2020-12-13T17:33:40.735000 |

The partial campaign contains 15,309 reusable committed local scores and 3,206 committed grid rows. Across all 30 stores, 95,810 saved local scores passed exact finite-logit, binary64 threshold/decision, model, threshold and feature-schema identity checks. All 140 checkpoints and latest-checkpoint-plus-command recovery passed for every organization, covering 10,288 committed commands and replaying 390 graph commands after latest checkpoints. The completed/partial independent history audits additionally replay their required histories. Independent graph replay used **zero GNN forwards**.

The partial sharing chain has 1674 completed barriers; latest complete timestamp: 2020-12-13T17:33:40.735000. It preserves 62 indicator episodes and 248 receipts. Issuance, publication, recipient identity, availability, exclusive expiry and paired decisions were independently checked. Pending barrier details:

```json
[
  {
    "at": "2020-12-13T17:33:41.419000",
    "organizations": [
      "Org2"
    ],
    "stages": {
      "Org2": {
        "LOCAL": false,
        "ISSUANCE": false,
        "PAIRED": false
      }
    },
    "PUBLISHED": false
  }
]
```

Per-organization committed SQL without LOCAL publication and pending commands are recorded verbatim in incomplete_instance_assessment.json. Such committed predictions are reusable; missing publication is not permission to recompute them. Volatile work after the last durable command may have been lost. There is no claim to preserve an in-progress feature tensor or an uncommitted prediction. Future continuation may compute genuinely uncommitted work only after separate authorization.

## Gates and limitations

| Gate | Finding |
|---|---|
| Original worker/launcher exit and lease availability | PASS |
| Hash-sealed complete physical snapshot | PASS, after documented capture-reader correction |
| Thirty database integrity checks | PASS |
| Thirty checkpoint and graph recovery sets | PASS |
| Saved prediction, threshold and identity preservation | PASS |
| Five original completed campaign reconciliations | PASS |
| All-five-organization partial committed-prefix consistency | PASS |
| Scientific protocol/model/source preservation | PASS within explicit preservation scope |
| Recovered-state readiness for a separately authorized bounded v4 pilot | PASS; production integration still requires its explicit certificate/authorization gates |
| Actual nonempty production WAL recovery | NOT EXERCISED; no nonempty WAL found |
| Production v4 continuation/pilot | NOT RUN; separate authorization required |
| Full 171-instance TEST completion | PENDING |

Frozen protocol SHA256 remains 9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b. Reviewed v4 release remains 4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370. Frozen register remains d9e2b1a63308e00da05b5dac2afd83f27b259c006e69044f593130db0cc0aaef. No architecture, feature, sampling, threshold, split, scoring unit, attribution or evaluation denominator was changed. No training or calibration occurred.

This recovery assessment uses the established independent validator for completed campaigns and separately written offline partial-state checks; it is not a second evaluator or a claim of a newly independent implementation of every numerical primitive. Graph commands were replayed to verify state, never to repeat committed GNN inference. Shared-Parquet logical-versus-physical isolation limitations remain. Fixed-grid 1% VAL calibration does not imply 1% operational or TEST FPR. The accepted VAL finding remains 0/171 wholly undetected campaigns; it does not demonstrate recovery of campaigns missed by every organization. Accepted historical scope incidents and failed reviews remain untouched.

The reviewed v4 synthetic release evidence remains in reports/phase6/wal_continuation_v4_v1/TECHNICAL_ACCEPTANCE_REPORT.md. Its documented limitation remains: the full matrix was not rerun after three guard-only changes; focused final-source tests and static/certificate rechecks supported applicability. This recovery audit does not replace that evidence with an actual production-v4 result.

## Recommendation and next gate

The verified saved state is suitable for review of a separately authorized, bounded v4 continuation pilot. This report does not create a production continuation certificate, capture authorization or execution grant. Before any pilot: bind the reviewed release, original predecessor identities, sealed forensic evidence and all-five-organization committed boundaries; validate the required v4 authorization/certificate gates; write only in a separate v4 namespace; reuse the five original completions and committed partial predictions without GNN repetition; and independently reconcile the pilot before considering the remaining run.

No production-equivalent v4 runtime was measured here. Prior indexed-journal/synthetic speedups cannot establish a reliable remaining-run ETA; a separately authorized bounded pilot must measure it. Full scientific completion remains pending all 171 instances and final independent validation. Stop here for the user's decision.
