"""Metadata-only manual grant preparation; never launches an evaluator.

Default/check-only mode writes nothing. Approval requires explicit console input.
Existing research, pilot approval and draft are never modified.
"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import argparse,csv,hashlib,json,msvcrt,subprocess,sys,os
import psutil
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
HERE=Path(__file__).resolve().parent
AUTH=ROOT/'reports/phase6/heldout_test_v2/wal_v4_authorizations'
PILOT=AUTH/'pilot_campaign6_execution_APPROVED_v1.json'
APPROVAL=AUTH/'remaining165_execution_APPROVED_v1.json'
DECISION=HERE/'user_execution_authorization.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def write_new(p,value):
    with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--approve-remaining165',action='store_true')
    args=parser.parse_args();assert not(args.check_only and args.approve_remaining165)
    before=sha(PILOT);pilot=read(PILOT);run=Path(pilot['output_root']);certpath=Path(pilot['certificate_path'])
    assert run==ROOT/'reports/phase6/heldout_test_v2/wal_v4_transition/pilot_campaign6_v1'
    assert not APPROVAL.exists() and not DECISION.exists(),'New grant/decision already exists; stop, do not overwrite or repeat creation.'
    assert not subprocess.check_output(['git','diff','--name-only'],cwd=ROOT).strip(),'Tracked files modified'
    assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=ROOT).strip(),'Staged changes present'
    for p in psutil.process_iter(['pid','cmdline']):
        try:
            cmd=p.info['cmdline'] or []
            assert not any(x in ('src.phase6.continuation_driver_v4','src.phase6.heldout_driver_v2','src.phase6.detectability_batch') for x in cmd),'An evaluator is already running'
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    from src.phase6.heldout_contract_v2 import Catalog
    from src.phase6.continuation_contract_v4 import ContinuationScope,release_identity,release_sources,REGISTER,REGISTER_SHA
    catalog=Catalog.permitted_metadata()
    assert release_identity()==pilot['release_identity']=='4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370'
    assert release_sources()==pilot['source_sha256']
    assert sha(certpath)==pilot['certificate_file_sha256']
    ContinuationScope.production(run,catalog,certpath,PILOT).assert_ready()
    assert sha(ROOT/REGISTER)==REGISTER_SHA==pilot['register_sha256']
    with (ROOT/REGISTER).open(newline='',encoding='utf-8-sig') as f:rows=sorted((r for r in csv.DictReader(f) if r['split']=='TEST'),key=lambda r:r['variant_id'])
    all_ids=[r['variant_id'] for r in rows];assert len(all_ids)==len(set(all_ids))==171
    completions=[]
    for p in sorted((run/'mixed_manifest/progress').glob('barriers.*.jsonl')):
        for line in p.read_bytes().splitlines(keepends=True):
            assert line.endswith(b'\n'),'Incomplete manifest record; stop for review'
            b=json.loads(line)['body']
            if b['event']=='INSTANCE_COMPLETE':completions.append(b)
    completed=[c['variant_id'] for c in completions]
    assert len(completed)==len(set(completed))==6 and set(completed)<=set(all_ids)
    for c in completions:assert sha(Path(c['proof']['directory'])/'completion.json')==c['proof']['completion_sha256']
    assert len(set(all_ids)-set(completed))==165
    assert not (run/'stop_after_current.request.json').exists(),'Boundary pause request exists; do not remove automatically'
    for lock in (ROOT/'reports/phase6/heldout_test_v2/final_v1/execution.lock',run/'execution.lock'):
        assert lock.is_file() and lock.stat().st_size>=1
        with lock.open('rb') as f:
            f.seek(0);h=hashlib.sha256(f.read()).hexdigest();f.seek(0)
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            try:f.seek(0);assert hashlib.sha256(f.read()).hexdigest()==h
            finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    print('PASS: existing release, certificate, production guards, six completion references, frozen 171-entry register and both leases.')
    print(f'Available RAM now: {psutil.virtual_memory().available/2**30:.2f} GiB. No evaluator launched.')
    if not args.approve_remaining165:
        print('CHECK ONLY: no grant or decision record created.');return
    print('\nAuthorize the existing v4 runner to finish ONLY the 165 unfinished instances;')
    print('reuse all six completions without GNN inference, retain frozen science,')
    print('perform final reporting/validation, and stop before Phase 7.')
    answer=input('Type RUN165 to approve creation of the ALL_171 completion grant: ').strip()
    if answer!='RUN165':raise RuntimeError('Authorization not given. No new grant created.')
    decision=dict(status='USER_EXPLICITLY_AUTHORIZED_REMAINING_165_MANUAL_EXECUTION',explicit_user_decision=True,typed_confirmation=answer,at=datetime.now(timezone(timedelta(hours=5))).isoformat(),execution_scope='ALL_171',remaining_instances_to_execute=165,maximum_newly_completed_campaign_instances=165,reuse_only_completed_variants=sorted(completed),repeat_completed_inference=False,phase7_authorized=False,stop_after_remaining_TEST_and_final_validation=True)
    full=dict(pilot);full.update(execution_scope='ALL_171',authorized_variants=all_ids,maximum_newly_completed_campaign_instances=165,reuse_completed_variants=sorted(completed),explicit_user_decision=True,execution_authorized=True,user_decision_record=str(DECISION),user_decision_sha256=hashlib.sha256((json.dumps(decision,indent=2)+'\n').encode()).hexdigest(),approved_at=decision['at'])
    write_new(DECISION,decision);assert sha(DECISION)==full['user_decision_sha256']
    write_new(APPROVAL,full)
    scope=ContinuationScope.production(run,catalog,certpath,APPROVAL);scope.assert_ready()
    assert scope.full_execution_grant and sha(PILOT)==before
    print('PASS: new certificate-bound ALL_171 grant verified; six complete instances remain reuse-only.')
    print('Grant:',APPROVAL)
    print('Grant SHA256:',sha(APPROVAL))
    print('No evaluator has been launched by this helper.')
if __name__=='__main__':
    try:main()
    except Exception as e:print(f'STOP: {type(e).__name__}: {e}',file=sys.stderr);sys.exit(1)
