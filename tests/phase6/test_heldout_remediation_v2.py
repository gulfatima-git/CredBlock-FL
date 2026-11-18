"""Synthetic-only plumbing tests. Never open accepted model weights or datasets."""
from dataclasses import replace
from datetime import datetime,timedelta
import copy,json,sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest,torch
from src.phase6.adapter_metadata_audit_v1 import MetadataReader,AccessDenied
from src.phase6.heldout_contract_v2 import ROOT,ORGS,Branch,BundleSeal,Catalog,Scope,canonical,digest
from src.phase6.heldout_grid_v2 import EvaluationContext,score_grid,eligible_predictions
from src.phase6.heldout_barrier_v2 import Barrier,Journal,write_once
from src.phase6.heldout_driver_v2 import Driver,ProductionBackend,normalize_frame,metrics,independently_reconcile
from src.organization.rolling_graph_v1 import OrganizationGraphRuntime,RollingGraph,OBSERVABLE,HISTORY,RECENT
from src.phase6.local_graphsage import state_digest
from src.phase6.local_inference import closure,adjacent

T=datetime(2020,12,12,6)

class ToyModel(torch.nn.Module):
    """Generated RAM-only buffer; not a trained/accepted checkpoint/model."""
    def __init__(self,bias):
        super().__init__();self.register_buffer('bias',torch.tensor(float(bias),dtype=torch.float32));self.calls=0
    def forward(self,batch):
        self.calls+=1
        n=len(batch) if isinstance(batch,torch.Tensor) else len(batch.routing[-1].destination_rows)
        return torch.ones(n,dtype=torch.float32)*self.bias

def observable(t,org,u=9,ip='shared-observed-fixture'):
    return dict(zip(OBSERVABLE,[org,t,u,ip,False]))

@pytest.fixture
def setup(tmp_path):
    torch.set_num_threads(1)
    base=Catalog.permitted_metadata() # approved metadata/source only, no weights
    bundles={};seals=[]
    for o in ORGS:
        for d in ('graphsage','tabular_mlp'):
            model=ToyModel(1 if (o=='Org1' if d=='graphsage' else o=='Org2') else -1).eval();model.requires_grad_(False)
            identity=dict(organization=o,detector=d,model_sha256=digest([o,d,'RAM-fixture']),threshold_sha256=digest(['fixture-threshold',o,d]))
            threshold=dict(kind='finite',value=0.,hex=float(0).hex())
            bundle=SimpleNamespace(organization=o,model=model,identity=identity,threshold=threshold,
                sampler=json.loads(base.sampler_json),protocol=json.loads(base.protocol_json))
            seal=BundleSeal(o,d,canonical(identity),state_digest(model.state_dict()),canonical(threshold),__name__+'.ToyModel',base.sampler_json,base.protocol_json,True)
            bundles[o,d]=bundle;seals.append(seal)
    catalog=replace(base,seals=tuple(seals),source_hashes=(),fixture_only=True)
    scope=Scope.synthetic(tmp_path,catalog)
    return scope,bundles

def fixture_branch(org='Org1',variant='SYNTHETIC_SEED1001_TEST',at=T):
    return Branch(variant,org,at.isoformat(),(at+timedelta(hours=1)).isoformat(),digest(['manifest',variant]),digest(['obs',org,variant]),digest(['history',org,variant]))

