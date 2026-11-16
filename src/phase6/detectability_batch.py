"""Append-only, resumable reference execution. Full run requires explicit review flag."""
import argparse,csv,hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import numpy as np,psutil,torch
from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.training_data import dump_json
from src.phase6.run_detectability import BASE,pinned,eligible_variant,truth_for_variant,breakdowns,canonical_results
from src.phase6.detectability import evaluate_campaigns,FAMILIES
from src.phase6.run_indicator_baseline import LocalAdapter
from src.phase6.run_continuous_inference import replay,pinned_configuration
from src.phase6.input_pipeline import PinnedInputs
from src.phase6.inference_replay import load_stream
from src.phase6.indicator_sharing import Issuer,Recipient,Network,canonical
from src.organization.rolling_graph_v1 import RollingGraph,OrganizationGraphRuntime

FULL=BASE/'full_v1'

def metadata(variant):
    eligible_variant(variant);pinned();rows=load(BASE/'required_val_inventory_v1.json');found=[r for r in rows if r['variant_id']==variant]
    require(len(found)==1,'Variant absent from frozen 171-instance inventory');return found[0]

def new_attempt(parent):
    parent.mkdir(parents=True,exist_ok=True)
    for i in range(1,100000):
        result=parent/f'attempt_{i:05d}'
        try:result.mkdir();return result
        except FileExistsError:continue
    raise ValueError('Too many attempts')

@contextmanager
def exclusive(name):
    folder=FULL/'.locks';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(name+'.lock')
    with path.open('a+b') as f:
        if path.stat().st_size==0:f.write(b'0');f.flush()
        f.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            f.seek(0)
            if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)

def seal(folder,kind):
    require(not (folder/'complete.json').exists(),'Completion is immutable')
    cfg,_=pinned()
    dump_json(folder/'complete.json',dict(status='COMPLETE',kind=kind,method_sha256=sha(ROOT/'configs/phase6/detectability_protocol_v1.json'),
        artifact_sha256={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file() and p.name!='complete.json'}))

def completed(parent,verify=True):
    for folder in sorted(parent.glob('attempt_*')):
        path=folder/'complete.json'
        if not path.exists():continue
        marker=load(path);require(marker['status']=='COMPLETE' and marker['method_sha256']==sha(ROOT/'configs/phase6/detectability_protocol_v1.json'),'Incompatible completion marker')
        if verify:
            for p,h in marker['artifact_sha256'].items():require(sha(folder/p)==h,'Completed artifact changed; do not silently replace: '+str(folder/p))
        return folder
    return None

