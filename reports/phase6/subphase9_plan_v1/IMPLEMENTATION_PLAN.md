# Phase 6 Subphase 9 (6.7): Metrics, comparisons and Phase 6 acceptance

**PLAN FOR REVIEW. Implementation NOT_STARTED. TEST outcome access is NOT_AUTHORIZED.**

Prepared 16 November 2026 (Asia/Karachi). Preparing this document is not implementation approval. Subphase 8 is USER_ACCEPTED in the new append-only `reports/phase6/detectability/acceptance_v1.json`; earlier technical-review reports retain their historical statuses.

## 1. Purpose and governing requirements

Consolidate the accepted local detection work into a reproducible, paper-ready Phase 6 evaluation package. Follow section 12 of the approved Phase 6 roadmap (6.7), the professor's implementation plan, final framework and two diagrams. Preserve all eleven phases and the original architecture.

The roadmap requires eventual held-out local-baseline evaluation before full Phase 6 completion. Current authorization permits this plan only. The implementation approval must explicitly authorize or defer the TEST execution described in Stage C. If TEST remains deferred, finish the authorized TRAIN/VAL reporting work and label final Phase 6 acceptance incomplete. Do not silently substitute VAL for TEST or declare Phase 6 complete.

This plan does not implement federation, differential privacy, robust aggregation, Docker or Hyperledger Fabric. Federated GraphSAGE remains a future comparison system, with unavailable results marked NOT_IMPLEMENTED rather than zero.

## 2. Findings and scientific constraints that must carry forward

| Accepted VAL endpoint | Local-only | Local plus indicators |
|---|---:|---:|
| Campaign detected at any targeted organization | 171/171 | 171/171 |
| Campaign detected at every targeted organization | 170/171 | 170/171 |
| Campaign undetected at all targeted organizations | 0/171 (0%) | 0/171 (0%) |
| Targeted organization trials detected | 548/549 | 548/549 |
| Detected local target-User occurrences | 13,733/36,000 | 15,111/36,000 |
| Earlier first campaign detection from sharing | Reference | 0 campaigns |

Indicator sharing added 1,378 detected target-User occurrences, improving User coverage in 146 campaigns. It did not rescue an additional wholly missed campaign. The undetected organization trial is Org5 in CFV1_RA_CS_030_SEED1002_VAL under both policies; its missing time-to-detection remains null and right-censored.

The verified VAL subset of campaigns missed by every local organization is empty. Consequently, it cannot support a claim that federation rescued campaigns in that subset. Do not alter campaign intensity, data, labels, models, thresholds, split assignments or attribution rules to populate it. Do not use future federated outcomes to redefine the local non-detection category.

Retain the complete limitations in `SCIENTIFIC_CARRY_FORWARD.json`. In particular:

- VAL selected models and calibrated thresholds; it is development evidence, not final generalization evidence.
- The 1% empirical FPR is defined over eligible negative fixed-grid User-time examples. Event-driven alerts and campaign detection have separate denominators.
- Shared background, repeated branch-local Users and three temporal seed blocks create dependence. Do not compute naive IID row/branch confidence intervals or globally deduplicate local IDs.
- Temporal attribution is association, not causal proof. Unattributed alerts are not automatically verified false positives.
- Keep the two controlled design families and single-organization descriptive references separate. Raccount can change target coverage/per-User intensity; fixed-per-org Sorg changes total volume and org composition. Raccount is N/A for single-organization references.
- RIP measures distinct attacker IPs divided by attack attempts, not chronological switching frequency.
- Zero-delay suspicious-IP sharing remains a separate comparator, not the professor's federated architecture or a realistic network measurement.
- Preserve final-ten-minute operational coverage and the frozen primary grid's missing end-of-hour endpoint. Do not add that endpoint post hoc.

## 3. Frozen inputs and reuse

Reuse, without modifying or regenerating:

