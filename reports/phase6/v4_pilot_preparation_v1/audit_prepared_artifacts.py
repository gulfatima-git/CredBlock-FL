"""Independent preparation evidence checks. Only derived SQLite is queried."""
from pathlib import Path
import json,hashlib,sqlite3,math,subprocess,msvcrt
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
VARIANT='CFV1_RA_CS_005_SEED1003_TEST'
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(d):return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(name,d):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(d,f,indent=2);f.write('\n')
def audit():
    gate=read(OUT/'gate4_certificate_and_reuse.json');denial=read(OUT/'gate5_draft_execution_denial.json')
    path=Path(gate['certificate_path']);cert=read(path);body=cert['body'];cap=Path(body['capture_root']);source=Path(body['source_root'])
    assert sha(path)==gate['certificate_sha256'] and cert['certificate_id']==digest(body)==gate['certificate_id']
    assert body['mode']=='production' and body['kind']=='INSTANCE_CONTINUATION' and body['origin']['variant']==VARIANT
    assert cap.is_relative_to(ROOT/'reports/phase6/heldout_test_v2/wal_v4_captures') and cap.name==VARIANT
    prior=read(ROOT/'reports/phase6/controlled_interruption_v1/incomplete_instance_assessment.json')
    assert len(body['completed_origins'])==5 and all(VARIANT!=v for v in body['completed_origins'])
    all_scores=0;reports=[]
    for p in prior['organizations']:
        org=p['organization'];database=cap/org/'derived.sqlite';m=read(cap/org/'derivation.json')
        assert m==body['wal_derivations'][org]
        assert m['source_SQLite_opens']==0 and m['GNN_forwards']==0 and m['manual_checkpoint'] is False
        assert sha(database)==m['derived_sha256']
        for suffix,info in m['physical_inventory'].items():
            original=source/org/('private/local.sqlite'+suffix)
            if info is None:assert not original.exists()
            else:assert original.stat().st_size==info['size'] and sha(original)==info['sha256']
        # In this production capture every WAL is absent; derived bytes must equal the sealed main bytes.
        assert m['analysis']['wal_bytes']==0 and m['analysis']['last_commit_frame']==0
        assert sha(database)==m['physical_inventory']['']['sha256']
        before=sha(database)
        db=sqlite3.connect(database.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
        try:
            assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
            assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==p['commands']
            assert db.execute('SELECT COUNT(*) FROM event_tokens').fetchone()[0]==p['input_events']
            assert db.execute('SELECT COUNT(*) FROM scores').fetchone()[0]==p['saved_scores']
            assert db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]==0
            assert db.execute('SELECT asof FROM commands ORDER BY seq DESC LIMIT 1').fetchone()[0]==p['last_committed_time']
            cut=read(ROOT/f'reports/phase6/calibration/v1/thresholds/{org}_graphsage.json')
            threshold_hash=sha(ROOT/f'reports/phase6/calibration/v1/thresholds/{org}_graphsage.json')
            count=0
            for value,z,th,decision,model,threshold in db.execute('SELECT logit,logit_hex,threshold_hex,decision,model_sha256,threshold_sha256 FROM scores'):
                logit=float.fromhex(z);assert math.isfinite(logit) and value==logit and th==cut['calibration']['threshold']['hex']
                assert decision==('ALERT' if logit>=float.fromhex(th) else 'NO_ALERT')
                assert model==cut['model_sha256'] and threshold==threshold_hash
                count+=1
        finally:db.close()
        assert sha(database)==before
        all_scores+=count;reports.append(dict(organization=org,status='PASS_DERIVED_BYTES_AND_SAVED_SCORES',commands=p['commands'],saved_scores=count,derived_sha256=before,original_SQLite_opens=0))
    assert all_scores==15309
    # Validate complete hash-chain linkage independently without calling the original parser/evaluator.
    previous='0'*64;seq=0;complete=[];begins=[];grid_commits=0
    for directory,expected in body['journals'].items():
        previous='0'*64;seq=0
        for file in sorted((source/directory).glob('barriers.*.jsonl')):
            for line in file.read_bytes().splitlines(keepends=True):
                assert line.endswith(b'\n');row=json.loads(line);unsigned=dict(row);h=unsigned.pop('sha256')
                assert row['seq']==seq and row['prev']==previous and digest(unsigned)==h and digest(row['body'])==row['body_sha256']
                seq+=1;previous=h;b=row['body']
                if directory=='sharing/progress':
                    if b['event']=='COMPLETE':complete.append(b['at'])
                    if b['event']=='BEGIN':begins.append(b['at'])
                elif b['event']=='GRID_COMMIT':grid_commits+=1
        assert previous==expected['last']
    assert len(complete)==1674 and complete[-1]==prior['sharing']['latest_completed_barrier']
    assert len(begins)==1675 and begins[-1]==prior['sharing']['pending'][0]['at'] and grid_commits==40
    draft=read(denial['draft_path'])
    assert draft['status']=='DRAFT_PILOT_ONLY_EXECUTION_NOT_AUTHORIZED' and draft['explicit_user_decision'] is False and draft['execution_authorized'] is False
    assert draft['execution_scope']=='PILOT_ONLY' and draft['authorized_variants']==[VARIANT] and draft['maximum_newly_completed_campaign_instances']==1
    assert draft['certificate_id']==cert['certificate_id'] and draft['certificate_file_sha256']==sha(path)
    assert draft['required_instances_total']==171 and len(draft['reuse_completed_variants'])==5
    assert not Path(draft['output_root']).exists()
    assert not subprocess.check_output(['git','diff','--name-only']).strip() and not subprocess.check_output(['git','diff','--cached','--name-only']).strip()
    save('independent_preparation_audit.json',dict(status='PASS_PREPARATION_ONLY_INDEPENDENT_RECONCILIATION',certificate_id=cert['certificate_id'],organizations=reports,saved_local_scores=all_scores,grid_commits=grid_commits,completed_barriers=len(complete),pending_barriers=1,completed_origins=5,execution_authorized=False,production_draft_rejected=True,continuation_output_created=False,GNN_forwards=0,source_SQLite_opens=0,limitations=['No actual nonempty production WAL: all five WALs absent','No pilot execution or production runtime measurement','Fresh host/quiescence/resource and identity checks remain mandatory before separately approved execution']))
    print('PASS_INDEPENDENT_PREPARATION_AUDIT_NO_EXECUTION')
def main():
    lock=ROOT/'reports/phase6/heldout_test_v2/final_v1/execution.lock'
    with lock.open('rb') as handle:
        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        try:audit()
        finally:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        save('STOP_independent_preparation_audit_failure.json',dict(status='STOP',error_type=type(e).__name__,message=str(e)));raise
