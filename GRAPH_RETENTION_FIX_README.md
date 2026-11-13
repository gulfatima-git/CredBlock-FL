# CredBlock-FL rolling graph retention fix v1

## Verified result

The actual execution passed:

- 20/20 unit tests.
- 45/45 fixed representative attack branches across every split/seed/org.
- 45/45 pure-background feature controls.
- 315/315 as-of feature, structural-edge and User-label integration checks.
- Checkpoint restart/resume for every representative branch.
- Actual expiry of 18,025 retained events across the checked replay hours.
- Preservation of all tracked input hashes and all three legacy module hashes.

The final decision is `PASS_PHASE5_DATA_AND_ROLLING_GRAPH_VALIDATION`. All four
handover closeout milestones are validated. Source installation remains necessary
before your main project can import the new version; model training is not done.

The final acceptance report and updated campaign register are under
`reports/phase5_final_acceptance_v2`. They supersede the earlier conditional
graph-gate decision while preserving the original dataset freeze and old reports.

This adds a versioned graph runtime and validates it against the frozen Phase 5
data. Existing graph modules, original campaigns, sources, labels and prior
reports remain unchanged. No model is trained.

## Accepted integration path

Use `src.organization.rolling_graph_v1.OrganizationGraphRuntime` for subsequent
GraphSAGE implementation. The legacy cumulative builder/updater are retained for
reproducing earlier work; they are not called by this runtime or validation path.

The old builder initialized from all past data and its updater only expired
ten-minute counters. The new runtime initializes from the bounded history view
and incrementally expires timestamped events AND structural edges after seven
days. This is a replacement path, not a patch that changes archived experiments.

## Exact behavior

- Retain event history and User-IP interactions in `(t-7 days,t]`.
- Derive recent features from `(t-10 minutes,t]`.
- A repeated User-IP relationship remains until its last retained event expires.
- Remove an edge only when its retained event count reaches zero.
- Remove orphan nodes from active tensors. Dense tensor indices can change per
  view; private organization-local entity keys remain the identity.
- Keep ingestion dedup tokens only for retained events. Reject duplicate retained
  tokens, out-of-order timestamps and a second batch at a closed timestamp.
- All simultaneous events arrive in one timestamp batch. Validation completes
  before mutation. Runtime calls follow one serialized event-time sequence.
- Both `training_view()` and `detection_view()` read the same persistent graph.
  Tensor export does not rebuild independent ten-minute graph states.
- Export immutable cached views; graph updates invalidate the cache. Copies of
  feature/edge tensors are supplied to PyG. Neither labels nor masks enter PyG Data.
- Save/resume retained event state and clock using checksummed JSON/GZIP.
- The runtime retains timestamped interactions even though GraphSAGE's tensor
  view uses aggregated bipartite adjacency. GraphSAGE remains the selected GNN.

Memory is bounded by traffic retained within seven days, rather than lifetime
event/node history. No fixed traffic-volume or byte cap is claimed.

## Observable feature schema

The eight columns preserve the existing feature names and ordering. Their
long-window counts now explicitly refer to retained seven-day history.

| Column | Value |
|---|---|
| total_logins | log1p of retained attempt count |
| successful_logins | log1p of retained successes |
| failed_logins | log1p of retained failures |
| failure_ratio | retained failures / retained attempts |
| distinct_neighbors | log1p of retained distinct opposite-type neighbors |
| recent_logins_10min | log1p of recent attempt count |
| recent_distinct_neighbors_10min | log1p of recent distinct neighbors |
| node_type | 0 for User, 1 for IP |

No fitted statistics are used. Raw IDs, IP strings, ingestion tokens, campaign
identifiers, source flags, labels and eligibility masks are excluded from model
features. Entity keys remain local graph/mapping information. User labels join by
organization-local key and graph as-of time, outside the model packet. IP nodes
remain unsupervised context. No permanent campaign-wide targeted-user flag is
carried inside graph state.

## Validation protocol

Twenty unit tests exercise exact cutoffs, repeated edges, idle expiry, orphan and
dedup memory cleanup, tied timestamps, invalid/duplicate/late inputs, organization
scope, feature values, model-packet allowlisting, label separation, fork isolation
and checkpoint tampering/restart.

The real-data protocol was fixed before execution: Sorg-family instances with
Sorg=5, RIP=.50 and Raccount=.50, for all three seeds in every chronological
split, and all five organizations. That gives 45 attack branches. Each is checked
at six grid times and the final microsecond before the exclusive replay end:
315 as-of feature/edge/label checks. There are also 45 derived pure-background
feature controls. No accepted dataset is edited to construct these controls.

An independent SQL oracle computes retained/recent counts, successes, distinct
neighbors and adjacency from the timestamped observations. Integer counts and
edge sets must match exactly; float32 transformed features use rtol=1e-6 and
atol=1e-7. Real-source checkpoint restart/resume is checked in every branch.
Both runtime views must agree, and attaching labels must leave the features
unchanged. All input files read and all three legacy module hashes are checked
for preservation.

This is representative graph validation across every organization and split/seed,
not graph-feature replay of all 2,565 branches. The earlier all-branch replay and
3,454,398-state label validation are reused without regeneration or re-audit.

Five representative TRAIN/seed1001 PyG graphs, private node mappings, checkpoints
and separate supervision arrays are provided for inspection and reproduction.
They are not a substitute for the full model-training/evaluation dataset.

## Installation: one copy, no result uploads

Save `CredBlock_FL_Graph_Retention_Fix_v1.zip` in the project root, then run:

```powershell
Set-Location 'C:\Users\Gulso\Documents\Gul\CredBlock-FL'
Expand-Archive -LiteralPath '.\CredBlock_FL_Graph_Retention_Fix_v1.zip' -DestinationPath '.'
```

The package adds NEW files under the existing `src/organization` and `reports`
folders, plus a validation script and runtime manifest. It does not replace these
folders or overwrite old graph modules. No `-Force` is used. If any of these new
file names already exist, stop rather than overwrite them.

You do not need to run tests or upload reports: the package contains the verified
results. Installation is still necessary before your main project can import the
new runtime. The tested implementation is initially in the shared working area.

For optional reproduction, with the existing virtual environment activated:

```powershell
python .\validate_phase5_graph_retention_v1.py --self-test
python .\validate_phase5_graph_retention_v1.py --freeze-dir '.\reports\phase5_graph_retention_v1\dataset_freeze_reference' --output '.\reports\phase5_graph_retention_v1_run2'
```

The second command requires a new output directory and uses existing source and
replay files. It neither regenerates attacks nor reruns the complete label audit.

## Next phase

After successful validation and installation, use this runtime for Phase 6
GraphSAGE. Training, threshold calibration, fitted preprocessing (if introduced),
actual training/evaluation isolation, FL, formal privacy, robust aggregation and
Fabric are not implemented or certified by this graph-retention fix.
