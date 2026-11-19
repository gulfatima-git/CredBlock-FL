"""Preparation-only read-only evidence gate. No SQLite or model execution."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json, hashlib, msvcrt, os, stat, time, sys
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def save(name,value):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def now():return datetime.now(timezone(timedelta(hours=5))).isoformat()
def census(base):
    result={}
    for p in base.rglob('*'):
        assert not p.is_symlink() and not getattr(p,'is_junction',lambda:False)(),str(p)
        if p.is_file():
            s=p.stat();result[p.relative_to(base).as_posix()]=(s.st_size,s.st_mtime_ns)
    return result
def main():
    host=read(OUT/'host_process_inspection.json')
    assert host['status']=='PASS_NO_EVALUATOR_IDENTIFIED'
    assert (datetime.now(timezone(timedelta(hours=5)))-datetime.fromisoformat(host['checked_at'])).total_seconds()<900,'Stale host inspection'
    python=[p for p in host['processes'] if p['Name'].lower().startswith('python')]
    assert all('autopep8' in p['CommandLine'] and 'lsp_server.py' in p['CommandLine'] for p in python),'Unclassified Python process'
    baseline=ROOT/'reports/phase6/controlled_interruption_v1/physical_snapshot_manifest.json'
    seal=read(ROOT/'reports/phase6/v2_forensic_v1/SNAPSHOT_SEAL.json')
    assert sha(baseline)==seal['manifest_sha256']
    m=read(baseline);source=Path(m['source']);snapshot=Path(m['snapshot']);lock=source/'execution.lock'
    with lock.open('rb') as f:
        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        try:
            first=census(source);time.sleep(1);assert census(source)==first,'Source not stable'
            assert set(first)==set(m['files'])==set(census(snapshot)),'Original/forensic inventory changed'
            save('gate2_quiescence.json',dict(status='PASS_READONLY_LEASE_AND_STABILITY',at=now(),original_worker_exited=True,original_lease_released=True,source_quiescent=True,source_root=str(source/'CFV1_RA_CS_005_SEED1003_TEST'),source_files=len(first),lock_written=False))
            for n,(rel,d) in enumerate(m['files'].items(),1):
                if rel=='execution.lock':f.seek(0);actual=hashlib.sha256(f.read()).hexdigest()
                else:actual=sha(source/rel)
                assert actual==d['sha256']==sha(snapshot/rel),'Original/forensic bytes differ: '+rel
                assert first[rel]==(d['size'],d['mtime_ns']),'Original metadata changed: '+rel
                assert not (snapshot/rel).stat().st_mode & stat.S_IWRITE,'Snapshot no longer read-only'
                if n%10000==0:print(json.dumps(dict(event='preservation_hashes_verified',files=n,total=len(first))),flush=True)
            assert census(source)==first,'Original state changed during verification'
            save('gate2_preservation.json',dict(status='PASS_ALL_ORIGINAL_AND_FORENSIC_HASHES',files=len(first),database_sets=len(m['database_sets']),nonempty_WAL=sum(bool(s['wal'] and s['wal']['size']) for s in m['database_sets']),original_SQLite_opens=0,source_files_modified=False,forensic_files_modified=False,at=now()))
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    from src.phase6.heldout_contract_v2 import Catalog
    from src.phase6.continuation_contract_v4 import release_identity,REGISTER,REGISTER_SHA
    catalog=Catalog.permitted_metadata()
    assert catalog.identity=='2d0846a880bed6938bde419a507cb7c5da8f3e1a136ddeab2b212ce978b09680'
    assert release_identity()=='4759df8a2b488c7cfd9395eba1914847e77a1323db1a33fd4e9a290dcf12a370'
    assert sha(ROOT/REGISTER)==REGISTER_SHA
    pairs=[]
    for s in catalog.seals:
        t=read(ROOT/f'reports/phase6/calibration/v1/thresholds/{s.organization}_{s.detector}.json')
        model=Path(t['model_path']).resolve();assert model.is_relative_to(ROOT/'reports/phase6')
        assert sha(model)==t['model_sha256']==json.loads(s.identity_json)['model_sha256']
        pairs.append(dict(organization=s.organization,detector=s.detector,model_sha256=t['model_sha256'],model_deserialized=False))
    save('gate3_science_and_model_identities.json',dict(status='PASS_METADATA_REGISTER_AND_10_MODEL_ARCHIVES',catalog_identity=catalog.identity,release_identity=release_identity(),register_sha256=REGISTER_SHA,bundles=pairs,GNN_forwards=0))
    print(json.dumps(dict(status='PASS_PRE_CAPTURE_GATES_2_3',files=len(first),model_archives=len(pairs),GNN_forwards=0)),flush=True)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        save('STOP_preservation_gate_failure.json',dict(status='STOP',error_type=type(e).__name__,message=str(e),execution_performed=False));raise
