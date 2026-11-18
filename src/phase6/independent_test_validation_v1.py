"""Offline held-out evidence audit. No GNN forward/training/calibration oracle.

Only completed, pre-label-sealed instances may be opened. Scientific outcomes
are recomputed from frozen labels/evidence and saved logits/transcripts, rather
than accepting the driver's completion status or calling its evaluators.
"""
from collections import Counter,defaultdict
from datetime import datetime,timedelta
import hashlib,json,math,sqlite3,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ORGS=tuple(f'Org{i}' for i in range(1,6))
REPLAY='data/phase5/controlled_replay_labels_all_orgs_causal_v1'
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canon(v).encode()).hexdigest()
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def need(ok,message):
    if not ok:raise ValueError(message)
def dump(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,indent=2);f.write('\n')

def counts_and_ap(rows):
    """Independent scalar counts and grouped-score AP; no driver helper."""
    c=dict(tp=0,fp=0,tn=0,fn=0);seen=set();groups=defaultdict(lambda:[0,0]);loss=0.
    for r in rows:
        key=(r['organization'],r['variant_id'],r['asof'],r['user_id'],r['detector'])
        need(key not in seen,'Duplicate fixed-grid User-time');seen.add(key)
        z=float.fromhex(r['logit_hex']);y=r['node_label'];th=r['threshold'];need(math.isfinite(z) and y in (0,1),'Invalid eligible score/label')
        alert=th['kind']=='finite' and z>=float.fromhex(th['hex'])
        need(alert==r['alert'],'Stored frozen-threshold decision differs')
        c['tp' if alert and y else 'fp' if alert else 'fn' if y else 'tn']+=1
        groups[z][0]+=y;groups[z][1]+=1;loss+=max(z,0)-z*y+math.log1p(math.exp(-abs(z)))
    tp,fp,tn,fn=(c[k] for k in ('tp','fp','tn','fn'));positives=tp+fn;negative=fp+tn
    cumulative=total=0;weighted=0.
    for z,(pos,n) in sorted(groups.items(),reverse=True):
        cumulative+=pos;total+=n;weighted+=pos*cumulative/total
    return dict(**c,eligible=len(rows),positive=positives,negative=negative,
        precision=tp/(tp+fp) if tp+fp else None,recall=tp/positives if positives else None,
        fpr=fp/negative if negative else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
        average_precision=weighted/positives if positives else None,bce=loss/len(rows) if rows else None)

def compare_metrics(actual,reported):
    for key,value in actual.items():
        expected=reported[key]
        need((value is None and expected is None) or (value is not None and expected is not None and abs(value-expected)<=1e-11),'Metric discrepancy: '+key)

def detection_summary(campaigns,organizations):
    """Keep campaign-anywhere, campaign-everywhere and User coverage distinct."""
    out={}
    for family in ('local_only','local_plus_indicator'):
        cs=[r for r in campaigns if r['detector_family']==family]
        os=[r for r in organizations if r['detector_family']==family]
        n=len(cs);undetected=sum(r['primary_all_targeted_undetected'] for r in cs)
        out[family]=dict(campaigns=n,detected_anywhere=n-undetected,wholly_undetected=undetected,
            wholly_undetected_percent=100*undetected/n if n else None,
            detected_every_targeted_organization=sum(r['all_organizations_detected'] for r in cs),
            organization_trials=len(os),detected_organization_trials=sum(r['detected'] for r in os),
            targeted_User_occurrences=sum(r['unique_exposed_target_users_summed_local'] for r in cs),
            detected_targeted_User_occurrences=sum(r['unique_detected_target_users_summed_local'] for r in cs),
            right_censored_campaigns=sum(r['right_censored'] for r in cs))
    return out

def factor_summaries(campaigns):
    cells=defaultdict(list)
    keys=('detector_family','family','RIP_target','Raccount_target','Sorg_target','seed')
    for r in campaigns:cells[canon({k:r[k] for k in keys})].append(r)
    return [dict(**json.loads(key),required_campaigns=len(rows),
        wholly_undetected=sum(r['primary_all_targeted_undetected'] for r in rows),
        all_targeted_organizations_detected=sum(r['all_organizations_detected'] for r in rows),
        right_censored=sum(r['right_censored'] for r in rows)) for key,rows in sorted(cells.items())]

