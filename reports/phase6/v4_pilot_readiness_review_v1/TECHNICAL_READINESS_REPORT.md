# Phase 6 v4 bounded pilot — independent execution-readiness review

**Recommendation: REVIEW_REQUIRED. Do not execute.** Integrity, artifact and one-campaign scope gates pass. Available-memory headroom is not established, and execution permission remains intentionally NOT GRANTED. No evaluator was launched, approval created, draft modified, model loaded for inference or campaign audit repeated.

## Gate findings

| Gate | Finding |
|---|---|
| Git commit a7adf15f0f9b97d062b9e91d784483457bdf67d0; no tracked/staged changes | PASS |
| Reviewed v4 release identity and frozen metadata/register/model/threshold identities | PASS |
| Four artifact/index SHA256 hashes, certificate checksum and cross-links | PASS |
| Capture preparation authority is preparation-only | PASS |
| Existing execution draft remains unchanged and rejected by production guard | PASS: exact existing message `Unapproved/stale v3 execution` |
| Original evaluator/associated Python writers absent; read-only original lease available | PASS at review time; only unrelated VS Code formatter Python process observed |
| Source stable; original/forensic census and narrow content anchors unchanged | PASS within the verification scope described below |
| Five completed campaign provenances retained without execution | PASS |
| Campaign-6 boundary: 1,690 commands, 15,309 scores, 40 grid bundles | PASS |
| All five recovered graph/checkpoint/journal identities | PASS using unchanged independently validated capture and fresh anchors |
| Committed prediction/grid reuse path and prefix-integrity checks | PASS by unchanged source inspection plus accepted real-prefix/synthetic recovery evidence |
| One proposed campaign, maximum one newly completed instance, no campaign-7 fallthrough | PASS |
| Planned continuation output is new and separate | PASS: directory does not exist |
| Recovery, sealing and independent reconciliation mechanisms available | PASS by source/evidence review; actual resumed behavior remains unexecuted |
| Disk capacity for observed storage/restoration baseline | PASS with limitations; no certified future peak bound |
| RAM capacity / avoidance of excessive paging | REVIEW_REQUIRED |
| Separate execution authorization | NOT GRANTED, as required |

