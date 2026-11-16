# Phase 6 Subphase 9 (6.7): TRAIN/VAL reporting technical acceptance

**Technical result: PASS for the explicitly authorized Option A, Stages A/B reporting scope. Awaiting USER_ACCEPTED. TEST evaluation is DEFERRED and UNAUTHORIZED; Stage C is unimplemented. Full Phase 6 completion remains PENDING. Phase 7 has not started.**

Date: 17 November 2026 (Asia/Karachi). The user supplied the authoritative four research questions and six projected contributions during this subphase; their exact wording is preserved in research_alignment.json and the new workbook. No model, feature, sampler, threshold, dataset, temporal split or attribution rule was changed.

## Scope, artifacts and implemented behavior

New additive reporting code reads only frozen TRAIN/VAL prediction CSVs and accepted summaries. TEST split and path requests are rejected before prediction I/O. There is no TEST adapter, training entry point, calibration call, model forward pass, operational inference replay or original campaign-evaluator call in the reporting path. Existing source files and restrictions remain intact.

The report consolidates **414,573 paired eligible TRAIN User-times** and **285,918 paired eligible VAL User-times** for two detector families over five organizations. Each org/split contains 171 campaign branches and 1,026 fixed-grid times. These are manifest-listed hours and dependent alternative branches, not continuous labeled coverage of entire calendar splits or all 31.27 million explored source records.

Created configuration final_reporting_v1.json; final_reporting.py, run_final_reporting.py and final_reporting_figures.py; new reporting tests; source inventories; exact tables; 11 publication figure sets in PNG/PDF; 19-sheet research workbook; alignment matrix; discrepancy register; and this report. Outputs are under reports/phase6/final/v1 and outputs/phase6_final_v1. Prior all-phases and Subphase 8 workbooks are unchanged.

## Exact primary fixed-grid VAL results

Operating metrics use the original per-org/per-detector binary64 logit thresholds calibrated on VAL at a 1% target. This is a target with finite-sample/tie constraints, not a claim that every achieved rate is exactly 1%. Best-local GraphSAGE selection remains locked for Org1–Org5.

| Org | Detector | Eligible | AP | BCE | TP | FP | TN | FN | Recall | Precision | F1 | FPR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Org1 | graphsage | 55386 | 0.743435620733 | 0.324969891456 | 2708 | 456 | 45315 | 6907 | 0.281643265731 | 0.855878634640 | 0.423820330229 | 0.009962640100 |
| Org1 | tabular_mlp | 55386 | 0.664224011469 | 0.370689006286 | 2423 | 399 | 45372 | 7192 | 0.252002080083 | 0.858610914245 | 0.389643804776 | 0.008717310087 |
| Org2 | graphsage | 51267 | 0.719192799891 | 0.394094665373 | 2215 | 399 | 44403 | 4250 | 0.342614075793 | 0.847360367253 | 0.487939200352 | 0.008905852417 |
| Org2 | tabular_mlp | 51267 | 0.584792066090 | 0.533623498337 | 1371 | 399 | 44403 | 5094 | 0.212064965197 | 0.774576271186 | 0.332969034608 | 0.008905852417 |
| Org3 | graphsage | 58005 | 0.653527055691 | 0.447068378244 | 2311 | 513 | 51072 | 4109 | 0.359968847352 | 0.818342776204 | 0.500000000000 | 0.009944751381 |
| Org3 | tabular_mlp | 58005 | 0.528775625830 | 0.539229760216 | 1395 | 513 | 51072 | 5025 | 0.217289719626 | 0.731132075472 | 0.335014409222 | 0.009944751381 |
| Org4 | graphsage | 57615 | 0.782557214426 | 0.379203955584 | 4086 | 456 | 47538 | 5535 | 0.424695977549 | 0.899603698811 | 0.576996399068 | 0.009501187648 |
| Org4 | tabular_mlp | 57615 | 0.665935166869 | 0.455626326945 | 2422 | 456 | 47538 | 7199 | 0.251740983266 | 0.841556636553 | 0.387551004080 | 0.009501187648 |
| Org5 | graphsage | 63645 | 0.702085587416 | 0.571306415909 | 2390 | 456 | 55056 | 5743 | 0.293864502644 | 0.839775122980 | 0.435376628108 | 0.008214440121 |
| Org5 | tabular_mlp | 63645 | 0.600009809640 | 0.622859641728 | 2142 | 513 | 54999 | 5991 | 0.263371449650 | 0.806779661017 | 0.397107897664 | 0.009241245136 |