def closed_sqlite(path):
    """Never create/checkpoint/delete SQLite sidecars during independent read."""
    path=Path(path);before={}
    for p in (path,Path(str(path)+'-wal'),Path(str(path)+'-shm')):
        before[str(p)]=dict(exists=p.exists(),size=p.stat().st_size if p.exists() else None,sha256=sha(p) if p.exists() else None)
    wal=Path(str(path)+'-wal');need(not wal.exists() or wal.stat().st_size==0,'Nonempty WAL blocks immutable inspection: '+str(wal))
    db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro&immutable=1',uri=True)
    need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity check failed')
    return db,before

def verify_local_graph(path,org,branch,raw_by_time,expected_identity,exported_local):
    """Replay accepted graph commands only; independently check target sets."""
    from src.organization.rolling_graph_v1 import RollingGraph,OBSERVABLE,HISTORY,RECENT
    db,before=closed_sqlite(path);comparisons=0;scores=alerts=events=0
    try:
        meta=read_json_value(db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])
        need(meta['organization']==org and meta['split']=='TEST' and meta['stream_id']==branch['variant_id'] and meta['bundle']==expected_identity,'Local SQLite bundle/scope identity mismatch')
        cp=db.execute('SELECT graph,sha256 FROM checkpoints WHERE seq=0').fetchone();need(cp and hashlib.sha256(cp[0]).hexdigest()==cp[1],'Initial graph checkpoint hash failed')
        graph=RollingGraph.from_checkpoint_bytes(cp[0]);need(graph.organization==org,'Foreign initial graph')
        start=datetime.fromisoformat(branch['anchor']);end=datetime.fromisoformat(branch['end'])
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
        commands=db.execute('SELECT seq,asof,payload,view_digest FROM commands ORDER BY seq').fetchall();last=None
        source_rows=[]
        for seq,at,payload,view_digest in commands:
            t=datetime.fromisoformat(at);need(start<=t<end and (last is None or t>last),'Local command outside/behind horizon');last=t
            p=json.loads(payload);rows=[dict(r,**{'Login Timestamp':datetime.fromisoformat(r['Login Timestamp'])}) for r in p['observations']]
            need(all(set(r)==set(OBSERVABLE) and r['organization']==org and r['Login Timestamp']==t for r in rows),'Hidden/noncausal observation column')
            source_rows.extend(p['observations']);events+=len(rows);changed=set();pairs=set()
            for r in rows:pairs.add((r['User ID'],r['IP Address']))
            for queue,duration in ((graph.recent_events,RECENT),(graph.history_events,HISTORY)):
                for e in queue:
                    if e.time>t-duration:break
                    pairs.add((e.user,e.ip))
            for u,ip in pairs:changed.update((('U',u),('I',ip)))
            expected=reach(changed)
            if rows:graph.ingest_batch(t,rows,p['tokens'])
            else:graph.advance(t)
            for u,ip in pairs:
                a,b=('U',u),('I',ip)
                if (u,ip) in graph.retained.edges:adjacency[a].add(b);adjacency[b].add(a)
                else:adjacency[a].discard(b);adjacency[b].discard(a)
            expected|=reach(changed);expected={u for u in expected if ('U',u) in graph.retained.nodes}
            if p['heartbeat']:expected.update(u for kind,u in graph.recent.nodes if kind=='U')
            records=db.execute('SELECT user_id,logit_hex,threshold_hex,decision,model_sha256,threshold_sha256,schema_sha256 FROM scores WHERE seq=? ORDER BY user_id',(seq,)).fetchall()
            need({r[0] for r in records}==expected and len(records)==len(expected),'Observable target-selection discrepancy')
            for uid,z,threshold,decision,model,th,schema in records:
                need(model==expected_identity['model_sha256'] and th==expected_identity['threshold_sha256'] and schema==expected_identity['feature_schema_sha256'],'Local score identity changed')
                flag=threshold is not None and float.fromhex(z)>=float.fromhex(threshold)
                need(flag==(decision=='ALERT'),'Local binary64 mismatch');scores+=1;alerts+=flag
            exported=exported_local[at]
            cols=['user_id','logit_hex','threshold_hex','decision','alert_id','model_sha256','threshold_sha256']
            originals=[dict(zip(cols,r)) for r in db.execute('SELECT '+','.join(cols)+' FROM scores WHERE seq=? ORDER BY user_id',(seq,))]
            need(exported['seq']==seq and exported['scores']==originals and exported['provenance']['view_digest']==view_digest,'Local export differs from original committed SQLite scores')
            need(exported['recent']==[[e.time.isoformat(),e.user,e.ip] for e in graph.recent_events],'Local recent evidence differs from graph runtime')
            current={}
            for r in rows:current.setdefault(str(r['User ID']),set()).add(r['IP Address'])
            need(exported['current']=={u:sorted(v) for u,v in current.items()},'Indicator target IPs differ from actual current authentication')
            if at in raw_by_time:
                view=graph.view();need(view.digest()==view_digest,'Grid source command digest mismatch')
                expected_roots={key[1] for key,x in zip(view.private_keys,view.x) if key[0]=='U' and x[5]>0}
                for raw in raw_by_time[at]:
                    need(raw['view_digest']==view.digest() and {r['user_id'] for r in raw['roots']}==expected_roots and len(raw['roots'])==len(expected_roots),'Primary raw-view/root census differs')
            if p['final']:need(t==end-timedelta(microseconds=1) and graph.view().digest()==view_digest,'Final coverage/digest failed')
            comparisons+=1
        need(last==end-timedelta(microseconds=1),'Missing complete final-ten-minute flush')
    finally:db.close()
    for name,old in before.items():
        p=Path(name);need(p.exists()==old['exists'] and (not p.exists() or sha(p)==old['sha256']),'Immutable SQLite/sidecar changed during audit')
    return dict(organization=org,commands=comparisons,scores=scores,alerts=alerts,events=events,sqlite_and_sidecars=before),source_rows

