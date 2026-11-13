# CredBlock-FL full replay and temporal labels v1

## Verified full execution

The actual run against the extracted inventory and original organization sources
passed all 22 tests and finished with
`PASS_FULL_CONTROLLED_REPLAY_AND_TEMPORAL_LABELS`.

| Check | Verified result |
|---|---:|
| Instances | 513 (171 per split) |
| Organization branches | 2,565 |
| Targeted branches | 1,647 |
| Background-only branches | 918, all with zero positive User labels |
| Replay event copies | 1,230,837 |
| Synthetic event copies | 155,988 |
| Background event copies | 1,074,849 |
| Target User/branch occurrences with pre-anchor observations | 108,000/108,000 |
| Materialized states checked against the direct oracle | 3,454,398 |
| Positive states | 295,194 |
| Clean-negative candidate states | 2,055,528 |
| Ambiguous masked states | 161,367 |
| Context-only masked states | 942,309 |
| Grid snapshots | 15,390 |
| Bounded historical source references | 45 |
| Input-file hashes unchanged | 2,172/2,172 |

The three aggregate CSV/JSON reports were also cross-checked for totals, label
partitions, background-only positives, unique grid keys and graph/context cohort
partitions. No disagreement was found. These are data preparation results, not
model performance results. Counts refer to copies/states in isolated branches.

This is the third of the four Phase 5 closeout steps in the handover. It replays
the complete corrected inventory and applies the unchanged accepted v1 temporal
User-node labeling policy. It does not implement GraphSAGE, fit preprocessing,
train a model, tune thresholds or choose a horizon using TEST results.

## Full organization scope

The 513 generated instances contain synthetic attacks in 1,647 targeted
organization branches. The implementation plan also requires non-targeted
organizations. Therefore this replay covers 513 x 5 = 2,565 branches:

- 1,647 targeted branches: background plus that organization's synthetic events.
- 918 background-only branches: original background and no injected events.
- All background-only branches must have zero synthetic-positive User labels.
- Each branch has six ten-minute as-of grid snapshots: 15,390 snapshots in total.

Earlier six-variant pilot files are preserved, not regenerated. A partial local
targeted-only trial was stopped before acceptance when checking this requirement.
It is marked ABORTED and is not part of this delivery or the accepted inventory.

## Inputs and output location

`replay_and_label_phase5_inventory_v1.py` needs the existing accepted
`build_phase5_temporal_user_labels_v1.py`. Its exact SHA-256 is pinned, so a changed
policy cannot be silently substituted. The script runs that module's 15 tests plus
seven replay tests (22 tests total).

An exact copy is also included under `replay_label_dependencies/` in the delivery
for reproducibility; extraction does not overwrite your existing root label
builder. If the root builder is missing, pass
`--label-builder '.\replay_label_dependencies\build_phase5_temporal_user_labels_v1.py'`.

Inventory autodetection accepts exactly one of:

```text
data/phase5/controlled_inventory_causal_v1/
data2/phase5/controlled_inventory_causal_v1/
```

Your current extraction is under `data2`, which is supported directly. There is
no need to move or regenerate it. If both locations exist, choose one explicitly
with `--inventory` rather than silently selecting a duplicate.

The default NEW output directory is:

```text
data/phase5/controlled_replay_labels_all_orgs_causal_v1/
```

Existing output directories are refused; the script has no overwrite/resume mode.

## Replay and temporal behavior

- Each organization contributes only its own source authentication events.
- Each instance gets an isolated one-hour replay: half-open `[anchor,end)`.
- All alternatives in a split/seed use identical normalized background events
  for the same organization. Logical digests verify recovery of that background.
- Background provenance and synthetic attack truth remain separate. Explicitly
  false source flags produce negative candidates; flagged or unknown flags are
  ambiguous, not established clean negatives.
- Replay records are sorted by timestamp, provenance, User, IP and stable event ID.
  Simultaneous events are available as one complete timestamp batch for labels.
- Stored replay Parquet contents are read back and compared with the normalized
  in-memory replay, not only counted.
- User labels use the unchanged `(t-10 minutes,t]` policy. Positives take priority
  over ambiguity. Users without recent evidence are unsupervised context.
- Every materialized label state is checked against the direct-record oracle.
  Stored label partitions are checked after writing.
- A prefix check removes future events at mid-hour and confirms earlier User
  states agree. This checks supervision timing, not a nonexistent feature pipeline.
- Fixed `[a,b)` event-count buckets are reported separately from as-of labels.
- Organization scopes and branch isolation are retained. There is no shared graph
  or runtime matching of synthetic credentials across organizations.

## Seven-day history without redundant copies