### Macro and pooled summaries

| Split | Detector | Aggregation | Recall | Precision | F1 | FPR | AP |
|---|---|---|---|---|---|---|---|
| TRAIN | graphsage | equal_weight_macro | 0.431695813593 | 0.860132981740 | 0.569242302899 | 0.007573348488 | 0.706621405636 |
| TRAIN | graphsage | pooled_confusion_counts | 0.425778043138 | 0.857250187829 | 0.568963797746 | 0.007612667479 | Not pooled |
| TRAIN | tabular_mlp | equal_weight_macro | 0.272539976393 | 0.768239026765 | 0.401921742814 | 0.008861466354 | 0.556405674581 |
| TRAIN | tabular_mlp | pooled_confusion_counts | 0.273478120258 | 0.768795020631 | 0.403442454492 | 0.008830694275 | Not pooled |
| VAL | graphsage | equal_weight_macro | 0.340557333814 | 0.852192119978 | 0.484826511552 | 0.009305774334 | 0.720159655631 |
| VAL | graphsage | pooled_confusion_counts | 0.340587270830 | 0.857410881801 | 0.487518668658 | 0.009280969129 | Not pooled |
| VAL | tabular_mlp | equal_weight_macro | 0.239293839564 | 0.802531111695 | 0.368457230070 | 0.009262069334 | 0.608747335979 |
| VAL | tabular_mlp | pooled_confusion_counts | 0.242286480847 | 0.810521067066 | 0.373056400252 | 0.009280969129 | Not pooled |

Equal-weight five-organization macro is primary; pooled confusion-count summaries are secondary and do not replace org-level failures. AP is tied-score grouped, noninterpolated average precision. It is not renamed trapezoidal PR-AUC. Descriptive tied-score ROC-AUC is provided separately. Pooled AP/ROC are intentionally not invented from an average of organization scores. Undefined metric semantics remain explicit.

TRAIN operating metrics are retrospective in-sample diagnostics: the models fit TRAIN, but the frozen thresholds were selected on later VAL. They are not historical online deployment performance. Complete TRAIN confusion counts are in tables/fixed_grid_metrics.csv.

## Threshold, population and inductive evidence

| Org | Detector | Original binary64 hex threshold | Eligible negatives | FP budget | Actual FP | Achieved FPR |
|---|---|---|---|---|---|---|
| Org1 | graphsage | 0x1.2b94040000001p+2 | 45771 | 457 | 456 | 0.009962640099626401 |
| Org1 | tabular_mlp | 0x1.730b140000001p+1 | 45771 | 457 | 399 | 0.008717310087173101 |
| Org2 | graphsage | 0x1.24d71e0000001p+2 | 44802 | 448 | 399 | 0.008905852417302799 |
| Org2 | tabular_mlp | 0x1.a619360000001p+1 | 44802 | 448 | 399 | 0.008905852417302799 |
| Org3 | graphsage | 0x1.2e94900000001p+2 | 51585 | 515 | 513 | 0.009944751381215469 |
| Org3 | tabular_mlp | 0x1.1087020000001p+2 | 51585 | 515 | 513 | 0.009944751381215469 |
| Org4 | graphsage | 0x1.9b36740000001p+1 | 47994 | 479 | 456 | 0.009501187648456057 |
| Org4 | tabular_mlp | 0x1.ad57dc0000001p+1 | 47994 | 479 | 456 | 0.009501187648456057 |
| Org5 | graphsage | 0x1.d626f40000001p+1 | 55512 | 555 | 456 | 0.008214440121054907 |
| Org5 | tabular_mlp | 0x1.f8aec00000001p+1 | 55512 | 555 | 513 | 0.00924124513618677 |

