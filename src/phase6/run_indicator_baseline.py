"""Frozen separate comparator; original local inference stays untouched."""
import argparse,json,hashlib,sqlite3,time,platform,sys
from pathlib import Path
from datetime import datetime
import numpy as np,psutil,torch
from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.training_data import dump_json
from src.phase6.input_pipeline import PinnedInputs
from src.phase6.run_continuous_inference import replay,pinned_configuration
from src.organization.rolling_graph_v1 import RollingGraph,OrganizationGraphRuntime
from src.phase6.inference_replay import load_stream
from src.phase6.indicator_sharing import Issuer,Recipient,Network,combine,canonical,WIRE

BASE=ROOT/'reports/phase6/indicator_baseline'
CONFIG=ROOT/'configs/phase6/indicator_sharing_v1.json'
SOURCES=['src/phase6/indicator_sharing.py','src/phase6/run_indicator_baseline.py','tests/phase6/test_indicator_sharing.py']

def freeze():
    destination=BASE/'preregistration_v1.json';require(not destination.exists(),'Policy already frozen')
    cfg=load(CONFIG);local,pins=pinned_configuration()
    require(cfg['organizations']==local['organizations'] and cfg['protocol_sha256']==local['protocol_sha256'],'Policy protocol identity mismatch')
    require(cfg['split']=='VAL' and cfg['variant_id']==local['demonstration']['variant_id'],'VAL proof identity mismatch')
    require(cfg['ttl_seconds']==600 and cfg['attribution_window_seconds']==600 and set(cfg['wire_fields'])==WIRE,'Policy contract mismatch')
    for p,h in pins['design_document_sha256'].items():require(sha(Path(p))==h,'Authoritative design document changed')
    dump_json(destination,dict(status='FROZEN_BEFORE_COMPARISON_OUTCOMES',configuration_sha256=sha(CONFIG),policy=cfg,
        source_sha256={p:sha(ROOT/p) for p in SOURCES},accepted_local_preregistration_sha256=sha(ROOT/'reports/phase6/inference/preregistration_v1.json'),
        accepted_inference_delivery_manifest_sha256=sha(ROOT/'reports/phase6/inference/delivery_manifest_v1.json'),design_document_sha256=pins['design_document_sha256'],
        decision='One preregistered descriptive ten-minute TTL/evidence policy; no search, tuning, TEST or accepted protocol amendment.'))
    print(json.dumps(dict(status='POLICY_FROZEN',configuration_sha256=sha(CONFIG))))

def pinned():
    p=load(BASE/'preregistration_v1.json');cfg=load(CONFIG)
    require(sha(CONFIG)==p['configuration_sha256'],'Policy changed after freeze')
    for path,h in p['source_sha256'].items():require(sha(ROOT/path)==h,'Source changed after freeze: '+path)
    require(sha(ROOT/'reports/phase6/inference/delivery_manifest_v1.json')==p['accepted_inference_delivery_manifest_sha256'],'Accepted local manifest changed')
    local,registry=pinned_configuration()
    return cfg,local,registry

def materialize(org):
    cfg,local,registry=pinned();require(org in cfg['organizations'],'Unknown organization')
    torch.set_num_threads(local['torch_threads']);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    directory=BASE/'local_v1'/org;require(not directory.exists(),'No overwrite');directory.mkdir(parents=True)
    pins=PinnedInputs(ROOT);graph,schedule,source=load_stream(pins,cfg['variant_id'],org)
    require(source==load(ROOT/f'reports/phase6/inference/v1/{org}/source_identity.json'),'Changed accepted observation stream')
    blob=graph.checkpoint_bytes();del graph
    result=replay(org,'indicator_baseline_local_materialization',blob,schedule,source,directory/'uninterrupted',local,registry['registry'],False)
    accepted=load(ROOT/f'reports/phase6/inference/v1/{org}/uninterrupted/summary.json')
    for key in ['decision_digest','final_graph_checkpoint_sha256','unchanged_model_state_digest','bundle_fingerprint','events','user_scores','alerts','no_alerts','final_ten_minutes']:
        require(result[key]==accepted[key],'Fresh local inference differs from accepted local-only evidence: '+key)
    require(not any(n.endswith('_labels.parquet') or n.endswith('_replay.parquet') or '_TEST/' in n for n in pins.checked),'Forbidden evaluator input')
    pins.verify_unchanged();pinned()
    dump_json(directory/'source_identity.json',source);dump_json(directory/'policy_snapshot.json',cfg)
    dump_json(directory/'summary.json',dict(status='PASS_FRESH_LOCAL_INFERENCE_EXACT_ACCEPTED_BASELINE',organization=org,local=result,input_sha256=pins.checked,test_files_opened=0))
    dump_json(directory/'artifact_sha256.json',{p.relative_to(directory).as_posix():sha(p) for p in directory.rglob('*') if p.is_file()})
    print(json.dumps(dict(status='LOCAL_MATERIALIZATION_PASS',organization=org,events=result['events'])),flush=True)

