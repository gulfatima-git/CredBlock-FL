# Phase 6 Subphase 8 (6.6): Local Detectability Boundary



**Final technical status: PASS. Ready for user review and acceptance. USER_ACCEPTED has not been recorded. Subphase 9 has not started.**



Date: 16 November 2026 (Asia/Karachi). This report supersedes the blocking review decision through an append-only, user-approved audit continuation. All earlier review records remain preserved.



## Independent audit scope and exact evidence



Verified all **171/171 frozen VAL campaign instances**, all **855/855 organization replays**, **342 campaign-policy rows**, **1,098 targeted organization-policy rows**, and all saved private target-User/alert-attribution records. Every campaign, organization and User result was independently reconstructed from saved predictions and VAL-only offline positive evidence; the auditor does not call the accepted campaign evaluator or perform GNN inference.

The audit verified **1,362 completion manifests**, **15,302 manifest artifact-hash entries**, **12,182 pre-Subphase-8 file hashes**, and the reviewed source/configuration/document identities. It separately reconstructed complete deterministic indicator issuance and checked every journal observation against its original VAL observation Parquet.

Frozen models, all ten original threshold artifacts, labels, split assignments, primary protocol, feature/sampler/runtime sources and earlier acceptance evidence were preserved through the prior-artifact inventory. New outputs are additive review records only. TEST-containing preserved files were processed only as opaque bytes for integrity hashes: no TEST outcome table was queried or used for development.



## SQLite sidecar finding and resolution



The complete inventory contains **1,710 sidecars: 855 WAL and 855 SHM files** for 855 source databases. Every WAL was zero bytes. Every SHM was classified as SQLite auxiliary WAL coordination/index state, rather than authoritative research output. Each sidecar has a path, database association, byte size, role and SHA256 in before/after inventories. Those inventories match exactly after immutable inspection. Every source database passed SQLite integrity_check.

All manifest-listed authoritative artifacts retain their original hashes. No rollback journal or unresolved nonempty WAL was accepted. Empty WALs establish that no WAL frames need incorporation into the sealed database; SQLite header and integrity checks then establish readable self-contained database structure. This does not prove a hypothetical power-loss scenario or infer safety from only one database.

No database or sidecar was deleted, checkpointed, resealed or regenerated. All SQL connections used mode=ro&immutable=1 after the full WAL preflight. Unexpected non-sidecar files remain errors. The original failed review and its evidence remain hash-preserved.



Two additional independent-checker assumptions were corrected in preserved continuation attempts: the journal digest is over canonical LF lines while Windows file-byte hashes include CRLF, and independently serialized organization rows initially omitted existing coverage/status/onset fields. The corrected checker verifies both original byte seals and the intended logical digest and compares all original result fields. These were checker corrections; no accepted source, protocol, score, threshold or saved outcome was changed. A superseded read-only checker was stopped to avoid unnecessary repeated audit work; no evaluation batch was stopped or restarted.



## Frozen operational definition



A campaign is an isolated (variant_id, campaign_id) branch. Accounts are keyed by branch, organization and local User. The observation horizon is [first actual positive campaign authentication across targeted organizations, declared campaign end). Local and User exposure onsets are retained separately. Full replay extends to end minus one microsecond and retains the final ten minutes.

A qualifying alert must concern the same local exposed User, be inside the horizon and have matching positive campaign evidence in (alert time minus ten minutes, alert time]. Exactly one candidate campaign receives credit; multiple candidates are ambiguous and receive none. Unrelated/pre-onset/stale/end-or-later alerts do not qualify. Attribution is operational association, not proof that the attack caused the alert.

An organization detects a campaign if at least one exposed User has a qualifying alert. Campaign detection means ANY targeted organization detects; ALL and partial detection are separate. The primary locally-undetected classification requires complete positive exposure and coverage at every targeted organization and zero qualifying detections everywhere. Missing coverage cannot become undetected. No-alert detection time is null and right-censored at the frozen end, never replaced by a finite number.