def read_json_value(v):return json.loads(v)

def campaign_oracle(specs,evidence,decisions):
    """Independent recent-event scan; never calls accepted campaign evaluator."""
    by_user=defaultdict(list);targets=defaultdict(set);onsets={};first={};attribution=Counter();seen=set()
    specmap={(s['variant_id'],s['campaign_id']):s for s in specs}
    for e in evidence:
        key=e['variant_id'],e['campaign_id'];s=specmap[key];need(e['organization'] in s['targeted_organizations'] and s['start']<=e['at']<s['end'],'Out-of-horizon targeting evidence')
        by_user[e['variant_id'],e['organization'],e['user_id']].append(e);targets[key,e['organization']].add(e['user_id']);onsets[key]=min(onsets.get(key,e['at']),e['at'])
    for d in decisions:
        unit=d['variant_id'],d['organization'],d['user_id'],d['at'],d['family'];need(unit not in seen,'Duplicate operational decision');seen.add(unit)
        if not d['alert']:continue
        matches=set()
        for e in by_user[d['variant_id'],d['organization'],d['user_id']]:
            s=specmap[e['variant_id'],e['campaign_id']]
            if d['at']-timedelta(minutes=10)<e['at']<=d['at']<s['end']:matches.add(e['campaign_id'])
        attribution['UNIQUE' if len(matches)==1 else 'AMBIGUOUS' if matches else 'UNATTRIBUTED']+=1
        if len(matches)==1:
            key=d['variant_id'],next(iter(matches)),d['organization'],d['user_id'],d['family'];first[key]=min(first.get(key,d['at']),d['at'])
    users=[];organizations=[];campaigns=[]
    for key,s in sorted(specmap.items()):
        onset=onsets.get(key);need(onset is not None,'Expected frozen campaign exposure missing')
        for family in ('local_only','local_plus_indicator'):
            detected_times=[];detected_orgs=0;total_targets=detected_users=0
            for org in s['targeted_organizations']:
                found=[]
                for u in sorted(targets[key,org]):
                    t=first.get((*key,org,u,family));total_targets+=1;detected_users+=int(t is not None)
                    if t is not None:found.append(t)
                    users.append(dict(variant_id=key[0],campaign_id=key[1],organization=org,user_id=u,family=family,first_detection=t.isoformat() if t else None,right_censored=t is None))
                when=min(found) if found else None;detected_orgs+=int(when is not None)
                if when is not None:detected_times.append(when)
                organizations.append(dict(variant_id=key[0],campaign_id=key[1],organization=org,detector_family=family,detected=when is not None,
                    unique_exposed_target_users=len(targets[key,org]),unique_detected_target_users=len(found),
                    first_qualifying_alert=when.isoformat() if when else None,event_time_seconds=(when-onset).total_seconds() if when else None,
                    right_censored=when is None,censor_time_seconds=(s['end']-onset).total_seconds()))
            when=min(detected_times) if detected_times else None
            campaigns.append(dict(variant_id=key[0],campaign_id=key[1],detector_family=family,detected_organizations=detected_orgs,
                any_organization_detected=detected_orgs>0,all_organizations_detected=detected_orgs==len(s['targeted_organizations']),
                primary_all_targeted_undetected=detected_orgs==0,event_time_seconds=(when-onset).total_seconds() if when else None,
                right_censored=when is None,censor_time_seconds=(s['end']-onset).total_seconds(),
                unique_exposed_target_users_summed_local=total_targets,unique_detected_target_users_summed_local=detected_users))
    return dict(users=users,organizations=organizations,campaigns=campaigns,attribution=dict(attribution))

