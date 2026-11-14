# Phase 6 Subphase 7 (6.5): Immediate indicator-sharing baseline



**Technical gate PASS for all five organizations; user acceptance pending.** Subphase 6 USER_ACCEPTED is recorded append-only in inference/acceptance_v1.json.



This is a separate research comparison baseline, not CredBlock-FL federation or the professor’s operational architecture. The original inference/model/threshold/runtime files were not changed.



## Frozen policy and causality



All distinct exact observed IP strings used by an actual locally alerted User in (t-600 seconds,t], any authentication outcome. No minimum failure count, attacker-IP list, campaign membership, ranking or learned policy. If no recent evidence, no indicator.

[issued_at,issued_at+600 seconds); available_at equals issued_at. Expire before processing events at exact expiry. No manual revocation/correction oracle; false indicators expire normally.

At t expire due records; all organizations with a local command at t update/score independently; derive indicators from those original local alerts; sort and broadcast to all other organizations at t; then apply received indicators to authentication evidence at t. Organization iteration order must not change outcomes. No cascade: indicator-assisted alerts never issue indicators.

On the unchanged local scoring rows, local_plus = local_alert OR a current authentication at t by that same local User with an IP matching a received live indicator. No rescore or modification of previous decisions; no retrospective matching of older authentication records on receipt. Heartbeat rows without current authentication can only be local alerts.

Record indicator matches for current authentication Users not scored by the accepted local policy separately with local_status=NOT_SCORED. Do not silently count them as local no-alerts or include them in paired scored-row comparisons.



False local alerts propagate unverified suspicion under exactly the same rule as any alert. There is no runtime malicious-IP oracle, benign-IP whitelist, synthetic-ID check or automatic correction based on labels. Shared benign addresses can create additional alerts. Rotation to an unflagged address provides no indicator match until fresh local evidence produces another local alert. No initial local alert means no shareable indicator. Only original GraphSAGE alerts issue indicators, preventing indicator-only cascades.



## Per-organization paired results



| Org | Events | Paired User scores | Local alerts | Local + indicator alerts | Added alerts | Issued | Received | Unique indicators used | Expired receipts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Org1 | 578 | 4438 | 122 | 124 | 2 | 49 | 229 | 6 | 229 |
| Org2 | 567 | 4859 | 468 | 477 | 9 | 56 | 222 | 13 | 222 |
| Org3 | 617 | 5749 | 482 | 484 | 2 | 62 | 216 | 8 | 216 |
| Org4 | 626 | 5862 | 379 | 381 | 2 | 61 | 217 | 6 | 217 |
| Org5 | 669 | 5474 | 615 | 620 | 5 | 50 | 228 | 8 | 228 |



All primary rows are paired with the accepted local-only score rows. Additional current-event Users without local scores are logged separately as NOT_SCORED; their indicator alerts are not counted as gains on paired rows. All observation events and the final ten minutes are preserved. Expiry-only drain runs after the last observation solely to demonstrate every lifetime ends.



## Reproducibility, resources and preservation



Five fresh full-hour actual GraphSAGE executions reuse the original LocalInference/replay pipeline, sealed models, thresholds, seven-day graphs and ten-minute features. Each exactly matches accepted Subphase 6 local-only scores/alerts, counts, final graph hash and model state. Because sharing has no feedback into local scoring, the comparison interleaves those immutable causal local journals without repeating expensive GNN work. Local adapters restore the original warm-up checkpoint and replay the same graph updates before attribution. Only public indicator envelopes cross adapters; local Users, source alerts, graph state and private features remain local.



The complete global sharing replay is repeated with reverse organization iteration. All per-organization decisions/counts, graph hashes and public network digest match exactly. Manifests, source/config pins, journal integrity, model fingerprints and binary64 decisions are checked. Tests and timing scope are in testing_results_v1.json and per-organization summaries.



Primary sharing-adapter replay wall time: 51.073064 s; CPU: 48.671875 s; observed RSS peak: 591.688 MiB. These exclude the separately reported fresh GNN materialization runs. Simulated propagation delay is zero by definition, not measured real network latency. File-close/hash costs are outside per-command adapter timing.