## Complete local-only versus indicator-sharing results



| Policy | Campaigns detected | Undetected everywhere | All targeted orgs detect | Partially detected | Org trials detected | Target-User occurrences detected | Qualifying alert rows |
|---|---|---|---|---|---|---|---|
| local_only | 171/171 | 0/171 (0%) | 170 | 1 | 548/549 | 13,733/36,000 | 59,121 |
| local_plus_indicator | 171/171 | 0/171 (0%) | 170 | 1 | 548/549 | 15,111/36,000 | 61,297 |



Target-User occurrences are local branch-specific exposed targets, not globally unique people or independent trials. Repeated scoring decisions are not unique Users. Targeted-organization denominators exclude non-targeted organizations; operational rows below include all five organizations.



| Organization | Policy | Detected targeted org trials | Detected target-User occurrences | Qualifying alert rows |
|---|---|---|---|---|
| Org1 | local_only | 129/129 | 2,701/8,508 | 12,398 |
| Org1 | local_plus_indicator | 129/129 | 3,078/8,508 | 12,986 |
| Org2 | local_only | 90/90 | 2,181/5,796 | 8,973 |
| Org2 | local_plus_indicator | 90/90 | 2,424/5,796 | 9,361 |
| Org3 | local_only | 90/90 | 2,421/5,796 | 9,651 |
| Org3 | local_plus_indicator | 90/90 | 2,614/5,796 | 10,013 |
| Org4 | local_only | 129/129 | 3,943/8,634 | 16,918 |
| Org4 | local_plus_indicator | 129/129 | 4,182/8,634 | 17,241 |
| Org5 | local_only | 110/111 | 2,487/7,266 | 11,181 |
| Org5 | local_plus_indicator | 110/111 | 2,813/7,266 | 11,696 |



## Empirical detectability boundary



**Local-only: 0/171 campaigns (0%) remained undetected by every targeted organization. Local plus indicators: 0/171 (0%).** Thus this frozen VAL inventory contains no campaign satisfying the primary all-targeted-organizations local non-detection definition. This is a measured finding, not an assumption based on generated volume.

Campaign-wide detection is a permissive ANY-organization endpoint. It does not establish complete User detection or success in every targeted organization. The undetected targeted-organization trials are listed below; all have null time-to-detection and explicit right-censoring.



| Variant | Organization | Policy | Target Users exposed | Detected Users | Censor horizon (s) |
|---|---|---|---|---|---|
| CFV1_RA_CS_030_SEED1002_VAL | Org5 | local_only | 84 | 0 | 3598.321715 |
| CFV1_RA_CS_030_SEED1002_VAL | Org5 | local_plus_indicator | 84 | 0 | 3598.321715 |



Indicator assistance added **1,378 detected local target-User occurrences**, improved User coverage in **146 campaigns**, and advanced first campaign detection in **0 campaigns**. It rescued no additional wholly missed campaigns under the primary definition. Exact paired timing differences appear in paired_campaign_changes.csv.

This inventory cannot demonstrate a later federated rescue of campaigns that every local organization missed because that subset is empty here. Later phases may investigate User coverage, timing and fixed-FPR gains under their approved protocol, but must not claim the empty subset is populated. No post-hoc dataset, threshold or attribution changes were made to manufacture sub-threshold campaigns.



## Factor-specific results and denominators



All 57 configurations appear under each of seeds 1001, 1002 and 1003 (171 instances). Each split-local inventory contains 81 Raccount controlled instances, 81 Sorg controlled instances and nine single-organization descriptive references. All five organizations have 171 replay records; targeted-trial counts differ by the frozen organization selections. All 342 detector/design/factor/seed cells have complete evaluation, with no pending cells.



