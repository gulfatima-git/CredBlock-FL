"""Post-exit byte-only capture. Original lock is read-only; no SQLite opens."""
from pathlib import Path
from datetime import datetime
import hashlib,json,os,shutil,stat,time
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL')
SOURCE=ROOT/'reports/phase6/heldout_test_v2/final_v1'
DEST=ROOT/'reports/phase6/v2_forensic_v1'
REPORT=Path(__file__).resolve().parent

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def save(name,value):
    with (REPORT/name).open('x',encoding='utf8') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def census():
    result={}
    for p in sorted(SOURCE.rglob('*')):
        if p.is_symlink() or getattr(p,'is_junction',lambda:False)():raise ValueError('Unexpected linked evidence: '+str(p))
        if p.is_file():
            s=p.stat();result[p.relative_to(SOURCE).as_posix()]=dict(size=s.st_size,mtime_ns=s.st_mtime_ns)
    return result
def main():
    assert not DEST.exists(),'Never overwrite a prior snapshot'
    exits=json.loads((REPORT/'independent_exit_check.json').read_text());assert exits['matching_evaluators']==[] and exits['historical_processes']==[]
    observation=json.loads((REPORT/'process_exit_observations.json').read_text());assert observation['status']=='WORKER_AND_LAUNCHER_EXIT_OBSERVED'
    lock=SOURCE/'execution.lock';before=sha(lock);handle=lock.open('rb');acquired=False
    try:
        import msvcrt
        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);acquired=True
        save('lease_verification.json',dict(status='PASS_ORIGINAL_READ_ONLY_LEASE_ACQUIRED',at=datetime.now().astimezone().isoformat(),lock=str(lock),sha256_before=before,no_lock_write=True))
        first=census();time.sleep(2);second=census();assert first==second,'Source filesystem not stable'
        size=sum(r['size'] for r in first.values());free=shutil.disk_usage(ROOT).free
        save('quiescence_and_space.json',dict(status='PASS_METADATA_STABILITY_UNDER_LEASE',files=len(first),bytes=size,free_bytes=free,stable_samples=2))
        assert free>size*3+1024**3,'Insufficient free space for preservation and verification copies'
        physical=DEST/'physical';physical.mkdir(parents=True,exist_ok=False)
        records={};total=len(first)
        for n,(rel,desc) in enumerate(first.items(),1):
            source=SOURCE/rel;target=physical/rel;target.parent.mkdir(parents=True,exist_ok=True)
            initial=sha(source)
            with source.open('rb') as src,target.open('xb') as dst:
                shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
            copied=sha(target);final=sha(source)
            assert initial==copied==final,'Physical copy hash failure: '+rel
            assert source.stat().st_size==desc['size'] and source.stat().st_mtime_ns==desc['mtime_ns'],'Source changed during capture: '+rel
            os.chmod(target,stat.S_IREAD) # snapshot only; originals never chmodded
            records[rel]=dict(**desc,sha256=initial,snapshot_read_only=True)
            if n%2000==0:print(json.dumps(dict(event='forensic_copy_progress',files=n,total=total)),flush=True)
        assert census()==first,'Original file census changed during capture'
        # Full final byte pass is independent of the per-file copy checks.
        for rel,desc in records.items():assert sha(SOURCE/rel)==desc['sha256']==sha(physical/rel),'Final preservation verification failed: '+rel
        assert sha(lock)==before,'Original lock bytes changed'
        inventory=[]
        for rel in records:
            if rel.endswith('.sqlite'):
                inventory.append(dict(database=rel,wal=records.get(rel+'-wal'),shm=records.get(rel+'-shm'),rollback=records.get(rel+'-journal')))
        manifest=dict(status='PASS_PHYSICAL_SNAPSHOT_HASH_PRESERVATION',at=datetime.now().astimezone().isoformat(),source=str(SOURCE),snapshot=str(physical),files=records,database_sets=inventory,total_bytes=size,immutability='Exclusive creation, read-only copied files, hash seal; not hardware WORM',no_original_SQLite_opens=True)
        save('physical_snapshot_manifest.json',manifest)
        with (DEST/'SNAPSHOT_SEAL.json').open('x') as f:json.dump(dict(status=manifest['status'],manifest=str(REPORT/'physical_snapshot_manifest.json'),manifest_sha256=sha(REPORT/'physical_snapshot_manifest.json'),files=total,bytes=size),f,indent=2);f.flush();os.fsync(f.fileno())
        print(json.dumps(dict(status=manifest['status'],files=total,bytes=size,database_sets=len(inventory),nonempty_WAL=sum(bool(x['wal'] and x['wal']['size']) for x in inventory))),flush=True)
    finally:
        if acquired:
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        handle.close()
if __name__=='__main__':
    try:main()
    except BaseException as e:
        save('capture_failure_'+datetime.now().strftime('%H%M%S%f')+'.json',dict(status='STOP',error_type=type(e).__name__,message=str(e),no_automatic_retry=True))
        raise
