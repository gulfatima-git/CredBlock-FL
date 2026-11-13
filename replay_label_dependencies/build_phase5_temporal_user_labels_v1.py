#!/usr/bin/env python3
"""CredBlock-FL temporal User-node supervision v1 (offline evaluator only).

Run from project root: python build_phase5_temporal_user_labels_v1.py
Self tests: python build_phase5_temporal_user_labels_v1.py --self-test
Requires DuckDB and Pandas; does not require PyArrow. Existing outputs are refused.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
import sys
import unittest

VERSION = 'temporal-user-labels-v1'
LOOKBACK = timedelta(minutes=10)
HISTORY = timedelta(days=7)
OBSERVABLE_COLUMNS = ['organization', 'Login Timestamp', 'User ID', 'IP Address', 'LoginSuccessful']
INPUT_COLUMNS = OBSERVABLE_COLUMNS + ['is_synthetic', 'credential_stuffing_label',
    'source_is_attack_ip', 'source_is_account_takeover', 'clean_negative_eligible', 'replay_event_id']
STATE_COLUMNS = ['organization', 'User ID', 'label_time', 'node_label', 'supervision_eligible',
    'reason', 'recent_event_count', 'recent_synthetic_count', 'recent_ambiguous_count',
    'latest_positive_evidence', 'positive_expires_at', 'query_kind']
SPLITS = [('TRAIN', datetime(2020, 2, 3), datetime(2020, 10, 1)),
          ('VAL', datetime(2020, 10, 1), datetime(2020, 12, 1)),
          ('TEST', datetime(2020, 12, 1), datetime(2021, 3, 1))]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, obj):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, default=str)
        f.write('\n')


def project_observations(frame):
    """Strict observation projection; identifiers are graph keys, not numeric features."""
    require(set(OBSERVABLE_COLUMNS) <= set(frame.columns), 'Missing observable fields')
    return frame.loc[:, OBSERVABLE_COLUMNS].copy()


def ambiguous(row):
    return (not row['is_synthetic'] and
            (row['source_is_attack_ip'] is not False or
             row['source_is_account_takeover'] is not False))


def validate_events(rows, org, start, end, history=False):
    seen = set()
    for r in rows:
        require(r['organization'] == org, 'Cross-organization input')
        require(isinstance(r['Login Timestamp'], datetime) and
                start <= r['Login Timestamp'] < end, 'Invalid timestamp or interval')
        require(r['User ID'] is not None, 'Null User ID')
        require(r['is_synthetic'] is True or r['is_synthetic'] is False, 'Unknown provenance')
        require(r['replay_event_id'] is not None and r['replay_event_id'] not in seen,
                'Missing/duplicate event ID')
        seen.add(r['replay_event_id'])
        if r['is_synthetic']:
            require(not history, 'Shared background history contains synthetic events')
            require(r['credential_stuffing_label'] == 1, 'Invalid synthetic truth')
            require(r['source_is_attack_ip'] is None and r['source_is_account_takeover'] is None,
                    'Synthetic truth/source flag mixing')
            require(r['clean_negative_eligible'] is False, 'Synthetic event eligible negative')
        else:
            require(r['credential_stuffing_label'] == 0, 'Invalid background truth')
            require(r['clean_negative_eligible'] is (not ambiguous(r)), 'Source eligibility mismatch')


class TemporalLabels:
    """Org-scoped, evaluator-only indices; every query uses an as-of upper bound."""
    def __init__(self, rows):
        self.events = defaultdict(list)
        for r in rows:
            self.events[(r['organization'], r['User ID'])].append(r)
        self.times, self.positive_times, self.ambiguous_times = {}, {}, {}
        for key, events in self.events.items():
            events.sort(key=lambda r: (r['Login Timestamp'], str(r['replay_event_id'])))
            self.times[key] = [r['Login Timestamp'] for r in events]
            self.positive_times[key] = [r['Login Timestamp'] for r in events if r['is_synthetic']]
            self.ambiguous_times[key] = [r['Login Timestamp'] for r in events if ambiguous(r)]

    @staticmethod
    def count(times, t):
        return bisect_right(times, t) - bisect_right(times, t - LOOKBACK)

    def state(self, org, user, t):
        key = (org, user)
        times = self.times.get(key, [])
        positives = self.positive_times.get(key, [])
        n, p = self.count(times, t), self.count(positives, t)
        a = self.count(self.ambiguous_times.get(key, []), t)
        if p:
            label, reason = 1, 'synthetic_targeting'
        elif a:
            label, reason = -1, 'ambiguous_source'
        elif n:
            label, reason = 0, 'clean_negative_candidate'
        else:
            label, reason = -1, 'no_recent_evidence_context_only'
        last = positives[bisect_right(positives, t) - 1] if p else None
        return dict(zip(STATE_COLUMNS[:-1], [org, user, t, label, label != -1,
            reason, n, p, a, last, last + LOOKBACK if last else None]))


def oracle(rows, org, user, t):
    recent = [r for r in rows if r['organization'] == org and r['User ID'] == user and
              t - LOOKBACK < r['Login Timestamp'] <= t]
    p = sum(r['is_synthetic'] for r in recent)
    a = sum(ambiguous(r) for r in recent)
    return (1 if p else -1 if a or not recent else 0, len(recent), p, a)


def build_schedule(history, replay, org, anchor, end):
    """Emit post-batch event states, exact expiries, and active-user grid snapshots.

    Fixed-grid snapshots are y(u,t) at t=anchor+k*10min (<end), NOT labels for
    a future bucket. Bucket accounting uses separate [a,b) intervals.
    Sparse context nodes without recent activity need no supervised row.
    """
    rows = history + replay
    engine = TemporalLabels(rows)
    queries = defaultdict(set)
    # Only the trailing ten minutes seed supervision. Older history is graph context.
    seeds = [r for r in history if r['Login Timestamp'] > anchor - LOOKBACK]
    for r in seeds:
        queries[(r['User ID'], anchor)].add('initial')
    for r in seeds + replay:
        t, uid = r['Login Timestamp'], r['User ID']
        if anchor <= t < end:
            queries[(uid, t)].add('event_batch')
        if anchor <= t + LOOKBACK < end:
            queries[(uid, t + LOOKBACK)].add('expiry')
    grid = []
    t = anchor
    while t < end:
        active_graph, active_recent = 0, 0
        for (o, uid), times in engine.times.items():
            if o != org:
                continue
            hi = bisect_right(times, t)
            if hi and times[hi - 1] > t - HISTORY:
                active_graph += 1
            if engine.count(times, t):
                active_recent += 1
                queries[(uid, t)].add('grid_snapshot')
        grid.append({'organization': org, 'label_time': t,
                     'graph_user_nodes_asof': active_graph,
                     'recent_active_users': active_recent,
                     'older_context_only_users': active_graph - active_recent})
        t += LOOKBACK
    schedule = []
    for (uid, t), kinds in sorted(queries.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        state = engine.state(org, uid, t)
        state['query_kind'] = '+'.join(sorted(kinds))
        schedule.append(state)
    return schedule, grid, engine


def check_schedule(history, replay, schedule, org, anchor, end):
    # Independent direct-record oracle: does not reuse the bisect implementation.
    by_user = defaultdict(list)
    for r in history + replay:
        if r['Login Timestamp'] > anchor - LOOKBACK:
            by_user[r['User ID']].append(r)
    positive_at_own_events = set()
    for state in schedule:
        require(anchor <= state['label_time'] < end, 'Label outside replay coverage')
        expected = oracle(by_user[state['User ID']], org, state['User ID'], state['label_time'])
        actual = tuple(state[k] for k in ['node_label', 'recent_event_count',
                                        'recent_synthetic_count', 'recent_ambiguous_count'])
        require(actual == expected, 'Temporal schedule/oracle disagreement')
        if state['node_label'] == 1:
            positive_at_own_events.add((state['User ID'], state['label_time']))
    require(all((r['User ID'], r['Login Timestamp']) in positive_at_own_events
                for r in replay if r['is_synthetic']), 'Synthetic event missing positive User label')
    require(len({(s['User ID'], s['label_time']) for s in schedule}) == len(schedule),
            'Duplicate node/time label')


def read_events(db, path):
    cols = ', '.join('"' + c.replace('"', '""') + '"' for c in INPUT_COLUMNS)
    return [dict(zip(INPUT_COLUMNS, r)) for r in
            db.execute('SELECT ' + cols + ' FROM read_parquet(?)', [str(path)]).fetchall()]


def write_parquet(db, path, records, columns=None):
    import pandas as pd
    frame = records if isinstance(records, pd.DataFrame) else pd.DataFrame(records, columns=columns)
    db.register('label_export', frame)
    try:
        escaped = str(path).replace("'", "''")
        db.execute("COPY label_export TO '" + escaped + "' (FORMAT PARQUET)")
    finally:
        db.unregister('label_export')


def policy():
    return {
        'version': VERSION, 'prediction_target': 'User node being targeted; not attacker identity or compromise',
        'positive_interval': '(t-10 minutes,t]', 'graph_history_interval': '(t-7 days,t]',
        'expiry': 'At latest qualifying event + 10 minutes, unless refreshed',
        'negative_eligibility': 'Recent event exists, no synthetic positive, all recent background flags explicitly false',
        'mask': 'Any recent suspicious/unknown source flag masks negative; no recent evidence is context-only',
        'priority': 'synthetic positive > ambiguous source > clean negative > context-only',
        'timestamp_precision': 'DuckDB/Python microseconds; source timezone-naive timestamps preserved without timezone inference',
        'ties': 'All events at the same timestamp are available together; one post-batch User state',
        'fixed_bucket_accounting': '[a,b); each replay event belongs to exactly one bucket',
        'grid_labels': 'Snapshots at anchor+k*10min (<end); y(u,t) includes events at t, never future bucket events',
        'coverage': 'Labels only within [anchor,end); no post-campaign persistence inferred without background coverage',
        'sampling': 'Sparse event/expiry transitions plus grid snapshots of recent active users; not independent samples',
        'context': 'History events are read-only context; no history training labels exported; IP nodes have no target labels',
        'split_usage': 'TEST fixture tests implementation only; no fitting, tuning, thresholding, or horizon selection',
        'source_provenance': 'Synthesized RBA authentication background with separately injected synthetic campaigns',
        'architecture_scope': 'Label tables do not rebuild graphs or implement GraphSAGE',
        'horizon_basis': 'Handover temporal policy; source diagrams specify ten-minute features, not a label-duration mandate',
        'limitations': ['Clean-negative candidates are not proven benign.',
                        'Ten-minute expiry does not imply security risk has disappeared.',
                        'No GraphSAGE features, DP, federation or model training implemented here.',
                        'Future feature-pipeline leakage and train-only preprocessing remain unverified.']}


def run(root, output):
    import duckdb
    import pandas as pd
    source = root / 'data/phase5/controlled_replay_causal_v2'
    audit_path = root / 'reports/phase5_label_leakage_causal_v2_summary.json'
    index_path = source / 'replay_index.json'
    require(source.is_dir(), 'Corrected replay not found')
    require(not output.exists(), 'Output exists; refusing overwrite: ' + str(output))
    require(not output.is_relative_to(source) and not source.is_relative_to(output), 'Output overlaps input')
    audit, index = load_json(audit_path), load_json(index_path)
    require(audit['status'] == 'PASS_DATA_LEVEL_PHASE6_GATES_OPEN', 'Prior data gate not accepted')
    require(index['status'] == 'PASS_CAUSAL_V2_REPLAY_MECHANICS_ONLY', 'Prior replay gate not accepted')
    require(index['all_replay_integrity_checks_passed'] is True, 'Prior replay failed')
    anchor, end = map(datetime.fromisoformat, [index['common_anchor'], index['background_window_end_exclusive']])
    hist_start = datetime.fromisoformat(index['history_start'])
    require(hist_start == anchor - HISTORY, 'History interval mismatch')
    split = next((name for name, lo, hi in SPLITS if lo <= anchor < end <= hi), None)
    require(split == 'TEST', 'This adapter is locked to the accepted TEST pilot')
    branches = index['per_org_checks']
    require(len(branches) == 16 and len({b['variant_id'] for b in branches}) == 6, 'Unexpected pilot inventory')
    require(len({(b['variant_id'], b['organization']) for b in branches}) == 16, 'Duplicate branch inventory')
    inputs = sorted(source.rglob('*'))
    inputs = [p for p in inputs if p.is_file()] + [audit_path]
    before = {str(p): digest(p) for p in inputs}
    # Fail-closed before creating output. Reuse prior acceptance hashes, not a new audit cycle.
    for b in branches:
        f = source / b['variant_id'] / (b['organization'] + '.parquet')
        require(before[str(f)] == b['replayed_parquet_sha256'], 'Accepted replay hash mismatch')
    db = duckdb.connect(':memory:')
    histories = {}
    for org in sorted({b['organization'] for b in branches}):
        histories[org] = read_events(db, source / 'shared_history_7d' / (org + '.parquet'))
        validate_events(histories[org], org, hist_start, anchor, history=True)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'policy.json', policy())
    results, evidence, buckets_all, grid_all = [], [], [], []
    try:
        for b in branches:
            variant, org = b['variant_id'], b['organization']
            manifest = load_json(source / variant / 'replay_manifest.json')
            require(manifest['anchor'] == anchor.isoformat() and manifest['end'] == end.isoformat(),
                    'Branch coverage mismatch')
            replay = read_events(db, source / variant / (org + '.parquet'))
            validate_events(replay, org, anchor, end)
            require(len(replay) == b['replay_events'] and
                    sum(r['is_synthetic'] for r in replay) == b['synthetic_events'], 'Event-count mismatch')
            history = histories[org]
            schedule, grid, engine = build_schedule(history, replay, org, anchor, end)
            check_schedule(history, replay, schedule, org, anchor, end)
            folder = output / variant
            folder.mkdir(exist_ok=True)
            for row in schedule:
                row['variant_id'], row['split'] = variant, split
            write_parquet(db, folder / (org + '_labels.parquet'), schedule, STATE_COLUMNS + ['variant_id', 'split'])
            frame = pd.DataFrame(replay)
            observable = project_observations(frame)
            require(list(observable.columns) == OBSERVABLE_COLUMNS, 'Observation projection leaked metadata')
            write_parquet(db, folder / (org + '_observations.parquet'), observable)
            t, buckets = anchor, []
            while t < end:
                right = min(t + LOOKBACK, end)
                events = [r for r in replay if t <= r['Login Timestamp'] < right]
                buckets.append({'variant_id': variant, 'organization': org, 'bucket_start': t,
                    'bucket_end_exclusive': right, 'events': len(events),
                    'synthetic_events': sum(r['is_synthetic'] for r in events)})
                t = right
            require(sum(x['events'] for x in buckets) == len(replay), 'Bucket accounting mismatch')
            buckets_all.extend(buckets)
            for g in grid:
                g['variant_id'] = variant
                states = [s for s in schedule if s['label_time'] == g['label_time'] and
                          'grid_snapshot' in s['query_kind']]
                g['positive_users'] = sum(s['node_label'] == 1 for s in states)
                g['negative_candidate_users'] = sum(s['node_label'] == 0 for s in states)
                g['ambiguous_users'] = sum(s['reason'] == 'ambiguous_source' for s in states)
                require(g['positive_users'] + g['negative_candidate_users'] + g['ambiguous_users'] ==
                        g['recent_active_users'], 'Grid cohort partition mismatch')
                grid_all.append(g)
            # Detailed evidence contains local IDs and stays inside the evaluator folder.
            for (o, uid), times in engine.positive_times.items():
                if not times:
                    continue
                positive_states = [s['label_time'] for s in schedule if s['User ID'] == uid and s['node_label'] == 1]
                evidence.append({'variant_id': variant, 'organization': o, 'User ID': uid,
                    'first_positive_evidence': times[0], 'last_positive_evidence': times[-1],
                    'last_materialized_positive': max(positive_states),
                    'nominal_expiry': times[-1] + LOOKBACK,
                    'expiry_outside_observed_coverage': times[-1] + LOOKBACK >= end})
            counts = Counter(s['node_label'] for s in schedule)
            result = {'variant_id': variant, 'organization': org, 'status': 'PASS_TEMPORAL_LABELS',
                'replay_events': len(replay), 'synthetic_events': b['synthetic_events'],
                'label_rows': len(schedule), 'positive_rows': counts[1],
                'negative_candidate_rows': counts[0], 'masked_rows': counts[-1],
                'ambiguous_masked_rows': sum(s['reason'] == 'ambiguous_source' for s in schedule),
                'context_only_rows': sum(s['recent_event_count'] == 0 for s in schedule),
                'oracle_checked_rows': len(schedule),
                'first_positive_time': min((s['label_time'] for s in schedule if s['node_label'] == 1), default=None),
                'last_materialized_positive_time': max((s['label_time'] for s in schedule if s['node_label'] == 1), default=None)}
            results.append(result)
            print(variant + '/' + org + ': PASS (' + str(len(schedule)) + ' label rows)', flush=True)
        require(sum(x['replay_events'] for x in results) == 5130 and
                sum(x['synthetic_events'] for x in results) == 1540, 'Pilot total mismatch')
        require(all(digest(Path(p)) == h for p, h in before.items()), 'An input changed during the run')
        pd.DataFrame(results).to_csv(output / 'branches.csv', index=False)
        pd.DataFrame(grid_all).to_csv(output / 'grid_snapshots.csv', index=False)
        pd.DataFrame(buckets_all).to_csv(output / 'fixed_bucket_event_counts.csv', index=False)
        write_parquet(db, output / 'user_positive_evidence.parquet', evidence)
        summary = {'version': VERSION, 'status': 'PASS_TEMPORAL_USER_LABEL_PILOT_ONLY',
            'phase5_complete': False, 'graphsage_feature_pipeline_verified': False,
            'training_performed': False, 'policy_optimized_on_test': False,
            'split': split, 'variants': 6, 'organization_branches': len(results),
            'replay_event_copies': 5130, 'synthetic_event_copies': 1540,
            'materialized_label_rows': sum(x['label_rows'] for x in results),
            'oracle_checked_rows': sum(x['oracle_checked_rows'] for x in results),
            'positive_user_branch_occurrences': len(evidence),
            'inputs_unchanged': True, 'source_sha256': before,
            'self_tests': 'PASS', 'policy': policy(), 'branches': results,
            'observable_projection_columns': OBSERVABLE_COLUMNS,
            'remaining_gates': ['Full corrected TRAIN/VAL/TEST inventory and replay',
                'Consolidated Phase 5 acceptance and freeze',
                'Actual graph-feature as-of checks and model feature allowlist enforcement',
                'Train-only fitted preprocessing and implemented training/evaluation isolation']}
        write_json(output / 'summary.json', summary)
        (output / 'summary.txt').write_text(
            'PASS_TEMPORAL_USER_LABEL_PILOT_ONLY\n6 variants; 16 branches; 5,130 replay event copies.\n'
            + str(summary['materialized_label_rows']) + ' materialized states matched the direct-record oracle.\n'
            'Inputs unchanged. No training or TEST-based policy selection.\n'
            'Label states are correlated snapshots/transitions, not independent samples.\n'
            'Phase 5 is still incomplete; GraphSAGE feature leakage is not certified.\n', encoding='utf-8')
        write_json(output / 'output_sha256.json', {str(p.relative_to(output)): digest(p)
            for p in sorted(output.rglob('*')) if p.is_file()})
        print('PASS_TEMPORAL_USER_LABEL_PILOT_ONLY\nReports: ' + str(output))
    except Exception as e:
        write_json(output / 'FAILED.json', {'status': 'FAILED_INCOMPLETE_OUTPUT', 'error': str(e)})
        raise
    finally:
        db.close()


def fixture(t, *, org='Org1', user=1, synthetic=False, flag=False, eid=None):
    return {'organization': org, 'User ID': user, 'Login Timestamp': t,
            'IP Address': '192.0.2.1', 'LoginSuccessful': False,
            'is_synthetic': synthetic, 'credential_stuffing_label': int(synthetic),
            'source_is_attack_ip': None if synthetic else flag,
            'source_is_account_takeover': None if synthetic else False,
            'clean_negative_eligible': False if synthetic else flag is False,
            'replay_event_id': eid or str((org, user, t, synthetic, flag))}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2020, 12, 12, 6)

    def test_onset_expiry_refresh(self):
        t = self.t
        e = TemporalLabels([fixture(t, synthetic=True), fixture(t + timedelta(minutes=9), synthetic=True)])
        self.assertEqual(e.state('Org1', 1, t - timedelta(microseconds=1))['node_label'], -1)
        self.assertEqual(e.state('Org1', 1, t)['node_label'], 1)
        self.assertEqual(e.state('Org1', 1, t + timedelta(minutes=10))['node_label'], 1)
        self.assertEqual(e.state('Org1', 1, t + timedelta(minutes=19))['node_label'], -1)

    def test_clean_negative_and_context_only(self):
        e = TemporalLabels([fixture(self.t)])
        self.assertEqual(e.state('Org1', 1, self.t)['node_label'], 0)
        self.assertFalse(e.state('Org1', 1, self.t + LOOKBACK)['supervision_eligible'])

    def test_ambiguity_and_unknown(self):
        for flag in [True, None]:
            e = TemporalLabels([fixture(self.t, flag=flag), fixture(self.t + timedelta(minutes=1))])
            self.assertEqual(e.state('Org1', 1, self.t + timedelta(minutes=1))['node_label'], -1)
            self.assertEqual(e.state('Org1', 1, self.t + LOOKBACK)['node_label'], 0)

    def test_positive_priority(self):
        e = TemporalLabels([fixture(self.t, flag=True), fixture(self.t, synthetic=True)])
        self.assertEqual(e.state('Org1', 1, self.t)['node_label'], 1)

    def test_org_scope(self):
        e = TemporalLabels([fixture(self.t, synthetic=True), fixture(self.t, org='Org2')])
        self.assertEqual(e.state('Org1', 1, self.t)['node_label'], 1)
        self.assertEqual(e.state('Org2', 1, self.t)['node_label'], 0)

    def test_positive_expiry_to_negative(self):
        e = TemporalLabels([fixture(self.t, synthetic=True), fixture(self.t + timedelta(minutes=5))])
        self.assertEqual(e.state('Org1', 1, self.t + LOOKBACK)['node_label'], 0)

    def test_future_prefix_invariance(self):
        past = [fixture(self.t)]
        future = fixture(self.t + timedelta(microseconds=1), synthetic=True)
        self.assertEqual(TemporalLabels(past).state('Org1', 1, self.t),
                         TemporalLabels(past + [future]).state('Org1', 1, self.t))

    def test_ties_order_deterministic(self):
        rows = [fixture(self.t, flag=True), fixture(self.t, synthetic=True), fixture(self.t)]
        a = build_schedule([], rows, 'Org1', self.t, self.t + timedelta(hours=1))[0]
        b = build_schedule([], rows[::-1], 'Org1', self.t, self.t + timedelta(hours=1))[0]
        self.assertEqual(a, b)
        self.assertEqual(a[0]['recent_event_count'], 3)
        self.assertEqual(a[0]['node_label'], 1)

    def test_history_mask_seed_and_expiry(self):
        h = [fixture(self.t - timedelta(minutes=1), flag=True)]
        s, _, _ = build_schedule(h, [], 'Org1', self.t, self.t + timedelta(hours=1))
        self.assertEqual(s[0]['reason'], 'ambiguous_source')
        self.assertTrue(any(x['label_time'] == self.t + timedelta(minutes=9) and
                            x['reason'] == 'no_recent_evidence_context_only' for x in s))

    def test_old_history_is_context(self):
        h = [fixture(self.t - timedelta(days=1))]
        s, g, _ = build_schedule(h, [], 'Org1', self.t, self.t + LOOKBACK)
        self.assertEqual(s, [])
        self.assertEqual(g[0]['older_context_only_users'], 1)

    def test_future_user_not_in_grid_cohort(self):
        r = [fixture(self.t + timedelta(minutes=1), synthetic=True)]
        _, g, _ = build_schedule([], r, 'Org1', self.t, self.t + LOOKBACK)
        self.assertEqual(g[0]['graph_user_nodes_asof'], 0)

    def test_fixed_buckets_and_grid_distinction(self):
        ts = [self.t, self.t + LOOKBACK, self.t + 2 * LOOKBACK - timedelta(microseconds=1)]
        counts = [sum(a <= t < a + LOOKBACK for t in ts) for a in [self.t, self.t + LOOKBACK]]
        self.assertEqual(counts, [1, 2])
        e = TemporalLabels([fixture(t, synthetic=True) for t in ts])
        self.assertEqual(e.state('Org1', 1, self.t + LOOKBACK)['recent_synthetic_count'], 1)

    def test_invalid_source_mask_rejected(self):
        r = fixture(self.t, flag=True)
        r['clean_negative_eligible'] = True
        with self.assertRaises(ValueError):
            validate_events([r], 'Org1', self.t, self.t + LOOKBACK)

    def test_observable_allowlist(self):
        import pandas as pd
        frame = pd.DataFrame([fixture(self.t, synthetic=True)])
        frame['future_secret'] = 42
        self.assertEqual(list(project_observations(frame).columns), OBSERVABLE_COLUMNS)

    def test_randomized_direct_oracle(self):
        rng = random.Random(901)
        rows = [fixture(self.t + timedelta(seconds=rng.randrange(1800)),
                        user=rng.randrange(4), org='Org' + str(rng.randrange(1, 3)),
                        synthetic=rng.choice([True, False]), flag=rng.choice([True, False, None]), eid=str(i))
                for i in range(120)]
        e = TemporalLabels(rows)
        for i in range(80):
            t = self.t + timedelta(seconds=i * 35)
            for org in ['Org1', 'Org2']:
                for uid in range(4):
                    s = e.state(org, uid, t)
                    self.assertEqual(tuple(s[k] for k in ['node_label', 'recent_event_count',
                        'recent_synthetic_count', 'recent_ambiguous_count']), oracle(rows, org, uid, t))


def self_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AcceptanceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    require(result.wasSuccessful(), 'Acceptance tests failed')
    return result.testsRun


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--output', type=Path, help='New, nonexistent directory; defaults under data/phase5')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    self_tests()
    if not args.self_test:
        root = args.root.resolve()
        output = (args.output or root / 'data/phase5/temporal_user_labels_causal_v1').resolve()
        run(root, output)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('STOPPED: ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        sys.exit(1)
