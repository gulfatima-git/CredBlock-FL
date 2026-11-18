# WAL-aware v3 successor, release v4 — implementation plan

Authorization: user attachment db5a7f48-fd59-45ea-b794-ef566c6c128e. Implementation and synthetic validation only; no live interruption, capture grant or execution grant.

1. Preserve the explicit 20-file predecessor source/configuration vector and every historical report. Create seven additive v4 continuation modules plus a WAL module/configuration, never edit v2/v3.
2. Version the physical-to-logical certificate and capability checks. Physical main/WAL/SHM hashes remain distinct from the derived self-contained image and logical table/prediction/checkpoint digests. Certificate creation requires a quiescent source lease and future explicit production capture authority.
3. Validate WAL checksums and commit boundaries, derive into a separate capture namespace, compare against SQLite on a disposable oracle copy, and seal derivation provenance. Preserve uncertain tails and fail closed pending review. No source SQLite connection, manual checkpoint, deletion or repair.
4. Verify source journal/database correspondence, original identities, graph command/checkpoint consistency and fixed-grid commits. Preserve bytes in original and physical archive; install only certified derived images in a new working namespace. Existing v3 WAL checks remain untouched.
5. Integrate indexed barrier and driver recovery, preserving committed scores and grid rows. Validate Org1–Org5 at local commit/publication, grid commit, issuance/receipt/publication, paired/expiry and score/completion boundaries using synthetic subprocess self-exits and fresh generated models.
6. Independently reconcile saved rows, journals, indicators, attribution/censoring and evaluation metrics. Test corruption, access denial, copy/publication interruption, wrong certificates/configuration, sidecar loss and working-copy recovery. No actual TEST payloads/weights are inputs.
7. Compare end-to-end synthetic execution with original v2 and existing v3, reporting workload size, model-call counts, wall/CPU/memory and scope limitations. Never infer a full-run ETA from microbenchmarks.
8. Pin final source/configuration and test evidence, run an independent allowlisted source/evidence audit, report every failed attempt and unverified production gate. Stop without any live action.

Production readiness is a separate decision. Shared-Parquet logical-versus-physical isolation and all frozen scientific limitations, including 0/171 wholly undetected VAL campaigns, remain unchanged. No federation, DP, robust aggregation, blockchain or Phase 7.
