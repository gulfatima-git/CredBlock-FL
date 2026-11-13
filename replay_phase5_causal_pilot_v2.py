#!/usr/bin/env python3
"""CredBlock-FL Phase 5: isolated six-variant causal shared-background replay v2.

Run from repository root:
    python replay_phase5_causal_pilot_v2.py

Requires duckdb, pandas (already used by the Phase 5 generator).

INPUTS ARE IMMUTABLE. Never writes to data/organizations, data/phase5/synthetic_events,
or data/phase5/controlled_pilot_causal_v2. Creates only NEW versioned output:
    data/phase5/controlled_replay_causal_v2/
    reports/phase5_controlled_replay_causal_v2_{summary.json,org_checks.csv,summary.txt}

This verifies pre-anchor observed-ID selection and replay mechanics only.
It is NOT GraphSAGE feature validation, account-creation proof, or model readiness.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = 'controlled-replay-causal-v2'
EXPECTED_ANCHOR = datetime.fromisoformat('2020-12-12T06:00:00')
SPLIT_TEST_START = datetime.fromisoformat('2020-12-01T00:00:00')
SPLIT_TEST_END = datetime.fromisoformat('2021-03-01T00:00:00')
PILOT_VERSION = 'controlled-causal-selection-pilot-v2'
FIELDS = ['organization', 'Login Timestamp', 'User ID', 'IP Address',
          'LoginSuccessful', 'is_synthetic', 'credential_stuffing_label',
          'scenario_id', 'campaign_id', 'synthetic_credential_id',
          'is_reused_credential', 'campaign_event_id', 'replay_event_id',
          'source_is_attack_ip', 'source_is_account_takeover',
          'clean_negative_eligible']


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for buf in iter(lambda: f.read(1 << 20), b''):
            h.update(buf)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def canonical_hash(rows):
    """A stable digest of the *logical* records, independent of Parquet bytes."""
    h = hashlib.sha256()
    for row in rows:
        values = [v.isoformat(timespec='microseconds') if isinstance(v, datetime)
                  else v for v in row]
        h.update(json.dumps(values, default=str, ensure_ascii=False,
                            separators=(',', ':')).encode('utf-8'))
        h.update(b'\n')
    return h.hexdigest()


def q(name):
    return '"' + str(name).replace('"', '""') + '"'


def select_org_source(con, source_files, org, start, anchor, end):
    """Read ONLY a bounded seven-day history plus the common one-hour window."""
    files = [str(p) for p in source_files]
    colset = {d[0] for d in con.execute('DESCRIBE SELECT * FROM read_parquet(?)', [files]).fetchall()}
    required = {'Login Timestamp', 'User ID', 'IP Address',
                'Is Attack IP', 'Is Account Takeover'}
    if not required <= colset:
        raise ValueError(f'{org} missing source columns: {sorted(required - colset)}')
    success = 'LoginSuccessful' if 'LoginSuccessful' in colset else 'Login Successful'
    if success not in colset:
        raise ValueError(f'{org} missing login outcome column')
    # Prevent accidental non-local source loading: path is organization-scoped.
    sql = f'''SELECT CAST("Login Timestamp" AS TIMESTAMP),
                    CAST("User ID" AS BIGINT), CAST("IP Address" AS VARCHAR),
                    TRY_CAST({q(success)} AS BOOLEAN),
                    TRY_CAST("Is Attack IP" AS BOOLEAN),
                    TRY_CAST("Is Account Takeover" AS BOOLEAN)
              FROM read_parquet(?)
              WHERE "Login Timestamp" >= ? AND "Login Timestamp" < ?
              ORDER BY 1, 2, 3, 4, 5, 6'''
    rows = con.execute(sql, [files, start, end]).fetchall()
    if not rows:
        raise ValueError(f'No background/history source records found: {org}')
    if any(r[0] is None or r[1] is None or r[2] is None or r[3] is None for r in rows):
        raise ValueError(f'{org} source rows contain null required values; cannot replay safely')
    history = [r for r in rows if r[0] < anchor]
    window = [r for r in rows if r[0] >= anchor]
    if not history or not window:
        raise ValueError(f'{org}: history or one-hour source background empty')
    # Distinguish evidence of activity from a proof of complete source coverage.
    active_hours = len({int((r[0] - start).total_seconds() // 3600) for r in history})
    history_users = {str(r[1]) for r in history}
    source_ambiguous = sum((r[4] is not False or r[5] is not False) for r in window)
    return history, window, history_users, active_hours, source_ambiguous


def preanchor_user_ids(con, files, anchor):
    # Strictly earlier authentication observations, not the last seven days only.
    # Query is organization-local and does not expose identifiers in output reports.
    rows = con.execute('''SELECT DISTINCT CAST("User ID" AS VARCHAR)
                           FROM read_parquet(?)
                           WHERE CAST("Login Timestamp" AS TIMESTAMP) < ?
                             AND "User ID" IS NOT NULL''',
                       [[str(p) for p in files], anchor]).fetchall()
    return {r[0] for r in rows if r[0] is not None}


def load_variant(con, path, manifest, anchor, end):
    orgs = list(manifest['targeted_organizations'])
    if len(orgs) != int(manifest['Sorg_actual']):
        raise ValueError(f'{path.name} Sorg mismatch')
    if datetime.fromisoformat(manifest['campaign_start']) != anchor:
        raise ValueError(f'{path.name} anchor mismatch')
    if datetime.fromisoformat(manifest['campaign_end']) != end:
        raise ValueError(f'{path.name} end mismatch')
    parquets = [path / f'{org}.parquet' for org in orgs]
    if any(not p.is_file() for p in parquets):
        raise FileNotFoundError(f'{path.name}: missing variant Parquet')
    expected_hashes = {f'{org}.parquet': h for org, h in manifest.get('event_parquet_sha256', {}).items()}
    if set(expected_hashes) != {p.name for p in parquets}:
        raise ValueError(f'{path.name}: incomplete Parquet hashes in manifest')
    for p in parquets:
        if sha256(p) != expected_hashes[p.name]:
            raise ValueError(f'{path.name}: input Parquet hash mismatch: {p.name}')
    cols = {r[0] for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',
                                     [[str(p) for p in parquets]]).fetchall()}
    required = set(FIELDS[:12]) - {'replay_event_id'}
    if not required <= cols:
        raise ValueError(f'{path.name}: synthetic columns missing: {sorted(required-cols)}')
    sql = '''SELECT CAST(organization AS VARCHAR),
                    CAST("Login Timestamp" AS TIMESTAMP),
                    CAST("User ID" AS BIGINT), CAST("IP Address" AS VARCHAR),
                    CAST(LoginSuccessful AS BOOLEAN), CAST(is_synthetic AS BOOLEAN),
                    CAST(credential_stuffing_label AS INTEGER),
                    CAST(scenario_id AS VARCHAR), CAST(campaign_id AS VARCHAR),
                    CAST(synthetic_credential_id AS VARCHAR),
                    CAST(is_reused_credential AS BOOLEAN), CAST(campaign_event_id AS VARCHAR)
             FROM read_parquet(?) ORDER BY 2, 1, 3, 12'''
    rows = con.execute(sql, [[str(p) for p in parquets]]).fetchall()
    if len(rows) != int(manifest['total_events']):
        raise ValueError(f'{path.name}: total event count mismatch')
    counts = Counter(r[0] for r in rows)
    if counts != Counter({str(k): int(v) for k,v in manifest['events_per_organization'].items()}):
        raise ValueError(f'{path.name}: per-organization event count mismatch')
    if any(r[0] not in orgs or not anchor <= r[1] < end or r[5] is not True or
           r[6] != 1 or r[8] != manifest['variant_id'] or r[3] is None or
           r[2] is None or r[11] is None for r in rows):
        raise ValueError(f'{path.name}: inconsistent synthetic event records')
    if len({r[11] for r in rows}) != len(rows):
        raise ValueError(f'{path.name}: duplicated synthetic event IDs')
    return rows, parquets


def source_background_record(org, ordinal, row):
    ts, uid, ip, success, attack, takeover = row
    # Null source flags => ambiguous for clean-negative evaluation.
    eligible = (attack is False and takeover is False)
    return (org, ts, uid, ip, success, False, 0, None, None, None,
            None, None, f'BG_{org}_{ordinal:012d}', attack, takeover, eligible)


def synthetic_replay_record(variant_id, r):
    return (*r, f'SYN_{variant_id}_{r[11]}', None, None, False)


def write_parquet(con, path, data):
    import pandas as pd
    frame = pd.DataFrame(data, columns=FIELDS)
    con.register('rows_export', frame)
    try:
        # The destination is constructed internally and never user-provided SQL.
        con.execute(f"COPY rows_export TO '{str(path).replace(chr(39), chr(39)*2)}' (FORMAT PARQUET)")
    finally:
        con.unregister('rows_export')


def atomic_reports(reports, contents):
    for target in reports:
        if target.exists():
            raise FileExistsError(f'Report already exists; refusing overwrite: {target}')
    temp_paths = []
    try:
        for target, content in zip(reports, contents):
            temp = target.with_name(target.name + '.incomplete')
            if temp.exists():
                raise FileExistsError(f'Incomplete report exists: {temp}')
            temp.write_text(content, encoding='utf-8')
            temp_paths.append(temp)
        for temp, target in zip(temp_paths, reports):
            temp.rename(target)
    finally:
        for temp in temp_paths:
            if temp.exists():
                temp.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='CredBlock-FL repository root')
    args = parser.parse_args()
    root = args.root.resolve()
    input_dir = (root / 'data/phase5/controlled_pilot_causal_v2').resolve()
    org_dir = (root / 'data/organizations').resolve()
    originals = (root / 'data/phase5/synthetic_events').resolve()
    output = (root / 'data/phase5/controlled_replay_causal_v2').resolve()
    reports_dir = (root / 'reports').resolve()
    reports = [reports_dir / ('phase5_controlled_replay_causal_v2_' + s)
               for s in ('summary.json', 'org_checks.csv', 'summary.txt')]
    if any(p.exists() for p in [output, *reports]):
        raise FileExistsError('Replay output or report already exists; refusing to overwrite')
    if not input_dir.is_dir() or not org_dir.is_dir() or not originals.is_dir():
        raise FileNotFoundError('Missing pilot data, organization background or original campaign directory')
    summary_path = reports_dir / 'phase5_causal_selection_pilot_v2_summary.json'
    if not summary_path.is_file():
        raise FileNotFoundError(summary_path)
    pilot = read_json(summary_path)
    if pilot.get('status') != 'PASS_CAUSAL_SELECTION_PILOT_ONLY' or pilot.get('pilot_variants') != 6 or pilot.get('organization_branches') != 16 or pilot.get('corrected_target_occurrences_with_pre_anchor_observation') != 890:
        raise ValueError('Controlled pilot synthetic input acceptance gate not satisfied')
    if str(pilot.get('anchor')) != EXPECTED_ANCHOR.isoformat():
        raise ValueError('Unexpected anchor; do not silently change experimental schedule')
    end = EXPECTED_ANCHOR + timedelta(hours=1)
    hist_start = EXPECTED_ANCHOR - timedelta(days=7)
    if not SPLIT_TEST_START <= EXPECTED_ANCHOR < end <= SPLIT_TEST_END:
        raise ValueError('Anchor violates TEST split')
    # History is permitted to cross an earlier split as *past context*, never for training on TEST labels.
    expected_variants = {r['variant_id'] for r in pilot['variant_results']}
    folders = sorted(p for p in input_dir.iterdir() if p.is_dir())
    if len(folders) != 6 or {p.name for p in folders} != expected_variants:
        raise ValueError('Pilot folders inconsistent with six-variant summary')
    import duckdb
    con = duckdb.connect(':memory:')
    source_hashes = {str(summary_path): sha256(summary_path)}
    source_records = {}
    source_files = {}
    print('CRED BLOCK-FL — PHASE 5 ISOLATED CAUSAL SHARED-BACKGROUND REPLAY PILOT V2')
    print(f'Anchor: {EXPECTED_ANCHOR.isoformat()} | history: {hist_start.isoformat()}')
    for org in [f'Org{i}' for i in range(1,6)]:
        folder = org_dir / f'organization={org}'
        paths = sorted(folder.rglob('*.parquet')) if folder.is_dir() else []
        if not paths:
            raise FileNotFoundError(f'{org}: no background Parquet files')
        source_files[org] = paths
        print(f'  Reading local source records: {org} ...', flush=True)
        source_records[org] = select_org_source(con, paths, org, hist_start,
                                                 EXPECTED_ANCHOR, end)
        hist, window, users, hours, ambiguous = source_records[org]
        print(f'    history={len(hist):,} | background={len(window):,} | active-hours={hours}/168 | ambiguous={ambiguous:,}')
        # Source Parquet checksums retained for reproducibility; never copied to outputs.
        for p in paths:
            source_hashes[str(p)] = sha256(p)
    # The verified v1 replay used the same unmodified source data and anchor.
    baseline_path = reports_dir / 'phase5_controlled_replay_pilot_v1_summary.json'
    if not baseline_path.is_file():
        raise FileNotFoundError('v1 replay baseline report required to verify identical background')
    baseline = read_json(baseline_path)
    if not baseline.get('all_replay_integrity_checks_passed') or baseline.get('common_anchor') != EXPECTED_ANCHOR.isoformat():
        raise ValueError('v1 replay baseline acceptance gate not satisfied')
    source_hashes[str(baseline_path)] = sha256(baseline_path)
    observed_pre_anchor = {}
    for org in source_records:
        observed_pre_anchor[org] = preanchor_user_ids(con, source_files[org], EXPECTED_ANCHOR)
    if not all(observed_pre_anchor.values()):
        raise ValueError('At least one organization has no pre-anchor observed users')
    variants = []
    all_target_user_checks = []
    for folder in folders:
        manifest_file = folder / 'manifest.json'
        if not manifest_file.is_file():
            raise FileNotFoundError(manifest_file)
        manifest = read_json(manifest_file)
        if manifest.get('schema_version') != PILOT_VERSION or manifest.get('variant_id') != folder.name:
            raise ValueError(f'Pilot manifest inconsistent: {folder.name}')
        rows, inputs = load_variant(con, folder, manifest, EXPECTED_ANCHOR, end)
        if manifest.get('target_selection_policy') != 'STRICTLY_PRE_ANCHOR_OBSERVED_IDS_FROM_SOURCE_AUTHENTICATION':
            raise ValueError(f'{folder.name}: missing causal selection policy in manifest')
        if manifest.get('causal_target_selection_corrected') is not True:
            raise ValueError(f'{folder.name}: corrected causal selection flag not verified')
        if not manifest.get('checks') or not all(manifest['checks'].values()):
            raise ValueError(f'{folder.name}: causal generator acceptance checks not all PASS')
        for org in manifest['targeted_organizations']:
            targeted = {str(r[2]) for r in rows if r[0] == org}
            absent = targeted - observed_pre_anchor[org]
            if absent:
                raise ValueError(f'{folder.name}/{org}: {len(absent)} IDs not observed before anchor; refusing replay')
        source_hashes[str(manifest_file)] = sha256(manifest_file)
        for p in inputs:
            source_hashes[str(p)] = sha256(p)
        per_org = defaultdict(list)
        for row in rows:
            per_org[row[0]].append(row)
        for org, events in per_org.items():
            target_users = {str(r[2]) for r in events}
            earlier = source_records[org][2]
            seen = target_users & earlier
            unseen = target_users - earlier
            all_target_user_checks.append(dict(variant_id=folder.name, organization=org,
                                               targeted_users=len(target_users),
                                               observed_prior_7d=len(seen),
                                               cold_start_users=len(unseen)))
        variants.append((folder, manifest, rows, per_org))
        print(f'  Loaded {folder.name}: {len(rows)} synthetic events, {len(per_org)} orgs')
    # Check corrected cohort against source authentication IDs strictly before anchor.
    # This proves prior observation, not account creation or absence of other leakage.
    # The same in-memory per-org background records are re-used in ALL six branches.
    source_bg = {org: [source_background_record(org, i, r)
                       for i, r in enumerate(source_records[org][1], 1)]
                 for org in source_records}
    source_history = {org: [source_background_record(org, i, r)
                            for i, r in enumerate(source_records[org][0], 1)]
                      for org in source_records}
    bg_digest = {org: canonical_hash(source_bg[org]) for org in source_bg}
    baseline_digests = baseline.get('common_background_digests', {})
    for org in bg_digest:
        if baseline_digests.get(org) != bg_digest[org]:
            raise ValueError(f'{org}: shared background differs from validated v1 replay')
    temp = output.with_name(output.name + '.incomplete')
    if temp.exists():
        raise FileExistsError(f'Incomplete replay output exists: {temp}')
    if any(p.exists() for p in reports):
        raise FileExistsError('Refusing to overwrite earlier replay reports')
    temp.mkdir(parents=True)
    results = []
    try:
        history_dir = temp / 'shared_history_7d'
        history_dir.mkdir()
        for org, events in source_history.items():
            write_parquet(con, history_dir / f'{org}.parquet', events)
        for folder, manifest, rows, by_org in variants:
            branch_dir = temp / folder.name
            branch_dir.mkdir()
            for org in sorted(by_org):
                background = source_bg[org]
                synthetic = [synthetic_replay_record(folder.name, r) for r in by_org[org]]
                combined = sorted(background + synthetic,
                                  key=lambda r: (r[1], r[5], r[2], r[3], r[12]))
                ids = [r[12] for r in combined]
                expected_n = len(background) + len(synthetic)
                checks = {
                    'exact_event_conservation': len(combined) == expected_n,
                    'synthetic_event_conservation': sum(r[5] for r in combined) == len(synthetic),
                    'source_event_conservation': sum(not r[5] for r in combined) == len(background),
                    'unique_replay_ids': len(ids) == len(set(ids)),
                    'timestamp_monotonic': all(combined[i][1] <= combined[i+1][1]
                                               for i in range(len(combined)-1)),
                    'within_common_window': all(EXPECTED_ANCHOR <= r[1] < end for r in combined),
                    'org_local_only': all(r[0] == org for r in combined),
                    'exact_common_background': canonical_hash([r for r in combined if not r[5]]) == bg_digest[org],
                    'pre_anchor_observed_target_ids': {str(r[2]) for r in by_org[org]} <= observed_pre_anchor[org],
                    'no_synthetic_clean_negative': all(not r[15] for r in combined if r[5]),
                    'source_flags_not_synthetic_labels': all(r[6] == 0 for r in combined if not r[5]),
                }
                if not all(checks.values()):
                    raise ValueError(f'Replay integrity failed: {folder.name}/{org}: {checks}')
                out_file = branch_dir / f'{org}.parquet'
                write_parquet(con, out_file, combined)
                actual_count, actual_synth, distinct_ids = con.execute('''
                    SELECT COUNT(*), SUM(CASE WHEN is_synthetic THEN 1 ELSE 0 END),
                           COUNT(DISTINCT replay_event_id) FROM read_parquet(?)''',
                    [str(out_file)]).fetchone()
                if (actual_count, actual_synth, distinct_ids) != (expected_n, len(synthetic), expected_n):
                    raise ValueError(f'Parquet post-write verification failed: {out_file}')
                _, _, previous_users, active_hours, source_flagged = source_records[org]
                targeted = {str(r[2]) for r in by_org[org]}
                results.append({
                    'variant_id': folder.name, 'family': manifest['family'],
                    'organization': org, 'background_events': len(background),
                    'synthetic_events': len(synthetic), 'replay_events': len(combined),
                    'background_digest': bg_digest[org],
                    'targeted_users': len(targeted),
                    'target_users_seen_in_7d': len(targeted & previous_users),
                    'target_users_seen_before_anchor': len(targeted & observed_pre_anchor[org]),
                    'target_users_cold_start_7d': len(targeted-previous_users),
                    'history_events_7d': len(source_history[org]),
                    'history_active_hours': active_hours,
                    'source_ambiguous_flagged_background': source_flagged,
                    'clean_negative_background_events': len(background)-source_flagged,
                    'checks_passed': all(checks.values()),
                    'replayed_parquet_sha256': sha256(out_file),
                })
            (branch_dir / 'replay_manifest.json').write_text(json.dumps({
                'version': VERSION, 'variant_id': folder.name,
                'synthetic_source_manifest_sha256': source_hashes[str(folder/'manifest.json')],
                'anchor': EXPECTED_ANCHOR.isoformat(), 'end': end.isoformat(),
                'background_policy': 'identical per-org source window, isolated replay',
                'background_digests': {org:bg_digest[org] for org in by_org},
                'shared_history_dir': '../shared_history_7d',
                'validation_scope': 'causal pre-anchor observed-ID selection + replay mechanics only; graph features/labels unverified',
                'pre_anchor_auth_observation_verified': True,
                'model_input_warning': 'DO NOT pass label/flags/synthetic IDs to model',
            }, indent=2), encoding='utf-8')
        # Enforce same background digest in every branch that targets that org.
        digests = defaultdict(set)
        for r in results:
            digests[r['organization']].add(r['background_digest'])
        if any(len(v) != 1 for v in digests.values()):
            raise ValueError('Background changed across experimental branches')
        if sum(r['targeted_users'] for r in results) != int(pilot['total_target_occurrences']):
            raise ValueError('Target occurrences do not match accepted v2 pilot')
        if sum(r['target_users_seen_before_anchor'] for r in results) != int(pilot['corrected_target_occurrences_with_pre_anchor_observation']):
            raise ValueError('Target eligibility count does not match v2 acceptance summary')
        manifest = {
            'version': VERSION,
            'status': 'PASS_CAUSAL_V2_REPLAY_MECHANICS_ONLY',
            'phase5_complete': False,
            'six_variants': len(variants), 'total_org_replays': len(results),
            'common_anchor': EXPECTED_ANCHOR.isoformat(),
            'history_start': hist_start.isoformat(),
            'history_end_exclusive': EXPECTED_ANCHOR.isoformat(),
            'background_window_end_exclusive': end.isoformat(),
            'all_replay_integrity_checks_passed': all(r['checks_passed'] for r in results),
            'common_background_digests': bg_digest,
            'source_input_sha256': source_hashes,
            'baseline_v1_background_digests_verified': True,
            'all_targeted_user_ids_observed_before_anchor': True,
            'selection_policy': 'STRICTLY_PRE_ANCHOR_OBSERVED_IDS_FROM_SOURCE_AUTHENTICATION',
            'per_org_checks': results,
            'total_target_occurrences_without_7d_history': sum(r['target_users_cold_start_7d'] for r in results),
            'unresolved_gates': [
                'Pre-anchor observed-ID selection verified, but account creation and generator process causality are not proven solely by login evidence',
                'Source history hourly activity does not prove completeness of all historical data',
                'Original source attack/takeover flags are ambiguous negatives, not credential-stuffing labels',
                'No causal feature extraction / graph label onset-expiry or model leakage audit performed',
                'This TEST pilot must not be used for hyperparameter tuning or selecting a model',
                'No TEST model selection or training has been performed',
                'Sorg and Raccount still change cohort/organization composition by design',
                'Cross-version synthetic IP assignments intentionally coincide as part of held-fixed attack behavior; versions must not be pooled',
            ],
            'preservation': 'No original, v1 pilot/replay, v2 pilot, or organization source file was written',
        }
        (temp / 'replay_index.json').write_text(json.dumps(manifest, indent=2),encoding='utf-8')
        # Full source integrity re-check, including all local background input Parquet.
        for path, expected_hash in source_hashes.items():
            if sha256(path) != expected_hash:
                raise RuntimeError(f'INPUT CHANGED during replay: {path}')
        # Atomic expose only after all branches/outputs and inputs validated.
        temp.rename(output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    reports_dir.mkdir(exist_ok=True)
    table_fields = list(results[0])
    from io import StringIO
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=table_fields)
    writer.writeheader()
    writer.writerows(results)
    summary = '\n'.join([
        'CRED BLOCK-FL — PHASE 5 SHARED-BACKGROUND REPLAY PILOT V2',
        '='*67,
        'STATUS: PASS_CAUSAL_V2_REPLAY_MECHANICS_ONLY',
        f'Six variants replayed: {len(variants)}; local organization branches: {len(results)}',
        f'Anchor: {EXPECTED_ANCHOR.isoformat()}; 7-day history starts: {hist_start.isoformat()}',
        f'Total source background event copies across branches: {sum(r["background_events"] for r in results):,}',
        f'Total synthetic event copies: {sum(r["synthetic_events"] for r in results):,}',
        f'Seven-day cold-start targeted account occurrences: {sum(r["target_users_cold_start_7d"] for r in results)}',
        'All replay integrity checks: PASS',
        'All corrected target IDs observed before anchor: PASS',
        'Background parity with validated v1 replay: PASS',
        'Verified: every corrected target User ID is present in pre-anchor authentication records.',
        'IMPORTANT: Label/masking/graph-feature temporal leakage is NOT yet validated.',
        'All original campaigns, v1 pilots/replays, and v2 pilot sources modified: 0',
        f'Output: {output}',
        ''])
    atomic_reports(reports, [json.dumps(manifest, indent=2), sio.getvalue(), summary])
    print('\n' + summary)
    for p in reports: print(p)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'REPLAY STOPPED: {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
