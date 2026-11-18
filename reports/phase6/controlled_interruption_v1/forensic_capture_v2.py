"""Append-only completion of failed capture; owner-handle lock reads only."""
from pathlib import Path
from datetime import datetime
import hashlib,json,os,shutil,stat,time,msvcrt
from forensic_capture import ROOT,SOURCE,DEST,REPORT,census,sha

def save(name,value):
    with (REPORT/name).open('x') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def main():
    need=json.loads((REPORT/'capture_failure_diagnosis.json').read_text())
    assert need['missing_copies']==['execution.lock','required_inventory.json'] and need['synthetic_owner_read_succeeds'] and need['synthetic_secondary_handle_denied']
    exitcheck=json.loads((REPORT/'pre_capture_v2_exit_check.json').read_text());assert exitcheck['matching_evaluators']==[]
    assert not (REPORT/'physical_snapshot_manifest.json').exists() and not (DEST/'SNAPSHOT_SEAL.json').exists()
    physical=DEST/'physical';lock=SOURCE/'execution.lock';initial_lock=sha(lock);handle=lock.open('rb');held=False
    def source_sha(path):
        if path!=lock:return sha(path)
        handle.seek(0);h=hashlib.sha256()
        for b in iter(lambda:handle.read(1024*1024),b''):h.update(b)
        return h.hexdigest()
    try:
        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);held=True
        first=census();time.sleep(2);assert census()==first,'Filesystem stability failed'
        records={};reused=created=0
        for n,(rel,desc) in enumerate(first.items(),1):
            source=SOURCE/rel;target=physical/rel;before=source_sha(source)
            if target.exists():assert sha(target)==before,'Previously copied evidence differs: '+rel;reused+=1
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as out:
                    if source==lock:
                        handle.seek(0);shutil.copyfileobj(handle,out,1024*1024)
                    else:
                        with source.open('rb') as src:shutil.copyfileobj(src,out,1024*1024)
                    out.flush();os.fsync(out.fileno())
                os.chmod(target,stat.S_IREAD);created+=1
            assert source_sha(source)==before==sha(target),'Source/copy preservation failed: '+rel
            assert source.stat().st_size==desc['size'] and source.stat().st_mtime_ns==desc['mtime_ns'],'Source metadata changed'
            records[rel]=dict(**desc,sha256=before,snapshot_read_only=True)
            if n%10000==0:print(json.dumps(dict(event='snapshot_reverification',files=n,total=len(first))),flush=True)
        assert census()==first,'Source file census changed'
        for rel,desc in records.items():assert source_sha(SOURCE/rel)==desc['sha256']==sha(physical/rel),'Final full-byte pass differs: '+rel
        assert source_sha(lock)==initial_lock,'Original lock bytes changed'
        snapshots={p.relative_to(physical).as_posix() for p in physical.rglob('*') if p.is_file()};assert snapshots==set(records)
        sets=[dict(database=rel,wal=records.get(rel+'-wal'),shm=records.get(rel+'-shm'),rollback=records.get(rel+'-journal')) for rel in records if rel.endswith('.sqlite')]
        manifest=dict(status='PASS_PHYSICAL_SNAPSHOT_HASH_PRESERVATION',capture_version=2,source=str(SOURCE),snapshot=str(physical),at=datetime.now().astimezone().isoformat(),files=records,database_sets=sets,total_bytes=sum(r['size'] for r in records.values()),reused_readonly_files=reused,newly_copied_files=created,lock_owner_handle_read=True,original_lock_sha256=initial_lock,no_original_SQLite_opens=True,immutability='Exclusive creation, read-only files, SHA256 seal; not hardware WORM',failed_attempt_preserved=True)
        save('physical_snapshot_manifest.json',manifest)
        with (DEST/'SNAPSHOT_SEAL.json').open('x') as f:json.dump(dict(status=manifest['status'],capture_version=2,manifest=str(REPORT/'physical_snapshot_manifest.json'),manifest_sha256=sha(REPORT/'physical_snapshot_manifest.json'),files=len(records)),f,indent=2);f.flush();os.fsync(f.fileno())
        save('lease_verification_v2.json',dict(status='PASS_READ_ONLY_LEASE_AND_LOCK_PRESERVATION',original_lock_sha256=initial_lock,owner_handle_read=True,lock_written=False))
        print(json.dumps(dict(status=manifest['status'],files=len(records),database_sets=len(sets),nonempty_WAL=sum(bool(s['wal'] and s['wal']['size']) for s in sets),reused=reused,new=created)),flush=True)
    finally:
        if held:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        handle.close()
if __name__=='__main__':
    try:main()
    except BaseException as e:
        save('capture_v2_failure_'+datetime.now().strftime('%H%M%S%f')+'.json',dict(status='STOP',type=type(e).__name__,message=str(e)))
        raise
