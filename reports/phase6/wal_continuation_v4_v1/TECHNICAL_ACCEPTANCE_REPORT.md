# Production WAL-aware v3 successor — technical acceptance report

**Implementation milestone: PASS within the documented synthetic and permitted-source audit scope. Actual transition: REVIEW_REQUIRED / NOT EXECUTED. USER_ACCEPTED: false.**

This implements the user's attachment db5a7f48-fd59-45ea-b794-ef566c6c128e. It is an additive successor, named **v4**, not a modification to accepted v3 or the professor's framework. No live interruption, capture, production pilot or execution approval was performed or created.

Final release identity:

`4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370`

## What changed

Eight new runtime modules integrate a versioned physical-to-logical WAL certificate, source authority, independent SQLite comparison, five-organization workspace recovery, indexed barrier and mixed-origin completion manifest. One new configuration pins recovery policy. Existing v2/v3 modules, accepted inference code, scientific protocols and model/threshold artifacts were not edited.

Original database/WAL/SHM bytes remain physical evidence. The successor creates a separately hashed self-contained committed image and binds both representations in `phase6-continuation-wal-certificate-v4`. It never bypasses the old v3 nonempty-WAL guard. A new certificate is mandatory; an image cannot masquerade as the old physical database.

The WAL analyzer checks header/version/page size, salts and cumulative frame checksums, finds commit markers and excludes complete uncommitted frames. SQLite independently reads a disposable oracle copy, and its complete schema/table contents must match the derived image. The accepted recovery inspector then validates model/config identity, binary64 scores, tokens, offsets, checkpoint hashes and graph command/view consistency. A separate journal/SQL join validates published LOCAL records and committed grid views. Integrity_check alone cannot release recovery.

The working namespace retains an immutable physical archive and installs only the certified logical images. Before initial READY, unexpected working WAL/SHM/journal files reject restore and remain untouched. After READY, repeated working-WAL recovery validates the original committed prefix before additional model execution. Original completion manifests are referenced with original provenance; incomplete work cannot be counted complete.

## Validation results

**55 distinct parameterized test cases have successful evidence across the stated runs.** Repeated passes are not added to that unique count; the 12,122 independent audit assertions are not another 12,122 unit tests.

| Evidence | Exact result | Scope |
|---|---|---|
| tests_attempt_03.xml | 44 passed | 27 crash stages, version/access/corruption/copy checks and 14 WAL edge cases |
| tests_receipts_01.xml | 5 passed | Interruption at receipt for each of Org1–Org5, generated all-alert RAM models |
| tests_final_focused_02.xml | 20 passed | Final source: two authority-denial cases, 14 WAL cases, initial-sidecar and second-working-WAL restart tests, two inventory/certificate tests |
| independent_audit_attempt_01/summary.json | 12,122 checks passed, 27 cases | Separately implemented SQLite/journal/decision/metric/censoring/completion reconciliation |
| final_static_review_v1.json | 14 checks passed | Unchanged scientific production methods, barrier process, reporting/reconciliation functions and final guard-change scope |
| final_certificate_rechecks_v1.json | 27 saved certificates passed on final source; zero model forwards | All original synthetic physical files, derived state, journals and committed temporal-grid joins reverified; deliberately wrong grid-view digest rejected |
| preservation_final_v1.json | 20/20 hashes match | Explicit accepted source/configuration and all seven old continuation runtime modules |

The main matrix covers: barrier BEGIN; SQLite commits before LOCAL publication for every organization; LOCAL publication for every organization; issuance; receipt; network in-memory publication; publication preparation and commit; paired decisions; barrier completion; indicator expiry; GraphSAGE and MLP grid commits/file publication; score sealing; offline label phase; final instance sealing and already-completed predecessor reuse. Every case compares all five organizations' scientific results and saved eligible predictions, User attribution and censoring with an original synthetic v2 reference. Six primary times, both detectors and all five organizations yield 60 primary raw bundles, plus the final operational flush.

Each main case uses a disposable subprocess that self-exits at its injected stage. Its parent reaps it before any database copy/read. No signal or termination request is sent to the live evaluator. The original physical fixture inventory is unchanged after capture and continuation. Predecessor model calls plus continuation calls equal the reference count in every case; there are **zero extra committed prediction calls**. Graph-history reconstruction is permitted and is distinguished from inference.

Five additional all-alert fixtures exercise receipt recovery at every recipient, including Org1 receiving another organization's indicator. These models are generated RAM-only fixtures with separate identities; they are not accepted trained checkpoints. Another test crashes the successor itself after a further committed local prediction, leaves nonempty working WAL, restarts and again matches the reference call budget and outputs.

