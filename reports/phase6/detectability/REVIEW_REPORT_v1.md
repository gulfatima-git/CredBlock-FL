# Phase 6 Subphase 8 — frozen method, representative verification and execution review

**IN_PROGRESS: 1 of 171 required VAL instances validated; 170 pending. This is not a Subphase 8 acceptance pass. The full sweep has not been launched.**

The user selected methodology/representative review before any multi-day full run. Required scientific coverage remains all 171 VAL campaign instances, both local-only and immediate-indicator systems, all design families and three seeds. Subphase 9 remains NOT_STARTED.

## Frozen operational definition

Onset is the earliest matching positive synthetic authentication event across the declared targeted organizations. Planned campaign start/end are the accepted register/manifest interval. The observation horizon begins at actual onset and ends at the declared exclusive campaign end; no post-end observations are fabricated. The representative onset is `2020-10-06T07:00:00.937950`, with exclusive end `2020-10-06T08:00:00`.

A qualifying alert is the stored local-only or separately stored local-plus-indicator decision for the same branch, organization and User, with campaign-specific positive targeting evidence in `(alert_time−10 minutes, alert_time]`, within the horizon. This preserves final-ten-minute operational coverage. Before-onset alerts, unrelated Users, non-targeted organizations, stale evidence and alerts at/after exclusive end receive no credit. A delayed alert after the last attempt may qualify while its evidence is recent and the horizon remains open.

Multiple eligible recent campaigns for one alert make it ambiguous: record all candidates and credit none in the primary result. Different organization/variant/User keys never cross-match. This is operational temporal association, not proof that the model responded causally to the injected attempts instead of background behavior. A zero-candidate alert is unattributed, not automatically a verified false positive.

An organization detects a campaign if at least one exposed targeted User has a uniquely attributable qualifying alert. A campaign is detected if ANY targeted organization detects; ALL detected and partial detection are additional distinct summaries. The primary all-targeted-undetected rule requires positive exposure and complete coverage in EVERY targeted organization and no qualifying detection anywhere. Missing or incomplete coverage remains pending/indeterminate, not undetected.

No qualifying alert has `event_time_seconds=null` and `right_censored=true`, with the observation duration stored separately as censor time. Complete-horizon non-detection is conditional on that horizon, not a claim the campaign would never be detected later. User-time rows, distinct targeted Users, organization-campaign trials and campaign instances have separate denominators.

Protocol: `configs/phase6/detectability_protocol_v1.json`; method SHA256: `f63e0bb73253eea4a8c8d7abc4231f94069aaf15c3eef68eeb3fa1b00d49bc55`. Preregistration and the entire 171-instance metadata inventory were saved before the first campaign outcome join. Primary fixed-grid protocol SHA256 remains `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`, verified in commit `5de030316176a27889054d0e782cb1ad92171cb5`. Neither thresholds, primary units, scoring grid nor the 1% clean-negative VAL FPR target changed.

## Predetermined representative results

`CFV1_SO_CS_027_SEED1001_VAL`: design family Sorg_fixed_per_org_attempts, RIP=0.5, Raccount=0.5, Sorg=5, seed=1001. The campaign was fixed by prior operational subphases, not selected using these new outcomes. Each organization has 60 distinct exposed target Users.

| Organization | Local detected Users / 60 | Indicator detected Users / 60 | Local qualifying alert rows | Indicator qualifying alert rows | Local first delay (s) | Indicator first delay (s) |
|---|---:|---:|---:|---:|---:|---:|
| Org1 | 23 | 25 | 92 | 94 | 533.886081 | 533.886081 |
| Org2 | 23 | 30 | 86 | 94 | 499.724469 | 499.724469 |
| Org3 | 28 | 29 | 126 | 128 | 346.743631 | 346.743631 |
| Org4 | 28 | 29 | 119 | 121 | 259.895029 | 259.895029 |
| Org5 | 23 | 27 | 92 | 97 | 636.951050 | 487.979535 |

Both systems detect this campaign in all five organizations: campaign detected 1/1, all-targeted-undetected 0/1 for each system. The first campaign detection is 259.895029 s from actual global onset for both. Summed organization-local distinct target-User detections are 125/300 local-only and 140/300 with indicators. These are not campaign recall estimates for all 171 instances and are not the calibrated fixed-grid FPR.

All factor/family/seed cells are in `representative_v1/factor_seed_coverage.json`, with required, complete-evaluated and pending denominators. The other 170 instances are explicitly pending; their missing outcomes are not zero detections or undetected campaigns. Private per-User and per-alert attributions stay in organization-local private folders.