Threshold decimal strings are preserved as text beside authoritative hexadecimal values in tables/calibration.csv and Excel. No threshold recalibration or post-threshold model re-selection occurred. All ten original VAL confusion matrices and FP budgets reconcile exactly. A subgroup or seed can exceed 1% even when the organization-wide calibration satisfies its budget; no subgroup recalibration is performed.

| Org | Split | Eligible positive | Eligible negative | Masked recent roots | Saved prediction rows |
|---|---|---|---|---|---|
| Org1 | TRAIN | 9546 | 65892 | 3534 | 78972 |
| Org1 | VAL | 9615 | 45771 | 2451 | 57837 |
| Org2 | TRAIN | 6474 | 70794 | 3021 | 80289 |
| Org2 | VAL | 6465 | 44802 | 3363 | 54630 |
| Org3 | TRAIN | 6477 | 76437 | 4275 | 87189 |
| Org3 | VAL | 6420 | 51585 | 4275 | 62280 |
| Org4 | TRAIN | 9579 | 77862 | 4902 | 92343 |
| Org4 | VAL | 9621 | 47994 | 2850 | 60465 |
| Org5 | TRAIN | 8121 | 83391 | 4845 | 96357 |
| Org5 | VAL | 8133 | 55512 | 3420 | 67065 |

Older graph context omitted from saved supervised roots is not silently counted as eligible negative data. Original background flags do not certify benignness. All 30 VAL detector/org inductive subgroup rows are in tables/inductive_subgroups.csv, with original TRAIN-unseen User and IP-context flags. IP nodes are context, never classification targets. Original masked-inside-population and outside-population counts are separate, resolving a presentation ambiguity without altering earlier calibration evidence.

## Local-only and immediate-sharing operational evidence

| Policy | Detected anywhere | Detected at every targeted org | Wholly undetected | Detected org trials | Detected local target-User occurrences | Qualifying alert rows |
|---|---|---|---|---|---|---|
| local_only | 171/171 | 170 | 0/171 (0%) | 548/549 | 13733/36000 | 59121 |
| local_plus_indicator | 171/171 | 170 | 0/171 (0%) | 548/549 | 15111/36000 | 61297 |

**The verified VAL all-targeted-undetected subset is empty: 0/171 under both policies.** Do not modify data, intensity, labels, thresholds or definitions to create such campaigns. No federated rescue of this empty subset can be demonstrated. This finding is carried into the alignment matrix and subsequent-phase constraints.

| Org | Policy | Detected targeted trials | Detected local User occurrences | Qualifying alerts |
|---|---|---|---|---|
| Org1 | local_only | 129/129 | 2701/8508 | 12398 |
| Org1 | local_plus_indicator | 129/129 | 3078/8508 | 12986 |
| Org2 | local_only | 90/90 | 2181/5796 | 8973 |
| Org2 | local_plus_indicator | 90/90 | 2424/5796 | 9361 |
| Org3 | local_only | 90/90 | 2421/5796 | 9651 |
| Org3 | local_plus_indicator | 90/90 | 2614/5796 | 10013 |
| Org4 | local_only | 129/129 | 3943/8634 | 16918 |
| Org4 | local_plus_indicator | 129/129 | 4182/8634 | 17241 |
| Org5 | local_only | 110/111 | 2487/7266 | 11181 |
| Org5 | local_plus_indicator | 110/111 | 2813/7266 | 11696 |

Indicator sharing adds 1,378 detected local target-User occurrences across 146 campaigns, with no additional detected campaign and no earlier first campaign detection. Operational User coverage rises from 38.147222% to 41.975000%. Local User occurrences are branch-local targets, not globally unique people. The single missed organization trial is Org5 in CFV1_RA_CS_030_SEED1002_VAL, with 84 exposed Users, zero qualifying detections and right-censoring under both policies.

The saved operational stream contains 350,196 events and 2,548,188 paired scoring decisions, 222,018 local alerts versus 224,251 combined alerts, 26,464 issued indicators and 105,856 receipts. All final-ten-minute evidence is retained. These are accepted Subphase 8 aggregates, imported and reconciled without repeating campaign evaluation. Operational rows include non-targeted organizations; targeted-trial denominators do not.

