"""Read-only readiness checks using narrow anchors and prior independent evidence.
No evaluator, model, workspace, backend or new approval is constructed.
"""
from pathlib import Path
import json,hashlib,subprocess,msvcrt,stat,sys,time
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
OUT=Path(__file__).resolve().parent;PREP=ROOT/'reports/phase6/v4_pilot_preparation_v1'
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def digest(d):return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(name,d):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(d,f,indent=2);f.write('\n')
def census(p):return {q.relative_to(p).as_posix():(q.stat().st_size,q.stat().st_mtime_ns) for q in p.rglob('*') if q.is_file()}
def main():
    assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='a7adf15f0f9b97d062b9e91d784483457bdf67d0'
    assert not subprocess.check_output(['git','diff','--name-only']).strip()
    assert not subprocess.check_output(['git','diff','--cached','--name-only']).strip()
    index=read(PREP/'prepared_artifact_index.json');anchors=[]
    for k,v in index['artifacts'].items():
        assert sha(v['path'])==v['sha256'] and Path(v['path']).stat().st_size==v['bytes'],k
        anchors.append(dict(role=k,**v))
    cert=read(index['artifacts']['predecessor_certificate']['path']);body=cert['body']
    assert digest(body)==cert['certificate_id']==index['certificate_id']
    draftpath=Path(index['artifacts']['NONEXECUTABLE_PILOT_ONLY_grant_DRAFT']['path']);draft=read(draftpath)
    assert draft['status']=='DRAFT_PILOT_ONLY_EXECUTION_NOT_AUTHORIZED' and not draft['explicit_user_decision'] and not draft['execution_authorized']
    variant='CFV1_RA_CS_005_SEED1003_TEST'
    assert draft['authorized_variants']==[variant] and draft['maximum_newly_completed_campaign_instances']==1 and draft['execution_scope']=='PILOT_ONLY'
    assert draft['certificate_id']==cert['certificate_id'] and draft['certificate_file_sha256']==sha(index['artifacts']['predecessor_certificate']['path'])
    assert not Path(draft['output_root']).exists()
    from src.phase6.heldout_contract_v2 import Catalog,Scope as V2Scope,ORGS
    from src.phase6.continuation_contract_v4 import release_identity,ContinuationScope,science,REGISTER,REGISTER_SHA
    catalog=Catalog.permitted_metadata()
    assert release_identity()==index['release_identity']=='4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370'
    assert body['science']==science(catalog) and body['origin']['adapter']==V2Scope.current_adapter_identity()
    assert sha(ROOT/REGISTER)==REGISTER_SHA and draft['register_sha256']==REGISTER_SHA
    assert sha(ROOT/'configs/phase6/split_protocol_v1.json')=='9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b'
    model_checks=[]
    for seal in catalog.seals:
        t=read(ROOT/f'reports/phase6/calibration/v1/thresholds/{seal.organization}_{seal.detector}.json')
        path=Path(t['model_path']).resolve();assert path.is_relative_to(ROOT/'reports/phase6')
        assert sha(path)==t['model_sha256']==json.loads(seal.identity_json)['model_sha256']
        model_checks.append(dict(organization=seal.organization,detector=seal.detector,model_sha256=t['model_sha256'],deserialized=False))
    try:
        scope=ContinuationScope.production(Path(draft['output_root']),catalog,Path(index['artifacts']['predecessor_certificate']['path']),draftpath)
        scope.assert_ready()
    except ValueError as e:
        assert str(e)=='Unapproved/stale v3 execution';rejection=str(e)
    else:raise AssertionError('Draft unexpectedly authorizes execution')
    assert sha(draftpath)==index['artifacts']['NONEXECUTABLE_PILOT_ONLY_grant_DRAFT']['sha256']
    # Reuse the sealed independent preparation findings; do not repeat scientific audits.
    delivery=read(PREP/'delivery_manifest_v1.json')
    reused=['independent_preparation_audit.json','gate4_certificate_and_reuse.json','gate2_preservation.json','post_preparation_preservation.json']
    for name in reused:assert sha(PREP/name)==delivery['files_sha256'][f'reports/phase6/v4_pilot_preparation_v1/{name}']
    old=read(PREP/'independent_preparation_audit.json');assert old['status']=='PASS_PREPARATION_ONLY_INDEPENDENT_RECONCILIATION'
    assert sum(s['last_seq'] for s in body['stores'].values())==1690 and sum(s['score_rows'] for s in body['stores'].values())==15309
    assert len(body['stores'])==5 and old['grid_commits']==40 and old['completed_origins']==5
    baseline=ROOT/'reports/phase6/controlled_interruption_v1/physical_snapshot_manifest.json'
    seal=read(ROOT/'reports/phase6/v2_forensic_v1/SNAPSHOT_SEAL.json');assert sha(baseline)==seal['manifest_sha256']
    m=read(baseline);source=Path(m['source']);snapshot=Path(m['snapshot']);source6=Path(body['source_root'])
    with (source/'execution.lock').open('rb') as handle:
        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        try:
            first=census(source);time.sleep(1);assert census(source)==first
            assert set(first)==set(m['files'])==set(census(snapshot))
            for rel,info in m['files'].items():
                assert first[rel]==(info['size'],info['mtime_ns']),rel
                s=(snapshot/rel).stat();assert s.st_size==info['size'] and not s.st_mode & stat.S_IWRITE,rel
            for name,proof in body['completed_origins'].items():
                assert sha(source/name/'completion.json')==proof['completion_sha256']
                earlier=read(ROOT/'reports/phase6/controlled_interruption_v1/completed_audits'/name/'summary.json')
                assert earlier['status']=='PASS_INDEPENDENT_INSTANCE_AUDIT' and earlier['completion_sha256']==proof['completion_sha256']
            for org in ORGS:
                dbrel=org+'/private/local.sqlite';original=source6/dbrel
                d=body['wal_derivations'][org];assert sha(original)==d['physical_inventory']['']['sha256']
                assert sha(snapshot/variant/dbrel)==sha(original)
                assert sha(Path(body['capture_root'])/org/'derived.sqlite')==d['derived_sha256']
                for suffix,desc in d['physical_inventory'].items():
                    p=Path(str(original)+suffix)
                    if desc is None:assert not p.exists()
                    else:assert p.stat().st_size==desc['size'] and sha(p)==desc['sha256']
                for rel in [org+'/private/grid_progress/'+s['name'] for s in body['journals'][org+'/private/grid_progress']['segments']]:
                    assert sha(source6/rel)==body['files'][rel]['sha256']
            for s in body['journals']['sharing/progress']['segments']:
                assert sha(source6/'sharing/progress'/s['name'])==s['sha256']
            handle.seek(0);assert hashlib.sha256(handle.read()).hexdigest()==m['original_lock_sha256']
        finally:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
    sizes={v:sum(d['size'] for p,d in m['files'].items() if p.startswith(v+'/')) for v in body['completed_origins']}
    restore_bytes=sum(d['size'] for d in body['files'].values())+sum(d['physical_inventory']['']['size'] for d in body['wal_derivations'].values())
    result=dict(status='PASS_NARROW_INTEGRITY_AND_NONEXECUTABLE_AUTHORIZATION_CHECKS',artifacts=anchors,certificate_id=cert['certificate_id'],release_identity=release_identity(),model_checks=model_checks,draft_guard_rejection=rejection,draft_modified=False,execution_authorized=False,pilot_executed=False,GNN_forwards=0,original_SQLite_opens=0,source_lease_available=True,source_stability=True,original_and_forensic_entries_metadata_checked=len(first),full_content_audit_repeated=False,completed_provenances_unchanged=5,committed_commands=1690,committed_local_scores=15309,grid_bundles=40,proposed_variant=variant,maximum_newly_completed_instances=1,output_directory_exists=False,capacity_not_certified=True,reused_audit_files=reused,disk_evidence=dict(original_complete_instance_bytes=sizes,known_partial_restore_payload_bytes=restore_bytes,full_v4_peak_not_measured=True))
    save('integrity_authorization_scope_review.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('artifacts','model_checks','disk_evidence')},indent=2));print(json.dumps(result['disk_evidence'],indent=2))
if __name__=='__main__':
    try:main()
    except BaseException as e:save('STOP_review_failure.json',dict(status='STOP',error_type=type(e).__name__,message=str(e)));raise
