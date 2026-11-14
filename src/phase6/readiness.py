"""Read-only Phase 5 inventory; writes only a new Phase 6 report directory."""
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[2]
REPLAY = 'data/phase5/controlled_replay_labels_all_orgs_causal_v1'
FREEZE = 'reports/phase5_graph_retention_v1/dataset_freeze_reference/dataset_freeze_manifest.json'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def exact_supervision(view, states):
    """Exact organization/User/time join, using the accepted runtime checks."""
    for row in states:
        if row['supervision_eligible'] != (row['node_label'] != -1):
            raise ValueError('Supervision mask disagrees with frozen label')
    return view.supervision(states)


def run(output):
    import duckdb
    import numpy as np
    import torch
    from src.organization.rolling_graph_v1 import RollingGraph, FEATURES

    if output.exists():
        raise FileExistsError('Refusing to overwrite previous readiness evidence')
    freeze = load(ROOT / FREEZE)
    acceptance = load(ROOT / 'reports/phase5_final_acceptance_v2/summary.json')
    assert sha(ROOT / FREEZE) == acceptance['dataset_freeze_manifest_sha256']
    for name, digest in acceptance['graph_code'].items():
        assert sha(ROOT / name) == digest, name
    # Verify the entire logical freeze without regenerating any accepted data.
    failures = []
    for entry in freeze['files']:
        p = ROOT / entry['path_relative_to_project']
        if not p.is_file() or p.stat().st_size != entry['size_bytes'] or sha(p) != entry['sha256']:
            failures.append(str(p))
    assert not failures, failures
    hashes = {FREEZE: sha(ROOT / FREEZE)}
    rows = []
    db = duckdb.connect(':memory:')
    for path in sorted((ROOT / REPLAY).glob('CFV1*/replay_manifest.json')):
        m = load(path)
        hashes[path.relative_to(ROOT).as_posix()] = sha(path)
        source = ROOT / 'data2/phase5/controlled_inventory_causal_v1' / m['variant_id'] / 'manifest.json'
        assert sha(source) == m['source_inventory_manifest_sha256']
        hashes[source.relative_to(ROOT).as_posix()] = sha(source)
        assert m['replayed_organizations'] == [f'Org{i}' for i in range(1, 6)]
        for branch in m['branches']:
            org = branch['organization']
            item = dict(variant_id=m['variant_id'], organization=org, split=m['split'], seed=m['seed'],
                        anchor=m['anchor'], end_exclusive=m['end_exclusive'])
            for suffix in ('observations', 'labels', 'replay'):
                p = path.parent / f'{org}_{suffix}.parquet'
                # Read every file schema and footer; no TEST outcome analysis/selection.
                schema = db.execute('DESCRIBE SELECT * FROM read_parquet(?)', [str(p)]).fetchall()
                item[suffix + '_schema'] = {r[0]: r[1] for r in schema}
                assert sha(p) == branch[suffix + '_parquet_sha256']
                item[suffix + '_path'] = p.relative_to(ROOT).as_posix()
                if suffix == 'observations':
                    assert set(item[suffix + '_schema']) == {'organization', 'Login Timestamp', 'User ID', 'IP Address', 'LoginSuccessful'}
            ref = ROOT / REPLAY / branch['history_reference']
            assert ref.is_file()
            hashes[ref.relative_to(ROOT).as_posix()] = sha(ref)
            item['history_reference'] = ref.relative_to(ROOT).as_posix()
            rows.append(item)
    assert len(rows) == 2565
    graphs = []
    for i in range(1, 6):
        org = f'Org{i}'
        folder = ROOT / 'reports/phase5_graph_retention_v1/representative_graphs' / org
        graph = RollingGraph.from_checkpoint_bytes((folder / 'checkpoint.json.gz').read_bytes())
        view = graph.view()
        packet = view.to_pyg()
        with np.load(folder / 'supervision.npz') as supervision:
            assert len(supervision['y']) == len(view.private_keys)
            assert np.array_equal(supervision['eligible_mask'], supervision['y'] != -1)
            assert all(supervision['y'][j] == -1 for j, key in enumerate(view.private_keys) if key[0] == 'I')
        mapping = load(folder / 'private_node_mapping.json')
        assert mapping  # Mapping is private provenance, never a model feature.
        assert graph.organization == org
        graphs.append(dict(organization=org, asof=view.asof.isoformat(), nodes=packet.num_nodes,
                           directed_edges=packet.num_edges, checkpoint_digest=view.digest()))
    register = ROOT / 'reports/phase5_final_acceptance_v2/campaign_register_v2.csv'
    with register.open(newline='') as stream:
        campaigns = list(csv.DictReader(stream))
    assert {r['variant_id'] for r in rows} == {r['variant_id'] for r in campaigns}
    for p in [register, ROOT / 'reports/phase5_final_acceptance_v2/summary.json', ROOT / 'phase5_graph_runtime_manifest_v1.json']:
        hashes[p.relative_to(ROOT).as_posix()] = sha(p)
    manifest_id = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    report = dict(status='PASS_SUBPHASE0_TECHNICAL_GATE_AWAITING_USER_ACCEPTANCE',
                  dataset_id='phase5-dataset-freeze-v1:' + sha(ROOT / FREEZE),
                  inventory_id='phase6-input-inventory-v1:' + manifest_id,
                  frozen_files_verified=len(freeze['files']), campaign_instances=len(campaigns),
                  organization_branches=len(rows), input_manifest_sha256=hashes,
                  inputs=rows, representative_checkpoints=graphs, features=list(FEATURES),
                  environment=dict(python=platform.python_version(), platform=platform.platform(),
                                   packages={p: importlib.metadata.version(p) for p in ['duckdb','numpy','pandas','torch','torch-geometric','pytest']},
                                   cuda_available=torch.cuda.is_available()),
                  limitations=['Representative checkpoints are examples/resumable states, not the full training dataset.',
                               'No learned preprocessing, sampler, model, threshold or TEST outcome analysis implemented.',
                               'Original architecture PDFs/diagrams not independently inspected; roadmap is supplied authority.',
                               'No dependency lockfile or research workbook found; this directory is the local research record.',
                               'Historical conditional flags remain frozen; final_acceptance_v2 supersedes them.'])
    output.mkdir(parents=True)
    (output / 'input_inventory_v1.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    db.close()
    print(json.dumps({k: report[k] for k in ['status','frozen_files_verified','campaign_instances','organization_branches','environment']}))


if __name__ == '__main__':
    run(ROOT / 'reports/phase6/readiness/v1')
