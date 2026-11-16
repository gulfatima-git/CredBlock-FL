"""Freeze/offline representative evaluation. This command never launches a sweep."""
import argparse,csv,json,hashlib,sqlite3,time
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict
from src.phase6.readiness import ROOT,REPLAY,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.input_pipeline import PinnedInputs
from src.phase6.training_data import dump_json
from src.phase6.detectability import evaluate_campaigns,FAMILIES

BASE=ROOT/'reports/phase6/detectability';CONFIG=ROOT/'configs/phase6/detectability_protocol_v1.json'
SOURCES=['src/phase6/detectability.py','src/phase6/run_detectability.py','tests/phase6/test_detectability.py']
IND=ROOT/'reports/phase6/indicator_baseline'

def eligible_variant(value):
    require(isinstance(value,str) and value.endswith('_VAL') and Path(value).name==value and '/' not in value and '\\' not in value,'Only isolated VAL variants are authorized; TEST forbidden before access')

def inventory():
    pins=PinnedInputs(ROOT);rows=[]
    with (ROOT/'reports/phase5_final_acceptance_v2/campaign_register_v2.csv').open(newline='',encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['split']!='VAL':continue
            eligible_variant(r['variant_id']);path=pins.check(ROOT/REPLAY/r['variant_id']/'replay_manifest.json');m=load(path)
            require(m['variant_id']==r['variant_id'] and m['split']=='VAL' and m['anchor']==r['campaign_start'] and m['end_exclusive']==r['campaign_end_exclusive'],'Frozen campaign/branch mismatch')
            orgs=r['targeted_organizations'].split('|');require(orgs==m['targeted_organizations'],'Targeted organization metadata mismatch')
            rows.append(dict(variant_id=r['variant_id'],scenario_id=r['scenario_id'],split='VAL',seed=int(r['seed']),start=r['campaign_start'],end_exclusive=r['campaign_end_exclusive'],targeted_organizations=orgs,
                factors={k:r[k] for k in ['family','RIP_target','Raccount_target','Sorg_target','RIP_actual','Raccount_actual','Sorg_actual']},manifest_sha256=sha(path)))
    require(len(rows)==171 and len({r['variant_id'] for r in rows})==171,'Required VAL inventory is not exactly 171')
    return sorted(rows,key=lambda r:r['variant_id']),pins

def freeze():
    require(not (BASE/'preregistration_v1.json').exists(),'No overwrite of frozen method')
    cfg=load(CONFIG);require(cfg['split']=='VAL' and cfg['required_instances']==171,'Scientific scope changed')
    require(load(IND/'acceptance_v1.json')['status']=='USER_ACCEPTED','Subphase 7 not accepted')
    rows,pins=inventory();require(cfg['predetermined_representative'] in {r['variant_id'] for r in rows},'Missing predetermined representative')
    require(sha(ROOT/'configs/phase6/split_protocol_v1.json')==cfg['primary_protocol_sha256'],'Primary protocol changed')
    documents=load(IND/'preregistration_v1.json')['design_document_sha256']
    for p,h in documents.items():require(sha(Path(p))==h,'Authoritative design document changed')
    dump_json(BASE/'required_val_inventory_v1.json',rows)
    dump_json(BASE/'preregistration_v1.json',dict(status='FROZEN_BEFORE_CAMPAIGN_OUTCOME_JOIN',configuration_sha256=sha(CONFIG),source_sha256={p:sha(ROOT/p) for p in SOURCES},
        inventory_sha256=sha(BASE/'required_val_inventory_v1.json'),accepted_indicator_delivery_sha256=sha(IND/'delivery_manifest_v1.json'),accepted_indicator_policy_sha256=sha(ROOT/'configs/phase6/indicator_sharing_v1.json'),
        design_document_sha256=documents,source_manifest_sha256=pins.checked,method=cfg,full_sweep_authorized=False))
    print(json.dumps(dict(status='METHOD_FROZEN_BEFORE_OUTCOME_JOIN',required_instances=171,configuration_sha256=sha(CONFIG))),flush=True)

def pinned():
    p=load(BASE/'preregistration_v1.json');cfg=load(CONFIG)
    require(sha(CONFIG)==p['configuration_sha256'],'Frozen detectability method changed')
    for path,h in p['source_sha256'].items():require(sha(ROOT/path)==h,'Frozen evaluator source changed: '+path)
    require(sha(BASE/'required_val_inventory_v1.json')==p['inventory_sha256'],'Inventory changed')
    require(sha(ROOT/'configs/phase6/split_protocol_v1.json')==cfg['primary_protocol_sha256'],'Primary protocol changed')
    require(sha(ROOT/'configs/phase6/indicator_sharing_v1.json')==p['accepted_indicator_policy_sha256'],'Indicator policy changed')
    return cfg,p

def jsonlines(path):
    with path.open(encoding='utf-8') as f:
        for line in f:
            if line.strip():yield json.loads(line)

def sealed_decisions(variant):
    """Decode model/temporal records only; no campaign ground truth enters here."""
    cfg,p=pinned();eligible_variant(variant);require(variant==cfg['predetermined_representative'],'Pilot accepts predetermined representative only')
    sealed=load(IND/'delivery_manifest_v1.json');require(sha(IND/'delivery_manifest_v1.json')==p['accepted_indicator_delivery_sha256'],'Accepted delivery seal changed')
    for path,h in sealed['artifact_sha256'].items():require(sha(ROOT/path)==h,'Accepted artifact changed: '+path)
    public={r['indicator_id']:r for r in jsonlines(IND/'paired_v1/network_events.jsonl') if r['event']=='creation'}
    decisions=[];alternate=[];coverage={};proof=[];all_hashes={}
    for org in ['Org1','Org2','Org3','Org4','Org5']:
        component=load(IND/f'local_v1/{org}/summary.json');source=load(IND/f'local_v1/{org}/source_identity.json')
        require(source['variant_id']==variant,'Accepted branch mismatch')
        paths=[ROOT/component['local']['private_store'],ROOT/f'reports/phase6/inference/v1/{org}/uninterrupted/private/inference.sqlite',ROOT/f'reports/phase6/inference/v1/{org}/restart_repeat/private/inference.sqlite']
        matrices=[];commands=[]
        for path in paths:
            all_hashes[path.relative_to(ROOT).as_posix()]=sha(path)
            db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro',uri=True)
            require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Accepted journal integrity failure')
            matrices.append(db.execute('SELECT seq,user_id,asof,trigger,logit_hex,threshold_hex,decision,alert_id,model_sha256,threshold_sha256,schema_sha256,processing_status FROM scores ORDER BY seq,user_id').fetchall())
            commands.append(db.execute('SELECT seq,asof,payload,event_offset,view_digest FROM commands ORDER BY seq').fetchall());db.close()
        require(matrices[0]==matrices[1]==matrices[2] and commands[0]==commands[1]==commands[2],'Score/threshold/alert/timestamp/feature-view reuse not exactly equivalent')
        current={};count=0
        for seq,at,payload,offset,digest in commands[0]:
            rows=json.loads(payload)['observations'];count+=len(rows);ips={}
            for r in rows:
                require(r['organization']==org and r['Login Timestamp']==at,'Noncausal accepted command')
                ips.setdefault(r['User ID'],set()).add(r['IP Address'])
            current[seq]=(at,ips)
        require(count==source['events'] and commands[0][-1][1]==(datetime.fromisoformat(source['end_exclusive'])-timedelta(microseconds=1)).isoformat(),'Full-hour coverage lost')
        pair=IND/f'paired_v1/{org}/private/paired_decisions.jsonl';reverse=IND/f'reverse_order_v1/{org}/private/paired_decisions.jsonl'
        require(sha(pair)==sha(reverse),'Combined decisions not reverse-order equivalent')
        pairs=list(jsonlines(pair));reverse_pairs=list(jsonlines(reverse));require(len(pairs)==len(matrices[0]),'Local/combined row census mismatch')
        for row,raw,independent_raw,reverse_row in zip(pairs,matrices[0],matrices[1],reverse_pairs):
            seq,user,at,trigger,logit,threshold,flag,alert_id,model_sha,threshold_sha,schema_sha,status=raw
            require((row['seq'],row['user_id'],row['at'],row['local_logit_hex'],row['threshold_hex'],row['local_alert'])==(seq,user,at,logit,threshold,flag=='ALERT'),'Stored paired row changed original score/threshold/alert')
            require(status=='OK' and (float.fromhex(logit)>=float.fromhex(threshold))==(flag=='ALERT'),'Unrounded binary64 decision mismatch')
            t=datetime.fromisoformat(at);wanted=sorted(k for k,v in public.items() if v['issuer']!=org and v['ip'] in current[seq][1].get(user,set()) and datetime.fromisoformat(v['available_at'])<=t<datetime.fromisoformat(v['expires_at']))
            require(wanted==row['indicator_ids'] and row['local_plus_indicator_alert']==(flag=='ALERT' or bool(wanted)),'Causal indicator decision mismatch')
            for family,alert in [('local_only',flag=='ALERT'),('local_plus_indicator',row['local_plus_indicator_alert'])]:
                decisions.append(dict(variant_id=variant,organization=org,user_id=user,at=t,family=family,alert=alert))
                alternate.append(dict(variant_id=variant,organization=org,user_id=independent_raw[1],at=datetime.fromisoformat(independent_raw[2]),family=family,alert=(independent_raw[6]=='ALERT') if family=='local_only' else reverse_row['local_plus_indicator_alert']))
        for family in FAMILIES:coverage[(variant,org,family)]=True
        proof.append(dict(organization=org,score_rows=len(pairs),independent_original_local_runs_compared=3,all_scores_thresholds_alerts_timestamps_views_exact=True,indicator_reverse_order_bytes_exact=True,causal_indicator_matches_recomputed=True,
            final_ten_minutes=component['local']['final_ten_minutes'],graph_sha256=component['local']['final_graph_checkpoint_sha256'],bundle_fingerprint=component['local']['bundle_fingerprint']))
    return decisions,alternate,coverage,proof,all_hashes

def truth_for_variant(row):
    """Offline evaluator-only loader, invoked after immutable runtime proofs."""
    eligible_variant(row['variant_id']);pins=PinnedInputs(ROOT);folder=ROOT/REPLAY/row['variant_id'];m=load(pins.check(folder/'replay_manifest.json'))
    import duckdb
    db=duckdb.connect(':memory:');events=[];ids=set()
    try:
        for branch in m['branches']:
            org=branch['organization'];path=pins.check(folder/f'{org}_replay.parquet');require(sha(path)==branch['replay_parquet_sha256'],'Offline truth source mismatch')
            values=db.execute('''SELECT CAST("User ID" AS BIGINT),CAST("Login Timestamp" AS TIMESTAMP),CAST(campaign_id AS VARCHAR) FROM read_parquet(?) WHERE organization=? AND is_synthetic=true AND credential_stuffing_label=1 ORDER BY 2,1,3''',[str(path),org]).fetchall()
            require(len(values)==branch['synthetic_events'] and len({u for u,t,c in values})==branch['targeted_users'],'Offline target/exposure census mismatch')
            require(bool(values)==(org in row['targeted_organizations']),'Targeted-org source mismatch')
            for u,t,c in values:
                require(c is not None,'Missing campaign identity');ids.add(c);events.append(dict(variant_id=row['variant_id'],campaign_id=c,organization=org,user_id=int(u),at=t))
    finally:db.close()
    require(len(ids)==1,'Accepted one-campaign branch requires explicit metadata for any additional campaign; do not merge silently')
    spec=dict(variant_id=row['variant_id'],campaign_id=next(iter(ids)),start=datetime.fromisoformat(row['start']),end=datetime.fromisoformat(row['end_exclusive']),targeted_organizations=row['targeted_organizations'],seed=row['seed'],factors=row['factors'])
    return [spec],events,pins

def canonical_results(value):return json.dumps(value,sort_keys=True,separators=(',',':'))

def breakdowns(result,inventory_rows):
    fields=['family','RIP_target','Raccount_target','Sorg_target'];groups=defaultdict(list)
    for r in inventory_rows:groups[tuple(r['factors'][k] for k in fields)+(r['seed'],)].append(r['variant_id'])
    output=[]
    for detector in FAMILIES:
        by_id={r['variant_id']:r for r in result['campaign_results'] if r['detector_family']==detector}
        for key,ids in sorted(groups.items()):
            evaluated=[by_id[v] for v in ids if v in by_id and by_id[v]['evaluable']];n=len(evaluated);undetected=sum(r['primary_all_targeted_undetected'] for r in evaluated)
            output.append(dict(detector_family=detector,**dict(zip(fields,key[:4])),seed=key[4],required_campaigns=len(ids),evaluated_complete_campaigns=n,pending_campaigns=len(ids)-n,
                detected_campaigns=n-undetected,undetected_campaigns=undetected,undetected_fraction=undetected/n if n else None,denominator_definition='complete evaluable isolated campaign instances in this design-family/factor/seed cell'))
    return output

def pilot():
    cfg,p=pinned();out=BASE/'representative_v1';require(not out.exists(),'Pilot outputs are append-only; do not overwrite');out.mkdir()
    clock=time.perf_counter();rows=load(BASE/'required_val_inventory_v1.json');row=next(r for r in rows if r['variant_id']==cfg['predetermined_representative'])
    before=time.perf_counter();decisions,alternative,coverage,proof,hashes=sealed_decisions(row['variant_id']);reuse_seconds=time.perf_counter()-before
    specs,evidence,pins=truth_for_variant(row);before=time.perf_counter();result=evaluate_campaigns(specs,evidence,decisions,coverage);evaluation_seconds=time.perf_counter()-before
    repeated=evaluate_campaigns(list(reversed(specs)),list(reversed(evidence)),list(reversed(alternative)),coverage)
    require(result==repeated,'Campaign attribution changed under equivalent independent score inputs/order')
    for org in ['Org1','Org2','Org3','Org4','Org5']:
        private=out/org/'private';private.mkdir(parents=True)
        for name,key in [('target_user_results.jsonl','private_user_results'),('alert_attribution.jsonl','private_alert_attribution')]:
            with (private/name).open('x',encoding='utf-8') as f:
                for r in result[key]:
                    if r['organization']==org:f.write(canonical_results(r)+'\n')
    for name,key in [('organization_results.csv','organization_results'),('campaign_results.csv','campaign_results')]:
        with (out/name).open('x',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(result[key][0]));writer.writeheader();writer.writerows(result[key])
    cells=breakdowns(result,rows);dump_json(out/'factor_seed_coverage.json',cells)
    digest=hashlib.sha256(canonical_results(result).encode()).hexdigest()
    summary=dict(status='PASS_PREDETERMINED_REPRESENTATIVE_METHOD_VERIFICATION_ONLY',subphase8_status='IN_PROGRESS',required_val_instances=171,evaluated_val_instances=1,pending_val_instances=170,
        variant_id=row['variant_id'],organization_results=result['organization_results'],campaign_results=result['campaign_results'],paired_operational_decision_rows=len(decisions),
        positive_targeting_evidence_rows=len(evidence),reuse_equivalence=proof,campaign_attribution_reproduced=True,campaign_attribution_digest=digest,
        measured_seconds=dict(accepted_decision_verification=reuse_seconds,offline_campaign_evaluation=evaluation_seconds,pilot_total=time.perf_counter()-clock),
        policy_sha256=p['configuration_sha256'],primary_protocol_sha256=cfg['primary_protocol_sha256'],input_sha256={**hashes,**pins.checked},
        labels_used_only_offline=True,test_files_opened=0,models_retrained=False,thresholds_recalibrated=False,full_sweep_launched=False,
        limitation='One fixed VAL instance verifies method, not full detectability boundary. All uncomputed factor/seed cells remain pending, not undetected. No causal/operational FPR claim.')
    pins.verify_unchanged();pinned();dump_json(out/'summary.json',summary)
    dump_json(out/'artifact_sha256.json',{x.relative_to(out).as_posix():sha(x) for x in out.rglob('*') if x.is_file()})
    print(json.dumps(dict(status=summary['status'],evaluated=1,required=171,pending=170,seconds=summary['measured_seconds'])),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--representative',action='store_true');args=parser.parse_args()
    if args.freeze:freeze()
    elif args.representative:pilot()