This event-driven comparison is not an indicator-versus-local primary fixed-grid recall-at-FPR result. The 1% fixed-grid clean-negative FPR target does not transfer to arbitrary event-triggered or campaign decisions. No operational FPR/precision is fabricated from unattributed alerts.

## Time-to-detection and censoring

| Policy | Unit | Total | Detected | Right censored | Median detected delay (s) | Time origin |
|---|---|---|---|---|---|---|
| local_only | campaign | 171 | 171 | 0 | 152.672165 | actual_global_campaign_onset |
| local_only | targeted_organization_trial | 549 | 548 | 1 | 440.920191 | actual_global_campaign_onset |
| local_only | local_target_User_occurrence | 36000 | 13733 | 22267 | 313.009918 | first_local_User_positive_exposure |
| local_plus_indicator | campaign | 171 | 171 | 0 | 152.672165 | actual_global_campaign_onset |
| local_plus_indicator | targeted_organization_trial | 549 | 548 | 1 | 401.136626 | actual_global_campaign_onset |
| local_plus_indicator | local_target_User_occurrence | 36000 | 15111 | 20889 | 105.819666 | first_local_User_positive_exposure |

Censored observations retain null detection times and their frozen observation horizon. The curves show observed detection fractions, not IID survival inference. User-delay medians are conditional on detection and compare different detected-User populations; their difference must not be claimed as a paired causal speedup. Campaign first-detection times are identical between policies. Attribution requires uniquely associated recent positive evidence inside the frozen horizon; real branches contain one campaign and zero observed ambiguity. Existing overlap/ambiguity boundary tests establish rule behavior, not the presence of real overlapping campaigns.

## Factors, seeds and controlled-design limits

All 57 VAL configurations occur under each of seeds 1001, 1002 and 1003. Family totals are 81 Raccount controlled instances, 81 Sorg controlled instances and nine descriptive Sorg1 references. All 342 detector/design/joint-factor/seed cells remain complete. Primary fixed-grid factor strata and campaign factor strata have separate tables and units.

tables/seed_metrics.csv contains 30 frozen-threshold seed/org/detector rows; tables/fixed_grid_factor_metrics.csv contains family-stratified fixed-grid confusion metrics. The accepted operational factor_results.csv and factor_seed_results.csv are incorporated unchanged in Excel and are pinned in provenance. tables/campaign_context_v2.csv lists all 171 VAL campaign durations, attack attempts, background counts, targeted organizations, attack/background ratios, exposed local targets and settings from hash-verified saved manifests.

RIP is distinct attacker IPs per attempt, not the chronological switching rate. Raccount is distinct synthetic credential reuse, evaluator-only and N/A for Sorg1. Raccount controls can still change target coverage and per-User intensity despite matched per-org attempt budgets. Sorg fixed-per-org budgets change total campaign volume and organization composition. Shared background and only three temporal blocks preclude naive IID confidence intervals over rows, Users, branches or organizations. Descriptive variability is retained; no new significance claim or fitted non-detection boundary curve is introduced.

## Original resource measurements

| Org | Detector | Selected trial (s) | All trials + repeat (s) | Observed training RSS (MiB) | Preparation (s) |
|---|---|---|---|---|---|
| Org1 | graphsage | 548.2039883001707 | 1351.4068148003425 | 377.82421875 | 2939.579461300047 |
| Org1 | tabular_mlp | 107.76726540000163 | 303.798722800002 | 407.1484375 | 42.838422199998604 |
| Org2 | graphsage | 619.8200974999927 | 1310.0156231999863 | 358.01171875 | 3111.4351283998694 |
| Org2 | tabular_mlp | 62.121977900000275 | 104.36070479999944 | 407.45703125 | 46.86398290000034 |
| Org3 | graphsage | 170.90513430000283 | 364.35760879982263 | 372.08984375 | 2803.07818880002 |
| Org3 | tabular_mlp | 87.09893549999833 | 198.1460442999978 | 410.9609375 | 32.08427429999938 |
| Org4 | graphsage | 54.85538939991966 | 239.70048639993183 | 379.7421875 | 2870.0889353998937 |
| Org4 | tabular_mlp | 84.17243550000057 | 219.48892440000236 | 412.62890625 | 48.779100099998686 |
| Org5 | graphsage | 251.16651379992254 | 484.106216999935 | 378.54296875 | 3630.918373099994 |
| Org5 | tabular_mlp | 178.02049249999982 | 481.42174479999994 | 413.93359375 | 46.32874089999859 |

