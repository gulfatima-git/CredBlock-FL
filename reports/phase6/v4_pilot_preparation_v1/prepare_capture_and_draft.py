"""Prepare the sole authorized predecessor and a fail-closed execution draft.

Never imports or instantiates the production backend, workspace, driver or model.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import csv,json,hashlib,os,sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
OUT=Path(__file__).resolve().parent
VARIANT='CFV1_RA_CS_005_SEED1003_TEST'
RELEASE='4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370'
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def now():return datetime.now(timezone(timedelta(hours=5))).isoformat()
def main():
    assert read(OUT/'gate2_preservation.json')['status']=='PASS_ALL_ORIGINAL_AND_FORENSIC_HASHES'
    assert read(OUT/'gate3_science_and_model_identities.json')['status']=='PASS_METADATA_REGISTER_AND_10_MODEL_ARCHIVES'
    auth=read(OUT/'user_preparation_authorization.json');assert not auth['execution_authorized'] and auth['variant']==VARIANT
    host=read(OUT/'host_pre_capture_inspection.json');assert host['status']=='PASS_NO_EVALUATOR_IDENTIFIED'
    assert (datetime.now(timezone(timedelta(hours=5)))-datetime.fromisoformat(host['checked_at'])).total_seconds()<300,'Stale fresh process check'
    from src.phase6.heldout_contract_v2 import Catalog,Scope,ORGS,digest
    from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope,release_identity,release_sources,REGISTER,REGISTER_SHA,ORIGINAL_RUN,CAPTURES,AUTHORIZATIONS,NEW_RUNS
    from src.phase6.continuation_reader_v4 import build_certificate
    catalog=Catalog.permitted_metadata();assert release_identity()==RELEASE
    source=ORIGINAL_RUN/VARIANT;capture=CAPTURES/'pilot_preparation_v1'/VARIANT
    future_output=NEW_RUNS/'pilot_campaign6_v1'
    assert not capture.exists() and not future_output.exists(),'Do not reuse outputs'
    # Obtain the exact reviewed read-only lease before issuing the attestation.
    import msvcrt
    lock=ORIGINAL_RUN/'execution.lock';expected=read(ROOT/'reports/phase6/controlled_interruption_v1/physical_snapshot_manifest.json')['original_lock_sha256']
    with lock.open('rb') as f:
        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        try:
            f.seek(0);assert hashlib.sha256(f.read()).hexdigest()==expected
            attestation=dict(status='SOURCE_QUIESCENCE_ATTESTED_FOR_PREPARATION_ONLY',at=now(),source_root=str(source),source_quiescent=True,original_worker_exited=True,original_lease_released=True,read_only_lease_acquired=True,lock_bytes_sha256=expected,lock_written=False,host_inspection=str(OUT/'host_pre_capture_inspection.json'),host_inspection_sha256=sha(OUT/'host_pre_capture_inspection.json'),preservation_gate=str(OUT/'gate2_preservation.json'),preservation_gate_sha256=sha(OUT/'gate2_preservation.json'),execution_authorized=False,requires_fresh_revalidation_before_future_execution=True)
            host_path=AUTHORIZATIONS/'source_quiescence_preparation_v1.json';save(host_path,attestation)
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    capture_path=AUTHORIZATIONS/'capture_preparation_only_v1.json'
    capture_approval=dict(status='USER_APPROVED_QUIESCENT_WAL_V4_CAPTURE',explicit_user_decision=True,authorization_scope='PREPARATION_ONLY_NO_EXECUTION',execution_authorized=False,source_root=str(source),release_identity=RELEASE,catalog_identity=catalog.identity,derived_root=str(capture),host_exit_attestation=str(host_path),host_exit_attestation_sha256=sha(host_path),user_preparation_record=str(OUT/'user_preparation_authorization.json'),user_preparation_record_sha256=sha(OUT/'user_preparation_authorization.json'),authorized_variants=[VARIANT],maximum_newly_completed_campaign_instances=1,other_campaigns_authorized=False)
    save(capture_path,capture_approval)
    permit=CapturePermit.production(source,catalog,capture_path)
    assert sha(ROOT/REGISTER)==REGISTER_SHA
    with (ROOT/REGISTER).open(newline='',encoding='utf-8-sig') as f:rows=sorted([r for r in csv.DictReader(f) if r['split']=='TEST'],key=lambda r:r['variant_id'])
    assert len(rows)==171 and len({r['variant_id'] for r in rows})==171
    row=next(r for r in rows if r['variant_id']==VARIANT)
    print(json.dumps(dict(event='capture_preparation_start',variant=VARIANT,execution_authorized=False)),flush=True)
    certificate_path=capture/'predecessor_certificate.json'
    cert=build_certificate(permit,catalog,row,certificate_path,rows)
    print(json.dumps(dict(event='predecessor_certificate_built',certificate_id=cert['certificate_id'])),flush=True)
    body=cert['body'];prior=read(ROOT/'reports/phase6/controlled_interruption_v1/incomplete_instance_assessment.json')
    expected_completed={r['variant'] for r in read(ROOT/'reports/phase6/controlled_interruption_v1/recovery_assessment_summary.json')['completed']}
    assert len(expected_completed)==5 and set(body['completed_origins'])==expected_completed
    for variant,proof in body['completed_origins'].items():
        previous=read(ROOT/'reports/phase6/controlled_interruption_v1/completed_audits'/variant/'summary.json')
        assert previous['status']=='PASS_INDEPENDENT_INSTANCE_AUDIT' and proof['completion_sha256']==previous['completion_sha256'],'Changed original completed provenance'
    assert body['kind']=='INSTANCE_CONTINUATION' and set(body['stores'])==set(ORGS)
    assert body['journals']['sharing/progress']['last']==prior['sharing']['journal_chain_sha256'],'Changed sharing chain'
    for p in prior['organizations']:
        s=body['stores'][p['organization']]
        assert (s['last_seq'],s['event_offset'],s['checkpoint_seq'],s['score_rows'],s['clock'])==(p['commands'],p['input_events'],p['latest_checkpoint_seq'],p['saved_scores'],p['last_committed_time']),p['organization']
        assert s['failure_max_id']==0,'Original failure state requires review'
    assert sum(s['score_rows'] for s in body['stores'].values())==15309
    assert not (source/'completion.json').exists()
    save(OUT/'gate4_certificate_and_reuse.json',dict(status='PASS_PREDECESSOR_CERTIFICATE_AND_PRIOR_BOUNDARY_MATCH',certificate_path=str(certificate_path),certificate_sha256=sha(certificate_path),certificate_id=cert['certificate_id'],completed_origins=body['completed_origins'],stores=body['stores'],journal_chains={p:v['last'] for p,v in body['journals'].items()},GNN_forwards=0,execution_authorized=False))
    # Deliberately NOT the executable USER_APPROVED_* status. No later approval is inferred.
    draft=dict(status='DRAFT_PILOT_ONLY_EXECUTION_NOT_AUTHORIZED',explicit_user_decision=False,execution_authorized=False,requires_separate_explicit_execution_approval=True,execution_scope='PILOT_ONLY',authorized_variants=[VARIANT],maximum_newly_completed_campaign_instances=1,required_instances_total=171,release_identity=RELEASE,source_sha256=release_sources(),catalog_identity=catalog.identity,register_sha256=REGISTER_SHA,output_root=str(future_output),certificate_id=cert['certificate_id'],certificate_path=str(certificate_path),certificate_file_sha256=sha(certificate_path),reuse_completed_variants=sorted(expected_completed),repeat_committed_GNN_inference=False,phase7_authorized=False,preparation_authority_sha256=sha(OUT/'user_preparation_authorization.json'))
    draft_path=AUTHORIZATIONS/'pilot_campaign6_execution_DRAFT_v1.json';save(draft_path,draft)
    rejected=False;message=None
    try:
        scope=ContinuationScope.production(future_output,catalog,certificate_path,draft_path)
        scope.assert_ready()
    except ValueError as e:
        message=str(e);assert message=='Unapproved/stale v3 execution',message;rejected=True
    assert rejected,'CRITICAL: preparation draft passed execution guard'
    assert not future_output.exists(),'No continuation workspace may be created'
    save(OUT/'gate5_draft_execution_denial.json',dict(status='PASS_DRAFT_REJECTED_BY_UNCHANGED_PRODUCTION_GUARD',draft_path=str(draft_path),draft_sha256=sha(draft_path),guard_message=message,execution_authorized=False,continuation_output_created=False,GNN_forwards=0,authorized_variants=[VARIANT],maximum_newly_completed_campaign_instances=1))
    print(json.dumps(dict(status='PASS_PREPARATION_ONLY_CERTIFICATE_AND_NONEXECUTABLE_DRAFT',certificate_id=cert['certificate_id'],GNN_forwards=0,execution_authorized=False)),flush=True)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        save(OUT/'STOP_capture_preparation_failure.json',dict(status='STOP',error_type=type(e).__name__,message=str(e),execution_authorized=False));raise
