import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from src.organization.rolling_graph_v1 import RollingGraph, FEATURES, OBSERVABLE
from src.phase6.readiness import exact_supervision

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / 'configs/phase6_data_contract_v1.json').read_text())


def view():
    t = datetime(2020, 3, 1, 13)
    graph = RollingGraph('Org1')
    graph.ingest_batch(t, [dict(zip(OBSERVABLE, ['Org1', t, 1, '192.0.2.1', False]))], ['private-token'])
    return graph.view()


def state(v, **changes):
    row = dict(organization='Org1', **{'User ID': 1}, label_time=v.asof, node_label=1, supervision_eligible=True)
    row.update(changes)
    return row


def test_contract_matches_accepted_runtime():
    assert tuple(f['name'] for f in CONTRACT['features']) == FEATURES
    assert set(CONTRACT['observable_columns']) == set(OBSERVABLE)
    assert set(view().to_pyg().keys()) == set(CONTRACT['model_packet_allowlist'])


@pytest.mark.parametrize('changes', [dict(organization='Org2'), dict(label_time=datetime(2021, 1, 1)),
                                    {'User ID': 2}, dict(node_label=2), dict(supervision_eligible=False)])
def test_invalid_supervision_rejected(changes):
    v = view()
    with pytest.raises(ValueError):
        exact_supervision(v, [state(v, **changes)])


def test_duplicate_supervision_rejected():
    v = view()
    with pytest.raises(ValueError):
        exact_supervision(v, [state(v), state(v)])


def test_label_join_does_not_change_features_and_ips_masked():
    v = view()
    digest = v.digest()
    y, mask = exact_supervision(v, [state(v)])
    assert y.tolist() == [1, -1]
    assert mask.tolist() == [True, False]
    assert digest == v.digest()
    y, mask = exact_supervision(v, [])
    assert not mask.any()


@pytest.mark.parametrize('column', CONTRACT['evaluator_only'])
def test_evaluator_columns_cannot_enter_runtime(column):
    v = view()
    row = dict(zip(OBSERVABLE, ['Org1', v.asof, 1, '192.0.2.1', False]))
    row[column] = 'forbidden'
    with pytest.raises(ValueError):
        RollingGraph('Org1').ingest_batch(v.asof, [row], ['token'])


@pytest.mark.parametrize('org', CONTRACT['organizations'])
def test_real_train_observation_exact_label_join(org):
    import duckdb
    root = Path(__file__).resolve().parents[2]
    folder = root / 'data/phase5/controlled_replay_labels_all_orgs_causal_v1/CFV1_SO_CS_027_SEED1001_TRAIN'
    db = duckdb.connect(':memory:')
    observations = str(folder / f'{org}_observations.parquet')
    labels = str(folder / f'{org}_labels.parquet')
    t = db.execute('SELECT min("Login Timestamp") FROM read_parquet(?)', [observations]).fetchone()[0]
    batch = db.execute('SELECT * FROM read_parquet(?) WHERE "Login Timestamp"=?', [observations, t]).fetchdf().to_dict('records')
    # Normalize pandas scalar timestamps to the accepted naive datetime API.
    for row in batch:
        row['Login Timestamp'] = t
    graph = RollingGraph(org)
    graph.ingest_batch(t, batch, [f'local-{i}' for i in range(len(batch))])
    v = graph.view()
    users = [key for kind, key in v.private_keys if kind == 'U']
    states = db.execute('SELECT organization,"User ID",label_time,node_label,supervision_eligible FROM read_parquet(?) WHERE label_time=? AND "User ID" IN (SELECT unnest(?))', [labels, t, users]).fetchdf().to_dict('records')
    assert states
    for row in states:
        row['label_time'] = t
    y, mask = exact_supervision(v, states)
    assert mask.any()
    db.close()