Inference resources are the accepted per-org replay summaries in the workbook and prior resource_summary.csv: median per-replay p95 end-to-end timestamp latency ranges approximately 1.399–1.717 seconds across organizations; per-replay extrema and peak RSS remain visible. These are CPU research workloads, not sub-50/100-ms production claims. Sums of overlapping component runtimes are not full-sweep elapsed time, and a median of replay p95s is not a pooled event p95. No models or inference workloads were rerun for timing.

## Research Question and Contribution Alignment Matrix

Source: user-supplied research statement, 17 November 2026. The main question concerns federated detection of campaigns sub-threshold everywhere without sharing raw logs. The matrix assesses design intent separately from implementation and evidence. All four RQs and six projected contributions are included in original order. Original wording is preserved in research_alignment.json, tables/research_alignment.csv and the workbook; the following matrix contains the complete evidence assessment.

| Item | Designed to achieve | Actually implemented | Evidence available | Untested / unsupported | Responsible subsequent phase | Claims currently permitted | Claims currently prohibited |
|---|---|---|---|---|---|---|---|
| RQ1 | Compare transferable federated graph learning with both baselines under controlled RIP/Raccount/Sorg and a common fixed-FPR protocol. | Five local GraphSAGE models, five non-graph MLPs, VAL-based best-local selection, frozen thresholds, causal local inference and separate immediate indicator sharing. | Full saved TRAIN/VAL fixed-grid evidence and independently verified 171 VAL operational campaigns; 0/171 wholly undetected locally, 548/549 organization trials detected, User coverage 13,733 versus 15,111 of 36,000. | No federated comparison, no measured federated recall difference, no held-out TEST outcomes. The all-targeted-undetected VAL subset is empty. | Phase 7 federated baseline; Phase 8 private/robust variants; Phase 11 controlled final comparison. Held-out Phase 6 evaluation remains deferred. | Local baseline construction and development-set detectability measurements; report zero wholly undetected VAL campaigns exactly. | Federation outperforms either baseline, rescues this empty subset, reconstructs cross-site IP links, or generalizes to TEST. |
| RQ2 | Measure detection/overhead against formal user-level epsilon/delta, contribution bounds, clipping and cumulative accounting. | Local-data isolation and reusable model/features only; no formal DP mechanism, privacy accountant or private federated training. | Non-private local reference metrics and resource records. Keeping logs local is not a formal DP guarantee. | No privacy budget sweep, composed privacy loss, DP utility curve or positive federated difference under DP. | Phase 8 user-level DP and privacy-utility experiments; Phase 11 final comparison. | The framework is designed for user-level privacy and the local reference exists. | Implemented user-level DP, any epsilon/delta guarantee, a privacy-utility result, or privacy merely from organization-level clipping. |
| RQ3 | Screen privacy-protected updates and measure poisoning degradation together with false exclusion of honest non-IID organizations. | Five non-IID simulated organizations and local reference models; no update screening or robust aggregation. | Organization-specific local behavior, metrics and resource differences provide the reference only. | No poisoned-update experiment, malicious-update rejection rate, honest-exclusion rate or robust detection preservation. | Phase 8 robust aggregation, one/two poisoned-client and honest-exclusion experiments; Phase 11 final audit. | Non-IID local foundations are established and fairness must be evaluated later. | Poisoning resistance, fair update exclusion or poison-proof aggregation. |
| RQ4 | Measure signed commitment, endorsement, acknowledgment, verification and storage/availability costs for five-organization rounds. | No integrated Fabric round protocol or ledger measurement in Phase 6; an earlier basic proof of concept is historical, not this subphase's implementation. | Local detector and indicator resource records only; these are not ledger or federated-round overhead. | No integrated per-round ledger latency, storage growth, five-of-five outage behavior or model-adoption failure evidence. | Phase 10 integrated ledger and failure tests; Phase 11 with/without-ledger overhead comparison; Phase 9 isolated deployment support. | A permissioned audit ledger is a proposed integrity component with defined limits. | Measured ledger overhead, implemented round verification, or proof of correct aggregation/DP/model quality from hashes. |
| C1 | Operationally define all-targeted local non-detection and investigate collaborative pattern learning over separate temporal graphs. | Frozen onset, observation horizon, qualifying User alert attribution, all-targeted-organizations rule and censoring; local temporal graph pipeline. | Independent 171-instance VAL audit, complete local coverage and boundary tests; measured wholly undetected fraction is zero. | No nonempty wholly-undetected VAL subset and no federated solution to its detection; conceptual novelty is not established by software tests. | Phase 7 collaborative implementation; Phase 11 detectability/claim evaluation; literature-based novelty argument remains a manuscript task. | An operational definition and measured local boundary on this frozen benchmark. | All low-volume campaigns evade local detectors or that the present dataset demonstrates locally invisible campaigns. |
| C2 | Transfer learned patterns through private updates while keeping logs, graphs, User IDs and credential mappings local. | Independent local graphs, models, input contracts and continuous inference. Federation and DP are absent. | Five local checkpoint/reproducibility records and local-only operational validation; explicit indicator sharing is a separate baseline. | No shared/global model, DP update exchange, cross-organization gain or legal-compliance guarantee. | Phase 7 federation; Phase 8 formal DP; Phase 9 deployment; Phase 11 evaluation. | A proposed federated design supported by implemented local foundations. Explain cross-organizational view as transferable learned patterns. | An implemented private federation, reconstructed cross-organization graph, shared IP identity index, or established regulatory compliance. |
| C3 | Characterize where federated advantage exists, vanishes or reverses under controlled campaign factors. | Controlled synthetic campaign inventory, measured factors, accepted local/indicator baselines and family-stratified VAL reporting. | 171 VAL campaigns; 0/171 wholly locally undetected; complete factor/seed denominators and incomplete targeted-User coverage. | No measured federated boundary or evidence that prospective real participants would benefit; generator and background dependence limit external validity. | Phase 7 federated baseline; Phase 8 private/robust comparisons; Phase 11 final boundary characterization. | A local development-set boundary and explicit experimental controls/limitations. | A federated advantage region, direct infrastructure correlation, or deployment benefit established by these local results. |
| C4 | Robust screening of DP-protected updates with explicit honest-client exclusion accounting. | Non-IID reference organization datasets; no shared updates, DP, screening or averaging. | Local reference metrics only. | Poisoning resistance and protection from unfair exclusion are untested design goals. | Phase 8 robust rule and DP interaction experiments; Phase 11 full comparison. | The framework plans a named robust rule and an honest-exclusion audit. | Implemented robust private aggregation or guaranteed non-exclusion of honest clients. |
| C5 | Five-organization endorsed, acknowledged commitment records and verify-before-adopt with fallback. | No integrated Fabric round protocol in Phase 6; local hashes/model-version checks do not implement a ledger. | Local artifact integrity and model/threshold identity evidence, not consortium endorsement or signed update commitments. | No integrated endorsement, attribution, round finalization, equivocation/failure or verified global-model adoption experiment. | Phase 10 signed commitments, endorsement and adoption; Phase 11 integrity/overhead validation. | Proposed non-repudiation and model-byte consistency goals; acknowledge the earlier PoC separately. | Implemented integrated ledger guarantees or mathematical aggregation correctness, DP correctness or model safety from hashes. |
| C6 | End-to-end RQ1–RQ4 evaluation with reproducible scope, negative findings and mechanism costs. | Synthetic web-authentication substrate, five simulated partitions, controlled campaigns, TRAIN/VAL local/indicator reporting and resource measurements. | Local GraphSAGE beats the tested MLP by VAL AP in all five organizations; primary threshold and operational results are saved. TEST is deferred. | No final headline for full CredBlock-FL, held-out generalization, privacy/robustness/ledger costs or cyber-physical deployment evidence. | Phases 7–10 implement components; Phase 11 final end-to-end evaluation; deferred Phase 6 TEST remains separately authorized work. | Precisely scoped local development-set results on simulated partitions, with observed resource costs and limitations. | Completed full-system evaluation, filled headline placeholders, production real-time SLA, formal privacy, robustness or cyber-physical effectiveness. |

