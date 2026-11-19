# Phase 6 v4 bounded pilot — preparation technical report

Status: **PASS for preparation and saved-evidence validation only. EXECUTION NOT AUTHORIZED.** Production pilot: NOT RUN. Execution readiness: BLOCKED pending independent user review, separate explicit approval and fresh host/capacity/identity gates. No USER_ACCEPTED decision is recorded.

## Exact scope and authorization

Only `CFV1_RA_CS_005_SEED1003_TEST` is listed in the draft PILOT_ONLY inventory. Maximum newly completed instances is one; no campaign 7, no other new campaign, no full-run launch and no Phase 7. Five original completed campaigns are provenance-only reuse references. The current user decision authorized capture/certificate/grant preparation, not TEST execution.

The capture-only approval uses the reviewed capture status because capture preparation was explicitly authorized. It is marked PREPARATION_ONLY_NO_EXECUTION. The execution draft instead has status DRAFT_PILOT_ONLY_EXECUTION_NOT_AUTHORIZED, explicit_user_decision=false and execution_authorized=false. Calling the unchanged production readiness guard with it was rejected with the exact legacy error string `Unapproved/stale v3 execution`. This is the existing v4 guard's inherited message; it is not a version change or a failed negative test. No backend, driver, model or continuation workspace was instantiated.

## Gates

| Gate | Finding |
|---|---|
| Committed release, 135 committed bytes and defined Git cleanliness | PASS |
| Explicit untracked-path inventory / exclusion, no existing entries changed or ignored | PASS: 10,722 status entries and 82,930 expanded untracked paths at inventory time |
| Process absence, original read-only lease and source stability | PASS at preparation time |
| Complete original/forensic preservation | PASS: all 51,690 original files and forensic copies hashed against the sealed inventory; snapshot read-only attributes verified |
| Frozen metadata/register/source identities and ten model archives | PASS; archives hashed only, not deserialized |
| WAL-aware production capture and predecessor certificate | PASS within actual no-WAL condition |
| All-five-organization graph/checkpoint/token/command/score recovery | PASS through unchanged reviewed reader; zero GNN forwards |
| Five completed original completion proofs | PASS, original SHA identities agree with previous independent audits; none executed |
| Exact campaign-6 boundary and journal/grids | PASS |
| Nonexecutable certificate-bound one-instance draft | PASS; independently rejected by production execution guard |
| Independent prepared-artifact reconciliation | PASS |
| Post-preparation hashes / original and forensic census / thirty DB-set hashes | PASS |
| Actual execution or post-pilot metrics | NOT RUN |
| Fresh execution capacity | REVIEW_REQUIRED, not certified by this preparation |

Git commit remains a7adf15f0f9b97d062b9e91d784483457bdf67d0. Release identity remains `4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370`. Frozen protocol SHA256 remains 9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b. No tracked or staged changes were made. Untracked research paths were inventoried using Git filename metadata; their contents were not broadly opened or hashed. The authorized original run and forensic evidence were separately hash-verified. No existing Git ignore rules were changed, no entries staged, no commit/tag created and no cleanup of the existing research tree was performed.

## Exact prepared artifacts

Certificate identity: `67ebdf7a895995729235091d85c40d68c2a0659576d74494b7e9e8b3331c116d`.

- source_quiescence_attestation: `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\heldout_test_v2\wal_v4_authorizations\source_quiescence_preparation_v1.json`; SHA256 `c23401d3ed0474f11150eeb167eec332fc1d647338edbcf589d5651e1c7d8f32`.
- capture_preparation_approval: `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\heldout_test_v2\wal_v4_authorizations\capture_preparation_only_v1.json`; SHA256 `829b036465824176347244a7e611fa63b29e7e579c7067f7ca0ad7f5a965d8ea`.
- predecessor_certificate: `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\heldout_test_v2\wal_v4_captures\pilot_preparation_v1\CFV1_RA_CS_005_SEED1003_TEST\predecessor_certificate.json`; SHA256 `dc4a59bf2c917425dba4c9a24b164ad88f370844f55a0e4ceb5176e31505bd72`.
- NONEXECUTABLE_PILOT_ONLY_grant_DRAFT: `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\heldout_test_v2\wal_v4_authorizations\pilot_campaign6_execution_DRAFT_v1.json`; SHA256 `2be53cf37ea0616dafddb3b31850de1ebe3aa2f123d538e44af035f181d8670a`.

