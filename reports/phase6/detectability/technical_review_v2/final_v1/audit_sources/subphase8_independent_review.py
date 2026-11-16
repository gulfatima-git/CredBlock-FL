"""Read-only evidence audit; no detector, batch runner or training calls.
Writes only new review evidence. Independently implements campaign attribution.
"""
import sys,json,hashlib,csv,sqlite3,time,math,statistics,traceback
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict,Counter
from bisect import bisect_right
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL')
OUT=ROOT/'reports/phase6/detectability/technical_review_v1'
BASE=ROOT/'reports/phase6/detectability'; FULL=BASE/'full_v1'
sys.path.insert(0,str(ROOT))
import duckdb,psutil
from src.organization.rolling_graph_v1 import RollingGraph
ORGS=['Org1','Org2','Org3','Org4','Org5']; FAMS=['local_only','local_plus_indicator']
start=time.perf_counter(); hashes={}; checks=Counter(); inventory=[]; allcamp=[]; allorg=[]; allusers=[]; instances=[]; ops=[]; resources=[]; failures=[]; extras=[]; inputhashes={}; snapshots={}; incomplete=[]
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def put(name,x):
 p=OUT/name
 with p.open('x',encoding='utf-8') as f:json.dump(x,f,indent=2);f.write('\n')
def require(x,msg):
 if not x:raise AssertionError(msg)
 checks['assertions']+=1
def lines(p):
 with Path(p).open(encoding='utf-8-sig') as f:
  for s in f:
   if s.strip():yield json.loads(s)
def sha(p):
 p=Path(p).resolve(); st=p.stat();stamp=(st.st_size,st.st_mtime_ns)
 if p in hashes:
  require(hashes[p][0]==stamp,'File changed during review: '+str(p));return hashes[p][1]
 with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
 hashes[p]=(stamp,h);return h
def pin(p,h):require(sha(p)==h,'SHA256 mismatch: '+str(p))
def sealed(folder,kind=None):
 marker=load(folder/'complete.json');require(marker['status']=='COMPLETE' and marker['method_sha256']==METHOD,'Invalid completion '+str(folder))
 if kind:require(marker['kind']==kind,'Wrong component kind '+str(folder))
 claimed=set(marker['artifact_sha256']); actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name!='complete.json'}
 require(actual==claimed,'Missing/unlisted sealed artifacts '+str(folder))
 for p,h in marker['artifact_sha256'].items():
  path=(folder/p).resolve();require(path.is_relative_to(folder.resolve()),'Escaping manifest path');pin(path,h)
 sha(folder/'complete.json');checks['completion_manifests']+=1;checks['artifact_hash_entries']+=len(claimed)
 return marker
def component(parent,kind):
 valid=[]
 for p in sorted(parent.glob('attempt_*')):
  if (p/'complete.json').exists():sealed(p,kind);valid.append(p)
  else:incomplete.append(str(p.relative_to(ROOT)))
 require(len(valid)==1,'Expected exactly one complete component '+str(parent));return valid[0]
