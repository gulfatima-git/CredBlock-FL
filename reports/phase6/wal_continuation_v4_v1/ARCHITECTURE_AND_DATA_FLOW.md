# WAL-aware successor to v3: architecture and data flow

The additive release is named v4 to distinguish it from the preserved v3 implementation and certificate. It changes recovery/provenance, not CredBlock-FL's detector architecture.

Original v2 bytes after separately verified process exit + original read-only lease
→ explicit physical database/WAL/SHM/journal inventory
→ checksum/commit-boundary analysis
→ separate committed-page projection in wal_v4_captures
→ SQLite committed-view oracle on a separate disposable copy
→ graph/checkpoint/command/prediction and LOCAL/grid reconciliation
→ phase6-continuation-wal-certificate-v4
→ physical archive plus certified derived images in wal_v4_transition
→ accepted local services and indexed five-organization barrier
→ sealed raw scores, then offline labels/attribution
→ exact completion proofs and original 171-instance mixed-origin manifest.

No SQLite connection is opened on the physical predecessor by the WAL projector. Original evidence is not manually checkpointed, deleted, repaired or normalized. SHM remains preserved auxiliary evidence; WAL commit boundaries determine the logical committed view. A derived image has its own SHA256 and is never substituted under a v3 certificate. New working images may evolve under the new run lease; certified original row/checkpoint prefixes remain protected. Repeated working-WAL recovery uses another separately proven image for inspection, then the unchanged local service's normal working-store restart.

The five organization graphs, User prediction targets, IP context nodes, graph retention, features, sampler, GraphSAGE/MLP checkpoints and binary64 thresholds remain the accepted definitions. ProductionBackend.prepare/labels/truth/inventory are AST-identical to v3. Original model bundles remain verified before the first future observation. Fixed-grid model comparisons and event-driven indicator decisions remain separate. The sharing baseline transmits only the accepted IP payloads; recovered databases and forensic archives are private evidence, not sharing payloads.

Production namespaces, none populated by a live capture/execution in this work:

- Capture artifacts/certificate: reports/phase6/heldout_test_v2/wal_v4_captures/<capture-id>/.
- Working execution: reports/phase6/heldout_test_v2/wal_v4_transition/<run-id>/.
- Future explicit approvals/host attestations: reports/phase6/heldout_test_v2/wal_v4_authorizations/*.json.

Capture requires a new release-bound authority, a pinned host-exit attestation and the original predecessor lease. Execution requires a separate release/source/config/certificate/inventory-bound PILOT_ONLY or ALL_171 grant. Original v2/v3 approvals cannot authorize this successor. Approval paths are denied outside the explicit metadata namespace before lookup/read; production certificates are confined to the capture namespace. This work creates none of those approval artifacts.

The production entry point is src.phase6.continuation_driver_v4; this review never invokes its production backend or CLI. Synthetic tests use generated models/labels and a synthetic backend through the same driver, graph, sampling, persistence, grid, sharing and reporting control flow.

Shared-Parquet isolation remains logical row selection rather than physical byte isolation. The historical access incident remains disclosed. The 1% VAL calibration target is not an event-driven or TEST FPR guarantee. The verified VAL finding of 0/171 wholly undetected campaigns remains unchanged; this recovery work supplies no new detection/federation claim.
