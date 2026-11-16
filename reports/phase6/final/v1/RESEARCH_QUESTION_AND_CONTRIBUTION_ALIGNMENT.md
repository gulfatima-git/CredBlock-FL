# Research Question and Contribution Alignment

Authoritative research statement supplied directly by the user on 17 November 2026; numbered contributions follow its original order.

Federated model-update sharing transfers learned local neighborhood patterns. It does not reconstruct an explicit cross-organization graph, align local identities, or directly match IP/credential infrastructure between organizations. No federation is implemented in Phase 6.

## RQ1

Original: Under what conditions of attacker infrastructure rotation, per-organization spread, and cross-organization credential reuse does the federated detector exceed both the best single-organization detector and immediate cross-organizational indicator sharing, measured as the difference in recall at a fixed false-positive rate, and where does that difference vanish?

**Designed:** Compare transferable federated graph learning with both baselines under controlled RIP/Raccount/Sorg and a common fixed-FPR protocol.

**Implemented:** Five local GraphSAGE models, five non-graph MLPs, VAL-based best-local selection, frozen thresholds, causal local inference and separate immediate indicator sharing.

**Evidence:** Full saved TRAIN/VAL fixed-grid evidence and independently verified 171 VAL operational campaigns; 0/171 wholly undetected locally, 548/549 organization trials detected, User coverage 13,733 versus 15,111 of 36,000.

**Unsupported:** No federated comparison, no measured federated recall difference, no held-out TEST outcomes. The all-targeted-undetected VAL subset is empty.

**Subsequent Phases:** Phase 7 federated baseline; Phase 8 private/robust variants; Phase 11 controlled final comparison. Held-out Phase 6 evaluation remains deferred.

**Paper Can Claim:** Local baseline construction and development-set detectability measurements; report zero wholly undetected VAL campaigns exactly.

**Paper Cannot Claim:** Federation outperforms either baseline, rescues this empty subset, reconstructs cross-site IP links, or generalizes to TEST.

## RQ2

Original: Across the per-user privacy budget range examined, how does detection of this faint distributed signal vary, and which settings retain a positive difference in recall at the operating false-positive rate?

**Designed:** Measure detection/overhead against formal user-level epsilon/delta, contribution bounds, clipping and cumulative accounting.

**Implemented:** Local-data isolation and reusable model/features only; no formal DP mechanism, privacy accountant or private federated training.

**Evidence:** Non-private local reference metrics and resource records. Keeping logs local is not a formal DP guarantee.

**Unsupported:** No privacy budget sweep, composed privacy loss, DP utility curve or positive federated difference under DP.

**Subsequent Phases:** Phase 8 user-level DP and privacy-utility experiments; Phase 11 final comparison.

**Paper Can Claim:** The framework is designed for user-level privacy and the local reference exists.

**Paper Cannot Claim:** Implemented user-level DP, any epsilon/delta guarantee, a privacy-utility result, or privacy merely from organization-level clipping.

## RQ3

Original: How far is detection preserved when a minority of participating organizations submit poisoned updates, and at what rate does robust aggregation exclude honest organizations under non-IID partitioning?

**Designed:** Screen privacy-protected updates and measure poisoning degradation together with false exclusion of honest non-IID organizations.

**Implemented:** Five non-IID simulated organizations and local reference models; no update screening or robust aggregation.

**Evidence:** Organization-specific local behavior, metrics and resource differences provide the reference only.

**Unsupported:** No poisoned-update experiment, malicious-update rejection rate, honest-exclusion rate or robust detection preservation.

**Subsequent Phases:** Phase 8 robust aggregation, one/two poisoned-client and honest-exclusion experiments; Phase 11 final audit.

**Paper Can Claim:** Non-IID local foundations are established and fairness must be evaluated later.

**Paper Cannot Claim:** Poisoning resistance, fair update exclusion or poison-proof aggregation.

## RQ4

Original: What latency and storage overhead do ledger commitment and verification add per federated round at the evaluated scale?

**Designed:** Measure signed commitment, endorsement, acknowledgment, verification and storage/availability costs for five-organization rounds.

**Implemented:** No integrated Fabric round protocol or ledger measurement in Phase 6; an earlier basic proof of concept is historical, not this subphase's implementation.

**Evidence:** Local detector and indicator resource records only; these are not ledger or federated-round overhead.

**Unsupported:** No integrated per-round ledger latency, storage growth, five-of-five outage behavior or model-adoption failure evidence.

**Subsequent Phases:** Phase 10 integrated ledger and failure tests; Phase 11 with/without-ledger overhead comparison; Phase 9 isolated deployment support.

**Paper Can Claim:** A permissioned audit ledger is a proposed integrity component with defined limits.

**Paper Cannot Claim:** Measured ledger overhead, implemented round verification, or proof of correct aggregation/DP/model quality from hashes.

## C1

Original: We introduce the notion of a sub-threshold credential-stuffing campaign, defined as one spread so that activity at each targeted organization remains below the threshold that organization would apply alone, and formalize its detection as a cross-organizational graph-learning problem over temporal User–IP graphs, which makes the limits of single-organization detection measurable rather than assumed.

**Designed:** Operationally define all-targeted local non-detection and investigate collaborative pattern learning over separate temporal graphs.

**Implemented:** Frozen onset, observation horizon, qualifying User alert attribution, all-targeted-organizations rule and censoring; local temporal graph pipeline.

**Evidence:** Independent 171-instance VAL audit, complete local coverage and boundary tests; measured wholly undetected fraction is zero.

**Unsupported:** No nonempty wholly-undetected VAL subset and no federated solution to its detection; conceptual novelty is not established by software tests.

