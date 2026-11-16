# Phase 6 Subphase 8: Independent technical review

Date: 16 November 2026 (Asia/Karachi).

**Technical acceptance status: REVIEW_REQUIRED. Not ready for user acceptance.**

Subphase 8 remains TECHNICAL_REVIEW_PENDING. No USER_ACCEPTED record was created. Subphase 9 has not started.

## Execution evidence versus independent verification

The existing runner aggregate reports PASS_ALL_171_VAL_INSTANCES_TECHNICAL_REVIEW_REQUIRED, required=171, evaluated=171. It contains 342 campaign-policy rows, 1,098 targeted organization-policy rows and 342 factor/seed-policy rows. These counts are observations of the saved aggregate, not independent confirmation of its underlying results.

An independently written, read-only evidence auditor was started. It does not call the batch runner, detector forward passes, training, threshold calibration, or the accepted campaign evaluator. Its intended checks include independent attribution from saved predictions and VAL-only offline truth, causal indicator use, private User evidence, censoring, hashes and preservation.

The audit stopped at its first failed structural check, before completing any full campaign validation. Four completion manifests and 66 artifact-hash entries had been verified. The audit did not reach the full preservation inventory or independently recompute campaign, organization or User outcomes. It must not be described as validating all 171 campaigns.

## Exact issue

Component:

`reports/phase6/detectability/full_v1/instances/CFV1_RA_CS_004_SEED1001_VAL/local/Org1/attempt_00001/`

The directory contains two files absent from its complete.json artifact map:

| Relative path | Bytes | SHA256 |
|---|---:|---|
| uninterrupted/private/inference.sqlite-wal | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| uninterrupted/private/inference.sqlite-shm | 32,768 | fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb |

No manifest-listed file is missing in that component. A targeted byte-hash check confirmed all five listed files still match their original hashes: the worker log, component summary, latency records, inference database and replay summary.

The failing audit assertion required the actual file set to equal the sealed file set. This exhaustive-directory check is stricter than the frozen runner's verifier, which checks listed hashes. The discrepancy is therefore a review finding, not evidence that detector scores changed or that the frozen method failed.

SQLite WAL and shared-memory files can be transient database sidecars. Here the WAL is empty, which is consistent with no pending WAL frames, but that alone is not sufficient to certify every database or every campaign. Their origin and equivalent conditions across the inventory were not established. The auditor stopped before opening this SQLite database, so its database reader did not create these two files during this attempt.

## Reported results: not independently accepted

| Policy | Runner-reported campaigns | Runner-reported undetected by all targeted organizations | Reported percentage |
|---|---:|---:|---:|
| Local-only | 171 | 0 | 0% |
| Local plus immediate indicators | 171 | 0 | 0% |

These are provisional figures read from the runner aggregate. They have not been independently recomputed. Complete paired organization/User statistics and factor-specific conclusions are withheld pending the independent audit.

If subsequently verified, zero wholly undetected campaigns would mean this VAL inventory supplies no campaign missed by every targeted organization under the frozen rule. It would not establish perfect User coverage, detection at every organization, low operational false positives, or the absence of benefits from federation. It would also limit claims that this inventory demonstrates recovery of campaigns missed everywhere locally. No dataset, threshold or attribution change should be made post hoc to manufacture such a subset.

## Smallest scientifically valid next action

Preserve the original manifests, database files, sidecars and failed review record. Do not checkpoint, delete, repair, reseal, regenerate or rerun campaign inference.

For a reviewed continuation of this evidence audit, use an append-only audit supplement to classify SQLite sidecars separately from authoritative sealed research outputs. Verify the authoritative database hashes, establish that each relevant WAL is empty, and read sealed databases with a genuinely non-writing connection (for example immutable read-only mode, only after verifying no pending WAL content). Nonempty WALs or any changed authoritative hash must remain blocking findings rather than being ignored.

This would correct the audit's file-classification assumption, not change the experimental protocol or results. It requires no GNN inference. The failed review attempt should remain unchanged, and a continuation should use a new output directory. No continuation or evaluation rerun has been launched automatically.

## Scientific limitations to retain in the eventual final report

- VAL was used in prior model selection and calibration; these are not final held-out TEST estimates.
- The 1% empirical FPR target concerns eligible fixed-grid VAL User-time negatives, not arbitrary event-triggered decisions or campaign-level false-positive rates.
- Campaign variants share background and have only three temporal seed blocks; row counts do not supply independent experimental replication or IID confidence intervals.
- Targeted organization trials, local User occurrences, scoring decisions and campaign instances are distinct denominators. Repeated Users cannot be counted as globally unique people.
- Alert attribution is temporal association with recent targeting evidence, not proof that injected attempts caused the model's alert.
- Shared IP indicators are suspicious and unverified; zero simulated distribution delay is not realistic network latency.
- Complete non-detection is right-censored at the frozen horizon; no finite time-to-detection may be invented.
- Ambiguous overlap handling needs its synthetic boundary tests as well as real-data audit. A single-campaign-per-branch inventory cannot by itself demonstrate real overlapping-campaign behavior.
- Factor comparisons must retain the controlled-design families: Raccount comparisons can alter per-User intensity and target coverage, while Sorg fixed-per-organization budgets alter total volume and organization composition. Single-organization Raccount is not applicable.

## Preservation and artifacts

New review outputs only:

- `review_status_started.json`: initial TECHNICAL_REVIEW_PENDING record.
- `validation_failure.json`: exact failed assertion, traceback and partial check counts.
- `TECHNICAL_ACCEPTANCE_REPORT.md`: this review report.
- `review_status_result.json`: REVIEW_REQUIRED decision and continuation recommendation.
- `reports/phase6/progress_v13.json`: append-only pending-review progress record.

The independent auditor is stored outside accepted project sources at `C:/Users/Gulso/OneDrive/Documents/ChatGPT/research/subphase8_independent_review.py`.

No existing accepted file was intentionally written or modified. Full byte-preservation verification remains outstanding; it is not claimed on the basis of this partial audit. No TEST outcomes were queried. No training, calibration, full batch execution, costly inference or Subphase 9 work was performed.

## Acceptance recommendation

Do not accept Subphase 8 yet. Resolve the sidecar evidence-classification finding through a reviewed, non-writing audit continuation, then complete the 171-instance independent checks. The successful runner status alone is insufficient for technical acceptance.