Large raw histories are not copied into every instance. Each of the nine
split/seed blocks has five checksum-pinned bounded source-view references in
`history_references/<split_seed>/<Org>.json` (45 references total).

These references record the original organization Parquet paths relative to the
project root, byte hashes, history bounds, counts and normalized logical digests.
Keep the existing `data/organizations` files: the history references depend on them.
They are not standalone copies of the source authentication dataset.

The complete seven-day history is actually read and validated once per block/org.
Only its final ten minutes are needed to seed label supervision. Repeated label
construction therefore uses that shorter seed, while graph-context User counts
use the complete last-observation index with exact rolling seven-day expiration.
Tests compare this implementation with the original full-history label builder.
Old-only users are context rather than millions of extra negative examples.

History may include earlier-split observations as past context. Only current
replay-window labels are exported; this is not permission to train on TEST labels.
No historical graph tensors are created, and these User-count checks do not
certify persistent graph edges or GraphSAGE feature computation.

## Output files

Each instance folder contains, for all five organizations:

| File | Role |
|---|---|
| `<Org>_replay.parquet` | Normalized merged events; evaluator truth/flags retained separately |
| `<Org>_labels.parquet` | Sparse User/time states, masks, reasons and positive evidence |
| `<Org>_observations.parquet` | Strict projection: organization, timestamp, User, IP, outcome only |
| `replay_manifest.json` | Bounds, source-manifest hash, organization scope, branch counts and hashes |

Top-level `summary.json`, `summary.txt`, `branches.csv`, `variants.csv`,
`grid_snapshots.csv`, `fixed_bucket_event_counts.csv`, `policy.json`,
`user_positive_evidence.parquet`, and `output_sha256.json` provide reproducibility
and aggregate validation. The detailed evidence file includes local User IDs and
is evaluator-only; aggregate reports do not expose them.

Observation exports have an enforced column allowlist. They are not GraphSAGE
features; raw identifiers are graph keys, not permission to use numeric IDs as
input features. Do not join evaluator labels, source flags or campaign metadata
into the runtime model input table.

## How to use the package

The package's `controlled_replay_labels_all_orgs_causal_v1` folder contains the
verified outputs. Copy that one NEW folder into your EXISTING `data/phase5`
folder. Do not replace or rename your entire `data` folder. Copy the new replay
script to the project root if you want to reproduce the run. No generator rerun
is required.

For the compressed `.tar.xz` delivery, save it in the project root and extract it
with PowerShell. The archive places the new results folder inside the existing
`data/phase5`; it does not replace the whole `data` folder:

```powershell
Set-Location 'C:\Users\Gulso\Documents\Gul\CredBlock-FL'
tar -xf .\CredBlock_FL_Full_Replay_Labels_v1.tar.xz
```

Do not extract over an existing `controlled_replay_labels_all_orgs_causal_v1`
output directory. Keep `data2/phase5/controlled_inventory_causal_v1` as the pinned
synthetic input, and keep `data/organizations` for the historical source views.

With your existing virtual environment activated, reproduction commands are:

```powershell
Set-Location 'C:\Users\Gulso\Documents\Gul\CredBlock-FL'
python .\replay_and_label_phase5_inventory_v1.py --self-test
python .\replay_and_label_phase5_inventory_v1.py --inventory '.\data2\phase5\controlled_inventory_causal_v1'
```

For a repeat execution, choose a new output:

```powershell
python .\replay_and_label_phase5_inventory_v1.py --inventory '.\data2\phase5\controlled_inventory_causal_v1' --output '.\data\phase5\controlled_replay_labels_all_orgs_causal_v1_run2'
```

If you execute it independently, share `summary.json`, `branches.csv` and
`grid_snapshots.csv` for aggregate review. Raw organization data and User evidence
need not be uploaded.

## Claim boundaries and progress

Successful status: `PASS_FULL_CONTROLLED_REPLAY_AND_TEMPORAL_LABELS`.

Counts of repeated background copies and sparse label states are not independent
samples. Original background is not confirmed benign ground truth. A ten-minute
label expiry is a design choice, not a claim that risk disappears. Replay coverage
ends at the exclusive end; nominal later expiry is marked coverage-censored.

The shared temporal blocks, Raccount coverage/per-user intensity effects, and
Sorg composition/total-volume effects remain methodological limitations. Optional
fixed-total Sorg sensitivity data is not created by this runner.

On successful execution, Phase 5 closeout is 3 of 4 handover steps complete. The
remaining step is the consolidated acceptance report and dataset freeze. Actual
graph-feature timing, model feature allowlists, train-only fitted preprocessing,
training/evaluation isolation and model effectiveness are not certified here.