**Subsequent Phases:** Phase 7 collaborative implementation; Phase 11 detectability/claim evaluation; literature-based novelty argument remains a manuscript task.

**Paper Can Claim:** An operational definition and measured local boundary on this frozen benchmark.

**Paper Cannot Claim:** All low-volume campaigns evade local detectors or that the present dataset demonstrates locally invisible campaigns.

## C2

Original: We propose CredBlock-FL, a federated graph-learning framework in which each organization trains a graph neural network on its own User–IP graph and shares only differentially private model updates, so that participants obtain the cross-organizational view without exchanging login records or depending on a data-sharing arrangement that regulation or competition would block.

**Designed:** Transfer learned patterns through private updates while keeping logs, graphs, User IDs and credential mappings local.

**Implemented:** Independent local graphs, models, input contracts and continuous inference. Federation and DP are absent.

**Evidence:** Five local checkpoint/reproducibility records and local-only operational validation; explicit indicator sharing is a separate baseline.

**Unsupported:** No shared/global model, DP update exchange, cross-organization gain or legal-compliance guarantee.

**Subsequent Phases:** Phase 7 federation; Phase 8 formal DP; Phase 9 deployment; Phase 11 evaluation.

**Paper Can Claim:** A proposed federated design supported by implemented local foundations. Explain cross-organizational view as transferable learned patterns.

**Paper Cannot Claim:** An implemented private federation, reconstructed cross-organization graph, shared IP identity index, or established regulatory compliance.

## C3

Original: We characterize the detectability boundary of cross-organizational detection using a parameterized synthetic campaign, identifying the conditions of infrastructure rotation, per-organization spread and cross-organization reuse under which federation exceeds both the best single-organization detector and immediate indicator sharing, so that a prospective participant can judge whether federation would help against the campaigns it actually faces.

**Designed:** Characterize where federated advantage exists, vanishes or reverses under controlled campaign factors.

**Implemented:** Controlled synthetic campaign inventory, measured factors, accepted local/indicator baselines and family-stratified VAL reporting.

**Evidence:** 171 VAL campaigns; 0/171 wholly locally undetected; complete factor/seed denominators and incomplete targeted-User coverage.

**Unsupported:** No measured federated boundary or evidence that prospective real participants would benefit; generator and background dependence limit external validity.

**Subsequent Phases:** Phase 7 federated baseline; Phase 8 private/robust comparisons; Phase 11 final boundary characterization.

**Paper Can Claim:** A local development-set boundary and explicit experimental controls/limitations.

**Paper Cannot Claim:** A federated advantage region, direct infrastructure correlation, or deployment benefit established by these local results.

## C4

Original: We address the poisoning exposure that shared updates introduce by screening the differentially private updates for outliers before averaging, while accounting for benign non-IID variation, so that an organization whose login population differs from its peers is not excluded as though it were an attacker.

**Designed:** Robust screening of DP-protected updates with explicit honest-client exclusion accounting.

**Implemented:** Non-IID reference organization datasets; no shared updates, DP, screening or averaging.

**Evidence:** Local reference metrics only.

**Unsupported:** Poisoning resistance and protection from unfair exclusion are untested design goals.

**Subsequent Phases:** Phase 8 robust rule and DP interaction experiments; Phase 11 full comparison.

**Paper Can Claim:** The framework plans a named robust rule and an honest-exclusion audit.

**Paper Cannot Claim:** Implemented robust private aggregation or guaranteed non-exclusion of honest clients.

## C5

Original: We integrate a permissioned ledger that commits each round’s update hashes, per-organization decisions, aggregation rule and resulting model hash, committing only after endorsement by the participating organizations, so that each organization can confirm both that it runs the same model as its peers and that its own contribution was recorded as submitted.

**Designed:** Five-organization endorsed, acknowledged commitment records and verify-before-adopt with fallback.

**Implemented:** No integrated Fabric round protocol in Phase 6; local hashes/model-version checks do not implement a ledger.

**Evidence:** Local artifact integrity and model/threshold identity evidence, not consortium endorsement or signed update commitments.

**Unsupported:** No integrated endorsement, attribution, round finalization, equivocation/failure or verified global-model adoption experiment.

**Subsequent Phases:** Phase 10 signed commitments, endorsement and adoption; Phase 11 integrity/overhead validation.

**Paper Can Claim:** Proposed non-repudiation and model-byte consistency goals; acknowledge the earlier PoC separately.

**Paper Cannot Claim:** Implemented integrated ledger guarantees or mathematical aggregation correctness, DP correctness or model safety from hashes.

## C6

Original: We evaluate CredBlock-FL on [dataset and scale], reporting [headline result], and quantify what the privacy, robustness and integrity mechanisms cost in detection performance and per-round overhead.

**Designed:** End-to-end RQ1–RQ4 evaluation with reproducible scope, negative findings and mechanism costs.

**Implemented:** Synthetic web-authentication substrate, five simulated partitions, controlled campaigns, TRAIN/VAL local/indicator reporting and resource measurements.

**Evidence:** Local GraphSAGE beats the tested MLP by VAL AP in all five organizations; primary threshold and operational results are saved. TEST is deferred.

**Unsupported:** No final headline for full CredBlock-FL, held-out generalization, privacy/robustness/ledger costs or cyber-physical deployment evidence.

**Subsequent Phases:** Phases 7–10 implement components; Phase 11 final end-to-end evaluation; deferred Phase 6 TEST remains separately authorized work.

**Paper Can Claim:** Precisely scoped local development-set results on simulated partitions, with observed resource costs and limitations.

**Paper Cannot Claim:** Completed full-system evaluation, filled headline placeholders, production real-time SLA, formal privacy, robustness or cyber-physical effectiveness.

