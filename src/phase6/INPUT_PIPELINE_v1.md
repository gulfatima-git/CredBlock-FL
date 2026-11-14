# Phase 6 input pipeline v1

This implements only Subphase 2. The accepted runtime, split protocol and supervision policies remain unchanged. No model, optimizer, training, calibration or final TEST evaluation is implemented.

## Use

Run from the CredBlock-FL project root with the existing virtual environment:

```python
from src.phase6.input_pipeline import PinnedInputs, BranchPipeline

pins = PinnedInputs('.')
with BranchPipeline(pins, 'CFV1_SO_CS_027_SEED1001_TRAIN', 'Org1',
                    purpose='integrity_audit') as branch:
    for t in branch.grid:
        sampler = branch.sampler(t)
        targets = branch.supervision_at(t)
        for batch in sampler.batches(batch_size=256, states=targets,
                                     protocol=pins.protocol):
            # Observable-only layer packets: batch.packets
            # Separate root supervision: batch.supervision.y / eligible_mask
            # Separate private alignment: batch.routing / root_rows
            pass
pins.verify_unchanged()
```

Only approved fixed-grid timestamps are accepted. The runtime persists through all six grid calls and is advanced chronologically. It consumes complete tied timestamp batches at or before `t`; a second timestamp batch cannot append after that clock is closed. History is initialized once per branch from the seven-day read-only source view. Each organization and alternative branch owns its state. Inputs are pinned to the frozen manifest; input/configuration hashes can be verified again at run close.

The `purpose` argument passes through the accepted split guard. TRAIN permits fitting inputs; VAL permits approved selection purposes; TEST cannot be opened for fit or selection. The default integrity-audit mode is for input validation, not authorization to run final TEST evaluation. `require_use` still rejects final evaluation until its later gate is explicitly implemented and authorized.

## Block tensor contract

`batch.packets` contains one PyG `Data` per model layer, in forward execution order. Every packet has exactly `x`, `edge_index`, and `num_nodes`. Features are the same eight float32 observable columns. Edges are int64 sampled neighbor-source to destination indices. No packet contains labels, masks, raw keys or evaluator provenance.

Expand backwards from the User roots using the fanouts in reverse layer order, then reverse the resulting blocks for model execution. A block's destination nodes are the prefix of its source nodes. The preceding block's destination rows equal the next block's source rows. `batch.routing[layer]` supplies these private row alignments; its length gives the destination count. Private keys never become embedding indices or numeric features.

For a future GraphSAGE forward pass, initialize hidden state from the first packet's `x`; at each layer, use that source hidden state, its destination prefix, and the packet's `edge_index`. Retain only the destination outputs before the next layer. Later layers consume the previous layer's hidden state, not a fresh reset to their raw packet `x`. Per-block raw `x` is retained for observable schema inspection. Self information is provided by GraphSAGE's root transform; sampled edges are the genuine User-IP adjacency without synthetic self edges. Final destinations are User roots only; IP nodes participate as context in intermediate layers.

`batch.supervision` contains only root labels and masks. All masks come from the accepted exact organization/User/time join. Missing or context-only supervision is `-1` and masked. The iterator joins supervision once per grid rather than allocating full-graph targets repeatedly for every batch. Roots and neighbors are chosen without labels; the default iterator covers every active User once in deterministic local order. It does not silently subsample clean negatives or rebalance classes.

## Deterministic temporal sampling

`configs/phase6/neighbor_sampling_v1.json` records two layers, fanouts `[15,10]`, batch size 256 and seed 60201. These are versioned input smoke-test defaults, not a selected model architecture. Sampling is uniform without replacement and uses all neighbors when degree is below the fanout. PCG64 is seeded by a stable SHA256 of local provenance, node key, layer and supplied seed, making neighbor choices independent of root batch partition and process hash randomization. NumPy version is recorded.

All hops use one immutable graph view at root scoring time `t`: eligible edges exist from events in `(t-7 days,t]`, and recent features use `(t-10 minutes,t]`. This is the approved GraphSAGE representation of time-stamped history, not a temporal GNN or a decreasing-time walk. A future event cannot mutate an earlier immutable view. New User and IP keys receive permitted observed features and local adjacency without any learned ID vocabulary.

Sorted CSR memory is linear in active nodes/edges; sampled block tensors are bounded by roots and fanouts. Python private mappings and retained event history also consume memory. No fixed byte cap or real million-node traffic throughput is promised by a synthetic degree-two scale smoke test.

## Reproduction and saved artifacts

```powershell
.venv/Scripts/python.exe -B -m pytest tests/phase6 -q -p no:cacheprovider
.venv/Scripts/python.exe -B -m src.phase6.validate_input_pipeline --output reports/phase6/pipeline/new_version
```

Existing report directories are refused. Real validation covers one fixed TRAIN/seed1001 branch, six grids per organization, with an independent SQL feature/edge oracle. Each organization has separate example `model_packets.npz`, `supervision.npz`, private routing and provenance under `reports/phase6/pipeline/v2/OrgN`. All NPZ arrays are numeric and load with `allow_pickle=False`. These are examples, not the complete training dataset. Preprocessing is fixed and unfitted; examples record schema/sampler hashes, preprocessing state and local node alignment. Future model runs must archive the corresponding full configuration files with their artifacts.
