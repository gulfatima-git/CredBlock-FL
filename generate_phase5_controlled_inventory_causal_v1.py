#!/usr/bin/env python3
"""Generate the complete causal controlled inventory, preserving all prior files.

From project root: python generate_phase5_controlled_inventory_causal_v1.py
Tests only: python generate_phase5_controlled_inventory_causal_v1.py --self-test
Requires existing DuckDB/Pandas. New output only; no overwrite or resume.
Attack-only generation is NOT background replay, graph validation, or Phase 5 acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import ipaddress
import json
from pathlib import Path
import random
import sys
import unittest

VERSION = 'controlled-inventory-causal-v1'
SPLITS = {'TRAIN': (datetime(2020, 2, 3), datetime(2020, 10, 1)),
          'VAL': (datetime(2020, 10, 1), datetime(2020, 12, 1)),
          'TEST': (datetime(2020, 12, 1), datetime(2021, 3, 1))}
FIELDS = ['organization', 'User ID', 'Login Timestamp', 'LoginSuccessful',
          'synthetic_credential_id', 'is_reused_credential', 'is_synthetic',
          'credential_stuffing_label', 'scenario_id', 'campaign_id',
          'IP Address', 'campaign_event_id']
NETWORK = ipaddress.ip_network('198.18.0.0/15')


def require(test, message):
    if not test:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def seed_for(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str, parts)).encode()).digest()[:8], 'big')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, default=str)
        f.write('\n')


def write_parquet(db, path, rows):
    import pandas as pd
    db.register('inventory_export', pd.DataFrame(rows, columns=FIELDS))
    try:
        escaped = str(path).replace("'", "''")
        db.execute("COPY inventory_export TO '" + escaped + "' (FORMAT PARQUET)")
    finally:
        db.unregister('inventory_export')
    require(db.execute('SELECT count(*) FROM read_parquet(?)', [str(path)]).fetchone()[0] == len(rows),
            'Parquet roundtrip count mismatch')


def flatten_recipes(document, manifests):
    require(document['raccount_recipe_count'] == 81 and document['sorg_recipe_count'] == 81,
            'Unexpected recipe inventory')
    jobs = []
    for recipe in document['recipes']:
        family = recipe['family']
        require(family in ['Raccount_fixed_per_org_attempts', 'Sorg_fixed_per_org_attempts'], 'Unknown family')
        for v in recipe['variants']:
            cid = v['source_campaign']
            m = manifests[cid]
            orgs = list(v.get('organizations', recipe.get('organizations', [])))
            counts, budgets = list(v['target_users_per_org']), list(v['attempts_per_org'])
            ra = float(v.get('raccount', recipe.get('raccount', 0)))
            rip = float(recipe['rip_target'])
            prefix = 'RA' if family.startswith('Raccount') else 'SO'
            # Recipes deliberately canonicalize org order; budgets and credential
            # counts follow THAT order. Source manifests may list the same set in
            # another order (notably seed1002). Do not realign recipe vectors.
            require(set(m['targeted_organizations']) == set(orgs),
                    'Recipe/source organization membership discrepancy: ' + cid)
            require(m['RIP_target'] == rip and m['Raccount_target'] == ra and m['Sorg_target'] == len(orgs),
                    'Recipe/source factor discrepancy')
            require(m['split'].upper() == recipe['split'] and m['seed'] == recipe['seed'], 'Split/seed discrepancy')
            require(len(orgs) == len(counts) == len(budgets) == len(v['user_attempt_allocation_per_org']),
                    'Recipe vector length mismatch')
            job = {'variant_id': 'CFV1_' + prefix + '_' + cid, 'source_campaign_id': cid,
                'recipe_id': recipe['recipe_id'], 'family': family, 'split': recipe['split'],
                'seed': int(recipe['seed']), 'organizations': orgs, 'target_counts': counts,
                'budgets': budgets, 'allocations': v['user_attempt_allocation_per_org'],
                'raccount': ra, 'rip': rip, 'reference_only': False}
            require(sum(budgets) == int(v.get('total_attempts', recipe.get('budget_total_attempts', sum(budgets)))),
                    'Recipe total budget mismatch')
            jobs.append(job)
    for ref in document['source_sorg1_references']:
        cid, split = ref['campaign_id'], ref['split']
        m = manifests[cid]
        require(m['Sorg_target'] == 1 and m['Raccount_target'] is None, 'Sorg1 reference has reuse factor')
        jobs.append({'variant_id': 'CFV1_REF_' + cid, 'source_campaign_id': cid,
            'recipe_id': 'REF_' + cid, 'family': 'Sorg1_descriptive_reference',
            'split': split, 'seed': int(ref['seed']), 'organizations': list(m['targeted_organizations']),
            'target_counts': [100], 'budgets': [int(m['total_events'])],
            'allocations': None, 'raccount': None, 'rip': float(ref['rip']), 'reference_only': True})
    require(len(jobs) == 513 and len({x['variant_id'] for x in jobs}) == 513, 'Expected 513 unique instances')
    require(Counter(x['split'] for x in jobs) == {'TRAIN': 171, 'VAL': 171, 'TEST': 171}, 'Split inventory mismatch')
    require(sum(len(j['organizations']) for j in jobs) == 1647, 'Expected 1647 organization branches')
    return sorted(jobs, key=lambda j: (list(SPLITS).index(j['split']), j['seed'], j['variant_id']))


def group_key(job):
    # Match attack behavior across RIP levels for controlled families. References
    # retain their own original event templates and are descriptive, not RIP pairs.
    if job['reference_only']:
        return job['variant_id']
    return '|'.join(map(str, [job['split'], job['seed'], job['family'],
                            len(job['organizations']), job['raccount']]))


def cohorts(job):
    reused = 0 if job['raccount'] is None else round(100 * job['raccount'])
    next_private = reused + 1
    out = {}
    for org, n in zip(job['organizations'], job['target_counts']):
        require(n >= reused, 'Cohort smaller than reused-credential count')
        private_count = n - reused
        out[org] = [(k, True) for k in range(1, reused + 1)] + [
            (k, False) for k in range(next_private, next_private + private_count)]
        next_private += private_count
    require(next_private == 101, 'Credential allocation does not produce 100 identities')
    return out


def attempt_counts(n, allocation, rng):
    nums = sum(([k] * int(allocation[name]) for k, name in
                [(1, 'one_attempt_users'), (2, 'two_attempt_users'), (3, 'three_attempt_users')]), [])
    require(len(nums) == n and sum(nums) == allocation['total_attempts'], 'Invalid attempt-allocation recipe')
    rng.shuffle(nums)
    return nums


def candidate_pool(db, files, anchor):
    # This WHERE clause is the causal selection boundary. Future source records
    # contribute neither candidate identities nor recent-activity statistics.
    return db.execute('''SELECT CAST("User ID" AS BIGINT) AS uid,
                     MAX(CAST("Login Timestamp" AS TIMESTAMP)) AS latest_prior_observation
                     FROM read_parquet(?)
                     WHERE CAST("Login Timestamp" AS TIMESTAMP) < ? AND "User ID" IS NOT NULL
                     GROUP BY CAST("User ID" AS BIGINT) ORDER BY uid''',
                      [[str(f) for f in files], anchor]).fetchall()


def select_mapping(pool, org, split, seed, anchor):
    require(len(pool) >= 100, 'Insufficient strictly pre-anchor observed users in ' + org)
    selected = random.Random(seed_for(VERSION, 'cohort', split, seed, org, anchor)).sample(pool, 100)
    require(all(t < anchor for uid, t in selected), 'Future-informed user selected')
    return {k: (uid, t) for k, (uid, t) in enumerate(selected, 1)}


def assign_ips(rows, addresses, rip, key):
    needed = round(len(rows) * rip)
    require(1 <= needed <= len(addresses), 'IP namespace allocation insufficient')
    rng = random.Random(seed_for(VERSION, key, rip, 'ip-assignment'))
    use = list(addresses[:needed])
    assignments = use + [rng.choice(use) for _ in range(len(rows) - needed)]
    rng.shuffle(assignments)
    for row, address in zip(rows, assignments):
        row['IP Address'] = address


def generate(job, mapping, anchor, addresses, reference_rows=None, reference_manifest=None):
    vid, rows = job['variant_id'], []
    if job['reference_only']:
        require(reference_rows is not None and reference_manifest is not None, 'Missing reference template')
        original_start = datetime.fromisoformat(reference_manifest['campaign_start'])
        cid = job['source_campaign_id']
        for source in reference_rows:
            credential = int(str(source['synthetic_credential_id']).removeprefix(cid + '_CRED_'))
            org = source['organization']
            offset = source['Login Timestamp'] - original_start
            require(timedelta(0) <= offset < timedelta(hours=1), 'Reference event outside original hour')
            rows.append({'organization': org, 'User ID': mapping[org][credential][0],
                'Login Timestamp': anchor + offset, 'LoginSuccessful': bool(source['LoginSuccessful']),
                'synthetic_credential_id': f'{vid}_CRED_{credential:03d}',
                'is_reused_credential': False})
    else:
        rng = random.Random(seed_for(VERSION, group_key(job), 'events'))
        for i, (org, entries) in enumerate(cohorts(job).items()):
            nums = attempt_counts(len(entries), job['allocations'][i], rng)
            for (credential, reused), n in zip(entries, nums):
                for _ in range(n):
                    rows.append({'organization': org, 'User ID': mapping[org][credential][0],
                        'Login Timestamp': anchor + timedelta(microseconds=rng.randrange(3600 * 10**6)),
                        'LoginSuccessful': rng.random() < 0.05,
                        'synthetic_credential_id': f'{vid}_CRED_{credential:03d}',
                        'is_reused_credential': reused})
    rows.sort(key=lambda r: (r['Login Timestamp'], r['organization'], r['synthetic_credential_id']))
    assign_ips(rows, addresses, job['rip'], group_key(job))
    for i, row in enumerate(rows, 1):
        row.update(is_synthetic=True, credential_stuffing_label=1,
                   scenario_id=job['source_campaign_id'].split('_SEED')[0],
                   campaign_id=vid, campaign_event_id=f'{vid}_EVT_{i:06d}')
    return rows


def behavior_digest(rows, vid):
    values = [(r['organization'], r['User ID'], r['Login Timestamp'].isoformat(),
               r['LoginSuccessful'], r['synthetic_credential_id'].removeprefix(vid + '_CRED_'),
               r['is_reused_credential']) for r in rows]
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def validate(rows, job, mapping, anchor):
    vid, orgs = job['variant_id'], job['organizations']
    end = anchor + timedelta(hours=1)
    lo, hi = SPLITS[job['split']]
    require(lo <= anchor < end <= hi and anchor - timedelta(days=7) >= SPLITS['TRAIN'][0],
            'Attack crosses split or history predates source coverage')
    require(len(rows) == sum(job['budgets']), 'Event budget mismatch')
    require(Counter(r['organization'] for r in rows) == dict(zip(orgs, job['budgets'])), 'Per-org budget mismatch')
    credential_orgs, users = defaultdict(set), defaultdict(set)
    attempts = Counter()
    for r in rows:
        org = r['organization']
        k = int(r['synthetic_credential_id'].removeprefix(vid + '_CRED_'))
        uid, evidence_time = mapping[org][k]
        require(r['User ID'] == uid and evidence_time < anchor, 'Invalid causal cohort assignment')
        require(anchor <= r['Login Timestamp'] < end, 'Attack outside replay interval')
        require(r['is_synthetic'] is True and r['credential_stuffing_label'] == 1, 'Invalid truth')
        credential_orgs[k].add(org)
        users[org].add(uid)
        attempts[(org, uid)] += 1
    require(len(credential_orgs) == 100, 'Expected 100 credential identities')
    require([len(users[o]) for o in orgs] == job['target_counts'], 'Target coverage mismatch')
    require(all(1 <= n <= 3 for n in attempts.values()), 'Outside 1-3 attempts per user')
    require(all(len(os) in (1, len(orgs)) for os in credential_orgs.values()), 'Partial credential sharing')
    reused = sum(len(os) > 1 for os in credential_orgs.values())
    expected_reused = 0 if job['raccount'] is None else round(100 * job['raccount'])
    require(reused == expected_reused, 'Cross-organization reuse mismatch')
    require(all(r['is_reused_credential'] is (len(credential_orgs[int(
        r['synthetic_credential_id'].removeprefix(vid + '_CRED_'))]) > 1) for r in rows), 'Reuse-flag mismatch')
    require(len({r['IP Address'] for r in rows}) == round(len(rows) * job['rip']), 'IP rotation mismatch')
    require(len({r['campaign_event_id'] for r in rows}) == len(rows), 'Duplicate event IDs')
    for i, org in enumerate(orgs):
        if job['allocations'] is not None:
            actual = Counter(n for (o, uid), n in attempts.items() if o == org)
            alloc = job['allocations'][i]
            require(all(actual[k] == alloc[name] for k, name in [(1, 'one_attempt_users'),
                (2, 'two_attempt_users'), (3, 'three_attempt_users')]), 'Attempt histogram differs from recipe')
    return users


def free_namespace(db, files, required):
    # Only addresses actually used are unavailable, not entire old allocation slots.
    # All background/source and previous event-bearing tables are scanned once.
    used = {row[0] for row in db.execute('''SELECT DISTINCT CAST("IP Address" AS VARCHAR)
              FROM read_parquet(?, union_by_name=true)
              WHERE starts_with(CAST("IP Address" AS VARCHAR), '198.18.')
                 OR starts_with(CAST("IP Address" AS VARCHAR), '198.19.')''',
              [[str(p) for p in files]]).fetchall()}
    free = []
    for address in NETWORK.hosts():
        s = str(address)
        if s not in used:
            free.append(s)
            if len(free) == required:
                return free, len(used)
    raise ValueError('Benchmark namespace capacity insufficient; no silent address-family change')


def ensure_new_output(root, output):
    require(not output.exists(), 'Output exists; refusing overwrite: ' + str(output))
    protected = [root / 'data', root / 'reports', root / 'src', root / 'notebooks']
    for p in protected:
        require(output != p and not p.is_relative_to(output), 'Output would contain protected inputs')
    # New sibling directories under data/phase5 are allowed; existing inputs are not.
    for p in [root / 'data/organizations', root / 'data/phase5/synthetic_events',
              root / 'data/phase5/controlled_pilot_v1', root / 'data/phase5/controlled_pilot_causal_v2',
              root / 'data/phase5/controlled_replay_pilot_v1', root / 'data/phase5/controlled_replay_causal_v2']:
        require(not output.is_relative_to(p), 'Output overlaps preserved input')


def run(root, output):
    import duckdb
    import pandas as pd
    ensure_new_output(root, output)
    recipe_file = root / 'reports/phase5_controlled_variant_recipes_v1.json'
    recipes = read_json(recipe_file)
    for name, expected in recipes['input_checksums_sha256'].items():
        require(sha(root / 'reports' / name) == expected, 'Recipe upstream checksum changed: ' + name)
    original = root / 'data/phase5/synthetic_events'
    manifests, manifest_paths, source_parquets = {}, {}, {}
    cids = {v['source_campaign'] for r in recipes['recipes'] for v in r['variants']}
    cids.update(r['campaign_id'] for r in recipes['source_sorg1_references'])
    require(len(cids) == 270, 'Recipe source inventory must resolve 270 original campaigns')
    for cid in sorted(cids):
        f = original / cid / 'manifest.json'
        m = read_json(f)
        require(m['campaign_id'] == cid, 'Campaign manifest identity mismatch')
        manifests[cid], manifest_paths[cid] = m, f
        source_parquets[cid] = [original / cid / (o + '.parquet') for o in m['targeted_organizations']]
        require(all(x.is_file() for x in source_parquets[cid]), 'Missing source campaign Parquet')
    jobs = flatten_recipes(recipes, manifests)
    anchors = {(split, seed): datetime.fromisoformat(manifests[f'CS_004_SEED{seed}_{split}']['campaign_start'])
               for split in SPLITS for seed in [1001, 1002, 1003]}
    for (split, seed), a in anchors.items():
        lo, hi = SPLITS[split]
        require(lo <= a < a + timedelta(hours=1) <= hi and a - timedelta(days=7) >= SPLITS['TRAIN'][0],
                'Invalid shared anchor')
    org_files = {}
    for i in range(1, 6):
        org = 'Org' + str(i)
        org_files[org] = sorted((root / 'data/organizations' / ('organization=' + org)).rglob('*.parquet'))
        require(bool(org_files[org]), 'Missing organization source: ' + org)
    # Read-only preservation hashes cover every prior Phase 5 file, source organization
    # Parquet, original campaign manifest, recipe inputs and implementation dependencies.
    prior_phase5 = [p for p in (root / 'data/phase5').rglob('*') if p.is_file()]
    read_only_files = set(prior_phase5 + [recipe_file] + list(manifest_paths.values()) +
        [p for fs in org_files.values() for p in fs] +
        [root / 'reports' / name for name in recipes['input_checksums_sha256']])
    print('Hashing preserved inputs...', flush=True)
    baseline = {str(p): sha(p) for p in sorted(read_only_files)}
    db = duckdb.connect(':memory:')
    # Existing outputs may include node-only Parquet; union_by_name keeps this an
    # address-only collision check, not a re-audit of their experimental contents.
    address_files = [p for p in prior_phase5 if p.suffix.lower() == '.parquet'] + [
        p for fs in org_files.values() for p in fs]
    capacity = defaultdict(int)
    for j in jobs:
        capacity[group_key(j)] = max(capacity[group_key(j)], round(sum(j['budgets']) * j['rip']))
    print('Checking new address namespace against existing inputs...', flush=True)
    free, existing_distinct_ips = free_namespace(db, address_files, sum(capacity.values()))
    addresses, offset = {}, 0
    for key in sorted(capacity):
        addresses[key] = free[offset:offset + capacity[key]]
        offset += capacity[key]
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'plan.json', {'version': VERSION, 'instances': 513, 'controlled_variants': 486,
        'descriptive_references': 27, 'organization_branches': 1647,
        'anchors': [{'split': s, 'seed': seed, 'anchor': a.isoformat()} for (s, seed), a in anchors.items()],
        'anchor_policy': 'Source CS_004 start per split/seed; common across isolated factor branches',
        'target_policy': 'Strictly pre-anchor observed User IDs, scoped per organization',
        'cohort_matching': 'Common org+credential ordinal mapping within each split/seed block',
        'ip_policy': 'Unoccupied benchmark IPv4 addresses, disjoint between groups/splits; nested prefixes only within controlled RIP counterparts',
        'new_distinct_ip_addresses_reserved': len(free), 'existing_distinct_addresses_checked': existing_distinct_ips,
        'replay_required': True, 'model_training_performed': False})
    variants, branches, signatures = [], [], {}
    success_count = 0
    try:
        for split in SPLITS:
            for seed in [1001, 1002, 1003]:
                anchor = anchors[(split, seed)]
                block_jobs = [j for j in jobs if j['split'] == split and j['seed'] == seed]
                mappings, pool_sizes, coverage = {}, {}, {}
                for org, files in org_files.items():
                    print(f'{split}/seed{seed}/{org}: selecting pre-anchor cohort...', flush=True)
                    pool = candidate_pool(db, files, anchor)
                    pool_sizes[org] = len(pool)
                    mappings[org] = select_mapping(pool, org, split, seed, anchor)
                    # Availability-only check, never choose anchors using attack/model outcomes.
                    history_n, window_n = db.execute('''SELECT
                        COUNT(*) FILTER (WHERE CAST("Login Timestamp" AS TIMESTAMP) < ?),
                        COUNT(*) FILTER (WHERE CAST("Login Timestamp" AS TIMESTAMP) >= ?)
                        FROM read_parquet(?) WHERE CAST("Login Timestamp" AS TIMESTAMP) >= ?
                          AND CAST("Login Timestamp" AS TIMESTAMP) < ?''',
                        [anchor, anchor, [str(f) for f in files], anchor - timedelta(days=7),
                         anchor + timedelta(hours=1)]).fetchone()
                    require(history_n > 0 and window_n > 0, 'Missing source history/replay observations')
                    coverage[org] = {'history_event_count': history_n, 'replay_background_event_count': window_n}
                    del pool
                for job in block_jobs:
                    cid, vid = job['source_campaign_id'], job['variant_id']
                    reference = None
                    if job['reference_only']:
                        cursor = db.execute('SELECT * FROM read_parquet(?)', [[str(p) for p in source_parquets[cid]]])
                        names = [x[0] for x in cursor.description]
                        reference = [dict(zip(names, row)) for row in cursor.fetchall()]
                        require(len(reference) == manifests[cid]['total_events'], 'Reference template count mismatch')
                    rows = generate(job, mappings, anchor, addresses[group_key(job)], reference, manifests[cid])
                    users = validate(rows, job, mappings, anchor)
                    signature = behavior_digest(rows, vid)
                    if not job['reference_only']:
                        previous = signatures.setdefault(group_key(job), signature)
                        require(previous == signature, 'Controlled RIP non-IP behavior changed')
                    folder = output / vid
                    folder.mkdir()
                    for org in job['organizations']:
                        local = [r for r in rows if r['organization'] == org]
                        write_parquet(db, folder / (org + '.parquet'), local)
                        evidence = [t for uid, t in mappings[org].values() if uid in users[org]]
                        branches.append({'variant_id': vid, 'split': split, 'seed': seed,
                            'organization': org, 'events': len(local), 'targeted_users': len(users[org]),
                            'pre_anchor_observed_users': len(evidence),
                            'without_recent_7d_observation': sum(t <= anchor - timedelta(days=7) for t in evidence),
                            'eligible_pool_size': pool_sizes[org], 'status': 'PASS_SYNTHETIC_CAUSAL_GENERATION'})
                    realized_ips = len({r['IP Address'] for r in rows})
                    record = {'variant_id': vid, 'family': job['family'], 'recipe_id': job['recipe_id'],
                        'source_campaign_id': cid, 'split': split, 'seed': seed,
                        'Sorg_target': len(job['organizations']), 'Raccount_target': job['raccount'],
                        'RIP_target': job['rip'], 'RIP_actual': realized_ips / len(rows),
                        'total_events': len(rows), 'campaign_start': anchor.isoformat(),
                        'campaign_end': (anchor + timedelta(hours=1)).isoformat(),
                        'reference_only': job['reference_only'], 'behavior_sha256_without_ip_or_campaign_metadata': signature,
                        'successful_events': sum(r['LoginSuccessful'] for r in rows),
                        'status': 'PASS_SYNTHETIC_CAUSAL_GENERATION'}
                    manifest = dict(record, schema_version=VERSION, targeted_organizations=job['organizations'],
                        events_per_organization=dict(zip(job['organizations'], job['budgets'])),
                        target_users_per_organization=dict(zip(job['organizations'], job['target_counts'])),
                        credential_identities=100, reused_credential_count=0 if job['raccount'] is None else round(100 * job['raccount']),
                        original_campaign_start=manifests[cid]['campaign_start'],
                        target_selection_policy='STRICTLY_PRE_ANCHOR_OBSERVED_IDS_FROM_SOURCE_AUTHENTICATION',
                        causal_target_selection_corrected=True, background_replayed=False,
                        anchor_status='SOURCE_AVAILABILITY_CHECKED_NOT_REPLAY_VALIDATED',
                        source_availability={o: coverage[o] for o in job['organizations']},
                        source_manifest_sha256=baseline[str(manifest_paths[cid])],
                        output_parquet_sha256={o: sha(folder / (o + '.parquet')) for o in job['organizations']})
                    write_json(folder / 'manifest.json', manifest)
                    success_count += record['successful_events']
                    variants.append(record)
                print(f'{split}/seed{seed}: {len(block_jobs)} instances passed', flush=True)
        require(len(variants) == 513 and len(branches) == 1647, 'Incomplete generation inventory')
        require(sum(v['total_events'] for v in variants if not v['reference_only']) == 150660,
                'Controlled event-budget total mismatch')
        require(all(b['targeted_users'] == b['pre_anchor_observed_users'] for b in branches), 'Causal cohort gate failed')
        print('Checking preserved input hashes...', flush=True)
        require(all(sha(Path(p)) == h for p, h in baseline.items()), 'Preserved input changed')
        pd.DataFrame(variants).to_csv(output / 'variants.csv', index=False)
        pd.DataFrame(branches).to_csv(output / 'branches.csv', index=False)
        summary = {'version': VERSION, 'status': 'PASS_FULL_CONTROLLED_CAUSAL_GENERATION_ONLY',
            'phase5_complete': False, 'background_replayed': False, 'temporal_labels_applied': False,
            'graphsage_features_verified': False, 'model_training_performed': False,
            'instances_generated': len(variants), 'controlled_variants': 486,
            'descriptive_references': 27, 'organization_branches': len(branches),
            'instances_per_split': dict(Counter(v['split'] for v in variants)),
            'total_synthetic_events': sum(v['total_events'] for v in variants),
            'controlled_synthetic_events': 150660,
            'successful_synthetic_events': success_count,
            'target_user_branch_occurrences': sum(b['targeted_users'] for b in branches),
            'pre_anchor_observed_target_occurrences': sum(b['pre_anchor_observed_users'] for b in branches),
            'target_occurrences_without_recent_7d_observation': sum(b['without_recent_7d_observation'] for b in branches),
            'controlled_RIP_behavior_groups_verified': len(signatures),
            'controlled_RIP_comparisons_verified': 324,
            'split_address_sets_disjoint': True,
            'no_collision_with_preexisting_input_addresses': True,
            'source_recipe_sha256': sha(recipe_file), 'builder_sha256': sha(Path(__file__).resolve()),
            'preserved_files_checked': len(baseline), 'all_preserved_input_hashes_unchanged': True,
            'preserved_input_sha256': baseline,
            'self_tests': 'PASS',
            'limitations': ['Attack-only generation; replay, full temporal labeling and final acceptance remain.',
                'Raccount changes coverage and per-user intensity; not an isolated causal intervention.',
                'Primary Sorg changes organization composition and total attempts; no fixed-total sensitivity dataset generated.',
                'Sorg=1 references retain original attempt offsets/outcomes/counts but have corrected users, new IPs and rebased anchors.',
                'All instances are a new dataset version; they do not replace or reproduce the accepted six-variant pilot.',
                'Three shared temporal blocks per split; factor branches share background windows and are not independent natural events.',
                'Observed IDs do not establish account-creation time; cold recent-history users remain included.',
                'Source availability counts are not proof of complete recording or matched background replay.',
                'Synthetic truth, campaign metadata and original source flags must stay evaluator-only.'],
            'next_step': 'Isolated shared-background replay and application of the accepted temporal labeling policy'}
        write_json(output / 'summary.json', summary)
        (output / 'summary.txt').write_text('PASS_FULL_CONTROLLED_CAUSAL_GENERATION_ONLY\n'
            '513 instances (486 controlled + 27 descriptive); 1647 organization branches.\n'
            f"{summary['total_synthetic_events']} synthetic events; all target occurrences observed before anchor.\n"
            'Previous input hashes unchanged. No replay, labels, features, or training performed.\n'
            'Phase 5 remains incomplete.\n', encoding='utf-8')
        write_json(output / 'output_sha256.json', {str(f.relative_to(output)): sha(f)
            for f in sorted(output.rglob('*')) if f.is_file()})
        print('PASS_FULL_CONTROLLED_CAUSAL_GENERATION_ONLY\n' + str(output))
    except Exception as exc:
        write_json(output / 'FAILED.json', {'status': 'FAILED_INCOMPLETE_OUTPUT', 'error': str(exc)})
        raise
    finally:
        db.close()


class GenerationTests(unittest.TestCase):
    def job(self, rip=0.2):
        return {'variant_id': 'TEST', 'source_campaign_id': 'CS_004_SEED1001_TRAIN',
            'family': 'Raccount_fixed_per_org_attempts', 'split': 'TRAIN', 'seed': 1001,
            'organizations': ['Org1', 'Org2'], 'target_counts': [60, 60], 'budgets': [90, 90],
            'raccount': 0.2, 'rip': rip, 'reference_only': False,
            'allocations': [{'one_attempt_users': 45, 'two_attempt_users': 0,
                             'three_attempt_users': 15, 'total_attempts': 90}] * 2}

    def setUp(self):
        self.a = datetime(2020, 3, 1)
        self.mapping = {o: {k: (1000 * i + k, self.a - timedelta(days=8)) for k in range(1, 101)}
                        for i, o in enumerate(['Org1', 'Org2'], 1)}
        self.ips = [str(NETWORK.network_address + i) for i in range(1, 181)]

    def test_generation_budgets_reuse_and_causality(self):
        j = self.job()
        rows = generate(j, self.mapping, self.a, self.ips)
        validate(rows, j, self.mapping, self.a)
        self.assertEqual(len(rows), 180)

    def test_rip_only_behavior_exact(self):
        rows = [generate(self.job(rip), self.mapping, self.a, self.ips) for rip in [0.2, 0.5, 0.8]]
        self.assertEqual(len({behavior_digest(r, 'TEST') for r in rows}), 1)
        self.assertEqual([len({x['IP Address'] for x in r}) for r in rows], [36, 90, 144])

    def test_determinism(self):
        self.assertEqual(generate(self.job(), self.mapping, self.a, self.ips),
                         generate(self.job(), self.mapping, self.a, self.ips))

    def test_future_candidate_rejected(self):
        pool = [(i, self.a) for i in range(100)]
        with self.assertRaises(ValueError):
            select_mapping(pool, 'Org1', 'TRAIN', 1001, self.a)

    def test_insufficient_pool_rejected(self):
        with self.assertRaises(ValueError):
            select_mapping([(1, self.a - timedelta(days=1))], 'Org1', 'TRAIN', 1001, self.a)

    def test_sql_prefix_invariance(self):
        import duckdb
        import pandas as pd
        import tempfile
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as d:
            path = Path(d) / 'source.parquet'
            db = duckdb.connect()
            try:
                frame = pd.DataFrame({'User ID': [1, 2, 3], 'Login Timestamp': [self.a - timedelta(seconds=1),
                    self.a, self.a + timedelta(days=1)]})
                db.register('test_source', frame)
                db.execute("COPY test_source TO '" + str(path).replace("'", "''") + "' (FORMAT PARQUET)")
                self.assertEqual(candidate_pool(db, [path], self.a), [(1, self.a - timedelta(seconds=1))])
            finally:
                db.close()

    def test_all_reuse_cohort_sizes(self):
        for counts, ra in [([60, 60], .2), ([75, 75], .5), ([90, 90], .8),
                           ([47, 47, 46], .2), ([67, 67, 66], .5), ([87, 87, 86], .8),
                           ([36] * 5, .2), ([60] * 5, .5), ([84] * 5, .8)]:
            j = self.job();j.update(target_counts=counts, organizations=['Org' + str(i + 1) for i in range(len(counts))], raccount=ra)
            c = cohorts(j)
            self.assertEqual(sum(len(x) for x in c.values()), sum(counts))
            self.assertEqual(len({k for entries in c.values() for k, reused in entries}), 100)

    def test_sorg1_reuse_not_applicable(self):
        j = self.job();j.update(target_counts=[100], organizations=['Org1'], raccount=None)
        c = cohorts(j)
        self.assertEqual(len(c['Org1']), 100)
        self.assertFalse(any(reused for k, reused in c['Org1']))

    def test_invalid_allocation(self):
        with self.assertRaises(ValueError):
            attempt_counts(3, {'one_attempt_users': 1, 'two_attempt_users': 0,
                'three_attempt_users': 0, 'total_attempts': 1}, random.Random(1))

    def test_split_boundary_rejected(self):
        j = self.job()
        a = datetime(2020, 10, 1)
        rows = generate(j, self.mapping, a, self.ips)
        with self.assertRaises(ValueError):
            validate(rows, j, self.mapping, a)

    def test_new_paths_only(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as d:
            root = Path(d)
            with self.assertRaises(ValueError):
                ensure_new_output(root, root)
            ensure_new_output(root, root / 'data/phase5/new_inventory')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--output', type=Path)
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GenerationTests))
    require(result.wasSuccessful(), 'Automated generation tests failed')
    if not args.self_test:
        root = args.root.resolve()
        output = (args.output or root / 'data/phase5/controlled_inventory_causal_v1').resolve()
        run(root, output)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('STOPPED: ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        sys.exit(1)
