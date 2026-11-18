"""WAL commit semantics, corruption and capability checks using disposable DBs."""
from pathlib import Path
from types import SimpleNamespace
import json,os,sqlite3,struct,subprocess,sys
import pytest
from src.phase6.heldout_contract_v2 import ROOT
from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope
from src.phase6.continuation_wal_v4 import physical_inventory,project_store,verify_derivation,analyze,checksum,sha,image_signature

WRITER='''import sqlite3,os,sys,json
from pathlib import Path
p=Path(sys.argv[1]);p.parent.mkdir(parents=True)
d=sqlite3.connect(p);d.execute('PRAGMA page_size='+sys.argv[3]);d.execute('PRAGMA journal_mode=WAL');d.execute('PRAGMA synchronous=FULL');d.execute('PRAGMA wal_autocheckpoint=0')
d.execute('CREATE TABLE score(id INTEGER PRIMARY KEY,z REAL,zhex TEXT,cuthex TEXT,flag INTEGER,payload BLOB)');d.commit()
for i,z in enumerate([-.25,1.,float.fromhex('0x1.0000000000001p+0')],1):
 d.execute('INSERT INTO score VALUES(?,?,?,?,?,?)',(i,z,z.hex(),(1.).hex(),z>=1,b'C'*16));d.commit()
if sys.argv[2]=='spill':
 d.execute('PRAGMA cache_size=2');d.execute('BEGIN IMMEDIATE')
 for i in range(4,40):d.execute('INSERT INTO score VALUES(?,?,?,?,?,?)',(i,99.,(99.).hex(),(1.).hex(),1,b'P'*10000))
os._exit(0)
'''

def fixture(root,mode='spill',page=4096):
    source=root/'original/SYNTHETIC_TEST';path=source/'Org1/private/local.sqlite'
    r=subprocess.run([sys.executable,'-B','-c',WRITER,str(path),mode,str(page)],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    (source.parent/'execution.lock').write_bytes(b'\n')
    catalog=SimpleNamespace(fixture_only=True,identity='synthetic-wal-unit')
    permit=CapturePermit.synthetic(source,catalog,root/'capture')
    return path,catalog,permit

@pytest.mark.parametrize('page',[512,4096,65536])
@pytest.mark.parametrize('mode',['committed','spill'])
def test_recovery_committed_exact_uncommitted_excluded(tmp_path,page,mode):
    source,catalog,permit=fixture(tmp_path,mode,page);before=physical_inventory(source)
    dest=permit.derived_root/'Org1/derived.sqlite'
    manifest=project_store(permit,catalog,'Org1',source,dest,before)
    verify_derivation(permit,catalog,'Org1',source,dest,manifest)
    assert manifest['physical_inventory']==before and physical_inventory(source)==before
    assert manifest['logical_signature']['tables']['score']['rows']==3 and manifest['GNN_forwards']==manifest['source_SQLite_opens']==0
    if mode=='spill':assert manifest['analysis']['uncommitted_frames']>0

@pytest.mark.parametrize('bad',['header','frame','salt','partial','rollback'])
def test_uncertain_or_corrupt_sources_require_review(tmp_path,bad):
    source,catalog,permit=fixture(tmp_path);wal=Path(str(source)+'-wal');raw=bytearray(wal.read_bytes())
    if bad=='header':raw[24]^=1
    elif bad=='frame':raw[70]^=1
    elif bad=='salt':raw[40]^=1
    elif bad=='partial':raw=raw[:-17]
    elif bad=='rollback':Path(str(source)+'-journal').write_bytes(b'UNRESOLVED_SYNTHETIC_JOURNAL')
    wal.write_bytes(raw);before=physical_inventory(source)
    with pytest.raises(ValueError):project_store(permit,catalog,'Org1',source,permit.derived_root/'Org1/derived.sqlite',before)
    assert physical_inventory(source)==before and not (permit.derived_root/'Org1/derived.sqlite').exists()

def test_capture_projection_interruption_is_idempotent(tmp_path):
    source,catalog,permit=fixture(tmp_path);before=physical_inventory(source);dest=permit.derived_root/'Org1/derived.sqlite'
    class Crash(Exception):pass
    def fail(stage):
        if stage=='after_derived_publish:Org1':raise Crash()
    with pytest.raises(Crash):project_store(permit,catalog,'Org1',source,dest,before,fail)
    assert dest.exists() and not (dest.parent/'derivation.json').exists()
    result=project_store(permit,catalog,'Org1',source,dest,before)
    assert result['logical_signature']['tables']['score']['rows']==3 and physical_inventory(source)==before

def test_old_grants_cannot_authorize_and_wrong_org_denied(tmp_path,monkeypatch):
    source,catalog,permit=fixture(tmp_path)
    def forbidden(*a,**kw):raise AssertionError('Payload access before authority rejection')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    for org in ('Org2','Org6'):
        with pytest.raises(ValueError):project_store(permit,catalog,org,ROOT/'data2/forbidden.sqlite',tmp_path/'wrong.sqlite',{})
    with pytest.raises(ValueError):ContinuationScope.production(tmp_path,catalog,ROOT/'data2/forbidden',tmp_path/'no_grant')

def test_forged_derived_image_is_rejected(tmp_path):
    source,catalog,permit=fixture(tmp_path);dest=permit.derived_root/'Org1/derived.sqlite';before=physical_inventory(source)
    m=project_store(permit,catalog,'Org1',source,dest,before)
    db=sqlite3.connect(dest);db.execute('UPDATE score SET z=777');db.commit();db.close()
    with pytest.raises(ValueError):verify_derivation(permit,catalog,'Org1',source,dest,m)
    assert physical_inventory(source)==before
