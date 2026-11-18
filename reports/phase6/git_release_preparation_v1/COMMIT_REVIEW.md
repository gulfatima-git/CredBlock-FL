# Proposed curated v4 recovery commit — awaiting review

No files have been staged. No commit or tag has been created.

Commit subject: `Preserve reviewed WAL-aware v4 continuation and verified v2 recovery`

Proposed annotated tag: `phase6-v4-4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370`

Reviewed executor release identity (not a Git commit hash): `4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370`.

The exact candidate list is proposed_paths_v1.txt. There are 135 candidates. Include only these literal paths; never use `git add .`, `git add -A`, or add a report directory wholesale.

Scope: reviewed v4 source/configuration, synthetic tests and fixture helpers, required untracked v1/v2/v3 dependencies, existing v4 synthetic reports (including failed-attempt evidence), recovery report/scripts/verification records, five independent completed-campaign audit summaries, progress v33/v34, forensic seal and compressed hash inventory, and this preparation record. The code dependencies are included unchanged because HEAD does not yet contain them.

Exclusions: all 51,690 files under reports/phase6/v2_forensic_v1/physical; all actual TEST observations, labels, row-level predictions, graphs, replay journals and databases/sidecars; original TEST-run trees; model archives; virtual environments; caches; disposable fixture trees; execution grants; empty sender logs; disposable lease-test byte file. No evaluator or synthetic experiment was rerun for this preparation.

The 14,220,903-byte original physical_snapshot_manifest.json remains unchanged locally. physical_snapshot_manifest.json.gz is a lossless, deterministic gzip containing only that inventory's metadata, not its referenced research files. Decompression hashes to `3968a3a90188e33da2fba7ceb41c9fe3f7e2de7f5f9b84607ceb06f79dffce64`, matching the existing SNAPSHOT_SEAL.json. Excluded artifacts referenced by original delivery manifests deliberately remain local; the curated Git commit is not a standalone copy of the private evidence archive.

New .gitattributes entries disable line-ending conversion only for new allowlisted files, preserving reviewed bytes under core.autocrlf=true. No accepted tracked source or frozen protocol is added, changed or renormalized. Frozen protocol SHA256 remains `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

Current recovery milestone: 5/171 completed and independently verified, one recoverable partial campaign, 165 not started; no v4 pilot/execution authorization. Tag wording must describe reviewed code and recovery evidence, not completed TEST evaluation or user acceptance of v4 production execution.

After user review: verify HEAD and candidate hashes, stage exactly the pathspec, inspect the staged names/stat/diff and forbidden-path checks, then create the commit and annotated tag. Verify the committed blobs reproduce the reviewed executor identity and the tag targets the new commit. No push is proposed.