### Architecture and draft-wording implications

Federated model-update sharing transfers learned local neighborhood patterns. It does not reconstruct an explicit cross-organization graph, align local identities, or directly match IP/credential infrastructure between organizations. No federation is implemented in Phase 6.

The supplied draft says the indicator baseline shares every observed attacking address immediately. The accepted runtime instead shares suspicious, unverified IPs attributed from actual local alerts and observable evidence, never an oracle attacker list. Paper wording must describe this accepted non-oracle mechanism; no runtime or protocol is changed here.

C2 cross-organizational view must mean learning transferable patterns through model updates, not explicit merging/reconstruction of User–IP graphs or direct IP/credential alignment. Current local GraphSAGE cannot reconstruct cross-organizational relationships. Indicator IP sharing belongs to the separate baseline. Formal DP, robust averaging, a shared global model and the final signed/endorsed ledger workflow do not exist in this subphase.

C1 and C3 are partially supported by an operational definition and measured local boundary; the full federated boundary and novelty/benefit claims remain unestablished. RQ2/C4 privacy/robustness and RQ4/C5 ledger claims remain future experimental work. The earlier basic Fabric proof of concept is historical evidence only, not an integrated Phase 6 round protocol or ledger benchmark. C6 placeholders for full-system headline results must remain unfilled; these are local development-set measurements, not completed CredBlock-FL evaluation.

