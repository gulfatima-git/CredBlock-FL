#!/usr/bin/env python3
"""Isolated full-inventory replay and temporal User labels (no model training).

Run from project root: python replay_and_label_phase5_inventory_v1.py
Uses the unchanged, accepted build_phase5_temporal_user_labels_v1.py module.
Input inventory autodetection: data/phase5/... then data2/phase5/... (one only).
Requires existing DuckDB and Pandas. Existing output directories are refused.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

VERSION = 'full-controlled-all-orgs-replay-labels-v1'
LABEL_BUILDER_SHA256 = '4e18cc290dd22d3fb0a43c009701ca84fbc6c2ef0699c3397e7eb49bcbf6efe2'
REPLAY_COLUMNS = ['organization', 'Login Timestamp', 'User ID', 'IP Address',
    'LoginSuccessful', 'is_synthetic', 'credential_stuffing_label', 'scenario_id',
    'campaign_id', 'synthetic_credential_id', 'is_reused_credential',
    'campaign_event_id', 'replay_event_id', 'source_is_attack_ip',
    'source_is_account_takeover', 'clean_negative_eligible']
SPLITS = {'TRAIN': (datetime(2020, 2, 3), datetime(2020, 10, 1)),
          'VAL': (datetime(2020, 10, 1), datetime(2020, 12, 1)),
          'TEST': (datetime(2020, 12, 1), datetime(2021, 3, 1))}
LABELS = None


def require(test, message):
    if not test:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, default=str)
        f.write('\n')


def load_label_builder(path):
    require(path.is_file(), 'Missing accepted label builder: ' + str(path))
    require(sha(path) == LABEL_BUILDER_SHA256, 'Label builder differs from accepted v1; refusing policy drift')
    spec = importlib.util.spec_from_file_location('accepted_temporal_user_labels_v1', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def q(name):
    return '"' + name.replace('"', '""') + '"'


def normalize_background(org, block, ordinal, row, history=False):
    t, uid, ip, success, attack, takeover = row
    return {'organization': org, 'Login Timestamp': t, 'User ID': uid,
        'IP Address': ip, 'LoginSuccessful': success,
        'is_synthetic': False, 'credential_stuffing_label': 0,
        'scenario_id': None, 'campaign_id': None, 'synthetic_credential_id': None,
        'is_reused_credential': None, 'campaign_event_id': None,
        'replay_event_id': f'{"HIST" if history else "BG"}_{block}_{org}_{ordinal:09d}',
        'source_is_attack_ip': attack, 'source_is_account_takeover': takeover,
        'clean_negative_eligible': attack is False and takeover is False}


def logical_hash(rows, columns=REPLAY_COLUMNS):
    h = hashlib.sha256()
    for row in rows:
        values = [row[c].isoformat(timespec='microseconds') if isinstance(row[c], datetime)
                  else row[c] for c in columns]
        h.update(json.dumps(values, separators=(',', ':'), ensure_ascii=False).encode())
        h.update(b'\n')
    return h.hexdigest()


def read_source_context(db, files, org, block, anchor):
    end = anchor + timedelta(hours=1)
    start = anchor - timedelta(days=7)
    schema = {r[0] for r in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',
                                     [[str(f) for f in files]]).fetchall()}
    outcome = 'LoginSuccessful' if 'LoginSuccessful' in schema else 'Login Successful'
    required = {'Login Timestamp', 'User ID', 'IP Address', outcome, 'Is Attack IP', 'Is Account Takeover'}
    require(required <= schema, 'Source schema incomplete: ' + org)
    rows = db.execute(f'''SELECT CAST("Login Timestamp" AS TIMESTAMP), CAST("User ID" AS BIGINT),
                  CAST("IP Address" AS VARCHAR), TRY_CAST({q(outcome)} AS BOOLEAN),
                  TRY_CAST("Is Attack IP" AS BOOLEAN), TRY_CAST("Is Account Takeover" AS BOOLEAN)
                  FROM read_parquet(?) WHERE CAST("Login Timestamp" AS TIMESTAMP) >= ?
                    AND CAST("Login Timestamp" AS TIMESTAMP) < ? ORDER BY 1,2,3,4,5,6''',
                  [[str(f) for f in files], start, end]).fetchall()
    require(all(t is not None and uid is not None and ip is not None and outcome is not None
                for t, uid, ip, outcome, a, b in rows), 'Null required source observation')
    history, background = [], []
    for r in rows:
        is_history = r[0] < anchor
        dest = history if is_history else background
        dest.append(normalize_background(org, block, len(dest), r, history=is_history))
    require(history and background, 'Source history/replay window is empty: ' + block + '/' + org)
    LABELS.validate_events(history, org, start, anchor, history=True)
    LABELS.validate_events(background, org, anchor, end)
    last_history = {}
    for row in history:
        last_history[row['User ID']] = row['Login Timestamp']
    require(len(last_history) > 0, 'No graph-context users')
    recent = [r for r in history if r['Login Timestamp'] > anchor - LABELS.LOOKBACK]
    return {'background': background, 'recent_history': recent,
        'history_count': len(history), 'history_logical_sha256': logical_hash(history),
        'background_logical_sha256': logical_hash(background),
        'history_last_by_user': last_history, 'sorted_history_last_times': sorted(last_history.values()),
        'history_start': start, 'anchor': anchor, 'end': end}


def graph_user_count(context, replay, t):
    cutoff = t - LABELS.HISTORY
    times = context['sorted_history_last_times']
    # Historical users remain only while their latest retained observation is >cutoff.
    retained = len(times) - bisect_right(times, cutoff)
    refreshed = {r['User ID'] for r in replay if cutoff < r['Login Timestamp'] <= t}
    retained += sum(context['history_last_by_user'].get(uid, datetime.min) <= cutoff for uid in refreshed)
    return retained


def build_labels(context, replay, org, anchor, end):
    # Labels depend only on ten-minute history. Retain full seven-day *as-of*
    # context counts separately, avoiding repeated full-history index construction.
    schedule, grid, engine = LABELS.build_schedule(context['recent_history'], replay, org, anchor, end)
    LABELS.check_schedule(context['recent_history'], replay, schedule, org, anchor, end)
    for g in grid:
        g['graph_user_nodes_asof'] = graph_user_count(context, replay, g['label_time'])
        g['older_context_only_users'] = g['graph_user_nodes_asof'] - g['recent_active_users']
        require(g['older_context_only_users'] >= 0, 'Graph/recent cohort inconsistency')
    return schedule, grid, engine


def read_synthetic(db, path, manifest, org):
    cursor = db.execute('SELECT * FROM read_parquet(?)', [str(path)])
    columns = [r[0] for r in cursor.description]
    rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
    require(len(rows) == manifest['events_per_organization'][org], 'Synthetic input count mismatch')
    out = []
    for r in rows:
        require(r['organization'] == org and r['campaign_id'] == manifest['variant_id'], 'Synthetic identity mismatch')
        require(r['is_synthetic'] is True and r['credential_stuffing_label'] == 1, 'Synthetic input truth mismatch')
        require(isinstance(r['User ID'], int) and r['User ID'] is not None, 'Invalid synthetic User ID')
        row = {c: r.get(c) for c in REPLAY_COLUMNS}
        row.update(replay_event_id='SYN_' + r['campaign_event_id'], source_is_attack_ip=None,
                   source_is_account_takeover=None, clean_negative_eligible=False)
        out.append(row)
    return out


def pre_anchor_evidence(db, files, users, anchor):
    import pandas as pd
    if not users:
        return {}
    db.register('targeted_user_keys', pd.DataFrame({'uid': sorted(users)}))
    try:
        return dict(db.execute('''SELECT CAST(s."User ID" AS BIGINT), MAX(CAST(s."Login Timestamp" AS TIMESTAMP))
            FROM read_parquet(?) s JOIN targeted_user_keys k ON CAST(s."User ID" AS BIGINT)=k.uid
            WHERE CAST(s."Login Timestamp" AS TIMESTAMP) < ? GROUP BY CAST(s."User ID" AS BIGINT)''',
            [[str(f) for f in files], anchor]).fetchall())
    finally:
        db.unregister('targeted_user_keys')


def resolve_inventory(root, explicit):
    if explicit:
        p = explicit.resolve()
        require(p.is_dir(), 'Inventory directory not found: ' + str(p))
        return p
    candidates = [root / part / 'phase5/controlled_inventory_causal_v1' for part in ['data', 'data2']]
    found = [p for p in candidates if p.is_dir()]
    require(len(found) == 1, 'Expected one inventory in data or data2; supply --inventory for an explicit location')
    return found[0]


def validate_merged(replay, synthetic, background, org, anchor, end):
    LABELS.validate_events(replay, org, anchor, end)
    require(len(replay) == len(synthetic) + len(background), 'Merged event-count mismatch')
    require(sum(r['is_synthetic'] for r in replay) == len(synthetic), 'Synthetic events lost/duplicated')
    recovered = [r for r in replay if not r['is_synthetic']]
    require(logical_hash(recovered) == logical_hash(sorted(background, key=event_sort)),
            'Shared background changed during branch replay')
    require(replay == sorted(replay, key=event_sort), 'Replay timestamps/ties are not deterministic')


def event_sort(row):
    return (row['Login Timestamp'], row['is_synthetic'], row['User ID'], row['IP Address'], row['replay_event_id'])


def verify_input_outputs(inventory):
    expected = read_json(inventory / 'output_sha256.json')
    require(len(expected) > 2000, 'Incomplete inventory hash manifest')
    for relative, h in expected.items():
        p = (inventory / relative).resolve()
        require(p.is_relative_to(inventory), 'Input hash path escapes inventory')
        require(sha(p) == h, 'Generated inventory input differs: ' + relative)


def run(root, inventory, output, dependency_path):
    import duckdb
    import pandas as pd
    require(not output.exists(), 'Output already exists; refusing overwrite: ' + str(output))
    for p in [inventory, root / 'data/organizations', root / 'data/phase5/controlled_replay_causal_v2']:
        require(not output.is_relative_to(p) and not p.is_relative_to(output), 'Output overlaps preserved input')
    generation = read_json(inventory / 'summary.json')
    require(generation['status'] == 'PASS_FULL_CONTROLLED_CAUSAL_GENERATION_ONLY', 'Generation acceptance gate failed')
    require(generation['instances_generated'] == 513 and generation['organization_branches'] == 1647,
            'Generation inventory counts differ')
    require(generation['all_preserved_input_hashes_unchanged'] is True, 'Generation preservation gate failed')
    verify_input_outputs(inventory)
    manifests = [read_json(p) for p in sorted(inventory.glob('CFV1*/manifest.json'))]
    require(len(manifests) == 513, 'Expected 513 instance manifests')
    require(len({m['variant_id'] for m in manifests}) == 513, 'Duplicate instance IDs')
    require(sum(len(m['targeted_organizations']) for m in manifests) == 1647, 'Branch inventory mismatch')
    org_files = {f'Org{i}': sorted((root / 'data/organizations' / f'organization=Org{i}').rglob('*.parquet'))
                 for i in range(1, 6)}
    require(all(org_files.values()), 'Missing organization background sources')
    inputs = [p for p in inventory.rglob('*') if p.is_file()] + [dependency_path] + [
        p for files in org_files.values() for p in files]
    print('Checking accepted inputs and source versions...', flush=True)
    baseline = {str(p): sha(p) for p in sorted(set(inputs))}
    prior_hashes = generation['preserved_input_sha256']
    for files in org_files.values():
        for f in files:
            require(prior_hashes.get(str(f)) == baseline[str(f)], 'Source changed since generation: ' + str(f))
    by_block = defaultdict(list)
    for m in manifests:
        require(m['schema_version'] == 'controlled-inventory-causal-v1', 'Wrong inventory schema')
        require(m['causal_target_selection_corrected'] is True, 'Uncorrected cohort input')
        split, seed = m['split'], m['seed']
        anchor = datetime.fromisoformat(m['campaign_start'])
        end = datetime.fromisoformat(m['campaign_end'])
        lo, hi = SPLITS[split]
        require(lo <= anchor < end <= hi and end - anchor == timedelta(hours=1), 'Campaign crosses split/duration')
        by_block[(split, seed, anchor)].append(m)
    require(len(by_block) == 9 and all(len(ms) == 57 for ms in by_block.values()), 'Expected nine 57-instance blocks')
    db = duckdb.connect(':memory:')
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'policy.json', LABELS.policy())
    branches, grids, buckets, variants, references, evidence = [], [], [], [], [], []
    try:
        for (split, seed, anchor), block_manifests in sorted(by_block.items(), key=lambda kv:
                (list(SPLITS).index(kv[0][0]), kv[0][1])):
            block = f'{split}_SEED{seed}'
            end = anchor + timedelta(hours=1)
            contexts, eligible = {}, {}
            print(block + ': reading shared source windows...', flush=True)
            targets_per_org = defaultdict(set)
            synthetic_cache = {}
            for m in block_manifests:
                vid = m['variant_id']
                for org in m['targeted_organizations']:
                    path = inventory / vid / (org + '.parquet')
                    require(baseline[str(path)] == m['output_parquet_sha256'][org], 'Instance Parquet hash mismatch')
                    rows = read_synthetic(db, path, m, org)
                    synthetic_cache[(vid, org)] = rows
                    targets_per_org[org].update(r['User ID'] for r in rows)
            reference_dir = output / 'history_references' / block
            reference_dir.mkdir(parents=True)
            for org in sorted(org_files):
                files = org_files[org]
                c = read_source_context(db, files, org, block, anchor)
                contexts[org] = c
                eligible[org] = pre_anchor_evidence(db, files, targets_per_org[org], anchor)
                require(set(eligible[org]) == targets_per_org[org], 'Target lacks pre-anchor source observation')
                # A bounded source view is the retained history, not an independent
                # graph snapshot. No duplicate copies of large raw histories are made.
                reference = {'version': VERSION, 'block': block, 'organization': org,
                    'source_kind': 'READ_ONLY_BOUNDED_ORGANIZATION_PARQUET_VIEW',
                    'source_files_relative_to_root': [str(f.relative_to(root)) for f in files],
                    'source_sha256': {str(f.relative_to(root)): baseline[str(f)] for f in files},
                    'history_start_inclusive': c['history_start'].isoformat(),
                    'history_end_exclusive': anchor.isoformat(), 'history_event_count': c['history_count'],
                    'history_logical_sha256': c['history_logical_sha256'],
                    'background_window_end_exclusive': end.isoformat(),
                    'background_event_count': len(c['background']),
                    'background_logical_sha256': c['background_logical_sha256'],
                    'history_normalization': 'Same normalization as normalize_background(); HIST ordinal in timestamp/User/IP/outcome/flags order',
                    'graph_retention_asof': '(t-7 days,t]; exclude lower-bound events when building graph state',
                    'context_only': True, 'history_supervision_exported': False}
                write_json(reference_dir / (org + '.json'), reference)
                references.append(reference)
            for m in block_manifests:
                vid = m['variant_id']
                folder = output / vid
                folder.mkdir()
                branch_entries = []
                for org in sorted(org_files):
                    c, synthetic = contexts[org], synthetic_cache.get((vid, org), [])
                    replay = sorted(c['background'] + synthetic, key=event_sort)
                    validate_merged(replay, synthetic, c['background'], org, anchor, end)
                    schedule, grid, engine = build_labels(c, replay, org, anchor, end)
                    require(len({(s['User ID'], s['label_time']) for s in schedule}) == len(schedule),
                            'Duplicate User/time state')
                    for s in schedule:
                        s['variant_id'], s['split'] = vid, split
                    LABELS.write_parquet(db, folder / (org + '_replay.parquet'), replay, REPLAY_COLUMNS)
                    # Read-back comparison covers exact event values, not only counts.
                    cur = db.execute('SELECT ' + ','.join(q(c) for c in REPLAY_COLUMNS) +
                                     ' FROM read_parquet(?) ORDER BY "Login Timestamp",is_synthetic,"User ID","IP Address",replay_event_id',
                                     [str(folder / (org + '_replay.parquet'))])
                    stored = [dict(zip(REPLAY_COLUMNS, row)) for row in cur.fetchall()]
                    require(logical_hash(stored) == logical_hash(replay), 'Stored replay roundtrip mismatch')
                    label_frame = pd.DataFrame(schedule, columns=LABELS.STATE_COLUMNS + ['variant_id', 'split'])
                    # Background-only branches have all-null positive evidence.
                    # Keep timestamp dtypes consistent rather than inferring INTEGER.
                    for column in ['label_time', 'latest_positive_evidence', 'positive_expires_at']:
                        label_frame[column] = pd.to_datetime(label_frame[column])
                    LABELS.write_parquet(db, folder / (org + '_labels.parquet'), label_frame)
                    label_values = db.execute('''SELECT COUNT(*),
                        COUNT(*) FILTER (WHERE node_label=1), COUNT(*) FILTER (WHERE node_label=0),
                        COUNT(*) FILTER (WHERE node_label=-1) FROM read_parquet(?)''',
                        [str(folder / (org + '_labels.parquet'))]).fetchone()
                    expected_counts = Counter(s['node_label'] for s in schedule)
                    require(label_values == (len(schedule), expected_counts[1], expected_counts[0], expected_counts[-1]),
                            'Stored label partition differs from validated schedule')
                    observations = LABELS.project_observations(pd.DataFrame(replay))
                    require(list(observations.columns) == LABELS.OBSERVABLE_COLUMNS, 'Observation metadata leak')
                    LABELS.write_parquet(db, folder / (org + '_observations.parquet'), observations)
                    per_grid = defaultdict(list)
                    for s in schedule:
                        if 'grid_snapshot' in s['query_kind']:
                            per_grid[s['label_time']].append(s)
                    for g in grid:
                        states = per_grid[g['label_time']]
                        g.update(variant_id=vid, split=split, seed=seed,
                            positive_users=sum(s['node_label'] == 1 for s in states),
                            negative_candidate_users=sum(s['node_label'] == 0 for s in states),
                            ambiguous_users=sum(s['reason'] == 'ambiguous_source' for s in states))
                        require(g['recent_active_users'] == g['positive_users'] +
                                g['negative_candidate_users'] + g['ambiguous_users'], 'Grid partition mismatch')
                        grids.append(g)
                    # Direct prefix check at the middle of the hour. Both constructions
                    # must agree for every User queried there, including future targets.
                    t = anchor + timedelta(minutes=30)
                    prefix = LABELS.TemporalLabels(c['recent_history'] + [r for r in replay if r['Login Timestamp'] <= t])
                    for uid in {s['User ID'] for s in schedule if s['label_time'] == t}:
                        require(prefix.state(org, uid, t) == engine.state(org, uid, t), 'Future event influenced earlier supervision')
                    bucket_events = 0
                    for k in range(6):
                        lo, hi = anchor + k * LABELS.LOOKBACK, anchor + (k + 1) * LABELS.LOOKBACK
                        rows = [r for r in replay if lo <= r['Login Timestamp'] < hi]
                        bucket_events += len(rows)
                        buckets.append({'variant_id': vid, 'split': split, 'organization': org,
                            'bucket_start': lo, 'bucket_end_exclusive': hi, 'events': len(rows),
                            'synthetic_events': sum(r['is_synthetic'] for r in rows)})
                    require(bucket_events == len(replay), 'Half-open bucket accounting mismatch')
                    for (o, uid), times in engine.positive_times.items():
                        if times:
                            states = [s['label_time'] for s in schedule if s['User ID'] == uid and s['node_label'] == 1]
                            evidence.append({'variant_id': vid, 'organization': o, 'User ID': uid,
                                'first_positive_evidence': times[0], 'last_positive_evidence': times[-1],
                                'last_materialized_positive': max(states), 'nominal_expiry': times[-1] + LABELS.LOOKBACK,
                                'expiry_outside_observed_coverage': times[-1] + LABELS.LOOKBACK >= end})
                    counts = Counter(s['node_label'] for s in schedule)
                    targeted = {r['User ID'] for r in synthetic}
                    require(bool(synthetic) is (org in m['targeted_organizations']), 'Target organization mismatch')
                    if not synthetic:
                        require(counts[1] == 0, 'Non-targeted organization has positive supervision')
                    result = {'variant_id': vid, 'family': m['family'], 'split': split, 'seed': seed,
                        'organization': org, 'status': 'PASS_REPLAY_AND_TEMPORAL_LABELS',
                        'is_targeted_organization': org in m['targeted_organizations'],
                        'background_events': len(c['background']), 'synthetic_events': len(synthetic),
                        'replay_events': len(replay), 'targeted_users': len(targeted),
                        'pre_anchor_observed_targeted_users': len(targeted & eligible[org].keys()),
                        'event_clean_negative_candidates': sum(r['clean_negative_eligible'] for r in c['background']),
                        'event_ambiguous_background': sum(LABELS.ambiguous(r) for r in c['background']),
                        'label_rows': len(schedule), 'oracle_checked_rows': len(schedule),
                        'positive_rows': counts[1], 'negative_candidate_rows': counts[0], 'masked_rows': counts[-1],
                        'ambiguous_masked_rows': sum(s['reason'] == 'ambiguous_source' for s in schedule),
                        'context_only_rows': sum(s['recent_event_count'] == 0 for s in schedule),
                        'background_logical_sha256': c['background_logical_sha256'],
                        'stored_replay_logical_sha256': logical_hash(stored),
                        'history_reference': str((reference_dir / (org + '.json')).relative_to(output)),
                        'replay_parquet_sha256': sha(folder / (org + '_replay.parquet')),
                        'labels_parquet_sha256': sha(folder / (org + '_labels.parquet')),
                        'observations_parquet_sha256': sha(folder / (org + '_observations.parquet'))}
                    branches.append(result)
                    branch_entries.append(result)
                write_json(folder / 'replay_manifest.json', {'version': VERSION, 'variant_id': vid,
                    'split': split, 'seed': seed, 'anchor': anchor.isoformat(), 'end_exclusive': end.isoformat(),
                    'targeted_organizations': m['targeted_organizations'], 'replayed_organizations': sorted(org_files),
                    'source_inventory_manifest_sha256': baseline[str(inventory / vid / 'manifest.json')],
                    'label_policy': LABELS.VERSION, 'branches': branch_entries,
                    'graphsage_feature_pipeline_verified': False, 'model_training_performed': False})
                variants.append({'variant_id': vid, 'split': split, 'seed': seed,
                    'organization_branches': len(branch_entries),
                    'replay_events': sum(b['replay_events'] for b in branch_entries),
                    'synthetic_events': sum(b['synthetic_events'] for b in branch_entries),
                    'label_rows': sum(b['label_rows'] for b in branch_entries),
                    'status': 'PASS_REPLAY_AND_TEMPORAL_LABELS'})
            print(block + ': 57 instances replayed and labeled', flush=True)
        require(len(variants) == 513 and len(branches) == 2565 and len(grids) == 15390, 'Incomplete output inventory')
        require(sum(b['is_targeted_organization'] for b in branches) == 1647, 'Targeted-branch coverage mismatch')
        require(sum(b['synthetic_events'] for b in branches) == generation['total_synthetic_events'], 'Synthetic total changed')
        require(sum(b['targeted_users'] for b in branches) == generation['target_user_branch_occurrences'], 'Target coverage changed')
        print('Verifying input preservation...', flush=True)
        require(all(sha(Path(p)) == h for p, h in baseline.items()), 'Input changed during replay')
        pd.DataFrame(branches).to_csv(output / 'branches.csv', index=False)
        pd.DataFrame(variants).to_csv(output / 'variants.csv', index=False)
        pd.DataFrame(grids).to_csv(output / 'grid_snapshots.csv', index=False)
        pd.DataFrame(buckets).to_csv(output / 'fixed_bucket_event_counts.csv', index=False)
        LABELS.write_parquet(db, output / 'user_positive_evidence.parquet', evidence)
        sums = {k: sum(b[k] for b in branches) for k in ['background_events', 'synthetic_events',
            'replay_events', 'targeted_users', 'pre_anchor_observed_targeted_users',
            'event_clean_negative_candidates', 'event_ambiguous_background', 'label_rows',
            'oracle_checked_rows', 'positive_rows', 'negative_candidate_rows', 'masked_rows',
            'ambiguous_masked_rows', 'context_only_rows']}
        summary = {'version': VERSION, 'status': 'PASS_FULL_CONTROLLED_REPLAY_AND_TEMPORAL_LABELS',
            'phase5_complete': False, 'final_acceptance_report_pending': True,
            'graphsage_feature_pipeline_verified': False, 'training_performed': False,
            'policy_optimized_on_test': False, 'label_policy_sha256': LABEL_BUILDER_SHA256,
            'builder_sha256': sha(Path(__file__).resolve()), 'variants': len(variants),
            'organization_branches': len(branches), 'grid_snapshots': len(grids),
            'targeted_organization_branches': 1647, 'background_only_organization_branches': 918,
            'all_background_only_branches_have_zero_positive_labels': True,
            'history_source_views': len(references), 'history_copies_materialized': False,
            'inventory_input': str(inventory), 'all_input_hashes_unchanged': True,
            'input_files_checked': len(baseline), 'source_input_sha256': baseline,
            'instances_per_split': dict(Counter(v['split'] for v in variants)),
            'totals': sums, 'self_tests': 'PASS',
            'checks': {'stored_replay_roundtrip': 'PASS', 'shared_background_logical_identity': 'PASS',
                'pre_anchor_target_eligibility': 'PASS', 'direct_record_label_oracle': 'PASS',
                'past_prefix_supervision_invariance': 'PASS', 'half_open_event_bucket_accounting': 'PASS',
                'observation_projection_allowlist': 'PASS', 'original_input_preservation': 'PASS',
                'asof_graph_user_context_counts': 'PASS', 'implemented_GraphSAGE_feature_pipeline': 'NOT_IMPLEMENTED'},
            'limitations': ['Original background is not established benign ground truth.',
                'Flags and truth are evaluator-only; runtime feature leakage is not certified before that pipeline exists.',
                'History is a read-only bounded view of checksum-pinned organization sources, not a duplicated historical dataset.',
                'Sparse label states and repeated background copies across isolated branches are not independent samples.',
                'No supervision beyond the replay end; nominal later expiries are coverage-censored.',
                'TRAIN/VAL/TEST are separate. No fitting, tuning, thresholding, or horizon selection occurs here.',
                'Raccount coverage/intensity and Sorg composition/volume limitations remain unchanged.'],
            'next_step': 'One consolidated Phase 5 acceptance report and dataset freeze'}
        write_json(output / 'summary.json', summary)
        (output / 'summary.txt').write_text('PASS_FULL_CONTROLLED_REPLAY_AND_TEMPORAL_LABELS\n'
            f"513 instances; 2565 branches (1647 targeted + 918 background-only); {sums['replay_events']} replay copies; {sums['label_rows']} oracle-checked User states.\n"
            'Inputs unchanged. Accepted v1 temporal policy reused without tuning.\n'
            'Phase 5 final acceptance/freeze pending. GraphSAGE feature pipeline not verified.\n', encoding='utf-8')
        write_json(output / 'output_sha256.json', {str(p.relative_to(output)): sha(p)
            for p in sorted(output.rglob('*')) if p.is_file()})
        print('PASS_FULL_CONTROLLED_REPLAY_AND_TEMPORAL_LABELS\n' + str(output))
    except Exception as exc:
        write_json(output / 'FAILED.json', {'status': 'FAILED_INCOMPLETE_OUTPUT', 'error': str(exc)})
        raise
    finally:
        db.close()


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.a = datetime(2020, 12, 12, 6)

    def context(self, history, background):
        last = {}
        for r in sorted(history, key=lambda r: r['Login Timestamp']):
            last[r['User ID']] = r['Login Timestamp']
        return {'background': background, 'recent_history': [r for r in history if r['Login Timestamp'] > self.a - LABELS.LOOKBACK],
            'history_last_by_user': last, 'sorted_history_last_times': sorted(last.values())}

    def test_optimized_schedule_matches_full_history(self):
        h = [LABELS.fixture(self.a - timedelta(days=7), user=5),
             LABELS.fixture(self.a - timedelta(days=6, hours=23, minutes=50), user=6),
             LABELS.fixture(self.a - timedelta(days=1), user=7),
             LABELS.fixture(self.a - timedelta(minutes=5), user=1, flag=True)]
        r = [LABELS.fixture(self.a + timedelta(minutes=1), user=7, synthetic=True),
             LABELS.fixture(self.a + timedelta(minutes=10), user=2)]
        expected, full_grid, _ = LABELS.build_schedule(h, r, 'Org1', self.a, self.a + timedelta(hours=1))
        actual, optimized_grid, _ = build_labels(self.context(h, []), r, 'Org1', self.a, self.a + timedelta(hours=1))
        self.assertEqual(expected, actual)
        self.assertEqual(full_grid, optimized_grid)

    def test_branch_isolation(self):
        h = [LABELS.fixture(self.a - timedelta(minutes=1), user=1)]
        a = [LABELS.fixture(self.a, user=1, synthetic=True)]
        b = [LABELS.fixture(self.a, user=2, synthetic=True)]
        c = self.context(h, [])
        sa, _, _ = build_labels(c, a, 'Org1', self.a, self.a + timedelta(hours=1))
        sb, _, _ = build_labels(c, b, 'Org1', self.a, self.a + timedelta(hours=1))
        self.assertEqual(next(s['node_label'] for s in sa if s['User ID'] == 1 and s['label_time'] == self.a), 1)
        self.assertEqual(next(s['node_label'] for s in sb if s['User ID'] == 1 and s['label_time'] == self.a), 0)

    def test_unknown_flags_masked(self):
        r = normalize_background('Org1', 'B', 0, (self.a, 1, '192.0.2.1', False, None, False))
        self.assertFalse(r['clean_negative_eligible'])
        self.assertTrue(LABELS.ambiguous(r))

    def test_background_only_org_has_no_positive_labels(self):
        h = [LABELS.fixture(self.a - timedelta(minutes=1), user=1, flag=True)]
        background = [LABELS.fixture(self.a + timedelta(minutes=1), user=2)]
        states, grid, _ = build_labels(self.context(h, background), background, 'Org1',
                                      self.a, self.a + timedelta(hours=1))
        self.assertFalse(any(s['node_label'] == 1 for s in states))
        self.assertTrue(any(s['reason'] == 'ambiguous_source' for s in states))

    def test_logical_hash_deterministic(self):
        r = normalize_background('Org1', 'B', 0, (self.a, 1, '192.0.2.1', False, False, False))
        self.assertEqual(logical_hash([r]), logical_hash([dict(r)]))
        changed = dict(r, credential_stuffing_label=1)
        self.assertNotEqual(logical_hash([r]), logical_hash([changed]))

    def test_no_future_graph_user(self):
        h = [LABELS.fixture(self.a - timedelta(days=1), user=1)]
        r = [LABELS.fixture(self.a + timedelta(seconds=1), user=2)]
        self.assertEqual(graph_user_count(self.context(h, []), r, self.a), 1)

    def test_history_expiry_and_refresh(self):
        h = [LABELS.fixture(self.a - timedelta(days=7) + timedelta(minutes=1), user=1)]
        c = self.context(h, [])
        t = self.a + timedelta(minutes=2)
        self.assertEqual(graph_user_count(c, [], t), 0)
        self.assertEqual(graph_user_count(c, [LABELS.fixture(t, user=1)], t), 1)


def main():
    global LABELS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--inventory', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--label-builder', type=Path)
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    root = args.root.resolve()
    dependency = (args.label_builder or root / 'build_phase5_temporal_user_labels_v1.py').resolve()
    LABELS = load_label_builder(dependency)
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(LABELS.AcceptanceTests),
                               unittest.defaultTestLoader.loadTestsFromTestCase(ReplayTests)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    require(result.wasSuccessful(), 'Replay/label acceptance tests failed')
    if not args.self_test:
        inventory = resolve_inventory(root, args.inventory)
        output = (args.output or root / 'data/phase5/controlled_replay_labels_all_orgs_causal_v1').resolve()
        run(root, inventory, output, dependency)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('STOPPED: ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        sys.exit(1)