All 12,050 prior inventoried files remain byte-identical, including accepted Phase 5 data/evidence, original models and all ten threshold artifacts, earlier replay/recovery/cold-start reports and workbooks. Frozen primary protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.



## Files and evidence



- configs/phase6/indicator_sharing_v1.json: frozen policy; src/phase6/indicator_sharing.py and run_indicator_baseline.py: additive source; tests/phase6/test_indicator_sharing.py: tests.

- reports/phase6/indicator_baseline/preregistration_v1.json: policy/source/design-document pins before outcomes.

- local_v1/Org1–Org5: actual fresh GraphSAGE local runs, source and policy snapshots, summaries and private journals.

- paired_v1 and reverse_order_v1: network creation/broadcast/expiry logs, per-org receipt/utilization/expiry logs, aggregate statistics, private paired/additional decisions and private source-alert provenance.

- final_v1/summary.json and artifact_sha256.json: exact results/resources and hashes; progress_v9.json: current subphase status.



## Limitations and next action



This proves mechanics and a paired operational comparison on one predeclared complete VAL hour per org, not all scenario families/seeds, final TEST, campaign detectability or production effectiveness. No labels were joined: extra alerts are not claimed to be true detections or false positives. No event-driven FPR/recall/TTD is calculated. The frozen 1% eligible fixed-grid User-window calibration does not transfer automatically to operational event decisions or the OR rule. Primary units, thresholds, eligibility masks and split protocol remain unchanged; later fixed-grid evaluation must use that protocol, not these operational counts.



Attribution may implicate benign/shared IPs associated with a targeted User; indicators are suspicious/unverified, not malicious labels. TTL is a preregistered ten-minute baseline choice, not a validated optimum. No manual correction/revocation beyond deterministic expiration is implemented. Zero simulated delay is optimistic; barriers and local execution occur in a research simulation, not a real distributed network. Logical organization isolation on one host is not production security. No final TEST, federation, differential privacy, robust aggregation or Fabric is implemented.



Next action: user review and explicit acceptance of Subphase 7. Subphase 8 NOT_STARTED. The frozen primary protocol must remain version-controlled before later final TEST evaluation.

## Fresh actual local inference resource measurements

| Org | Replay wall (s) | CPU (s) | End-to-end p95 (s) | Sampling + scoring p95 (s) | Observed RSS peak (MiB) | Exact accepted local match |
|---|---:|---:|---:|---:|---:|---|
| Org1 | 1157.295475 | 1151.234375 | 2.328512 | 0.173374 | 471.508 | Yes |
| Org2 | 1207.692604 | 1196.578125 | 2.470989 | 0.177011 | 474.953 | Yes |
| Org3 | 1398.051112 | 1391.125000 | 2.604856 | 0.189814 | 481.336 | Yes |
| Org4 | 1481.544890 | 1474.312500 | 2.719414 | 0.191896 | 483.348 | Yes |
| Org5 | 1621.461130 | 1619.609375 | 2.825338 | 0.201549 | 486.988 | Yes |

An independent audit verified all 26,382 primary paired decisions, 0 separate event-only rows and 278 issued indicators against local original alerts and observable ten-minute evidence. Every recipient decision was independently recomputed using availability, exact exclusive expiry and current authentication. No source journal changed. See delivery_audit_v1.json.

Models and thresholds remain exactly the accepted originals. Sampling + scoring includes sampled-batch construction and forward passes. Fresh materialization runs overlapped on one CPU research host, two Torch threads per org. These resource measurements are workload observations, not production requirements or an SLA.

Global comparison wall time includes adapter loading, private-source hashes, graph replay, barriers, attribution/matching, output close and final graph/source verification. Per-org adapter timing spans prepare through finish including same-timestamp barrier/peer work; excludes fresh GNN materialization and final close/hash costs. Model-stage timing includes batch sampling plus forward passes. Simulated propagation is zero by definition, not measured transport.
