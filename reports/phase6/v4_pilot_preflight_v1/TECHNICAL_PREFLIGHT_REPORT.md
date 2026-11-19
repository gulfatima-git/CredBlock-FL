# Phase 6 v4 bounded production pilot — gate review

Decision: **BLOCKED / FAIL at authorization prerequisite**. No pilot executed. This is not an implementation or scientific-result failure.

Verified Git commit: `a7adf15f0f9b97d062b9e91d784483457bdf67d0`. Annotated release tag: `phase6-v4-4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370`. All 135 explicit candidate files match their committed bytes. The committed v4/v2 source-only identity calculation matches `4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370`. Frozen protocol byte hash matches both HEAD and the working file: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

## Gate findings

| Gate | Finding |
|---|---|
| Commit, tag, required committed implementation files and byte identities | PASS |
| No tracked changes or staged changes | PASS |
| Fully clean Git working tree | FAIL literally: 10720 untracked status entries, including this newly created preflight directory; preflight initially observed 10,720 unrelated/pre-existing untracked entries. No files were deleted, ignored or staged to conceal them. |
| Previous recovery milestone | Preserved in committed report and progress_v34; not rerun or treated as a new production certificate |
| Original v2 approval | Present; does not authorize v4 |
| Required v4 capture approval/host attestation | MISSING |
| Production predecessor certificate and WAL-aware capture provenance | MISSING from designated namespace |
| Certificate-bound PILOT_ONLY execution grant | MISSING |
| Exact pilot campaign list and maximum | Not approved in a production grant |
| Fresh all-five-organization recovery/model checks and resource-capacity gate | NOT REACHED after blocking authorization finding |
| Pilot execution and post-pilot independent validation | NOT RUN |
| Production runtime comparison / remaining-run ETA | UNAVAILABLE; no measurements or speedup claimed |

## Evidence read and preserved

Reviewed the recovery report, v4 technical acceptance report, source-defined scope/driver gates, historical transition plan, inventory-weighted pilot planning metadata and progress_v34. The three designated v4 authorization/capture/continuation directories do not exist. Original v2 grant metadata was inspected only as a historical approval; no grant was created or upgraded. Inspection used code, Git blobs and permitted reports/configuration metadata, not observations, labels, row-level predictions, model weights, database contents or forensic payloads.

The prior recovery audit records five independently verified completed campaigns and one partial campaign: CFV1_RA_CS_005_SEED1003_TEST, with 1,690 committed commands, 15,309 local scores, 40 grid bundles (3,206 rows) and a final pending Org2 barrier at 2020-12-13T17:33:41.419000 before SQL commit/publication. These are prior validated findings, not a fresh scan or newly issued v4 certificate. All five states require the actual certificate/readiness gates before pilot execution. The forensic snapshot, original evidence and accepted artifacts were not modified or reopened for recovery during this preflight.

The old transition plan's proposed seed1001/seed1002 campaigns are now among the five completed campaigns. That historical plan is retained unchanged; its stale candidate list must not be used to rerun them. The source contract allows PILOT_ONLY inventories of 1–4 variants, but that implementation bound is not a user-selected campaign list or permission to choose four.

## Smallest next approval needed

Recommended proposed scope for review: authorize preparation of the source-quiescence attestation, WAL-aware production capture/predecessor certificate and a release/certificate-bound PILOT_ONLY grant for **only CFV1_RA_CS_005_SEED1003_TEST**. Maximum newly completed campaign instances: **one**. Reuse all five original completed instances through verified original completion provenance; do not execute them. Recover committed partial work without GNN repetition. Do not start campaign 7 or the remaining full evaluation.

This is a proposal, not an approval artifact. Preparation must preserve original v2 and forensic namespaces and use the designated v4 capture and continuation namespaces. New explicit approval must specify whether it authorizes only preparation/review or also execution after every gate passes. Also clarify whether the Git condition means no tracked/staged changes with explicitly excluded research artifacts remaining local; a fully clean tree cannot honestly be claimed today. No automatic cleanup is proposed.

After valid approval artifacts exist: establish host quiescence and lease state afresh; independently verify the five completion provenances and all-five-organization committed boundary, models/thresholds/protocol, journal/WAL/graph state; inspect the bounded inventory and system capacity; then execute only the approved pilot, seal outputs, reconcile independently, and measure actual runtime/resources/inference reuse. Stop before any full-run continuation.

## Required deliverables disposition

Technical execution report: this blocked preflight, no execution. Independent validation report: committed byte/source identity findings in preflight_verification.json and committed_allowlist_verification.json; no post-pilot validation claimed. Runtime comparison: not measurable before execution. Preservation/provenance: no tracked modifications, all committed allowlist bytes verified, no research payload access; previous full forensic preservation remains its separate milestone. Progress: new append-only progress_v35.json. Remaining work: five previously verified complete, 166 incomplete (one partial plus 165 not started), pending fresh readiness checks and separately authorized pilot/full run. Scientific limits from the accepted reports remain, including 0/171 wholly undetected VAL campaigns, fixed-grid versus operational FPR distinction, shared-Parquet logical/physical isolation and no production-v4 performance result.

Phase 6 remains IN_PROGRESS. Phase 7 remains UNSTARTED. No USER_ACCEPTED milestone, execution grant, new scientific method, model training, calibration or inference was created. Stop for user review.