WAL edge cases include page sizes 512/4096/65536, committed and spilled uncommitted frames, uncertain/corrupt header/frame/salt/partial/rollback states, interrupted derived-image publication, forged logical images, wrong organizations and denied metadata paths. The earlier feasibility milestone additionally covers both checksum byte orders and empty/header-only/no-commit WAL. Those earlier results remain preserved; they are not silently counted as newly rerun production-module cases.

### Final source applicability

The full 27-stage matrix and five-receiver matrix preceded three final guard-only changes: initial working-sidecar rejection; approval/attestation namespace denial before lookup/read; and production certificate output confinement. `matrix_source_sha256.json` pins that tested source vector. `final_static_review_v1.json` records the three changed files and confirms unchanged scientific methods. The final focused 20 tests exercise the changed guards, legitimate initial and repeated-WAL recovery, WAL cases and inventory checks on the final release. All 27 saved synthetic certificates were additionally reverified using the final source, including physical/derived hashes, saved SQL and temporal-view reconciliation; no model forwards occurred. A deliberately wrong grid-view digest was rejected.

**The complete 55-case collection was not rerun as one invocation on the final source vector.** No claim is made otherwise. The final-source coverage and unchanged-method applicability are explicit review limits.

## Independent audit

The audit does not call the campaign evaluator as its oracle. It uses a separate journal checksum parser, SQLite WAL readers on separate disposable copies, direct saved LOCAL/SQL joins, independent binary64/indicator-availability/expiry decisions, eligible-unit confusion counts, censoring checks and completion hashes. It also invokes the unchanged v3 store inspector on the new self-contained synthetic images, independently checking the successor's recovered descriptors.

It verified all **27 synthetic crash cases**, not the 171 actual TEST campaigns. It is a separately implemented source/evidence audit, not a claim of an independent human review. No actual TEST scientific evaluation was repeated or independently completed by this implementation milestone.

## Runtime and resources

End-to-end synthetic workload: five organizations, 100 extra timestamped events per organization, accepted graph/features/sampler/persistence/grid/sharing/offline-reporting path, 60 primary raw bundles and generated RAM-only models. All versions produced identical scientific results and **550 total model calls**.

| Version | Wall seconds | CPU seconds |
|---|---:|---:|
| Original v2 | 74.6555 | 28.8125 |
| Existing indexed v3 | 61.7955 | 34.6094 |
| WAL successor | 55.0834 | 28.5469 |

Observed ratios: 1.355× versus v2 and 1.122× versus v3. These are single shared-host samples, not a controlled causal speedup estimate. All three runs reported the same cumulative process peak working set, 400,674,816 bytes (about 382 MiB); this is **not an independent per-version memory peak**. The generated models do not represent accepted GraphSAGE inference cost.

A second benchmark includes capture and continuation of a three-local-commit prefix:

| Path | Capture seconds | Resume seconds | End-to-end seconds | Remaining model calls |
|---|---:|---:|---:|---:|
| v3, separately constructed self-contained logical-reference fixture | 0.6131 | 19.5428 | 20.2031 | 47 |
| Successor, preserved physical WAL fixture | 1.4821 | 13.2920 | 14.8155 | 47 |

The v3 comparison uses a new synthetic self-contained reference with equivalent committed rows and unchanged journal bytes; it does not substitute a recovered image under an old accepted certificate. The original WAL fixture remained unchanged. Capture/resume benchmark JSON retains exact measurements and source hashes. Startup/import/model construction outside each timed region and host contention limit interpretation. **No full-run ETA or ten-day-to-N-day promise follows from these measurements.** A separately approved bounded real pilot is still required.

## Requirement findings

| Requirement | Implemented | Tested synthetically | Independent verification | Production |
|---|---|---|---|---|
| New certificate; separate physical/logical hashes | PASS | PASS | Source/schema and derivation checks PASS | Unverified |
| Original DB/WAL/SHM preserved; no manual checkpoint/repair/delete | PASS | PASS | Source inventories/20-file allowlist PASS | No live capture |
| Committed WAL recovery, uncommitted exclusion | PASS | PASS | Independent SQLite comparison PASS | Unverified actual WAL |
| Org1–Org5 crash recovery and indexed barrier | PASS | PASS | 27 cases plus five receiver tests PASS | Unverified |
| Exact committed predictions and binary64 thresholds | PASS | PASS | Saved-row joins/call budgets PASS | No actual weight/prediction access |
| Original architecture/features/sampler/model identities | Reused | Generated-model path tested | Unchanged-source/AST identities PASS | Actual sealed bundles not reopened |
| Indicator availability/expiry, paired decisions | Unchanged | PASS | Separate direct decision checks PASS | Unverified |
| Attribution/censoring and frozen denominators | Unchanged | PASS | Audit checks plus original-reference output comparison PASS | No actual TEST reconciliation |
| Original 171/855 inventory and incomplete sealing guards | PASS | PASS metadata fixture | Source/config checks PASS | Full actual run pending |
| Provenance, version/namespace separation and access denial | PASS | PASS | Final static and negative checks PASS | No grants created |
| Efficient capture/recovery/resource measurement | PASS | Measured | Saved benchmark evidence PASS | Production ETA unestablished |
| All arbitrary WAL states automatically recoverable | NOT CLAIMED | Ambiguous cases block | Fail-closed policy verified | Requires post-exit classification |

