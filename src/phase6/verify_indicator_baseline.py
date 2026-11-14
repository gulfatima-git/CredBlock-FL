"""Independent local provenance/decision audit and additive readable report."""
from pathlib import Path
from datetime import datetime,timedelta
import json,hashlib,sqlite3,math
from src.organization.rolling_graph_v1 import RollingGraph
from src.phase6.readiness import ROOT,load,sha
from src.phase6.indicator_sharing import WIRE,Indicator

BASE=ROOT/'reports/phase6/indicator_baseline'
cfg=load(ROOT/'configs/phase6/indicator_sharing_v1.json');final=load(BASE/'final_v1/summary.json')
assert final['status']=='PASS_SUBPHASE7_IMMEDIATE_INDICATOR_BASELINE_AWAITING_USER_ACCEPTANCE'
def lines(p):
 with p.open(encoding='utf-8') as f:
  for line in f:
   if line.strip():yield json.loads(line)
public={r['indicator_id']:{k:r[k] for k in WIRE} for r in lines(BASE/'paired_v1/network_events.jsonl') if r['event']=='creation'}
for p in public.values():assert Indicator.parse(cfg,p).payload()==p

def audit_local(org):
 # This function operates on one organization's private records only.
 source=load(BASE/'local_v1'/org/'summary.json');path=ROOT/source['local']['private_store'];before=sha(path)
 db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro',uri=True)
 cp=db.execute('SELECT graph FROM checkpoints WHERE seq=0').fetchone()[0];initial=RollingGraph.from_checkpoint_bytes(cp)
 observed=[(e.time,e.user,e.ip) for e in initial.recent_events]
 commands={};scores={}
 for seq,at,payload in db.execute('SELECT seq,asof,payload FROM commands ORDER BY seq'):
  t=datetime.fromisoformat(at);events=json.loads(payload)['observations'];current={}
  for r in events:
   assert r['organization']==org and datetime.fromisoformat(r['Login Timestamp'])==t
   current.setdefault(r['User ID'],set()).add(r['IP Address']);observed.append((t,r['User ID'],r['IP Address']))
  commands[seq]=(t,current)
 for seq,user,logit,th,decision,alert in db.execute('SELECT seq,user_id,logit_hex,threshold_hex,decision,alert_id FROM scores'):
  assert math.isfinite(float.fromhex(logit));assert decision==('ALERT' if float.fromhex(logit)>=float.fromhex(th) else 'NO_ALERT')
  scores[(seq,user)]=(logit,th,decision,alert)
 private=BASE/'paired_v1'/org/'private';count=0;added=0
 for r in lines(private/'paired_decisions.jsonl'):
  t,current=commands[r['seq']];logit,threshold,decision,_=scores[(r['seq'],r['user_id'])]
  assert r['at']==t.isoformat() and r['local_logit_hex']==logit and r['threshold_hex']==threshold
  assert r['local_alert']==(decision=='ALERT')
  wanted=sorted(k for k,p in public.items() if p['issuer']!=org and p['ip'] in current.get(r['user_id'],set()) and datetime.fromisoformat(p['available_at'])<=t<datetime.fromisoformat(p['expires_at']))
  assert wanted==r['indicator_ids'] and r['local_plus_indicator_alert']==(r['local_alert'] or bool(wanted))
  count+=1;added+=int(not r['local_alert'] and bool(wanted))
 extras=0
 for r in lines(private/'additional_event_decisions.jsonl'):
  t,current=commands[r['seq']];assert (r['seq'],r['user_id']) not in scores and r['user_id'] in current and r['local_status']=='NOT_SCORED'
  wanted=sorted(k for k,p in public.items() if p['issuer']!=org and p['ip'] in current[r['user_id']] and datetime.fromisoformat(p['available_at'])<=t<datetime.fromisoformat(p['expires_at']))
  assert r['indicator_ids']==wanted and r['local_plus_indicator_alert']==bool(wanted);extras+=1
 issued=0;seen=set();alerts_by_time_user={(commands[seq][0],user):alert for (seq,user),(_,_,decision,alert) in scores.items() if decision=='ALERT'}
 for r in lines(private/'issuance_provenance.jsonl'):
  p=public[r['indicator_id']];t=datetime.fromisoformat(r['issued_at'])
  assert p['issuer']==org and p['ip']==r['ip'] and p['issued_at']==r['issued_at']
  assert alerts_by_time_user[(t,r['user_id'])]==r['source_alert_id']
  assert any(time>t-timedelta(seconds=600) and time<=t and user==r['user_id'] and ip==r['ip'] for time,user,ip in observed)
  assert r['indicator_id'] not in seen;seen.add(r['indicator_id']);issued+=1
 receipts=[r for r in lines(BASE/'paired_v1'/org/'indicator_events.jsonl') if r['event']=='receipt']
 assert len(receipts)==sum(p['issuer']!=org for p in public.values())
 for r in receipts:assert r['at']==public[r['indicator_id']]['issued_at']
 db.close();assert sha(path)==before
 expected=next(r for r in final['comparison']['records'] if r['organization']==org)
 assert count==expected['paired_rows'] and issued==expected['issued'] and added==expected['added_alerts'] and extras==expected['additional_event_users']
 return dict(organization=org,status='PASS_INDEPENDENT_LOCAL_CAUSAL_PROVENANCE_AND_PAIR_AUDIT',paired_rows=count,additional_event_rows=extras,issued_provenance_verified=issued,added_alerts_verified=added,private_source_unchanged=True)

