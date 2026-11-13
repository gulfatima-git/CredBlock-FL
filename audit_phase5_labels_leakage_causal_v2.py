#!/usr/bin/env python3
"""CredBlock-FL Phase 5: consolidated replay label/mask/time/leakage audit.

READ-ONLY INPUTS. Creates ONLY new reports/phase5_label_leakage_causal_v2_*
from the immutable data/phase5/controlled_replay_causal_v2 and prior reports.

Run from CredBlock-FL root:
  python audit_phase5_labels_leakage_causal_v2.py

A PASS_DATA_LEVEL result is NOT certification of GraphSAGE features, node-label
onset/expiry, source negatives being truly benign, or correct use of TEST data.
Those are flagged as NOT_TESTABLE_IN_REPLAY and transferred to Phase 6.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

VERSION = 'phase5-label-leakage-causal-v2'
BASE = 'phase5_label_leakage_causal_v2'
ANCHOR = datetime.fromisoformat('2020-12-12T06:00:00')
END = ANCHOR + timedelta(hours=1)
HISTORY = ANCHOR - timedelta(days=7)
SPLIT_START = datetime.fromisoformat('2020-12-01T00:00:00')
SPLIT_END = datetime.fromisoformat('2021-03-01T00:00:00')
EXPECTED_VARIANTS = {
    'CPV2_RA_CS_004_SEED1001_TEST': {'Org1', 'Org2'},
    'CPV2_RA_CS_013_SEED1001_TEST': {'Org1', 'Org2'},
    'CPV2_RA_CS_014_SEED1001_TEST': {'Org1', 'Org2'},
    'CPV2_SO_CS_004_SEED1001_TEST': {'Org1', 'Org2'},
    'CPV2_SO_CS_019_SEED1001_TEST': {'Org1', 'Org2', 'Org5'},
    'CPV2_SO_CS_025_SEED1001_TEST': {'Org1', 'Org2', 'Org3', 'Org4', 'Org5'},
}
EXPECTED_FIELDS = {
    'organization', 'Login Timestamp', 'User ID', 'IP Address',
    'LoginSuccessful', 'is_synthetic', 'credential_stuffing_label',
    'scenario_id', 'campaign_id', 'synthetic_credential_id',
    'is_reused_credential', 'campaign_event_id', 'replay_event_id',
    'source_is_attack_ip', 'source_is_account_takeover',
    'clean_negative_eligible',
}
# These remain for audit/provenance ONLY, never for predictive features.
FORBIDDEN_MODEL_FEATURES = {
    'is_synthetic', 'credential_stuffing_label', 'scenario_id',
    'campaign_id', 'synthetic_credential_id', 'is_reused_credential',
    'campaign_event_id', 'replay_event_id', 'clean_negative_eligible',
    'source_is_attack_ip', 'source_is_account_takeover',
    'label', 'label_mask', 'node_label', 'is_attack_ip',
    'is_account_takeover',
}


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def assert_equal(actual, expected, description):
    if actual != expected:
        raise ValueError(f'{description}: expected {expected!r}, got {actual!r}')


def bool_flag(v):
    # DuckDB produces bool or None for nullable BOOLEAN columns.
    return v is True


def source_clean_eligible(is_attack, takeover):
    # Only both flags explicitly False are clean-negative candidates.
    return is_attack is False and takeover is False


def evaluate_rows(rows, *, variant, org, expected_bg, expected_syn):
    """Pure record-level audit logic; also used by embedded smoke tests."""
    failures = []
    def require(condition, code):
        if not condition:
            failures.append(code)

    n = len(rows)
    require(n == expected_bg + expected_syn, 'EVENT_CONSERVATION')
    require(all(r['organization'] == org for r in rows), 'ORG_ISOLATION')
    require(all(isinstance(r['Login Timestamp'], datetime) and
                ANCHOR <= r['Login Timestamp'] < END for r in rows), 'WINDOW_BOUNDARY')
    require(all(rows[k]['Login Timestamp'] <= rows[k+1]['Login Timestamp']
                for k in range(n-1)), 'TIMESTAMP_MONOTONIC')
    ids = [r['replay_event_id'] for r in rows]
    require(all(isinstance(x, str) and x for x in ids) and
            len(set(ids)) == n, 'REPLAY_ID_UNIQUE')
    require(all(r['User ID'] is not None and r['IP Address'] is not None and
                r['LoginSuccessful'] is not None for r in rows), 'REQUIRED_FIELDS')

    syn = [r for r in rows if r['is_synthetic'] is True]
    bg = [r for r in rows if r['is_synthetic'] is False]
    require(len(syn) == expected_syn, 'SYNTHETIC_COUNT')
    require(len(bg) == expected_bg, 'BACKGROUND_COUNT')
    require(all(r['is_synthetic'] in (True, False) for r in rows), 'SYNTHETIC_FLAG_NULL')
    require(all(r['credential_stuffing_label'] == 1 for r in syn), 'SYNTHETIC_GROUND_TRUTH')
    require(all(r['credential_stuffing_label'] == 0 for r in bg), 'BACKGROUND_CREDENTIAL_LABEL')
    require(all(r['clean_negative_eligible'] is False for r in syn), 'SYNTHETIC_NEGATIVE_MASK')
    require(all(r['source_is_attack_ip'] is None and
                r['source_is_account_takeover'] is None for r in syn), 'SYNTHETIC_SOURCE_FLAG_CONTAMINATION')
    require(all(r['campaign_id'] == variant and
                r['campaign_event_id'] is not None and
                r['synthetic_credential_id'] is not None for r in syn), 'SYNTHETIC_PROVENANCE')
    require(all(r['replay_event_id'].startswith('SYN_') for r in syn), 'SYNTHETIC_ID_NAMESPACE')
    require(all(r['replay_event_id'].startswith('BG_') for r in bg), 'BACKGROUND_ID_NAMESPACE')
    require(all(r['campaign_id'] is None and
                r['campaign_event_id'] is None and
                r['synthetic_credential_id'] is None and
                r['scenario_id'] is None and
                r['is_reused_credential'] is None for r in bg), 'BACKGROUND_SYNTHETIC_METADATA')
    require(all(r['clean_negative_eligible'] is source_clean_eligible(
                r['source_is_attack_ip'], r['source_is_account_takeover']) for r in bg),
            'SOURCE_NEGATIVE_POLICY')

    ambiguous = sum(not source_clean_eligible(r['source_is_attack_ip'],
                   r['source_is_account_takeover']) for r in bg)
    clean = sum(r['clean_negative_eligible'] is True for r in bg)
    require(clean + ambiguous == len(bg), 'NEGATIVE_PARTITION')
    require(not any(r['clean_negative_eligible'] is True and
                    r['credential_stuffing_label'] == 1 for r in rows), 'POSITIVE_NEGATIVE_COLLISION')

    # The replay contains EVENT-level labels. Derive first-positive times for
    # evidence only; there is no implemented node-label schedule to certify.
    first_positive = {}
    for r in syn:
        key = r['User ID']
        if key not in first_positive or r['Login Timestamp'] < first_positive[key]:
            first_positive[key] = r['Login Timestamp']
    require(all(ANCHOR <= ts < END for ts in first_positive.values()),
            'FIRST_POSITIVE_BEFORE_ANCHOR')
    return {
        'variant_id': variant, 'organization': org,
        'background_events': len(bg), 'synthetic_events': len(syn),
        'replay_events': n, 'clean_negative_candidates': clean,
        'ambiguous_background_events': ambiguous,
        'distinct_positive_user_ids': len(first_positive),
        'first_positive_min': min(first_positive.values()).isoformat() if first_positive else '',
        'first_positive_max': max(first_positive.values()).isoformat() if first_positive else '',
        'status': 'PASS_DATA_LEVEL' if not failures else 'FAIL_DATA_LEVEL',
        'failures': failures,
    }


def run_audit(root: Path):
    replay_dir = root / 'data/phase5/controlled_replay_causal_v2'
    report_dir = root / 'reports'
    summary_file = report_dir / 'phase5_controlled_replay_causal_v2_summary.json'
    selection_file = report_dir / 'phase5_causal_selection_pilot_v2_summary.json'
    baseline_file = report_dir / 'phase5_controlled_replay_pilot_v1_summary.json'
    outputs = [report_dir / f'{BASE}_{name}' for name in
               ('summary.json', 'branches.csv', 'summary.txt')]
    if any(p.exists() for p in outputs):
        raise FileExistsError('An audit report already exists; refusing to overwrite')
    if not replay_dir.is_dir():
        raise FileNotFoundError(f'Missing corrected replay: {replay_dir}')
    for p in (summary_file, selection_file, baseline_file):
        if not p.is_file():
            raise FileNotFoundError(f'Missing required prior validation: {p}')
    summary, selection, baseline = map(read_json, (summary_file, selection_file, baseline_file))
    assert_equal(summary.get('status'), 'PASS_CAUSAL_V2_REPLAY_MECHANICS_ONLY', 'v2 replay status')
    assert_equal(summary.get('six_variants'), 6, 'v2 variant count')
    assert_equal(summary.get('total_org_replays'), 16, 'v2 branch count')
    assert_equal(summary.get('all_replay_integrity_checks_passed'), True, 'v2 replay mechanics')
    assert_equal(summary.get('all_targeted_user_ids_observed_before_anchor'), True, 'cohort eligibility')
    assert_equal(summary.get('common_anchor'), ANCHOR.isoformat(), 'v2 anchor')
    assert_equal(summary.get('history_start'), HISTORY.isoformat(), 'v2 history')
    assert_equal(selection.get('corrected_target_occurrences_with_pre_anchor_observation'), 890,
                 'pre-anchor selection count')
    assert_equal(selection.get('status'), 'PASS_CAUSAL_SELECTION_PILOT_ONLY', 'v2 selection')
    assert_equal(summary.get('common_background_digests'), baseline.get('common_background_digests'),
                 'v1 vs v2 background parity')
    if not SPLIT_START <= ANCHOR < END <= SPLIT_END:
        raise ValueError('Pilot timestamp out of TEST split')
    prior = summary.get('per_org_checks', [])
    assert_equal(len(prior), 16, 'per-branch expected counts')
    prior_map = {(r['variant_id'],r['organization']):r for r in prior}
    assert_equal(len(prior_map), 16, 'unique per-branch summary keys')
    expected_keys = {(v,o) for v,orgs in EXPECTED_VARIANTS.items() for o in orgs}
    assert_equal(set(prior_map), expected_keys, 'exact expected branches')
    assert_equal(set(p.name for p in replay_dir.iterdir() if p.is_dir()) - {'shared_history_7d'},
                 set(EXPECTED_VARIANTS), 'replay directory inventory')

    import duckdb
    db = duckdb.connect(':memory:')
    fields = ['organization', 'Login Timestamp', 'User ID', 'IP Address',
              'LoginSuccessful', 'is_synthetic', 'credential_stuffing_label',
              'scenario_id', 'campaign_id', 'synthetic_credential_id',
              'is_reused_credential', 'campaign_event_id', 'replay_event_id',
              'source_is_attack_ip', 'source_is_account_takeover',
              'clean_negative_eligible']
    branches = []
    source_hashes = {str(p.relative_to(root)): file_hash(p) for p in
                     (summary_file, selection_file, baseline_file)}
    for variant in sorted(EXPECTED_VARIANTS):
        folder = replay_dir / variant
        manifest_path = folder / 'replay_manifest.json'
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        manifest = read_json(manifest_path)
        assert_equal(manifest.get('version'), 'controlled-replay-causal-v2', 'branch manifest version')
        assert_equal(manifest.get('variant_id'), variant, 'branch manifest ID')
        assert_equal(manifest.get('anchor'), ANCHOR.isoformat(), 'branch anchor')
        assert_equal(manifest.get('end'), END.isoformat(), 'branch end')
        source_hashes[str(manifest_path.relative_to(root))] = file_hash(manifest_path)
        for org in sorted(EXPECTED_VARIANTS[variant]):
            path = folder / f'{org}.parquet'
            if not path.is_file():
                raise FileNotFoundError(path)
            expected_hash = prior_map[(variant,org)]['replayed_parquet_sha256']
            assert_equal(file_hash(path), expected_hash, f'replay file hash {variant}/{org}')
            schema = {x[0] for x in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',
                                                 [str(path)]).fetchall()}
            assert_equal(EXPECTED_FIELDS <= schema, True, f'replay schema {variant}/{org}')
            # Extra fields may indicate a derived output erroneously used for training.
            # Do not fail for optional audit metadata; record its existence.
            extra = sorted(schema - EXPECTED_FIELDS)
            if any(c.lower() in {'node_label', 'model_feature', 'prediction'} for c in extra):
                raise ValueError(f'Unexpected model/label fields in replay: {variant}/{org} {extra}')
            sql = 'SELECT ' + ', '.join('"'+c.replace('"','""')+'"' for c in fields) + \
                  ' FROM read_parquet(?) ORDER BY "Login Timestamp", is_synthetic, "User ID", "IP Address", replay_event_id'
            cursor = db.execute(sql, [str(path)])
            rows = [dict(zip(fields, values)) for values in cursor.fetchall()]
            counts = prior_map[(variant,org)]
            result = evaluate_rows(rows, variant=variant, org=org,
                                   expected_bg=counts['background_events'],
                                   expected_syn=counts['synthetic_events'])
            result['replay_sha256'] = expected_hash
            result['extra_columns'] = extra
            result['background_digest_matches_prior'] = (
                counts['background_digest'] == summary['common_background_digests'][org])
            if not result['background_digest_matches_prior']:
                result['failures'].append('BACKGROUND_DIGEST_PARITY')
                result['status'] = 'FAIL_DATA_LEVEL'
            branches.append(result)
            print(f'  {variant}/{org}: {result["status"]} | positive={result["synthetic_events"]} '
                  f'negative-candidates={result["clean_negative_candidates"]} '
                  f'ambiguous={result["ambiguous_background_events"]}', flush=True)
            source_hashes[str(path.relative_to(root))] = expected_hash
    assert_equal(sum(r['synthetic_events'] for r in branches), 1540, 'synthetic event copies')
    assert_equal(sum(r['background_events'] for r in branches), 3590, 'background event copies')
    assert_equal(sum(r['replay_events'] for r in branches), 5130, 'all replay event copies')
    assert_equal(set((r['variant_id'],r['organization']) for r in branches), expected_keys,
                 'covered branch inventory')
    for relative, expected in source_hashes.items():
        assert_equal(file_hash(root/relative), expected, f'input immutability: {relative}')

    passed = all(r['status'] == 'PASS_DATA_LEVEL' for r in branches)
    # Only column classification can be asserted; whether a future feature pipeline
    # accidentally exposes them has NOT been inspected or certified here.
    gates = {
        'event_ground_truth_consistency': 'PASS' if passed else 'FAIL',
        'source_flags_and_clean_negative_mask_consistency': 'PASS' if passed else 'FAIL',
        'replay_timestamp_order_and_split_bounds': 'PASS' if passed else 'FAIL',
        'corrected_target_pre_anchor_observation': 'PASS_PRIOR_REPLAY_REPORT',
        'same_background_as_v1': 'PASS_PRIOR_REPLAY_REPORT',
        'node_label_onset_and_expiry': 'NOT_TESTABLE_IN_REPLAY',
        'graph_feature_asof_time_and_future_edge_exclusion': 'NOT_TESTABLE_IN_REPLAY',
        'model_feature_column_allowlist_enforcement': 'NOT_TESTABLE_IN_REPLAY',
        'fitted_preprocessing_train_only': 'NOT_TESTABLE_IN_REPLAY',
        'test_split_never_used_for_training_or_selection': 'NOT_TESTABLE_IN_REPLAY',
        'source_flags_are_true_benign_ground_truth': 'NOT_ESTABLISHED',
    }
    outcome = {
        'audit': VERSION,
        'status': 'PASS_DATA_LEVEL_PHASE6_GATES_OPEN' if passed else 'FAIL_DATA_LEVEL',
        'phase5_complete': False,
        'model_ready': False,
        'test_split': 'TEST',
        'anchor': ANCHOR.isoformat(),
        'replay_folder': str(replay_dir),
        'variants': 6, 'organization_branches': len(branches),
        'events_total': sum(r['replay_events'] for r in branches),
        'synthetic_event_copies': sum(r['synthetic_events'] for r in branches),
        'background_event_copies': sum(r['background_events'] for r in branches),
        'clean_negative_candidates': sum(r['clean_negative_candidates'] for r in branches),
        'ambiguous_background_event_copies': sum(r['ambiguous_background_events'] for r in branches),
        'source_input_sha256': source_hashes,
        'checks': gates,
        'forbidden_model_input_columns': sorted(FORBIDDEN_MODEL_FEATURES),
        'phase6_acceptance_gates': [
            'Implement time-dependent User-node labels: positive only at/after first qualifying attack; define expiry/horizon and prove no pre-onset positives.',
            'Implement strict as-of event/edge construction for every prediction; never use future events or future-derived statistics.',
            'Enforce an explicit model feature allowlist; exclude simulation provenance, ground-truth and label-mask columns.',
            'Fit encoders/scalers/imputers and any feature statistics using TRAIN only; VAL for tuning; TEST for final locked evaluation only.',
            'Define evaluation policy for original source attack/takeover flags; mask ambiguous negatives and report sensitivity.',
            'Separate experiment branches; do not pool replay variants as independent natural events or pool v1/v2.',
            'Treat original user IDs observed before anchor as eligible observed identities, not proof of account creation.',
        ],
        'limitations': [
            'The event-level credential_stuffing_label=0 for background means no injected credential-stuffing truth, NOT established benignness.',
            'Negative-eligibility flags are audit/evaluation masks, not model features.',
            'First-positive timestamps are derived only for event-label consistency; no node-label schedule was materialized.',
            'This audit does not inspect GraphSAGE feature-extraction or actual model inputs.',
            'The input is a TEST pilot; never tune models or preprocessing against these results.',
        ],
        'branches': branches,
        'preservation': 'All source datasets and earlier output directories were read-only.',
    }
    # Assemble reports first; never overwrite previous outputs.
    table_columns = ['variant_id','organization','background_events','synthetic_events',
                     'replay_events','clean_negative_candidates','ambiguous_background_events',
                     'distinct_positive_user_ids','first_positive_min','first_positive_max',
                     'status','failures','replay_sha256','background_digest_matches_prior','extra_columns']
    table = StringIO()
    writer = csv.DictWriter(table, fieldnames=table_columns)
    writer.writeheader()
    for b in branches:
        writer.writerow({k: json.dumps(b[k]) if isinstance(b[k],list) else b[k]
                         for k in table_columns})
    lines = [
        'CRED BLOCK-FL — PHASE 5 CONSOLIDATED DATA LABEL & LEAKAGE AUDIT',
        '=' * 70,
        f'STATUS: {outcome["status"]}',
        f'Branches passing data-level checks: {sum(r["status"]=="PASS_DATA_LEVEL" for r in branches)}/16',
        f'Event copies: {outcome["events_total"]:,} (synthetic {outcome["synthetic_event_copies"]:,}; background {outcome["background_event_copies"]:,})',
        f'Clean-negative background candidates: {outcome["clean_negative_candidates"]:,}',
        f'Ambiguous background copies (must not be treated as clean negatives): {outcome["ambiguous_background_event_copies"]:,}',
        'NOTE: Background credential label=0 does NOT certify benign source ground truth.',
        'NOT VERIFIED: node-label timing, GraphSAGE feature timing/allowlist, train-only preprocessing, TEST usage.',
        'SOURCE INPUTS: unchanged; no source Parquet, manifests, or replay data modified.',
        'PHASE 5 COMPLETE: NO; accept only within checked data-level scope.',
    ]
    report_dir.mkdir(exist_ok=True)
    texts = [json.dumps(outcome, indent=2), table.getvalue(), '\n'.join(lines)+'\n']
    staged = []
    try:
        for path, content in zip(outputs, texts):
            temp = path.with_name(path.name + '.incomplete')
            if temp.exists():
                raise FileExistsError(f'Incomplete prior report exists: {temp}')
            temp.write_text(content, encoding='utf-8')
            staged.append(temp)
        for temp, final in zip(staged, outputs):
            if final.exists():
                raise FileExistsError(f'Report exists: {final}')
            temp.rename(final)
    finally:
        for temp in staged:
            if temp.exists():
                temp.unlink()
    print('\n'+'\n'.join(lines))
    for p in outputs:
        print(p)
    return 0 if passed else 2


def smoke_tests():
    def row(ts, is_syn, **overrides):
        base = dict(organization='Org1', **{'Login Timestamp':ts, 'User ID':123,
              'IP Address':'192.0.2.1', 'LoginSuccessful':False,
              'is_synthetic':is_syn, 'credential_stuffing_label':1 if is_syn else 0,
              'scenario_id':'CS' if is_syn else None,
              'campaign_id':'V' if is_syn else None,
              'synthetic_credential_id':'C' if is_syn else None,
              'is_reused_credential':False if is_syn else None,
              'campaign_event_id':'CE' if is_syn else None,
              'replay_event_id':'SYN_V_CE' if is_syn else 'BG_Org1_0001',
              'source_is_attack_ip':None if is_syn else False,
              'source_is_account_takeover':None if is_syn else False,
              'clean_negative_eligible':False if is_syn else True})
        base.update(overrides)
        return base
    original = [row(ANCHOR+timedelta(minutes=1),False),
                row(ANCHOR+timedelta(minutes=2),True)]
    assert evaluate_rows(original,variant='V',org='Org1',expected_bg=1,expected_syn=1)['status']=='PASS_DATA_LEVEL'
    corrupt = [dict(r) for r in original]
    corrupt[1]['credential_stuffing_label'] = 0
    assert 'SYNTHETIC_GROUND_TRUTH' in evaluate_rows(corrupt,variant='V',org='Org1',expected_bg=1,expected_syn=1)['failures']
    corrupt = [dict(r) for r in original]
    corrupt[0]['source_is_attack_ip'] = True
    assert 'SOURCE_NEGATIVE_POLICY' in evaluate_rows(corrupt,variant='V',org='Org1',expected_bg=1,expected_syn=1)['failures']
    corrupt = [dict(r) for r in original]
    corrupt[1]['Login Timestamp'] = ANCHOR-timedelta(seconds=1)
    assert 'WINDOW_BOUNDARY' in evaluate_rows(corrupt,variant='V',org='Org1',expected_bg=1,expected_syn=1)['failures']
    print('SMOKE TESTS: PASS (valid, mislabeled, ambiguous-negative, past-timestamp)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(),
                        help='CredBlock-FL repository root, defaults to current folder')
    parser.add_argument('--self-test', action='store_true', help='Run pure-record smoke tests only')
    args = parser.parse_args()
    if args.self_test:
        smoke_tests()
        return 0
    print('CRED BLOCK-FL — PHASE 5 CONSOLIDATED LABEL/MASK/LEAKAGE AUDIT V2', flush=True)
    return run_audit(args.root.resolve())


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as ex:
        print(f'AUDIT STOPPED: {type(ex).__name__}: {ex}',file=sys.stderr)
        sys.exit(1)
