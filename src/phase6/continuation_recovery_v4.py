"""Verified graph/SQLite recovery and append-only working-copy preparation."""
from pathlib import Path
from datetime import datetime
import json,hashlib,sqlite3,os,uuid
from src.phase6.heldout_contract_v2 import ORGS,canonical,digest,Branch,ROOT
from src.phase6.temporal_protocol import require,bounds
from src.phase6.continuation_contract_v4 import ContinuationScope,CapturePermit,relative_path
from src.phase6.continuation_reader_v4 import PredecessorReader,sha,parse_journal
from src.phase6.heldout_barrier_v2 import write_once,Journal

def row_digest(rows):
    h=hashlib.sha256()
    for row in rows:h.update((canonical(row)+'\n').encode())
    return h.hexdigest()

def prefix_digests(db,last_seq,checkpoint_seq,failure_max_id=None):
    if failure_max_id is None:failure_max_id=db.execute('SELECT COALESCE(MAX(id),0) FROM failures').fetchone()[0]
    return dict(
        score_digest=row_digest(db.execute('SELECT * FROM scores WHERE seq<=? ORDER BY seq,user_id',(last_seq,))),
        command_digest=row_digest(db.execute('SELECT * FROM commands WHERE seq<=? ORDER BY seq',(last_seq,))),
        token_digest=row_digest(db.execute('SELECT * FROM event_tokens WHERE seq<=? ORDER BY token',(last_seq,))),
        checkpoint_digest=row_digest((seq,hashlib.sha256(blob).hexdigest(),h) for seq,blob,h in db.execute('SELECT * FROM checkpoints WHERE seq<=? ORDER BY seq',(checkpoint_seq,))),
        failure_digest=row_digest(db.execute('SELECT * FROM failures WHERE id<=? ORDER BY id',(failure_max_id,))))