def compare(a,b,label):require(a==b,label+' differs')
def csvout(name,rows):
 if not rows:return
 with (OUT/name).open('x',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def dt(x):return datetime.fromisoformat(x)

def independent_outcomes(row,evidence,decisions):
 """Separate implementation; does not call accepted evaluator or outcomes runner."""
 variant=row['variant_id'];end=dt(row['end_exclusive']); declared=dt(row['start']);targets=row['targeted_organizations'];campaigns={e[2] for es in evidence.values() for e in es}
 require(len(campaigns)==1,'Single-campaign evidence contract violated');cid=next(iter(campaigns))
 onset=min(t for es in evidence.values() for _,t,_ in es)
 histories=defaultdict(list);users=defaultdict(dict);localstart={}
 for org,es in evidence.items():
  for u,t,c in es:
   require(org in targets and declared<=t<end and c==cid,'Out-of-window/organization evidence')
   histories[(org,u)].append((t,c));users[org][u]=min(t,users[org].get(u,t));localstart[org]=min(t,localstart.get(org,t))
 for v in histories.values():v.sort()
 private=[];first={};qual=Counter();raw=defaultdict(lambda:dict(score_rows=0,raw_alert_rows=0,raw_alert_users=set()));seen=set()
 for d in sorted(decisions,key=lambda x:(x['variant_id'],x['at'],x['organization'],x['user_id'],x['family'])):
  o,u,t,f=d['organization'],d['user_id'],dt(d['at']),d['family'];key=(o,u,t,f)
  require(key not in seen,'Duplicate User-time evidence');seen.add(key);r=raw[o,f];r['score_rows']+=1
  if not d['alert']:continue
  r['raw_alert_rows']+=1;r['raw_alert_users'].add(u)
  candidates=sorted({c for et,c in histories.get((o,u),[]) if t-timedelta(minutes=10)<et<=t and onset<=t<end})
  status='UNIQUE' if len(candidates)==1 else 'AMBIGUOUS' if candidates else 'UNATTRIBUTED'
  private.append(dict(variant_id=variant,organization=o,user_id=u,at=t.isoformat(),family=f,status=status,candidate_campaign_ids=candidates))
  checks['attribution_'+status]+=1
  if len(candidates)==1:
   qual[o,f]+=1;first[o,u,f]=min(t,first.get((o,u,f),t))
 organizations=[];campaigns=[];ur=[]
 for f in FAMS:
  rs=[]
  for o in targets:
   ts=sorted(users[o]);found=[first[o,u,f] for u in ts if (o,u,f) in first];d=min(found) if found else None;r=raw[o,f];require(bool(ts),'Targeted org without positive exposure')
   org=dict(variant_id=variant,campaign_id=cid,organization=o,detector_family=f,**row['factors'],seed=row['seed'],global_onset=onset.isoformat(),observation_end_exclusive=end.isoformat(),operational_score_rows=r['score_rows'],raw_alert_rows=r['raw_alert_rows'],raw_unique_alerted_users=len(r['raw_alert_users']),qualifying_alert_rows=qual[o,f],unique_exposed_target_users=len(ts),unique_detected_target_users=len(found),detected=bool(found),first_qualifying_alert=d.isoformat() if d else None,event_time_seconds=(d-onset).total_seconds() if d else None,local_exposure_delay_seconds=(d-localstart[o]).total_seconds() if d else None,right_censored=d is None,censor_time_seconds=(end-onset).total_seconds(),local_exposure_start=localstart[o].isoformat())
   # local_exposure_start is independently retained in users; remove from exact accepted schema.
   org.pop('local_exposure_start');org['evaluable']=True;organizations.append(org);rs.append(org)
   for u in ts:
    when=first.get((o,u,f));ur.append(dict(variant_id=variant,campaign_id=cid,organization=o,user_id=u,family=f,first_exposure=users[o][u].isoformat(),first_detection=when.isoformat() if when else None,event_time_seconds=(when-users[o][u]).total_seconds() if when else None,right_censored=when is None))
  n=sum(r['detected'] for r in rs);fd=min((dt(r['first_qualifying_alert']) for r in rs if r['detected']),default=None)
  campaigns.append(dict(variant_id=variant,campaign_id=cid,detector_family=f,**row['factors'],seed=row['seed'],targeted_organization_count=len(rs),evaluable=True,detected_organizations=n,any_organization_detected=n>0,all_organizations_detected=n==len(rs),partially_detected=0<n<len(rs),primary_all_targeted_undetected=n==0,status='DETECTED' if n else 'UNDETECTED_ALL_TARGETED_ORGANIZATIONS',global_onset=onset.isoformat(),observation_end_exclusive=end.isoformat(),event_time_seconds=(fd-onset).total_seconds() if fd else None,right_censored=fd is None,censor_time_seconds=(end-onset).total_seconds(),unique_exposed_target_users_summed_local=sum(r['unique_exposed_target_users'] for r in rs),unique_detected_target_users_summed_local=sum(r['unique_detected_target_users'] for r in rs)))
 return dict(campaign_results=campaigns,organization_results=organizations,private_user_results=ur,private_alert_attribution=private)

def audit_instance(row):
 variant=row['variant_id'];path=FULL/'instances'/variant;ev=component(path/'evaluation','verified_representative_reuse' if variant==PILOT else 'offline_evaluation');saved=load(ev/'summary.json')
 if variant==PILOT:
  share=ROOT/'reports/phase6/indicator_baseline/paired_v1';reverse=ROOT/'reports/phase6/indicator_baseline/reverse_order_v1';localpaths={o:ROOT/'reports/phase6/indicator_baseline/local_v1'/o for o in ORGS}
  pin(BASE/'representative_v1/artifact_sha256.json',saved['reused_representative_manifest_sha256'])
  for p,h in load(BASE/'representative_v1/artifact_sha256.json').items():pin(BASE/'representative_v1'/p,h)
  for folder in [share,reverse,*localpaths.values()]:
   for p,h in load(folder/'artifact_sha256.json').items():pin(folder/p,h)
  evaluation=BASE/'representative_v1'
 else:
  share=component(path/'sharing','sharing');reverse=component(path/'reverse_sharing','reverse_sharing');localpaths={o:component(path/'local'/o,'local_runtime') for o in ORGS};evaluation=ev
 a,b=load(share/'summary.json'),load(reverse/'summary.json');compare(a['network_digest'],b['network_digest'],'Reverse network digest')
 network=list(lines(share/'network_events.jsonl'));compare(hashlib.sha256(canon(network).encode()).hexdigest(),a['network_digest'],'Network trace digest');compare(list(lines(reverse/'network_events.jsonl')),network,'Reverse network trace')
 public={};broadcasts={};expired={};last=None;live={}
 wire={'indicator_id','ip','issuer','issued_at','available_at','expires_at','policy_version','status'}
 for n in network:
  t=dt(n.get('at',n.get('issued_at')));require(last is None or t>=last,'Network time reversed');last=t
  if n['event']=='creation':
   require(set(n)==wire|{'event'},'Indicator wire privacy schema');pid=n['indicator_id'];require(pid not in public,'Duplicate creation')
   require(n['issuer'] in ORGS and n['policy_version']==POLICY['version'] and n['status']==POLICY['status'],'Indicator policy mismatch')
   require(n['available_at']==n['issued_at'] and dt(n['expires_at'])==t+timedelta(seconds=600),'Availability/TTL mismatch')
   compare(pid,hashlib.sha256(canon([POLICY['version'],n['issuer'],n['ip'],t.isoformat()]).encode()).hexdigest(),'Indicator identity')
   require(live.get((n['issuer'],n['ip']),datetime.min)<=t,'Live duplicate indicator renewal');live[n['issuer'],n['ip']]=dt(n['expires_at']);public[pid]=n
  elif n['event']=='broadcast':
   pid=n['indicator_id'];require(pid in public and pid not in broadcasts,'Invalid/duplicate broadcast');p=public[pid]
   require(n['at']==p['issued_at'] and n['receivers']==sorted(set(ORGS)-{p['issuer']}) and n['simulated_delay_seconds']==0,'Distribution mismatch');broadcasts[pid]=n
  elif n['event']=='expiry':
   pid=n['indicator_id'];require(pid in public and pid not in expired and n['at']==public[pid]['expires_at'],'Expiry mismatch');expired[pid]=n
  else:raise AssertionError('Unexpected network event '+n['event'])
 compare(set(public),set(broadcasts),'Broadcast completeness');compare(set(public),set(expired),'Expiry completeness');checks['indicators']+=len(public)
 byip=defaultdict(list)
 for k,v in public.items():byip[v['ip']].append((k,v))
 decisions=[];manifest=load(ROOT/'data/phase5/controlled_replay_labels_all_orgs_causal_v1'/variant/'replay_manifest.json');pin(ROOT/'data/phase5/controlled_replay_labels_all_orgs_causal_v1'/variant/'replay_manifest.json',row['manifest_sha256'])
 require(manifest['split']=='VAL' and manifest['anchor']==row['start'] and manifest['end_exclusive']==row['end_exclusive'],'Replay interval mismatch');compare(manifest['targeted_organizations'],row['targeted_organizations'],'Target organizations')
 evidence={};counts=[]
 for o in ORGS:
  local=load(localpaths[o]/'summary.json');loc=local['local'];source=local.get('source') or load(localpaths[o]/'source_identity.json')
  require(source['variant_id']==variant and source['organization']==o and source['split']=='VAL' and source['anchor']==row['start'] and source['end_exclusive']==row['end_exclusive'],'Local source identity mismatch')
  branch=next(x for x in manifest['branches'] if x['organization']==o)
  require(loc['processing_failures']==0 and source['events']==loc['events'],'Failures or events mismatch')
  for p,h in local['input_sha256'].items():
   require(not p.endswith(('_labels.parquet','_replay.parquet')) and '_TEST/' not in p,'Truth/TEST path in runtime provenance');pin(ROOT/p,h);inputhashes[p]=h
  journal=ROOT/loc['private_store'];db=sqlite3.connect('file:'+journal.resolve().as_posix()+'?mode=ro',uri=True)
  require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity')
  cp=db.execute('SELECT graph,sha256 FROM checkpoints WHERE seq=0').fetchone();compare(hashlib.sha256(cp[0]).hexdigest(),cp[1],'Initial checkpoint')
  graph=RollingGraph.from_checkpoint_bytes(cp[0]);recent=defaultdict(list)
  for e in graph.recent_events:recent[e.user].append((e.time,e.ip))
  del graph
  commands={};previous=None;eventcount=0;last10=0;end=dt(row['end_exclusive']);cut=end-timedelta(minutes=10)
  for seq,at,payload in db.execute('SELECT seq,asof,payload FROM commands ORDER BY seq'):
   t=dt(at);require(previous is None or t>previous,'Local command time not increasing');previous=t;require(dt(row['start'])<=t<end,'Command outside branch');current=defaultdict(set);events=json.loads(payload)['observations']
   for e in events:
    require(e['organization']==o and dt(e['Login Timestamp'])==t,'Command event attribution/time');u=e['User ID'];ip=e['IP Address'];current[u].add(ip);recent[u].append((t,ip))
   eventcount+=len(events);last10+=len(events) if t>=cut else 0;commands[seq]=(t,current)
  require(previous==end-timedelta(microseconds=1),'Missing exclusive-end final flush');require(eventcount==loc['events'] and len(commands)==loc['timestamp_commands'],'Complete chronological event/command census');compare(dict(events=last10,user_scores=loc['final_ten_minutes']['user_scores'],last_flush=previous.isoformat(),covered=True),loc['final_ten_minutes'],'Final ten-minute events/flush')
  scores={};score10=0;localalerts=0
  pins=REG['models'][o];threshold=load(ROOT/pins['threshold_path'])['calibration']['threshold']['hex']
  for s in db.execute('SELECT seq,user_id,asof,logit_hex,threshold_hex,decision,alert_id,model_sha256,threshold_sha256,schema_sha256,processing_status FROM scores ORDER BY seq,user_id'):
   seq,u,at,l,th,flag,aid,mh,thh,sch,status=s;t,current=commands[seq];require(at==t.isoformat() and math.isfinite(float.fromhex(l)),'Nonfinite/mistimed score')
   require(th==threshold and mh==pins['model_sha256'] and thh==pins['threshold_sha256'] and sch==REG['shared_sha256']['configs/phase6/feature_allowlist_v1.json'] and status=='OK','Model/threshold/schema/status identity')
   require(flag==('ALERT' if float.fromhex(l)>=float.fromhex(th) else 'NO_ALERT'),'Binary64 decision mismatch');require((seq,u) not in scores,'Duplicate local score');scores[seq,u]=s;score10+=t>=cut;localalerts+=flag=='ALERT'
  require(len(scores)==loc['user_scores'] and localalerts==loc['alerts'] and score10==loc['final_ten_minutes']['user_scores'],'Score/final-ten census');db.close()
  pairs=list(lines(share/o/'private/paired_decisions.jsonl'));compare(sha(share/o/'private/paired_decisions.jsonl'),sha(reverse/o/'private/paired_decisions.jsonl'),'Reverse paired bytes')
  require(len(pairs)==len(scores),'Paired cohort size');seen=set();added=0;used=set();util=Counter()
  for r in pairs:
   key=r['seq'],r['user_id'];require(key in scores and key not in seen,'Paired identity census');seen.add(key);s=scores[key];seq,u,at,l,th,flag,*_=s;t,current=commands[seq]
   require((r['at'],r['local_logit_hex'],r['threshold_hex'],r['local_alert'])==(at,l,th,flag=='ALERT'),'Changed original local prediction')
   wanted=sorted(k for ip in current.get(u,set()) for k,p in byip[ip] if p['issuer']!=o and dt(p['available_at'])<=t<dt(p['expires_at']))
   require(r['indicator_ids']==wanted and r['local_plus_indicator_alert']==(flag=='ALERT' or bool(wanted)),'Noncausal/wrong combined decision');added+=not r['local_alert'] and r['local_plus_indicator_alert'];used.update(wanted)
   for k in wanted:util[(k,at,'utilization_paired')]+=1
   for f,bv in [(FAMS[0],r['local_alert']),(FAMS[1],r['local_plus_indicator_alert'])]:decisions.append(dict(variant_id=variant,organization=o,user_id=u,at=at,family=f,alert=bv))
  additional=list(lines(share/o/'private/additional_event_decisions.jsonl'));compare(sha(share/o/'private/additional_event_decisions.jsonl'),sha(reverse/o/'private/additional_event_decisions.jsonl'),'Reverse additional bytes')
  for r in additional:
   seq,u=r['seq'],r['user_id'];t,current=commands[seq];require((seq,u) not in scores and u in current and r['local_status']=='NOT_SCORED','Extra row not separate NOT_SCORED')
   wanted=sorted(k for ip in current[u] for k,p in byip[ip] if p['issuer']!=o and dt(p['available_at'])<=t<dt(p['expires_at']))
   require(r['indicator_ids']==wanted and r['local_plus_indicator_alert']==bool(wanted),'Additional event causal match')
   for k in wanted:util[(k,r['at'],'utilization_additional_event')]+=1
  receivers=list(lines(share/o/'indicator_events.jsonl'));received={};expiredrec={};actualutil=Counter()
  for r in receivers:
   k=r['indicator_id'];p=public[k];require(r['organization']==o,'Receiver organization mismatch')
   if r['event']=='receipt':require(k not in received and p['issuer']!=o and r['at']==p['issued_at'],'Invalid receipt');received[k]=r
   elif r['event']=='expiry':require(k not in expiredrec and r['at']==p['expires_at'],'Receiver expiry');expiredrec[k]=r
   elif r['event'].startswith('utilization_'):actualutil[(k,r['at'],r['event'])]+=1
   else:raise AssertionError('Unexpected receipt event')
  compare(set(received),{k for k,p in public.items() if p['issuer']!=o},'All four receivers');compare(set(expiredrec),set(received),'Receipt expiry census');compare(actualutil,util,'Utilization trace')
  provenance=list(lines(share/o/'private/issuance_provenance.jsonl'));issuedids=[]
  alerts={s[6]:(s[1],dt(s[2])) for s in scores.values() if s[5]=='ALERT'}
  for r in provenance:
   k=r['indicator_id'];p=public[k];u,t=alerts[r['source_alert_id']]
   require(p['issuer']==o and r['user_id']==u and r['ip']==p['ip'] and r['issued_at']==p['issued_at']==t.isoformat(),'Indicator not from original local alert')
   require(any(t-timedelta(seconds=600)<et<=t and ip==p['ip'] for et,ip in recent[u]),'No observable recent IP evidence');issuedids.append(k)
  compare(set(issuedids),{k for k,p in public.items() if p['issuer']==o},'Issuance provenance complete');require(len(issuedids)==len(set(issuedids)),'Duplicate provenance')
  record=next(x for x in a['records'] if x['organization']==o);revrecord=next(x for x in b['records'] if x['organization']==o)
  for k in ['paired_decision_digest','additional_decision_digest','final_graph_sha256']:compare(record[k],revrecord[k],'Reverse '+k)
  require(record['paired_decision_digest']==sha(share/o/'private/paired_decisions.jsonl') and record['final_graph_sha256']==loc['final_graph_checkpoint_sha256'],'Paired/graph seals')
  require(record['paired_rows']==len(pairs) and record['added_alerts']==added and record['issued']==len(issuedids) and record['received']==len(received),'Sharing census')
  ops.append(dict(variant_id=variant,organization=o,events=eventcount,scoring_decisions=len(pairs),local_alerts=localalerts,combined_alerts=localalerts+added,additional_alerts=added,indicators_issued=len(issuedids),indicators_received=len(received),unique_indicators_used=len(used),event_only_unscored_rows=len(additional),final_ten_minutes_events=last10,final_ten_minutes_scores=score10))
  resources.append(dict(variant_id=variant,organization=o,reused_representative=variant==PILOT,**loc['resources'],latency=loc['latency_seconds']))
  checks['organization_replays']+=1;checks['local_scores']+=len(scores);checks['event_only_rows']+=len(additional);checks['raw_events']+=eventcount;checks['commands']+=len(commands);checks['receipts']+=len(received);checks['issuance_provenance']+=len(provenance)
  # Evaluator-only ground truth, after local score and causal-sharing validation.
  truth=ROOT/'data/phase5/controlled_replay_labels_all_orgs_causal_v1'/variant/f'{o}_replay.parquet';pin(truth,branch['replay_parquet_sha256'])
  db=duckdb.connect(':memory:',config={'threads':1});evrows=db.execute('SELECT CAST("User ID" AS BIGINT),CAST("Login Timestamp" AS TIMESTAMP),CAST(campaign_id AS VARCHAR) FROM read_parquet(?) WHERE organization=? AND is_synthetic=true AND credential_stuffing_label=1 ORDER BY 2,1,3',[str(truth),o]).fetchall();db.close()
  require(len(evrows)==branch['synthetic_events'] and len({u for u,t,c in evrows})==branch['targeted_users'],'Truth event/target census');require(bool(evrows)==(o in row['targeted_organizations']),'Exposure org mismatch');evidence[o]=evrows
 result=independent_outcomes(row,evidence,decisions)
 compare(result['campaign_results'],saved['campaign_results'],'Independent campaign outcome')
 compare(result['organization_results'],saved['organization_results'],'Independent organization outcome')
 digest=hashlib.sha256(canon(result).encode()).hexdigest();compare(digest,saved['attribution_digest'],'Independent full attribution digest')
 for o in ORGS:
  userfile='target_user_results.jsonl' if variant==PILOT else 'target_users.jsonl';attrfile='alert_attribution.jsonl' if variant==PILOT else 'attribution.jsonl'
  compare(list(lines(evaluation/o/'private'/userfile)),[r for r in result['private_user_results'] if r['organization']==o],'Independent per-User evidence')
  compare(list(lines(evaluation/o/'private'/attrfile)),[r for r in result['private_alert_attribution'] if r['organization']==o],'Independent attribution evidence')
 allcamp.extend(result['campaign_results']);allorg.extend(result['organization_results'])
 # Public aggregates never publish private User keys.
 for r in result['private_user_results']:allusers.append({k:v for k,v in r.items() if k!='user_id'})
 return dict(variant_id=variant,status='PASS',targeted_organizations=len(row['targeted_organizations']),attribution_digest=digest,positive_events=sum(map(len,evidence.values())),reused_representative=variant==PILOT,issued_indicators=len(public))

try:
 # Observe process list only; never launch or terminate a batch process.
 active=[]
 for p in psutil.process_iter(['pid','name','cmdline']):
  try:
   args=p.info['cmdline'] or [];command=' '.join(args)
   if p.info['pid']!=psutil.Process().pid and any(str(x)=='src.phase6.detectability_batch' for x in args):active.append(dict(pid=p.info['pid'],name=p.info['name']))
  except (psutil.AccessDenied,psutil.NoSuchProcess):pass
 require(not active,'A batch process is still active; review must not interfere')
 inventory=load(BASE/'required_val_inventory_v1.json');METHOD=sha(ROOT/'configs/phase6/detectability_protocol_v1.json');cfg=load(ROOT/'configs/phase6/detectability_protocol_v1.json');PILOT=cfg['predetermined_representative'];POLICY=load(ROOT/'configs/phase6/indicator_sharing_v1.json');REG=load(ROOT/'reports/phase6/inference/preregistration_v1.json')['registry']
 require(METHOD=='f63e0bb73253eea4a8c8d7abc4231f94069aaf15c3eef68eeb3fa1b00d49bc55','Detectability protocol hash');pin(ROOT/'configs/phase6/split_protocol_v1.json',cfg['primary_protocol_sha256'])
 pre=load(BASE/'preregistration_v1.json');pin(BASE/'required_val_inventory_v1.json',pre['inventory_sha256'])
 for p,h in pre['source_sha256'].items():pin(ROOT/p,h)
 for p,h in pre['design_document_sha256'].items():pin(Path(p),h)
 plan=load(BASE/'execution_plan_v1.json');pin(ROOT/'src/phase6/detectability_batch.py',plan['engine_source_sha256']);pin(ROOT/'tests/phase6/test_detectability_batch.py',plan['engine_test_sha256'])
 for p,h in REG['shared_sha256'].items():pin(ROOT/p,h)
 for org,model in REG['models'].items():pin(ROOT/model['model_path'],model['model_sha256']);pin(ROOT/model['threshold_path'],model['threshold_sha256'])
 require(len(inventory)==171 and len({r['variant_id'] for r in inventory})==171,'Frozen inventory uniqueness');require(all(r['split']=='VAL' and r['variant_id'].endswith('_VAL') for r in inventory),'Non-VAL inventory')
 compare(Counter(r['seed'] for r in inventory),Counter({1001:57,1002:57,1003:57}),'Seed coverage')
 require(set(p.name for p in (FULL/'instances').iterdir() if p.is_dir())=={r['variant_id'] for r in inventory},'Unexpected/missing full instances')
 finaldir=component(FULL/'validated_171','full_171_validation');final=load(finaldir/'summary.json');require(final['status']=='PASS_ALL_171_VAL_INSTANCES_TECHNICAL_REVIEW_REQUIRED' and final['required']==final['evaluated']==171 and not final['test_used'] and not final['subphase9_started'],'Runner aggregate declaration')
 for i,row in enumerate(inventory,1):
  instances.append(audit_instance(row))
  print(json.dumps(dict(event='independent_review_progress',verified=i,required=171,variant_id=row['variant_id'],hashes=len(hashes))),flush=True)
 compare(allcamp,final['campaign_results'],'Final campaign aggregation');compare(allorg,final['organization_results'],'Final organization aggregation')
 # Factor/seed cells independently rebuilt, without calling the batch aggregation function.
 cells=[];grouped=defaultdict(list)
 for r in inventory:grouped[tuple(r['factors'][k] for k in ['family','RIP_target','Raccount_target','Sorg_target'])+(r['seed'],)].append(r['variant_id'])
 for f in FAMS:
  mapping={r['variant_id']:r for r in allcamp if r['detector_family']==f}
  for key,ids in sorted(grouped.items()):
   n=len(ids);u=sum(mapping[x]['primary_all_targeted_undetected'] for x in ids)
   cells.append(dict(detector_family=f,**dict(zip(['family','RIP_target','Raccount_target','Sorg_target'],key[:4])),seed=key[4],required_campaigns=n,evaluated_complete_campaigns=n,pending_campaigns=0,detected_campaigns=n-u,undetected_campaigns=u,undetected_fraction=u/n,denominator_definition='complete evaluable isolated campaign instances in this design-family/factor/seed cell'))
 compare(cells,final['factor_seed_results'],'Independent factor-seed aggregates');require(len(cells)==342,'Factor/seed cell coverage')
 baseline=load(BASE/'accepted_inputs_before_subphase8_v1.json')
 for i,(p,h) in enumerate(baseline.items(),1):
  pin(ROOT/p,h)
  if i%2000==0:print(json.dumps(dict(event='preservation_progress',verified=i,required=len(baseline))),flush=True)
 # The review reads TEST-containing frozen files only as opaque hash bytes, never queries their outcomes.
 for p,(stamp,h) in hashes.items():require((p.stat().st_size,p.stat().st_mtime_ns)==stamp,'Input mutated during audit '+str(p))
 csvout('campaign_results.csv',allcamp);csvout('organization_results.csv',allorg);csvout('factor_seed_results.csv',cells);csvout('operational_results.csv',ops);csvout('instance_validation.csv',instances)
 put('resource_measurements.json',resources)
 aggregate=[]
 for f in FAMS:
  cs=[r for r in allcamp if r['detector_family']==f];os=[r for r in allorg if r['detector_family']==f];us=[r for r in allusers if r['family']==f]
  aggregate.append(dict(detector_family=f,campaigns=len(cs),detected_campaigns=sum(r['any_organization_detected'] for r in cs),undetected_campaigns=sum(r['primary_all_targeted_undetected'] for r in cs),all_orgs_detected=sum(r['all_organizations_detected'] for r in cs),partially_detected=sum(r['partially_detected'] for r in cs),targeted_org_trials=len(os),detected_org_trials=sum(r['detected'] for r in os),exposed_user_occurrences=len(us),detected_user_occurrences=sum(not r['right_censored'] for r in us),qualifying_alert_rows=sum(r['qualifying_alert_rows'] for r in os),censored_user_occurrences=sum(r['right_censored'] for r in us),censored_org_trials=sum(r['right_censored'] for r in os),censored_campaigns=sum(r['right_censored'] for r in cs)))
 put('aggregate_results.json',aggregate)
 # Every read evidence file is pinned for independent reproducibility, including source byte hashes.
 put('verified_input_sha256.json',{str(p):v[1] for p,v in sorted(hashes.items(),key=lambda x:str(x[0]))})
 summary=dict(status='PASS_INDEPENDENT_SUBPHASE8_TECHNICAL_VALIDATION',recorded_on_local_date='2026-11-16',required=171,independently_validated=len(instances),checks=dict(checks),aggregate_results=aggregate,prior_files_preserved=len(baseline),method_sha256=METHOD,primary_protocol_sha256=cfg['primary_protocol_sha256'],active_batch_processes=active,incomplete_attempts=incomplete,elapsed_seconds=time.perf_counter()-start,observed_rss_bytes=psutil.Process().memory_info().rss,expensive_inference_repeated=False,models_retrained=False,thresholds_recalibrated=False,test_outcomes_queried=False,test_integrity_hashing_only=True,user_accepted=False,subphase9_started=False)
 put('independent_validation_summary.json',summary);print(json.dumps(summary),flush=True)
except BaseException as e:
 failures.append(dict(error_type=type(e).__name__,message=str(e),traceback=traceback.format_exc()))
 put('validation_failure.json',dict(status='FAIL',verified_instances=len(instances),failures=failures,checks=dict(checks),elapsed_seconds=time.perf_counter()-start));print(traceback.format_exc(),flush=True);sys.exit(1)
