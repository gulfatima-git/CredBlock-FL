"""Five-organization WAL continuation; synthetic sources and RAM models only."""
from pathlib import Path
from types import SimpleNamespace
import ast,json,hashlib,shutil,sqlite3,subprocess,sys,time
import pytest
from wal_fixture_worker_v4 import make_world,Backend
from src.phase6.heldout_contract_v2 import ROOT,ORGS,Scope as V2Scope,canonical,digest
from src.phase6.heldout_driver_v2 import Driver as V2Driver
from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope,release_identity
from src.phase6.continuation_reader_v4 import build_certificate,PredecessorReader,sha
from src.phase6.continuation_driver_v4 import Driver as V4Driver,run_lease
from src.phase6.continuation_recovery_v4 import Workspace,inspect_store
from src.phase6.continuation_wal_v4 import analyze,physical_inventory,project_store,sql_digest

def science(path):
    r=json.loads((path/'public_results.json').read_bytes())
    return {k:r[k] for k in ('fixed_grid','campaign_results','organization_results','operational_decision_rows','independent_sharing')}

def physical_files(root):return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}

def crashed(tmp,stage,version='v2',cert=None):
    assert 'wal_v4' in str(tmp).lower()
    args=[sys.executable,'-B',str(ROOT/'tests/phase6/wal_fixture_worker_v4.py'),str(tmp),stage,version]
    if cert:args.append(str(cert))
    r=subprocess.run(args,capture_output=True,text=True,timeout=180)
    assert r.returncode==73,r.stdout+r.stderr
    return json.loads((tmp/'child_exit.json').read_text())

@pytest.fixture(scope='module')
def reference(tmp_path_factory):
    root=tmp_path_factory.mktemp('wal_v4_reference');_,old,bundles=make_world(root/'meta')
    backend=Backend(old,bundles);row=backend.inventory()[0];start=time.perf_counter();V2Driver(old,backend).run_instance(row)
    return root,old.catalog,row,old.output_root/row['variant_id'],sum(b.model.calls for b in bundles.values()),time.perf_counter()-start

STAGES=['after_begin']+['after_local:'+o for o in ORGS]+['after_local_record:'+o for o in ORGS]+[
    'after_issuance:Org1','after_receipt:Org2','after_network_memory','after_publication_prepared','after_published',
    'after_paired:Org1','before_complete','after_complete','after_expiry',
    'after_grid_commit:Org1:graphsage','after_grid_commit:Org5:tabular_mlp','after_grid_file:Org2:tabular_mlp',
    'after_score_seal','after_labels','before_instance_complete','after_instance_complete']

@pytest.mark.parametrize('stage',STAGES)
def test_five_org_crash_recovery_no_repeated_committed_inference(tmp_path,reference,stage):
    _,catalog,row,ref,reference_calls,_=reference
    root=tmp_path/'wal_v4_case';exit=crashed(root,stage);source=Path(exit['source']);original=physical_files(source)
    _,old,bundles=make_world(root/'parent_metadata');assert old.catalog==catalog
    permit=CapturePermit.synthetic(source,catalog);certpath=root/'certificate_v4.json'
    cert=build_certificate(permit,catalog,row,certpath)
    assert cert['format']=='phase6-continuation-wal-certificate-v4' and set(cert['body']['wal_derivations'])==set(ORGS)
    assert any(m['physical_inventory']['-wal'] and m['physical_inventory']['-wal']['size'] for m in cert['body']['wal_derivations'].values())
    new=ContinuationScope.synthetic(root/'continued',catalog,certpath)
    start=time.perf_counter();result=V4Driver(new,Backend(new,bundles)).run_instance(row);elapsed=time.perf_counter()-start
    target=new.output_root/row['variant_id']
    if (source/'completion.json').exists():target=source
    assert science(target)==science(ref)
    for org in ORGS:
        for name in ('eligible_graphsage.json','eligible_tabular_mlp.json','campaign_user_results.json','alert_attribution.json'):
            assert json.loads((target/org/'private'/name).read_bytes())==json.loads((ref/org/'private'/name).read_bytes())
    assert exit['model_calls']+sum(b.model.calls for b in bundles.values())==reference_calls
    assert original==physical_files(source)
    with run_lease(new.output_root):
        workspace=Workspace(new);workspace.prepare();workspace.verify_prefix();workspace.verify_recovered_stores()
    # Completion coverage includes all six grid times and final operational flush.
    seal=json.loads((target/'score_seal.json').read_bytes());assert len(seal['branches'])==5 and len(seal['raw_score_digests'])==60
    with (root/'case_evidence.json').open('x') as f:json.dump(dict(stage=stage,status='PASS',organizations=5,reference_model_calls=reference_calls,predecessor_model_calls=exit['model_calls'],continuation_model_calls=sum(b.model.calls for b in bundles.values()),extra_committed_model_calls=0,continuation_seconds=elapsed,physical_files=len(original),certificate_id=cert['certificate_id']),f,indent=2)