class SyntheticPort:
    def __init__(self,backend,branch,path):
        self.backend,self.branch,self.organization=backend,branch,branch.organization
        self.db=sqlite3.connect(path);self.db.executescript('CREATE TABLE IF NOT EXISTS command(at TEXT PRIMARY KEY,frame TEXT,record TEXT,graph BLOB);')
        last=self.db.execute('SELECT graph FROM command ORDER BY at DESC LIMIT 1').fetchone()
        if last:self.runtime=OrganizationGraphRuntime(self.organization,RollingGraph.from_checkpoint_bytes(last[0]))
        else:
            self.runtime=OrganizationGraphRuntime(self.organization);t=branch.start-timedelta(seconds=30)
            self.runtime.apply_timestamp_batch(t,[observable(t,self.organization,u=1)],['H0'])
    def frame_identity(self,t,frame):return digest(dict(branch=self.branch.identity,at=t.isoformat(),frame=normalize_frame(frame)))
    def ensure_local(self,t,frame):
        at=t.isoformat();expected=canonical(normalize_frame(frame));old=self.db.execute('SELECT frame,record FROM command WHERE at=?',(at,)).fetchone()
        if old:
            assert old[0]==expected;return json.loads(old[1])
        assert self.runtime.graph.clock<t
        self.backend.local_calls+=1
        graph=self.runtime.graph;old_adj=adjacent(graph);changed=set()
        for row in frame['observations']:changed.update([('U',row['User ID']),('I',row['IP Address'])])
        for events,duration in ((graph.recent_events,RECENT),(graph.history_events,HISTORY)):
            for e in events:
                if e.time>t-duration:break
                changed.update([('U',e.user),('I',e.ip)])
        users=closure(old_adj,changed)
        if frame['observations']:self.runtime.apply_timestamp_batch(t,frame['observations'],frame['tokens'])
        else:self.runtime.advance(t)
        users|=closure(adjacent(graph),changed);users={u for u in users if ('U',u) in graph.retained.nodes}
        if frame['heartbeat']:users.update(k[1] for k in graph.recent.nodes if k[0]=='U')
        z=float(self.bundle('graphsage').model.bias.item());scores=[]
        for u in sorted(users):scores.append(dict(user_id=u,logit_hex=z.hex(),threshold_hex=float(0).hex(),decision='ALERT' if z>=0 else 'NO_ALERT',alert_id=digest([self.branch.identity,at,u]) if z>=0 else None))
        current={}
        for r in frame['observations']:current.setdefault(str(r['User ID']),set()).add(r['IP Address'])
        value=dict(at=at,scores=scores,recent=[[e.time.isoformat(),e.user,e.ip] for e in graph.recent_events],current={u:sorted(v) for u,v in current.items()},provenance=dict(branch=self.branch.identity,bundle=self.bundle('graphsage').identity,view_digest=graph.view().digest()))
        with self.db:self.db.execute('INSERT INTO command VALUES (?,?,?,?)',(at,expected,canonical(value),graph.checkpoint_bytes()))
        return value
    def view(self,t):assert self.runtime.graph.clock==t;return self.runtime.detection_view()
    def bundle(self,d):return self.backend.bundles[self.organization,d]
    def resource_summary(self):return dict(kind='synthetic_contract_fixture',local_commits=self.db.execute('SELECT COUNT(*) FROM command').fetchone()[0],original_GNN_latency_measured=False)
    def close(self):self.db.close()