Each is also indexed in prepared_artifact_index.json. The draft binds the certificate file hash/ID, release/source hashes, catalog, original 171-instance register identity, future separate output root and exactly one variant. The designated future continuation root is `C:\Users\Gulso\Documents\Gul\CredBlock-FL\reports\phase6\heldout_test_v2\wal_v4_transition\pilot_campaign6_v1` and it does not exist. Production capture outputs and derived SQLite/oracle copies exist only in the designated new WAL-v4 capture namespace. They contain private saved research state and must remain excluded from Git. The untracked pathname inventory is also local-only metadata, not a proposed Git deliverable.

## Independently checked reusable state

| Organization | Committed commands | Saved local scores | Derived-state audit |
|---|---:|---:|---|
| Org1 | 271 | 2236 | PASS |
| Org2 | 270 | 2274 | PASS |
| Org3 | 395 | 3438 | PASS |
| Org4 | 393 | 3723 | PASS |
| Org5 | 361 | 3638 | PASS |

Total: 1,690 committed commands and 15,309 local scores. Forty grid commits preserve the previously validated 3,206 grid rows. There are 1,674 complete global timestamp barriers; the latest is 2020-12-13T17:33:40.735000. A single pending Org2 barrier at 2020-12-13T17:33:41.419000 has no SQL commit, LOCAL, issuance, publication or paired decision. It is uncommitted work, not a completed or reusable prediction. Original per-organization clocks, offsets, checkpoint identities, score rows and all journal chains match the prior independent recovery evidence.

The separate audit checked derived SQLite integrity, byte equality to the preserved original main files in the actual absent-WAL case, exact stored binary64 logits/threshold decisions and model/threshold identities, command/token/score counts, journal chain linkage, completed/pending barrier counts and original completion references. It never queried an original SQLite database. Reviewed capture verification additionally replayed committed graph commands and reconciled committed SQL with saved LOCAL/grid evidence. Replaying graph commands is distinct from rerunning GNN inference. Saved scores remain exact; no new scores or scientific metrics were generated.

All five original main/WAL/SHM/rollback sets are recorded, with all five actual WALs absent. New standalone derived images agree with the independent SQLite engine on separate disposable oracle copies. The original databases, sidecars, journals and forensic snapshot were not checkpointed, repaired, deleted, overwritten or opened through SQLite. This validates actual production absent-WAL provenance; nonempty production-WAL recovery remains unexercised and retains the reviewed synthetic limitations.

## Preservation and execution limits

The post-preparation check reconfirmed all 69 explicitly listed release/source/evidence hashes, all 30 original/forensic database sets, full 51,690-file census/metadata and the unchanged original lock bytes. Original accepted results, historical scope incidents, failed audits and prior progress files remain untouched. No training, recalibration, feature/sampler/model/architecture/split/label/threshold/protocol/attribution change occurred. No raw TEST observations, new campaign manifests or labels were opened for scoring; saved predictions and graph evidence were read only for the authorized recovery preparation. No TEST inference occurred.

Available memory was about 1.86 GiB before capture and 0.70 GiB in the final host sample. Available C: space was about 198.6 GiB. These are observations, not a certified workload requirement or an invented acceptance threshold. Low available memory is a material execution-readiness concern: inspect capacity again and establish adequate headroom before any separately authorized pilot. Do not reduce batch/graph/sampling semantics or terminate applications unilaterally to resolve it. No v2-versus-v4 production throughput comparison or remaining-run ETA is claimed; no production pilot ran.

The accepted VAL finding remains 0/171 wholly undetected campaigns. Fixed-grid 1% VAL calibration does not establish operational or TEST FPR. Shared-Parquet logical-versus-physical isolation and all prior attribution/censoring/factor-design limitations remain. This preparation provides no federated-learning, privacy, robustness or ledger evidence.

## Review and stopping point

Current completed TEST count remains five of 171; campaign 6 is still partial and 165 others have not started. Prepared artifacts are ready for independent review. A future approval must explicitly authorize execution and a separately versioned approved execution grant; do not edit this preserved draft or infer execution permission from the capture approval. Recheck source/process/lease/quiescence, preserved hashes, model/threshold identities, capacity and exact one-campaign scope immediately before any launch. The existing draft must remain rejected until a separately approved artifact exists.

Stop here. No evaluator launch, continuation workspace, campaign-7 execution, full-run continuation or Phase 7 is authorized or performed.
