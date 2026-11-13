#!/usr/bin/env python3
"""CredBlock-FL Phase 5 — read-only target causal-eligibility audit v1.

Run from the CredBlock-FL repository root, in its existing virtual environment:
    python audit_phase5_target_causal_eligibility.py

Examines six immutable controlled-pilot variants and five original organization
Parquet datasets. The replay pilot summary is verified but replay Parquet files
are NEVER changed or regenerated. Examines user activity throughout the whole
source dataset relative to the common anchor (not only seven-day history).

CAUTION: Pre-anchor authentication activity is evidence an ID was observed,
not proof an account existed/was selectable. No activity before anchor is NOT
proof the account did not exist. The generator's query is audited separately.

Requires: duckdb. Outputs aggregate reports only, with no raw User IDs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE = 'phase5_target_causal_eligibility_v1'
EXPECTED_ANCHOR = datetime(2020, 12, 12, 6)
EXPECTED_VARIANTS = 6
EXPECTED_BRANCHES = 16
ORG_NAMES = [f'Org{x}' for x in range(1, 6)]


def digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as fh:
        for b in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def read_json(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def generator_evidence(root: Path):
    """Static source review; avoid pretending regex proves all possible runtime paths."""
    candidates = [root / 'credential_stuffing_generator.py',
                  root / 'src' / 'phase5' / 'credential_stuffing_generator.py',
                  root / 'src' / 'phase_5' / 'credential_stuffing_generator.py']
    for p in sorted([*root.glob('src/**/credential_stuffing_generator.py'), *root.glob('scripts/**/credential_stuffing_generator.py')]):
        if any(s in {'data', '.venv', 'venv', 'reports', '.git', '__pycache__'} for s in p.parts):
            continue
        if p not in candidates:
            candidates.append(p)
    source = next((p for p in candidates if p.is_file()), None)
    if source is None:
        return {'status': 'SOURCE_UNAVAILABLE_MANUAL_REVIEW_REQUIRED',
                'source_location': None, 'sha256': None,
                'finding': 'Generator code unavailable; cannot establish target selection process.'}, []
    lines = source.read_text(encoding='utf-8-sig').splitlines()
    code = '\n'.join(lines)
    match = re.search(r'^def select_local_users\s*\(.*?(?=^def\s|^class\s|\Z)',
                      code, re.M | re.S)
    cfg = re.search(r'^def select_campaign_target_users\s*\(.*?(?=^def\s|^class\s|\Z)',
                    code, re.M | re.S)
    if not match or not cfg:
        status = 'TARGET_SELECTION_LOGIC_NOT_LOCATED'
        finding = 'Function definitions not located; manual source review required.'
    else:
        body = match.group(0)
        call = cfg.group(0)
        has_full_source = bool(re.search(r'SELECT\s+DISTINCT\s+"User ID"', body, re.I))
        has_read_parquet = 'read_parquet(' in body
        invokes = 'select_local_users(' in call
        date_gate = bool(re.search(r'"Login Timestamp"\s*(?:<|<=|BETWEEN)|\b(?:campaign_start|anchor|cutoff|as_of|before_ts)\b', body, re.I))
        if has_full_source and has_read_parquet and invokes and not date_gate:
            status = 'FULL_PERIOD_USER_POOL_IN_GENERATOR_SOURCE'
            finding = ('select_campaign_target_users calls select_local_users, which selects distinct '
                       'User IDs from the full organization Parquet without a timestamp cutoff. '
                       'This is a future-informed *selection pool* design risk; the audit measures '
                       'actual selected IDs with no pre-anchor observations separately.')
        else:
            status = 'MANUAL_REVIEW_REQUIRED'
            finding = ('Static inspection did not establish the exact absence or presence of '
                       'a causal cutoff. Inspect selection path manually.')
    evidence = {'status': status, 'source_location': str(source.relative_to(root)),
                'sha256': digest(source), 'finding': finding,
                'select_local_users_first_line': code[:match.start()].count('\n') + 1 if match else None,
                'static_review_only': True}
    return evidence, [source]


def scan_org(con, files, target_users, anchor, hist_start):
    """For selected IDs only, scan source records and find full-history first/last.

    Entire Parquet is scanned to establish *absence* of any pre-anchor record.
    Target IDs stay inside the local in-memory SQL join and never appear in reports.
    """
    import duckdb  # dependency check on demand
    if not target_users:
        return {}
    values = [(str(uid),) for uid in sorted(target_users)]
    con.execute('CREATE OR REPLACE TEMP TABLE _target_uid (uid VARCHAR)')
    con.executemany('INSERT INTO _target_uid VALUES (?)', values)
    sql = '''SELECT t.uid,
                    MIN(CAST(s."Login Timestamp" AS TIMESTAMP)) first_seen,
                    MIN(CASE WHEN s."Login Timestamp" < ?
                             THEN CAST(s."Login Timestamp" AS TIMESTAMP) END) first_pre,
                    MAX(CASE WHEN s."Login Timestamp" < ?
                             THEN CAST(s."Login Timestamp" AS TIMESTAMP) END) last_pre,
                    SUM(CASE WHEN s."Login Timestamp" >= ? AND s."Login Timestamp" < ?
                             THEN 1 ELSE 0 END) AS seven_day_events,
                    SUM(CASE WHEN s."Login Timestamp" < ? THEN 1 ELSE 0 END) AS pre_events,
                    SUM(CASE WHEN s."Login Timestamp" >= ? THEN 1 ELSE 0 END) AS post_events
             FROM _target_uid t LEFT JOIN read_parquet(?) s
               ON CAST(s."User ID" AS VARCHAR) = t.uid
             GROUP BY t.uid'''
    rows = con.execute(sql, [anchor, anchor, hist_start, anchor, anchor, anchor, files]).fetchall()
    con.execute('DROP TABLE _target_uid')
    out = {}
    for uid, first, first_pre, last_pre, recent_count, pre_count, post_count in rows:
        pre_count = int(pre_count or 0)
        recent_count = int(recent_count or 0)
        post_count = int(post_count or 0)
        if recent_count > 0:
            status = 'OBSERVED_WITHIN_7D_PRE_ANCHOR'
        elif pre_count > 0:
            status = 'OBSERVED_EARLIER_THAN_7D_PRE_ANCHOR'
        elif post_count > 0:
            status = 'FIRST_OBSERVED_ON_OR_AFTER_ANCHOR'
        else:
            status = 'NEVER_OBSERVED_IN_ORG_SOURCE'
        out[uid] = {'status': status, 'pre_events': pre_count,
                    'recent_events': recent_count, 'post_events': post_count,
                    'first_seen': first, 'first_pre': first_pre, 'last_pre': last_pre}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='CredBlock-FL repository root')
    args = parser.parse_args()
    root = args.root.resolve()
    pilot_dir = root / 'data' / 'phase5' / 'controlled_pilot_v1'
    replay_dir = root / 'data' / 'phase5' / 'controlled_replay_pilot_v1'
    org_root = root / 'data' / 'organizations'
    reports_dir = root / 'reports'
    pilot_report = reports_dir / 'phase5_controlled_pilot_v1_summary.json'
    replay_report = reports_dir / 'phase5_controlled_replay_pilot_v1_summary.json'
    destinations = [reports_dir / f'{BASE}_summary.json',
                    reports_dir / f'{BASE}_branches.csv',
                    reports_dir / f'{BASE}_summary.txt']
    if any(p.exists() for p in destinations):
        raise FileExistsError('Existing causal-audit report found. Refusing overwrite; rename manually for a new version.')
    for path in [pilot_dir, replay_dir, org_root, pilot_report, replay_report]:
        if not path.exists():
            raise FileNotFoundError(path)
    pilot, replay = read_json(pilot_report), read_json(replay_report)
    if pilot.get('variants_generated') != EXPECTED_VARIANTS or pilot.get('status') != 'PASS_SYNTHETIC_PILOT_ONLY':
        raise ValueError('Pilot validation gate failed')
    if replay.get('status') != 'PASS_REPLAY_MECHANICS_CAUSAL_COHORT_NOT_PROVEN' or not replay.get('all_replay_integrity_checks_passed'):
        raise ValueError('Replay validation gate failed')
    if replay.get('six_variants') != EXPECTED_VARIANTS or replay.get('total_org_replays') != EXPECTED_BRANCHES:
        raise ValueError('Replay inventory unexpected')
    anchor = datetime.fromisoformat(replay['common_anchor'])
    if anchor != EXPECTED_ANCHOR or str(pilot.get('shared_anchor_candidate')) != anchor.isoformat():
        raise ValueError('Unexpected TEST common anchor')
    hist_start = anchor - timedelta(days=7)
    import duckdb
    con = duckdb.connect(':memory:')
    input_hashes = {str(pilot_report.relative_to(root)): digest(pilot_report),
                    str(replay_report.relative_to(root)): digest(replay_report)}
    evidence, code_files = generator_evidence(root)
    all_inputs = [pilot_report, replay_report, *code_files]
    expected_ids = {v['variant_id'] for v in pilot['results']}
    folders = sorted(p for p in pilot_dir.iterdir() if p.is_dir())
    if {p.name for p in folders} != expected_ids or len(folders) != EXPECTED_VARIANTS:
        raise ValueError('Pilot source folders disagree with validated summary')
    branch_targets = {}
    union_targets = defaultdict(set)
    branch_original_counts = {}
    for folder in folders:
        manifest_path = folder / 'manifest.json'
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        manifest = read_json(manifest_path)
        all_inputs.append(manifest_path)
        if manifest.get('variant_id') != folder.name or datetime.fromisoformat(manifest['campaign_start']) != anchor:
            raise ValueError(f'Invalid pilot manifest: {folder.name}')
        for org in manifest['targeted_organizations']:
            path = folder / f'{org}.parquet'
            if not path.is_file():
                raise FileNotFoundError(path)
            if digest(path) != manifest['generated_parquet_sha256'][path.name]:
                raise ValueError(f'Pilot Parquet hash mismatch: {path}')
            all_inputs.append(path)
            rows = con.execute('SELECT DISTINCT CAST("User ID" AS VARCHAR) FROM read_parquet(?) WHERE "User ID" IS NOT NULL', [str(path)]).fetchall()
            uidset = {r[0] for r in rows}
            if len(uidset) != int(manifest['target_users_per_organization'][org]):
                raise ValueError(f'Target cohort size mismatch: {folder.name}/{org}')
            branch_targets[(folder.name, org)] = uidset
            union_targets[org].update(uidset)
            branch_original_counts[(folder.name, org)] = len(uidset)
    if len(branch_targets) != EXPECTED_BRANCHES:
        raise ValueError(f'Expected {EXPECTED_BRANCHES} org branches, got {len(branch_targets)}')
    # Snapshot input digests BEFORE the expensive full-history scan.
    for org in ORG_NAMES:
        org_dir = org_root / f'organization={org}'
        all_inputs.extend(sorted(org_dir.glob('*.parquet')))
    input_hashes.update({str(p.relative_to(root)): digest(p) for p in all_inputs})
    source_observations = {}
    print('CRED BLOCK-FL — PHASE 5 TARGET CAUSAL ELIGIBILITY AUDIT V1')
    print(f'Anchor: {anchor.isoformat()} | preceding 7d: {hist_start.isoformat()}')
    print('Reading full organization source histories, aggregate classifications only ...')
    for org in ORG_NAMES:
        org_dir = org_root / f'organization={org}'
        paths = sorted(org_dir.glob('*.parquet'))
        if not paths:
            raise FileNotFoundError(f'No source Parquet for {org}')
        source_observations[org] = scan_org(con, [str(p) for p in paths], union_targets[org], anchor, hist_start)
        print(f'  {org}: {len(union_targets[org])} unique targeted IDs classified')
    per_branch = []
    total = Counter()
    unique_org_counts = Counter()
    for org in ORG_NAMES:
        unique_org_counts.update(s['status'] for s in source_observations[org].values())
    replay_checks = {(r['variant_id'], r['organization']): r for r in replay['per_org_checks']}
    if len(replay_checks) != EXPECTED_BRANCHES:
        raise ValueError('Replay report branch checks invalid')
    for (variant_id, org), users in sorted(branch_targets.items()):
        states = Counter(source_observations[org][u]['status'] for u in users)
        seven = states['OBSERVED_WITHIN_7D_PRE_ANCHOR']
        cold = len(users) - seven
        matching = replay_checks.get((variant_id, org))
        if matching is None or seven != int(matching['target_users_seen_in_7d']) or cold != int(matching['target_users_cold_start_7d']):
            raise ValueError(f'Preceding 7-day classification disagrees with replay report: {variant_id}/{org}')
        total.update(states)
        per_branch.append({'variant_id': variant_id, 'organization': org,
                           'target_occurrences': len(users),
                           'observed_within_prior_7d': seven,
                           'observed_earlier_than_7d': states['OBSERVED_EARLIER_THAN_7D_PRE_ANCHOR'],
                           'first_seen_at_or_after_anchor': states['FIRST_OBSERVED_ON_OR_AFTER_ANCHOR'],
                           'never_seen_in_org_source': states['NEVER_OBSERVED_IN_ORG_SOURCE'],
                           'with_pre_anchor_observation': seven + states['OBSERVED_EARLIER_THAN_7D_PRE_ANCHOR'],
                           'no_pre_anchor_observation': (states['FIRST_OBSERVED_ON_OR_AFTER_ANCHOR'] +
                                                         states['NEVER_OBSERVED_IN_ORG_SOURCE']),
                           'replay_history_match': True})
    for p in all_inputs:
        key = str(p.relative_to(root))
        after = digest(p)
        before = input_hashes[key]
        if before != after:
            raise ValueError(f'Input hash changed unexpectedly: {key}')
    totals = {'target_occurrences': sum(total.values()),
              'observed_within_prior_7d': total['OBSERVED_WITHIN_7D_PRE_ANCHOR'],
              'observed_earlier_than_7d': total['OBSERVED_EARLIER_THAN_7D_PRE_ANCHOR'],
              'first_seen_at_or_after_anchor': total['FIRST_OBSERVED_ON_OR_AFTER_ANCHOR'],
              'never_seen_in_org_source': total['NEVER_OBSERVED_IN_ORG_SOURCE']}
    totals['with_pre_anchor_observation'] = totals['observed_within_prior_7d'] + totals['observed_earlier_than_7d']
    totals['without_pre_anchor_observation'] = totals['first_seen_at_or_after_anchor'] + totals['never_seen_in_org_source']
    method = evidence['status']
    if method == 'FULL_PERIOD_USER_POOL_IN_GENERATOR_SOURCE':
        status = 'FUTURE_INFORMED_SELECTION_POOL_CONFIRMED_REQUIRES_CORRECTION'
    elif method == 'SOURCE_UNAVAILABLE_MANUAL_REVIEW_REQUIRED':
        status = 'INCONCLUSIVE_GENERATOR_SOURCE_NOT_AVAILABLE'
    else:
        status = 'INCONCLUSIVE_MANUAL_GENERATOR_REVIEW_REQUIRED'
    output = {
        'version': BASE, 'status': status, 'phase5_complete': False,
        'anchor': anchor.isoformat(), 'seven_day_history_start': hist_start.isoformat(),
        'pilot_variants': len(folders), 'organization_branches': len(per_branch),
        'generator_selection_source_review': evidence,
        'target_occurrence_totals': totals,
        'unique_target_user_organization_pairs': sum(len(v) for v in union_targets.values()),
        'unique_user_org_classifications': dict(unique_org_counts),
        'per_branch_aggregates': per_branch,
        'read_only_input_sha256': input_hashes,
        'interpretation': [
            'Pre-anchor login activity confirms prior observation of the User ID, not account creation time.',
            'No pre-anchor login is not proof that a user account was nonexistent or invalid.',
            'A generator pool drawn from full-period distinct IDs can use future information even if some selected IDs happened to be known before the anchor.',
            'Selecting only IDs seen in recent history would change the cold-start experimental distribution; do not silently filter or change original campaigns.',
            'Evidence from first/last observations must not be used to infer authorization or account creation time.',
            'No outputs modify original campaigns, controlled pilot variants, replay files, or organization source data.'
        ],
        'recommended_next_action': 'Develop causally timestamp-filtered selection policy as a new version; assess distributional impact and run a small pilot before any expansion.'
    }
    reports_dir.mkdir(exist_ok=True)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(per_branch[0]))
    writer.writeheader(); writer.writerows(per_branch)
    text = '\n'.join([
        'CRED BLOCK-FL — PHASE 5 CAUSAL TARGET ELIGIBILITY AUDIT V1',
        '=' * 67,
        f'STATUS: {status}',
        f'Source review: {evidence["status"]}',
        f'Generator finding: {evidence["finding"]}',
        f'Variants: {len(folders)} | local org branches: {len(per_branch)}',
        f'Target occurrences: {totals["target_occurrences"]}',
        f'Observed within preceding seven days: {totals["observed_within_prior_7d"]}',
        f'Observed earlier than preceding seven days: {totals["observed_earlier_than_7d"]}',
        f'First observed on/after anchor: {totals["first_seen_at_or_after_anchor"]}',
        f'Never observed in source: {totals["never_seen_in_org_source"]}',
        'These are authentication observations, not account creation records.',
        'Causally selected target cohorts are NOT established by this audit.',
        'Original campaigns, controlled variants, and replay branches not modified.'
    ]) + '\n'
    content = [json.dumps(output, indent=2, ensure_ascii=False) + '\n', stream.getvalue(), text]
    for path, content_item in zip(destinations, content):
        if path.exists():
            raise FileExistsError(path)
        path.write_text(content_item, encoding='utf-8')
    print('\n' + text)
    print('Reports:')
    for p in destinations: print(p)


if __name__ == '__main__':
    main()