class SyntheticBackend:
    def __init__(self,scope,bundles,count=1):self.scope,self.bundles,self.count=scope,bundles,count;self.local_calls=0;self.truth_calls=0;self.label_calls=0
    def inventory(self):return [dict(variant_id=f'SYNTHETIC_SEED{1001+i}_TEST',campaign_start=(T+timedelta(days=i)).isoformat(),campaign_end_exclusive=(T+timedelta(days=i,hours=1)).isoformat(),targeted_organizations='|'.join(ORGS),seed=str(1001+i)) for i in range(self.count)]
    def prepare(self,row,root):
        ports={};schedules={};contexts={};start=datetime.fromisoformat(row['campaign_start'])
        for o in ORGS:
            b=fixture_branch(o,row['variant_id'],start);folder=root/o/'private';folder.mkdir(parents=True,exist_ok=True)
            ports[o]=SyntheticPort(self,b,folder/'local.sqlite');contexts[o]=EvaluationContext.bind(self.scope.catalog,b)
            schedule={t:dict(observations=[],tokens=[],heartbeat=True,final=False) for t in b.grid}
            for minute in (0,59):
                t=start+timedelta(seconds=1) if minute==0 else start+timedelta(minutes=59)
                schedule[t]=dict(observations=[observable(t,o)],tokens=[str(minute)],heartbeat=False,final=False)
            schedule[b.stop-timedelta(microseconds=1)]=dict(observations=[],tokens=[],heartbeat=True,final=True);schedules[o]=schedule
        return ports,schedules,contexts
    def labels(self,context,at,seal):
        assert seal['status']=='SCORES_SEALED_BEFORE_LABELS';assert (self.scope.output_root/context.branch.variant/'score_seal.json').exists();self.label_calls+=1
        elapsed=(at-context.branch.start).total_seconds();rows=[]
        for u in (1,9):
            y=0 if u==1 and elapsed==0 else 1 if u==9 and elapsed==600 else -1
            positive=context.branch.start+timedelta(seconds=1) if y==1 else None
            rows.append(dict(organization=context.branch.organization,split='TEST',variant_id=context.branch.variant,label_time=at,**{'User ID':u},node_label=y,supervision_eligible=y!=-1,latest_positive_evidence=positive,positive_expires_at=positive+timedelta(minutes=10) if positive else None,query_kind='grid_snapshot'))
        return rows
    def truth(self,row,contexts,seal):
        assert seal['status']=='SCORES_SEALED_BEFORE_LABELS';self.truth_calls+=1;b=contexts['Org1'].branch
        specs=[dict(variant_id=b.variant,campaign_id='synthetic-campaign',start=b.start,end=b.stop,targeted_organizations=list(ORGS),seed=int(row['seed']),factors=dict(family='fixture',RIP_target=.2,Raccount_target=.5,Sorg_target=5))]
        evidence=[dict(variant_id=b.variant,campaign_id='synthetic-campaign',organization=o,user_id=9,at=b.start+timedelta(seconds=1)) for o in ORGS]
        return specs,evidence

def make_barrier(scope,bundles,directory=None):
    backend=SyntheticBackend(scope,bundles);row=backend.inventory()[0];root=directory or scope.output_root/row['variant_id'];root.mkdir(parents=True,exist_ok=True)
    ports,schedules,contexts=backend.prepare(row,root)
    return Barrier(scope,ports,root/'sharing'),backend,schedules,contexts

@pytest.mark.parametrize('bad',['missing','mixed_variant','horizon','manifest','network','issuer','recipient','org'])
def test_F1_negative(setup,bad):
    scope,bundles=setup;barrier,backend,schedules,contexts=make_barrier(scope,bundles)
    try:
        if bad=='missing':barrier.branches.pop('Org5')
        elif bad=='mixed_variant':barrier.branches['Org5']=replace(barrier.branches['Org5'],variant='OTHER_TEST')
        elif bad=='horizon':barrier.branches['Org5']=replace(barrier.branches['Org5'],anchor=(T+timedelta(hours=1)).isoformat(),end=(T+timedelta(hours=2)).isoformat())
        elif bad=='manifest':barrier.branches['Org5']=replace(barrier.branches['Org5'],manifest_sha256='1'*64)
        elif bad=='network':barrier.network.config['ttl_seconds']+=1
        elif bad=='issuer':barrier.issuers['Org2'].config['ttl_seconds']+=1
        elif bad=='recipient':barrier.network.recipients['Org3'].config['status']='malicious'
        else:barrier.issuers['Org2'].organization='Org3'
        with pytest.raises(ValueError):barrier.process(T,{o:schedules[o][T] for o in ORGS})
        assert backend.local_calls==0
    finally:
        for p in barrier.ports.values():p.close()