| Design family | Policy | Campaigns | Undetected | Org trials detected | Detected User occurrences |
|---|---|---|---|---|---|
| Raccount_fixed_per_org_attempts | local_only | 81 | 0 | 269/270 | 5660/17550 |
| Sorg1_descriptive_reference | local_only | 9 | 0 | 9/9 | 693/900 |
| Sorg_fixed_per_org_attempts | local_only | 81 | 0 | 270/270 | 7380/17550 |
| Raccount_fixed_per_org_attempts | local_plus_indicator | 81 | 0 | 269/270 | 6312/17550 |
| Sorg1_descriptive_reference | local_plus_indicator | 9 | 0 | 9/9 | 693/900 |
| Sorg_fixed_per_org_attempts | local_plus_indicator | 81 | 0 | 270/270 | 8106/17550 |



For RIP, Raccount and Sorg, factor_results.csv provides family-stratified counts, detection fractions, organization denominators, User coverage and qualifying alerts at each factor level. factor_seed_results.csv preserves every joint factor/seed cell. Each individual campaign is retained in campaign_results.csv, so aggregate zero non-detection cannot conceal an uncomputed cell.

RIP is distinct attacker IPs divided by attack attempts, not temporal IP-switch rate. Raccount is cross-organization synthetic credential reuse; single-organization values remain N/A. Raccount changes target coverage/per-User intensity despite matched per-org attempt budgets. Sorg fixed-per-org budgets change total volume and org composition. Descriptive references and the two controlled families must not be pooled to imply a causal one-factor effect.



### Marginal factor summaries within design families



| Design family | Factor | Level | Policy | Campaigns | Undetected everywhere | Detected User occurrences |
|---|---|---|---|---|---|---|
| Raccount_fixed_per_org_attempts | RIP_target | 0.2 | local_only | 27 | 0 (0.0%) | 2667/5850 |
| Raccount_fixed_per_org_attempts | RIP_target | 0.5 | local_only | 27 | 0 (0.0%) | 1714/5850 |
| Raccount_fixed_per_org_attempts | RIP_target | 0.8 | local_only | 27 | 0 (0.0%) | 1279/5850 |
| Sorg1_descriptive_reference | RIP_target | 0.2 | local_only | 3 | 0 (0.0%) | 249/300 |
| Sorg1_descriptive_reference | RIP_target | 0.5 | local_only | 3 | 0 (0.0%) | 233/300 |
| Sorg1_descriptive_reference | RIP_target | 0.8 | local_only | 3 | 0 (0.0%) | 211/300 |
| Sorg_fixed_per_org_attempts | RIP_target | 0.2 | local_only | 27 | 0 (0.0%) | 3195/5850 |
| Sorg_fixed_per_org_attempts | RIP_target | 0.5 | local_only | 27 | 0 (0.0%) | 2258/5850 |
| Sorg_fixed_per_org_attempts | RIP_target | 0.8 | local_only | 27 | 0 (0.0%) | 1927/5850 |
| Raccount_fixed_per_org_attempts | RIP_target | 0.2 | local_plus_indicator | 27 | 0 (0.0%) | 3118/5850 |
| Raccount_fixed_per_org_attempts | RIP_target | 0.5 | local_plus_indicator | 27 | 0 (0.0%) | 1867/5850 |
| Raccount_fixed_per_org_attempts | RIP_target | 0.8 | local_plus_indicator | 27 | 0 (0.0%) | 1327/5850 |
| Sorg1_descriptive_reference | RIP_target | 0.2 | local_plus_indicator | 3 | 0 (0.0%) | 249/300 |
| Sorg1_descriptive_reference | RIP_target | 0.5 | local_plus_indicator | 3 | 0 (0.0%) | 233/300 |
| Sorg1_descriptive_reference | RIP_target | 0.8 | local_plus_indicator | 3 | 0 (0.0%) | 211/300 |
| Sorg_fixed_per_org_attempts | RIP_target | 0.2 | local_plus_indicator | 27 | 0 (0.0%) | 3676/5850 |
| Sorg_fixed_per_org_attempts | RIP_target | 0.5 | local_plus_indicator | 27 | 0 (0.0%) | 2453/5850 |
| Sorg_fixed_per_org_attempts | RIP_target | 0.8 | local_plus_indicator | 27 | 0 (0.0%) | 1977/5850 |
| Raccount_fixed_per_org_attempts | Raccount_target | 0.2 | local_only | 27 | 0 (0.0%) | 2375/3960 |
| Raccount_fixed_per_org_attempts | Raccount_target | 0.5 | local_only | 27 | 0 (0.0%) | 1920/5850 |
| Raccount_fixed_per_org_attempts | Raccount_target | 0.8 | local_only | 27 | 0 (0.0%) | 1365/7740 |
| Raccount_fixed_per_org_attempts | Raccount_target | 0.2 | local_plus_indicator | 27 | 0 (0.0%) | 2527/3960 |
| Raccount_fixed_per_org_attempts | Raccount_target | 0.5 | local_plus_indicator | 27 | 0 (0.0%) | 2203/5850 |
| Raccount_fixed_per_org_attempts | Raccount_target | 0.8 | local_plus_indicator | 27 | 0 (0.0%) | 1582/7740 |
| Sorg1_descriptive_reference | Sorg_target | 1 | local_only | 9 | 0 (0.0%) | 693/900 |
| Sorg_fixed_per_org_attempts | Sorg_target | 2 | local_only | 27 | 0 (0.0%) | 1688/4050 |
| Sorg_fixed_per_org_attempts | Sorg_target | 3 | local_only | 27 | 0 (0.0%) | 2182/5400 |
| Sorg_fixed_per_org_attempts | Sorg_target | 5 | local_only | 27 | 0 (0.0%) | 3510/8100 |
| Sorg1_descriptive_reference | Sorg_target | 1 | local_plus_indicator | 9 | 0 (0.0%) | 693/900 |
| Sorg_fixed_per_org_attempts | Sorg_target | 2 | local_plus_indicator | 27 | 0 (0.0%) | 1807/4050 |
| Sorg_fixed_per_org_attempts | Sorg_target | 3 | local_plus_indicator | 27 | 0 (0.0%) | 2400/5400 |
| Sorg_fixed_per_org_attempts | Sorg_target | 5 | local_plus_indicator | 27 | 0 (0.0%) | 3899/8100 |