def inspect_store(path,org,variant,catalog,binding=None,authority=None,_working_projection=None):
    """Immutable inspection. Replays graph commands only; no model call exists."""
    from src.organization.rolling_graph_v1 import RollingGraph,OBSERVABLE
    path=Path(path).resolve()
    if catalog.fixture_only:
        require(not path.is_relative_to(ROOT) and not ROOT.is_relative_to(path),'Fixture store inspection escaped project')
    else:
        require(path.is_relative_to(ROOT/'reports/phase6/heldout_test_v2'),'Store outside approved evidence tree')
        if type(authority) is CapturePermit:
            authority.validate(catalog);require(path in {authority.source/org/'private/local.sqlite',authority.derived_root/org/'derived.sqlite'},'Capture database mismatch')
        else:
            require(type(authority) is ContinuationScope,'Production store inspection requires authority');authority.assert_ready()
            source=Path(authority.certificate()['body']['source_root'])
            cap=Path(authority.certificate()['body']['capture_root'])
            allowed={authority.output_root/variant/org/'private/local.sqlite',source/org/'private/local.sqlite',cap/org/'derived.sqlite'}
            if _working_projection is not None:
                from src.phase6.continuation_wal_v4 import physical_inventory,image_signature
                original=authority.output_root/variant/org/'private/local.sqlite'
                require(path.is_relative_to(authority.output_root/'wal_working_reviews') and _working_projection['physical_inventory']==physical_inventory(original) and sha(path)==_working_projection['derived_sha256'] and image_signature(path)==_working_projection['logical_signature'],'Unverified working projection')
                allowed.add(path)
            require(path in allowed,'Unapproved predecessor/working store')
    wal=Path(str(path)+'-wal')
    if wal.exists() and wal.stat().st_size and type(authority) is ContinuationScope and path==authority.output_root/variant/org/'private/local.sqlite':
        from src.phase6.continuation_wal_v4 import physical_inventory,project_store
        image=authority.output_root/'wal_working_reviews'/uuid.uuid4().hex/org/'derived.sqlite'
        m=project_store(authority,catalog,org,path,image,physical_inventory(path))
        return inspect_store(image,org,variant,catalog,binding,authority,_working_projection=m)
    require(not wal.exists() or wal.stat().st_size==0,'Nonempty WAL blocks immutable inspection')
    before={str(p):sha(p) for p in (path,wal,Path(str(path)+'-shm')) if p.exists()}
    db=sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro&immutable=1',uri=True)
    try:
        require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Recovery database integrity failure')
        identity=json.loads(db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0]);seal=catalog.seal(org,'graphsage')
        require(identity['format']=='phase6-local-inference-store-v1' and identity['organization']==org and identity['stream_id']==variant and identity['split']=='TEST' and
            identity['bundle']==json.loads(seal.identity_json) and identity['config_sha256']==digest(json.loads(catalog.inference_config_json)),'SQLite identity/model/config mismatch')
        src=identity['source_identity'];require(src['organization']==org and src['variant_id']==variant and src['split']=='TEST','Nonlocal SQLite source')
        if binding:
            b=Branch(**binding);b.validate(catalog)
            require(b.variant==variant and b.organization==org and src['anchor']==b.anchor and src['end_exclusive']==b.end and src['observations_sha256']==b.observations_sha256 and src['history_reference_sha256']==b.history_sha256,'SQLite branch-source mismatch')
        cp=db.execute('SELECT seq,graph,sha256 FROM checkpoints ORDER BY seq DESC LIMIT 1').fetchone()
        require(cp is not None and hashlib.sha256(cp[1]).hexdigest()==cp[2],'Latest graph checkpoint corrupt')
        graph=RollingGraph.from_checkpoint_bytes(cp[1]);require(graph.organization==org,'Nonlocal graph checkpoint')
        lo,hi=bounds(catalog.protocol,'TEST');require(lo<=graph.clock<hi and all(lo<=e.time<hi for e in graph.history_events),'Graph checkpoint crosses split')
        commands=db.execute('SELECT seq,asof,payload,event_offset,view_digest,timings FROM commands ORDER BY seq').fetchall()
        require(cp[0]<=len(commands),'Checkpoint beyond final command')
        if cp[0]:require(graph.clock.isoformat()==commands[cp[0]-1][1] and graph.view().digest()==commands[cp[0]-1][4],'Checkpoint does not match committed command')
        else:require(graph.clock<datetime.fromisoformat(src['anchor']) and all(e.time<datetime.fromisoformat(src['anchor']) for e in graph.history_events),'Initial checkpoint contains replay/future events')
        last=None;offset=0;replayed=0;token_rows=[]
        for n,(seq,at,payload,event_offset,view_digest,timings) in enumerate(commands,1):
            t=datetime.fromisoformat(at);p=json.loads(payload);rows=p['observations'];ts=json.loads(timings)
            require(seq==n and lo<=t<hi and (last is None or t>last) and datetime.fromisoformat(src['anchor'])<=t<datetime.fromisoformat(src['end_exclusive']),'Invalid committed sequence/time')
            require(len(rows)==len(p['tokens']) and len(set(p['tokens']))==len(p['tokens']),'Committed token mismatch')
            for r in rows:require(set(r)==set(OBSERVABLE) and r['organization']==org and r['Login Timestamp']==at,'Hidden/mixed committed observation')
            offset+=len(rows);require(offset==event_offset and ts['input_events']==len(rows),'Committed source offset mismatch')
            token_rows.extend((token,seq) for token in p['tokens'])
            stored=db.execute('SELECT user_id,logit_hex,threshold_hex,decision,model_sha256,threshold_sha256,schema_sha256,processing_status,logit,probability,asof,alert_id FROM scores WHERE seq=? ORDER BY user_id',(seq,)).fetchall()
            require(len(stored)==ts['scored_users'],'Missing committed score rows')
            import math
            for u,z,th,decision,model,threshold,schema,status,real,prob,score_time,alert_id in stored:
                value=float.fromhex(z);expected=json.loads(seal.identity_json);cut=json.loads(seal.threshold_json)
                require(math.isfinite(value) and th==cut['hex'] and decision==('ALERT' if th is not None and value>=float.fromhex(th) else 'NO_ALERT') and status=='OK','Committed binary64 decision invalid')
                require(real==value and math.isfinite(prob) and 0<=prob<=1 and score_time==at and (alert_id is not None)==(decision=='ALERT'),'Committed score representation/time invalid')
                require(model==expected['model_sha256'] and threshold==expected['threshold_sha256'] and schema==catalog.schema_sha256,'Committed score identity invalid')
            if seq>cp[0]:
                if rows:graph.ingest_batch(t,[dict(r,**{'Login Timestamp':datetime.fromisoformat(r['Login Timestamp'])}) for r in rows],p['tokens'])
                else:graph.advance(t)
                require(graph.view().digest()==view_digest,'Recovered command view differs');replayed+=1
            last=t
        require(cp[0]<=len(commands),'Checkpoint beyond final command')
        if commands:require(graph.view().digest()==commands[-1][4],'Recovered final graph differs')
        require(db.execute('SELECT COUNT(*) FROM scores WHERE seq NOT IN (SELECT seq FROM commands)').fetchone()[0]==0,'Orphan scores')
        require(db.execute('SELECT COUNT(*) FROM event_tokens').fetchone()[0]==offset,'Committed token ledger mismatch')
        require(sorted(token_rows)==db.execute('SELECT token,seq FROM event_tokens ORDER BY token').fetchall(),'Committed tokens do not match command payloads')
        descriptor=dict(identity=identity,last_seq=len(commands),event_offset=offset,checkpoint_seq=cp[0],checkpoint_sha256=cp[2],
            view_digest=graph.view().digest(),clock=graph.clock.isoformat(),score_rows=db.execute('SELECT COUNT(*) FROM scores').fetchone()[0],graph_commands_replayed=replayed,
            failure_max_id=db.execute('SELECT COALESCE(MAX(id),0) FROM failures').fetchone()[0],
            **prefix_digests(db,len(commands),cp[0]))
    finally:db.close()
    require(before=={str(p):sha(p) for p in (path,wal,Path(str(path)+'-shm')) if p.exists()},'Read-only inspection changed database/sidecars')
    return dict(descriptor=descriptor,graph=graph,GNN_forwards=0)