@pytest.mark.parametrize('bad',['state','identity','threshold','sampler','training','class','context','view','snapshot','variant'])
def test_F2_negative(setup,bad):
    scope,bundles=setup;barrier,backend,schedules,contexts=make_barrier(scope,bundles);ctx=contexts['Org1'];p=barrier.ports['Org1']
    try:
        barrier.process(T,{o:schedules[o][T] for o in ORGS});view=ctx.capture(scope,p,T);bundle=bundles['Org1','graphsage']
        if bad=='state':bundle.model.bias.add_(1)
        elif bad=='identity':bundle.identity['model_sha256']='f'*64
        elif bad=='threshold':bundle.threshold['value']=2
        elif bad=='sampler':bundle.sampler['seed']+=1
        elif bad=='training':bundle.model.train()
        elif bad=='class':bundle.model=torch.nn.Identity().eval()
        elif bad=='context':ctx=replace(ctx,schema_sha256='e'*64)
        elif bad=='view':view=replace(view,context_identity='d'*64)
        elif bad=='snapshot':view=replace(view,asof=(T+timedelta(seconds=1)).isoformat())
        else:ctx=replace(ctx,branch=replace(ctx.branch,variant='DIFFERENT_TEST'))
        calls=getattr(bundle.model,'calls',0)
        with pytest.raises(ValueError):score_grid(scope,ctx,view,bundle,'graphsage')
        assert getattr(bundle.model,'calls',0)==calls
    finally:
        for p in barrier.ports.values():p.close()

def test_F2_original_shapes_and_offline_masks(setup):
    scope,bundles=setup;b,backend,schedules,contexts=make_barrier(scope,bundles)
    try:
        b.process(T,{o:schedules[o][T] for o in ORGS});ctx=contexts['Org1'];bound=ctx.capture(scope,b.ports['Org1'],T)
        raw=score_grid(scope,ctx,bound,bundles['Org1','graphsage'],'graphsage');assert [r['user_id'] for r in raw['roots']]==[1]
        row=dict(organization='Org1',split='TEST',variant_id=ctx.branch.variant,label_time=T,**{'User ID':1},node_label=0,supervision_eligible=True,latest_positive_evidence=None,positive_expires_at=None,query_kind='grid_snapshot')
        seal=dict(status='SCORES_SEALED_BEFORE_LABELS',raw_score_digests=[digest(raw)])
        assert len(eligible_predictions(scope,ctx,raw,[row],seal))==1
        for change in ({'split':'VAL'},{'supervision_eligible':False},{'variant_id':'OTHER_TEST'},{'label_time':T+timedelta(seconds=1)},{'query_kind':'event_only'}):
            with pytest.raises(ValueError):eligible_predictions(scope,ctx,raw,[dict(row,**change)],seal)
        with pytest.raises(ValueError):eligible_predictions(scope,ctx,raw,[row,row],seal)
        with pytest.raises(ValueError):eligible_predictions(scope,ctx,raw,[row],{})
    finally:
        for p in b.ports.values():p.close()

class Crash(Exception):pass

@pytest.mark.parametrize('stage',['after_begin','after_network_memory','after_publication_prepared','after_published','before_complete','after_complete']+
 [f'{stage}:{org}' for stage in ('before_local','after_local','after_local_record','after_issuance','after_paired') for org in ORGS]+
 [f'after_receipt:{org}' for org in ORGS if org!='Org1'])
def test_F3_restart_exact_no_committed_local_rescoring(setup,stage):
    scope,bundles=setup;b,backend,schedules,contexts=make_barrier(scope,bundles)
    commands={o:schedules[o][T] for o in ORGS}
    def fail(value):
        if value==stage:raise Crash(value)
    try:
        with pytest.raises(Crash):b.process(T,commands,fail)
    finally:
        for p in b.ports.values():p.close()
    root=scope.output_root/contexts['Org1'].branch.variant
    ports,_,_=backend.prepare(backend.inventory()[0],root);restored=Barrier(scope,ports,root/'sharing')
    try:
        actual=restored.process(T,commands)
        assert backend.local_calls==5
        # Compare to a clean isolated reference, preserving all original traces.
        cleanroot=scope.output_root/'reference';cleanports,_,_=backend.prepare(backend.inventory()[0],cleanroot)
        clean=Barrier(scope,cleanports,cleanroot/'sharing')
        try:expected=clean.process(T,commands);assert actual==expected
        finally:
            for p in cleanports.values():p.close()
    finally:
        for p in ports.values():p.close()

