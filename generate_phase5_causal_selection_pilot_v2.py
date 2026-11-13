#!/usr/bin/env python3
"""CredBlock-FL Phase 5: strictly versioned causal target-selection pilot v2.

Run from the repo root in the existing .venv:
    python generate_phase5_causal_selection_pilot_v2.py

Creates six *attack-only* controlled variants in a NEW directory. Each User ID
comes exclusively from source authentication rows whose timestamp is earlier
than the common attack anchor. All other attack-event attributes are copied
from the six validated pilot-v1 sources (except campaign-scoped identifiers).

No original campaigns, pilot-v1 variants, replay-v1 branches, or source datasets
are modified. Output is never silently overwritten. This is NOT a replay,
model-training dataset, proof of account creation time, nor causal-effect study.

Dependencies in your current .venv: duckdb, pandas.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = 'controlled-causal-selection-pilot-v2'
BASE = 'phase5_causal_selection_pilot_v2'
EXPECTED = {'CPV1_RA_CS_004_SEED1001_TEST', 'CPV1_RA_CS_013_SEED1001_TEST',
            'CPV1_RA_CS_014_SEED1001_TEST', 'CPV1_SO_CS_004_SEED1001_TEST',
            'CPV1_SO_CS_019_SEED1001_TEST', 'CPV1_SO_CS_025_SEED1001_TEST'}
SPLIT_END = datetime(2021, 3, 1)
SPLIT_START = datetime(2020, 12, 1)
REQUIRED = {'organization', 'User ID', 'Login Timestamp', 'LoginSuccessful',
            'synthetic_credential_id', 'campaign_event_id', 'campaign_id',
            'is_reused_credential', 'IP Address'}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def as_dt(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=None) if v.tzinfo else v
    return datetime.fromisoformat(str(v))


def stable_seed(*values):
    return int.from_bytes(hashlib.sha256('|'.join(map(str, values)).encode()).digest()[:8], 'big')


def escape_sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def assert_new_output(root: Path, output: Path, report_files):
    if output.exists() or output.with_name(output.name + '.incomplete').exists():
        raise FileExistsError(f'New output already exists or is incomplete: {output}')
    forbidden = [root / 'data' / 'organizations',
                 root / 'data' / 'phase5' / 'synthetic_events',
                 root / 'data' / 'phase5' / 'controlled_pilot_v1',
                 root / 'data' / 'phase5' / 'controlled_replay_pilot_v1']
    if root not in output.parents or any(output == p or p in output.parents or output in p.parents for p in forbidden):
        raise ValueError(f'Output must be a NEW sibling directory inside repository: {output}')
    if any(p.exists() for p in report_files):
        raise FileExistsError('A v2 report already exists; refusing overwrite: ' +
                              ', '.join(str(p) for p in report_files if p.exists()))


def read_events(db, path: Path):
    cursor = db.execute('SELECT * FROM read_parquet(?)', [str(path)])
    cols = [c[0] for c in cursor.description]
    if not REQUIRED <= set(cols):
        raise ValueError(f'Missing event fields in {path}: {sorted(REQUIRED - set(cols))}')
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def eligible_pre_anchor(db, org_file: Path, anchor: datetime, history_start: datetime):
    # Strictly timestamp-bound query: no future rows contribute to candidate identities.
    # Also count recent activity to assess resulting 7-day cold-start distribution.
    rows = db.execute('''
        SELECT CAST("User ID" AS VARCHAR) AS uid,
               MAX(CASE WHEN CAST("Login Timestamp" AS TIMESTAMP) >= ?
                        THEN 1 ELSE 0 END) AS in_recent_history
        FROM read_parquet(?)
        WHERE CAST("Login Timestamp" AS TIMESTAMP) < ?
          AND "User ID" IS NOT NULL
        GROUP BY CAST("User ID" AS VARCHAR)
        ORDER BY uid
    ''', [history_start, str(org_file), anchor]).fetchall()
    out = {}
    for uid, recent in rows:
        if uid is not None and uid != '':
            out[str(uid)] = bool(recent)
    return out


def credential_key(variant_id: str, record: dict):
    prefix = variant_id + '_CRED_'
    raw = str(record['synthetic_credential_id'])
    if not raw.startswith(prefix):
        raise ValueError(f'Source credential does not match manifest: {raw}')
    return raw[len(prefix):]


def record_event_suffix(variant_id: str, record: dict):
    prefix = variant_id + '_EVT_'
    raw = str(record['campaign_event_id'])
    if not raw.startswith(prefix):
        raise ValueError(f'Source event ID does not match manifest: {raw}')
    return raw[len(prefix):]


def load_input_pilots(db, root: Path, pilot_summary):
    base = root / 'data' / 'phase5' / 'controlled_pilot_v1'
    ids = set()
    loaded = []
    for rec in pilot_summary['results']:
        vid = rec['variant_id']
        if vid in ids or vid not in EXPECTED:
            raise ValueError(f'Unexpected/duplicate pilot variant: {vid}')
        ids.add(vid)
        folder = base / vid
        manifest_path = folder / 'manifest.json'
        manifest = read_json(manifest_path)
        orgs = manifest['targeted_organizations']
        if manifest['variant_id'] != vid or not orgs or len(orgs) != manifest['Sorg_actual']:
            raise ValueError(f'Bad pilot manifest: {vid}')
        if manifest['split'] != 'TEST' or int(manifest['seed']) != 1001:
            raise ValueError(f'Unexpected split/seed: {vid}')
        rows_by_org = {}
        for org in orgs:
            path = folder / (org + '.parquet')
            records = read_events(db, path)
            if not records or any(str(x['organization']) != org or str(x['campaign_id']) != vid for x in records):
                raise ValueError(f'Invalid source rows in {path}')
            rows_by_org[org] = records
        if sum(len(x) for x in rows_by_org.values()) != int(manifest['total_events']):
            raise ValueError(f'Pilot source total mismatch: {vid}')
        loaded.append((vid, manifest, manifest_path, rows_by_org))
    if ids != EXPECTED or len(loaded) != 6:
        raise ValueError('Expected all and only the six original pilot variants')
    return loaded


def build_mapping(loaded, pools, anchor):
    """Consistent org+credential->User ID map shared across all six variants.

    For a given organization, the SAME synthetic credential identity gets the
    SAME new local user across both experiment families; ensures user uniqueness
    across credentials and reproducibility. Distinct organizations have
    independent selection pools, preserving non-IID local user partitions.
    """
    requirements = defaultdict(set)
    source_per_org_key = defaultdict(set)
    for vid, m, _, by_org in loaded:
        for org, rows in by_org.items():
            local = defaultdict(set)
            for r in rows:
                key = credential_key(vid, r)
                local[key].add(str(r['User ID']))
                requirements[org].add(key)
                source_per_org_key[(org, vid, key)].add(str(r['User ID']))
            if any(len(v) != 1 for v in local.values()):
                raise ValueError(f'Source credential maps to multiple users in {vid}/{org}')
            if len(local) != int(m['target_users_per_organization'][org]):
                raise ValueError(f'Source user-cohort count mismatch in {vid}/{org}')
            if len({next(iter(uids)) for uids in local.values()}) != len(local):
                raise ValueError(f'Not a one-to-one source credential mapping: {vid}/{org}')
    mapping = {}
    for org, keys in sorted(requirements.items()):
        available = sorted(pools[org])
        if len(available) < len(keys):
            raise ValueError(f'Insufficient pre-anchor observed user IDs in {org}: '
                             f'{len(available)} eligible, {len(keys)} needed. Fail closed.')
        random.Random(stable_seed(VERSION, 'observed-pre-anchor', org, anchor.isoformat())).shuffle(available)
        mapping[org] = dict(zip(sorted(keys), available[:len(keys)]))
    return mapping, source_per_org_key


def validate_factor_equivalence(rows_by_org, src_m, new_m):
    events = [r for records in rows_by_org.values() for r in records]
    n = len(events)
    orgs = list(src_m['targeted_organizations'])
    cred = defaultdict(set)
    usercounts = defaultdict(Counter)
    for r in events:
        key = str(r['synthetic_credential_id'])
        cred[key].add(str(r['organization']))
        usercounts[str(r['organization'])][str(r['User ID'])] += 1
    reused = sum(len(orgs) == len(v) for v in cred.values()) if len(orgs) > 1 else 0
    checks = {
        'same_event_total': n == int(src_m['total_events']),
        'same_org_coverage': set(rows_by_org) == set(orgs),
        'same_per_org_attempt_budgets': all(len(rows_by_org[o]) == int(src_m['events_per_organization'][o]) for o in orgs),
        'same_per_org_user_counts': all(len(usercounts[o]) == int(src_m['target_users_per_organization'][o]) for o in orgs),
        'one_to_three_per_user': all(1 <= k <= 3 for c in usercounts.values() for k in c.values()),
        'same_number_credential_identities': len(cred) == 100,
        'same_cross_org_reuse_count': reused == int(src_m['reused_credential_count']),
        'same_rip': len({str(r['IP Address']) for r in events}) == round(n * float(src_m['RIP_target'])),
        'same_sorg': len(orgs) == int(src_m['Sorg_target']),
        'all_timestamps_in_anchor': all(as_dt(src_m['campaign_start']) <= as_dt(r['Login Timestamp']) < as_dt(src_m['campaign_end']) for r in events),
        'no_duplicate_campaign_event_ids': len({str(r['campaign_event_id']) for r in events}) == n,
        'no_missing_user_ids': all(r['User ID'] is not None and str(r['User ID']) != '' for r in events),
    }
    if not all(checks.values()):
        raise ValueError(f'Corrected variant failed: {new_m}: {checks}')
    return checks


def write_parquet(db, dest, records):
    import pandas as pd
    df = pd.DataFrame.from_records(records)
    db.register('_rows_to_write_causal_v2', df)
    try:
        db.execute(f"COPY _rows_to_write_causal_v2 TO '{escape_sql_path(dest)}' (FORMAT PARQUET)")
    finally:
        db.unregister('_rows_to_write_causal_v2')
    verify = db.execute('SELECT COUNT(*) FROM read_parquet(?)', [str(dest)]).fetchone()[0]
    if verify != len(records):
        raise ValueError(f'Parquet round-trip count mismatch: {dest}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / 'data' / 'phase5' / 'controlled_pilot_causal_v2'
    reports = root / 'reports'
    files_out = [reports / (BASE + '_summary.json'),
                 reports / (BASE + '_branches.csv'),
                 reports / (BASE + '_summary.txt')]
    assert_new_output(root, output, files_out)

    import duckdb
    db = duckdb.connect(':memory:')
    summary_path = reports / 'phase5_controlled_pilot_v1_summary.json'
    replay_path = reports / 'phase5_controlled_replay_pilot_v1_summary.json'
    causal_path = reports / 'phase5_target_causal_eligibility_v1_summary.json'
    required_reports = [summary_path, replay_path, causal_path]
    for p in required_reports:
        if not p.is_file():
            raise FileNotFoundError(f'Missing prior audit: {p}')
    pilot_summary = read_json(summary_path)
    replay_summary = read_json(replay_path)
    causal_summary = read_json(causal_path)
    if (pilot_summary.get('status') != 'PASS_SYNTHETIC_PILOT_ONLY'
        or replay_summary.get('status') != 'PASS_REPLAY_MECHANICS_CAUSAL_COHORT_NOT_PROVEN'
        or causal_summary.get('status') != 'FUTURE_INFORMED_SELECTION_POOL_CONFIRMED_REQUIRES_CORRECTION'):
        raise ValueError('Upstream report status gate not met')
    if pilot_summary.get('variants_generated') != 6 or causal_summary.get('organization_branches') != 16:
        raise ValueError('Upstream pilot count gate not met')
    anchor = as_dt(replay_summary['common_anchor'])
    if anchor != as_dt(pilot_summary['shared_anchor_candidate']) or anchor != as_dt(causal_summary['anchor']):
        raise ValueError('Anchor discrepancy across reports')
    if not SPLIT_START <= anchor < anchor + timedelta(hours=1) <= SPLIT_END:
        raise ValueError('Anchor not inside TEST split')
    history_start = anchor - timedelta(days=7)
    loaded = load_input_pilots(db, root, pilot_summary)
    expected_files = [*required_reports]
    for _, _, manifest_p, by_org in loaded:
        expected_files.append(manifest_p)
        expected_files.extend(manifest_p.parent / (o + '.parquet') for o in by_org)

    # Verify original pilot inputs against the hashes established by the read-only audit.
    stored = causal_summary.get('read_only_input_sha256', {})
    for p in expected_files:
        rel = str(p.relative_to(root)).replace('/', '\\')
        if rel in stored and sha256(p) != stored[rel]:
            raise ValueError(f'Original input differs from causal audit: {p}')
    baseline = {str(p): sha256(p) for p in expected_files}
    source_files = {}
    orgs = sorted(set().union(*(set(by_org) for _, _, _, by_org in loaded)))
    pools = {}
    print('CRED BLOCK-FL — PHASE 5 CAUSAL SELECTION PILOT V2')
    print(f'Anchor: {anchor.isoformat()} | pre-anchor eligibility: entire source history < anchor')
    for org in orgs:
        f = root / 'data' / 'organizations' / f'organization={org}' / 'data_0.parquet'
        if not f.is_file():
            raise FileNotFoundError(f)
        source_files[org] = f
        baseline[str(f)] = sha256(f)
        pools[org] = eligible_pre_anchor(db, f, anchor, history_start)
        print(f'  {org}: {len(pools[org])} distinct IDs observed before anchor')
    mapping, _ = build_mapping(loaded, pools, anchor)

    tmp = output.with_name(output.name + '.incomplete')
    branches = []
    variant_summaries = []
    written = []
    total_old_pre = total_new_pre = total_new_recent = 0
    try:
        tmp.mkdir(parents=True, exist_ok=False)
        for vid, old_m, src_mpath, by_org in loaded:
            new_vid = vid.replace('CPV1_', 'CPV2_', 1)
            dst_dir = tmp / new_vid
            dst_dir.mkdir()
            start = as_dt(old_m['campaign_start'])
            if start != anchor:
                raise ValueError(f'Variant anchor differs from verified replay: {vid}')
            transformed = {}
            per_org_stats = {}
            new_source_m = dict(old_m)
            new_source_m.update({
                'schema_version': VERSION, 'variant_id': new_vid,
                'source_pilot_variant_id': vid,
                'source_manifest_sha256': sha256(src_mpath),
                'target_selection_policy': 'STRICTLY_PRE_ANCHOR_OBSERVED_IDS_FROM_SOURCE_AUTHENTICATION',
                'eligibility_timestamp_exclusive': anchor.isoformat(),
                'cohort_selection_uses_only_timestamp_and_user_id': True,
                'causal_target_selection_corrected': True,
                'background_replayed': False,
                'input_causal_audit_sha256': sha256(causal_path),
                'limitations': [
                    'No source account-creation records: observed ID is not proof of account creation time',
                    'Historical authentication cohort excludes truly unobserved legitimate accounts by design',
                    'Original source factors can change cohort composition and per-user attempt rates',
                    'IP addresses reused across isolated experimental VERSIONS to hold attack behavior fixed',
                    'Synthetic labels and campaign identifiers are forbidden model input features',
                    'Causally selected candidates do not establish absence of other label/feature leakage',
                    'Attack-only pilot: shared-background replay must be regenerated as a new version',
                ],
            })
            # Preserve the original target counts / per-user attempt distributions exactly.
            for org, rows in by_org.items():
                before_cohort = {str(r['User ID']) for r in rows}
                old_pre = len(before_cohort & pools[org].keys())
                replacements = mapping[org]
                new_rows = []
                for row in rows:
                    key = credential_key(vid, row)
                    candidate = replacements[key]
                    if candidate not in pools[org]:
                        raise ValueError(f'Future/unobserved candidate assigned in {new_vid}/{org}')
                    copy = dict(row)
                    copy['User ID'] = candidate
                    copy['campaign_id'] = new_vid
                    copy['synthetic_credential_id'] = new_vid + '_CRED_' + key
                    copy['campaign_event_id'] = new_vid + '_EVT_' + record_event_suffix(vid, row)
                    new_rows.append(copy)
                old_t = Counter((credential_key(vid, r), str(r['IP Address']), as_dt(r['Login Timestamp']),
                                 str(r['LoginSuccessful']), str(r['is_reused_credential'])) for r in rows)
                new_t = Counter((credential_key(new_vid, r), str(r['IP Address']), as_dt(r['Login Timestamp']),
                                 str(r['LoginSuccessful']), str(r['is_reused_credential'])) for r in new_rows)
                if old_t != new_t:
                    raise ValueError(f'Behavioral events changed unexpectedly: {new_vid}/{org}')
                new_users = {str(r['User ID']) for r in new_rows}
                if len(new_users) != len(before_cohort):
                    raise ValueError(f'Cohort size changed in {new_vid}/{org}')
                recent = sum(bool(pools[org][uid]) for uid in new_users)
                output_parquet = dst_dir / f'{org}.parquet'
                write_parquet(db, output_parquet, new_rows)
                written.append(output_parquet)
                transformed[org] = new_rows
                per_org_stats[org] = {
                    'eligible_pool_size': len(pools[org]),
                    'old_target_users': len(before_cohort),
                    'old_observed_before_anchor': old_pre,
                    'old_no_pre_anchor_observation': len(before_cohort) - old_pre,
                    'new_target_users': len(new_users),
                    'new_observed_before_anchor': len(new_users),
                    'new_recent_7d': recent,
                    'new_cold_start_7d': len(new_users) - recent,
                    'retained_user_ids_from_old': len(new_users & before_cohort),
                    'synthetic_events': len(new_rows),
                }
                total_old_pre += old_pre
                total_new_pre += len(new_users)
                total_new_recent += recent
                branches.append({'variant_id': new_vid, 'source_variant_id': vid,
                                 'organization': org, **per_org_stats[org],
                                 'status': 'PASS_CAUSAL_SELECTION'})
            checks = validate_factor_equivalence(transformed, old_m, new_vid)
            new_source_m['checks'] = checks
            new_source_m['causal_selection_by_organization'] = per_org_stats
            new_source_m['event_parquet_sha256'] = {o: sha256(dst_dir / (o + '.parquet')) for o in transformed}
            (dst_dir / 'manifest.json').write_text(json.dumps(new_source_m, indent=2, default=str) + '\n', encoding='utf-8')
            variant_summaries.append({'variant_id': new_vid, 'source_variant_id': vid,
                                      'family': old_m['family'], 'Sorg': old_m['Sorg_target'],
                                      'RIP': old_m['RIP_target'], 'Raccount': old_m['Raccount_target'],
                                      'events': old_m['total_events'], 'checks': checks,
                                      'status': 'PASS_CAUSAL_SELECTION'})
            print(f'  {new_vid}: {old_m["total_events"]} events | {len(by_org)} orgs — PASS')
        if len(branches) != 16 or len(variant_summaries) != 6:
            raise ValueError(f'Unexpected branch/variant totals {len(branches)}/{len(variant_summaries)}')
        if total_new_pre != 890:
            raise ValueError(f'Target occurrences changed: expected 890, got {total_new_pre}')
        if total_old_pre != 764:
            raise ValueError(f'Pilot baseline differs from causal eligibility audit: expected 764, got {total_old_pre}')
        if any(sha256(Path(p)) != h for p, h in baseline.items()):
            raise ValueError('Input integrity changed; refuse to commit corrected pilot')
        # Commit only after every variant passes; never mutate original/source directories.
        tmp.rename(output)
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp)
        raise

    summary = {
        'version': VERSION, 'status': 'PASS_CAUSAL_SELECTION_PILOT_ONLY',
        'phase5_complete': False, 'model_ready': False, 'replay_ready': False,
        'anchor': anchor.isoformat(), 'history_start': history_start.isoformat(),
        'target_selection_policy': 'IDs OBSERVED IN SOURCE AUTH LOGS STRICTLY BEFORE ANCHOR',
        'pilot_variants': len(variant_summaries), 'organization_branches': len(branches),
        'total_target_occurrences': total_new_pre,
        'original_target_occurrences_with_pre_anchor_observation': total_old_pre,
        'original_target_occurrences_with_no_pre_anchor_observation': 890 - total_old_pre,
        'corrected_target_occurrences_with_pre_anchor_observation': total_new_pre,
        'corrected_target_occurrences_with_last_7d_observation': total_new_recent,
        'corrected_target_occurrences_cold_start_7d': total_new_pre - total_new_recent,
        'source_sha256': {str(Path(p).relative_to(root)): h for p, h in baseline.items()},
        'source_pilot_summary_sha256': sha256(summary_path),
        'source_causal_audit_sha256': sha256(causal_path),
        'variant_results': variant_summaries,
        'branch_results': branches,
        'output_dir': str(output),
        'untouched': ['270 original synthetic campaigns', 'six controlled pilot v1 variants',
                      'six shared-background replay v1 variants', 'five original organization source datasets'],
        'limitations': ['Causal pre-anchor OBSERVATION is established for selection, not account creation time',
                        'No unseen-account subpopulation is simulated in this corrected policy',
                        'No matched-background replay of v2 generated yet',
                        'No graph-feature leakage/label onset-expiry validation yet',
                        'Raccount and Sorg comparisons still contain design-driven changes'],
    }
    reports.mkdir(parents=True, exist_ok=True)
    # Refuse existing report writes, even if they appeared while generation was running.
    if any(p.exists() for p in files_out):
        raise FileExistsError('Pilot generated but report destination now exists; do not overwrite: ' + str(files_out))
    files_out[0].write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    with files_out[1].open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(branches[0]))
        writer.writeheader()
        writer.writerows(branches)
    digest_text = '\n'.join([
        'CRED BLOCK-FL — PHASE 5 CAUSAL SELECTION PILOT V2', '=' * 62,
        'STATUS: PASS_CAUSAL_SELECTION_PILOT_ONLY',
        'New attack-only variants: 6; local org branches: 16',
        f'Anchor: {anchor.isoformat()}; eligible pool: all local User IDs observed earlier',
        'Original pilot target occurrences observed before anchor: 764/890',
        'Original pilot target occurrences without prior observation: 126/890',
        f'Corrected target occurrences observed before anchor: {total_new_pre}/890',
        f'Corrected target occurrences cold in prior seven days: {total_new_pre-total_new_recent}/890',
        'Event behavior, attack time, factor settings, outcomes, credentials and IPs preserved.',
        'All input sources untouched. New data not yet replayed; no label/feature leakage validation.',
        f'Output: {output}', '',
    ])
    files_out[2].write_text(digest_text, encoding='utf-8')
    print('\n' + digest_text)
    print('Reports:')
    for p in files_out:
        print(p)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'CAUSAL PILOT V2 FAILED: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)