1. Phase 5 frozen dataset/register, manifests, causal temporal labels and persistent seven-day graph runtime.
2. The primary split protocol, ten-minute User-time grid and eligibility masks.
3. Feature allowlist, transforms, deterministic neighbor sampler and inductive node handling.
4. All five selected GraphSAGE checkpoints and five MLP checkpoints, including full TRAIN/VAL predictions and histories.
5. VAL-selected best-local GraphSAGE choice for Org1–Org5, unchanged after seeing threshold or operational results.
6. All ten frozen binary64 logit thresholds and their provenance.
7. Accepted continuous inference, immediate sharing, frozen attribution method and the complete independently validated Subphase 8 evidence.
8. Original source journals and sidecars. Access SQLite with immutable read-only connections after verifying the authoritative hash and checking that the associated WAL is absent or empty. Nonempty WALs, unknown auxiliary files or changed hashes block access pending review.

Primary protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

Detectability protocol SHA256: `f63e0bb73253eea4a8c8d7abc4231f94069aaf15c3eef68eeb3fa1b00d49bc55`.

Do not call training/calibration or the VAL batch runner during reporting. Reuse original measured resources; do not repeat accepted inference to create fresh timing numbers.

## 4. Stage A — Evidence inventory and reporting contract

After implementation approval:

1. Inspect existing reporting and metric functions before adding code; reconcile names, formulas and current source signatures.
2. Write a new input inventory pinning source artifacts, acceptance records, protocols, selected models, thresholds and original result files.
3. Define the reporting schema before calculating new comparisons: split, organization, variant/design family, seed, detector/policy, metric unit, eligible population, numerator, denominator, undefined-value rule and source hash.
4. Establish the comparison matrix: GraphSAGE and MLP on the primary fixed grid; best-local GraphSAGE versus GraphSAGE plus indicators on the paired operational stream. Do not compare event-triggered rows with fixed-grid rows as if they were the same cohort.
5. Verify existing metric semantics: tied-score grouped average precision is AP, not automatically trapezoidal PR-AUC. Report the exact implementation and distinguish any additional descriptive area calculation.
6. Declare any additional descriptive analysis before calculating it. Changes to the experimental protocol require an explicit versioned amendment, not an unnoticed reporting option.

Deliverable: new reporting configuration, evidence inventory and read-only verification log. This adds no new model or threshold selection.

## 5. Stage B — TRAIN/VAL consolidation from saved outputs

### Primary fixed-grid results

- Use identical eligible keys for paired GraphSAGE/MLP comparisons. Preserve ambiguous/context-only exclusions.
- Publish TP, FP, TN, FN, positive/negative counts, precision, recall, F1, empirical FPR, AP and unweighted BCE where supported by saved evidence.
- Use the original frozen thresholds via the exact binary64 helper. Do not recalibrate to make achieved rates equal 1%.
- Report all five organizations; primary macro summaries equally weight organizations and secondary pooled summaries sum eligible confusion counts. Undefined metrics remain explicit and are not silently dropped.
- Publish prevalence, supervision masks and unseen-User/unseen-IP-context subgroups with exact definitions and denominators. IP context does not become an IP classification task.
- Reuse selected/candidate training histories to plot training/validation curves. No rerun of selected fits.

### Operational and campaign results

- Import the accepted 171-instance campaign, organization, User coverage, attribution, indicator and timing evidence.
- Show campaign detection anywhere, all-targeted detection, partial detection, all-targeted non-detection, organization trials and local target-User coverage separately.
- Publish paired additional-User coverage and earlier-detection differences. Include missed/censored observations; never replace them with a finite detection time or zero delay.
- Preserve all 342 detector/design/factor/seed coverage cells and the factor-family caveats. Report campaign intensity, background volume and composition from existing manifests as context, not model inputs.
- Display undetected fraction as 0/171 with an explicit empty-subset statement. Do not fit a non-detection boundary curve when there are no such observations.

### Resources and uncertainty