def test_F3_incomplete_tail_preserved_and_checksum_corruption_blocked(tmp_path):
    j=Journal(tmp_path/'tail',{'x':1});path=tmp_path/'tail/barriers.000000.jsonl';original=path.read_bytes()
    with path.open('ab') as f:f.write(b'{"uncommitted"')
    recovered=Journal(tmp_path/'tail',{'x':1});assert path.read_bytes()==original+b'{"uncommitted"'
    assert recovered.records[-1]['body']['event']=='PRESERVED_INCOMPLETE_TAIL'
    bad=tmp_path/'bad';bad.mkdir();(bad/'barriers.000000.jsonl').write_bytes(original.replace(b'"x":1',b'"x":2'))
    with pytest.raises(ValueError):Journal(bad,{'x':1})

def test_F4_end_to_end_two_instances_and_completion_reuse(setup):
    scope,bundles=setup;backend=SyntheticBackend(scope,bundles,count=2);driver=Driver(scope,backend)
    result=driver.run_all();assert result['completed']==result['required']==2
    assert set(result['pooled'])=={'graphsage','tabular_mlp'}
    assert all(r['any_organization_detected'] for r in result['campaign_results'])
    assert any(not r['all_organizations_detected'] for r in result['campaign_results'] if r['detector_family']=='local_only')
    assert all(r['all_organizations_detected'] for r in result['campaign_results'] if r['detector_family']=='local_plus_indicator')
    old_calls=backend.local_calls;old_grid=sum(b.model.calls for b in bundles.values());labels=backend.label_calls
    again=driver.run_all();assert again==result and old_calls==backend.local_calls and old_grid==sum(b.model.calls for b in bundles.values()) and backend.label_calls==labels

@pytest.mark.parametrize('stage',['after_grid_commit:Org1:graphsage','after_grid_file:Org2:tabular_mlp','after_score_seal','after_labels','before_instance_complete','after_instance_complete'])
def test_F4_recovery_and_seal_before_labels(setup,stage):
    scope,bundles=setup;backend=SyntheticBackend(scope,bundles);driver=Driver(scope,backend)
    def fail(s):
        if s==stage:raise Crash(s)
    with pytest.raises(Crash):driver.run_all(fail)
    assert not (scope.output_root/'run_completion.json').exists()
    if stage.startswith('after_grid'):assert backend.label_calls==0
    result=driver.run_all();assert result['completed']==1 and backend.local_calls==45
    assert sum(b.model.calls for b in bundles.values())==20 # committed grid model calls never repeat
    assert (scope.output_root/'run_completion.json').exists()

def test_F4_incomplete_schedule_rejected_before_labels(setup):
    scope,bundles=setup;backend=SyntheticBackend(scope,bundles);prepare=backend.prepare
    def broken(row,root):
        ports,schedules,contexts=prepare(row,root);schedules['Org5'].pop(T+timedelta(minutes=50));return ports,schedules,contexts
    backend.prepare=broken
    with pytest.raises(ValueError,match='heartbeat'):Driver(scope,backend).run_all()
    assert backend.label_calls==backend.truth_calls==0 and not (scope.output_root/'run_completion.json').exists()

def test_F4_independent_reconciliation_rejects_altered_metrics():
    row=dict(organization='Org1',variant_id='FIXTURE_TEST',asof=T.isoformat(),user_id=1,detector='graphsage',node_label=1,logit_hex=float(1).hex(),alert=True,threshold=dict(kind='finite',value=0.,hex=float(0).hex()))
    result=metrics([row]);independently_reconcile([row],result)
    with pytest.raises(ValueError):independently_reconcile([row],dict(result,tp=0))