Ledger hashes can establish committed-byte consistency and attribution within the future endorsement/acknowledgment protocol, not arithmetic correctness of aggregation, DP correctness or model accuracy. A consistently distributed incorrect aggregate is not automatically detected by hashing. Legal/regulatory compliance and cyber-physical deployment effectiveness are not established by these experiments.

## Tests, independent checks and preservation

**57 automated tests passed:** 26 new reporting tests and 31 existing synthetic temporal-contract tests. New tests cover TEST-before-I/O rejection, forbidden paths, tied-score AP/ROC, binary64 boundaries, masking/subgroups, undefined metrics, macro coverage, overwrite rejection, alignment completeness and absence of execution calls. Temporal tests use fixtures and metadata, not TEST payloads or trained model inference.

Independent reconciliation recomputed all 20 real saved prediction components using sklearn average_precision_score, roc_auc_score and confusion_matrix plus standard-library stable logit loss via math.fsum. Confusion counts match exactly; AP/ROC/loss match within 1e-12. All ten paired org/split cohorts match; all ten original VAL thresholds/confusion matrices/budgets match accepted evidence. There is no original campaign evaluator acting as the independent oracle.

All 12,254 pre-existing paths retain their original size and mtime; 241 critical accepted source/configuration/model/threshold/workbook files and 254 reporting inputs additionally passed before/after byte-hash checks. TEST paths were inspected only as preservation metadata; no TEST payload was opened or rehashed. This is not a claim that every source-dataset byte was freshly rehashed: the full Subphase 8 integrity audit remains preserved evidence.

The final workbook independently passed 58,578 source-cell comparisons, all 12 formula/cache checks, 21 native tables and 19-sheet structure checks. No formula-error cells exist. Visual review covered summary, matrix layout and representative figures. Original v1 workbook formatting draft and initial figure drafts are preserved. The native exporter terminated after saving with exit -1073740791; saved-file verification supports the deliverable, and the runtime warning is not concealed.

## Discrepancies and warnings

