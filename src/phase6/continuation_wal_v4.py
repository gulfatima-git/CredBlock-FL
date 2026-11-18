"""WAL projection and independent SQLite reconciliation. No source SQLite opens."""
from pathlib import Path
import hashlib,json,os,sqlite3,uuid,time
from src.phase6.temporal_protocol import require
from src.phase6.heldout_contract_v2 import ROOT,ORGS,canonical,digest
from src.phase6.heldout_barrier_v2 import write_once
import struct

def checksum(data,endian,state=(0,0)):
    require(len(data)%8==0,'Invalid checksum input size')
    a,b=state
    for x,y in struct.iter_unpack(endian+'II',data):
        a=(a+x+b)&0xffffffff;b=(b+y+a)&0xffffffff
    return a,b

def analyze(base,wal):
    require(len(base)>=100 and base[:16]==b'SQLite format 3\0','Invalid main database header')
    page=struct.unpack('>H',base[16:18])[0];page=65536 if page==1 else page
    require(512<=page<=65536 and page&(page-1)==0 and len(base)%page==0,'Invalid main page size/length')
    result=dict(page_size=page,wal_present=wal is not None,wal_bytes=len(wal or b''),valid_frames=0,
                commit_frames=[],last_commit_frame=0,db_pages=len(base)//page,uncommitted_frames=0,
                partial_tail_bytes=0,tail_classification='NONE')
    if not wal:return result,base
    require(len(wal)>=32,'Incomplete WAL header requires investigation')
    magic,version,wpage,sequence,salt1,salt2,c1,c2=struct.unpack('>8I',wal[:32])
    require(magic in (0x377f0682,0x377f0683) and version==3007000,'Unsupported WAL header')
    require(wpage==page,'WAL/main page-size mismatch')
    endian='<' if magic==0x377f0682 else '>'
    state=checksum(wal[:24],endian);require(state==(c1,c2),'WAL header checksum failure')
    result.update(checksum_endian=endian,checkpoint_sequence=sequence,salts=[salt1,salt2])
    frames=[];stride=24+page;full=(len(wal)-32)//stride
    for i in range(full):
        off=32+i*stride;header=wal[off:off+24];data=wal[off+24:off+stride]
        pg,dbsize,s1,s2,a,b=struct.unpack('>6I',header)
        require((s1,s2)==(salt1,salt2),'Salt-mismatched/stale-or-corrupt suffix requires investigation; no automatic recovery')
        require(pg>0,'Invalid WAL page number')
        state=checksum(header[:8]+data,endian,state)
        require(state==(a,b),'WAL frame checksum failure requires investigation')
        frames.append((pg,data));result['valid_frames']+=1
        if dbsize:
            require(dbsize<=0xfffffffe,'Invalid commit database size')
            result['commit_frames'].append(i+1);result['last_commit_frame']=i+1;result['db_pages']=dbsize
    result['partial_tail_bytes']=(len(wal)-32)%stride
    result['uncommitted_frames']=len(frames)-result['last_commit_frame']
    if result['partial_tail_bytes']:result['tail_classification']='PARTIAL_APPEND_REQUIRES_LEDGER_RECONCILIATION'
    elif result['uncommitted_frames']:result['tail_classification']='VALID_UNCOMMITTED_FRAMES'
    if not result['last_commit_frame']:return result,base
    latest={pg:data for pg,data in frames[:result['last_commit_frame']]}
    count=result['db_pages']
    # Do not allocate an attacker-controlled sparse database or invent missing pages.
    require(count<=len(base)//page+len(latest),'Missing pages in committed view')
    output=bytearray()
    for pg in range(1,count+1):
        value=latest.get(pg,base[(pg-1)*page:pg*page])
        require(len(value)==page,'Missing committed database page')
        output.extend(value)
    return result,bytes(output)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def physical_inventory(path):
    return {s:dict(size=p.stat().st_size,sha256=sha(p)) if p.exists() else None
            for s in ('','-wal','-shm','-journal') for p in [Path(str(path)+s)]}

def _authorize(authority,catalog,org,source,destination):
    from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope,relative_path
    from src.phase6.continuation_lease_v4 import working_is_held
    require(org in ORGS,'Unknown organization')
    source=Path(source).resolve();destination=Path(destination).resolve()
    if type(authority) is CapturePermit:
        authority.validate(catalog)
        require(source==relative_path(authority.source,org+'/private/local.sqlite'),'Capture source database mismatch')
        require(destination==relative_path(authority.derived_root,org+'/derived.sqlite'),'Capture projection path mismatch')
    else:
        require(type(authority) is ContinuationScope,'WAL projection requires versioned authority');authority.assert_ready()
        require(working_is_held(authority.output_root),'Working database projection requires exclusive run lease')
        require(source.is_relative_to(authority.output_root) and source.parts[-3:]==(org,'private','local.sqlite'),'Unapproved working database')
        variant=source.parent.parent.parent.name;authority.check_variant(variant,org)
        review=authority.output_root/'wal_working_reviews'
        require(destination.is_relative_to(review) and destination.name=='derived.sqlite','Unapproved working projection destination')
        relative_path(authority.output_root,destination.relative_to(authority.output_root).as_posix())
    require(not destination.is_relative_to(source.parent) and not source.is_relative_to(destination.parent),'Projection overlaps physical database')
    return source,destination

def _publish(path,raw):
    path=Path(path)
    if path.exists():require(sha(path)==hashlib.sha256(raw).hexdigest(),'Derived artifact collision');return
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name('.w.'+uuid.uuid4().hex[:16])
    with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    if os.name=='nt':os.rename(temp,path)
    else:os.link(temp,path)

def sql_digest(db):
    def typed(v):
        if v is None:return ['null']
        if isinstance(v,bytes):return ['blob',v.hex()]
        if isinstance(v,float):return ['float',v.hex()]
        return [type(v).__name__,v]
    schema=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    values={}
    for kind,name,table,sql in schema:
        if kind!='table':continue
        quoted='"'+name.replace('"','""')+'"'
        rows=sorted(canonical([typed(v) for v in row]) for row in db.execute('SELECT * FROM '+quoted))
        values[name]=dict(rows=len(rows),sha256=hashlib.sha256(('\n'.join(rows)+'\n').encode()).hexdigest())
    return dict(schema_sha256=digest(schema),tables=values)

def image_signature(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        require(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Derived SQLite integrity failure')
        return sql_digest(db)
    finally:db.close()

def project_store(authority,catalog,org,source,destination,expected,fail=lambda stage:None):
    """Called under predecessor/working lease; originals only read as bytes."""
    from src.phase6.continuation_lease_v4 import predecessor_lease
    source,destination=_authorize(authority,catalog,org,source,destination)
    with predecessor_lease(authority,catalog):
        require(physical_inventory(source)==expected,'Physical source inventory differs')
        require(expected['-journal'] is None or expected['-journal']['size']==0,'Rollback journal requires explicit review')
        blobs={s:Path(str(source)+s).read_bytes() for s,d in expected.items() if d is not None}
        analysis,raw=analyze(blobs[''],blobs.get('-wal'))
        require(analysis['partial_tail_bytes']==0,'Partial WAL append requires explicit completeness review')
        require(physical_inventory(source)==expected,'Source changed while reading WAL')
        fail('after_wal_analysis:'+org)
        _publish(destination,raw);fail('after_derived_publish:'+org)
        logical=image_signature(destination)
        # Independent SQLite engine on a disposable third copy. It may update
        # only its own auxiliary index. No source connection/checkpoint occurs.
        oracle=destination.parent/('o_'+uuid.uuid4().hex[:16]);oracle.mkdir()
        for suffix,value in blobs.items():_publish(oracle/('local.sqlite'+suffix),value)
        oracle_db=oracle/'local.sqlite'
        db=sqlite3.connect(oracle_db.as_uri()+'?mode=ro',uri=True)
        try:
            require(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Independent WAL-view integrity failure')
            independent=sql_digest(db)
        finally:db.close()
        require(independent==logical,'WAL projection differs from independent SQLite committed view')
        require(sha(oracle_db)==expected['']['sha256'] and
                (expected['-wal'] is None or sha(Path(str(oracle_db)+'-wal'))==expected['-wal']['sha256']),
                'Independent oracle altered physical main/WAL copy')
        require(physical_inventory(source)==expected,'Original database/sidecars changed during derivation')
        manifest=dict(format='phase6-wal-derivation-v4',organization=org,source=str(source),
            physical_inventory=expected,analysis=analysis,derived_sha256=hashlib.sha256(raw).hexdigest(),
            logical_signature=logical,independent_sqlite_signature=independent,sqlite_version=sqlite3.sqlite_version,
            manual_checkpoint=False,source_SQLite_opens=0,GNN_forwards=0)
        write_once(destination.parent/'derivation.json',manifest);fail('after_derivation_seal:'+org)
        return manifest

def verify_derivation(authority,catalog,org,source,destination,manifest):
    source,destination=_authorize_capture_read(authority,catalog,org,source,destination)
    require(manifest['format']=='phase6-wal-derivation-v4' and manifest['organization']==org and manifest['source']==str(source),'Foreign WAL derivation')
    require(physical_inventory(source)==manifest['physical_inventory'],'Physical WAL evidence changed')
    require(json.loads((destination.parent/'derivation.json').read_bytes())==manifest,'Derivation metadata changed')
    blobs={s:Path(str(source)+s).read_bytes() for s,d in manifest['physical_inventory'].items() if d is not None}
    analysis,raw=analyze(blobs[''],blobs.get('-wal'))
    require(analysis==manifest['analysis'] and not analysis['partial_tail_bytes'],'WAL committed-prefix analysis differs')
    require(hashlib.sha256(raw).hexdigest()==manifest['derived_sha256']==sha(destination),'Derived physical image differs')
    require(manifest['logical_signature']==manifest['independent_sqlite_signature']==image_signature(destination),'Derived logical view differs')
    require(physical_inventory(source)==manifest['physical_inventory'],'Original sidecars changed during verification')
    return manifest

def _authorize_capture_read(authority,catalog,org,source,destination):
    from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope,relative_path
    if type(authority) is CapturePermit:return _authorize(authority,catalog,org,source,destination)
    require(type(authority) is ContinuationScope,'Verified WAL continuation authority required');authority.assert_ready()
    cert=authority.certificate();root=Path(cert['body']['source_root']);cap=Path(cert['body']['capture_root'])
    require(Path(source).resolve()==relative_path(root,org+'/private/local.sqlite') and Path(destination).resolve()==relative_path(cap,org+'/derived.sqlite'),'Uncertified physical/derived path')
    return Path(source).resolve(),Path(destination).resolve()