## Exact reuse and measured verification

Accepted score/decision verification: 12.307302 s; offline evaluation: 0.656077 s; total representative method run: 14.979298 s. Generalized bridge replay: 53.164359 s, observed RSS peak 592.863 MiB. Imports/external tool overhead are not included in these internal timers.

For each organization, all scores, exact threshold encodings, original alerts, timestamps, input commands and view digests match across three independently executed accepted local journals. Primary/reverse indicator decisions are byte-identical, and live IP matches were recomputed from current authentication with exact availability/expiry checks. The generalized bridge inherits the accepted prepare/finish/close methods and reproduced the public network digest, paired/additional decision digests, graph hashes and campaign-attribution digest exactly. No approximate computation is accepted.

Enabled reuse avoids rerunning the already validated representative GNN computations. The other 170 instances still need fresh accepted event-driven inference; fixed-grid validation predictions cannot replace them. Persistent model workers and clean background checkpoint/fork caching are proposals only: they are not implemented/enabled as speed claims, and require whole-trace score, threshold, alert, time/view/graph and campaign-attribution equivalence before adoption.

## Append-only execution design and resource budget

The reference driver processes one independent instance at a time with five local subprocesses, two Torch intra-op threads each. It reuses the accepted model registry, full-hour chronological runtime, sampler and frozen indicator classes. Runtime source receives observable columns only; truth joins happen after local and sharing outputs are sealed. Each instance resets its graphs/indicator state. No TEST access, fitting, threshold calibration or later-phase component is implemented.

Per-org model runs, normal/reverse sharing passes and offline evaluation each use independent attempt directories and immutable completion manifests with artifact hashes. Valid completed components are checked and reused on resume; incomplete/failed attempts are preserved and retried in new directories. Completed-artifact tampering fails closed. OS advisory locks prevent concurrent owners and release on owner exit; logical exception/lock release is tested. Progress is printed every 30 s during model work and appended per completed/failed instance. Interruptions terminate owned children. Power-loss/OS-kill recovery and fresh execution of all other campaign workers remain unproven; partial or corrupted completion markers fail closed for review rather than being silently overwritten.

Measured reference model-only estimate for 170 remaining instances: 76.569 h. Two sharing passes add roughly 5.021 h at the representative bridge rate, yielding a reference subtotal of 81.590 h before startup, variable branch sizes, input/hash verification, offline evaluation and failures. No larger speedup is claimed.

Observed summed five-worker RSS: 2.342 GiB; budget about 8 GiB system RAM and ten Torch intra-op threads plus framework/IO threads. Remaining local-journal reference storage is 11.093 GiB; allow about 20 GiB or more for journals, two sharing passes, evaluation outputs and margin. Current free disk was 199.195 GiB at report creation. These are single-instance extrapolations, not guarantees.

Review-gated commands (do not launch until explicit post-pilot review approval):

```powershell
cd "C:\Users\Gulso\Documents\Gul\CredBlock-FL"
.venv\Scripts\python.exe -B -m src.phase6.detectability_batch --status
# AFTER explicit review approval; rerun this same command to resume:
.venv\Scripts\python.exe -B -m src.phase6.detectability_batch --run-all --review-approved
# Optional single-instance repair/resume after review:
.venv\Scripts\python.exe -B -m src.phase6.detectability_batch --run-instance CFV1_RA_CS_004_SEED1001_VAL --review-approved
```

`--status` reports full-sweep completion markers separately from the prevalidated pilot. Currently there are zero full-run markers and one separately verified pilot. The full driver imports that pilot without another GNN run when its inventory entry is encountered. Resume validates all marked artifacts; final validation requires 171 evaluable campaigns in BOTH systems, not just marker presence.

## Tests, preservation and current gate

288 distinct current tests passed: 268 Phase 6 regression tests (35 new methodology/execution cases) plus 20 accepted-runtime synthetic self-tests. One existing TEST-manifest-opening test is deliberately excluded; pre-access TEST guards passed. Exact commands, timings, warning types and coverage are in testing_results_v1.json.

All 12,182 prior inventoried files remain byte-identical. The original Phase 5/6 data, local-only/indicator journals, models, thresholds, policies, hashes, acceptance evidence and earlier workbooks are untouched. Protocol and plan source hashes are frozen in preregistration/execution records.

Next action: user review of this frozen definition, pilot evidence, execution/resource plan and exact commands. Do not launch the full sweep until approval. Keep Subphase 8 IN_PROGRESS until all 171 instances have been evaluated and validated. Do not begin Subphase 9 without explicit Subphase 8 acceptance.
