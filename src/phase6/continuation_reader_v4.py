"""Read-only certificate and journal verification. Constructors never write."""
from pathlib import Path
import json,hashlib,sqlite3
from src.phase6.heldout_contract_v2 import canonical,digest,ORGS,Branch,Scope,ROOT
from src.phase6.heldout_grid_v2 import EvaluationContext
from src.phase6.temporal_protocol import require
from src.phase6.continuation_contract_v4 import relative_path,science,CapturePermit,ContinuationScope,ORIGINAL_RUN

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def parse_journal(root,expected_identity=None):
    root=Path(root);records=[];last='0'*64;segments=[];tails=[]
    resolved=root.resolve()
    require(not ROOT.is_relative_to(resolved) and (not resolved.is_relative_to(ROOT) or resolved.is_relative_to(ROOT/'reports/phase6/heldout_test_v2')),'Journal read outside approved evidence/fixture tree')
    files=sorted(root.glob('barriers.*.jsonl'))
    require(bool(files),'Missing predecessor journal')
    for index,p in enumerate(files):
        require(p.name==f'barriers.{index:06d}.jsonl','Missing/noncontiguous journal segment')
        raw=p.read_bytes();segments.append(dict(name=p.name,size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b'\n'):
                tails.append(dict(segment=index,bytes=len(line),sha256=hashlib.sha256(line).hexdigest()));break
            r=json.loads(line);check=dict(r);h=check.pop('sha256')
            require(r['seq']==len(records) and r['prev']==last and digest(check)==h and digest(r['body'])==r['body_sha256'],'Journal sequence/checksum failure')
            records.append(r);last=h
    require(records and records[0]['body'].get('event')=='IDENTITY','Missing original journal identity')
    identity=records[0]['body']['identity']
    if expected_identity is not None:require(identity==expected_identity,'Original journal identity mismatch')
    for tail in tails:
        if tail['segment']<len(files)-1:
            expected=dict(event='PRESERVED_INCOMPLETE_TAIL',**tail)
            require(any(r['body']==expected for r in records),'Unexplained older incomplete tail')
    seen={}
    for r in records[1:]:
        b=r['body'];k=tuple(b.get(x) for x in ('event','at','organization','key'))
        if b.get('event') in ('BEGIN','COMPLETE','LOCAL','ISSUANCE','PUBLICATION_PREPARED','PUBLISHED','PAIRED','RECEIPT','GRID_COMMIT'):
            require(k not in seen,'Duplicate committed journal stage');seen[k]=b
    return dict(identity=identity,records=records,last=last,segments=segments,tails=tails)

class PredecessorReader:
    def __init__(self,certificate,catalog,authority=None):
        self.certificate=certificate;self.body=certificate['body'];self.catalog=catalog
        require(certificate['format']=='phase6-continuation-wal-certificate-v4' and certificate['certificate_id']==digest(self.body),'Certificate checksum mismatch')
        require(self.body['science']==science(catalog) and self.body['mode']==('synthetic' if catalog.fixture_only else 'production'),'Certificate scientific/mode mismatch')
        self.root=Path(self.body['source_root']).resolve();self._journals={};self._grids={}
        if catalog.fixture_only:
            require(not self.root.is_relative_to(ROOT) and not ROOT.is_relative_to(self.root),'Fixture reader escaped into project')
        else:
            require(self.root.parent==ORIGINAL_RUN,'Production predecessor outside original run')
            if type(authority) is CapturePermit:
                authority.validate(catalog);require(authority.source==self.root,'Capture source mismatch')
            else:
                require(type(authority) is ContinuationScope,'Production predecessor requires capture/execution authority')
                authority.assert_ready();require(authority.certificate_id==certificate['certificate_id'],'Unapproved predecessor certificate')
        self.authority=authority if authority is not None else CapturePermit.synthetic(self.root,catalog,Path(self.body['capture_root']))
        capture=Path(self.body['capture_root']).resolve()
        require(not capture.is_relative_to(self.root.parent) and not self.root.is_relative_to(capture),'WAL capture overlaps original run')
        if catalog.fixture_only:require(not capture.is_relative_to(ROOT) and not ROOT.is_relative_to(capture),'Fixture capture escaped project')
        origin=self.body['origin'];row=self.body['row']
        require(self.body.get('kind') in ('INSTANCE_CONTINUATION','RUN_BOUNDARY'),'Unknown predecessor certificate kind')
        require(origin.get('version')=='heldout-instance-v2' and origin.get('adapter')==Scope.current_adapter_identity() and origin.get('catalog')==catalog.identity and origin.get('variant')==row.get('variant_id') and origin.get('register_row_sha256')==digest(row),'Certificate row/origin mismatch')
    def verify(self):
        from src.phase6.continuation_lease_v4 import predecessor_lease
        with predecessor_lease(self.authority,self.catalog):return self._verify()
    def _verify(self):
        actual={p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()}
        require(actual==set(self.body['files']),'Unexpected/missing predecessor artifact or sidecar')
        for rel,desc in self.body['files'].items():
            p=relative_path(self.root,rel);require(p.stat().st_size==desc['size'] and sha(p)==desc['sha256'],'Predecessor file changed: '+rel)
        origin=json.loads(relative_path(self.root,'identity.json').read_bytes())
        require(origin==self.body['origin'],'Predecessor origin changed')
        require((self.root/'completion.json').exists()==(self.body['kind']=='RUN_BOUNDARY'),'Predecessor completion kind differs')
        bindings=json.loads((self.root/'bindings.json').read_bytes()) if (self.root/'bindings.json').exists() else {}
        require(bindings==self.body['bindings'] and (not bindings or set(bindings)==set(ORGS)),'Certificate binding map differs from source')
        for org,b in bindings.items():
            branch=Branch(**b);branch.validate(self.catalog)
            require(branch.organization==org and branch.variant==origin['variant'] and branch.anchor==self.body['row']['campaign_start'] and branch.end==self.body['row']['campaign_end_exclusive'],'Binding differs from frozen row')
        for directory,desc in self.body['journals'].items():
            require(directory in ['sharing/progress']+[o+'/private/grid_progress' for o in ORGS],'Unsupported predecessor journal')
            if directory=='sharing/progress':expected=dict(version='heldout-barrier-v2',adapter=origin['adapter'],catalog=self.catalog.identity,branches={o:Branch(**b).identity for o,b in bindings.items()})
            else:
                org=directory.split('/')[0];expected=dict(context=EvaluationContext.bind(self.catalog,Branch(**bindings[org])).identity,adapter=origin['adapter'])
            require(desc['identity']==expected,'Certificate journal identity not derived from original science')
            parsed=parse_journal(relative_path(self.root,directory),desc['identity']);require(parsed['last']==desc['last'] and parsed['segments']==desc['segments'] and parsed['tails']==desc['tails'],'Journal descriptor changed')
            require(not any(r['body']['event']=='ENGINE_TRANSITION' for r in parsed['records']),'Only original v2 predecessors are supported')
            self._journals[directory]=parsed
            for r in parsed['records']:
                b=r['body']
                if 'path' in b:
                    rel='sharing/'+b['path'];require(rel in self.body['files'] and self.body['files'][rel]['sha256']==b['sha256'],'Uncertified stage reference')
                if b['event']=='GRID_COMMIT':
                    org=directory.split('/')[0];raw=b['raw'];self._check_grid(org,b,raw)
                    self._grids[org,b['at'],b['key']]=b
        # A published raw file without a durable GRID_COMMIT is not a cache hit.
        import re
        for rel in self.body['files']:
            match=re.fullmatch(r'(Org[1-5])/private/grid_(\d\d)_(graphsage|tabular_mlp)\.json',rel)
            if match:
                raw=json.loads(relative_path(self.root,rel).read_bytes())
                stage=self.grid(match[1],raw['asof'],match[3])
                require(stage is not None and stage['raw']==raw,'Uncommitted or changed published grid file')
        from src.phase6.continuation_recovery_v4 import inspect_store
        actual_stores={o for o in ORGS if (self.root/o/'private/local.sqlite').exists()}
        require(actual_stores==set(self.body['stores'])==set(self.body['wal_derivations']),'Certificate store/derivation census mismatch')
        for org,expected in self.body['stores'].items():
            from src.phase6.continuation_wal_v4 import verify_derivation
            derived=relative_path(Path(self.body['capture_root']),org+'/derived.sqlite')
            physical=self.root/org/'private/local.sqlite';manifest=self.body['wal_derivations'][org]
            for suffix,desc in manifest['physical_inventory'].items():require(desc==self.body['files'].get(org+'/private/local.sqlite'+suffix),'WAL derivation not bound to physical certificate')
            verify_derivation(self.authority,self.catalog,org,physical,derived,manifest)
            actual=inspect_store(derived,org,origin['variant'],self.catalog,bindings.get(org),authority=self.authority)['descriptor']
            require(actual==expected,'Certificate committed-store summary differs')
            source=actual['identity']['source_identity'];require(source['anchor']==self.body['row']['campaign_start'] and source['end_exclusive']==self.body['row']['campaign_end_exclusive'],'Store source period differs from frozen row')
        self.reconcile_saved_evidence()
        return self
    def reconcile_saved_evidence(self):
        """Independent saved-LOCAL/grid -> committed SQL join; no evaluator/model."""
        columns=['user_id','logit_hex','threshold_hex','decision','alert_id','model_sha256','threshold_sha256']
        for org in self.body['stores']:
            path=relative_path(Path(self.body['capture_root']),org+'/derived.sqlite')
            db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                sharing=self._journals.get('sharing/progress',{}).get('records',[])
                for record in sharing:
                    b=record['body']
                    if b['event']!='LOCAL' or b.get('organization')!=org:continue
                    value=json.loads(relative_path(self.root,'sharing/'+b['path']).read_bytes())
                    command=db.execute('SELECT asof,view_digest FROM commands WHERE seq=?',(value['seq'],)).fetchone()
                    require(command==(b['at'],value['provenance']['view_digest']) and value['at']==b['at'],'LOCAL journal/committed command mismatch')
                    rows=[dict(zip(columns,r)) for r in db.execute('SELECT '+','.join(columns)+' FROM scores WHERE seq=? ORDER BY user_id',(value['seq'],))]
                    require(rows==value['scores'],'LOCAL journal/committed prediction mismatch')
                    require(value['provenance']['branch']==Branch(**self.body['bindings'][org]).identity and value['provenance']['bundle']==json.loads(self.catalog.seal(org,'graphsage').identity_json),'LOCAL committed provenance mismatch')
                for (o,at,detector),b in self._grids.items():
                    if o!=org:continue
                    row=db.execute('SELECT view_digest FROM commands WHERE asof=?',(at,)).fetchone()
                    require(row is not None and row[0]==b['raw']['view_digest'],'Grid/committed temporal-view mismatch')
            finally:db.close()
    def _check_grid(self,org,b,raw):
        binding=self.body['bindings'][org];context=EvaluationContext.bind(self.catalog,Branch(**binding));seal=context.seal(b['key'])
        require(raw['version']=='sealed-grid-raw-v2' and raw['manifest_sha256']==context.branch.manifest_sha256 and raw['adapter_identity']==self.body['origin']['adapter'] and raw['context_identity']==context.identity and
            raw['branch_identity']==context.branch.identity and raw['organization']==org and raw['variant_id']==context.branch.variant and
            raw['asof']==b['at'] and raw['detector']==b['key'] and b['at'] in [t.isoformat() for t in context.branch.grid], 'Legacy grid scope mismatch')
        require(raw['model_identity']==json.loads(seal.identity_json) and raw['model_state_digest']==seal.state_digest and
            raw['threshold']==json.loads(seal.threshold_json) and raw['feature_schema_sha256']==context.schema_sha256 and
            raw['sampler_configuration_identity_sha256']==digest(json.loads(seal.sampler_json)), 'Legacy grid bundle/schema/sampler mismatch')
        require(len({r['user_id'] for r in raw['roots']})==len(raw['roots']),'Duplicate legacy grid User')
        import math
        th=json.loads(seal.threshold_json)
        for row in raw['roots']:
            z=float.fromhex(row['logit_hex']);require(math.isfinite(z) and row['alert']==(th['kind']=='finite' and z>=float.fromhex(th['hex'])),'Legacy binary64 decision differs')
    def grid(self,org,at,detector):return self._grids.get((org,at,detector))
    def journal(self,directory):return self._journals.get(directory)

def build_certificate(permit,catalog,row,output,register_rows=None):
    """Capture a quiescent single instance only; not callable on live production."""
    permit.validate(catalog)
    if not permit.fixture:require(Path(output).resolve()==permit.derived_root/'predecessor_certificate.json','Production certificate must use its explicit capture namespace')
    require(not Path(output).resolve().is_relative_to(permit.source.parent),'Certificate would modify original run')
    from src.phase6.continuation_lease_v4 import predecessor_lease
    with predecessor_lease(permit,catalog):return _build_certificate(permit,catalog,row,output,register_rows)

def _build_certificate(permit,catalog,row,output,register_rows=None):
    permit.validate(catalog);source=permit.source
    kind='RUN_BOUNDARY' if (source/'completion.json').exists() else 'INSTANCE_CONTINUATION'
    origin=json.loads((source/'identity.json').read_bytes())
    require(origin['version']=='heldout-instance-v2' and origin['adapter']==Scope.current_adapter_identity() and origin['catalog']==catalog.identity and origin['variant']==row['variant_id'] and origin['register_row_sha256']==digest(row),'Wrong predecessor inventory identity')
    files={}
    for p in sorted(source.rglob('*')):
        require(not p.is_symlink() and not getattr(p,'is_junction',lambda:False)(),'Linked snapshot file/directory')
        if p.is_file():
            rel=p.relative_to(source).as_posix();relative_path(source,rel);files[rel]=dict(size=p.stat().st_size,sha256=sha(p))
    bindings=json.loads((source/'bindings.json').read_bytes()) if (source/'bindings.json').exists() else {}
    require(not bindings or set(bindings)==set(ORGS),'Partial branch identity map')
    journals={}
    directories=['sharing/progress']+[o+'/private/grid_progress' for o in ORGS]
    for directory in directories:
        p=source/directory
        if not p.exists():continue
        require(set(bindings)==set(ORGS),'Journal without complete branch bindings')
        if directory=='sharing/progress':
            expected=dict(version='heldout-barrier-v2',adapter=origin['adapter'],catalog=catalog.identity,branches={o:Branch(**b).identity for o,b in bindings.items()})
        else:
            org=directory.split('/')[0];expected=dict(context=EvaluationContext.bind(catalog,Branch(**bindings[org])).identity,adapter=origin['adapter'])
        parsed=parse_journal(p,expected);journals[directory]={k:parsed[k] for k in ('identity','last','segments','tails')}
    if 'sharing/progress' in journals:require(all((source/o/'private/local.sqlite').exists() for o in ORGS),'Coordinator without five stores')
    stores={};derivations={}
    from src.phase6.continuation_recovery_v4 import inspect_store
    for org in ORGS:
        db=source/org/'private/local.sqlite'
        if db.exists():
            from src.phase6.continuation_wal_v4 import physical_inventory,project_store
            derived=relative_path(permit.derived_root,org+'/derived.sqlite')
            derivations[org]=project_store(permit,catalog,org,db,derived,physical_inventory(db))
            stores[org]=inspect_store(derived,org,row['variant_id'],catalog,bindings.get(org),authority=permit)['descriptor']
    from src.phase6.continuation_manifest_v4 import verify_completion
    if not permit.fixture:
        import csv
        from src.phase6.continuation_contract_v4 import ROOT,REGISTER,REGISTER_SHA
        require(sha(ROOT/REGISTER)==REGISTER_SHA,'Frozen register changed')
        with (ROOT/REGISTER).open(newline='',encoding='utf-8-sig') as f:register_rows=sorted([r for r in csv.DictReader(f) if r['split']=='TEST'],key=lambda r:r['variant_id'])
    registered={r['variant_id']:r for r in (register_rows or [row])}
    require(registered.get(row['variant_id'])==row,'Predecessor not in certified register')
    completed={}
    for sibling in source.parent.iterdir():
        require(not sibling.is_symlink() and not getattr(sibling,'is_junction',lambda:False)(),'Linked original run entry')
        if sibling.is_dir() and (sibling/'completion.json').exists():
            require(sibling.name in registered,'Unregistered completed predecessor')
            completed[sibling.name]=verify_completion(sibling,registered[sibling.name],catalog,{origin['adapter']})
    body=dict(kind=kind,mode='synthetic' if permit.fixture else 'production',source_root=str(source),origin=origin,row=row,science=science(catalog),
        capture_authority_sha256=permit.approval_sha256,files=files,bindings=bindings,journals=journals,stores=stores,
        completed_origins=completed,register_rows_digest=digest(sorted(register_rows,key=lambda r:r['variant_id'])) if register_rows else None,
        capture_root=str(permit.derived_root),wal_derivations=derivations)
    cert=dict(format='phase6-continuation-wal-certificate-v4',body=body,certificate_id=digest(body))
    PredecessorReader(cert,catalog,permit).verify()
    # Recheck every enumerated source byte after inspection; no best-effort copy.
    for rel,d in files.items():require(sha(relative_path(source,rel))==d['sha256'],'Source changed during capture')
    require({p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}==set(files),'Source inventory changed during capture')
    from src.phase6.heldout_barrier_v2 import write_once
    write_once(output,cert);return cert
