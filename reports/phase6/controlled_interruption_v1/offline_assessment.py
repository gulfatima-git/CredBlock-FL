"""Authorized post-exit audit on sealed forensic copies. No model forward."""
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict,Counter
import hashlib,json,math,os,shutil,sqlite3,sys,time
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');sys.path.insert(0,str(ROOT))
REPORT=Path(__file__).resolve().parent
PHYSICAL=ROOT/'reports/phase6/v2_forensic_v1/physical'
LOGICAL=ROOT/'reports/phase6/v2_verify_v1'
from src.phase6 import independent_test_validation_v1 as independent
from src.phase6.continuation_wal_v4 import analyze,image_signature,sql_digest
ORGS=independent.ORGS
def need(ok,message):
    if not ok:raise ValueError(message)
def sha(p):return independent.sha(p)
def read(p):return independent.read(p)
def dump(name,v):independent.dump(REPORT/name,v)
def readonly(path):
    path=Path(path).resolve();need(path.is_relative_to(LOGICAL) or path.is_relative_to(PHYSICAL),'Audit database escaped forensic namespaces')
    return sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)

def derive(manifest):
    """Distinct audit view; never a v4 certificate or substitution in originals."""
    need(not LOGICAL.exists(),'No overwrite of existing verification tree');LOGICAL.mkdir()
    sets=manifest['database_sets'];nonempty=any(s['wal'] and s['wal']['size'] for s in sets)
    need(all(s['rollback'] is None or s['rollback']['size']==0 for s in sets),'Unresolved rollback journal requires review')
    # Use exact immutable snapshot directly when no WAL frames require projection.
    if not nonempty:
        reports=[]
        for record in sets:
            p=PHYSICAL/record['database'];db=readonly(p)
            try:need(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Forensic SQLite integrity failure: '+record['database'])
            finally:db.close()
            reports.append(dict(database=record['database'],status='PASS_SELF_CONTAINED_FORENSIC_DB',physical_sha256=sha(p),WAL=record['wal'],SHM=record['shm']))
        dump('database_derivations.json',dict(status='PASS_ALL_DATABASE_SETS',nonempty_WAL=0,sets=reports,run=str(PHYSICAL)))
        return PHYSICAL
    # Create a NEW logical audit tree only; all source/certificate bytes remain.
    for rel,desc in manifest['files'].items():
        if rel.endswith(('.sqlite','.sqlite-wal','.sqlite-shm','.sqlite-journal')):continue
        p=LOGICAL/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PHYSICAL/rel,p);need(sha(p)==desc['sha256'],'Audit artifact copy differs')
    reports=[]
    for record in sets:
        relative=record['database'];source=PHYSICAL/relative;wal=Path(str(source)+'-wal')
        raw=source.read_bytes();analysis,image=analyze(raw,wal.read_bytes() if wal.exists() else None)
        need(analysis['partial_tail_bytes']==0,'Partial WAL requires explicit review: '+relative)
        need(record['rollback'] is None or record['rollback']['size']==0,'Unresolved rollback journal: '+relative)
        output=LOGICAL/relative;output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as f:f.write(image);f.flush();os.fsync(f.fileno())
        signature=image_signature(output)
        oracle=REPORT/'wal_oracle_copies'/Path(relative).parent;oracle.mkdir(parents=True,exist_ok=True)
        for suffix in ('','-wal','-shm'):
            p=Path(str(source)+suffix)
            if p.exists():shutil.copyfile(p,oracle/('local.sqlite'+suffix))
        db=sqlite3.connect((oracle/'local.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            need(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Independent WAL oracle integrity failed')
            need(sql_digest(db)==signature,'Independent WAL committed view differs')
        finally:db.close()
        reports.append(dict(database=relative,status='PASS_SEPARATE_COMMITTED_IMAGE',physical_sha256=sha(source),derived_sha256=sha(output),analysis=analysis,signature=signature))
    dump('database_derivations.json',dict(status='PASS_ALL_DATABASE_SETS',nonempty_WAL=sum(bool(s['wal'] and s['wal']['size']) for s in sets),sets=reports,run=str(LOGICAL),role='Offline verification only; not a v4 continuation certificate'))
    return LOGICAL

def journal(directory):
    records=[];previous='0'*64
    for n,p in enumerate(sorted(directory.glob('barriers.*.jsonl'))):
        need(p.name==f'barriers.{n:06d}.jsonl','Noncontiguous journal segment')
        for line in p.read_bytes().splitlines(keepends=True):
            need(line.endswith(b'\n'),'Unresolved partial journal tail')
            row=json.loads(line);body=dict(row);value=body.pop('sha256')
            need(row['seq']==len(records) and row['prev']==previous and independent.digest(body)==value and independent.digest(row['body'])==row['body_sha256'],'Journal-chain failure')
            records.append(row);previous=value
    need(records and records[0]['body']['event']=='IDENTITY','Missing journal identity')
    return records,previous

def sharing_prefix(root,policy):
    """Independent committed-stage oracle, also permits an incomplete final barrier."""
    records,last=journal(root/'sharing/progress');stages={};refs={}
    kinds={'BEGIN','COMPLETE','LOCAL','ISSUANCE','PUBLISHED','PAIRED','PUBLICATION_PREPARED','RECEIPT'}
    for row in records:
        b=row['body'];event=b['event']
        need(event in kinds|{'IDENTITY'},'Unexpected or failed original sharing stage requires review')
        if event in kinds:
            key=(event,b.get('at'),b.get('organization'),b.get('key'));need(key not in stages,'Duplicate journal stage');stages[key]=b
        if 'path' in b:
            p=(root/'sharing'/b['path']).resolve();need(p.is_relative_to(root/'sharing') and sha(p)==b['sha256'],'Sharing referenced file differs');refs[event,b['at'],b.get('organization')]=read(p)
    local_by_org={o:{} for o in ORGS};until={};indicators={};expired=set();complete=[];pending=[];published=0;paired=0;receipts=0
    def value(event,at,org=None):return refs.get((event,at,org))
    begins=[r['body'] for r in records if r['body']['event']=='BEGIN']
    need([b['at'] for b in begins]==sorted(set(b['at'] for b in begins)),'Nonchronological barriers')
    for index,begin in enumerate(begins):
        at=begin['at'];t=datetime.fromisoformat(at);expected=[];is_complete=('COMPLETE',at,None,None) in stages
        need(is_complete or index==len(begins)-1,'Incomplete non-final barrier')
        for org in sorted(begin['frames']):
            local=value('LOCAL',at,org)
            if local is None:
                need(not is_complete and value('ISSUANCE',at,org) is None,'Issuance without LOCAL');continue
            local_by_org[org][at]=local;issued=[]
            for score in sorted(local['scores'],key=lambda r:(r['user_id'],r['alert_id'] or '')):
                flag=score['threshold_hex'] is not None and float.fromhex(score['logit_hex'])>=float.fromhex(score['threshold_hex'])
                need(flag==(score['decision']=='ALERT'),'Local binary64 mismatch')
                if not flag:continue
                ips=sorted({ip for when,u,ip in local['recent'] if u==score['user_id'] and t-timedelta(seconds=policy['attribution_window_seconds'])<datetime.fromisoformat(when)<=t})
                for ip in ips:
                    if until.get((org,ip),datetime.min)>t:continue
                    expiry=t+timedelta(seconds=policy['ttl_seconds']);until[org,ip]=expiry
                    issued.append(dict(indicator_id=independent.digest([policy['version'],org,ip,at]),ip=ip,issuer=org,issued_at=at,available_at=at,expires_at=expiry.isoformat(),policy_version=policy['version'],status=policy['status']))
            issuance=value('ISSUANCE',at,org)
            if issuance is not None:need(issuance['payloads']==issued,'Alert/IP attribution or suppression differs');expected.extend(issued)
            else:need(not is_complete,'Missing complete issuance')
        proof=value('PUBLISHED',at)
        if proof is not None:
            need(all(value('ISSUANCE',at,o) is not None for o in begin['frames']),'Publication before all local issuances')
            need(proof['payloads']==expected,'Publication payload set differs')
            need(set(proof['recipients'])==set(ORGS) and all(all(e.get('organization')==o for e in log) for o,log in proof['recipients'].items()),'Recipient organization identity differs')
            before={k for k,p in indicators.items() if datetime.fromisoformat(p['expires_at'])<=t and k not in expired}
            events=[e for e in proof['events'] if e['event']=='expiry'];need(len(events)==len(before) and {e['indicator_id'] for e in events}==before and all(e['at']==indicators[e['indicator_id']]['expires_at'] for e in events),'Exclusive indicator expiry differs');expired.update(before)
            actual=Counter((e['indicator_id'],o,e['at']) for o,events in proof['recipients'].items() for e in events if e['event']=='receipt')
            wanted=Counter((p['indicator_id'],o,at) for p in expected for o in ORGS if o!=p['issuer']);need(actual==wanted,'Receipt/availability differs');receipts+=sum(actual.values())
            indicators.update({p['indicator_id']:p for p in expected});published+=1
        else:need(not is_complete,'Missing complete publication')
        for org in begin['frames']:
            pair=value('PAIRED',at,org)
            if pair is None:need(not is_complete,'Missing complete paired decision');continue
            need(proof is not None,'Paired decision before publication');local=local_by_org[org][at]
            scores={s['user_id']:s for s in local['scores']};current={int(u):set(v) for u,v in local['current'].items()}
            need(len(pair['paired'])==len(scores) and {r['user_id'] for r in pair['paired']}==set(scores),'Paired population differs')
            def hits(u):return sorted(k for k,p in indicators.items() if p['issuer']!=org and p['ip'] in current.get(u,set()) and datetime.fromisoformat(p['available_at'])<=t<datetime.fromisoformat(p['expires_at']))
            for r in pair['paired']:
                s=scores[r['user_id']];flag=s['decision']=='ALERT';ids=hits(r['user_id'])
                need(r['logit_hex']==s['logit_hex'] and r['threshold_hex']==s['threshold_hex'] and r['local_alert']==flag and r['indicator_ids']==ids and r['local_plus_indicator_alert']==(flag or bool(ids)),'Paired decision differs')
            need({r['user_id'] for r in pair['additional_event_users']}==set(current)-set(scores),'Additional-event population differs')
            for r in pair['additional_event_users']:need(r['local_status']=='NOT_SCORED' and r['indicator_ids']==hits(r['user_id']) and r['local_plus_indicator_alert']==bool(hits(r['user_id'])),'Additional event indicator mismatch')
            paired+=1
        if is_complete:complete.append(at)
        else:pending.append(dict(at=at,organizations=sorted(begin['frames']),stages={o:dict(LOCAL=value('LOCAL',at,o) is not None,ISSUANCE=value('ISSUANCE',at,o) is not None,PAIRED=value('PAIRED',at,o) is not None) for o in begin['frames']},PUBLISHED=proof is not None))
    return local_by_org,dict(status='PASS_COMMITTED_SHARING_PREFIX',journal_chain_sha256=last,completed_barriers=len(complete),latest_completed_barrier=complete[-1] if complete else None,pending=pending,published=published,paired_records=paired,receipts=receipts,indicator_episodes=len(indicators))

def assess_partial(root,entry,thresholds,original,policy):
    from src.organization.rolling_graph_v1 import RollingGraph,OBSERVABLE,HISTORY,RECENT
    from src.phase6.heldout_contract_v2 import Catalog,Branch,Scope
    from src.phase6.heldout_grid_v2 import EvaluationContext
    catalog=Catalog.permitted_metadata();bindings=read(root/'bindings.json');identity=read(root/'identity.json')
    need(set(bindings)==set(ORGS) and identity['variant']==entry['variant_id'],'Incomplete instance identities differ')
    need(identity['adapter']==Scope.current_adapter_identity() and identity['catalog']==catalog.identity,'Incomplete original code/catalog identity differs')
    records,_=journal(root/'sharing/progress');header=records[0]['body']['identity']
    need(header==dict(version='heldout-barrier-v2',adapter=identity['adapter'],catalog=catalog.identity,branches={o:Branch(**bindings[o]).identity for o in ORGS}),'Sharing journal origin/branch identities differ')
    local,sharing=sharing_prefix(root,policy);orgs=[]
    for org in ORGS:
        branch=Branch(**bindings[org]);context=EvaluationContext.bind(catalog,branch);bytime=defaultdict(list);grid_records=[]
        gp=root/org/'private/grid_progress'
        if gp.exists():
            records,_=journal(gp)
            for record in records:
                b=record['body']
                if b['event']!='GRID_COMMIT':continue
                raw=b['raw'];det=b['key'];seal=context.seal(det)
                need(raw['asof']==b['at'] and raw['asof'] in [t.isoformat() for t in branch.grid] and raw['organization']==org and raw['variant_id']==entry['variant_id'],'Grid identity/time mismatch')
                need(raw['adapter_identity']==identity['adapter'] and raw['context_identity']==context.identity and raw['branch_identity']==branch.identity and raw['manifest_sha256']==entry['manifest_sha256'],'Grid source/context differs')
                need(raw['model_identity']==json.loads(seal.identity_json) and raw['model_state_digest']==seal.state_digest and raw['threshold']==thresholds[org,det]['calibration']['threshold'] and raw['feature_schema_sha256']==catalog.schema_sha256 and raw['sampler_configuration_identity_sha256']==independent.digest(json.loads(seal.sampler_json)),'Grid frozen bundle/schema/sampler differs')
                need(len({r['user_id'] for r in raw['roots']})==len(raw['roots']),'Duplicate grid Users')
                for r in raw['roots']:need(math.isfinite(float.fromhex(r['logit_hex'])) and r['alert']==(raw['threshold']['kind']=='finite' and float.fromhex(r['logit_hex'])>=float.fromhex(raw['threshold']['hex'])),'Grid binary64 decision differs')
                published=root/org/'private'/f"grid_{datetime.fromisoformat(b['at']).minute:02d}_{det}.json"
                if published.exists():need(read(published)==raw,'Published grid differs from committed grid')
                bytime[b['at']].append(raw);grid_records.append(dict(at=b['at'],detector=det,published=published.exists(),saved_rows=len(raw['roots'])))
        db=readonly(root/org/'private/local.sqlite')
        try:
            need(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Partial DB integrity failed')
            expected=next(v['identity'] for v in original if v['organization']==org and v['detector']=='graphsage')
            meta=json.loads(db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])
            need(meta['format']=='phase6-local-inference-store-v1' and meta['split']=='TEST' and meta['organization']==org and meta['stream_id']==entry['variant_id'] and meta['bundle']==expected and meta['config_sha256']==independent.digest(json.loads(catalog.inference_config_json)),'Partial store/model identity differs')
            source=meta['source_identity'];info=next(b for b in entry['branches'] if b['organization']==org)
            need(source['anchor']==entry['anchor'] and source['end_exclusive']==entry['end'] and source['observations_sha256']==info['observations_sha256'] and source['history_reference_sha256']==info['history_reference_sha256'],'Partial immutable input identity differs')
            checkpoints=db.execute('SELECT seq,graph,sha256 FROM checkpoints ORDER BY seq').fetchall();cpmap={seq:(blob,h) for seq,blob,h in checkpoints}
            need(0 in cpmap and all(hashlib.sha256(blob).hexdigest()==h for seq,blob,h in checkpoints),'Checkpoint bytes failed hash')
            graph=RollingGraph.from_checkpoint_bytes(cpmap[0][0]);need(graph.organization==org,'Foreign initial graph')
            start=branch.start;end=branch.stop
            need(all(start-timedelta(days=7)<=e.time<start for e in graph.history_events),'Noncausal warmup checkpoint')
            adjacency=defaultdict(set)
            for u,ip in graph.retained.edges:adjacency['U',u].add(('I',ip));adjacency['I',ip].add(('U',u))
            def reach(changed):
                seen=set(changed);front=set(changed)
                for _ in range(2):
                    nxt=set()
                    for node in front:nxt.update(adjacency.get(node,()))
                    front=nxt-seen;seen.update(front)
                return {u for kind,u in seen if kind=='U'}
            commands=db.execute('SELECT seq,asof,payload,event_offset,view_digest,timings FROM commands ORDER BY seq').fetchall()
            last=None;events=0;scores=0;tokens=[];unpublished=[];source_rows=[];cols=['user_id','logit_hex','threshold_hex','decision','alert_id','model_sha256','threshold_sha256']
            for n,(seq,at,payload,offset,view_digest,timings) in enumerate(commands,1):
                t=datetime.fromisoformat(at);p=json.loads(payload);ts=json.loads(timings)
                need(seq==n and start<=t<end and (last is None or t>last),'Partial command sequence/time differs');last=t
                rows=[dict(r,**{'Login Timestamp':datetime.fromisoformat(r['Login Timestamp'])}) for r in p['observations']]
                need(len(rows)==len(p['tokens']) and len(set(p['tokens']))==len(p['tokens']) and all(set(r)==set(OBSERVABLE) and r['organization']==org and r['Login Timestamp']==t for r in rows),'Partial command contains hidden/nonlocal evidence')
                source_rows.extend(p['observations']);events+=len(rows);need(offset==events and ts['input_events']==len(rows),'Partial committed input offsets differ');tokens.extend((token,seq) for token in p['tokens'])
                pairs={(r['User ID'],r['IP Address']) for r in rows}
                for queue,duration in ((graph.recent_events,RECENT),(graph.history_events,HISTORY)):
                    for e in queue:
                        if e.time>t-duration:break
                        pairs.add((e.user,e.ip))
                changed=set()
                for u,ip in pairs:changed.update((('U',u),('I',ip)))
                target=reach(changed)
                if rows:graph.ingest_batch(t,rows,p['tokens'])
                else:graph.advance(t)
                for u,ip in pairs:
                    a,b=('U',u),('I',ip)
                    if (u,ip) in graph.retained.edges:adjacency[a].add(b);adjacency[b].add(a)
                    else:adjacency[a].discard(b);adjacency[b].discard(a)
                target|=reach(changed);target={u for u in target if ('U',u) in graph.retained.nodes}
                if p['heartbeat']:target.update(u for kind,u in graph.recent.nodes if kind=='U')
                view=graph.view();need(view.digest()==view_digest,'Partial committed graph view differs')
                if seq in cpmap:need(hashlib.sha256(graph.checkpoint_bytes()).hexdigest()==cpmap[seq][1],'Periodic checkpoint differs from independent history replay')
                saved=[dict(zip(cols,r)) for r in db.execute('SELECT '+','.join(cols)+' FROM scores WHERE seq=? ORDER BY user_id',(seq,))]
                need({r['user_id'] for r in saved}==target and len(saved)==len(target)==ts['scored_users'],'Partial scoring target set differs')
                cut=thresholds[org,'graphsage']['calibration']['threshold']['hex']
                for s in saved:
                    z=float.fromhex(s['logit_hex']);need(math.isfinite(z) and s['threshold_hex']==cut and s['model_sha256']==expected['model_sha256'] and s['threshold_sha256']==expected['threshold_sha256'] and s['decision']==('ALERT' if cut is not None and z>=float.fromhex(cut) else 'NO_ALERT'),'Partial saved score/threshold/model differs')
                for real,z,schema,status,when in db.execute('SELECT logit,logit_hex,schema_sha256,processing_status,asof FROM scores WHERE seq=?',(seq,)):
                    need(real==float.fromhex(z) and schema==catalog.schema_sha256 and status=='OK' and when==at,'Partial score storage/identity differs')
                scores+=len(saved)
                exported=local[org].get(at)
                if exported:
                    need(exported['seq']==seq and exported['scores']==saved and exported['provenance']['view_digest']==view_digest and exported['provenance']['bundle']==expected and exported['provenance']['branch']==branch.identity,'Partial LOCAL export differs from SQL')
                    need(exported['recent']==[[e.time.isoformat(),e.user,e.ip] for e in graph.recent_events],'Partial alert attribution evidence differs')
                    current={}
                    for row in rows:current.setdefault(str(row['User ID']),set()).add(row['IP Address'])
                    need(exported['current']=={u:sorted(v) for u,v in current.items()},'Current IP attribution evidence differs')
                else:unpublished.append(dict(seq=seq,at=at,saved_scores=len(saved),role='Committed SQL; no LOCAL publication; reusable without inference'))
                if at in bytime:
                    roots={key[1] for key,x in zip(view.private_keys,view.x) if key[0]=='U' and x[5]>0}
                    for raw in bytime[at]:need(raw['view_digest']==view_digest and {r['user_id'] for r in raw['roots']}==roots,'Partial grid temporal view/targets differ')
            need(max(cpmap)<=len(commands),'Checkpoint beyond committed history')
            need(sorted(tokens)==db.execute('SELECT token,seq FROM event_tokens ORDER BY token').fetchall(),'Partial token ledger differs')
            need(db.execute('SELECT COUNT(*) FROM scores WHERE seq NOT IN (SELECT seq FROM commands)').fetchone()[0]==0,'Orphan committed scores')
            failures=db.execute('SELECT id,error_type,phase,requires_restart FROM failures').fetchall()
            need(not failures,'Partial store contains failures requiring review')
            need(all(at in {r[1] for r in commands} for at in local[org]),'LOCAL without committed SQL')
            # Independently compare the exact committed prefix with frozen observations.
            import duckdb
            q=duckdb.connect(':memory:')
            try:
                observations=ROOT/independent.REPLAY/entry['variant_id']/f'{org}_observations.parquet';need(sha(observations)==info['observations_sha256'],'Partial frozen observation source hash differs')
                expected_rows=[] if last is None else q.execute('SELECT organization,"Login Timestamp","User ID","IP Address",LoginSuccessful FROM read_parquet(?) WHERE "Login Timestamp"<=? ORDER BY 2,3,4,5',[str(observations),last]).fetchall()
                expected_rows=[dict(zip(OBSERVABLE,[o,t.isoformat(),u,ip,success])) for o,t,u,ip,success in expected_rows]
                need(source_rows==expected_rows,'Committed partial source prefix differs')
            finally:q.close()
            pending=[]
            for b in sharing['pending']:
                if org in b['organizations']:pending.append(dict(at=b['at'],SQL_committed=db.execute('SELECT 1 FROM commands WHERE asof=?',(b['at'],)).fetchone() is not None,LOCAL_published=b['stages'][org]['LOCAL']))
            orgs.append(dict(organization=org,status='PASS_COMMITTED_GRAPH_SQL_GRID_PREFIX',commands=len(commands),input_events=events,saved_scores=scores,last_committed_time=last.isoformat() if last else None,latest_checkpoint_seq=max(cpmap),checkpoint_rows=len(cpmap),committed_grid_bundles=len(grid_records),saved_grid_rows=sum(r['saved_rows'] for r in grid_records),unpublished_committed_SQL=unpublished,pending_commands=pending,GNN_forwards=0))
            print(json.dumps(dict(event='partial_org_verified',organization=org,commands=len(commands),saved_scores=scores)),flush=True)
        finally:db.close()
    result=dict(status='PASS_RECOVERABLE_INCOMPLETE_INSTANCE',variant_id=entry['variant_id'],organizations=orgs,sharing=sharing,complete=False,remaining_future_work='Continue only after separate approval; no final operational flush or full grid/completion claimed',GNN_forwards=0)
    dump('incomplete_instance_assessment.json',result);return result

def main():
    need((REPORT/'physical_snapshot_manifest.json').is_file(),'Snapshot preservation not complete')
    manifest=read(REPORT/'physical_snapshot_manifest.json');need(manifest['status']=='PASS_PHYSICAL_SNAPSHOT_HASH_PRESERVATION','Capture did not pass')
    run=derive(manifest);policy=read(ROOT/'configs/phase6/indicator_sharing_v1.json')
    inventory=read(ROOT/'reports/phase6/test_execution_preflight_v1/inventory.json');byvariant={r['variant_id']:r for r in inventory}
    thresholds={(o,d):read(ROOT/f'reports/phase6/calibration/v1/thresholds/{o}_{d}.json') for o in ORGS for d in ('graphsage','tabular_mlp')}
    original=read(ROOT/'reports/phase6/test_execution_preflight_v1/verified_model_threshold_bundles.json')
    models=[]
    for v in original:
        o,d=v['organization'],v['detector'];t=thresholds[o,d];model=Path(t['model_path']).resolve();need(model.is_relative_to(ROOT/'reports/phase6'),'Model escaped explicit archive scope')
        need(sha(model)==t['model_sha256']==v['identity']['model_sha256'],'Original model archive hash differs')
        p=ROOT/f'reports/phase6/calibration/v1/thresholds/{o}_{d}.json';need(sha(p)==v['identity']['threshold_sha256'],'Original threshold hash differs')
        models.append(dict(organization=o,detector=d,model_sha256=t['model_sha256'],threshold_sha256=sha(p),checkpoint_deserialized=False))
    dump('model_threshold_preservation.json',dict(status='PASS_10_ORIGINAL_MODEL_AND_THRESHOLD_PAIRS',pairs=models))
    completed=[];incomplete=[]
    for folder in sorted(p for p in run.iterdir() if p.is_dir()):
        if folder.name not in byvariant:continue
        if (folder/'completion.json').exists():
            report,_=independent.validate_instance(run,byvariant[folder.name],REPORT/'completed_audits'/folder.name,thresholds,policy)
            completed.append(dict(variant=folder.name,status=report['status'],organization_branches=report['organization_branches'],GNN_forwards=report['GNN_forwards']))
            print(json.dumps(dict(event='independent_complete_campaign_verified',variant=folder.name,verified=len(completed))),flush=True)
        else:incomplete.append(folder)
    need(len(incomplete)<=1,'Unexpected multiple incomplete instances')
    partial=[]
    for folder in incomplete:partial.append(assess_partial(folder,byvariant[folder.name],thresholds,original,policy))
    dump('recovery_assessment_summary.json',dict(status='PASS_POST_INTERRUPTION_RECOVERY_VERIFICATION',completed_verified=len(completed),required=171,completed=completed,incomplete=partial,GNN_forwards=0,production_v4_launch=False,production_pilot_authorized=False))
    print(json.dumps(dict(status='PASS_POST_INTERRUPTION_RECOVERY_VERIFICATION',completed_verified=len(completed),incomplete_instances=len(partial))),flush=True)

if __name__=='__main__':
    try:main()
    except BaseException as e:
        dump('assessment_failure_'+datetime.now().strftime('%H%M%S%f')+'.json',dict(status='STOP_INDEPENDENT_RECOVERY_CHECK_FAILED',error_type=type(e).__name__,message=str(e),GNN_forwards=0))
        raise
