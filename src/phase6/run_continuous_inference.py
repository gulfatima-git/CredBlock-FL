"""Demonstrate all-five independent event-to-alert loops without TEST or ground truth."""
import argparse,json,hashlib,sqlite3,time,platform
from pathlib import Path
from datetime import datetime,timedelta
import numpy as np
import psutil,torch
from src.organization.rolling_graph_v1 import RollingGraph
from src.phase6.readiness import ROOT,load,sha
from src.phase6.input_pipeline import PinnedInputs
from src.phase6.local_graphsage import state_digest
from src.phase6.fpr_calibration import canonical_digest
from src.phase6.training_data import dump_json
from src.phase6.temporal_protocol import require
from src.phase6.inference_registry import LocalModelRegistry
from src.phase6.local_inference import LocalInference
from src.phase6.inference_replay import load_stream

BASE=ROOT/'reports/phase6/inference'

def pinned_configuration():
    config=load(ROOT/'configs/phase6/continuous_inference_v1.json');pins=load(BASE/'preregistration_v1.json')
    require(sha(ROOT/'configs/phase6/continuous_inference_v1.json')==pins['configuration_sha256'],'Inference configuration changed')
    for p,h in pins['source_sha256'].items():require(sha(ROOT/p)==h,'Inference source changed: '+p)
    return config,pins