- Reuse measured training time, memory, inference latency, component CPU time and indicator costs. State scope, concurrency, reuse and excluded startup/I/O clearly.
- Do not call sums of overlapping organization runtimes full-sweep elapsed time. Do not label a median of per-replay p95 values as a pooled p95.
- Use descriptive per-seed/per-block variability. With only three temporal blocks, omit unsupported confidence intervals rather than treating dependent rows as independent trials. No new significance claim is required for completion.

Deliverables: source-linked TRAIN/VAL comparison tables, resource tables, limitations register and manuscript figures. Stage B cannot independently satisfy the roadmap's final TEST gate.

## 6. Stage C — Held-out evaluation, conditional on explicit TEST authorization

No TEST outcomes are accessed while preparing or reviewing this plan. Future execution is a distinct authorization scope: the approval must explicitly include it before any TEST observations, labels or predictions are opened or generated.

Before a permitted TEST run:

1. Verify that the frozen primary protocol is present in version control with the expected SHA256; preserve the verified commit reference and test execution configuration before opening outcomes.
2. Freeze the test execution inventory from structural metadata and record model, threshold, policy and evaluator identities. Expected scope is the accepted 171 TEST campaign instances and all five organizations, subject to inventory confirmation without outcome inspection.
3. Separate scored evidence production from offline label joins. Lock model selection, thresholds, metric definitions and attribution first.
4. Estimate resources from existing measured component records, disclose uncertainty and prepare append-only resumable per-instance outputs. Do not extrapolate the old 77-hour estimate as an actual measurement or guarantee.

The authorized evaluation would then:

- Score the frozen TEST fixed-grid examples with both original detector families and their original per-org thresholds; make no optimizer/calibration calls.
- Evaluate best-local GraphSAGE and the frozen immediate-indicator baseline on the same causal TEST event streams, with isolated per-variant state and full-hour/final-ten-minute coverage.
- Apply the unchanged offline detectability definition after sealing predictions. Never use ground truth to select runtime scoring targets or indicators.
- Independently verify score/threshold identities, metric populations, timing, indicator causality, campaign attribution, censoring and aggregate reconciliation.
- Report observed TEST FPR at the frozen threshold even when it exceeds 1%; do not tune TEST thresholds to impose the target. Describe results as operating at a VAL-calibrated 1% target with observed held-out FPR, not automatically at exact 1% TEST FPR.
- Report the observed TEST undetected subset independently, whether empty or nonempty, without selecting it using future federated results.

Existing entry points such as training cache readers and the detectability runner intentionally restrict allowed split/purpose. Do not bypass them or change their accepted sources. Plan a separate explicitly authorized evaluation-only adapter, with pre-I/O guards and no training interface. If reuse requires changing the frozen VAL-only method document merely to permit TEST, stop for an explicit versioned scope amendment that preserves the accepted scientific rule and historical outputs. Do not silently edit the VAL protocol or mutate its split field.

New TEST inference would be previously unperformed held-out work, not a repeat of the accepted 171 VAL runs. No launch is authorized by this document alone. If this stage is deferred, mark it pending in the final checklist and do not claim full Phase 6 completion.

## 7. Required tables and figures

| Output | Evidence and interpretation |
|---|---|
| Per-org class/mask prevalence | Exact fixed-grid eligible and excluded denominators |
| GraphSAGE learning curves | Original candidate histories and selected epoch markers |
| GraphSAGE versus MLP | Paired eligible examples; AP/BCE plus frozen-threshold confusion metrics |
| Calibration table | All ten accepted thresholds, negative counts, FP budgets and achieved VAL FPR |
| PR/ROC summaries | Exact tie policy; no mixing of nominal and calibrated operating points |
| Local versus indicator comparison | Paired operational User coverage and campaign/org endpoints |
| RIP/Raccount/Sorg results | Separate design families, joint coverage cells and seed breakdowns |
| Non-detection fractions | Explicit numerators/denominators and empty VAL subset |
| Time-to-detection | Campaign/org time origins, censored counts and observed horizons |
| Latency/resource tables | Original scope/concurrency and correct quantile interpretation |
| Inductive subgroup table | TRAIN-unseen Users and TRAIN-unseen IP context separately |

