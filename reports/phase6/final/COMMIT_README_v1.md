# Accepted Subphase 8/9 curated commit

The repository HEAD was still the Subphase 7 acceptance commit when these instructions were prepared. Therefore COMMIT_PATHS_v2.txt includes the pending Subphase 8 code/configuration, accepted aggregate audit evidence and its Subphase 9 planning/acceptance dependencies, as well as the accepted Subphase 9 reporting package.

Included: the six new reporting/detectability source modules, three tests, two configurations, preparation helper, public aggregate reports and hash inventories, historical progress v11–v20, explicit user approval event, acceptance records, all final figures and preserved drafts, research workbooks and verification records. The exact file list is in COMMIT_PATHS_v2.txt.

Excluded from this commit: raw authentication records, local graphs, SQLite journals and sidecars, per-organization private attribution/User records, model/prediction archives, large inspection traces and unrelated untracked files. These remain intact in the local research archive. Hash references remain available; this Git commit is not claimed to contain every raw experimental artifact.

The protocol already exists in verified commit 5de030316176a27889054d0e782cb1ad92171cb5. Its original SHA256 and content are preserved. core.autocrlf=false is specified for this staging command so newly committed byte-hashed reporting artifacts are not normalized by Git during add. No repository configuration is changed.

Git dry-run was attempted but could not create .git/index.lock under this session's read-only Git metadata permissions. No staging or commit occurred. Path existence, exclusion boundaries, file sizes and selected artifacts were checked read-only instead. Run the commands in your own project terminal.

```powershell
Set-Location "C:\Users\Gulso\Documents\Gul\CredBlock-FL"
git -c core.autocrlf=false add --pathspec-from-file=reports/phase6/final/COMMIT_PATHS_v2.txt
git commit -m "Accept Phase 6 Subphases 8 and 9 Option A; defer TEST evaluation"
```

Subphase 9 acceptance covers only Stages A–B TRAIN/VAL reporting. Full Phase 6 remains PENDING_HELD_OUT_TEST_EVALUATION. TEST and Phase 7 remain unauthorized. After the user says done, stop and wait for instructions.
