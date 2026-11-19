# Phase 6 — v4 bounded production pilot technical acceptance report

**PASS — one authorized pilot completed and independently validated.** Technical recommendation: PASS for considering separately authorized continuation of the remaining 165 instances, with the performance limitations below. No remaining instance was launched, no Phase 7 was started and no USER_ACCEPTED decision is recorded. Phase 6 remains IN_PROGRESS.

## Execution and preservation

Exactly one evaluator launch attempt executed CFV1_RA_CS_005_SEED1003_TEST under the newly approved, certificate-bound PILOT_ONLY grant. Native status is BOUNDED_EXECUTION_COMPLETE_FULL_RUN_PENDING: six completed / 165 pending. The five previous v2 campaigns are referenced in the mixed-origin ledger without execution. The only campaign output folder in the continuation run is campaign 6. Process exit code is zero; final host inspection confirms no evaluator remains.

- Commit: a7adf15f0f9b97d062b9e91d784483457bdf67d0.
- Reviewed release: 4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370.
- Predecessor certificate: 67ebdf7a895995729235091d85c40d68c2a0659576d74494b7e9e8b3331c116d.
- Protocol SHA256: 9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b.
- Approved grant SHA256: 0a8c77967fc3ae7a482619fb42ac32c9f667e3368ac0e04627491376ca317560. The original non-executable draft and all four preparation artifacts remain unchanged.
- Completion SHA256: 523e864e79250fa6230f3d1aab91c4113e0401b40d232e5bdef48d22a47df29d.

The exact original SQL score/command/token/checkpoint/failure prefix digests match for all five organizations: **1,690 commands and 15,309 local scores**. All **40 prior raw grid artifacts** remain byte-identical, and original journal byte prefixes are preserved. Recovery reads graph history without model inference. Cached COMPLETE/LOCAL/GRID paths bypass committed inference; no committed prediction was regenerated. Prefix proof: exact_reuse_and_execution_counts.json.

New work contains 1186 committed local commands and 10253 local scores. There are 1,174 new global barriers and 2,848 total barriers. The required final flush is exactly 2020-12-13T17:59:59.999999; the full final-ten-minute observation interval is retained. All 60 primary grid bundles (six times, two families, five organizations) are present, including 20 newly produced bundles.

New model batch-call counts derived from committed records and unchanged batch_size=256 are **1196 GraphSAGE batches** (1186 local plus ten grid batches) and ten MLP grid batches. These are reproducible code/record-derived counts, not an injected live forward profiler. Original-prefix bypass, exact prefix digests, unchanged scoring code and accepted counter-based recovery tests support the zero-duplicate-committed-inference finding. No second GNN run was made on newly scored inputs to manufacture a comparison oracle.

Post-pilot preservation passed: all 69 explicitly listed source/evidence hashes, ten original model archives and frozen metadata match; original partial database/WAL sets, forensic database anchors, lock bytes and five original completion identities are unchanged. No original SQLite database was opened, checkpointed, repaired or deleted. The forensic snapshot remains in its dedicated directory; no full repository checksum sweep was repeated. No tracked or staged changes were made. Private new replay/database/prediction outputs must remain excluded from Git.

## Independent validation gates

| Gate | Result |
|---|---|
| Single campaign / maximum one new completion / five reuse references | PASS |
| Exact inherited SQL, raw-grid and journal prefixes | PASS |
| Model, threshold, schema, sampler and protocol identities | PASS |
| Graph reconstruction, observable-only targets and saved temporal views | PASS |
| Six primary times, equal eligible GraphSAGE/MLP cohorts, exact binary64 decisions | PASS |
| Indicator attribution/publication/receipt/availability/exclusive expiration | PASS |
| Full operational horizon and final flush | PASS |
| Campaign/org/targeted-User attribution, ambiguity and censoring | PASS |
| Completion hashes, score sealing before labels and mixed-origin provenance | PASS |
| Independent saved-evidence audit | PASS, 77.302 seconds, zero GNN forwards |
| Original artifacts, model archives and non-executable draft preservation | PASS |

The independent oracle is src/phase6/independent_test_validation_v1.py, not the production campaign evaluator. Its report is independent_campaign6_audit/summary.json. Original five campaign audits were reused; they were not rerun. No failed check or execution exception occurred. The known PyTorch/Python 3.14 torch.jit.script FutureWarning remains logged; no dependency or model behavior was changed. Tiny native-versus-independent floating summation differences in BCE are within the existing comparator tolerance, with exact decision/confusion-count agreement.

## Verified results: this campaign only

Primary evaluation unit: eligible fixed-grid User-time. Thresholds remain the 1% empirical VAL-FPR calibrations; observed TEST FPR is reported without recalibration. NA recall means no positive examples for that organization, not zero recall.

