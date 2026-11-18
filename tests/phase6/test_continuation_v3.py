"""Production-schema synthetic stores; no real TEST payloads or checkpoints."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import json,sqlite3,hashlib
import pytest,torch
import test_heldout_remediation_v2 as fixture
from src.phase6.heldout_contract_v2 import Scope as V2Scope,ORGS,canonical,digest,Branch
from src.phase6.heldout_driver_v2 import Driver as V2Driver,LocalPort
from src.phase6.heldout_local_inference_v1 import HeldOutLocalInference
from src.phase6.heldout_grid_v2 import EvaluationContext
from src.organization.rolling_graph_v1 import OrganizationGraphRuntime
from src.phase6.continuation_contract_v3 import ContinuationScope,CapturePermit,eligible_compat,relative_path
from src.phase6.continuation_reader_v3 import build_certificate,PredecessorReader,sha
from src.phase6.continuation_recovery_v3 import Workspace,inspect_store
from src.phase6.continuation_driver_v3 import Driver as V3Driver
from src.phase6.continuation_manifest_v3 import FullRunManifest,frozen_rows,verify_completion

class RealStoreBackend(fixture.SyntheticBackend):
    def inventory(self):
        return [dict(r,split='TEST',family='fixture',RIP_target='0.2',Raccount_target='0.5',Sorg_target='5') for r in super().inventory()]
    def prepare(self,row,root):
        ports={};schedules={};contexts={}
        from datetime import datetime
        start=datetime.fromisoformat(row['campaign_start'])
        for org in ORGS:
            branch=fixture.fixture_branch(org,row['variant_id'],start);runtime=OrganizationGraphRuntime(org)
            warm=start-timedelta(seconds=30);runtime.apply_timestamp_batch(warm,[fixture.observable(warm,org,u=1)],['H0'])
            identity=dict(split='TEST',organization=org,variant_id=row['variant_id'],anchor=branch.anchor,end_exclusive=branch.end,
                observations_sha256=branch.observations_sha256,history_reference_sha256=branch.history_sha256)
            bundle=self.bundles[org,'graphsage'];registry=SimpleNamespace(organization=org,current=bundle)
            service=HeldOutLocalInference(root/org/'private/local.sqlite',org,row['variant_id'],registry,
                json.loads(self.scope.catalog.inference_config_json),initial_graph=runtime.graph,source_identity=identity,scope=self.scope)
            ports[org]=LocalPort(branch,service,self.bundles[org,'tabular_mlp']);contexts[org]=EvaluationContext.bind(self.scope.catalog,branch)
            s={t:dict(observations=[],tokens=[],heartbeat=True,final=False) for t in branch.grid}
            for k,t in enumerate((start+timedelta(seconds=1),start+timedelta(minutes=59))):
                s[t]=dict(observations=[fixture.observable(t,org)],tokens=[f'R{k}'],heartbeat=False,final=False)
            s[branch.stop-timedelta(microseconds=1)]=dict(observations=[],tokens=[],heartbeat=True,final=True);schedules[org]=s
        return ports,schedules,contexts

@pytest.fixture
def world(tmp_path_factory):
    root=tmp_path_factory.mktemp('c');old,bundles=fixture.setup.__wrapped__(root/'s')
    seals=[]
    for s in old.catalog.seals:
        b=bundles[s.organization,s.detector]
        b.identity=dict(b.identity,feature_schema_sha256=old.catalog.schema_sha256,protocol_sha256=digest(old.catalog.protocol))
        b.fingerprint=digest(b.identity);seals.append(replace(s,identity_json=canonical(b.identity)))
    catalog=replace(old.catalog,seals=tuple(seals));old=V2Scope.synthetic(root/'s',catalog)
    return root,old,bundles

class Crash(Exception):pass

def prefix(world,stage='after_local:Org3'):
    root,old,bundles=world;backend=RealStoreBackend(old,bundles);row=backend.inventory()[0]
    def fail(s):
        if s==stage:raise Crash(s)
    with pytest.raises(Crash):V2Driver(old,backend).run_instance(row,fail)
    cert_path=root/'certificate.json'
    cert=build_certificate(CapturePermit.synthetic(old.output_root/row['variant_id'],old.catalog),old.catalog,row,cert_path)
    new=ContinuationScope.synthetic(root/'d',old.catalog,cert_path)
    return backend,row,cert,new

def science_result(root):
    p=json.loads((root/'public_results.json').read_bytes())
    return {k:p[k] for k in ('fixed_grid','campaign_results','organization_results','operational_decision_rows','independent_sharing')}

@pytest.mark.parametrize('stage',[
    'after_begin','after_local:Org3','after_issuance:Org2','after_receipt:Org2',
    'after_publication_prepared','after_published','before_complete','after_complete',
    'after_grid_commit:Org1:graphsage','after_grid_file:Org2:tabular_mlp',
    'after_score_seal','after_labels','before_instance_complete'])
def test_cross_version_recovery_exact_without_committed_inference_repeat(world,stage):
    root,old,bundles=world;before_calls=sum(b.model.calls for b in bundles.values())
    backend,row,cert,new=prefix(world,stage);source=old.output_root/row['variant_id']
    pinned={r:sha(source/r) for r in cert['body']['files']}
    next_backend=RealStoreBackend(new,bundles);V3Driver(new,next_backend).run_instance(row)
    mixed=new.output_root/row['variant_id'];calls_mixed=sum(b.model.calls for b in bundles.values())-before_calls
    # Separate generated reference model execution; never an accepted campaign.
    fresh=V2Scope.synthetic(root/'r',old.catalog);ref=RealStoreBackend(fresh,bundles)
    before_reference=sum(b.model.calls for b in bundles.values());V2Driver(fresh,ref).run_instance(row)
    assert calls_mixed==sum(b.model.calls for b in bundles.values())-before_reference
    assert science_result(mixed)==science_result(fresh.output_root/row['variant_id'])
    for org in ORGS:
        for name in ('eligible_graphsage.json','eligible_tabular_mlp.json','campaign_user_results.json','alert_attribution.json'):
            assert json.loads((mixed/org/'private'/name).read_bytes())==json.loads((fresh.output_root/row['variant_id']/org/'private'/name).read_bytes())
    workspace=Workspace(new);workspace.verify_prefix();workspace.verify_recovered_stores()
    assert pinned=={r:sha(source/r) for r in pinned}
    provenance=json.loads((mixed/'completion.json').read_bytes())['execution_provenance']
    assert provenance['certificate_id']==cert['certificate_id'] and provenance['origin_executor']!=provenance['effective_executor']

def test_certificate_reader_no_writes_and_grid_origin_binding(world):
    root,old,bundles=world;_,row,cert,new=prefix(world,'after_grid_commit:Org1:graphsage')
    source=old.output_root/row['variant_id'];before={p:sha(source/p) for p in cert['body']['files']}
    reader=PredecessorReader(cert,old.catalog).verify();raw=reader.grid('Org1',fixture.T.isoformat(),'graphsage')['raw']
    ctx=EvaluationContext.bind(old.catalog,Branch(**cert['body']['bindings']['Org1']))
    rows=[dict(organization='Org1',split='TEST',variant_id=row['variant_id'],label_time=fixture.T,**{'User ID':1},node_label=0,supervision_eligible=True,latest_positive_evidence=None,positive_expires_at=None,query_kind='grid_snapshot')]
    seal=dict(status='SCORES_SEALED_BEFORE_LABELS',raw_score_digests=[digest(raw)])
    assert len(eligible_compat(new,ctx,raw,rows,seal,reader))==1
    with pytest.raises(ValueError):eligible_compat(new,ctx,dict(raw,adapter_identity='f'*64),rows,seal,reader)
    with pytest.raises(ValueError):eligible_compat(new,ctx,dict(raw,roots=[]),rows,dict(seal,raw_score_digests=[digest(dict(raw,roots=[]))]),reader)
    assert before=={p:sha(source/p) for p in before}

@pytest.mark.parametrize('bad',['body','science','source','journal','checkpoint','WAL'])
def test_corruption_and_unsafe_capture_rejected(world,bad):
    root,old,bundles=world;_,row,cert,new=prefix(world)
    source=old.output_root/row['variant_id']
    if bad=='body':
        cert['body']['origin']['variant']='OTHER_TEST'
        with pytest.raises(ValueError):PredecessorReader(cert,old.catalog)
    elif bad=='science':
        with pytest.raises(ValueError):PredecessorReader(cert,replace(old.catalog,schema_sha256='f'*64))
    elif bad=='source':
        with (source/'identity.json').open('ab') as f:f.write(b' ')
        with pytest.raises(ValueError):PredecessorReader(cert,old.catalog).verify()
    elif bad=='journal':
        q=source/'sharing/progress/barriers.000000.jsonl';q.write_bytes(q.read_bytes().replace(b'BEGIN',b'BOGUS'))
        with pytest.raises(ValueError):build_certificate(CapturePermit.synthetic(source,old.catalog),old.catalog,row,root/'bad.json')
    elif bad=='checkpoint':
        db=sqlite3.connect(source/'Org1/private/local.sqlite');db.execute("UPDATE checkpoints SET sha256='bad'");db.commit();db.close()
        with pytest.raises(ValueError):inspect_store(source/'Org1/private/local.sqlite','Org1',row['variant_id'],old.catalog,cert['body']['bindings']['Org1'])
    else:
        (source/'Org1/private/local.sqlite-wal').write_bytes(b'pending')
        with pytest.raises(ValueError,match='WAL'):build_certificate(CapturePermit.synthetic(source,old.catalog),old.catalog,row,root/'bad.json')

def test_workspace_copy_interruption_and_transition_idempotence(world):
    root,old,bundles=world;_,row,cert,new=prefix(world)
    w=Workspace(new);first=next(iter(cert['body']['files']))
    def fail(stage):
        if stage=='after_copy_file:'+first:raise Crash(stage)
    with pytest.raises(Crash):w.prepare(fail)
    w.prepare();w.prepare();w.verify_recovered_stores()
    backend=RealStoreBackend(new,bundles);driver=V3Driver(new,backend);driver.run_instance(row)
    calls=sum(b.model.calls for b in bundles.values());driver.run_instance(row)
    assert sum(b.model.calls for b in bundles.values())==calls
    for directory in cert['body']['journals']:
        q=w.target/directory/'barriers.000000.jsonl'
        records=[json.loads(x) for x in q.read_bytes().splitlines()]
        assert sum(r['body']['event']=='ENGINE_TRANSITION' for r in records)==1

@pytest.mark.parametrize('relative',['../escape','/absolute','a/../../b','C:/escape','a\\b'])
def test_path_escape_denied_before_access(tmp_path,relative):
    with pytest.raises(ValueError):relative_path(tmp_path,relative)

def test_production_permission_cannot_come_from_implementation_approval(world):
    root,old,bundles=world
    with pytest.raises(ValueError):CapturePermit.synthetic(Path(__file__).resolve().parents[2],old.catalog)
    with pytest.raises(ValueError,match='not separately approved'):
        ContinuationScope.production(root/'never',old.catalog,root/'missing_cert.json',root/'missing_approval.json')
    assert not (root/'never').exists()

def make_register(row):
    rows=[row]
    for i in range(1,171):rows.append(dict(row,variant_id=f'EXTRA_{i:03}_TEST',seed=str(1001+i%3)))
    return sorted(rows,key=lambda r:r['variant_id'])

def test_full_manifest_requires_all171_and_denies_duplicate_or_train_rows(world):
    root,old,bundles=world;scope=ContinuationScope.synthetic(root/'m',old.catalog);row=RealStoreBackend(old,bundles).inventory()[0];rows=make_register(row)
    ledger=FullRunManifest(scope,rows,scope.output_root/'manifest')
    assert len(ledger.by_id)==171
    with pytest.raises(ValueError,match='Incomplete'):ledger.seal()
    with pytest.raises(ValueError):frozen_rows(scope,rows[:-1])
    with pytest.raises(ValueError):frozen_rows(scope,[dict(rows[0],split='TRAIN'),*rows[1:]])
    with pytest.raises(ValueError):frozen_rows(scope,[rows[0],*rows[1:-1],rows[0]])

def test_rewritten_committed_sqlite_prefix_is_rejected(world):
    root,old,bundles=world;_,row,cert,new=prefix(world);w=Workspace(new).prepare()
    db=sqlite3.connect(w.target/'Org1/private/local.sqlite');db.execute('UPDATE scores SET probability=0.123');db.commit();db.close()
    with pytest.raises(ValueError):w.verify_recovered_stores()
