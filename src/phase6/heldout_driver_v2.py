"""Complete evaluation-only driver; actual data/weight access is gated first.

No execution approval is generated here. CLI execution remains blocked until a
separate explicit reviewed approval binds sources/config/catalog/physical scope.
"""
from dataclasses import asdict
from datetime import datetime,timedelta
import csv,hashlib,json,math,os,time
from contextlib import contextmanager
from pathlib import Path
from src.phase6.heldout_contract_v2 import ROOT,ORGS,Scope,Catalog,Branch,canonical,digest,file_hash
from src.phase6.heldout_grid_v2 import EvaluationContext,score_grid,eligible_predictions
from src.phase6.heldout_barrier_v2 import Barrier,Journal,write_once
from src.phase6.temporal_protocol import require

REGISTER='reports/phase5_final_acceptance_v2/campaign_register_v2.csv'
REGISTER_SHA256='d9e2b1a63308e00da05b5dac2afd83f27b259c006e69044f593130db0cc0aaef'

@contextmanager
def run_lease(directory):
    """OS-released single-run lease; no stale-lock deletion on recovery."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    handle=(directory/'execution.lock').open('a+b')
    if handle.tell()==0:handle.write(b'\n');handle.flush()
    handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close();raise ValueError('Another evaluation process owns this run')
    try:yield
    finally:
        handle.seek(0)
        if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(handle,fcntl.LOCK_UN)
        handle.close()

def normalize_frame(frame):
    return dict(observations=[dict(r,**{'Login Timestamp':r['Login Timestamp'].isoformat()}) for r in frame['observations']],
                tokens=frame['tokens'],heartbeat=frame['heartbeat'],final=frame['final'])

class LocalPort:
    """Private original local service. Recovery reads its committed SQLite rows."""
    def __init__(self,branch,service,tabular):
        self.branch,self.organization,self.service,self.tabular=branch,branch.organization,service,tabular
    def frame_identity(self,t,frame):return digest(dict(at=t.isoformat(),frame=normalize_frame(frame),branch=self.branch.identity))
    def attest(self,context):
        s=self.service;b=context.branch
        require(self.branch==b and s.organization==b.organization and s.stream_id==b.variant and s.split=='TEST','Foreign local view producer')
        source=json.loads(s.db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])['source_identity']
        require(source['variant_id']==b.variant and source['organization']==b.organization and source['anchor']==b.anchor and
                source['end_exclusive']==b.end and source['observations_sha256']==b.observations_sha256 and
                source['history_reference_sha256']==b.history_sha256 and id(s.runtime.graph)==s.graph_object_id,'Local graph source identity changed')
    def ensure_local(self,t,frame):
        s=self.service;at=t.isoformat();expected=normalize_frame(frame)
        committed=s.db.execute('SELECT seq,payload FROM commands WHERE asof=?',(at,)).fetchall()
        require(len(committed)<=1,'Duplicate local commit')
        if committed:
            seq,payload=committed[0];require(json.loads(payload)==expected,'Changed committed command')
        else:
            if frame['observations']:s.process_batch(t,frame['observations'],frame['tokens'],heartbeat=frame['heartbeat'],final=frame['final'])
            else:s.tick(t,final=frame['final'])
            seq=s.seq
        require(s.runtime.graph.clock==t,'Recovery needs latest committed graph at this barrier')
        cols=['user_id','logit_hex','threshold_hex','decision','alert_id','model_sha256','threshold_sha256']
        scores=[dict(zip(cols,r)) for r in s.db.execute('SELECT '+','.join(cols)+' FROM scores WHERE seq=? ORDER BY user_id',(seq,))]
        for r in scores:
            require(r['model_sha256']==s.bundle.identity['model_sha256'] and r['threshold_sha256']==s.bundle.identity['threshold_sha256'] and
                    r['threshold_hex']==s.bundle.threshold['hex'] and r['decision']==('ALERT' if r['threshold_hex'] is not None and float.fromhex(r['logit_hex'])>=float.fromhex(r['threshold_hex']) else 'NO_ALERT'),'Unsealed local commit')
        current={}
        for r in frame['observations']:current.setdefault(str(r['User ID']),set()).add(r['IP Address'])
        return dict(at=at,seq=seq,scores=scores,recent=[[e.time.isoformat(),e.user,e.ip] for e in s.runtime.graph.recent_events],
            current={u:sorted(ips) for u,ips in current.items()},provenance=dict(branch=self.branch.identity,bundle=s.bundle.identity,view_digest=s.runtime.graph.view().digest()))
    def view(self,t):
        require(self.service.runtime.graph.clock==t,'Grid graph clock mismatch');return self.service.runtime.detection_view()
    def bundle(self,detector):return self.service.bundle if detector=='graphsage' else self.tabular
    def resource_summary(self):
        import numpy as np
        rows=[json.loads(r[0]) for r in self.service.db.execute('SELECT timings FROM commands ORDER BY seq')]
        result=dict(kind='accepted_original_local_service',commands=len(rows),input_events=sum(r['input_events'] for r in rows),scored_users=sum(r['scored_users'] for r in rows))
        for field in ('precommit_processing_seconds','model_scoring_seconds','graph_update_seconds','feature_and_sampler_seconds'):
            values=[r[field] for r in rows]
            result[field]=dict(mean=float(np.mean(values)),p50=float(np.quantile(values,.5)),p95=float(np.quantile(values,.95)),p99=float(np.quantile(values,.99)),maximum=max(values)) if values else None
        result['limitation']='Command precommit latency excludes final SQLite commit; model seconds exclude feature construction. No event-driven FPR guarantee.'
        return result
    def close(self):self.service.close()

class ProductionBackend:
    def __init__(self,scope):
        scope.assert_ready()
        require(type(scope) is Scope and not scope.synthetic_only and scope.root==ROOT and not scope.catalog.fixture_only,'Production backend rejects fixture/unverified capability')
        self.scope=scope
    def _production_only(self):
        require(type(self.scope) is Scope and not self.scope.synthetic_only and self.scope.root==ROOT and not self.scope.catalog.fixture_only,'Production reader rejects fixture/unverified capability')
    def inventory(self):
        self.scope.assert_ready();self._production_only();require(file_hash(ROOT/REGISTER)==REGISTER_SHA256,'Frozen register changed')
        with (ROOT/REGISTER).open(newline='',encoding='utf-8-sig') as f:
            rows=[r for r in csv.DictReader(f) if r['split']=='TEST']
        require(len(rows)==171 and len({r['variant_id'] for r in rows})==171,'Incomplete frozen TEST inventory')
        require({int(r['seed']) for r in rows}=={1001,1002,1003},'Missing frozen seeds')
        require(all(sum(int(r['seed'])==seed for r in rows)==57 for seed in (1001,1002,1003)),'Expected 57 original configurations per seed')
        return sorted(rows,key=lambda r:r['variant_id'])
    def verify_register_row(self,row):
        require(any(row==r for r in self.inventory()),'Instance is not an exact frozen register row')
    def prepare(self,row,directory):
        self.scope.assert_ready()
        self._production_only()
        from src.phase6.input_pipeline import PinnedInputs
        from src.phase6.readiness import REPLAY
        from src.phase6.heldout_replay_v1 import load_stream
        from src.phase6.heldout_local_inference_v1 import HeldOutLocalInference
        from src.phase6.heldout_tabular_bundle_v1 import HeldOutTabularBundle
        from src.phase6.inference_registry import LocalModelRegistry
        import torch
        # Match the accepted inference configuration. Verify every original
        # model/threshold BEFORE opening the first TEST campaign manifest or
        # observation file. This path is never invoked during remediation.
        torch.set_num_threads(json.loads(self.scope.catalog.inference_config_json)['torch_threads'])
        registry=json.loads((ROOT/'reports/phase6/inference/preregistration_v1.json').read_bytes())['registry']
        registries={o:LocalModelRegistry(ROOT,o,registry) for o in ORGS}
        tabular_models={o:HeldOutTabularBundle(o) for o in ORGS}
        for o in ORGS:
            self.scope.catalog.seal(o,'graphsage').validate(registries[o].current)
            self.scope.catalog.seal(o,'tabular_mlp').validate(tabular_models[o])
        self.pins=PinnedInputs(ROOT);variant=row['variant_id'];self.scope.check_variant(variant,'Org1')
        manifest_path=self.pins.check(ROOT/REPLAY/variant/'replay_manifest.json');m=json.loads(manifest_path.read_bytes())
        require(m['split']=='TEST' and m['variant_id']==variant and m['anchor']==row['campaign_start'] and
                m['end_exclusive']==row['campaign_end_exclusive'] and m['targeted_organizations']==row['targeted_organizations'].split('|') and
                set(m['replayed_organizations'])==set(ORGS) and int(m['seed'])==int(row['seed']),'Register/manifest mismatch')
        ports={};schedules={};contexts={}
        try:
            for org in ORGS:
                graph,schedule,identity=load_stream(self.pins,variant,org,split='TEST',scope=self.scope)
                branch=Branch(variant,org,m['anchor'],m['end_exclusive'],file_hash(manifest_path),identity['observations_sha256'],identity['history_reference_sha256'])
                context=EvaluationContext.bind(self.scope.catalog,branch)
                local=HeldOutLocalInference(directory/org/'private/local.sqlite',org,variant,registries[org],
                    json.loads(self.scope.catalog.inference_config_json),initial_graph=graph,source_identity=identity,scope=self.scope)
                tabular=tabular_models[org];context.tabular_seal.validate(tabular)
                ports[org]=LocalPort(branch,local,tabular);schedules[org]=dict(schedule);contexts[org]=context
        except Exception:
            for p in ports.values():p.close()
            raise
        return ports,schedules,contexts
    def labels(self,context,at,seal):
        self.scope.assert_ready();self._production_only();require(seal['status']=='SCORES_SEALED_BEFORE_LABELS','Unsealed label access')
        from src.phase6.input_pipeline import PinnedInputs
        from src.phase6.readiness import REPLAY
        from src.phase6.heldout_evaluation_v1 import load_grid_labels
        pins=PinnedInputs(ROOT);b=context.branch
        # Pin against the frozen branch manifest again; no model is loaded.
        mpath=pins.check(ROOT/REPLAY/b.variant/'replay_manifest.json');require(file_hash(mpath)==b.manifest_sha256,'Offline manifest changed')
        m=json.loads(mpath.read_bytes());branch=next(v for v in m['branches'] if v['organization']==b.organization)
        # Read all grid label rows including masks so the v2 join validates each.
        path=self.scope.check_input(ROOT/REPLAY/b.variant/f'{b.organization}_labels.parquet',b.variant,b.organization,labels=True)
        path=pins.check(path);require(file_hash(path)==branch['labels_parquet_sha256'],'Label source changed')
        import duckdb
        db=duckdb.connect(':memory:')
        try:
            q=db.execute('SELECT * FROM read_parquet(?) WHERE label_time=? AND contains(query_kind,\'grid_snapshot\') ORDER BY "User ID"',[str(path),at])
            cols=[c[0] for c in q.description];return [dict(zip(cols,r)) for r in q.fetchall()]
        finally:db.close()
    def truth(self,row,contexts,seal):
        self.scope.assert_ready();self._production_only();require(seal['status']=='SCORES_SEALED_BEFORE_LABELS','Unsealed truth access')
        from src.phase6.input_pipeline import PinnedInputs
        from src.phase6.readiness import REPLAY
        pins=PinnedInputs(ROOT);variant=row['variant_id'];folder=ROOT/REPLAY/variant
        path=pins.check(folder/'replay_manifest.json');require(file_hash(path)==contexts['Org1'].branch.manifest_sha256,'Truth manifest changed')
        m=json.loads(path.read_bytes());events=[];ids=set()
        import duckdb
        db=duckdb.connect(':memory:')
        try:
            for branch in m['branches']:
                org=branch['organization'];p=pins.check(folder/f'{org}_replay.parquet')
                require(file_hash(p)==branch['replay_parquet_sha256'],'Offline truth source changed')
                rows=db.execute('SELECT CAST("User ID" AS BIGINT),CAST("Login Timestamp" AS TIMESTAMP),CAST(campaign_id AS VARCHAR) FROM read_parquet(?) WHERE organization=? AND is_synthetic=true AND credential_stuffing_label=1 ORDER BY 2,1,3',[str(p),org]).fetchall()
                require(len(rows)==branch['synthetic_events'] and len({u for u,t,c in rows})==branch['targeted_users'],'Exposure census mismatch')
                require(bool(rows)==(org in row['targeted_organizations'].split('|')),'Targeted organization mismatch')
                for u,t,c in rows:
                    require(c is not None,'Missing campaign identity');ids.add(c);events.append(dict(variant_id=variant,campaign_id=c,organization=org,user_id=int(u),at=t))
        finally:db.close()
        require(len(ids)==1,'Expected one campaign per accepted branch')
        spec=dict(variant_id=variant,campaign_id=next(iter(ids)),start=datetime.fromisoformat(row['campaign_start']),end=datetime.fromisoformat(row['campaign_end_exclusive']),targeted_organizations=row['targeted_organizations'].split('|'),seed=int(row['seed']),factors={k:row[k] for k in ('family','RIP_target','Raccount_target','Sorg_target','RIP_actual','Raccount_actual','Sorg_actual')})
        return [spec],events

def metrics(rows):
    from src.phase6.local_graphsage import classification_metrics
    import numpy as np
    y=np.asarray([r['node_label'] for r in rows],dtype=np.int64);z=np.asarray([float.fromhex(r['logit_hex']) for r in rows],dtype=np.float64)
    value=classification_metrics(y,z,np.ones(len(rows),dtype=bool))
    tp=sum(r['alert'] and r['node_label']==1 for r in rows);fp=sum(r['alert'] and r['node_label']==0 for r in rows)
    positives=sum(r['node_label']==1 for r in rows);negatives=len(rows)-positives
    value.update(tp=tp,fp=fp,fn=positives-tp,tn=negatives-fp,
        recall=tp/positives if positives else None,precision=tp/(tp+fp) if tp+fp else None,
        fpr=fp/negatives if negatives else None,f1=2*tp/(2*tp+fp+positives-tp) if 2*tp+fp+positives-tp else None)
    return value

def independently_reconcile(rows,reported):
    """Separate simple oracle: never calls metrics/classification_metrics."""
    counts=dict(tp=0,fp=0,fn=0,tn=0);seen=set()
    for r in rows:
        key=(r['organization'],r['variant_id'],r['asof'],r['user_id'],r['detector'])
        require(key not in seen,'Duplicate eligible evaluation unit');seen.add(key)
        z=float.fromhex(r['logit_hex']);threshold=r['threshold']
        expected=False if threshold['kind']!='finite' else z>=float.fromhex(threshold['hex'])
        require(expected==r['alert'],'Independent binary64 mismatch')
        counts['tp' if expected and r['node_label']==1 else 'fp' if expected else 'fn' if r['node_label']==1 else 'tn']+=1
    require(all(reported[k]==v for k,v in counts.items()),'Independent confusion-count mismatch')
    tp,fp,fn,tn=(counts[k] for k in ('tp','fp','fn','tn'))
    for key,num,den in [('recall',tp,tp+fn),('precision',tp,tp+fp),('fpr',fp,fp+tn),('f1',2*tp,2*tp+fp+fn)]:
        expected=num/den if den else None;require(reported[key]==expected,'Independent metric mismatch: '+key)
    ordered=sorted(rows,key=lambda r:-float.fromhex(r['logit_hex']));total=sum(r['node_label'] for r in rows)
    cumulative=0;ap=0.;i=0
    while i<len(ordered):
        j=i+1
        while j<len(ordered) and float.fromhex(ordered[j]['logit_hex'])==float.fromhex(ordered[i]['logit_hex']):j+=1
        new=sum(r['node_label'] for r in ordered[i:j]);cumulative+=new
        ap+=new*cumulative/j;i=j
    expected=ap/total if total else None
    require((expected is None and reported['average_precision'] is None) or
            (expected is not None and abs(expected-reported['average_precision'])<1e-12),'Independent AP mismatch')
    return counts

class Driver:
    def __init__(self,scope,backend):
        scope.assert_ready()
        require(type(scope) is Scope,'Unverified scope implementation')
        require(scope.synthetic_only or type(backend) is ProductionBackend,'Production requires verified frozen-register backend')
        self.scope,self.backend=scope,backend
    def _verify_files(self,root,files):
        for relative,h in files.items():
            p=(root/relative).resolve();require(p.is_relative_to(root.resolve()) and file_hash(p)==h,'Sealed output missing/changed')
    def run_instance(self,row,fail=lambda stage:None):
        self.scope.assert_ready()
        with run_lease(self.scope.output_root):return self._run_instance(row,fail)
    def _run_instance(self,row,fail=lambda stage:None):
        self.scope.assert_ready();variant=row['variant_id'];self.scope.check_variant(variant,'Org1')
        if not self.scope.synthetic_only:self.backend.verify_register_row(row)
        root=self.scope.output_root/variant;self.scope.check_output(root);root.mkdir(parents=True,exist_ok=True)
        identity=dict(version='heldout-instance-v2',adapter=self.scope.adapter_identity,catalog=self.scope.catalog.identity,register_row_sha256=digest(row),variant=variant)
        write_once(root/'identity.json',identity)
        if (root/'completion.json').exists():
            completed=json.loads((root/'completion.json').read_bytes());self._verify_files(root,completed['files_sha256'])
            require(completed['status']=='COMPLETE_VALIDATED' and completed['identity']==identity,'Invalid completion manifest')
            return json.loads((root/'public_results.json').read_bytes())
        start=time.perf_counter();cpu=time.process_time();ports={};contexts={};schedules={}
        try:
            if not (root/'score_seal.json').exists():
                ports,schedules,contexts=self.backend.prepare(row,root)
                require(set(ports)==set(schedules)==set(contexts)==set(ORGS),'Missing organization')
                require(all(contexts[o].branch==ports[o].branch for o in ORGS),'Context/port branch mismatch')
                write_once(root/'bindings.json',{o:asdict(contexts[o].branch) for o in ORGS})
                coordinator=Barrier(self.scope,ports,root/'sharing')
                grid_journals={o:Journal(root/o/'private/grid_progress',dict(context=contexts[o].identity,adapter=self.scope.adapter_identity)) for o in ORGS}
                times=sorted({t for schedule in schedules.values() for t in schedule})
                for o in ORGS:
                    b=contexts[o].branch;require(all(b.start<=t<b.stop for t in schedules[o]),'Out-of-hour schedule')
                    require(all(t in schedules[o] and schedules[o][t]['heartbeat'] for t in b.grid),'Missing primary heartbeat')
                    last=b.stop-timedelta(microseconds=1)
                    require(last in schedules[o] and schedules[o][last]['final'],'Missing final-ten-minute flush')
                for t in times:
                    commands={o:schedules[o][t] for o in ORGS if t in schedules[o]}
                    coordinator.process(t,commands,fail)
                    for o in ORGS:
                        context=contexts[o]
                        if t not in context.branch.grid:continue
                        for detector in ('graphsage','tabular_mlp'):
                            journal=grid_journals[o];record=journal.get('GRID_COMMIT',t.isoformat(),key=detector)
                            if record:raw=record['raw']
                            else:
                                bound=context.capture(self.scope,ports[o],t)
                                raw=score_grid(self.scope,context,bound,ports[o].bundle(detector),detector)
                                journal.append(dict(event='GRID_COMMIT',at=t.isoformat(),key=detector,raw=raw))
                                fail('after_grid_commit:'+o+':'+detector)
                            write_once(root/o/'private'/f'grid_{t.minute:02d}_{detector}.json',raw)
                            fail('after_grid_file:'+o+':'+detector)
                refs={};raw_digests=[]
                for o,context in contexts.items():
                    resource_path=root/o/'private/local_resource_summary.json';write_once(resource_path,ports[o].resource_summary())
                    refs[resource_path.relative_to(root).as_posix()]=file_hash(resource_path)
                    for t in context.branch.grid:
                        for detector in ('graphsage','tabular_mlp'):
                            p=root/o/'private'/f'grid_{t.minute:02d}_{detector}.json';raw=json.loads(p.read_bytes())
                            require(raw['context_identity']==context.identity and raw['asof']==t.isoformat(),'Grid census mismatch')
                            refs[p.relative_to(root).as_posix()]=file_hash(p);raw_digests.append(digest(raw))
                for record in coordinator.journal.records:
                    body=record['body']
                    if 'path' in body:refs['sharing/'+body['path']]=body['sha256']
                for journal in [coordinator.journal,*grid_journals.values()]:
                    for index in range(journal.index+1):
                        p=journal.root/f'barriers.{index:06d}.jsonl'
                        if p.exists():refs[p.relative_to(root).as_posix()]=file_hash(p)
                refs['bindings.json']=file_hash(root/'bindings.json')
                complete=[r['body']['at'] for r in coordinator.journal.records if r['body']['event']=='COMPLETE']
                require(complete==[t.isoformat() for t in times],'Operational coverage incomplete')
                seal=dict(status='SCORES_SEALED_BEFORE_LABELS',identity=identity,files_sha256=refs,raw_score_digests=raw_digests,
                    branches={o:c.branch.identity for o,c in contexts.items()},completed_barriers=complete,
                    journal_chain_sha256=coordinator.journal.last,catalog_identity=self.scope.catalog.identity)
                write_once(root/'score_seal.json',seal);fail('after_score_seal')
            else:
                bindings=json.loads((root/'bindings.json').read_bytes())
                contexts={o:EvaluationContext.bind(self.scope.catalog,Branch(**b)) for o,b in bindings.items()}
                require(set(contexts)==set(ORGS),'Incomplete sealed bindings')
            seal=json.loads((root/'score_seal.json').read_bytes());require(seal['identity']==identity,'Score seal identity mismatch')
            self._verify_files(root,seal['files_sha256'])
            sharing_proof=independent_sharing_reconciliation(root,seal,self.scope.catalog.policy,contexts)
            eligible={o:{d:[] for d in ('graphsage','tabular_mlp')} for o in ORGS}
            for o,context in contexts.items():
                for t in context.branch.grid:
                    labels=self.backend.labels(context,t,seal)
                    for detector in ('graphsage','tabular_mlp'):
                        raw=json.loads((root/o/'private'/f'grid_{t.minute:02d}_{detector}.json').read_bytes())
                        eligible[o][detector].extend(eligible_predictions(self.scope,context,raw,labels,seal))
                require([(r['asof'],r['user_id'],r['node_label']) for r in eligible[o]['graphsage']]==[(r['asof'],r['user_id'],r['node_label']) for r in eligible[o]['tabular_mlp']],'Unfair detector cohort')
                for detector,rows in eligible[o].items():write_once(root/o/'private'/f'eligible_{detector}.json',rows)
            fail('after_labels')
            specs,evidence=self.backend.truth(row,contexts,seal)
            decisions=[]
            for relative in seal['files_sha256']:
                if not relative.startswith('sharing/') or '/private/' not in relative:continue
                value=json.loads((root/relative).read_bytes())
                if 'paired' not in value:continue
                for r in value['paired']:
                    for family,key in [('local_only','local_alert'),('local_plus_indicator','local_plus_indicator_alert')]:
                        decisions.append(dict(variant_id=variant,organization=value['organization'],user_id=r['user_id'],at=datetime.fromisoformat(value['at']),family=family,alert=r[key]))
                for r in value['additional_event_users']:
                    decisions.append(dict(variant_id=variant,organization=value['organization'],user_id=r['user_id'],at=datetime.fromisoformat(value['at']),family='local_plus_indicator',alert=r['local_plus_indicator_alert']))
            coverage={(variant,o,f):True for o in ORGS for f in ('local_only','local_plus_indicator')}
            from src.phase6.detectability import evaluate_campaigns
            campaign=evaluate_campaigns(specs,evidence,decisions,coverage)
            # Separate attribution oracle does not call the accepted evaluator.
            independent_campaign_reconciliation(specs,evidence,decisions,campaign)
            per_org={o:{d:metrics(rows) for d,rows in detectors.items()} for o,detectors in eligible.items()}
            for o,detectors in eligible.items():
                for d,rows in detectors.items():independently_reconcile(rows,per_org[o][d])
            for o in ORGS:
                write_once(root/o/'private/campaign_user_results.json',[r for r in campaign['private_user_results'] if r['organization']==o])
                write_once(root/o/'private/alert_attribution.json',[r for r in campaign['private_alert_attribution'] if r['organization']==o])
            memory=__import__('psutil').Process().memory_info()
            public=dict(status='PASS_SYNTHETIC_INSTANCE' if self.scope.synthetic_only else 'PASS_HELD_OUT_INSTANCE',variant_id=variant,
                fixed_grid=per_org,campaign_results=campaign['campaign_results'],organization_results=campaign['organization_results'],
                operational_decision_rows=len(decisions),score_seal_sha256=file_hash(root/'score_seal.json'),
                independent_sharing=sharing_proof,
                local_resources={o:json.loads((root/o/'private/local_resource_summary.json').read_bytes()) for o in ORGS},
                resources=dict(attempt_elapsed_seconds=time.perf_counter()-start,attempt_cpu_seconds=time.process_time()-cpu,
                    peak_rss_bytes=getattr(memory,'peak_wset',memory.rss)),
                limitations=['Fixed-grid VAL 1% target does not imply TEST/event FPR','Logical shared-Parquet row filtering is not physical byte isolation','Prior unauthorized hash access remains disclosed'])
            if (root/'public_results.json').exists():
                prior=json.loads((root/'public_results.json').read_bytes())
                require({k:v for k,v in prior.items() if k!='resources'}=={k:v for k,v in public.items() if k!='resources'},'Changed recovered evaluation result')
                public=prior # retain the original measured successful attempt
            write_once(root/'public_results.json',public);fail('before_instance_complete')
            outputs=dict(seal['files_sha256']);outputs['score_seal.json']=file_hash(root/'score_seal.json');outputs['public_results.json']=file_hash(root/'public_results.json')
            for o in ORGS:
                for name in ('eligible_graphsage.json','eligible_tabular_mlp.json','campaign_user_results.json','alert_attribution.json'):
                    relative=f'{o}/private/{name}';outputs[relative]=file_hash(root/relative)
            write_once(root/'completion.json',dict(status='COMPLETE_VALIDATED',identity=identity,files_sha256=outputs,independent_reconciliation='PASS'))
            fail('after_instance_complete');return public
        finally:
            for p in ports.values():p.close()

    def run_all(self,fail=lambda stage:None):
        self.scope.assert_ready()
        with run_lease(self.scope.output_root):return self._run_all(fail)
    def _run_all(self,fail=lambda stage:None):
        self.scope.assert_ready();rows=self.backend.inventory()
        require(len({r['variant_id'] for r in rows})==len(rows),'Duplicate instance register')
        if not self.scope.synthetic_only:require(len(rows)==171,'Incomplete TEST register')
        write_once(self.scope.output_root/'required_inventory.json',dict(catalog=self.scope.catalog.identity,rows=rows))
        write_once(self.scope.output_root/'catalog_metadata.json',asdict(self.scope.catalog))
        write_once(self.scope.output_root/'adapter_provenance.json',dict(adapter_identity=self.scope.adapter_identity,
            source_sha256={p:file_hash(ROOT/p) for p in __import__('src.phase6.heldout_contract_v2',fromlist=['MODULES']).MODULES},
            configuration_sha256=file_hash(ROOT/'configs/phase6/heldout_remediation_v2.json')))
        results=[self._run_instance(row,fail) for row in rows]
        pooled={};macro={};per_org={o:{} for o in ORGS};primary_cells={}
        for d in ('graphsage','tabular_mlp'):
            pooled_rows=[];org_metrics=[]
            for org in ORGS:
                values=[]
                for row in rows:
                    p=self.scope.output_root/row['variant_id']/org/'private'/f'eligible_{d}.json';items=json.loads(p.read_bytes());values.extend(items)
                    cell=canonical(dict(detector=d,seed=row['seed'],**{k:row.get(k,'fixture') for k in ('family','RIP_target','Raccount_target','Sorg_target')}))
                    primary_cells.setdefault(cell,[]).extend(items)
                m=metrics(values);independently_reconcile(values,m);org_metrics.append(m);per_org[org][d]=m;pooled_rows.extend(values)
            pooled[d]=metrics(pooled_rows);independently_reconcile(pooled_rows,pooled[d])
            macro[d]={k:sum(v[k] for v in org_metrics if v[k] is not None)/sum(v[k] is not None for v in org_metrics) if any(v[k] is not None for v in org_metrics) else None for k in ('recall','precision','fpr','f1','average_precision')}
        primary_factor=[]
        for cell,items in sorted(primary_cells.items()):
            value=metrics(items);independently_reconcile(items,value)
            primary_factor.append(dict(**json.loads(cell),metrics=value,interpretation='Descriptive frozen cell, dependent User-time examples; no causal effect or IID interval implied'))
        summary=dict(status='COMPLETE_SYNTHETIC_VALIDATION' if self.scope.synthetic_only else 'COMPLETE_171_TEST_TECHNICAL_REVIEW_REQUIRED',required=len(rows),completed=len(results),pooled=pooled,macro=macro,per_organization=per_org,primary_factor_seed_cells=primary_factor,
            campaign_results=[r for x in results for r in x['campaign_results']],
            factor_seed_cells=factor_cells([r for x in results for r in x['campaign_results']]),resources=[x['resources'] for x in results],
            instance_completion_sha256={r['variant_id']:file_hash(self.scope.output_root/r['variant_id']/'completion.json') for r in rows},
            run_metadata_sha256={p:file_hash(self.scope.output_root/p) for p in ('required_inventory.json','catalog_metadata.json','adapter_provenance.json')})
        write_once(self.scope.output_root/'run_completion.json',summary);return summary

def independent_campaign_reconciliation(specs,evidence,decisions,reported):
    """Brute-force temporal attribution oracle, separate from bisect evaluator."""
    first={};attribution=[];seen=set();by_user={};by_campaign={};spec_by_key={(s['variant_id'],s['campaign_id']):s for s in specs}
    for e in evidence:
        by_user.setdefault((e['variant_id'],e['organization'],e['user_id']),[]).append(e)
        by_campaign.setdefault((e['variant_id'],e['campaign_id']),[]).append(e)
    for d in sorted(decisions,key=lambda r:(r['variant_id'],r['at'],r['organization'],r['user_id'],r['family'])):
        key=(d['variant_id'],d['organization'],d['user_id'],d['at'],d['family'])
        require(key not in seen,'Duplicate operational unit');seen.add(key)
        if not d['alert']:continue
        candidates=set()
        for e in by_user.get((d['variant_id'],d['organization'],d['user_id']),[]):
            if d['at']-timedelta(minutes=10)<e['at']<=d['at']<spec_by_key[(e['variant_id'],e['campaign_id'])]['end']:candidates.add(e['campaign_id'])
        candidates=sorted(candidates)
        if len(candidates)==1:
            k=(d['variant_id'],candidates[0],d['organization'],d['user_id'],d['family']);first[k]=min(first.get(k,d['at']),d['at'])
        attribution.append(dict(variant_id=d['variant_id'],organization=d['organization'],user_id=d['user_id'],at=d['at'].isoformat(),family=d['family'],status='UNIQUE' if len(candidates)==1 else 'AMBIGUOUS' if candidates else 'UNATTRIBUTED',candidate_campaign_ids=sorted(candidates)))
    require(attribution==reported['private_alert_attribution'],'Independent attribution mismatch')
    for r in reported['private_user_results']:
        k=(r['variant_id'],r['campaign_id'],r['organization'],r['user_id'],r['family']);t=first.get(k)
        require(r['first_detection']==(t.isoformat() if t else None) and r['right_censored']==(t is None),'Independent User detection mismatch')
    for r in reported['organization_results']:
        found=[t for (v,c,o,u,f),t in first.items() if (v,c,o,f)==(r['variant_id'],r['campaign_id'],r['organization'],r['detector_family'])]
        require(r['detected']==bool(found) and r['unique_detected_target_users']==len(found) and r['first_qualifying_alert']==(min(found).isoformat() if found else None),'Independent organization detection mismatch')
        exposure=by_campaign.get((r['variant_id'],r['campaign_id']),[])
        targets={e['user_id'] for e in exposure if e['organization']==r['organization']}
        onset=min((e['at'] for e in exposure),default=None);end=spec_by_key[(r['variant_id'],r['campaign_id'])]['end']
        require(r['unique_exposed_target_users']==len(targets) and r['right_censored']==(not found) and
                r['event_time_seconds']==((min(found)-onset).total_seconds() if found else None) and
                r['censor_time_seconds']==((end-onset).total_seconds() if onset else None),'Independent coverage/censoring mismatch')
    for r in reported['campaign_results']:
        orgs={o for v,c,o,u,f in first if (v,c,f)==(r['variant_id'],r['campaign_id'],r['detector_family'])}
        require(r['detected_organizations']==len(orgs) and r['primary_all_targeted_undetected']==(not orgs if r['evaluable'] else None),'Independent campaign detection mismatch')
        exposure=by_campaign.get((r['variant_id'],r['campaign_id']),[]);onset=min((e['at'] for e in exposure),default=None)
        times=[t for (v,c,o,u,f),t in first.items() if (v,c,f)==(r['variant_id'],r['campaign_id'],r['detector_family'])]
        require(r['any_organization_detected']==bool(orgs) and r['all_organizations_detected']==(len(orgs)==r['targeted_organization_count']) and
                r['right_censored']==(not times) and r['event_time_seconds']==((min(times)-onset).total_seconds() if times else None),'Independent campaign time/classification mismatch')

def factor_cells(campaigns):
    groups={};fields=('detector_family','family','RIP_target','Raccount_target','Sorg_target','seed')
    for row in campaigns:groups.setdefault(canonical({k:row[k] for k in fields}),[]).append(row)
    return [dict(**json.loads(key),required_campaigns=len(rows),evaluable_campaigns=sum(r['evaluable'] for r in rows),
        wholly_undetected=sum(r['primary_all_targeted_undetected'] is True for r in rows),
        all_targeted_organizations_detected=sum(r['all_organizations_detected'] for r in rows),
        right_censored=sum(r['right_censored'] for r in rows),
        interpretation='Descriptive frozen-design cell; not an independent causal effect') for key,rows in sorted(groups.items())]

def independent_sharing_reconciliation(root,seal,policy,contexts):
    """Read sealed outputs only. No Issuer/Network/Recipient/evaluator oracle."""
    from collections import Counter
    root=Path(root);records=[];previous='0'*64
    segments=sorted(p for p in seal['files_sha256'] if p.startswith('sharing/progress/barriers.'))
    for relative in segments:
        for line in (root/relative).read_bytes().splitlines(keepends=True):
            if not line.endswith(b'\n'):break # preserved uncommitted crash tail
            r=json.loads(line);value=dict(r);h=value.pop('sha256')
            require(r['prev']==previous and r['seq']==len(records) and digest(value)==h and digest(r['body'])==r['body_sha256'],'Independent sharing journal-chain mismatch')
            previous=h;records.append(r['body'])
    require(previous==seal['journal_chain_sha256'],'Independent sharing chain seal mismatch')
    lookup={}
    for body in records:
        if body['event'] not in ('LOCAL','ISSUANCE','PUBLISHED','PAIRED','BEGIN','COMPLETE'):continue
        key=(body['event'],body.get('at'),body.get('organization'))
        require(key not in lookup,'Duplicate scientific barrier stage');lookup[key]=body
    def artifact(event,at,org=None):
        body=lookup[event,at,org];relative='sharing/'+body['path']
        require(seal['files_sha256'].get(relative)==body['sha256'],'Unsealed sharing reference')
        return json.loads((root/relative).read_bytes())
    all_indicators={};until={};expired=set();received=0;paired_rows=extra_rows=0
    begins=sorted((body for body in records if body['event']=='BEGIN'),key=lambda b:b['at'])
    for begin in begins:
        at=begin['at'];t=datetime.fromisoformat(at)
        require(('COMPLETE',at,None) in lookup,'Incomplete sharing barrier')
        expected=[];locals={}
        for org in sorted(begin['frames']):
            local=artifact('LOCAL',at,org);locals[org]=local
            require(local['provenance']['branch']==contexts[org].branch.identity and
                    local['provenance']['bundle']==json.loads(contexts[org].graph_seal.identity_json),'Independent local source/model provenance mismatch')
            recent=local['recent'];alerts=[]
            for score in local['scores']:
                require(score['threshold_hex']==json.loads(contexts[org].graph_seal.threshold_json)['hex'],'Independent local threshold mismatch')
                flag=score['threshold_hex'] is not None and float.fromhex(score['logit_hex'])>=float.fromhex(score['threshold_hex'])
                require(flag==(score['decision']=='ALERT') and bool(score['alert_id'])==flag,'Independent original local decision mismatch')
                if flag:alerts.append(score)
            issued=[]
            for score in sorted(alerts,key=lambda r:(r['user_id'],r['alert_id'])):
                ips=sorted({ip for when,u,ip in recent if u==score['user_id'] and t-timedelta(seconds=policy['attribution_window_seconds'])<datetime.fromisoformat(when)<=t})
                for ip in ips:
                    if until.get((org,ip),datetime.min)>t:continue
                    expiry=t+timedelta(seconds=policy['ttl_seconds']);until[org,ip]=expiry
                    value=dict(indicator_id=digest([policy['version'],org,ip,at]),ip=ip,issuer=org,issued_at=at,available_at=at,expires_at=expiry.isoformat(),policy_version=policy['version'],status=policy['status'])
                    issued.append(value);expected.append(value)
            require(artifact('ISSUANCE',at,org)['payloads']==issued,'Independent alert-to-IP attribution/suppression mismatch')
        proof=artifact('PUBLISHED',at)
        require(proof['payloads']==expected,'Independent publication-set mismatch')
        expiring={k for k,v in all_indicators.items() if datetime.fromisoformat(v['expires_at'])<=t and k not in expired}
        expiry_events=[r for r in proof['events'] if r['event']=='expiry']
        require({r['indicator_id'] for r in expiry_events}==expiring and len(expiry_events)==len(expiring) and
                all(r['at']==all_indicators[r['indicator_id']]['expires_at'] for r in expiry_events),'Independent exclusive expiry mismatch')
        expired.update(expiring)
        receipts=[]
        for org,events in proof['recipients'].items():
            receipts.extend((r['indicator_id'],org,r['at']) for r in events if r['event']=='receipt')
            require(all(r['organization']==org for r in events),'Recipient transcript identity mismatch')
        expected_receipts=[(p['indicator_id'],o,at) for p in expected for o in ORGS if o!=p['issuer']]
        require(Counter(receipts)==Counter(expected_receipts),'Independent receipt/availability mismatch')
        received+=len(receipts)
        require(Counter(r['indicator_id'] for r in proof['events'] if r['event']=='creation')==Counter(p['indicator_id'] for p in expected),'Independent creation transcript mismatch')
        for event in (r for r in proof['events'] if r['event']=='broadcast'):
            p=next(p for p in expected if p['indicator_id']==event['indicator_id'])
            require(event['at']==at and event['receivers']==sorted(o for o in ORGS if o!=p['issuer']) and event['simulated_delay_seconds']==0,'Independent broadcast mismatch')
        all_indicators.update({p['indicator_id']:p for p in expected})
        for org,local in locals.items():
            paired=artifact('PAIRED',at,org)
            require(paired['organization']==org and paired['variant_id']==contexts[org].branch.variant and paired['at']==at and paired['policy_sha256']==digest(policy),'Paired provenance mismatch')
            require(paired['local_provenance']==local['provenance'],'Paired source/model provenance mismatch')
            original={r['user_id']:r for r in local['scores']};current={int(u):set(ips) for u,ips in local['current'].items()}
            require(len(paired['paired'])==len(original) and {r['user_id'] for r in paired['paired']}==set(original),'Paired local-score cohort mismatch')
            def hits(user):return sorted(k for k,p in all_indicators.items() if p['issuer']!=org and p['ip'] in current.get(user,set()) and datetime.fromisoformat(p['available_at'])<=t<datetime.fromisoformat(p['expires_at']))
            for r in paired['paired']:
                score=original[r['user_id']];live=hits(r['user_id']);local_flag=score['decision']=='ALERT'
                require(r['logit_hex']==score['logit_hex'] and r['threshold_hex']==score['threshold_hex'] and r['local_alert']==local_flag and
                        r['indicator_ids']==live and r['local_plus_indicator_alert']==(local_flag or bool(live)),'Independent paired decision/utilization mismatch')
            additional=paired['additional_event_users']
            require({r['user_id'] for r in additional}==set(current)-set(original) and len(additional)==len(set(current)-set(original)),'Additional-event cohort mismatch')
            for r in additional:require(r['local_status']=='NOT_SCORED' and r['indicator_ids']==hits(r['user_id']) and r['local_plus_indicator_alert']==bool(hits(r['user_id'])),'Additional-event indicator mismatch')
            paired_rows+=len(paired['paired']);extra_rows+=len(additional)
    return dict(status='PASS_INDEPENDENT_SHARING_RECONCILIATION',barriers=len(begins),indicators=len(all_indicators),receipts=received,paired_rows=paired_rows,additional_event_users=extra_rows)

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    catalog=Catalog.permitted_metadata();scope=Scope.production(args.output,catalog)
    scope.assert_ready() # must fail before any register, manifest, weight or Parquet read
    print(canonical(Driver(scope,ProductionBackend(scope)).run_all()))

if __name__=='__main__':main()