def test_production_scope_blocks_before_register_payload_or_weight_io(setup,monkeypatch):
    scope,bundles=setup;real=Scope.production(ROOT/'reports/phase6/heldout_test_v2/never_started',Catalog.permitted_metadata())
    # No execution approval exists; do not create one even for this test.
    with pytest.raises(ValueError,match='blocked'):ProductionBackend(real)
    assert not real.output_root.exists()

def test_fixture_scope_cannot_activate_any_production_reader(setup):
    scope,bundles=setup
    with pytest.raises(ValueError,match='rejects fixture'):ProductionBackend(scope)
    # Even a constructor-skipping misuse must fail before any project payload IO.
    backend=ProductionBackend.__new__(ProductionBackend);backend.scope=scope
    for call in (lambda:backend.inventory(),lambda:backend.prepare({},scope.output_root),
                 lambda:backend.labels(None,T,{}),lambda:backend.truth({},None,{})):
        with pytest.raises(ValueError,match='rejects fixture'):call()

def test_production_model_validation_and_original_threads_precede_payload_loading():
    import ast,inspect
    source=inspect.getsource(ProductionBackend.prepare)
    assert source.index('self.scope.assert_ready()')<source.index('torch.set_num_threads(')<source.index('LocalModelRegistry(ROOT')<source.index('manifest_path=self.pins.check(')<source.index('graph,schedule,identity=load_stream(')
    assert source.index(".seal(o,'graphsage').validate(")<source.index('manifest_path=self.pins.check(')
    assert source.index(".seal(o,'tabular_mlp').validate(")<source.index('manifest_path=self.pins.check(')

def test_production_port_identity_supports_qualified_and_m_invocations(monkeypatch):
    import sys
    from src.phase6.heldout_grid_v2 import verified_port_type
    from src.phase6.heldout_driver_v2 import LocalPort
    assert verified_port_type(LocalPort.__new__(LocalPort))
    MainPort=type('LocalPort',(),{'__module__':'__main__'})
    monkeypatch.setattr(sys.modules['__main__'],'__spec__',SimpleNamespace(name='src.phase6.heldout_driver_v2'))
    assert verified_port_type(MainPort())
    monkeypatch.setattr(sys.modules['__main__'],'__spec__',SimpleNamespace(name='unrelated_module'))
    assert not verified_port_type(MainPort()) and not verified_port_type(SimpleNamespace())

def test_F4_process_lease_excludes_concurrent_runners(tmp_path):
    from src.phase6.heldout_driver_v2 import run_lease
    with run_lease(tmp_path):
        with pytest.raises(ValueError,match='Another evaluation'): 
            with run_lease(tmp_path):pass
    with run_lease(tmp_path):pass # OS releases ownership, no stale-file deletion

def test_F2_self_consistent_but_unissued_view_rejected(setup):
    from src.phase6.heldout_grid_v2 import BoundView
    scope,bundles=setup;b,backend,schedules,contexts=make_barrier(scope,bundles)
    try:
        b.process(T,{o:schedules[o][T] for o in ORGS});ctx=contexts['Org1'];view=b.ports['Org1'].view(T)
        forged=BoundView(ctx.identity,T.isoformat(),view.digest(),view)
        with pytest.raises(ValueError,match='not issued'):score_grid(scope,ctx,forged,bundles['Org1','graphsage'],'graphsage')
    finally:
        for p in b.ports.values():p.close()