records=[audit_local(o) for o in cfg['organizations']]
old=load(BASE/'accepted_inputs_before_subphase7_v1.json')
for p,h in old.items():assert sha(ROOT/p)==h,p
for directory in [BASE/'paired_v1',BASE/'reverse_order_v1',BASE/'final_v1']+[BASE/'local_v1'/o for o in cfg['organizations']]:
 for p,h in load(directory/'artifact_sha256.json').items():assert sha(directory/p)==h,p
audit=dict(status='PASS_INDEPENDENT_SUBPHASE7_DELIVERY_AUDIT',records=records,wire_indicators=len(public),prior_files_preserved=len(old),
 timing_scope='Global comparison wall time includes adapter loading, private-source hashes, graph replay, barriers, attribution/matching, output close and final graph/source verification. Per-org adapter timing spans prepare through finish including same-timestamp barrier/peer work; excludes fresh GNN materialization and final close/hash costs. Model-stage timing includes batch sampling plus forward passes. Simulated propagation is zero by definition, not measured transport.',
 source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in [BASE/'final_v1/summary.json',ROOT/'configs/phase6/indicator_sharing_v1.json',BASE/'preregistration_v1.json',BASE/'testing_results_v1.json',ROOT/'reports/phase6/inference/acceptance_v1.json',ROOT/'reports/phase6/progress_v9.json',Path(__file__).resolve()]},
 scope='Read-only per-organization provenance and causal paired-decision recomputation. No labels, TEST, training, threshold/policy changes or future campaign information.')
destination=BASE/'delivery_audit_v1.json';assert not destination.exists();destination.write_text(json.dumps(audit,indent=2)+'\n')
# Preserve hashed final report; produce an additive copy with readable Markdown tables.
original=(BASE/'final_v1/ACCEPTANCE_REPORT.md').read_text(encoding='utf-8').splitlines();fixed=[]
for i,line in enumerate(original):
 if not line.strip():
  previous=next((v for v in reversed(fixed) if v.strip()),'');following=next((v for v in original[i+1:] if v.strip()),'')
  if previous.startswith('|') and following.startswith('|'):continue
 fixed.append(line)
fixed+=['','## Fresh actual local inference resource measurements','',
 '| Org | Replay wall (s) | CPU (s) | End-to-end p95 (s) | Sampling + scoring p95 (s) | Observed RSS peak (MiB) | Exact accepted local match |',
 '|---|---:|---:|---:|---:|---:|---|']
for org in cfg['organizations']:
 r=load(BASE/'local_v1'/org/'summary.json')['local'];fixed.append(f"| {org} | {r['resources']['elapsed_seconds']:.6f} | {r['resources']['process_cpu_seconds']:.6f} | {r['latency_seconds']['timestamp_end_to_end']['p95']:.6f} | {r['latency_seconds']['model_scoring']['p95']:.6f} | {r['resources']['observed_rss_peak_bytes']/1048576:.3f} | Yes |")
fixed+=['',f"An independent audit verified all {sum(r['paired_rows'] for r in records):,} primary paired decisions, {sum(r['additional_event_rows'] for r in records):,} separate event-only rows and {len(public):,} issued indicators against local original alerts and observable ten-minute evidence. Every recipient decision was independently recomputed using availability, exact exclusive expiry and current authentication. No source journal changed. See delivery_audit_v1.json.",'',
 'Models and thresholds remain exactly the accepted originals. Sampling + scoring includes sampled-batch construction and forward passes. Fresh materialization runs overlapped on one CPU research host, two Torch threads per org. These resource measurements are workload observations, not production requirements or an SLA.',
 '',audit['timing_scope']]
report=BASE/'TECHNICAL_ACCEPTANCE_REPORT_v1.md';assert not report.exists();report.write_text('\n'.join(fixed)+'\n',encoding='utf-8')
print(json.dumps(dict(status=audit['status'],paired_rows=sum(r['paired_rows'] for r in records),indicators=len(public),prior_files_preserved=len(old))))