## Preservation and historical failures

All 20 explicitly allowlisted predecessor hashes match, including frozen protocol:

`9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`

No broad Git/data-tree sweep was performed. Actual models, thresholds and experiment archives were not reopened or rehashed; preservation of those artifacts follows the bounded writes and access scope, not a claimed new exhaustive hash audit. The active original runner was not inspected or controlled, and it can continue its already-authorized writes; this work does not claim its active output tree stayed static. Immutability of predecessor evidence is enforced after separately established quiescent capture.

Historical failures are retained:

- tests_attempt_01.xml: one failed smoke case due to excessive Windows temporary-path length; source_attempt_01_sha256.json retains the code vector. Temporary names and disposable root lengths were shortened without changing durability.
- review_negative_attempt_01.xml: unexpected working SHM was not rejected before initial READY. Fixed by preserving the unexpected sidecar and refusing initial restoration. No accepted evidence was affected.
- authority_negative_attempt_01.xml: two deliberately intercepted excluded-path lookups demonstrated missing early metadata namespace enforcement. No excluded path was actually looked up or read: test monkeypatches raised first. Fixed before the final pass. This is separate from, and does not reverse, the historical TEST access incident.
- All earlier reports, failed reviews and the disposable WAL feasibility evidence remain unchanged. No USER_ACCEPTED record is created here.

The existing PyTorch/Python 3.14 warning remains disclosed. No dependency change was made.

## Limits and transition recommendation

Well-formed nonempty WAL is recoverable within tested conditions. Stale-salt suffixes, partial appends, rollback journals, invalid checksums, unresolved committed-state completeness or mismatched journals/graphs stop capture for review. A valid earlier SQL view can still be incomplete if an entire later commit was lost; hash/SQLite integrity agreement alone cannot rule that out. Never delete sidecars or silently select an earlier prefix to bypass a failed gate.

Actual console interruption safety, actual process exit/lease release, physical source quiescence, real WAL contents, disk-space/permission conditions and real-model end-to-end performance remain unverified. Original v2 has no cooperative boundary stop; passing these recovery tests does not make an interruption graceful. Shared-Parquet isolation remains logical, the 1% VAL target is not a TEST/event FPR guarantee, and the verified 0/171 wholly undetected VAL finding remains unchanged. This supplies no federation, privacy, robustness or blockchain evidence.

**Recommendation:** the additive successor is ready for user review as a synthetically validated implementation milestone. Any live interruption, post-exit capture and bounded production pilot remain separate, explicitly reviewed decisions. Do not launch the successor merely because this report says PASS within scope. If an actual snapshot falls outside supported WAL conditions, stop and propose the smallest additive correction; never repair the original or rerun committed inference.

## Deliverables and reproducibility

- IMPLEMENTATION_PLAN.md and ARCHITECTURE_AND_DATA_FLOW.md.
- Eight src/phase6/continuation_*_v4.py modules and audit_continuation_wal_v4.py.
- configs/phase6/continuation_wal_v4.json.
- test_continuation_wal_v4*.py, two disposable writer helpers and two benchmark scripts in tests/phase6.
- All XML results, both benchmark summaries, independent audit summary, static review, preservation vectors and technical_summary_v1.json.
- Append-only reports/phase6/progress_v33.json; previous progress records untouched.
- delivery_manifest_v1.json pins curated source/configuration/test/report evidence. Raw disposable oracle caches are auxiliary evidence, not curated Git deliverables.

Synthetic reproduction must use a NEW temporary base/output name; never reuse --basetemp because pytest may clear it. The original successful commands and output locations are recorded by the XML and benchmark evidence. A fresh combined test invocation may run the six test_continuation_wal_v4*.py files with a unique external wal_v4_* base. These use generated RAM models and synthetic labels only. No production CLI/capture command or execution-approval artifact is supplied as an authorized next step.

Implementation and validation stop here. No live interruption, capture, optimized evaluator launch, retraining, recalibration, methodology amendment or Phase 7 work is authorized or performed.