def replay(organization,kind,graph_blob,schedule,source,output,config,registry_pins,restart):
    require(not output.exists(),'Replay output exists; no overwrite');output.mkdir(parents=True)
    local=output/'private';local.mkdir();path=local/'inference.sqlite'
    registry=LocalModelRegistry(ROOT,organization,registry_pins)
    original_weights=state_digest(registry.current.model.state_dict());initial=RollingGraph.from_checkpoint_bytes(graph_blob)
    service=LocalInference(path,organization,source['variant_id'],registry,config,initial,source_identity=source)
    initial_graph_id=id(service.runtime.graph);latencies=[];rss=[];queue_finish=0.;max_backlog=0.;restart_metrics=None
    cut=len(schedule)//2
    if cut%config['persistence']['checkpoint_every_commits']==0:cut+=1
    start=time.perf_counter();cpu=time.process_time();retained_peak=0
    try:
        for i,(t,item) in enumerate(schedule):
            if restart and i==cut:
                before=service.runtime.graph.checkpoint_bytes();cursor=service.input_offset;digest=service.decision_digest();service.close()
                clock=time.perf_counter();service=LocalInference(path,organization,source['variant_id'],registry,config,source_identity=source)
                require(service.runtime.graph.checkpoint_bytes()==before and service.input_offset==cursor and service.decision_digest()==digest,'Restart changed committed graph/cursor/scores')
                require(service.recovered_commands>0,'Journal recovery was not exercised')
                restart_metrics=dict(at_commit=i,replayed_committed_commands=service.recovered_commands,restore_seconds=time.perf_counter()-clock,input_offset=cursor,exact_graph_and_decisions=True)
                initial_graph_id=id(service.runtime.graph)
            result=service.process_batch(t,item['observations'],item['tokens'],item['heartbeat'],item['final']) if item['observations'] else service.tick(t,item['final'])
            require(id(service.runtime.graph)==initial_graph_id,'Graph instance replaced between updates')
            latencies.append(result);rss.append(psutil.Process().memory_info().rss);retained_peak=max(retained_peak,len(service.runtime.graph.retained.nodes))
            arrival=(t-datetime.fromisoformat(source['anchor'])).total_seconds();queue_finish=max(queue_finish,arrival)+result['elapsed_seconds'];max_backlog=max(max_backlog,queue_finish-arrival)
            if (i+1)%100==0 or i+1==len(schedule):print(json.dumps(dict(event='inference_progress',organization=organization,run=kind,commands=i+1,total=len(schedule),events=service.input_offset)),flush=True)
        require(service.input_offset==source['events'],'Full-hour source observations not consumed')
        require(service.last_time==datetime.fromisoformat(source['end_exclusive'])-timedelta(microseconds=1),'Final-ten-minute coverage lost')
        require(state_digest(registry.current.model.state_dict())==original_weights,'Model retrained or mutated')
        count=service.db.execute("SELECT COUNT(*),SUM(decision='ALERT'),SUM(decision='NO_ALERT') FROM scores").fetchone()
        failures=service.db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]
        require(count[0]>0 and failures==0,'No operational scores or processing failure')
        last_ten=datetime.fromisoformat(source['anchor'])+timedelta(minutes=50)
        events_final=sum(len(item['observations']) for t,item in schedule if t>=last_ten)
        scores_final=service.db.execute('SELECT COUNT(*) FROM scores WHERE asof>=?',(last_ten.isoformat(),)).fetchone()[0]
        elapsed=time.perf_counter()-start
        vector=lambda name:np.asarray([r[name] for r in latencies],dtype=float)
        statistics=lambda z:dict(mean=float(z.mean()),p50=float(np.quantile(z,.5)),p95=float(np.quantile(z,.95)),p99=float(np.quantile(z,.99)),maximum=float(z.max()))
        examples={}
        for decision in ['ALERT','NO_ALERT']:
            example=service.db.execute('SELECT asof,trigger,logit_hex,threshold_hex,decision,model_sha256,threshold_sha256 FROM scores WHERE decision=? ORDER BY seq,user_id LIMIT 1',(decision,)).fetchone()
            examples[decision]=dict(zip(['asof','trigger','logit_hex','threshold_hex','decision','model_sha256','threshold_sha256'],example)) if example else None
        first=service.db.execute("SELECT MIN(asof) FROM scores WHERE decision='ALERT'").fetchone()[0]
        summary=dict(status='PASS_REPRESENTATIVE_REAL_FULL_HOUR_OPERATIONAL_REPLAY',organization=organization,run=kind,scope='One frozen VAL branch; no TEST or ground-truth evaluation',
            events=service.input_offset,timestamp_commands=len(schedule),user_scores=count[0],alerts=count[1],no_alerts=count[2],processing_failures=failures,
            final_ten_minutes=dict(events=events_final,user_scores=scores_final,last_flush=service.last_time.isoformat(),covered=True),
            decision_digest=service.decision_digest(),final_graph_checkpoint_sha256=hashlib.sha256(service.runtime.graph.checkpoint_bytes()).hexdigest(),
            unchanged_model_state_digest=original_weights,bundle_fingerprint=registry.current.fingerprint,restart=restart_metrics,
            latency_seconds=dict(timestamp_end_to_end=statistics(vector('elapsed_seconds')),graph_update=statistics(vector('graph_update_seconds')),
                feature_and_sampler=statistics(vector('feature_and_sampler_seconds')),model_scoring=statistics(vector('model_scoring_seconds')),
                amortized_processing_per_input_event=sum(r['elapsed_seconds'] for r in latencies)/source['events']),
            resources=dict(elapsed_seconds=elapsed,process_cpu_seconds=time.process_time()-cpu,observed_rss_peak_bytes=max(rss),process_peak_rss_bytes=getattr(psutil.Process().memory_info(),'peak_wset',max(rss)),retained_node_peak=retained_peak,
                replay_events_per_wall_second=source['events']/elapsed,serial_simulated_max_finish_lag_seconds=max_backlog,
                backlog_definition='Hypothetical single serial server with source timestamp arrivals and observed processing costs; not a real deployment backlog',torch_threads=torch.get_num_threads(),device='cpu'),
            first_alert_offset_seconds_from_replay_start=(datetime.fromisoformat(first)-datetime.fromisoformat(source['anchor'])).total_seconds() if first else None,
            first_alert_interpretation='Local alert chronology only; not ground-truth time-to-detection',examples=examples,
            evaluation_unit='Operational triggered local User score; not primary eligible fixed-grid User-window',event_driven_fpr=None,event_driven_recall=None,
            privacy='Private store contains local User IDs, raw journal and graph. Aggregate report omits identifiers.',private_store=str(path.relative_to(ROOT)))
        require(events_final>0 and scores_final>0,'No final-ten-minute operational evidence')
        dump_json(output/'latency_records.json',latencies);dump_json(output/'summary.json',summary)
    finally:service.close()
    return summary