These are descriptive marginal summaries within each named family, not independent treatment-effect estimates. The complete joint factor/seed cells remain authoritative for coverage.



## Operational evidence and reproducibility



| Measure | Verified count |
|---|---|
| events | 350,196 |
| scoring_decisions | 2,548,188 |
| local_alerts | 222,018 |
| combined_alerts | 224,251 |
| additional_alerts | 2,233 |
| indicators_issued | 26,464 |
| indicators_received | 105,856 |
| event_only_unscored_rows | 0 |
| final_ten_minutes_events | 58,461 |
| final_ten_minutes_scores | 485,530 |



Every stored local score retains the original model/schema/threshold identity and exact binary64 logit comparison. Every paired row matches its original local journal. Current authentication IPs, issue availability, exclusive expiration and receiving organizations were independently recomputed. Every indicator was reconstructed from original local alerts and the observable recent ten-minute authentication evidence, including duplicate suppression and no-evidence behavior. No synthetic attacker-IP truth selected an indicator.

Normal and reverse-order sharing traces match at every paired/additional decision byte digest, network digest and final local graph hash. Full campaign/organization/User outcomes and private attribution digests match the saved evaluator outputs. The independent audit separately verifies saved lifecycle records and exact original observation content, including non-targeted organizations.



Real data attribution counts: UNIQUE=120,418; AMBIGUOUS=0; UNATTRIBUTED=325,851. Each frozen branch contains one campaign; zero observed ambiguity is not evidence of overlapping real campaigns. The boundary suite tests multiple-campaign ambiguity, temporal edges and repeated identities separately.

