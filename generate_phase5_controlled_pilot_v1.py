#!/usr/bin/env python3
"""CredBlock-FL Phase 5 — versioned controlled variant PILOT generator.

Run from project root (existing .venv with duckdb and pandas):
    python generate_phase5_controlled_pilot_v1.py

Generates SIX synthetic variants: three Raccount (Sorg=2; RIP=.20) and
three Sorg (2,3,5; RIP=.20; Raccount=.20), all TEST/seed1001.

Reads source campaign Parquet, original manifests and planning reports. It DOES
NOT modify or merge original campaigns/background records. Outputs new pilot
Parquet and manifests under data/phase5/controlled_pilot_v1/ and four reports.

IMPORTANT: This creates ATTACK-ONLY pilot events. It does not create matched
background replay, graph features, labels, model-training data, or claim a
causal isolation of Raccount/Sorg. Candidate anchor does not imply validation.

Uses deliberately reserved 198.18/15 benchmark addresses at offsets >=100000,
checks all original synthetic IPs for collisions, and rejects preexisting
output directories. Do not run on real systems; offline synthetic study only.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import ipaddress
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

NETWORK = ipaddress.ip_network('198.18.0.0/15')
IP_BASE_OFFSET = 100000
IP_SLOT_SIZE = 4096
REQUIRED = {'organization','User ID','Login Timestamp','LoginSuccessful',
            'synthetic_credential_id','is_reused_credential','campaign_id',
            'campaign_event_id','IP Address'}
SPLIT_BOUNDS = {'TRAIN': ('2020-02-03','2020-10-01'),
                'VAL': ('2020-10-01','2020-12-01'),
                'TEST': ('2020-12-01','2021-03-01')}
VERSION='controlled-pilot-v1'


def filehash(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()


def stable_seed(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str,parts)).encode()).digest()[:8], 'big')


def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def find_recipe(recs, family, split='TEST', seed=1001, rip='0.20', sorg=2, raccount='0.20'):
    hits=[r for r in recs if r['family']==family and r['split']==split
          and int(r['seed'])==seed and r['rip_target']==rip and
          (int(r['sorg'])==sorg if family.startswith('Raccount')
           else r['raccount']==raccount)]
    if len(hits)!=1: raise ValueError(f'Expected exactly one {family} pilot recipe, got {len(hits)}')
    return hits[0]


def source_record(db, root, cid):
    p=root/'data'/'phase5'/'synthetic_events'/cid
    mpath=p/'manifest.json'
    if not mpath.is_file(): raise FileNotFoundError(mpath)
    manifest=load_json(mpath)
    if manifest['campaign_id']!=cid: raise ValueError(f'Campaign ID inconsistent: {cid}')
    orgs=list(manifest['targeted_organizations'])
    files=[p/f'{org}.parquet' for org in orgs]
    if any(not f.is_file() for f in files):
        raise FileNotFoundError(f'Missing org Parquet in {cid}: {files}')
    cursor=db.execute('SELECT * FROM read_parquet(?)', [[str(f) for f in files]])
    cols=[c[0] for c in cursor.description]
    if not REQUIRED.issubset(cols): raise ValueError(f'Missing fields in {cid}: {sorted(REQUIRED-set(cols))}')
    rows=[dict(zip(cols,r)) for r in cursor.fetchall()]
    if len(rows)!=int(manifest['total_events']): raise ValueError(f'Manifest event total mismatch: {cid}')
    if {x['organization'] for x in rows}!=set(orgs): raise ValueError(f'Org mismatch: {cid}')
    for x in rows:
        if str(x['campaign_id'])!=cid or x['Login Timestamp'] is None:
            raise ValueError(f'Invalid source event {cid}')
    return manifest, mpath, files, rows


def credential_cohorts(rows, cid, orgs, expected_counts, reuse):
    """Preserve original credential->local-user mapping without sharing users across orgs."""
    lookup=defaultdict(dict)
    for row in rows:
        org=str(row['organization']); key=str(row['synthetic_credential_id'])
        prefix=cid+'_CRED_'
        if not key.startswith(prefix): raise ValueError(f'Unexpected credential ID {key}')
        k=key[len(prefix):]
        user=str(row['User ID'])
        pair=(user,bool(row['is_reused_credential']))
        prev=lookup[org].setdefault(k,pair)
        if prev!=pair: raise ValueError(f'Credential mapping inconsistent: {cid}/{org}/{k}')
    if set(lookup)!=set(orgs): raise ValueError(f'Org cohorts do not match recipe {cid}')
    out={}
    for i,org in enumerate(orgs):
        entries=sorted((key,user,flag) for key,(user,flag) in lookup[org].items())
        if len(entries)!=int(expected_counts[i]): raise ValueError(f'Cohort count mismatch: {cid}/{org}')
        if len({user for _,user,_ in entries})!=len(entries):
            raise ValueError(f'Non-unique local user targets: {cid}/{org}')
        out[org]=entries
    all_ids=set().union(*(set(lookup[o]) for o in orgs))
    if len(all_ids)!=100: raise ValueError(f'Expected 100 credential identities, got {len(all_ids)} in {cid}')
    expected_reused=0 if len(orgs)==1 else round(100*reuse)
    present={k:set(o for o in orgs if k in lookup[o]) for k in all_ids}
    actual_reused=sum(len(v)==len(orgs) for v in present.values()) if len(orgs)>1 else 0
    if actual_reused!=expected_reused: raise ValueError(f'Raccount mismatch {cid}: {actual_reused} != {expected_reused}')
    for k, active_orgs in present.items():
        if len(active_orgs) not in (1,len(orgs)):
            raise ValueError(f'Unexpected subset credential reuse: {cid}/{k}')
        for org in active_orgs:
            if lookup[org][k][1] != (len(active_orgs)>1):
                raise ValueError(f'Incorrect reused flag: {cid}/{org}/{k}')
    return out, actual_reused


def user_attempt_counts(n, recipe_allocation, rng):
    expected=[1]*int(recipe_allocation['one_attempt_users']) + [2]*int(recipe_allocation['two_attempt_users']) + [3]*int(recipe_allocation['three_attempt_users'])
    if len(expected)!=n or sum(expected)!=int(recipe_allocation['total_attempts']):
        raise ValueError('Attempt allocation violates recipe')
    rng.shuffle(expected)
    return expected


def generate_variant(recipe, v, slot, source_rows, source_manifest, mpath, files, anchor):
    cid=v['source_campaign']
    split=recipe['split']; seed=int(recipe['seed'])
    orgs=list(v.get('organizations',recipe.get('organizations',[])))
    if len(orgs)!=int(v.get('sorg',recipe.get('sorg'))):
        raise ValueError(f'Wrong org count for {cid}')
    target_counts=list(map(int,v['target_users_per_org']))
    budgets=list(map(int,v['attempts_per_org']))
    allocations=v['user_attempt_allocation_per_org']
    ra=float(v.get('raccount',recipe.get('raccount',0.2)))
    rip=float(v.get('rip_target',recipe['rip_target']))
    if abs(rip-float(source_manifest['RIP_target']))>1e-9:
        raise ValueError(f'Source RIP mismatch {cid}')
    if abs(ra-float(source_manifest['Raccount_target']))>1e-9:
        raise ValueError(f'Source Raccount mismatch {cid}')
    if int(source_manifest['Sorg_target'])!=len(orgs) or list(source_manifest['targeted_organizations'])!=orgs:
        raise ValueError(f'Source organizations mismatch {cid}')
    start=datetime.fromisoformat(anchor)
    end=start+timedelta(hours=1)
    lower,upper=(datetime.fromisoformat(x) for x in SPLIT_BOUNDS[split])
    if not lower<=start<end<=upper: raise ValueError('Anchor crosses chronological split')
    cohorts, reused=credential_cohorts(source_rows,cid,orgs,target_counts,ra)
    branch=('RA' if recipe['family'].startswith('Raccount') else 'SO')
    vid=f'CPV1_{branch}_{cid}'
    rng=random.Random(stable_seed(VERSION,vid,'events'))
    events=[]
    for i,org in enumerate(orgs):
        entries=cohorts[org]
        nums=user_attempt_counts(len(entries),allocations[i],rng)
        for (key,user,flag),n in zip(entries,nums):
            for _ in range(n):
                micros=rng.randrange(0,3600*1000000)
                ts=start+timedelta(microseconds=micros)
                events.append({
                    'organization':org, 'User ID':user, 'Login Timestamp':ts,
                    'LoginSuccessful':rng.random()<0.05,
                    'synthetic_credential_id':f'{vid}_CRED_{key}',
                    'is_reused_credential':flag,
                    'is_synthetic':True,'credential_stuffing_label':1,
                    'scenario_id':str(source_manifest['scenario_id']),
                    'campaign_id':vid,
                    'IP Address':None, 'campaign_event_id':None})
    n=len(events); expected_total=int(v['total_attempts']) if 'total_attempts' in v else int(recipe['budget_total_attempts'])
    if n!=expected_total or [sum(x['organization']==org for x in events) for org in orgs]!=budgets:
        raise ValueError(f'Budget mismatch {vid}')
    needed=max(1,min(n,round(n*rip)))
    start_ip=IP_BASE_OFFSET+slot*IP_SLOT_SIZE
    if needed>IP_SLOT_SIZE or start_ip+IP_SLOT_SIZE>NETWORK.num_addresses:
        raise ValueError('IP namespace capacity exceeded')
    addresses=[str(NETWORK.network_address+start_ip+i) for i in range(needed)]
    iprng=random.Random(stable_seed(VERSION,vid,'ip'))
    assignments=addresses.copy()
    assignments.extend(iprng.choice(addresses) for _ in range(n-needed))
    iprng.shuffle(assignments)
    for i,e in enumerate(events):
        e['IP Address']=assignments[i]
    events.sort(key=lambda x:(x['Login Timestamp'],x['organization'],x['User ID']))
    for i,e in enumerate(events,1):
        e['campaign_event_id']=f'{vid}_EVT_{i:05d}'
    checks={
        'events_total':n==expected_total,
        'per_org_attempt_budgets':all(sum(e['organization']==o for e in events)==b for o,b in zip(orgs,budgets)),
        'per_org_cohort_sizes':all(len({e['User ID'] for e in events if e['organization']==o})==c for o,c in zip(orgs,target_counts)),
        'one_to_three_attempts_per_local_user':all(1<=num<=3 for num in Counter((e['organization'],e['User ID']) for e in events).values()),
        'unique_credential_identities_100':len({e['synthetic_credential_id'] for e in events})==100,
        'reused_credential_identities':reused==round(100*ra),
        'unique_ip_count_matches_RIP':len({e['IP Address'] for e in events})==needed,
        'timestamps_in_anchor':all(start<=e['Login Timestamp']<end for e in events),
        'event_ids_unique':len({e['campaign_event_id'] for e in events})==n,
    }
    if not all(checks.values()): raise ValueError(f'Variant checks failed: {vid}: {checks}')
    manifest={
        'schema_version':VERSION, 'pilot_only':True,'variant_id':vid,'family':recipe['family'],
        'recipe_id':recipe['recipe_id'],'source_campaign_id':cid,
        'source_manifest_sha256':filehash(mpath),
        'source_parquet_sha256':{p.name:filehash(p) for p in files},
        'split':split,'seed':seed, 'targeted_organizations':orgs,
        'RIP_target':rip,'RIP_actual':needed/n,
        'Raccount_target':ra,'Raccount_actual':reused/100,
        'Sorg_target':len(orgs),'Sorg_actual':len(orgs),
        'campaign_start':start.isoformat(),'campaign_end':end.isoformat(),
        'original_campaign_start':source_manifest['campaign_start'],
        'anchor_status':'CANDIDATE_ONLY_NOT_REPLAY_VALIDATED',
        'background_replayed':False,
        'background_window_shared_only_in_future_isolated_branches':True,
        'total_events':n, 'events_per_organization':dict(zip(orgs,budgets)),
        'target_users_per_organization':dict(zip(orgs,target_counts)),
        'credential_identities':100,'reused_credential_count':reused,
        'success_probability':0.05,'min_attempts_per_account':1,'max_attempts_per_account':3,
        'ip_namespace_start_offset':start_ip,'ip_namespace_slot_capacity':IP_SLOT_SIZE,
        'limitations':['Raccount changes local cohort sizes/attempts per user',
                       'Sorg changes org composition and total campaign intensity',
                       'No merged background, no labels/graphs, no causal claims'],
        'checks':checks,
    }
    return events,manifest


def safe_write_parquet(db, path, rows):
    import pandas as pd
    frame=pd.DataFrame(rows)
    db.register('pilot_rows_to_write',frame)
    quoted=str(path).replace("'","''")
    try: db.execute(f"COPY pilot_rows_to_write TO '{quoted}' (FORMAT PARQUET)")
    finally: db.unregister('pilot_rows_to_write')


def validate_output(db,path,expected,manifest):
    data=db.execute('SELECT * FROM read_parquet(?)',[str(path)]).fetchall()
    if len(data)!=expected: raise ValueError(f'Written Parquet count mismatch {path}')
    distinct=db.execute('SELECT count(DISTINCT "campaign_event_id"), count(DISTINCT "IP Address") FROM read_parquet(?)',[str(path)]).fetchone()
    if distinct[0]!=expected or distinct[1]>manifest['total_events']:
        raise ValueError(f'Written Parquet integrity failed {path}')


def original_ip_scan(db,root,pilot_ips):
    """Check against *every* original source synthetic Parquet; fail closed on missing input."""
    base=root/'data'/'phase5'/'synthetic_events'
    all_dirs=sorted(d for d in base.iterdir() if d.is_dir() and d.name.endswith(('_TRAIN','_VAL','_TEST')))
    if len(all_dirs)!=270: raise ValueError(f'Expected 270 original campaign folders, found {len(all_dirs)}')
    checked=0
    for folder in all_dirs:
        manifest=load_json(folder/'manifest.json')
        files=sorted(folder.glob('*.parquet'))
        if not files or len(files)!=len(manifest['targeted_organizations']):
            raise ValueError(f'Missing original files in {folder}')
        ips=db.execute('SELECT DISTINCT "IP Address" FROM read_parquet(?)',[[str(p) for p in files]]).fetchall()
        checked+=1
        overlap=pilot_ips.intersection(str(x[0]) for x in ips)
        if overlap: raise ValueError(f'Pilot IP collides with original campaign {folder.name}: {list(overlap)[:3]}')
    return checked


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--recipes',type=Path,default=None)
    parser.add_argument('--output',type=Path,default=None)
    args=parser.parse_args()
    root=args.root.resolve()
    import duckdb
    db=duckdb.connect(':memory:')
    recipes_path=(args.recipes or root/'reports'/'phase5_controlled_variant_recipes_v1.json').resolve()
    plan_path=root/'reports'/'phase5_controlled_comparison_plan_v1.json'
    rip_path=root/'reports'/'phase5_rip_exact_equivalence_summary.json'
    for p in [recipes_path,plan_path,rip_path]:
        if not p.is_file(): raise FileNotFoundError(p)
    obj=load_json(recipes_path); plan=load_json(plan_path); rip=load_json(rip_path)
    if (int(obj['source_campaign_count'])!=270 or
        int(obj['raccount_recipe_count'])!=81 or int(obj['sorg_recipe_count'])!=81 or
        rip['statuses'].get('PASS_SYNTHETIC_RIP_EQUIVALENCE')!=270):
        raise ValueError('Upstream audit gate failed')
    for fname,expected in obj['input_checksums_sha256'].items():
        path=root/'reports'/fname
        if filehash(path)!=expected: raise ValueError(f'Upstream recipe input checksum mismatch: {path}')
    ra=find_recipe(obj['recipes'],'Raccount_fixed_per_org_attempts')
    so=find_recipe(obj['recipes'],'Sorg_fixed_per_org_attempts')
    pilot=[(ra,v) for v in ra['variants']]+[(so,v) for v in so['variants']]
    if len(pilot)!=6 or len({(r['family'],v['source_campaign']) for r,v in pilot})!=6:
        raise ValueError('Pilot is not six independent versioned variants')
    # Shared common candidate time; never selected using TEST model scores.
    anchor_candidate=ra['anchor_campaign_candidate']
    source_anchor=load_json(root/'data'/'phase5'/'synthetic_events'/anchor_candidate/'manifest.json')
    anchor=source_anchor['campaign_start']
    all_orgs=sorted(set().union(*(set(v.get('organizations',r.get('organizations',[]))) for r,v in pilot)))
    start=datetime.fromisoformat(anchor)
    cov=plan['source_coverage']
    for org in all_orgs:
        if (datetime.fromisoformat(cov[org]['start']) > start-timedelta(days=7)
                or datetime.fromisoformat(cov[org]['end']) < start+timedelta(hours=1)):
            raise ValueError(f'Insufficient source date bounds for {org} at {anchor}')
    output=(args.output or root/'data'/'phase5'/'controlled_pilot_v1').resolve()
    if output.exists(): raise FileExistsError(f'Output exists; refusing to overwrite: {output}')
    if root not in output.parents: raise ValueError('Output must be inside project root')
    source_dir=(root/'data'/'phase5'/'synthetic_events').resolve()
    if output==source_dir or source_dir in output.parents or output in source_dir.parents:
        raise ValueError('Output path overlaps original synthetic source')
    temp=output.parent/(output.name+'.incomplete')
    if temp.exists(): raise FileExistsError(f'Incomplete previous output exists: {temp}')
    print('CRED BLOCK-FL — PHASE 5 VERSIONED CONTROLLED PILOT V1')
    print(f'Pilot: 3 Raccount + 3 Sorg | TEST seed1001 | candidate anchor={anchor}')
    print('Preloading and validating all six source campaigns ...')
    source_data={}
    for _,v in pilot:
        cid=v['source_campaign']
        if cid not in source_data:
            source_data[cid]=source_record(db,root,cid)
    baseline_sha={str(p):filehash(p) for sm,mp,ps,rows in source_data.values() for p in [mp,*ps]}
    generated=[]; all_ips=set(); checks=[]
    for slot,(recipe,v) in enumerate(pilot):
        cid=v['source_campaign']
        sm,mp,parquets,rows=source_data[cid]
        ev,man=generate_variant(recipe,v,slot,rows,sm,mp,parquets,anchor)
        ips={e['IP Address'] for e in ev}
        if all_ips.intersection(ips): raise ValueError('Cross-variant IP collision')
        all_ips.update(ips)
        generated.append((ev,man))
        checks.append({'variant_id':man['variant_id'],'family':recipe['family'],
                       'source_campaign':cid,'events':len(ev),'orgs':len(man['targeted_organizations']),
                       'rip_actual':man['RIP_actual'],'raccount_actual':man['Raccount_actual'],
                       'status':'PASS_SYNTHETIC_GENERATION', 'anchor':'CANDIDATE_ONLY'})
        print(f"  {man['variant_id']}: {len(ev)} events, {len(man['targeted_organizations'])} orgs — PASS")
    print('Checking all 270 original campaign IP inventories for collisions ...')
    orig_checked=original_ip_scan(db,root,all_ips)
    temp.mkdir(parents=True)
    try:
        for events,manifest in generated:
            d=temp/manifest['variant_id'];d.mkdir()
            for org in manifest['targeted_organizations']:
                part=[x for x in events if x['organization']==org]
                f=d/f'{org}.parquet';safe_write_parquet(db,f,part)
                validate_output(db,f,len(part),manifest)
            manifest['generated_parquet_sha256']={p.name:filehash(p) for p in d.glob('*.parquet')}
            (d/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        temp.rename(output)
    except Exception:
        shutil.rmtree(temp,ignore_errors=True)
        raise
    if any(filehash(Path(p))!=digest for p,digest in baseline_sha.items()):
        raise ValueError('Original campaign file checksum changed during pilot; investigate immediately')
    report_dir=root/'reports';report_dir.mkdir(exist_ok=True)
    base='phase5_controlled_pilot_v1'
    report={
        'version':VERSION,'status':'PASS_SYNTHETIC_PILOT_ONLY',
        'variants_generated':len(generated),'raccount_variants':3,'sorg_variants':3,
        'original_campaigns_scanned_for_ip_collisions':orig_checked,
        'original_campaigns_modified':0,'shared_anchor_candidate':anchor,
        'anchor_ready_for_replay':False,'background_replayed':False,
        'labels_and_feature_leakage_verified':False,'source_recipe_sha256':filehash(recipes_path),
        'source_plan_sha256':filehash(plan_path),
        'source_RIP_audit_sha256':filehash(rip_path),
        'output_folder':str(output),
        'results':checks,
        'limitations':['Existing source target-user cohorts may reflect full-period selection; verify causal eligibility before final replay',
            'No real background merged or validated at candidate anchor',
            'Raccount changes target-user coverage and per-user attack rate',
            'Sorg changes organization composition and total attempts',
            'Do not train GraphSAGE on synthetic metadata, labels or credential identifiers'],
    }
    (report_dir/(base+'_summary.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (report_dir/(base+'_variants.csv')).open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(checks[0]));writer.writeheader();writer.writerows(checks)
    summary='\n'.join([
        'CRED BLOCK-FL — PHASE 5 CONTROLLED PILOT V1',
        '='*58, 'STATUS: PASS_SYNTHETIC_PILOT_ONLY',
        'Generated: 6 variants (3 Raccount + 3 Sorg)',
        f'Original synthetic campaign IP inventories checked: {orig_checked}/270',
        'Original campaigns modified: 0',
        f'Candidate common anchor: {anchor} (NOT REPLAY VALIDATED)',
        'No background replay, labels, graph features, or causal effects validated.',
        'Files:',str(output),str(report_dir/(base+'_summary.json')),
        str(report_dir/(base+'_variants.csv')),''])
    (report_dir/(base+'_summary.txt')).write_text(summary,encoding='utf-8')
    print('\n'+summary)


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(f'PILOT FAILED (no original campaigns modified): {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