def run_org(org):
    config,prereg=pinned_configuration();require(org in config['organizations'],'Unknown organization')
    torch.set_num_threads(config['torch_threads']);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    out=BASE/'v1'/org;require(not out.exists(),'Organization result exists');out.mkdir(parents=True)
    pins=PinnedInputs(ROOT);started=time.perf_counter();graph,schedule,source=load_stream(pins,config['demonstration']['variant_id'],org)
    graph_blob=graph.checkpoint_bytes();del graph
    dump_json(out/'source_identity.json',source);dump_json(out/'config_snapshot.json',config)
    first=replay(org,'uninterrupted',graph_blob,schedule,source,out/'uninterrupted',config,prereg['registry'],False)
    repeated=replay(org,'restart_repeat',graph_blob,schedule,source,out/'restart_repeat',config,prereg['registry'],True)
    require(first['decision_digest']==repeated['decision_digest'] and first['final_graph_checkpoint_sha256']==repeated['final_graph_checkpoint_sha256'],'Uninterrupted/restarted inference differs')
    require(not any(name.endswith('_labels.parquet') or name.endswith('_replay.parquet') or '_TEST/' in name for name in pins.checked),'Ground-truth or TEST source was opened')
    pins.verify_unchanged();pinned_configuration()
    result=dict(status='PASS_LOCAL_INFERENCE_AND_EXACT_RECOVERY_COMPONENT',organization=org,uninterrupted=first,restarted=repeated,
                exact_score_alert_and_graph_reproduction=True,source=source,elapsed_seconds=time.perf_counter()-started,test_files_opened=0,
                input_sha256=pins.checked,private_scope='Raw events and User IDs remain in organization-local SQLite stores')
    dump_json(out/'summary.json',result)
    dump_json(out/'artifact_sha256.json',{p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()})
    print(json.dumps(dict(event='organization_complete',organization=org,events=first['events'],alerts=first['alerts'],reproduced=True)),flush=True)