| ID | Classification | Exact finding / disposition |
|---|---|---|
| D1 | reporting_setup_error_resolved | Initial preparation assumed Org3–Org5 training files lived under full_v2. Existing sealed prediction provenance points to full_org3/4/5_v1. Preparation now derives the TRAIN file from its accepted VAL source directory; first failed attempt wrote only the preserved metadata snapshot. |
| D2 | reporting_setup_error_resolved | Best-local selection is stored as the string graphsage, not a dictionary. Corrected only the new reporting reader; accepted selections unchanged. |
| D3 | historical_reporting_ambiguity_retained | Older calibration subgroup masked counts include outside-subgroup rows. New tables separately report original masked-inside-population and outside-population. Detection counts and accepted summaries are unchanged. |
| D4 | draft_figure_presentation_corrected | Initial PR/ROC rendering used a staircase convention inconsistent with AP/trapezoidal ROC depiction. Final PR uses pre-step endpoint precision, ROC linear interpolation. Source numeric curves/metrics unchanged; draft images retained and figure_manifest_v2 identifies final figures. |
| D5 | export_runtime_warning | Artifact exporter saved both workbook drafts then exited -1073740791. Final v2 independently verified: ZIP, all 58,578 source cells, 12 cached formulas and 21 native tables pass. Initial formatting draft v1 preserved. |
| D6 | research_draft_wording_discrepancy | Draft every observed attacking address is not an oracle authorization. Accepted baseline shares suspicious IPs only after actual local alerts using observed recent evidence; paper must describe this non-oracle rule. |
| D7 | research_claim_limitation | VAL contains zero wholly locally-undetected campaigns; cannot demonstrate federated rescue of that empty subset. Formal DP, federation, poisoning robustness, integrated ledger costs and held-out performance remain untested. |
| D8 | external_validity_and_latency_limit | Five simulated partitions of synthesized web authentication data are not independent real owners or cyber-physical deployment evidence. Measured CPU end-to-end latency does not establish a production sub-50/100-ms SLA. |

No unresolved numerical reconciliation failure or changed accepted artifact was found. The limitations above restrict scientific claims; they are not repaired by modifying accepted results.

## Reproducibility, files and scope boundaries

Authoritative reporting inputs/configuration: configs/phase6/final_reporting_v1.json; tables/input_sha256.json; additional_source_sha256.json; figure_manifest_v2.json; preservation_verification.json. Research source and matrix: research_alignment.json. All exact tables are in tables/. Independent evidence: independent_reconciliation.json and testing_results.json. Final figures: outputs/phase6_final_v1/figures/ using the filenames in figure_manifest_v2.json. Final workbook: outputs/phase6_final_v1/CredBlock_FL_Phase6_TRAIN_VAL_Results_v2.xlsx.

Commands used (recorded for provenance, not instructions to rerun completed evaluations):

```text
.venv\Scripts\python.exe -B -m src.phase6.run_final_reporting
C:\Python314\python.exe -B <workspace>/subphase9_independent_reconciliation.py
C:\Python314\python.exe -B -m src.phase6.final_reporting_figures
C:\Python314\python.exe -B <workspace>/complete_subphase9_derived_tables.py
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/phase6/test_final_reporting.py
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/phase6/test_temporal_protocol.py
```

Existing outputs refuse overwrite. Any future reproduction must use a new isolated output version with the same frozen inputs; no evaluation or inference is needed to rebuild saved-score reporting. Audit sources and helper versions are preserved with delivery hashes. Reporting uses NumPy in the project environment, sklearn/matplotlib in the already installed C:\Python314 environment, and the bundled Artifact Tool for Excel. No dependency installation or accepted environment change occurred.

## Technical acceptance checklist and next action

| Requirement | Disposition |
|---|---|
| Stage A evidence inventory/reporting contract | PASS |
| Stage B exact TRAIN/VAL comparisons and figures | PASS |
| Four-RQ / six-contribution alignment matrix | PASS; unsupported claims explicitly marked |
| Independent saved-evidence reconciliation and relevant tests | PASS |
| Prior-artifact preservation and additive workbook | PASS within documented checks |
| TEST / Stage C | DEFERRED, explicitly unauthorized and unimplemented |
| Full Phase 6 completion | PENDING held-out evaluation |
| Subphase 9 Option A USER_ACCEPTED | AWAITING explicit user decision |
| Phase 7 and all later implementations | NOT_STARTED by this subphase |

The user may review and accept or request correction of the authorized Option A reporting work. That decision does not itself authorize TEST or Phase 7. No USER_ACCEPTED record is created by this report.