class BatchAdapter(LocalAdapter):
    """Only generalized initialization. Accepted prepare/finish/close methods unchanged."""
    def __init__(self,org,cfg,directory,component):
        self.organization,self.cfg=org,cfg;self.accepted=load(component/'summary.json')
        require(self.accepted['status'] in ['PASS_FROZEN_LOCAL_REPLAY_COMPONENT','PASS_FRESH_LOCAL_INFERENCE_EXACT_ACCEPTED_BASELINE'],'Invalid sealed local component')
        manifest=load(component/('complete.json' if (component/'complete.json').exists() else 'artifact_sha256.json'))
        hashes=manifest.get('artifact_sha256',manifest)
        for p,h in hashes.items():require(sha(component/p)==h,'Local component changed')
        path=ROOT/self.accepted['local']['private_store'];self.source_hash=sha(path);self.db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro',uri=True)
        require(self.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Local journal corrupt')
        cp=self.db.execute('SELECT graph,sha256 FROM checkpoints WHERE seq=0').fetchone();require(hashlib.sha256(cp[0]).hexdigest()==cp[1],'Warm-up checkpoint mismatch')
        self.runtime=OrganizationGraphRuntime(org,RollingGraph.from_checkpoint_bytes(cp[0]));self.graph_id=id(self.runtime.graph)
        self.iterator=iter(self.db.execute('SELECT seq,asof,payload FROM commands ORDER BY seq'));self.next=next(self.iterator,None)
        self.issuer=Issuer(org,cfg);self.receiver=Recipient(org,cfg)
        self.private=directory/org/'private';self.private.mkdir(parents=True)
        self.decisions=(self.private/'paired_decisions.jsonl').open('x',encoding='utf-8');self.extra=(self.private/'additional_event_decisions.jsonl').open('x',encoding='utf-8')
        self.digest=hashlib.sha256();self.extra_digest=hashlib.sha256()
        self.stats=dict(organization=org,events=0,commands=0,paired_rows=0,local_alerts=0,local_plus_alerts=0,added_alerts=0,no_alerts_local_plus=0,matched_paired_rows=0,additional_event_users=0,additional_indicator_alerts=0,final_ten_minutes_events=0,final_ten_minutes_paired_rows=0)
        self.used=set();self.latency=[];self.frame=None
        self.model_pins=load(ROOT/'reports/phase6/inference/preregistration_v1.json')['registry']['models'][org]
        self.threshold=load(ROOT/self.model_pins['threshold_path'])['calibration']['threshold']

def sharing(components,out,reverse=False):
    start=time.perf_counter();cfg=load(ROOT/'configs/phase6/indicator_sharing_v1.json')
    adapters={o:BatchAdapter(o,cfg,out,components[o]) for o in cfg['organizations']};network=Network(cfg,{o:a.receiver for o,a in adapters.items()});order=list(adapters)
    if reverse:order.reverse()
    ticks=0;rss=[]
    while True:
        clocks=[a.next_time() for a in adapters.values() if a.next_time() is not None];expiry=network.next_expiry()
        if expiry is not None:clocks.append(expiry)
        if not clocks:break
        t=min(clocks);network.advance(t);active=[o for o in order if adapters[o].next_time()==t];payloads=[]
        for o in active:payloads.extend(adapters[o].prepare(t))
        network.publish(payloads,t)
        for o in active:adapters[o].finish(t)
        ticks+=1;rss.append(psutil.Process().memory_info().rss)
        if ticks%500==0:print(json.dumps(dict(event='sharing_progress',ticks=ticks,at=t.isoformat())),flush=True)
    records=[adapters[o].close(out) for o in cfg['organizations']]
    require(len(network.created)==len(network.expired) and sum(r['received'] for r in records)==4*len(network.created),'Incomplete indicator lifecycle')
    with (out/'network_events.jsonl').open('x',encoding='utf-8') as f:
        for r in network.log:f.write(canonical(r)+'\n')
    value=dict(status='PASS_FROZEN_SHARING_COMPONENT',records=records,network_digest=hashlib.sha256(canonical(network.log).encode()).hexdigest(),issued=len(network.created),expired=len(network.expired),elapsed_seconds=time.perf_counter()-start,rss_peak_bytes=max(rss))
    dump_json(out/'summary.json',value);return value

def outcomes(variant,sharing_path,out):
    """Offline truth joins occur only after runtime/sharing completion."""
    row=metadata(variant);specs,evidence,pins=truth_for_variant(row);decisions=[];coverage={}
    for org in ['Org1','Org2','Org3','Org4','Org5']:
        with (sharing_path/org/'private/paired_decisions.jsonl').open(encoding='utf-8') as f:
            for line in f:
                r=json.loads(line)
                for family,flag in [('local_only',r['local_alert']),('local_plus_indicator',r['local_plus_indicator_alert'])]:
                    decisions.append(dict(variant_id=variant,organization=org,user_id=r['user_id'],at=datetime.fromisoformat(r['at']),family=family,alert=flag))
        for family in FAMILIES:coverage[(variant,org,family)]=True
    value=evaluate_campaigns(specs,evidence,decisions,coverage)
    for org in ['Org1','Org2','Org3','Org4','Org5']:
        private=out/org/'private';private.mkdir(parents=True)
        for filename,key in [('target_users.jsonl','private_user_results'),('attribution.jsonl','private_alert_attribution')]:
            with (private/filename).open('x',encoding='utf-8') as f:
                for r in value[key]:
                    if r['organization']==org:f.write(canonical(r)+'\n')
    dump_json(out/'summary.json',dict(status='PASS_CAMPAIGN_INSTANCE',variant_id=variant,campaign_results=value['campaign_results'],organization_results=value['organization_results'],attribution_digest=hashlib.sha256(canonical_results(value).encode()).hexdigest(),truth_source_sha256=pins.checked))
    pins.verify_unchanged();return value

def golden():
    """Representative only: prove generalized bridge exactly matches accepted mechanics."""
    cfg,_=pinned();out=BASE/'engine_representative_v1';require(not out.exists(),'No overwrite');out.mkdir()
    components={o:ROOT/f'reports/phase6/indicator_baseline/local_v1/{o}' for o in ['Org1','Org2','Org3','Org4','Org5']}
    summary=sharing(components,out);old=load(ROOT/'reports/phase6/indicator_baseline/paired_v1/summary.json')
    require(summary['network_digest']==old['network_digest'],'Generalized bridge changed network decisions')
    for r,previous in zip(summary['records'],old['records']):
        for k in previous:
            if k!='sharing_adapter_seconds':require(r[k]==previous[k],'Bridge equivalence failure: '+k)
    evaluation=BASE/'engine_evaluation_v1';require(not evaluation.exists(),'No overwrite');evaluation.mkdir();result=outcomes(cfg['predetermined_representative'],out,evaluation)
    digest=hashlib.sha256(canonical_results(result).encode()).hexdigest();require(digest==load(BASE/'representative_v1/summary.json')['campaign_attribution_digest'],'Campaign attribution differs after execution generalization')
    dump_json(out/'equivalence.json',dict(status='PASS_EXACT_GENERALIZED_BRIDGE_AND_CAMPAIGN_ATTRIBUTION',network_digest=summary['network_digest'],campaign_attribution_digest=digest,source_sha256=sha(Path(__file__)),full_run_launched=False))
    seal(out,'representative_engine_only');seal(evaluation,'representative_evaluator_only')
    print(json.dumps(dict(status='PASS_ENGINE_REPRESENTATIVE_EQUIVALENCE',seconds=summary['elapsed_seconds'],full_run_launched=False)),flush=True)

def plan():
    cfg,p=pinned();pilot=load(BASE/'representative_v1/summary.json');engine=load(BASE/'engine_representative_v1/equivalence.json');require(engine['source_sha256']==sha(Path(__file__)),'Engine changed after representative verification')
    rows=load(BASE/'required_val_inventory_v1.json');seconds=[];sizes=[];rss=[]
    for o in ['Org1','Org2','Org3','Org4','Org5']:
        folder=ROOT/f'reports/phase6/indicator_baseline/local_v1/{o}';r=load(folder/'summary.json')['local'];seconds.append(r['resources']['elapsed_seconds']);rss.append(r['resources']['observed_rss_peak_bytes']);sizes.append(sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()))
    value=dict(status='READY_FOR_REVIEW_NOT_LAUNCHED',required_instances=171,reused_verified_instances=1,remaining_fresh_instances=170,full_sweep_authorized=False,
        method_sha256=p['configuration_sha256'],engine_source_sha256=sha(Path(__file__)),engine_test_sha256=sha(ROOT/'tests/phase6/test_detectability_batch.py'),
        inventory_sha256=sha(BASE/'required_val_inventory_v1.json'),instance_order=[r['variant_id'] for r in rows],
        execution='One instance at a time, five organization-local subprocesses, two CPU Torch threads each. Original sealed models/thresholds/runtime/sampler and immediate indicator policy; reverse-order sharing repeat per instance; offline truth only afterward.',
        recovery='OS-released per-instance/per-worker advisory locks; independent attempt directories; never overwrite incomplete/failed attempts. Reuse only hash-verified complete org/sharing/evaluation components; failures remain pending. Resume same command, skip completed components; tampered completed artifacts fail closed.',
        optimizations={'enabled':'Reuse exact-verified representative completion and accepted immutable model/decision artifacts. No approximation or changed scoring.','proposed_disabled':'Persistent worker/model and clean background checkpoint caching; would require whole-trace score/threshold/alert/view/graph and campaign-attribution equivalence. No unvalidated caching or incremental graph export enabled.'},
        estimates=dict(reference_parallel_instance_seconds=max(seconds),remaining_model_reference_hours=170*max(seconds)/3600,
            caveat='Extrapolation from one accepted VAL instance, excluding startup variation, different event/node counts, sharing repeats, IO and offline evaluation. Not a 77-hour guarantee.',
            observed_five_worker_rss_sum_bytes=sum(rss),recommended_ram_bytes=8*1024**3,torch_cpu_threads_total=10,
            observed_local_artifact_bytes_per_instance=sum(sizes),remaining_local_artifact_reference_bytes=170*sum(sizes),disk_margin_recommendation='Allow at least 25% above estimated local journal size plus sharing/evaluator logs; existing frozen data already on disk.'),
        commands={'status':'.venv/Scripts/python.exe -B -m src.phase6.detectability_batch --status',
            'full_after_review':'.venv/Scripts/python.exe -B -m src.phase6.detectability_batch --run-all --review-approved',
            'single_after_review':'.venv/Scripts/python.exe -B -m src.phase6.detectability_batch --run-instance VARIANT_ID_VAL --review-approved'},
        test_used=False,subphase8_status='IN_PROGRESS')
    destination=BASE/'execution_plan_v1.json';require(not destination.exists(),'Execution plan is append-only');dump_json(destination,value);print(json.dumps(dict(status=value['status'],remaining=170,estimated_model_hours=value['estimates']['remaining_model_reference_hours'])),flush=True)