class Workspace:
    def __init__(self,scope):
        require(type(scope) is ContinuationScope,'Invalid continuation capability');scope.assert_ready()
        self.scope=scope;self.cert=scope.certificate();self.reader=PredecessorReader(self.cert,scope.catalog,scope).verify()
        self.target=scope.output_root/self.reader.body['origin']['variant']
        require(not self.target.resolve().is_relative_to(self.reader.root) and not self.reader.root.is_relative_to(self.target.resolve()),'Overlapping predecessor/workspace')
        self.meta=scope.output_root/'continuation_meta'/self.target.name
    def prepare(self,fail=lambda stage:None):
        from src.phase6.continuation_lease_v4 import predecessor_lease
        with predecessor_lease(self.scope,self.scope.catalog):return self._prepare(fail)
    def _prepare(self,fail=lambda stage:None):
        self.scope.assert_ready()
        ready=self.meta/'ready.json'
        if self.reader.body['kind']=='RUN_BOUNDARY':
            self.reader.verify()
            write_once(ready,dict(certificate_id=self.cert['certificate_id'],executor=self.scope.adapter_identity,kind='RUN_BOUNDARY',files_copied=0))
            return self
        if ready.exists():
            require(json.loads(ready.read_bytes())['certificate_id']==self.cert['certificate_id'],'Wrong restored workspace')
            self.verify_prefix();self.verify_recovered_stores();return self
        # Before READY no local service has been authorized to open the restored
        # image. A pre-existing WAL/SHM/journal here could change its SQL view.
        # Preserve the unexpected bytes and refuse, never delete or normalize.
        for org in self.reader.body['stores']:
            for suffix in ('-wal','-shm','-journal'):
                require(not (self.target/org/'private'/('local.sqlite'+suffix)).exists(),
                        'Unexpected working sidecar before initial restore seal')
        log=Journal(self.meta/'copy_progress',dict(certificate_id=self.cert['certificate_id'],executor=self.scope.adapter_identity))
        for fragment in self.target.rglob('*.copying.*'):
            rel=fragment.relative_to(self.target).as_posix()
            if not log.get('PRESERVED_COPY_FRAGMENT',None,key=rel):
                log.append(dict(event='PRESERVED_COPY_FRAGMENT',key=rel,size=fragment.stat().st_size,sha256=sha(fragment),role='auxiliary_uncommitted_copy_fragment'))
        for rel,desc in self.reader.body['files'].items():
            source=relative_path(self.reader.root,rel)
            is_db=rel.endswith(('.sqlite','.sqlite-wal','.sqlite-shm','.sqlite-journal'))
            dest=relative_path(self.meta/'physical_archive' if is_db else self.target,rel)
            require(sha(source)==desc['sha256'],'Predecessor changed before copy')
            if dest.exists():require(sha(dest)==desc['sha256'],'Existing incomplete copy differs')
            else:
                dest.parent.mkdir(parents=True,exist_ok=True);staging=dest.with_name(dest.name+'.copying.'+uuid.uuid4().hex)
                with source.open('rb') as src,staging.open('xb') as out:
                    for b in iter(lambda:src.read(1024*1024),b''):
                        out.write(b);fail('after_copy_chunk:'+rel)
                    out.flush();os.fsync(out.fileno())
                require(sha(staging)==desc['sha256'],'Copy checksum mismatch')
                if os.name=='nt':os.rename(staging,dest)
                else:os.link(staging,dest) # No replacement; preserve the staging inode.
            fail('after_copy_file:'+rel)
            if not log.get('COPY_FILE',None,key=rel):log.append(dict(event='COPY_FILE',key=rel,sha256=desc['sha256']))
        for org,manifest in self.reader.body['wal_derivations'].items():
            source=relative_path(Path(self.reader.body['capture_root']),org+'/derived.sqlite')
            dest=relative_path(self.target,org+'/private/local.sqlite')
            require(sha(source)==manifest['derived_sha256'],'Certified image changed before restore')
            if dest.exists():require(sha(dest)==manifest['derived_sha256'],'Uncommitted restored image differs')
            else:
                from src.phase6.continuation_wal_v4 import _publish
                _publish(dest,source.read_bytes())
            fail('after_restore_database:'+org)
            if not log.get('RESTORE_IMAGE',None,key=org):log.append(dict(event='RESTORE_IMAGE',key=org,sha256=manifest['derived_sha256']))
        self.reader.verify();self.verify_prefix(initial=True)
        write_once(ready,dict(certificate_id=self.cert['certificate_id'],executor=self.scope.adapter_identity,files=len(self.reader.body['files'])))
        fail('after_workspace_ready');return self
    def verify_prefix(self,initial=False):
        if self.reader.body['kind']=='RUN_BOUNDARY':return
        for rel,desc in self.reader.body['files'].items():
            if rel.endswith(('.sqlite','.sqlite-wal','.sqlite-shm','.sqlite-journal')):
                p=relative_path(self.meta/'physical_archive',rel);require(sha(p)==desc['sha256'],'Physical archive changed')
                continue
            p=relative_path(self.target,rel)
            if initial:require(sha(p)==desc['sha256'],'Initial workspace copy invalid');continue
            if '/progress/barriers.' in rel or '/grid_progress/barriers.' in rel:
                with p.open('rb') as f:prefix=f.read(desc['size'])
                require(len(prefix)==desc['size'] and hashlib.sha256(prefix).hexdigest()==desc['sha256'],'Original journal prefix rewritten')
            elif rel.endswith(('.sqlite','.sqlite-wal','.sqlite-shm')):continue # Verified independently as committed working state.
            else:require(sha(p)==desc['sha256'],'Immutable predecessor artifact rewritten')
    def verify_recovered_stores(self):
        if self.reader.body['kind']=='RUN_BOUNDARY':return {}
        result={}
        for org,expected in self.reader.body['stores'].items():
            path=self.target/org/'private/local.sqlite'
            current=inspect_store(path,org,self.target.name,self.scope.catalog,self.reader.body['bindings'].get(org),authority=self.scope)['descriptor']
            require(current['last_seq']>=expected['last_seq'],'Committed predecessor work lost')
            if current['last_seq']==expected['last_seq']:
                require(all(v==expected[k] for k,v in current.items() if k not in ('failure_max_id','failure_digest')),'Recovered predecessor state differs')
            wal=Path(str(path)+'-wal')
            if wal.exists() and wal.stat().st_size:
                from src.phase6.continuation_wal_v4 import physical_inventory,project_store
                projected=self.scope.output_root/'wal_working_reviews'/uuid.uuid4().hex/org/'derived.sqlite'
                project_store(self.scope,self.scope.catalog,org,path,projected,physical_inventory(path));path=projected
            db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                hashes=prefix_digests(db,expected['last_seq'],expected['checkpoint_seq'],expected['failure_max_id'])
                require(all(h==expected[k] for k,h in hashes.items()),'Previously committed SQLite rows/checkpoints were rewritten')
            finally:db.close()
            result[org]=current
        return result