The 35 existing detectability and batch boundary tests passed without accessing TEST outcomes or running real GNN inference. These are tests of method and orchestration semantics; the 171-instance audit supplies full real-evidence coverage. Earlier preserved smoke/representative and full-training evidence retains its original scope.



## Resource measurements



| Organization | Fresh / reused replays | Fresh replay wall sum (s) | Max observed RSS (MiB) | Median of replay p95 timestamp latencies (s) |
|---|---|---|---|---|
| Org1 | 170 / 1 | 76426.058 | 472.043 | 1.398880 |
| Org2 | 170 / 1 | 77720.671 | 476.426 | 1.489029 |
| Org3 | 170 / 1 | 92416.094 | 481.336 | 1.573243 |
| Org4 | 170 / 1 | 97059.410 | 484.645 | 1.643286 |
| Org5 | 170 / 1 | 104383.656 | 487.695 | 1.716887 |



These are original measured component resources, not new inference benchmarks. Wall-time sums add organization jobs that may overlap; they are not full-sweep elapsed time. Median replay p95 is a distribution of per-replay p95 values, not a pooled event p95. Host concurrency, startup and I/O affect timings. Full-sweep wall time was not recorded as an authoritative benchmark and is not inferred from file timestamps or the earlier runtime estimate.

Independent main evidence audit elapsed 1445.203 seconds; issuance/source supplement elapsed 1228.843 seconds. No costly model inference was repeated.



## Scientific limitations for the paper



- VAL was used for model selection and calibration; these operational results are not final held-out TEST estimates. TEST outcomes were not queried.

- The frozen 1% empirical FPR concerns eligible clean-negative fixed-grid User-time examples. It is not an operational event-driven or campaign FPR, and clean-negative candidates do not certify benignness.

- Alternative worlds reuse background and only three temporal seed blocks. Users, rows, campaign variants and organization trials are dependent; no IID confidence intervals or independent-replication claims are made.

- Temporal alert attribution cannot prove that injected activity, rather than background behavior, caused the alert. Unattributed alerts are not automatically verified false positives.

- Finite horizon, right-censoring and selected campaign generator bound conclusions. No detection after the exclusive end is claimed.

- Zero-delay sharing is a separate suspicious-IP comparison baseline, not realistic network latency or the CredBlock-FL federation mechanism.

- The observed all-targeted-undetected set is empty. The headline question about rescuing locally invisible campaigns is not empirically demonstrated by this VAL set. Do not alter accepted data or thresholds post hoc.

- Graph state, source logs and User identifiers remain local private artifacts. Public reports aggregate branch-local User counts and do not create a cross-organization identity index.

- No federation, DP, robust aggregation, Fabric or final TEST evaluation was performed in this subphase.



## Provenance and artifact locations



- Frozen method: configs/phase6/detectability_protocol_v1.json; SHA256 f63e0bb73253eea4a8c8d7abc4231f94069aaf15c3eef68eeb3fa1b00d49bc55.

- Frozen primary split/grid/FPR protocol SHA256: 9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b.

- Original full execution: reports/phase6/detectability/full_v1/instances/<variant>/ and full_v1/validated_171/attempt_00001/.

- Independent main audit: technical_review_v2/continuation_00004/; includes per-instance validation, campaign/organization/factor-seed/operational CSVs, source hash inventory, resources, complete sidecar before/after inventory and summary.

- Independent complete issuance/source proof: technical_review_v2/issuance_and_observation_audit_v1/.

- Final report, aggregates, factor tables, timing changes and resource table: technical_review_v2/final_v1/.

- Original stopped review: technical_review_v1/. Continuation attempts are retained in technical_review_v2/ without overwriting them.



## Next action



User reviews this report and explicitly accepts or requests correction of Subphase 8. The technical gate passes; USER_ACCEPTED is not recorded. Subphase 9 remains NOT_STARTED. No additional execution is authorized by this report.