def authorize(review):
    require(review,'Full execution is review-gated; --review-approved requires explicit post-pilot user review')
    cfg,p=pinned();value=load(BASE/'execution_plan_v1.json')
    require(value['engine_source_sha256']==sha(Path(__file__)) and value['engine_test_sha256']==sha(ROOT/'tests/phase6/test_detectability_batch.py') and value['method_sha256']==p['configuration_sha256'],'Reviewed execution source/method changed')
    local,registry=pinned_configuration()
    for path,h in registry['registry']['shared_sha256'].items():require(sha(ROOT/path)==h,'Accepted shared runtime/config changed')
    for model in registry['registry']['models'].values():
        require(sha(ROOT/model['model_path'])==model['model_sha256'] and sha(ROOT/model['threshold_path'])==model['threshold_sha256'],'Accepted model/threshold changed')
    for path,h in load(ROOT/'reports/phase6/indicator_baseline/preregistration_v1.json')['source_sha256'].items():require(sha(ROOT/path)==h,'Accepted indicator implementation changed')
    return value

def worker(variant,org,attempt):
    row=metadata(variant);require(org in ['Org1','Org2','Org3','Org4','Org5'],'Invalid organization')
    require(attempt.resolve().is_relative_to((FULL/'instances'/variant/'local'/org).resolve()),'Worker output outside isolated instance')
    with exclusive(variant+'_'+org):
        local,registry=pinned_configuration();torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
        pins=PinnedInputs(ROOT);graph,schedule,source=load_stream(pins,variant,org);blob=graph.checkpoint_bytes();del graph
        result=replay(org,'detectability_full_reference',blob,schedule,source,attempt/'uninterrupted',local,registry['registry'],False)
        require(not any(x.endswith('_labels.parquet') or x.endswith('_replay.parquet') or '_TEST/' in x for x in pins.checked),'Runtime accessed offline truth/TEST')
        pins.verify_unchanged();pinned()
        dump_json(attempt/'summary.json',dict(status='PASS_FROZEN_LOCAL_REPLAY_COMPONENT',organization=org,source=source,local=result,input_sha256=pins.checked))
        seal(attempt,'local_runtime')

