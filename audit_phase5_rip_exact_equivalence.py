"""CredBlock-FL Phase 5: exact RIP counterpart-equivalence audit (READ ONLY).

Run in the project root:
    python audit_phase5_rip_exact_equivalence.py

Requires duckdb (already used by Phase 5 scripts). Reads only the existing
270 split campaign manifests and their per-organization Parquet files.
Writes only:
    reports/phase5_rip_exact_equivalence_summary.json
    reports/phase5_rip_exact_equivalence_pairs.csv
    reports/phase5_rip_exact_equivalence_summary.txt

A PASS means matching synthetic behavioral events up to relative timestamp,
with RIP/IP variations and known scenario-dependent metadata ignored. It does
NOT validate background matching, timestamp rebasing, graph features/labels,
or the entire Phase 5 experiment. No campaigns are modified or regenerated.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

try:
    import duckdb
except ImportError as exc:
    raise SystemExit('Please install DuckDB in your existing .venv: pip install duckdb') from exc

FACTOR_VALUES = (0.2, 0.5, 0.8)
SPLITS = {'TRAIN', 'VAL', 'TEST'}
# Non-behavioral simulation metadata. Their literal values are campaign-specific.
METADATA_IGNORE = {'scenario_id', 'campaign_id', 'campaign_event_id'}
# The source IP is the *only* intended attacker-side behavioral difference.
IP_COLUMN = 'IP Address'
REQUIRED = {
    'organization', 'User ID', 'Login Timestamp', 'LoginSuccessful',
    'synthetic_credential_id', 'is_reused_credential', 'is_synthetic',
    'credential_stuffing_label', 'scenario_id', 'campaign_id',
    'campaign_event_id', IP_COLUMN,
}
PAIR_COLUMNS = [
    'campaign_a','campaign_b','split','seed','sorg','raccount','rip_a','rip_b',
    'organizations','events_a','events_b','identical_organizations',
    'identical_user_cohorts','identical_attempts_per_user',
    'identical_relative_timestamps','identical_login_outcomes',
    'identical_reuse_flags','identical_normalized_credential_mapping',
    'identical_non_ip_events','identical_event_id_suffixes',
    'unique_ips_a','unique_ips_b','measured_rip_a','measured_rip_b',
    'rip_rounded_target_a','rip_rounded_target_b',
    'ip_assignment_difference','ip_sets_disjoint','status','reason_codes',
    'diff_sample','manifest_sha256_a','manifest_sha256_b',
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def dt(s):
    return datetime.fromisoformat(str(s))


def path_inventory(root):
    campaign_dir = root / 'data' / 'phase5' / 'synthetic_events'
    if not campaign_dir.is_dir():
        raise FileNotFoundError(f'Campaigns folder missing: {campaign_dir}')
    campaigns, issues = {}, []
    for folder in sorted(campaign_dir.iterdir()):
        if not folder.is_dir() or not folder.name.endswith(('_TRAIN','_VAL','_TEST')):
            continue
        source = folder / 'manifest.json'
        try:
            data = json.loads(source.read_text(encoding='utf-8'))
            cid = data['campaign_id']
            split = str(data['split']).upper()
            seed = int(data['seed'])
            sorg = int(data['Sorg_target'])
            raccount = data.get('Raccount_target')
            raccount = None if raccount is None else round(float(raccount), 2)
            rip = round(float(data['RIP_target']), 2)
            orgs = tuple(sorted(data['targeted_organizations']))
            start, end = dt(data['campaign_start']), dt(data['campaign_end'])
            files = sorted(folder.glob('*.parquet'))
            if (cid != folder.name or split not in SPLITS or not start < end
                    or rip not in FACTOR_VALUES or sorg != len(orgs)
                    or not files or len({p.stem for p in files}) != len(files)
                    or any(p.stem not in orgs for p in files)
                    or set(p.stem for p in files) != set(orgs)
                    or (sorg == 1 and raccount is not None)
                    or (sorg > 1 and raccount not in FACTOR_VALUES)):
                raise ValueError('Invalid manifest ID/split/window/factors/Parquet inventory')
            if cid in campaigns:
                raise ValueError('Duplicate campaign ID')
            campaigns[cid] = {
                'id': cid, 'scenario': data['scenario_id'], 'seed': seed,
                'split': split, 'sorg': sorg, 'raccount': raccount,
                'rip': rip, 'orgs': orgs, 'start': start,
                'end': end, 'files': files, 'manifest': data,
                'manifest_sha256': sha256(source),
            }
        except Exception as exc:
            issues.append({'folder': str(folder), 'error': str(exc)})
    return campaigns, issues


def norm_credential(credential, campaign_id):
    """Remove only the prefix identifying the campaign, never credential identity."""
    s = str(credential)
    if not s.startswith(campaign_id):
        # Unknown format is deliberately retained, not blindly stripped.
        return f'UNRECOGNIZED:{s}'
    return s[len(campaign_id):]


def norm_event_id(event_id, campaign_id):
    match = re.fullmatch(re.escape(campaign_id) + r'_EVT_(\d+)', str(event_id))
    return int(match.group(1)) if match else f'UNRECOGNIZED:{event_id}'


def normalize_value(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec='microseconds')
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, bytes):
        return value.hex()
    return value


def load_events(db, campaign):
    """Read all campaign Parquet data without copying or changing the source."""
    files = [str(p) for p in campaign['files']]
    # Passing paths as DuckDB parameters avoids SQL quoting/path issues on Windows.
    cursor = db.execute('SELECT * FROM read_parquet(?)', [files])
    columns = [d[0] for d in cursor.description]
    if len(columns) != len(set(columns)) or not REQUIRED.issubset(columns):
        raise ValueError(f'Parquet schema mismatch; missing={sorted(REQUIRED-set(columns))}')
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cid = campaign['id']
    start, end = campaign['start'], campaign['end']
    orgs = campaign['orgs']
    event_sigs = Counter()
    cohort = defaultdict(set)
    attempts = Counter()
    outcomes = Counter()
    offsets = Counter()
    reuse_flags = Counter()
    cred_mapping = defaultdict(set)
    indexes = Counter()
    ip_by_event = defaultdict(list)
    ips = set()
    event_count_org = Counter()
    problem_samples = []
    for row in records:
        org, user, timestamp, ip = row['organization'], row['User ID'], row['Login Timestamp'], row[IP_COLUMN]
        if (org not in orgs or not isinstance(timestamp, datetime)
                or not (start <= timestamp < end)
                or str(row['campaign_id']) != cid
                or str(row['scenario_id']) != campaign['scenario']
                or row['is_synthetic'] is not True
                or row['credential_stuffing_label'] != 1
                or ip is None):
            raise ValueError(f'Unexpected synthetic event metadata in {cid}: {str(row)[:220]}')
        delta_us = (timestamp-start).days*86400000000 + (timestamp-start).seconds*1000000 + (timestamp-start).microseconds
        uid = (str(org), str(user))
        # Use the local identifier, not a purported cross-org identity match.
        credential = norm_credential(row['synthetic_credential_id'], cid)
        reused = bool(row['is_reused_credential'])
        success = bool(row['LoginSuccessful'])
        number = norm_event_id(row['campaign_event_id'], cid)
        if not isinstance(number, int):
            problem_samples.append(str(number)[:130])
        indexes[number] += 1
        ip_by_event[number].append(str(ip))
        cohort[str(org)].add(str(user))
        attempts[uid] += 1
        offsets[(uid, delta_us)] += 1
        outcomes[(uid, delta_us, success)] += 1
        reuse_flags[(uid, delta_us, reused)] += 1
        cred_mapping[(org, credential)].add(str(user))
        ips.add(str(ip))
        event_count_org[org] += 1
        # Explicit comparison of all other Parquet columns (future-safe).
        additional = tuple(sorted((k, normalize_value(v)) for k,v in row.items()
                                  if k not in REQUIRED and k not in METADATA_IGNORE))
        sig = (str(org), str(user), delta_us, success, credential, reused,
               bool(row['is_synthetic']), int(row['credential_stuffing_label']),
               number, additional)
        event_sigs[sig] += 1
    if len(records) != int(campaign['manifest']['total_events']):
        raise ValueError(f'Parquet vs manifest total count mismatch in {cid}')
    expected = {k:int(v) for k,v in campaign['manifest']['events_per_organization'].items()}
    if dict(event_count_org) != expected:
        raise ValueError(f'Parquet vs manifest per-org counts mismatch in {cid}')
    if len(indexes) != len(records) or any(x!=1 for x in indexes.values()):
        raise ValueError(f'Non-unique campaign_event_id indices in {cid}')
    if problem_samples:
        raise ValueError(f'Unexpected campaign_event_id format in {cid}: {problem_samples[:2]}')
    if any(x.startswith('UNRECOGNIZED:') for _,x in cred_mapping):
        raise ValueError(f'Unexpected credential ID format in {cid}')
    return {
        'n': len(records), 'orgs': orgs, 'cohort': {k:frozenset(v) for k,v in cohort.items()},
        'attempts': attempts, 'offsets': offsets, 'outcomes': outcomes,
        'reuse_flags': reuse_flags,
        'cred_mapping': {k:frozenset(v) for k,v in cred_mapping.items()},
        'event_sigs': event_sigs, 'index_counter': indexes,
        'ip_by_event': {k:tuple(v) for k,v in ip_by_event.items()},
        'ips': ips,
    }


def sample_difference(counter_a, counter_b):
    excess_a = counter_a - counter_b
    excess_b = counter_b - counter_a
    return {'a_only': [str(k)[:180] for k in list(excess_a.keys())[:2]],
            'b_only': [str(k)[:180] for k in list(excess_b.keys())[:2]]}


def compare_pair(a, b, x, y):
    checks = {
        'identical_organizations': x['orgs'] == y['orgs'],
        'identical_user_cohorts': x['cohort'] == y['cohort'],
        'identical_attempts_per_user': x['attempts'] == y['attempts'],
        'identical_relative_timestamps': x['offsets'] == y['offsets'],
        'identical_login_outcomes': x['outcomes'] == y['outcomes'],
        'identical_reuse_flags': x['reuse_flags'] == y['reuse_flags'],
        'identical_normalized_credential_mapping': x['cred_mapping'] == y['cred_mapping'],
        'identical_non_ip_events': x['event_sigs'] == y['event_sigs'],
        'identical_event_id_suffixes': x['index_counter'] == y['index_counter'],
    }
    # The intended RIP targets have integer rounding. Confirm observed unique-IP counts.
    na, nb = x['n'], y['n']
    ua, ub = len(x['ips']), len(y['ips'])
    target_a = max(1,min(na,round(na*a['rip']))) if na else 0
    target_b = max(1,min(nb,round(nb*b['rip']))) if nb else 0
    ip_diff = x['ip_by_event'] != y['ip_by_event']
    disjoint = not bool(x['ips'] & y['ips'])
    reasons = [k.upper()+'_MISMATCH' for k,v in checks.items() if not v]
    if not na or not nb:
        reasons.append('EMPTY_CAMPAIGN')
    if ua != target_a or ub != target_b:
        reasons.append('UNIQUE_IP_COUNT_DISAGREES_WITH_RIP_TARGET')
    if not ip_diff:
        reasons.append('IP_ASSIGNMENTS_IDENTICAL')
    if not disjoint:
        reasons.append('CROSS_CAMPAIGN_IP_OVERLAP')
    if a['rip'] == b['rip'] or a['sorg'] != b['sorg'] or a['raccount'] != b['raccount']:
        reasons.append('NOT_A_ONE_FACTOR_RIP_PAIR')
    if na != nb:
        reasons.append('ATTEMPT_COUNT_MISMATCH')
    status = 'PASS_SYNTHETIC_RIP_EQUIVALENCE' if not reasons else 'FAIL'
    diff = sample_difference(x['event_sigs'],y['event_sigs']) if not checks['identical_non_ip_events'] else {}
    return {
        'campaign_a': a['id'], 'campaign_b': b['id'],
        'split': a['split'], 'seed': a['seed'], 'sorg': a['sorg'],
        'raccount': a['raccount'], 'rip_a': a['rip'], 'rip_b': b['rip'],
        'organizations': ';'.join(a['orgs']), 'events_a': na, 'events_b': nb,
        **checks,
        'unique_ips_a': ua, 'unique_ips_b': ub,
        'measured_rip_a': round(ua/na,8) if na else None,
        'measured_rip_b': round(ub/nb,8) if nb else None,
        'rip_rounded_target_a': target_a, 'rip_rounded_target_b': target_b,
        'ip_assignment_difference': ip_diff, 'ip_sets_disjoint': disjoint,
        'status': status, 'reason_codes': reasons, 'diff_sample': diff,
        'manifest_sha256_a': a['manifest_sha256'],
        'manifest_sha256_b': b['manifest_sha256'],
    }


def write_csv(path, rows):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=PAIR_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k:(json.dumps(row[k],sort_keys=True)
                                if isinstance(row.get(k),(dict,list)) else row.get(k))
                             for k in PAIR_COLUMNS})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--output-dir',type=Path,default=None)
    args=parser.parse_args()
    root=args.project_root.resolve()
    report_dir=(args.output_dir or root/'reports').resolve()
    campaigns, inventory_errors=path_inventory(root)
    if inventory_errors:
        print(f'WARNING: {len(inventory_errors)} manifests/inventories could not be loaded.')
    print('CRED BLOCK-FL PHASE 5 — EXACT RIP EQUIVALENCE AUDIT')
    print(f'Campaigns loaded: {len(campaigns)} | Inventory errors: {len(inventory_errors)}')
    if not campaigns:
        raise SystemExit('No campaigns loaded: check --project-root')
    by_group=defaultdict(list)
    for item in campaigns.values():
        by_group[(item['split'],item['seed'],item['sorg'],item['raccount'],item['orgs'])].append(item)
    pairs=[]
    for group,items in sorted(by_group.items(),key=lambda kv:str(kv[0])):
        for a,b in combinations(sorted(items,key=lambda x:(x['rip'],x['id'])),2):
            if a['rip'] != b['rip']:
                pairs.append((a,b))
    # If source is otherwise valid, the current full design has exactly 270 RIP pairs.
    print(f'RIP pairs identified: {len(pairs)}')
    conn=duckdb.connect(database=':memory:',read_only=False)
    cache={}
    read_errors={}
    results=[]
    for i,(a,b) in enumerate(pairs,1):
        for item in (a,b):
            if item['id'] not in cache and item['id'] not in read_errors:
                try:
                    cache[item['id']]=load_events(conn,item)
                except Exception as exc:
                    read_errors[item['id']]=str(exc)
        if a['id'] in read_errors or b['id'] in read_errors:
            result={key:None for key in PAIR_COLUMNS}
            result.update(campaign_a=a['id'],campaign_b=b['id'],
                          split=a['split'],seed=a['seed'],sorg=a['sorg'],
                          raccount=a['raccount'],rip_a=a['rip'],rip_b=b['rip'],
                          organizations=';'.join(a['orgs']),status='ERROR',
                          reason_codes=['SOURCE_READ_OR_VALIDATION_ERROR'],
                          diff_sample={'a':read_errors.get(a['id']),
                                       'b':read_errors.get(b['id'])},
                          manifest_sha256_a=a['manifest_sha256'],
                          manifest_sha256_b=b['manifest_sha256'])
        else:
            result=compare_pair(a,b,cache[a['id']],cache[b['id']])
        results.append(result)
        if i % 50 == 0 or i == len(pairs):
            print(f'  Compared {i}/{len(pairs)} pairs')
    statuses=Counter(x['status'] for x in results)
    reasons=Counter(reason for x in results for reason in x['reason_codes'])
    summary={
        'audit': 'Phase 5 exact synthetic RIP counterpart-equivalence',
        'expected_campaigns':270,'campaigns_loaded':len(campaigns),
        'inventory_errors':inventory_errors,'expected_rip_pairs':270,
        'rip_pairs_found':len(pairs),'statuses':dict(statuses),
        'reason_counts':dict(reasons),'source_read_errors':read_errors,
        'note': 'PASS is limited to synthetic event equivalence except attacker IPs; background matching/replay/labels/leakage are NOT verified.',
        'criteria': {
            'RIP_pair_grouping': 'same seed, split, Sorg, Raccount, targeted organizations; RIP differs',
            'timestamp_comparison': 'exact microsecond offsets relative to each original campaign start',
            'metadata_normalization': 'strip campaign_id prefix from synthetic_credential_id and campaign_event_id',
            'behavioral_comparison': 'organization, user, event index, credential identity, reuse flag, offset, login outcome, and any additional non-IP columns',
            'IP_condition': 'unique IP counts agree with round(total_attempts*RIP), IP allocation differs and campaign IP sets are disjoint',
        },
        'output_warning': 'Never use simulated labels/IDs as model inputs. Do not modify the 270 original campaigns.',
    }
    report_dir.mkdir(parents=True,exist_ok=True)
    prefix='phase5_rip_exact_equivalence'
    report_json=report_dir/f'{prefix}_summary.json'
    report_csv=report_dir/f'{prefix}_pairs.csv'
    report_txt=report_dir/f'{prefix}_summary.txt'
    report_json.write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    write_csv(report_csv,results)
    lines=[
        'CRED BLOCK-FL — PHASE 5 EXACT RIP EQUIVALENCE AUDIT',
        '='*62,f'Campaigns: {len(campaigns)}/270',
        f'RIP pairs: {len(pairs)}/270',
        f'Pair statuses: {dict(statuses)}',
        f'Failure reasons: {dict(reasons)}',
        f'Manifest/inventory errors: {len(inventory_errors)}',
        f'Parquet read errors: {len(read_errors)}','',
        'Scope: compares actual synthetic events after normalizing campaign-relative timestamps and metadata.',
        'A pass does not prove matched original background, correct replays, labels, leakage prevention, or Phase 5 completion.','',
        'Reports:',str(report_json),str(report_csv),str(report_txt),
    ]
    report_txt.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('\n'.join(lines))
    # Non-zero status warns shell/CI if complete matching cannot be established.
    if len(campaigns)!=270 or len(pairs)!=270 or inventory_errors or read_errors or statuses.get('FAIL',0) or statuses.get('ERROR',0):
        raise SystemExit(1)

if __name__=='__main__':
    main()