class LocalAdapter:
    """Private local journal/state adapter; returns only IP indicator envelopes."""
    def __init__(self,org,cfg,directory):
        self.organization,self.cfg=org,cfg
        source=BASE/'local_v1'/org
        for p,h in load(source/'artifact_sha256.json').items():require(sha(source/p)==h,'Fresh local evidence changed')
        self.accepted=load(source/'summary.json');require(self.accepted['status']=='PASS_FRESH_LOCAL_INFERENCE_EXACT_ACCEPTED_BASELINE','Local inference incomplete')
        path=ROOT/self.accepted['local']['private_store'];self.source_hash=sha(path)
        self.db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro',uri=True)
        require(self.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Local source journal corrupt')
        cp=self.db.execute('SELECT graph,sha256 FROM checkpoints WHERE seq=0').fetchone()
        require(hashlib.sha256(cp[0]).hexdigest()==cp[1],'Initial graph checkpoint mismatch')
        self.runtime=OrganizationGraphRuntime(org,RollingGraph.from_checkpoint_bytes(cp[0]));self.graph_id=id(self.runtime.graph)
        self.iterator=iter(self.db.execute('SELECT seq,asof,payload FROM commands ORDER BY seq'));self.next=next(self.iterator,None)
        self.issuer=Issuer(org,cfg);self.receiver=Recipient(org,cfg)
        private=directory/org/'private';private.mkdir(parents=True)
        self.private=private;self.decisions=(private/'paired_decisions.jsonl').open('x',encoding='utf-8')
        self.extra=(private/'additional_event_decisions.jsonl').open('x',encoding='utf-8');self.digest=hashlib.sha256();self.extra_digest=hashlib.sha256()
        self.stats=dict(organization=org,events=0,commands=0,paired_rows=0,local_alerts=0,local_plus_alerts=0,added_alerts=0,no_alerts_local_plus=0,matched_paired_rows=0,additional_event_users=0,additional_indicator_alerts=0,final_ten_minutes_events=0,final_ten_minutes_paired_rows=0)
        self.used=set();self.latency=[];self.frame=None
        model_pins=load(ROOT/'reports/phase6/inference/preregistration_v1.json')['registry']['models'][org]
        self.threshold=load(ROOT/model_pins['threshold_path'])['calibration']['threshold'];self.model_pins=model_pins

    def next_time(self):return datetime.fromisoformat(self.next[1]) if self.next else None

    def prepare(self,t):
        require(self.next_time()==t,'Wrong local command clock')
        start=time.perf_counter();seq,asof,payload=self.next;command=json.loads(payload)
        rows=[dict(r,**{'Login Timestamp':datetime.fromisoformat(r['Login Timestamp'])}) for r in command['observations']]
        if rows:self.runtime.apply_timestamp_batch(t,rows,command['tokens'])
        else:self.runtime.advance(t)
        require(id(self.runtime.graph)==self.graph_id,'Graph replaced during sharing replay')
        scores=[dict(zip(['user_id','logit_hex','threshold_hex','decision','alert_id','model_sha256','threshold_sha256'],r)) for r in self.db.execute('SELECT user_id,logit_hex,threshold_hex,decision,alert_id,model_sha256,threshold_sha256 FROM scores WHERE seq=? ORDER BY user_id',(seq,))]
        for s in scores:
            require(s['threshold_hex']==self.threshold['hex'] and s['model_sha256']==self.model_pins['model_sha256'] and s['threshold_sha256']==self.model_pins['threshold_sha256'],'Unsealed local score identity')
            require(s['decision']==('ALERT' if float.fromhex(s['logit_hex'])>=float.fromhex(s['threshold_hex']) else 'NO_ALERT'),'Local binary64 rule changed')
        alerts=[{k:s[k] for k in ['user_id','alert_id','decision']} for s in scores if s['decision']=='ALERT']
        payloads=self.issuer.attribute(t,self.runtime.graph,alerts)
        current={}
        for r in rows:current.setdefault(r['User ID'],set()).add(r['IP Address'])
        self.frame=(seq,t,rows,scores,current,start)
        self.next=next(self.iterator,None)
        return payloads

    def finish(self,t):
        require(self.frame is not None and self.frame[1]==t,'No prepared local command')
        seq,_,rows,scores,current,start=self.frame;self.frame=None
        stats=self.stats;stats['events']+=len(rows);stats['commands']+=1
        cutoff=datetime.fromisoformat(self.accepted['local']['final_ten_minutes']['last_flush']).replace(minute=50,second=0,microsecond=0)
        final=t>=cutoff
        if final:stats['final_ten_minutes_events']+=len(rows);stats['final_ten_minutes_paired_rows']+=len(scores)
        scored=set()
        for score in scores:
            user=score['user_id'];scored.add(user);local=score['decision']=='ALERT'
            combined,hits=combine(local,current.get(user,set()),self.receiver,t);self.used.update(hits)
            value=dict(seq=seq,at=t.isoformat(),user_id=user,local_logit_hex=score['logit_hex'],threshold_hex=score['threshold_hex'],local_alert=local,local_plus_indicator_alert=combined,indicator_ids=hits)
            line=canonical(value)+'\n';self.decisions.write(line);self.digest.update(line.encode())
            stats['paired_rows']+=1;stats['local_alerts']+=int(local);stats['local_plus_alerts']+=int(combined);stats['added_alerts']+=int(combined and not local);stats['no_alerts_local_plus']+=int(not combined);stats['matched_paired_rows']+=int(bool(hits))
            for key in hits:self.receiver.log.append(dict(event='utilization_paired',organization=self.organization,indicator_id=key,at=t.isoformat()))
        for user in sorted(set(current)-scored):
            _,hits=combine(False,current[user],self.receiver,t);self.used.update(hits)
            value=dict(seq=seq,at=t.isoformat(),user_id=user,local_status='NOT_SCORED',local_plus_indicator_alert=bool(hits),indicator_ids=hits)
            line=canonical(value)+'\n';self.extra.write(line);self.extra_digest.update(line.encode());stats['additional_event_users']+=1;stats['additional_indicator_alerts']+=int(bool(hits))
            for key in hits:self.receiver.log.append(dict(event='utilization_additional_event',organization=self.organization,indicator_id=key,at=t.isoformat()))
        self.latency.append(time.perf_counter()-start)

    def close(self,directory):
        self.decisions.close();self.extra.close();local=self.accepted['local']
        require(self.stats['events']==local['events'] and self.stats['paired_rows']==local['user_scores'] and self.stats['local_alerts']==local['alerts'],'Paired accepted local census mismatch')
        require(self.stats['final_ten_minutes_events']==local['final_ten_minutes']['events'] and self.stats['final_ten_minutes_paired_rows']==local['final_ten_minutes']['user_scores'],'Final ten minutes lost')
        graph=hashlib.sha256(self.runtime.graph.checkpoint_bytes()).hexdigest();require(graph==local['final_graph_checkpoint_sha256'],'Sharing replay changed local graph')
        self.db.close();path=ROOT/local['private_store'];require(sha(path)==self.source_hash,'Local journal changed')
        with (self.private/'issuance_provenance.jsonl').open('x',encoding='utf-8') as f:
            for r in self.issuer.provenance:f.write(canonical(r)+'\n')
        with (directory/self.organization/'indicator_events.jsonl').open('x',encoding='utf-8') as f:
            for r in self.receiver.log:f.write(canonical(r)+'\n')
        stats=self.stats;stats.update(issued=len(self.issuer.provenance),suppressed_live_duplicates=self.issuer.suppressed,alerts_without_recent_evidence=self.issuer.without_evidence,
            received=sum(r['event']=='receipt' for r in self.receiver.log),expired_receipts=len(self.receiver.expired),unique_indicators_utilized=len(self.used),
            utilization_records=sum(r['event'].startswith('utilization_') for r in self.receiver.log),paired_decision_digest=self.digest.hexdigest(),additional_decision_digest=self.extra_digest.hexdigest(),final_graph_sha256=graph,
            sharing_adapter_seconds=dict(mean=float(np.mean(self.latency)),p95=float(np.quantile(self.latency,.95)),maximum=max(self.latency)),
            scope='Adapter cost includes private journal reads, graph replay, attribution, indicator matching and decision buffering; excludes already measured fresh GNN materialization and final file close.')
        dump_json(directory/self.organization/'summary.json',stats)
        return stats

def compare(name,reverse=False):
    cfg,_,_=pinned();directory=BASE/name;require(not directory.exists(),'No overwrite');directory.mkdir(parents=True)
    start=time.perf_counter();cpu=time.process_time();adapters={o:LocalAdapter(o,cfg,directory) for o in cfg['organizations']}
    network=Network(cfg,{o:a.receiver for o,a in adapters.items()});order=list(adapters)
    if reverse:order.reverse()
    rss=[];ticks=0
    while True:
        clocks=[a.next_time() for a in adapters.values() if a.next_time() is not None]
        expiry=network.next_expiry()
        if expiry is not None:clocks.append(expiry)
        if not clocks:break
        t=min(clocks);network.advance(t);active=[o for o in order if adapters[o].next_time()==t];payloads=[]
        for org in active:payloads.extend(adapters[org].prepare(t))
        network.publish(payloads,t)
        for org in active:adapters[org].finish(t)
        rss.append(psutil.Process().memory_info().rss);ticks+=1
        if ticks%500==0:print(json.dumps(dict(event='sharing_progress',run=name,ticks=ticks,at=t.isoformat())),flush=True)
    records=[adapters[o].close(directory) for o in cfg['organizations']]
    with (directory/'network_events.jsonl').open('x',encoding='utf-8') as f:
        for value in network.log:f.write(canonical(value)+'\n')
    require(len(network.expired)==len(network.created),'Indicators did not expire')
    require(sum(r['received'] for r in records)==len(network.created)*4,'Broadcast/receipt count mismatch')
    summary=dict(status='PASS_PAIRED_OPERATIONAL_INDICATOR_COMPARISON_COMPONENT',records=records,issued_total=len(network.created),expired_total=len(network.expired),
        network_digest=hashlib.sha256(canonical(network.log).encode()).hexdigest(),final_expiry_clock=network.clock.isoformat(),
        elapsed_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu,observed_rss_peak_bytes=max(rss),global_ticks=ticks,
        scope='One complete VAL hour in each organization. Expiry-only drain may extend ten minutes past observation end; no new observations scored during drain.',
        false_positive_rate=None,recall=None,ground_truth_labels_opened=0,test_files_opened=0,simulated_propagation_delay_seconds=0)
    dump_json(directory/'summary.json',summary);dump_json(directory/'artifact_sha256.json',{p.relative_to(directory).as_posix():sha(p) for p in directory.rglob('*') if p.is_file()})
    print(json.dumps(dict(status=summary['status'],run=name,issued=summary['issued_total'])),flush=True)

def finalize():
    cfg,_,_=pinned();a=load(BASE/'paired_v1/summary.json');b=load(BASE/'reverse_order_v1/summary.json')
    require(a['status']==b['status']=='PASS_PAIRED_OPERATIONAL_INDICATOR_COMPARISON_COMPONENT','Comparison incomplete')
    require(a['network_digest']==b['network_digest'],'Organization iteration order changed public network')
    for x,y in zip(a['records'],b['records']):
        for k in x:
            if k not in ['sharing_adapter_seconds']:require(x[k]==y[k],'Nonreproducible result: '+k)
    for directory in [BASE/'paired_v1',BASE/'reverse_order_v1']+[BASE/'local_v1'/o for o in cfg['organizations']]:
        for p,h in load(directory/'artifact_sha256.json').items():require(sha(directory/p)==h,'New evidence changed: '+p)
    tests=load(BASE/'testing_results_v1.json');require(tests['status']=='PASS','Tests incomplete')
    old=load(BASE/'accepted_inputs_before_subphase7_v1.json')
    for p,h in old.items():require(sha(ROOT/p)==h,'Accepted evidence changed: '+p)
    out=BASE/'final_v1';require(not out.exists(),'No overwrite');out.mkdir()
    summary=dict(status='PASS_SUBPHASE7_IMMEDIATE_INDICATOR_BASELINE_AWAITING_USER_ACCEPTANCE',organizations=5,comparison=a,reverse_order_reproduced=True,
        fresh_local_inference_exactly_matches_accepted=True,tests=tests,prior_files_preserved=len(old),policy_sha256=sha(CONFIG),protocol_sha256=cfg['protocol_sha256'],
        scope=cfg['evaluation'],test_used=False,ground_truth_used=False,next_action='User review/acceptance of Subphase 7; Subphase 8 NOT_STARTED')
    dump_json(out/'summary.json',summary)
    lines=['# Phase 6 Subphase 7 (6.5): Immediate indicator-sharing baseline','',
        '**Technical gate PASS for all five organizations; user acceptance pending.** Subphase 6 USER_ACCEPTED is recorded append-only in inference/acceptance_v1.json.','',
        'This is a separate research comparison baseline, not CredBlock-FL federation or the professor’s operational architecture. The original inference/model/threshold/runtime files were not changed.','',
        '## Frozen policy and causality','',cfg['attribution'],cfg['lifetime'],cfg['timestamp_barrier'],cfg['recipient_rule'],cfg['additional_event_users'],'',
        'False local alerts propagate unverified suspicion under exactly the same rule as any alert. There is no runtime malicious-IP oracle, benign-IP whitelist, synthetic-ID check or automatic correction based on labels. Shared benign addresses can create additional alerts. Rotation to an unflagged address provides no indicator match until fresh local evidence produces another local alert. No initial local alert means no shareable indicator. Only original GraphSAGE alerts issue indicators, preventing indicator-only cascades.','',
        '## Per-organization paired results','',
        '| Org | Events | Paired User scores | Local alerts | Local + indicator alerts | Added alerts | Issued | Received | Unique indicators used | Expired receipts |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in a['records']:lines.append('| '+' | '.join(str(r[k]) for k in ['organization','events','paired_rows','local_alerts','local_plus_alerts','added_alerts','issued','received','unique_indicators_utilized','expired_receipts'])+' |')
    lines+=['','All primary rows are paired with the accepted local-only score rows. Additional current-event Users without local scores are logged separately as NOT_SCORED; their indicator alerts are not counted as gains on paired rows. All observation events and the final ten minutes are preserved. Expiry-only drain runs after the last observation solely to demonstrate every lifetime ends.','',
        '## Reproducibility, resources and preservation','',
        'Five fresh full-hour actual GraphSAGE executions reuse the original LocalInference/replay pipeline, sealed models, thresholds, seven-day graphs and ten-minute features. Each exactly matches accepted Subphase 6 local-only scores/alerts, counts, final graph hash and model state. Because sharing has no feedback into local scoring, the comparison interleaves those immutable causal local journals without repeating expensive GNN work. Local adapters restore the original warm-up checkpoint and replay the same graph updates before attribution. Only public indicator envelopes cross adapters; local Users, source alerts, graph state and private features remain local.','',
        'The complete global sharing replay is repeated with reverse organization iteration. All per-organization decisions/counts, graph hashes and public network digest match exactly. Manifests, source/config pins, journal integrity, model fingerprints and binary64 decisions are checked. Tests and timing scope are in testing_results_v1.json and per-organization summaries.','',
        f"Primary sharing-adapter replay wall time: {a['elapsed_seconds']:.6f} s; CPU: {a['process_cpu_seconds']:.6f} s; observed RSS peak: {a['observed_rss_peak_bytes']/1048576:.3f} MiB. These exclude the separately reported fresh GNN materialization runs. Simulated propagation delay is zero by definition, not measured real network latency. File-close/hash costs are outside per-command adapter timing.",'',
        f"All {len(old):,} prior inventoried files remain byte-identical, including accepted Phase 5 data/evidence, original models and all ten threshold artifacts, earlier replay/recovery/cold-start reports and workbooks. Frozen primary protocol SHA256: `{cfg['protocol_sha256']}`.",'',
        '## Files and evidence','',
        '- configs/phase6/indicator_sharing_v1.json: frozen policy; src/phase6/indicator_sharing.py and run_indicator_baseline.py: additive source; tests/phase6/test_indicator_sharing.py: tests.',
        '- reports/phase6/indicator_baseline/preregistration_v1.json: policy/source/design-document pins before outcomes.',
        '- local_v1/Org1–Org5: actual fresh GraphSAGE local runs, source and policy snapshots, summaries and private journals.',
        '- paired_v1 and reverse_order_v1: network creation/broadcast/expiry logs, per-org receipt/utilization/expiry logs, aggregate statistics, private paired/additional decisions and private source-alert provenance.',
        '- final_v1/summary.json and artifact_sha256.json: exact results/resources and hashes; progress_v9.json: current subphase status.','',
        '## Limitations and next action','',
        'This proves mechanics and a paired operational comparison on one predeclared complete VAL hour per org, not all scenario families/seeds, final TEST, campaign detectability or production effectiveness. No labels were joined: extra alerts are not claimed to be true detections or false positives. No event-driven FPR/recall/TTD is calculated. The frozen 1% eligible fixed-grid User-window calibration does not transfer automatically to operational event decisions or the OR rule. Primary units, thresholds, eligibility masks and split protocol remain unchanged; later fixed-grid evaluation must use that protocol, not these operational counts.','',
        'Attribution may implicate benign/shared IPs associated with a targeted User; indicators are suspicious/unverified, not malicious labels. TTL is a preregistered ten-minute baseline choice, not a validated optimum. No manual correction/revocation beyond deterministic expiration is implemented. Zero simulated delay is optimistic; barriers and local execution occur in a research simulation, not a real distributed network. Logical organization isolation on one host is not production security. No final TEST, federation, differential privacy, robust aggregation or Fabric is implemented.','',
        'Next action: user review and explicit acceptance of Subphase 7. Subphase 8 NOT_STARTED. The frozen primary protocol must remain version-controlled before later final TEST evaluation.']
    (out/'ACCEPTANCE_REPORT.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    dump_json(out/'artifact_sha256.json',{p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()})
    progress=load(ROOT/'reports/phase6/progress_v8.json');progress['version']='phase6-progress-v9';progress['subphases']['7']={'status':'TECHNICAL_GATE_PASS_AWAITING_USER_ACCEPTANCE','evidence':'reports/phase6/indicator_baseline/final_v1/ACCEPTANCE_REPORT.md'};progress['next_exact_action']=summary['next_action'];dump_json(ROOT/'reports/phase6/progress_v9.json',progress)
    print(json.dumps(dict(status=summary['status'],prior_files_preserved=len(old))),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--organization');p.add_argument('--compare',action='store_true');p.add_argument('--reverse',action='store_true');p.add_argument('--finalize',action='store_true');a=p.parse_args()
    if a.freeze:freeze()
    elif a.organization:materialize(a.organization)
    elif a.compare:compare('reverse_order_v1' if a.reverse else 'paired_v1',a.reverse)
    elif a.finalize:finalize()