def run_instance(variant):
    cfg,_=pinned();metadata(variant)
    with exclusive(variant):
        instance=FULL/'instances'/variant;existing=completed(instance/'evaluation')
        if existing:return load(existing/'summary.json')
        if variant==cfg['predetermined_representative']:
            pilot=load(BASE/'representative_v1/summary.json')
            for p,h in load(BASE/'representative_v1/artifact_sha256.json').items():require(sha(BASE/'representative_v1'/p)==h,'Verified pilot artifact changed')
            out=new_attempt(instance/'evaluation');dump_json(out/'summary.json',dict(status='PASS_CAMPAIGN_INSTANCE',variant_id=variant,campaign_results=pilot['campaign_results'],organization_results=pilot['organization_results'],attribution_digest=pilot['campaign_attribution_digest'],reused_representative_manifest_sha256=sha(BASE/'representative_v1/artifact_sha256.json')));seal(out,'verified_representative_reuse');return load(out/'summary.json')
        components={};processes=[];logs=[]
        try:
            for org in ['Org1','Org2','Org3','Org4','Org5']:
                parent=instance/'local'/org;valid=completed(parent)
                if valid:components[org]=valid;continue
                attempt=new_attempt(parent);private=attempt/'private';private.mkdir();log=(private/'worker_stdout.log').open('xb');logs.append(log)
                args=[sys.executable,'-B','-m','src.phase6.detectability_batch','--worker-org',org,'--variant',variant,'--attempt',str(attempt),'--review-approved']
                processes.append((org,attempt,subprocess.Popen(args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)))
            next_report=0.
            while any(p.poll() is None for _,_,p in processes):
                if time.monotonic()>=next_report:
                    print(json.dumps(dict(event='instance_progress',variant_id=variant,active_organizations=[o for o,a,p in processes if p.poll() is None])),flush=True);next_report=time.monotonic()+30
                time.sleep(1)
            for org,attempt,p in processes:require(p.returncode==0 and completed(attempt.parent)==attempt,'Worker failed; partial attempt preserved: '+str(attempt));components[org]=attempt
        finally:
            for _,_,p in processes:
                if p.poll() is None:
                    p.terminate()
                    try:p.wait(timeout=30)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
            for log in logs:log.close()
        paths=[]
        for name,reverse in [('sharing',False),('reverse_sharing',True)]:
            parent=instance/name;valid=completed(parent)
            if not valid:valid=new_attempt(parent);sharing(components,valid,reverse);seal(valid,name)
            paths.append(valid)
        a,b=[load(p/'summary.json') for p in paths];require(a['network_digest']==b['network_digest'],'Sharing order mismatch')
        for x,y in zip(a['records'],b['records']):
            for k in ['paired_decision_digest','additional_decision_digest','final_graph_sha256']:require(x[k]==y[k],'Sharing reproducibility failure')
        out=new_attempt(instance/'evaluation');outcomes(variant,paths[0],out);seal(out,'offline_evaluation')
        return load(out/'summary.json')