def read_sharing(root,seal,policy):
    """Independent causal indicator reconstruction from sealed source records."""
    stages={};last='0'*64;seq=0
    for name in sorted(k for k in seal['files_sha256'] if k.startswith('sharing/progress/barriers.')):
        for line in (root/name).read_bytes().splitlines(keepends=True):
            if not line.endswith(b'\n'):break
            r=json.loads(line);h=r['sha256'];body={k:v for k,v in r.items() if k!='sha256'}
            need(r['seq']==seq and r['prev']==last and digest(body)==h and digest(r['body'])==r['body_sha256'],'Independent journal checksum/chain discrepancy')
            seq+=1;last=h;b=r['body']
            if b['event'] in ('BEGIN','COMPLETE','LOCAL','ISSUANCE','PUBLISHED','PAIRED'):
                key=b['event'],b.get('at'),b.get('organization');need(key not in stages,'Duplicate evidence stage');stages[key]=b
    need(last==seal['journal_chain_sha256'],'Journal final chain digest differs')
    def get(event,at,org=None):
        b=stages[event,at,org];p='sharing/'+b['path'];need(seal['files_sha256'][p]==b['sha256'],'Unsealed journal reference');return read(root/p)
    indicators={};until={};expired=set();decisions=[];local_by_org=defaultdict(dict);created=receipts=0
    for _,at,_ in sorted((k for k in stages if k[0]=='BEGIN'),key=lambda k:k[1]):
        t=datetime.fromisoformat(at);need(('COMPLETE',at,None) in stages,'Incomplete timestamp barrier');begin=stages['BEGIN',at,None];issued=[]
        for org in sorted(begin['frames']):
            local=get('LOCAL',at,org);local_by_org[org][at]=local
            for s in sorted(local['scores'],key=lambda r:(r['user_id'],r['alert_id'] or '')):
                flag=s['threshold_hex'] is not None and float.fromhex(s['logit_hex'])>=float.fromhex(s['threshold_hex']);need(flag==(s['decision']=='ALERT'),'Local frozen decision mismatch')
                if not flag:continue
                for ip in sorted({ip for when,u,ip in local['recent'] if u==s['user_id'] and t-timedelta(seconds=policy['attribution_window_seconds'])<datetime.fromisoformat(when)<=t}):
                    if until.get((org,ip),datetime.min)>t:continue
                    expiry=t+timedelta(seconds=policy['ttl_seconds']);until[org,ip]=expiry
                    issued.append(dict(indicator_id=digest([policy['version'],org,ip,at]),ip=ip,issuer=org,issued_at=at,available_at=at,expires_at=expiry.isoformat(),policy_version=policy['version'],status=policy['status']))
        publication=get('PUBLISHED',at);need(publication['payloads']==issued,'Observed-alert/IP attribution or suppression differs')
        for p in issued:need(set(p)=={'indicator_id','ip','issuer','issued_at','available_at','expires_at','policy_version','status'},'Private indicator field leaked')
        expected_receipts=Counter((p['indicator_id'],org,at) for p in issued for org in ORGS if org!=p['issuer'])
        actual_receipts=Counter((r['indicator_id'],org,r['at']) for org,log in publication['recipients'].items() for r in log if r['event']=='receipt')
        need(expected_receipts==actual_receipts,'Indicator receipt/availability discrepancy');created+=len(issued);receipts+=sum(actual_receipts.values())
        expected_expiry={k for k,p in indicators.items() if datetime.fromisoformat(p['expires_at'])<=t and k not in expired}
        expiry=[e for e in publication['events'] if e['event']=='expiry']
        need(len(expiry)==len(expected_expiry) and {e['indicator_id'] for e in expiry}==expected_expiry and all(e['at']==indicators[e['indicator_id']]['expires_at'] for e in expiry),'Exclusive expiry discrepancy')
        expired.update(expected_expiry);indicators.update({p['indicator_id']:p for p in issued})
        for org in begin['frames']:
            local=local_by_org[org][at];pair=get('PAIRED',at,org);current={int(u):set(ips) for u,ips in local['current'].items()};original={s['user_id']:s for s in local['scores']}
            need(len(pair['paired'])==len(original) and {r['user_id'] for r in pair['paired']}==set(original),'Paired operational population differs')
            def hits(u):return sorted(k for k,p in indicators.items() if p['issuer']!=org and p['ip'] in current.get(u,set()) and datetime.fromisoformat(p['available_at'])<=t<datetime.fromisoformat(p['expires_at']))
            for r in pair['paired']:
                s=original[r['user_id']];flag=s['decision']=='ALERT';ids=hits(r['user_id'])
                need(r['local_alert']==flag and r['logit_hex']==s['logit_hex'] and r['threshold_hex']==s['threshold_hex'] and r['indicator_ids']==ids and r['local_plus_indicator_alert']==(flag or bool(ids)),'Causal paired decision discrepancy')
                for family,alert in [('local_only',flag),('local_plus_indicator',flag or bool(ids))]:decisions.append(dict(variant_id=pair['variant_id'],organization=org,user_id=r['user_id'],at=t,family=family,alert=alert))
            need({r['user_id'] for r in pair['additional_event_users']}==set(current)-set(original),'Additional event population differs')
            for r in pair['additional_event_users']:
                ids=hits(r['user_id']);need(r['indicator_ids']==ids and r['local_plus_indicator_alert']==bool(ids) and r['local_status']=='NOT_SCORED','Additional indicator use differs')
                decisions.append(dict(variant_id=pair['variant_id'],organization=org,user_id=r['user_id'],at=t,family='local_plus_indicator',alert=bool(ids)))
    return decisions,local_by_org,dict(indicators=created,receipts=receipts,timestamp_barriers=sum(k[0]=='COMPLETE' for k in stages),operational_decisions=len(decisions))

