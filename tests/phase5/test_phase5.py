"""CredBlock-FL Phase 5 checks. Read-only; no campaign files are generated or overwritten.
Run from project root: python -m pytest tests/phase5 -v -rs
"""
import importlib
import ipaddress
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest


def generator():
    return importlib.import_module('src.simulation.credential_stuffing_generator')


@pytest.fixture(scope='module')
def g():
    return generator()


@pytest.fixture(scope='module')
def project_root(g):
    return Path(g.PROJECT_ROOT)


def _schedule(root):
    path = root / 'data/phase5/metadata/split_campaign_schedule.json'
    if not path.is_file():
        pytest.skip(f'Local schedule not available: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def _campaign_ids(g, split=None):
    ids = [name for name, _ in sorted(g.CAMPAIGN_SLOTS.items(), key=lambda p: p[1])]
    return [f'{x}_{split}' for x in ids] if split else ids


def _new_campaign_dirs(root):
    root = root / 'data/phase5/synthetic_events'
    return [root / name for name in sorted(root.iterdir()) if name.is_dir() and name.name.endswith(('_TRAIN', '_VAL', '_TEST'))] if root.exists() else []


# A. Scenario design and schedule

def test_01_30_scenarios_and_full_factorial(g):
    assert len(g.SCENARIOS) == 30
    actual = Counter((v['org_spread'], v['rotation_level'], v['account_reuse_level']) for v in g.SCENARIOS.values())
    expected = Counter()
    for rotation in g.ROTATION_LEVELS:
        expected[(1, rotation, None)] += 1
        for spread in (2, 3, 5):
            for reuse in g.ACCOUNT_REUSE_LEVELS:
                expected[(spread, rotation, reuse)] += 1
    assert actual == expected


def test_02_seed_and_campaign_slots(g):
    assert tuple(g.EXPERIMENT_SEEDS) == (1001, 1002, 1003)
    assert len(g.CAMPAIGN_SLOTS) == 90
    assert set(g.CAMPAIGN_SLOTS.values()) == set(range(90))


def test_03_split_allocation_count(g):
    assert len(g.SPLIT_IP_ALLOCATIONS) == 270
    assert Counter(k.rsplit('_', 1)[-1] for k in g.SPLIT_IP_ALLOCATIONS) == {'TRAIN': 90, 'VAL': 90, 'TEST': 90}


def test_04_schedule_shape(project_root):
    schedule = _schedule(project_root)
    assert set(schedule) == {'train', 'val', 'test'}
    assert all(isinstance(schedule[k], list) and len(schedule[k]) == 90 for k in schedule)


def test_05_schedule_order_nonoverlap_and_split_limits(g, project_root):
    schedule = _schedule(project_root)
    all_periods = []
    for split in ('train', 'val', 'test'):
        dates = [datetime.fromisoformat(t) for t in schedule[split]]
        assert len(set(dates)) == 90
        lower, upper = (datetime.fromisoformat(t) for t in g.CHRONOLOGICAL_SPLITS[split])
        assert all(lower <= t and t + timedelta(minutes=g.CAMPAIGN_DURATION_MINUTES) <= upper for t in dates)
        periods = sorted((t, t + timedelta(minutes=g.CAMPAIGN_DURATION_MINUTES)) for t in dates)
        assert all(a[1] <= b[0] for a, b in zip(periods, periods[1:]))
        all_periods.extend(periods)
    all_periods.sort()
    assert all(a[1] <= b[0] for a, b in zip(all_periods, all_periods[1:]))


def test_06_proposed_schedule_to_allocation_mapping(g, project_root):
    """Checks constructed mapping only; does not prove a batch runner actually uses it."""
    schedule = _schedule(project_root)
    for split in ('TRAIN', 'VAL', 'TEST'):
        assert len(_campaign_ids(g, split)) == len(schedule[split.lower()])
        assert all(cid in g.SPLIT_IP_ALLOCATIONS for cid in _campaign_ids(g, split))


# B. IP reservations

def test_07_reserved_ranges_valid_and_separate(g):
    ranges = sorted((s, s + c, cid) for cid, (s, c) in g.SPLIT_IP_ALLOCATIONS.items())
    assert len(ranges) == 270
    assert ranges[0][0] >= g.IP_BLOCK_SIZE
    assert all(c > a and 0 <= a < c <= g.IP_NETWORK.num_addresses for a, c, _ in ranges)
    assert all(a[1] <= b[0] for a, b in zip(ranges, ranges[1:]))


def test_08_split_ip_ranges_pairwise_disjoint(g):
    bounds = {}
    for split in ('TRAIN', 'VAL', 'TEST'):
        arr = [(s, s + c) for cid, (s, c) in g.SPLIT_IP_ALLOCATIONS.items() if cid.endswith('_' + split)]
        assert len(arr) == 90
        bounds[split] = min(s for s, _ in arr), max(e for _, e in arr)
    for earlier, later in (('TRAIN', 'VAL'), ('TRAIN', 'TEST'), ('VAL', 'TEST')):
        assert bounds[earlier][1] <= bounds[later][0]


def test_09_allocator_outputs_stay_in_reservations(g):
    # Tests real allocator, not merely the capacity formula.
    for cid, (start, capacity) in g.SPLIT_IP_ALLOCATIONS.items():
        for index in sorted({0, capacity // 2, capacity - 1}):
            ip = ipaddress.ip_address(g.create_synthetic_ip(index, cid, capacity))
            offset = int(ip) - int(g.IP_NETWORK.network_address)
            assert start <= offset < start + capacity, (cid, index)


def test_10_allocator_rejects_out_of_bounds(g):
    cid, (_, capacity) = next(iter(g.SPLIT_IP_ALLOCATIONS.items()))
    with pytest.raises(ValueError):
        g.create_synthetic_ip(capacity, cid, capacity)
    with pytest.raises(ValueError):
        g.create_synthetic_ip(0, cid, capacity + 1)


def test_11_config_targets_and_determinism(g):
    for sid in g.SCENARIOS:
        for seed in g.EXPERIMENT_SEEDS:
            a, b = g.build_campaign_config(sid, seed), g.build_campaign_config(sid, seed)
            assert a == b
            assert len(a['targeted_organizations']) == a['Sorg']
            assert a['RIP_target'] in (0.2, 0.5, 0.8)
            assert a['Raccount_target'] is None if a['Sorg'] == 1 else a['Raccount_target'] in (0.2, 0.5, 0.8)


def test_12_reservations_sufficient_for_worst_case(g):
    for cid, (_, cap) in g.SPLIT_IP_ALLOCATIONS.items():
        sid = cid.split('_SEED')[0]
        sc = g.SCENARIOS[sid]
        spread = sc['org_spread']
        reused = 0 if spread == 1 else round(g.NUM_CREDENTIAL_IDENTITIES * g.ACCOUNT_REUSE_LEVELS[sc['account_reuse_level']])
        mappings = g.NUM_CREDENTIAL_IDENTITIES + (spread - 1) * reused
        required = round(mappings * g.MAX_ATTEMPTS_PER_ACCOUNT * g.ROTATION_LEVELS[sc['rotation_level']])
        assert cap >= required, cid


# C. Existing campaign data (run only when local files exist)

def test_13_historical_campaign_files_present(project_root, g):
    root = project_root / 'data/phase5/synthetic_events'
    if not root.exists():
        pytest.skip('Local historical campaign data not included in source ZIP')
    dirs = [root / cid for cid in _campaign_ids(g) if int(cid[3:6]) <= 12]
    assert len(dirs) == 36
    assert all(d.is_dir() and list(d.glob('*.parquet')) for d in dirs)


def test_14_historical_ips_do_not_overlap_new_reservations(project_root, g):
    duckdb = pytest.importorskip('duckdb')
    root = project_root / 'data/phase5/synthetic_events'
    files = [f for cid in _campaign_ids(g) if int(cid[3:6]) <= 12 for f in (root / cid).glob('*.parquet')]
    if not files:
        pytest.skip('Historical Parquet files unavailable')
    start_new = min(s for s, _ in g.SPLIT_IP_ALLOCATIONS.values())
    base = int(g.IP_NETWORK.network_address)
    for path in files:
        ips = duckdb.read_parquet(str(path)).project('"IP Address"').fetchall()
        for (ip,) in ips:
            offset = int(ipaddress.ip_address(ip)) - base
            assert 0 <= offset < start_new, (str(path), ip)


def test_15_generated_campaign_coverage(project_root, g):
    actual = {d.name for d in _new_campaign_dirs(project_root)}
    if not actual:
        pytest.skip('270 new campaigns not generated yet')
    expected = set(g.SPLIT_IP_ALLOCATIONS)
    assert actual == expected, f'Missing: {len(expected - actual)}, unexpected: {len(actual - expected)}'


def test_16_generated_manifests_complete(project_root, g):
    dirs = _new_campaign_dirs(project_root)
    if not dirs:
        pytest.skip('New campaigns not generated yet')
    expected_fields = {'campaign_id', 'scenario_id', 'seed', 'split', 'campaign_start', 'campaign_end', 'RIP_target', 'RIP_actual', 'Sorg_target', 'Sorg_actual', 'Raccount_target', 'Raccount_actual', 'total_events'}
    for d in dirs:
        path = d / 'manifest.json'
        assert path.is_file(), path
        manifest = json.loads(path.read_text(encoding='utf-8'))
        assert expected_fields <= set(manifest), (d, expected_fields - set(manifest))
        assert manifest['campaign_id'] == d.name


def test_17_generated_manifest_targets_and_times(project_root, g):
    dirs = _new_campaign_dirs(project_root)
    if not dirs:
        pytest.skip('New campaigns not generated yet')
    for d in dirs:
        path = d / 'manifest.json'
        assert path.is_file(), path
        m = json.loads(path.read_text(encoding='utf-8'))
        sc = g.SCENARIOS[m['scenario_id']]
        assert m['Sorg_actual'] == sc['org_spread']
        assert abs(m['RIP_actual'] - m['RIP_target']) <= (1 / max(1, m['total_events']) + 1e-10)
        assert m['Raccount_actual'] is None if sc['org_spread'] == 1 else abs(m['Raccount_actual'] - m['Raccount_target']) <= 0.011
        begin, end = datetime.fromisoformat(m['campaign_start']), datetime.fromisoformat(m['campaign_end'])
        assert end - begin == timedelta(minutes=60)
        lower, upper = (datetime.fromisoformat(t) for t in g.CHRONOLOGICAL_SPLITS[m['split']])
        assert lower <= begin < end <= upper


def test_18_actual_generated_ips_within_allocations(project_root, g):
    duckdb = pytest.importorskip('duckdb')
    dirs = _new_campaign_dirs(project_root)
    if not dirs:
        pytest.skip('New campaigns not generated yet')
    base = int(g.IP_NETWORK.network_address)
    for d in dirs:
        start, capacity = g.SPLIT_IP_ALLOCATIONS[d.name]
        files = sorted(d.glob('*.parquet'))
        assert files, d
        for path in files:
            for (ip,) in duckdb.read_parquet(str(path)).project('"IP Address"').fetchall():
                off = int(ipaddress.ip_address(ip)) - base
                assert start <= off < start + capacity, (d.name, ip)


def test_19_generated_event_integrity(project_root, g):
    duckdb = pytest.importorskip('duckdb')
    dirs = _new_campaign_dirs(project_root)
    if not dirs:
        pytest.skip('New campaigns not generated yet')
    for d in dirs:
        path = d / 'manifest.json'
        assert path.exists(), path
        m = json.loads(path.read_text(encoding='utf-8'))
        begin, end = datetime.fromisoformat(m['campaign_start']), datetime.fromisoformat(m['campaign_end'])
        ids = set()
        count = 0
        for parquet in d.glob('*.parquet'):
            for stamp, eid, cid in duckdb.read_parquet(str(parquet)).project('"Login Timestamp", campaign_event_id, campaign_id').fetchall():
                if isinstance(stamp, str): stamp = datetime.fromisoformat(stamp)
                assert begin <= stamp < end, (d.name, stamp)
                assert cid == d.name
                assert eid not in ids, (d.name, eid)
                ids.add(eid)
                count += 1
        assert count == m['total_events'], d.name


# D. Research acceptance gates — explicit unverified conditions, never fake PASS

def test_20_matched_factorial_comparison_evidence(project_root):
    pytest.skip('Requires independently audited cohort/background/intensity matching results; no verified audit artifact in uploaded ZIP')


def test_21_temporal_replay_graph_and_label_evidence(project_root):
    pytest.skip('Requires replay, seven-day retention, ten-minute feature, label onset/expiration and leakage audit artifacts')


def test_22_batch_generation_and_reproducibility_evidence(project_root):
    pytest.skip('Requires verified schedule-driven batch runner, independent regenerations and complete consolidated audit manifests')