def status():
    rows=load(BASE/'required_val_inventory_v1.json');done=[r['variant_id'] for r in rows if completed(FULL/'instances'/r['variant_id']/'evaluation',verify=False)]
    print(json.dumps(dict(status='IN_PROGRESS' if len(done)<171 else 'COMPLETION_MARKERS_PRESENT_VALIDATION_REQUIRED',required=171,completed_markers=len(done),pending=171-len(done),separately_verified_pilot_instances=1 if (BASE/'representative_v1/summary.json').exists() else 0,full_run_directory_exists=FULL.exists(),note='Quick status; resume/finalization verifies every completed artifact hash.')),flush=True)

def run_all():
    rows=load(BASE/'required_val_inventory_v1.json');campaigns=[];organizations=[];FULL.mkdir(parents=True,exist_ok=True)
    progress=FULL/'progress.jsonl'
    for row in rows:
        try:
            result=run_instance(row['variant_id']);campaigns.extend(result['campaign_results']);organizations.extend(result['organization_results'])
            event=dict(event='instance_complete',variant_id=row['variant_id'],completed_instances=len(campaigns)//2,required_instances=171)
        except BaseException as error:
            with progress.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(event='instance_failure_or_interrupt',variant_id=row['variant_id'],error_type=type(error).__name__,required_instances=171))+'\n')
            raise
        with progress.open('a',encoding='utf-8') as f:f.write(json.dumps(event)+'\n')
        print(json.dumps(event),flush=True)
    require(len(campaigns)==342 and all(r['evaluable'] for r in campaigns),'Full coverage is incomplete/not evaluable')
    old=load(BASE/'accepted_inputs_before_subphase8_v1.json')
    for path,h in old.items():require(sha(ROOT/path)==h,'Prior accepted artifact changed: '+path)
    if completed(FULL/'validated_171'):
        print(json.dumps(dict(status='REUSED_HASH_VERIFIED_171_VALIDATION',evaluated=171)),flush=True);return
    out=new_attempt(FULL/'validated_171');value=dict(status='PASS_ALL_171_VAL_INSTANCES_TECHNICAL_REVIEW_REQUIRED',campaign_results=campaigns,organization_results=organizations,factor_seed_results=breakdowns({'campaign_results':campaigns},rows),required=171,evaluated=171,test_used=False,subphase9_started=False,prior_files_preserved=len(old))
    dump_json(out/'summary.json',value);seal(out,'full_171_validation');print(json.dumps(dict(status=value['status'],required=171,evaluated=171)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify-representative-engine',action='store_true');p.add_argument('--prepare-plan',action='store_true');p.add_argument('--status',action='store_true');p.add_argument('--run-all',action='store_true');p.add_argument('--run-instance');p.add_argument('--review-approved',action='store_true');p.add_argument('--worker-org');p.add_argument('--variant');p.add_argument('--attempt');a=p.parse_args()
    if a.verify_representative_engine:golden()
    elif a.prepare_plan:plan()
    elif a.status:status()
    elif a.worker_org:authorize(a.review_approved);worker(a.variant,a.worker_org,Path(a.attempt))
    elif a.run_instance:authorize(a.review_approved);run_instance(a.run_instance)
    elif a.run_all:authorize(a.review_approved);run_all()
