# Phase 6 — short resource reassessment

**READY for separately approved, monitored one-campaign pilot. Execution remains NOT AUTHORIZED.**

Five read-only samples on 19 November 2026, 00:07:27–00:07:37 Asia/Karachi, measured 6.44–6.45 GiB available RAM out of 15.70 GiB usable physical memory. Previous samples measured 0.80–0.84 GiB available. Commit usage declined from 69% to 37%; page-read samples declined from 119/7/852 per second to 0/7/3/0/3. No page writes were sampled. Pagefile current usage declined from 3,577 MiB to 1,406 MiB. Free disk is approximately 198.7 GiB.

The real v2 worker previously used approximately 0.62 GiB working set and 1.10 GiB private allocation. Current available memory is roughly 5.9 times that observed private allocation. This provides credible headroom for one monitored pilot, with caveats: those v2 observations are not peaks, private allocation is not identical to resident RAM, v4's indexed/recovery allocations are not production-peak measured, and a ten-second sample cannot guarantee future pressure. No minimum-RAM rule, peak upper bound or scientific parameter change is introduced. Record actual peak memory/paging during the separately authorized pilot and stop for failures; do not infer full-run capacity or runtime from this reassessment.

This reassessment reused the completed integrity/readiness review. It did not repeat recovery audits, graph reconstruction, checksums, scientific reviews or inference. No application was terminated and no Windows settings or scientific batch/graph/sampler/model parameters were changed.

Proposed scope: only CFV1_RA_CS_005_SEED1003_TEST, maximum one newly completed campaign. Reuse the five completed campaigns by provenance and all committed local/grid scores. No campaign 7, remaining full-run continuation or Phase 7.

After separate explicit user approval, create a NEW certificate/release-bound PILOT_ONLY approved grant at the proposed path below. Preserve the existing non-executable draft unchanged. The approved grant has NOT been created. The proposed production action, not executed, is:

```powershell
.venv\Scripts\python.exe -B -u -m src.phase6.continuation_driver_v4 --output reports/phase6/heldout_test_v2/wal_v4_transition/pilot_campaign6_v1 --certificate reports/phase6/heldout_test_v2/wal_v4_captures/pilot_preparation_v1/CFV1_RA_CS_005_SEED1003_TEST/predecessor_certificate.json --approval reports/phase6/heldout_test_v2/wal_v4_authorizations/pilot_campaign6_execution_APPROVED_v1.json
```

The command cannot pass the production guard until a valid separately approved grant exists. Launch at most one evaluator, record actual runtime/resources/reuse counts, independently reconcile the campaign and stop at bounded completion. Current readiness is a resource observation, not a new execution authorization. Stop now for user review.