def test_version_and_access_denial_before_payload_reads(tmp_path,monkeypatch):
    from src.phase6.continuation_contract_v3 import ContinuationScope as Old
    _,old,bundles=make_world(tmp_path/'wal_v4_metadata')
    def denied(*a,**kw):raise AssertionError('Forbidden payload read')
    monkeypatch.setattr(Path,'read_bytes',denied)
    # No approval path exists: constructor must reject before opening certificate.
    with pytest.raises(ValueError):ContinuationScope.production(tmp_path,old.catalog,ROOT/'data2/forbidden',tmp_path/'missing_approval.json')
    with pytest.raises(ValueError):project_store(object(),old.catalog,'Org1',ROOT/'data2/forbidden',tmp_path/'derived.sqlite',{})

def test_wal_corruption_and_old_guard_remain_blocking(tmp_path):
    root=tmp_path/'wal_v4_negative';exit=crashed(root,'after_local:Org3');source=Path(exit['source'])
    _,old,bundles=make_world(root/'metadata_parent');row=Backend(old,bundles).inventory()[0]
    from src.phase6.continuation_contract_v3 import CapturePermit as OldPermit
    from src.phase6.continuation_reader_v3 import build_certificate as OldBuild
    with pytest.raises(ValueError,match='Nonempty WAL'):OldBuild(OldPermit.synthetic(source,old.catalog),old.catalog,row,root/'old_certificate.json')
    wal=source/'Org1/private/local.sqlite-wal';raw=bytearray(wal.read_bytes());raw[24]^=1
    # Modify a separate synthetic negative source, never the positive predecessor.
    bad=root/'bad_run'/source.name;shutil.copytree(source,bad);(bad/'Org1/private/local.sqlite-wal').write_bytes(raw)
    (bad.parent/'execution.lock').write_bytes(b'\n')
    with pytest.raises(ValueError,match='checksum'):build_certificate(CapturePermit.synthetic(bad,old.catalog),old.catalog,row,root/'bad_certificate.json')

def test_workspace_copy_interruption_restarts_exactly(tmp_path,reference):
    _,catalog,row,ref,calls,_=reference;root=tmp_path/'wal_v4_copy';exit=crashed(root,'after_local:Org3');source=Path(exit['source']);before=physical_files(source)
    _,old,bundles=make_world(root/'parent');p=root/'cert.json';build_certificate(CapturePermit.synthetic(source,catalog),catalog,row,p)
    new=ContinuationScope.synthetic(root/'new',catalog,p)
    class Interrupted(Exception):pass
    def fail(stage):
        if stage=='after_restore_database:Org3':raise Interrupted()
    with pytest.raises(Interrupted):V4Driver(new,Backend(new,bundles)).run_instance(row,fail)
    V4Driver(new,Backend(new,bundles)).run_instance(row)
    assert science(new.output_root/row['variant_id'])==science(ref) and before==physical_files(source)
    assert sum(b.model.calls for b in bundles.values())+exit['model_calls']==calls