def validate_instance(run,entry,destination,thresholds,policy):
    """Read an actually COMPLETE instance only, never infer or repair outputs."""
    started=time.perf_counter();root=run/entry['variant_id'];completion=read(root/'completion.json');seal=read(root/'score_seal.json')
    need(completion['status']=='COMPLETE_VALIDATED' and seal['status']=='SCORES_SEALED_BEFORE_LABELS','Incomplete instance')
    for relative,h in completion['files_sha256'].items():
        p=(root/relative).resolve();need(p.is_relative_to(root.resolve()) and sha(p)==h,'Authoritative completion hash mismatch')
    need(completion['files_sha256']['score_seal.json']==sha(root/'score_seal.json'),'Score seal identity mismatch')
    results=read(root/'public_results.json');bindings=read(root/'bindings.json');need(set(bindings)==set(ORGS),'Missing branch binding')
    frames,local,sstats=read_sharing(root,seal,policy);all_rows={d:[] for d in ('graphsage','tabular_mlp')};perorg={};sidecars=[];graph_reports=[]
    import duckdb
    sql=duckdb.connect(':memory:')
    try:
        for org in ORGS:
            info=next(b for b in entry['branches'] if b['organization']==org);anchor=datetime.fromisoformat(entry['anchor']);bytime={};eligible_by_d={d:[] for d in all_rows}
            labelpath=ROOT/REPLAY/entry['variant_id']/f'{org}_labels.parquet';need(sha(labelpath)==info['labels_sha256'],'Frozen TEST label hash differs')
            for minute in (0,10,20,30,40,50):
                at=anchor+timedelta(minutes=minute)
                q=sql.execute('SELECT * FROM read_parquet(?) WHERE label_time=? AND contains(query_kind,\'grid_snapshot\') ORDER BY "User ID"',[str(labelpath),at]);columns=[v[0] for v in q.description];labels=[dict(zip(columns,x)) for x in q.fetchall()]
                need(len({r['User ID'] for r in labels})==len(labels),'Duplicate fixed-grid labels')
                for d in all_rows:
                    raw=read(root/org/'private'/f'grid_{at.minute:02d}_{d}.json');bytime.setdefault(at.isoformat(),[]).append(raw);th=thresholds[org,d]
                    need(raw['organization']==org and raw['variant_id']==entry['variant_id'] and raw['asof']==at.isoformat() and raw['manifest_sha256']==entry['manifest_sha256'] and raw['threshold']==th['calibration']['threshold'],'Raw score provenance differs')
                    need(raw['model_identity']['model_sha256']==th['model_sha256'] and raw['model_state_digest']==th['model_version']['state_digest'],'Raw model version differs')
                    need(digest(raw) in seal['raw_score_digests'],'Raw scores absent from pre-label seal')
                    scores={r['user_id']:r for r in raw['roots']};need(len(scores)==len(raw['roots']),'Duplicate raw roots')
                    for row in labels:
                        y=row['node_label'];eligible=row['supervision_eligible']
                        need(row['organization']==org and row['split']=='TEST' and row['variant_id']==entry['variant_id'] and row['label_time']==at and y in (-1,0,1) and type(eligible)is bool and eligible==(y!=-1),'Eligibility/split/identity discrepancy')
                        if y==1:need(at-timedelta(minutes=10)<row['latest_positive_evidence']<=at and row['positive_expires_at']==row['latest_positive_evidence']+timedelta(minutes=10),'Future/expired positive label')
                        else:need(row['latest_positive_evidence'] is None and row['positive_expires_at'] is None,'Nonpositive label evidence differs')
                        if eligible:
                            need(row['User ID'] in scores,'Missing eligible raw User');s=scores[row['User ID']]
                            eligible_by_d[d].append(dict(organization=org,variant_id=entry['variant_id'],asof=at.isoformat(),user_id=row['User ID'],detector=d,node_label=y,logit_hex=s['logit_hex'],alert=s['alert'],threshold=raw['threshold']))
            need([(r['asof'],r['user_id'],r['node_label']) for r in eligible_by_d['graphsage']]==[(r['asof'],r['user_id'],r['node_label']) for r in eligible_by_d['tabular_mlp']],'Unfair eligible comparison populations')
            perorg[org]={}
            for d,rows in eligible_by_d.items():
                need(rows==read(root/org/'private'/f'eligible_{d}.json'),'Saved eligible rows differ from independent frozen-label join')
                m=counts_and_ap(rows);compare_metrics(m,results['fixed_grid'][org][d]);perorg[org][d]=m;all_rows[d].extend(rows)
            originals=read(ROOT/'reports/phase6/test_execution_preflight_v1/verified_model_threshold_bundles.json')
            authority=next(v['identity'] for v in originals if v['organization']==org and v['detector']=='graphsage')
            report,source=verify_local_graph(root/org/'private/local.sqlite',org,dict(bindings[org],variant_id=entry['variant_id']),bytime,authority,local[org])
            need(report['events']==info['events'],'Source command event count differs');graph_reports.append(report)
            # Exact observable source stream comparison, with no ground truth.
            p=ROOT/REPLAY/entry['variant_id']/f'{org}_observations.parquet';need(sha(p)==info['observations_sha256'],'Observation source hash differs')
            rows=sql.execute('SELECT organization,"Login Timestamp","User ID","IP Address",LoginSuccessful FROM read_parquet(?) ORDER BY 2,3,4,5',[str(p)]).fetchall()
            expected=[dict(zip(('organization','Login Timestamp','User ID','IP Address','LoginSuccessful'),[o,t.isoformat(),u,ip,outcome])) for o,t,u,ip,outcome in rows]
            need(source==expected,'Local command stream differs from frozen observable source')
        manifest=read(ROOT/REPLAY/entry['variant_id']/'replay_manifest.json');need(sha(ROOT/REPLAY/entry['variant_id']/'replay_manifest.json')==entry['manifest_sha256'],'Frozen manifest changed')
        evidence=[];ids=set()
        for b in manifest['branches']:
            org=b['organization'];p=ROOT/REPLAY/entry['variant_id']/f'{org}_replay.parquet';info=next(v for v in entry['branches'] if v['organization']==org);need(sha(p)==info['offline_replay_sha256'],'Offline targeting source differs')
            rows=sql.execute('SELECT CAST("User ID" AS BIGINT),CAST("Login Timestamp" AS TIMESTAMP),CAST(campaign_id AS VARCHAR) FROM read_parquet(?) WHERE organization=? AND is_synthetic=true AND credential_stuffing_label=1 ORDER BY 2,1,3',[str(p),org]).fetchall()
            need(len(rows)==b['synthetic_events'] and len({u for u,t,c in rows})==b['targeted_users'],'Independent targeting census mismatch')
            for u,t,c in rows:ids.add(c);evidence.append(dict(variant_id=entry['variant_id'],campaign_id=c,organization=org,user_id=int(u),at=t))
        need(len(ids)==1 and None not in ids,'Frozen campaign identity missing/ambiguous')
        registered=next(r for r in read(run/'required_inventory.json')['rows'] if r['variant_id']==entry['variant_id'])
        target_orgs=registered['targeted_organizations'].split('|')
        need({e['organization'] for e in evidence}==set(target_orgs),'Registered targeted-organization coverage mismatch')
        specs=[dict(variant_id=entry['variant_id'],campaign_id=next(iter(ids)),start=datetime.fromisoformat(registered['campaign_start']),end=datetime.fromisoformat(registered['campaign_end_exclusive']),targeted_organizations=target_orgs)]
        oracle=campaign_oracle(specs,evidence,frames)
        for kind,reported in [('organizations',results['organization_results']),('campaigns',results['campaign_results'])]:
            keys=('variant_id','campaign_id','organization','detector_family') if kind=='organizations' else ('variant_id','campaign_id','detector_family')
            by={tuple(r[k] for k in keys):r for r in reported};need(len(by)==len(oracle[kind]),'Campaign/org denominator differs')
            for row in oracle[kind]:need(all(by[tuple(row[k] for k in keys)][k]==v for k,v in row.items()),'Independent campaign/org detection/censoring discrepancy')
        for org in ORGS:
            reported=read(root/org/'private/campaign_user_results.json');expected=[r for r in oracle['users'] if r['organization']==org]
            by={(r['campaign_id'],r['user_id'],r['family']):r for r in reported};need(len(by)==len(expected),'Targeted-User denominator differs')
            for row in expected:need(all(by[row['campaign_id'],row['user_id'],row['family']][k]==v for k,v in row.items()),'Targeted-User first detection/censoring differs')
    finally:sql.close()
    for row in oracle['campaigns']:
        row.update({k:registered[k] for k in ('family','RIP_target','Raccount_target','Sorg_target','RIP_actual','Raccount_actual','Sorg_actual')})
        row['seed']=int(registered['seed'])
    summary=dict(status='PASS_INDEPENDENT_INSTANCE_AUDIT',variant_id=entry['variant_id'],organization_branches=5,
        fixed_grid=perorg,sharing=sstats,campaign_results=oracle['campaigns'],organization_results=oracle['organizations'],
        targeted_User_occurrences=len(oracle['users']),attribution=oracle['attribution'],local_graph_audit=graph_reports,
        completion_sha256=sha(root/'completion.json'),elapsed_seconds=time.perf_counter()-started,GNN_forwards=0)
    dump(Path(destination)/'summary.json',summary)
    return summary,all_rows

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--completed-only',action='store_true');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    inventory=read(ROOT/'reports/phase6/test_execution_preflight_v1/inventory.json')
    thresholds={(o,d):read(ROOT/f'reports/phase6/calibration/v1/thresholds/{o}_{d}.json') for o in ORGS for d in ('graphsage','tabular_mlp')}
    policy=read(ROOT/'configs/phase6/indicator_sharing_v1.json');audits=[];all_rows={d:[] for d in ('graphsage','tabular_mlp')}
    try:
        for entry in inventory:
            root=args.run/entry['variant_id']
            if not (root/'completion.json').exists():
                need(args.completed_only,'Required instance not complete: '+entry['variant_id']);continue
            report,rows=validate_instance(args.run,entry,args.output/entry['variant_id'],thresholds,policy);audits.append(report)
            for d in all_rows:all_rows[d].extend(rows[d])
            print(canon(dict(event='independent_instance_verified',variant_id=entry['variant_id'],verified=len(audits))),flush=True)
        complete=len(audits)==171
        pooled={d:counts_and_ap(v) for d,v in all_rows.items()}
        campaigns=[r for a in audits for r in a['campaign_results']]
        organizations=[r for a in audits for r in a['organization_results']]
        factors=factor_summaries(campaigns)
        if complete:
            original=read(args.run/'run_completion.json')
            expected_factors=[{k:v for k,v in r.items() if k not in ('interpretation','evaluable_campaigns')} for r in original['factor_seed_cells']]
            need(factors==expected_factors,'Independent factor/seed detection counts differ')
            for d,m in pooled.items():compare_metrics(m,original['pooled'][d])
            perorg={org:{d:counts_and_ap([r for r in rows if r['organization']==org]) for d,rows in all_rows.items()} for org in ORGS}
            for org,detectors in perorg.items():
                for d,m in detectors.items():compare_metrics(m,original['per_organization'][org][d])
            for d in all_rows:
                for metric in ('recall','precision','fpr','f1','average_precision'):
                    values=[perorg[o][d][metric] for o in ORGS if perorg[o][d][metric] is not None]
                    expected=sum(values)/len(values) if values else None
                    need(expected==original['macro'][d][metric],'Equal-weight macro metric differs')
            protected=read(ROOT/'reports/phase6/test_execution_preflight_v1/protected_artifact_sha256.json')
            for relative,h in protected.items():need(sha(ROOT/relative)==h,'Prior accepted artifact changed: '+relative)
            original_models=read(ROOT/'reports/phase6/test_execution_preflight_v1/verified_model_threshold_bundles.json')
            for v in original_models:
                t=thresholds[v['organization'],v['detector']]
                need(sha(Path(t['model_path']))==t['model_sha256'] and sha(ROOT/f"reports/phase6/calibration/v1/thresholds/{v['organization']}_{v['detector']}.json")==v['identity']['threshold_sha256'],'Original model or threshold changed after TEST')
        dump(args.output/'summary.json',dict(status='PASS_ALL_171_INDEPENDENT_VALIDATIONS' if complete else 'PASS_COMPLETED_SUBSET_NOT_FINAL',
            required=171,verified=len(audits),organization_branches=5*len(audits),pooled=pooled,
            campaign_results=campaigns,organization_results=organizations,
            operational_detection=detection_summary(campaigns,organizations),factor_seed_cells=factors,GNN_forwards=0))
    except Exception as e:
        dump(args.output/'failure.json',dict(status='FAIL_STOPPED_INDEPENDENT_AUDIT',error_type=type(e).__name__,message=str(e),verified=len(audits)));raise

if __name__=='__main__':main()