| Org | Detector | Eligible | TP | FP | TN | FN | FPR | Recall | Precision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Org1 | graphsage | 370 | 0 | 3 | 367 | 0 | 0.811% | NA | 0.000% |
| Org2 | graphsage | 378 | 0 | 8 | 370 | 0 | 2.116% | NA | 0.000% |
| Org3 | graphsage | 490 | 21 | 9 | 413 | 47 | 2.133% | 30.882% | 70.000% |
| Org4 | graphsage | 513 | 32 | 5 | 435 | 41 | 1.136% | 43.836% | 86.486% |
| Org5 | graphsage | 454 | 0 | 8 | 446 | 0 | 1.762% | NA | 0.000% |
| Org1 | tabular_mlp | 370 | 0 | 8 | 362 | 0 | 2.162% | NA | 0.000% |
| Org2 | tabular_mlp | 378 | 0 | 5 | 373 | 0 | 1.323% | NA | 0.000% |
| Org3 | tabular_mlp | 490 | 8 | 4 | 418 | 60 | 0.948% | 11.765% | 66.667% |
| Org4 | tabular_mlp | 513 | 9 | 9 | 431 | 64 | 2.045% | 12.329% | 50.000% |
| Org5 | tabular_mlp | 454 | 0 | 4 | 450 | 0 | 0.881% | NA | 0.000% |

Pooled fixed-grid results (2,205 units per detector; 141 positive, 2,064 negative):
- graphsage: TP=53, FP=33, TN=2031, FN=88; FPR=1.599%, recall=37.589%, precision=61.628%.
- tabular_mlp: TP=17, FP=30, TN=2034, FN=124; FPR=1.453%, recall=12.057%, precision=36.170%.

Exact AP/BCE, macro results and denominators are in validated_primary_and_operational_results.json and fixed_grid_metrics.csv. Macro recall/AP averages only the two organizations with positive examples; FPR averages all five. These are pilot-only results, not all-171 results or a TEST-based model-selection decision. GraphSAGE remains the VAL-selected best-local family for every organization.

Operational local-only and local-plus-indicator both detect the campaign at both targeted organizations (2/2). First campaign detection is 96.992786 seconds after onset for both, not the time all organizations first detect. Targeted-User coverage is 64/150 local-only and 65/150 with indicators. There are 121 indicator episodes, 484 receipts and 51,124 combined family-specific operational decision rows. These event-driven results are distinct from fixed-grid FPR/recall. No operational 1% FPR guarantee is claimed. This campaign is detected, not right-censored; the independent evaluator verified attribution/censoring rules rather than inventing finite times for undetected examples.

## Measured runtime and resource requirements

- Full supervised wall time: **4271.672 s (71.19 min)**, from 2026-11-19T00:14:15.749251+05:00 to 2026-11-19T01:25:27.421075+05:00.
- Native campaign-attempt wall time: **2507.354 s (41.79 min)**. It excludes earlier source recovery/provenance setup; it includes model/input preparation, cached-prefix dispatch, new scoring and native evaluation.
- Earlier setup/recovery/provenance time by difference: **1764.318 s (29.41 min)**.
- Worker CPU: **4188.203 s**, from retained read-only Windows process handles, including final exit times. Supervisor and audit CPU are separate.
- Observed Windows worker peak working set: **854.75 MiB**. Sampled process-tree RSS peak: 860.70 MiB, potentially double-counting shared pages. External samples were five seconds apart; kernel peaks are through the last successful sample, not an assertion about an unobserved final instant.
- Minimum available RAM sampled during evaluator execution: **2.10 GiB**. Paging samples are preserved; they do not prove the absence of every brief paging spike. No OOM or resource failure occurred.
- New-score-publication to final-flush wall interval: approximately **1909.67 s (31.83 min)** by artifact filesystem timestamps. This is not an injected phase timer and excludes the first new forward before publication plus later sealing/evaluation.

V2's original partial-campaign wall interval is 11.55 hours and includes the known laptop-sleep period. It is not a valid compute-speed baseline; v2 and v4 also processed different temporal portions. **No apples-to-apples end-to-end speedup has been established.** Saved local precommit means are 0.600210 s for the old v2 prefix versus 1.149623 s for the new v4 tail. The latter is higher; this is not concealed. These unequal-workload values exclude final SQLite commit and coordinator/journal overhead, so neither proves a causal version speedup/regression. Synthetic indexed-journal speedups must not be represented as production speedups.

## Remaining 165 and stopping decision

The frozen metadata lists 330,916 remaining observation events. A count-based global timestamp bound is 332,071 (events plus seven common grid/final times per instance). Applying this pilot tail's seconds/barrier to that bound gives an event-phase-only scenario of **150.0 hours**, before unmeasured new-case setup/warm-up, sealing/evaluation, independent audits and final full-run reporting. This is **not a certified end-to-end ETA, speedup or confidence bound**: workload/root/graph costs, timestamp overlap and host conditions differ. A multi-day remaining run is plausible. Technical/scientific pilot gates pass; practical runtime should be reviewed before authorizing the full continuation.

A future continuation must reuse the six completed instances and preserve this output's existing mixed-origin ledger and prefixes. No grant expansion, new pilot, full run, optimization or Phase 7 implementation has been performed. A separately versioned explicit authorization is required for remaining cases; do not rerun campaign 6 or infer permission from this pilot grant.

Prior limitations remain: 0/171 wholly undetected VAL campaigns; no claim of recovering campaigns missed by every organization; shared-Parquet logical-versus-physical isolation and historical audit incident; temporal dependence, denominator, factor-design and attribution limitations; no federation, DP, robust aggregation or ledger evidence. One TEST pilot does not establish full-study generalization or the full CredBlock-FL research claims. No source data, model, threshold, feature, sampler, split or scientific rule was changed to obtain these results.

**Stop after this report. Phase 6 remains IN_PROGRESS with 6/171 complete and 165 pending. User acceptance and any further execution are separate decisions.**