Preserve organization-specific failures rather than presenting only a favorable pooled average. Figures should be standalone publication-quality PNG/PDF or SVG as appropriate. New versioned Excel workbooks must preserve previous workbooks, cite sources, retain N/A and null semantics, and be checked against saved data and formulas.

## 8. Proposed additive implementation files, after approval only

Inspect the repository again before committing exact names. Candidate additions:

- `configs/phase6/final_reporting_v1.json`: reporting contract, no experimental changes.
- `src/phase6/final_reporting.py`: saved-evidence loading, metric reconciliation and tables.
- `src/phase6/run_final_reporting.py`: reporting-only entry point with explicit split scope.
- `tests/phase6/test_final_reporting.py`: metric/denominator, provenance and scope tests.
- Separately reviewed TEST-only configuration/adapter/tests if Stage C is authorized; not a change to accepted VAL runners or training readers.
- `reports/phase6/final/v1/`: inventory, exact tables, figure sources, testing results, limitations, acceptance checklist and technical report.
- `outputs/phase6_final_v1/`: new workbook and publication figures; old outputs untouched.

These are proposed paths, not files created by this planning task. No implementation is included in this plan.

## 9. Verification and failure handling

Unit checks: metric definitions and confusion counts; zero/undefined denominators; tied-score AP; binary64 boundaries; masked examples; paired cohort identity; macro versus pooled aggregation; split before I/O guards; local User key isolation; censoring; missing coverage; zero-undetected reporting; N/A factors; provenance and overwrite rejection.

Integration checks: reconcile new TRAIN/VAL tables exactly with accepted model/comparator/calibration summaries and every Subphase 8 endpoint; verify all org/configuration/seed coverage; rebuild tables/figures from saved evidence deterministically; verify no training/calibration/VAL-runner call is reachable; check prior artifact hashes before and after reporting. Validate any future authorized TEST adapter separately before full execution, using fixtures and TRAIN/VAL-only development.

Run relevant existing tests and new reporting tests with caches/temp data outside accepted outputs. Keep smoke, fixture, representative and full held-out evidence explicitly distinct. A non-TEST regression suite must exclude actual TEST-opening tests while TEST remains unauthorized.

If a source hash changes, eligibility differs, a paired cohort diverges, a nonempty WAL appears, or a new table fails reconciliation: stop that stage, preserve its attempt, state the discrepancy and propose the smallest correction. Do not overwrite accepted artifacts or automatically rerun completed evaluations.

## 10. Acceptance and execution gates

| Gate | Required state |
|---|---|
| Current plan | Awaiting user review; implementation NOT_STARTED |
| Subphase 8 | USER_ACCEPTED, immutable acceptance and scientific carry-forward record |
| Reporting implementation | Explicit plan approval before code, tests or reporting execution |
| Held-out TEST execution | Explicit scope authorization and pre-outcome freeze; not authorized now |
| Technical reporting | All exact reconciliations, checks, resources, figures, Excel and limitations complete |
| Full Phase 6 closeout | Roadmap's required held-out baseline evidence complete; otherwise pending |
| User acceptance | New append-only acceptance only after explicit user decision |
| Phase 7 | Not started automatically; no federation as part of Subphase 9 |

Final technical report must state completed/pending gates, exact metrics, all source hashes, reproducibility commands, tests, limitations and retained failures. Technical success does not guarantee a favorable research result or authorize a later phase.

## Requested review decision

Review the plan and explicitly specify whether approval covers (A) TRAIN/VAL reporting implementation only, keeping TEST deferred, or (B) the full Subphase 9 scope including the frozen held-out TEST stage. Until then, no Subphase 9 implementation or TEST outcome access will occur.