def finalize():
    config,prereg=pinned_configuration();output=BASE/'final_v1';require(not output.exists(),'Final output exists')
    tests=load(BASE/'testing_results_v1.json');require(tests['status']=='PASS','Tests not complete')
    records=[]
    for org in config['organizations']:
        directory=BASE/'v1'/org;r=load(directory/'summary.json')
        require(r['status']=='PASS_LOCAL_INFERENCE_AND_EXACT_RECOVERY_COMPONENT' and r['exact_score_alert_and_graph_reproduction'] and r['test_files_opened']==0,'Incomplete local inference component')
        for path,h in load(directory/'artifact_sha256.json').items():require(sha(directory/path)==h,'Inference artifact changed: '+path)
        for a in [r['uninterrupted'],r['restarted']]:
            require(a['events']==r['source']['events'] and a['processing_failures']==0 and a['alerts']+a['no_alerts']==a['user_scores'],'Operational census mismatch')
            require(a['final_ten_minutes']['covered'] and a['final_ten_minutes']['events']>0,'Missing final interval')
            db=sqlite3.connect('file:'+str(ROOT/a['private_store'])+'?mode=ro',uri=True)
            require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Private journal integrity failure')
            require(db.execute('SELECT COUNT(*) FROM event_tokens').fetchone()[0]==a['events'],'Source offset/token mismatch')
            require(db.execute("SELECT COUNT(*) FROM scores WHERE processing_status!='OK'").fetchone()[0]==0,'Bad processing record')
            db.close()
        require(r['restarted']['restart']['replayed_committed_commands']>0,'No actual journal recovery')
        require(r['uninterrupted']['decision_digest']==r['restarted']['decision_digest'] and r['uninterrupted']['final_graph_checkpoint_sha256']==r['restarted']['final_graph_checkpoint_sha256'],'Recovery reproducibility mismatch')
        records.append(r)
    preserved=load(BASE/'accepted_inputs_before_subphase6_v1.json')
    for p,h in preserved.items():require(sha(ROOT/p)==h,'Accepted artifact changed: '+p)
    output.mkdir();summary=dict(status='PASS_SUBPHASE6_FIVE_LOCAL_INFERENCE_LOOPS_AWAITING_USER_ACCEPTANCE',organizations=5,records=records,
        evidence_scope='Representative full-hour frozen VAL replay per organization plus exact independent restart replay; not all branches or final TEST evaluation',
        tests=tests,accepted_files_preserved=len(preserved),protocol_sha256=config['protocol_sha256'],
        model_training_performed=False,threshold_calibration_performed=False,test_files_opened=0,event_driven_fpr_claimed=False,
        next_action='User acceptance of Subphase 6; Subphase 7 NOT_STARTED')
    dump_json(output/'summary.json',summary)
    lines=['# Phase 6 Subphase 6 (6.4): Continuous Local Inference','',
      '**Technical gate: PASS; user acceptance pending.** Subphase 5 USER_ACCEPTED is recorded append-only in calibration/acceptance_v1.json.','',
      '## Implemented local event-to-alert workflow','',
      'Each organization has its own hash-verified original GraphSAGE model, sealed threshold and SQLite store. Complete timestamp batches update the same accepted seven-day RollingGraph object before feature export and scoring. An additive adjacency index selects surviving User nodes in pre/post two-hop closures of endpoints changed by observations or ten-minute/seven-day expiration. Ten-minute heartbeats and a final-hour flush additionally score observable recent Users. Labels, target membership, attacker metadata and credentials are absent from the service and replay loader. The accepted sampler/schema/transforms/fanouts/seed are unchanged. No optimization or recalibration occurs.','',
      'The exact binary64 helper compares unrounded logits against the original frozen threshold. Every decision logs local User, timestamp, trigger, exact logit/threshold encoding, model/schema/threshold versions, alert/no-alert, processing status and scoring-stage latency. Commands record graph/feature/model costs; external per-command measurements include persistence and checkpoint costs. Failure records never become no-alert decisions.','',
      'SQLite WAL with synchronous FULL commits input commands/tokens, decisions and state digest atomically. Accepted-runtime graph checkpoints are saved periodically and at final flush. Restart validates org/stream/bundle/config/source identities, restores a hashed checkpoint, replays committed commands without duplicating alert records, restores input cursor and verifies state. Failed post-mutation processing faults the client until recovery. Invalid registry candidates are rejected while retaining the last usable original bundle. This is local hash validation, not federated/Fabric adoption.','',
      '## Per-organization real full-hour evidence','',
      '| Organization | Events | Timestamp commands | User scores | Alerts | No-alert | Final-ten-minute events | End-to-end p95 (s) | Model p95 (s) | RSS peak MiB | Exact restart repeat |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in records:
        a=r['uninterrupted'];lines.append(f"| {r['organization']} | {a['events']} | {a['timestamp_commands']} | {a['user_scores']} | {a['alerts']} | {a['no_alerts']} | {a['final_ten_minutes']['events']} | {a['latency_seconds']['timestamp_end_to_end']['p95']:.6f} | {a['latency_seconds']['model_scoring']['p95']:.6f} | {a['resources']['observed_rss_peak_bytes']/1048576:.3f} | Yes |")
    lines+=['','All five primary runs and five independent restart repeats consume the entire observation hour, including events after minute 50, and flush at the last microsecond before the exclusive end. Source counts, final graph bytes and canonical score/alert records match exactly between uninterrupted and restarted execution. The restart point deliberately falls after a checkpoint so committed journal replay is exercised.','',
      'Full precision measurements, p50/p95/p99/max graph/feature/scoring/end-to-end costs, observed replay throughput, hypothetical serialized-server backlog, first local alert offset, final-ten-minute score counts, recovery costs and redacted alert/no-alert examples are in summary.json. Private per-User decision and raw-event journals remain in each organization directory. All processing failures in valid real replay are zero. Synthetic failure, schema and restart cases are recorded separately in automated test evidence.','',
      '## Evidence scope and research boundaries','',
      'The predeclared demonstration is one full frozen VAL branch (CFV1_SO_CS_027_SEED1001_VAL) in every organization, not all 513 alternative worlds, million-node operational benchmarking, TEST evaluation or deployed live traffic. The independent repeat restarts midway and verifies exact recovery. Sampling and target selection are deterministic functions of observable graph history, clock and local namespace. The namespace is used only by the accepted sampling policy and source audit, not as a numeric feature or target-selection oracle.','',
      'Operational scoring units are event/heartbeat-triggered local User scores. They are distinct from the accepted eligible fixed-grid User-windows. No operational FPR/recall is calculated or claimed, and calibrated 1% VAL grid FPR does not imply 1% on arbitrary event scoring. Positives/labels are not opened here. Local first-alert offset is not ground-truth time-to-detection; later offline evaluation can join complete private logs, including the final ten minutes, under its own authorized protocol.','',
      'The replay adapter buffers a complete timestamp group; a real live producer still needs a completeness/watermark contract. Earlier/repeated timestamps and duplicate tokens fail before graph mutation. The proof adapter is VAL-only and rejects TEST before source access; deployment and authorization of other replay periods require a later explicit protocol/adapter decision. SQLite storage and process boundaries are logically organization-local on one research host, not production tenant security. The command/decision journal is retained for audit and has no production archival/compaction policy yet.','',
      'Feature export and CSR construction still scan the accepted retained graph. Observed shared-host CPU/memory/throughput on the representative graph do not establish million-node or production scalability. Event-driven sampling may vary with timestamp by the accepted policy; the affected-node policy does not promise rescoring every otherwise unchanged User on every event. No external alert-delivery system, real-time scheduler daemon, indicator sharing, federation, DP or blockchain is implemented.','',
      '## Tests, provenance and preservation','',
      'See ../testing_results_v1.json and ../preregistration_v1.json for exact commands, scientific policy and source pins. Unit tests cover duplicate/out-of-order data, complete tied timestamps, label/metadata rejection, causal views, expiration boundaries, neighborhood targets, graph identity, startup/model/schema mismatch, retained fallback, atomic failures, tampered checkpoints and committed-journal restart. Real integration and its resource evidence are distinct from synthetic tests.','',
      f"All {len(preserved)} inventoried prior accepted/support artifacts remain byte-identical, including all ten threshold JSONs, comparison and calibration results, original validation predictions, both model families, binary64 helper, feature schema and frozen protocol. Protocol SHA256: `{config['protocol_sha256']}`.",'',
      'A version-control commit of the frozen protocol remains required before any later final TEST evaluation; this subphase does not certify that commit. Review and explicitly accept Subphase 6 before Subphase 7.']
    (output/'ACCEPTANCE_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    dump_json(output/'artifact_sha256.json',{p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()})
    progress=load(ROOT/'reports/phase6/progress_v6.json');progress['version']='phase6-progress-v7'
    progress['subphases']['5']={'status':'USER_ACCEPTED','evidence':'reports/phase6/calibration/acceptance_v1.json'}
    progress['subphases']['6']={'status':'TECHNICAL_GATE_PASS_AWAITING_USER_ACCEPTANCE','evidence':'reports/phase6/inference/final_v1/ACCEPTANCE_REPORT.md','organizations':5}
    progress['next_exact_action']=summary['next_action'];dump_json(ROOT/'reports/phase6/progress_v7.json',progress)
    print(json.dumps(dict(status=summary['status'],organizations=5,preserved=len(preserved))),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--organization');p.add_argument('--finalize',action='store_true');a=p.parse_args()
    if a.finalize:finalize()
    else:run_org(a.organization)