@pytest.mark.parametrize('mode',['no_alerts','onset','expired','overlap','multiple_orgs'])
def test_F4_independent_campaign_oracle_on_temporal_edge_fixtures(mode):
    from src.phase6.detectability import evaluate_campaigns
    from src.phase6.heldout_driver_v2 import independent_campaign_reconciliation
    spec=dict(variant_id='EDGE_TEST',campaign_id='c1',start=T,end=T+timedelta(hours=1),targeted_organizations=['Org1','Org2'],seed=1001,factors=dict(family='fixture',RIP_target=.1,Raccount_target=.2,Sorg_target=2))
    evidence=[dict(variant_id='EDGE_TEST',campaign_id='c1',organization=o,user_id=9,at=T) for o in ('Org1','Org2')]
    specs=[spec];decisions=[]
    if mode!='no_alerts':
        at=T+timedelta(minutes=10) if mode=='expired' else T
        decisions=[dict(variant_id='EDGE_TEST',organization=o,user_id=9,at=at,family=f,alert=True) for o in (('Org1','Org2') if mode=='multiple_orgs' else ('Org1',)) for f in ('local_only','local_plus_indicator')]
    if mode=='overlap':
        specs.append(dict(spec,campaign_id='c2'));evidence += [dict(e,campaign_id='c2') for e in evidence]
    result=evaluate_campaigns(specs,evidence,decisions,{('EDGE_TEST',o,f):True for o in ('Org1','Org2') for f in ('local_only','local_plus_indicator')})
    independent_campaign_reconciliation(specs,evidence,decisions,result)
    broken=copy.deepcopy(result);broken['campaign_results'][0]['detected_organizations']+=1
    with pytest.raises(ValueError):independent_campaign_reconciliation(specs,evidence,decisions,broken)

def test_historical_722_and_all_raw_weight_paths_denied():
    metadata='reports/phase6/test_adapter_v1/scope_incident_v1/affected_paths_from_saved_metadata.json'
    paths=MetadataReader(ROOT,[metadata]).json(metadata)['paths'];r=MetadataReader(ROOT,paths,paths)
    for p in paths:
        with pytest.raises(AccessDenied):r.read(p)
    assert r.accesses==[]

def test_F2_multi_chunk_shapes_and_masking_only_after_raw_seal(setup):
    scope,bundles=setup;b,backend,schedules,contexts=make_barrier(scope,bundles);p=b.ports['Org1'];ctx=contexts['Org1']
    try:
        t=T-timedelta(seconds=1);rows=[observable(t,'Org1',u=i) for i in range(2,302)]
        p.runtime.apply_timestamp_batch(t,rows,[f'X{i}' for i in range(len(rows))])
        b.process(T,{o:schedules[o][T] for o in ORGS});sizes=[];bundle=bundles['Org1','graphsage'];original=bundle.model.forward
        def forward(packet):sizes.append(len(packet.routing[-1].destination_rows));return original(packet)
        bundle.model.forward=forward
        raw=score_grid(scope,ctx,ctx.capture(scope,p,T),bundle,'graphsage')
        assert sizes==[256,45] and len(raw['roots'])==301
        rows=[dict(organization='Org1',split='TEST',variant_id=ctx.branch.variant,label_time=T,**{'User ID':u},node_label=0 if u==1 else -1,supervision_eligible=u==1,latest_positive_evidence=None,positive_expires_at=None,query_kind='grid_snapshot') for u in range(1,302)]
        joined=eligible_predictions(scope,ctx,raw,rows,dict(status='SCORES_SEALED_BEFORE_LABELS',raw_score_digests=[digest(raw)]))
        assert len(joined)==1 and sizes==[256,45]
        with pytest.raises(ValueError):ctx.capture(scope,p,T+timedelta(seconds=1))
    finally:
        for port in b.ports.values():port.close()

def test_F4_completed_artifact_tampering_is_blocked_without_model_calls(setup):
    scope,bundles=setup;backend=SyntheticBackend(scope,bundles);driver=Driver(scope,backend);driver.run_all()
    old=backend.local_calls;calls=sum(b.model.calls for b in bundles.values())
    path=scope.output_root/backend.inventory()[0]['variant_id']/'Org1/private/grid_00_graphsage.json'
    with path.open('ab') as f:f.write(b'corrupt')
    with pytest.raises(ValueError,match='Sealed output'):driver.run_all()
    assert old==backend.local_calls and calls==sum(b.model.calls for b in bundles.values())