Release identity: `4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370`. Certificate identity: `67ebdf7a895995729235091d85c40d68c2a0659576d74494b7e9e8b3331c116d`. Frozen protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`. Source and model/threshold archives were narrowly hashed; no model deserialization or GNN execution occurred.

## Prepared artifacts and recovery integrity

All four artifacts match prepared_artifact_index.json: the source-quiescence attestation, capture-only preparation approval, WAL-aware predecessor certificate and non-executable PILOT_ONLY grant draft. The certificate pins the capture approval, which pins the attestation; source/capture/catalog/release relationships and the full frozen 171-instance inventory digest agree. Draft status remains DRAFT_PILOT_ONLY_EXECUTION_NOT_AUTHORIZED with explicit_user_decision=false and execution_authorized=false. Its proposed variant is only CFV1_RA_CS_005_SEED1003_TEST. It cannot itself authorize execution. No new approval or grant was written.

The existing full original/forensic hash audit and independent preparation audit were reused after verifying their preserved file hashes. Fresh checks covered original read-only lease/stability, all 51,690 original/forensic inventory and metadata entries, forensic read-only flags, the five original completion-manifest anchors, campaign-6 database/WAL absence and derived-image hashes, all certified grid/sharing journal segment hashes, frozen protocol/register metadata and ten narrowly identified model archives. No broad repository-wide checksum sweep, fresh full 51,690-content-hash scan, SQLite inspection or scientific campaign evaluation was repeated. This scope is not a claim of a new full byte audit or protection against an adversary rewriting files while preserving all metadata. Existing reader gates will verify certified source bytes again before continuation.

The five completion hashes agree with their previous independent audits. They will enter the mixed-origin ledger as REUSED_COMPLETE_V2 references; their evaluation paths are not executed. Campaign 6's five stores match the prior graph/token/command/score boundary. Existing evidence preserves 40 bundles / 3,206 grid rows, 1,674 completed barriers and the single pending Org2 barrier at 2020-12-13T17:33:41.419000 before SQL commit/publication. No partial campaign has been marked complete. All actual production WALs were absent at capture; real nonempty-WAL recovery remains unexercised.

The coordinator returns saved PAIRED decisions for completed barriers and loads saved LOCAL artifacts where present. The grid loop returns existing GRID_COMMIT raw scores instead of recapturing/scoring them. Workspace recovery verifies original score/command/token/checkpoint prefix digests. The actual certified prefix has all 1,690 durable local commands already published; committed results are reused. The pending uncommitted command and missing future grids/operational flush may be computed only after separate approval. Accepted tests support interruption/recovery equivalence; no fresh original GNN run was performed to compare new unseen predictions.

The production inventory loop handles original completions by reference, checks permits_variant before any new instance and ends with BOUNDED_EXECUTION_COMPLETE_FULL_RUN_PENDING under PILOT_ONLY. With exactly one allowed variant, campaign 7 and the other 165 unstarted instances are skipped, not executed. The one-instance limit is the allowed variant list, not merely an informational maximum field. The current draft is rejected even before that loop or a backend is opened. The designated future directory is reports/phase6/heldout_test_v2/wal_v4_transition/pilot_campaign6_v1 and remains absent.

## Current resource assessment

Read-only Windows sample window: 2026-11-18T23:50:57.7613341+05:00 through 2026-11-18T23:51:00.5138705+05:00 (Asia/Karachi). Usable physical RAM: **15.70 GiB**. The earlier OS free-memory snapshot was 0.98 GiB; the subsequent three AvailableBytes samples were **0.80–0.84 GiB**, approximately 5.1–5.3% of physical RAM. These counters were sampled at different times and are reported separately.

Commit usage was 69% of the approximately 40.7 GiB commit limit. Disk-backed page-read operations were [119, 7, 852] per second; pages-per-second samples were [1431, 26, 7968]. The pagefile had 3.49 GiB current usage of 25.0 GiB allocated. These short samples establish paging activity and low headroom; they do not prove sustained thrashing, attribute page reads to one application or predict a failure.

The real v2 worker evidence recorded working sets of 0.617–0.619 GiB and private allocation of 1.093–1.095 GiB. These two historical samples concern the same accepted local evaluation architecture, but a different point in its run. Private allocation is not necessarily resident RAM; neither measure is a measured peak or a production-v4 upper bound. V4 additionally retains indexed journal/recovery structures and may have transient setup/graph/batch allocations. The accepted evidence contains no measured real v4 peak with which to establish adequate current headroom. It would be unsupported to declare memory PASS or invent a minimum-RAM threshold.

C: has **198.6 GiB free**. The certificate's known initial restoration payload is 92.5 MiB before filesystem/staging/metadata overhead. Five existing complete v2 campaign directories occupy 55.9–116.1 MiB each in the sealed inventory. That supports a substantial disk margin for the observed workload, while future v4 output, staging, duplication and pagefile peak remain unmeasured. Disk is not the observed blocker. No new execution-runtime estimate or synthetic-to-production speedup is asserted.

## Unresolved blockers and next action

1. Memory capacity remains REVIEW_REQUIRED: sufficient headroom and avoidance of excessive paging have not been established from real evidence. Do not launch under a capacity PASS claim. No application was terminated, Windows setting changed, batch reduced or scientific computation weakened.
2. The user has not granted execution authorization. The reviewed draft must remain untouched and non-executable.

Next safe action is user review of this report and resolution of the capacity uncertainty, followed by a fresh short resource/readiness check. No extra model/inference benchmark is implicitly authorized. If capacity is subsequently supported and the user separately approves execution, prepare a **new**, release/certificate-bound approved grant for exactly campaign 6 / maximum one newly completed campaign, preserve the present draft, recheck source/process/lease/identities, launch one evaluator with measured resources/reuse counts, independently validate and stop at bounded completion. Do not authorize or start the remaining full run through that decision.

The frozen method, five local User–IP graphs, accepted GraphSAGE architecture and all thresholds/features/sampling/evaluation rules remain unchanged. The accepted VAL result of 0/171 wholly undetected campaigns, fixed-grid versus operational FPR distinction, shared-Parquet isolation and attribution/censoring/factor-design limits remain. No scientific claim about recovery of wholly missed campaigns or federation is added. Phase 6 remains IN_PROGRESS at five complete and one partial campaign; Phase 7 remains UNSTARTED.

**Stop here for separate user review. No pilot execution or approval activation was performed.**
