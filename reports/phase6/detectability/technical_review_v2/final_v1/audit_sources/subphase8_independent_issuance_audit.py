"""Supplement: independently reconstruct every indicator issuance, not GNN inference."""
import json,sqlite3,hashlib,sys,time,traceback
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');sys.path.insert(0,str(ROOT))
import duckdb
from src.organization.rolling_graph_v1 import RollingGraph
BASE=ROOT/'reports/phase6/detectability';OUT=BASE/'technical_review_v2/issuance_and_observation_audit_v1';OUT.mkdir()
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def lines(p):
 with p.open(encoding='utf-8') as f:
  for l in f:
   if l.strip():yield json.loads(l)
def save(n,x):
 with (OUT/n).open('x',encoding='utf-8') as f:json.dump(x,f,indent=2)
def req(x,m):
 if not x:raise AssertionError(m)
def only(p):
 result=[x for x in p.glob('attempt_*') if (x/'complete.json').exists()];req(len(result)==1,'Ambiguous component '+str(p));return result[0]
rows=load(BASE/'required_val_inventory_v1.json');cfg=load(ROOT/'configs/phase6/indicator_sharing_v1.json');pilot=load(ROOT/'configs/phase6/detectability_protocol_v1.json')['predetermined_representative'];proof=[];start=time.perf_counter()
try:
 for index,row in enumerate(rows,1):
  v=row['variant_id'];req(v.endswith('_VAL'),'Not VAL');parent=BASE/'full_v1/instances'/v
  share=ROOT/'reports/phase6/indicator_baseline/paired_v1' if v==pilot else only(parent/'sharing')
  for o in cfg['organizations']:
   component=ROOT/'reports/phase6/indicator_baseline/local_v1'/o if v==pilot else only(parent/'local'/o)
   value=load(component/'summary.json');local=value['local'];path=ROOT/local['private_store'];wal=Path(str(path)+'-wal');req(not wal.exists() or wal.stat().st_size==0,'Nonempty WAL blocks immutable read')
   db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro&immutable=1',uri=True)
   blob,h=db.execute('SELECT graph,sha256 FROM checkpoints WHERE seq=0').fetchone();req(hashlib.sha256(blob).hexdigest()==h,'Initial checkpoint digest')
   graph=RollingGraph.from_checkpoint_bytes(blob);hist=defaultdict(list)
   for e in graph.recent_events:hist[e.user].append((e.time,e.ip))
   del graph
   expected=[];suppressed=0;without=0;until={};observed=[]
   for seq,at,payload in db.execute('SELECT seq,asof,payload FROM commands ORDER BY seq'):
    t=datetime.fromisoformat(at)
    for r in json.loads(payload)['observations']:
     u=int(r['User ID']);hist[u].append((t,r['IP Address']));observed.append((u,t,r['IP Address'],r['LoginSuccessful'],r['organization']))
    alerts=db.execute("SELECT user_id,alert_id FROM scores WHERE seq=? AND decision='ALERT' ORDER BY user_id,alert_id",(seq,)).fetchall()
    for user,aid in alerts:
     ips={ip for et,ip in hist[user] if t-timedelta(minutes=10)<et<=t}
     if not ips:without+=1
     for ip in sorted(ips):
      if until.get(ip,datetime.min)>t:suppressed+=1;continue
      until[ip]=t+timedelta(minutes=10);identity=hashlib.sha256(canonical([cfg['version'],o,ip,t.isoformat()]).encode()).hexdigest()
      expected.append(dict(indicator_id=identity,source_alert_id=aid,user_id=user,ip=ip,issued_at=t.isoformat()))
   db.close()
   actual=list(lines(share/o/'private/issuance_provenance.jsonl'));req(actual==expected,'Missing/extra/wrong deterministic indicator attribution '+v+' '+o)
   stats=load(share/o/'summary.json');req(stats['suppressed_live_duplicates']==suppressed and stats['alerts_without_recent_evidence']==without,'Suppression/no-evidence counters '+v+' '+o)
   observations=ROOT/'data/phase5/controlled_replay_labels_all_orgs_causal_v1'/v/f'{o}_observations.parquet'
   conn=duckdb.connect(':memory:',config={'threads':1})
   original=conn.execute('SELECT CAST("User ID" AS BIGINT),CAST("Login Timestamp" AS TIMESTAMP),"IP Address",LoginSuccessful,organization FROM read_parquet(?) ORDER BY 2,1,3,4,5',[str(observations)]).fetchall();conn.close()
   req(sorted(observed,key=lambda x:(x[1],x[0],x[2],x[3],x[4]))==original,'Journal/source observation content mismatch '+v+' '+o)
   proof.append(dict(variant_id=v,organization=o,status='PASS',events_exact_source=len(original),deterministic_issued_indicators=len(expected),suppressed_duplicates=suppressed,alerts_without_recent_evidence=without))
  if index%10==0:print(json.dumps(dict(event='issuance_observation_review',campaigns=index,organizations=len(proof))),flush=True)
 save('per_organization_proof.json',proof);save('summary.json',dict(status='PASS_INDEPENDENT_COMPLETE_ISSUANCE_AND_OBSERVATION_AUDIT',campaigns=len(rows),organization_replays=len(proof),events=sum(r['events_exact_source'] for r in proof),issued_indicators=sum(r['deterministic_issued_indicators'] for r in proof),elapsed_seconds=time.perf_counter()-start,no_gnn_inference=True,sqlite_immutable=True));print('PASS independent complete issuance and source observations',flush=True)
except BaseException as e:
 save('failure.json',dict(status='FAIL',error=str(e),traceback=traceback.format_exc(),complete_organizations=len(proof)));raise
