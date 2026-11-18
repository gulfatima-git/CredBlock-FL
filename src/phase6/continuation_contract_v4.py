"""Additive continuation authority. No data, model or process access at import."""
from dataclasses import dataclass
from pathlib import Path
import json,hashlib
from src.phase6.heldout_contract_v2 import ROOT,ORGS,Catalog,Scope,canonical,digest,file_hash
from src.phase6.temporal_protocol import require

MODULES=tuple('src/phase6/'+n+'.py' for n in (
    'continuation_contract_v4','continuation_reader_v4','continuation_recovery_v4',
    'continuation_manifest_v4','continuation_barrier_v4','continuation_driver_v4','continuation_lease_v4','continuation_wal_v4'))+('configs/phase6/continuation_wal_v4.json',)
REGISTER='reports/phase5_final_acceptance_v2/campaign_register_v2.csv'
REGISTER_SHA='d9e2b1a63308e00da05b5dac2afd83f27b259c006e69044f593130db0cc0aaef'
ORIGINAL_RUN=ROOT/'reports/phase6/heldout_test_v2/final_v1'
NEW_RUNS=ROOT/'reports/phase6/heldout_test_v2/wal_v4_transition'
CAPTURES=ROOT/'reports/phase6/heldout_test_v2/wal_v4_captures'
AUTHORIZATIONS=ROOT/'reports/phase6/heldout_test_v2/wal_v4_authorizations'
_CAPTURE=object()

def release_sources():return {p:file_hash(ROOT/p) for p in MODULES}
def release_identity():return digest(dict(version='continuation-wal-executor-v4',sources=release_sources(),v2=Scope.current_adapter_identity()))

def production_destination(path):
    path=Path(path).resolve()
    require(path.is_relative_to(NEW_RUNS) and path!=NEW_RUNS,'Production continuation requires its separate versioned output subtree')
    return path

def relative_path(root,relative):
    require(isinstance(relative,str) and relative and '\\' not in relative,'Noncanonical relative path')
    p=Path(relative)
    require(relative==p.as_posix() and not p.is_absolute() and '..' not in p.parts and '.' not in p.parts and ':' not in relative,'Unsafe/noncanonical relative path')
    root=Path(root).resolve();target=(root/p).resolve()
    require(target.is_relative_to(root) and target!=root,'Path escaped instance')
    require(not any(q.is_symlink() or getattr(q,'is_junction',lambda:False)() for q in [root/p,*list((root/p).parents)[:len(p.parts)-1]]),'Linked snapshot path')
    return target

def science(catalog):
    return dict(catalog=catalog.identity,protocol=digest(catalog.protocol),sampler=digest(json.loads(catalog.sampler_json)),
        schema=catalog.schema_sha256,indicator=digest(catalog.policy),inference=digest(json.loads(catalog.inference_config_json)),
        bundles={s.organization+':'+s.detector:dict(identity=json.loads(s.identity_json),state=s.state_digest,threshold=json.loads(s.threshold_json)) for s in catalog.seals})

def authorization_path(path):
    raw=Path(path).absolute()
    require(raw.is_relative_to(AUTHORIZATIONS) and raw!=AUTHORIZATIONS and '..' not in raw.parts and raw.suffix=='.json','Approval/attestation outside explicit WAL-v4 metadata namespace')
    return relative_path(AUTHORIZATIONS,raw.relative_to(AUTHORIZATIONS).as_posix())

@dataclass(frozen=True)
class CapturePermit:
    source:Path
    catalog_identity:str
    fixture:bool
    approval_sha256:str
    _issued:object
    authorization_path:Path|None=None
    derived_root:Path|None=None

    @classmethod
    def synthetic(cls,source,catalog,derived_root=None):
        source=Path(source).resolve()
        require(catalog.fixture_only and not source.is_relative_to(ROOT) and not ROOT.is_relative_to(source),'Synthetic capture escaped fixture')
        derived=Path(derived_root).resolve() if derived_root else source.parent.parent/'wal_captures_v4'/source.name
        require(not derived.is_relative_to(ROOT) and not derived.is_relative_to(source.parent) and not source.is_relative_to(derived),'Unsafe fixture capture output')
        return cls(source,catalog.identity,True,digest(['fixture-wal-capture',str(source),str(derived)]),_CAPTURE,derived_root=derived)
    @classmethod
    def production(cls,source,catalog,approval_path):
        # The current implementation approval is not an execution/capture grant.
        p=authorization_path(approval_path)
        require(not catalog.fixture_only and catalog==Catalog.permitted_metadata(),'Non-authoritative catalog')
        require(p.is_file(),'Separate user-approved quiescent capture is required')
        a=json.loads(p.read_bytes());source=Path(source).resolve()
        require(a.get('status')=='USER_APPROVED_QUIESCENT_WAL_V4_CAPTURE' and a.get('explicit_user_decision') and a.get('source_root')==str(source),'Capture not approved')
        require(a.get('release_identity')==release_identity() and a.get('catalog_identity')==catalog.identity,'Stale capture release/science')
        host=authorization_path(a['host_exit_attestation']);require(file_hash(host)==a['host_exit_attestation_sha256'],'Unpinned host attestation')
        state=json.loads(host.read_bytes())
        require(state.get('source_quiescent') is True and state.get('original_worker_exited') is True and state.get('original_lease_released') is True and state.get('source_root')==str(source),'Quiescence not established')
        require(source.parent==ORIGINAL_RUN,'Capture outside the original approved run')
        derived=Path(a['derived_root']).resolve()
        require(derived.is_relative_to(CAPTURES) and derived!=CAPTURES,'Separate WAL capture namespace required')
        return cls(source,catalog.identity,False,file_hash(p),_CAPTURE,p,derived)
    def validate(self,catalog):
        require(self._issued is _CAPTURE and self.catalog_identity==catalog.identity and self.fixture==catalog.fixture_only,'Invalid capture capability')
        if self.fixture:require(not self.source.is_relative_to(ROOT) and not ROOT.is_relative_to(self.source),'Fixture source escaped')
        else:require(self.authorization_path is not None and file_hash(self.authorization_path)==self.approval_sha256,'Capture authority changed')
        require(self.derived_root is not None and not self.derived_root.is_relative_to(self.source.parent) and not self.source.is_relative_to(self.derived_root),'Capture output overlaps original run')

@dataclass(frozen=True)
class ContinuationScope(Scope):
    certificate_path:Path|None=None
    certificate_id:str|None=None
    execution_approval:Path|None=None
    fixture_variants:tuple|None=None
    execution_approval_sha256:str|None=None

    @staticmethod
    def current_adapter_identity():return release_identity()
    @classmethod
    def synthetic(cls,root,catalog,certificate_path=None):
        root=Path(root).resolve();require(catalog.fixture_only and not root.is_relative_to(ROOT) and not ROOT.is_relative_to(root),'Fixture continuation escaped')
        cid=None
        if certificate_path is not None:
            v=json.loads(Path(certificate_path).read_bytes());cid=v['certificate_id']
        return cls(root,root/'outputs',catalog,True,release_identity(),Path(certificate_path) if certificate_path else None,cid,None)
    @classmethod
    def production(cls,output,catalog,certificate_path,approval_path):
        approval_path=authorization_path(approval_path)
        c=Path(certificate_path).absolute()
        require(c.is_relative_to(CAPTURES) and c!=CAPTURES and '..' not in c.parts and c.suffix=='.json','Certificate outside WAL-v4 capture namespace')
        c=relative_path(CAPTURES,c.relative_to(CAPTURES).as_posix())
        # No payload or certificate is opened before the separate approval exists.
        require(Path(approval_path).is_file(),'v3 execution not separately approved')
        raw=Path(approval_path).read_bytes();a=json.loads(raw)
        return cls(ROOT,Path(output).resolve(),catalog,False,release_identity(),c,a.get('certificate_id'),Path(approval_path),execution_approval_sha256=hashlib.sha256(raw).hexdigest())
    def approval_metadata(self):
        require(not self.synthetic_only and self.execution_approval is not None,'No production authorization')
        authorization_path(self.execution_approval)
        raw=self.execution_approval.read_bytes()
        require(hashlib.sha256(raw).hexdigest()==self.execution_approval_sha256,'Execution grant changed; use a separately approved new scope')
        return json.loads(raw)
    def assert_ready(self):
        require(self.adapter_identity==release_identity(),'Continuation source changed')
        if not self.synthetic_only:
            production_destination(self.output_root)
            require(self.execution_approval is not None,'No production authorization')
            authorization_path(self.execution_approval)
            require(self.execution_approval is not None and self.execution_approval.is_file(),'v3 execution not separately approved')
            a=self.approval_metadata()
            require(a.get('status')=='USER_APPROVED_WAL_V4_CONTINUATION_EXECUTION' and a.get('explicit_user_decision') and
                a.get('release_identity')==self.adapter_identity and a.get('source_sha256')==release_sources() and
                a.get('output_root')==str(self.output_root) and a.get('certificate_id')==self.certificate_id and
                a.get('catalog_identity')==self.catalog.identity and a.get('register_sha256')==REGISTER_SHA,'Unapproved/stale v3 execution')
            allowed=a.get('authorized_variants');all_ids=set(dict(self.catalog.manifest_pins))
            require(isinstance(allowed,list) and len(allowed)==len(set(allowed)) and set(allowed)<=all_ids and a.get('required_instances_total')==171,'Invalid instance execution grant')
            require((a.get('execution_scope')=='ALL_171' and set(allowed)==all_ids) or
                (a.get('execution_scope')=='PILOT_ONLY' and 1<=len(allowed)<=4),'Unbounded or incomplete execution grant')
            require(self.certificate_path and file_hash(self.certificate_path)==a.get('certificate_file_sha256'),'Certificate not pinned by execution approval')
        Scope.assert_ready(self) # Retain every original v2 source/metadata/approval check.
        if self.certificate_path:
            c=json.loads(self.certificate_path.read_bytes())
            require(c.get('format')=='phase6-continuation-wal-certificate-v4' and c['certificate_id']==self.certificate_id==digest(c['body']) and c['body']['science']==science(self.catalog),'Changed certificate or science')
            require(c['body']['mode']==('synthetic' if self.synthetic_only else 'production'),'Mixed certificate execution mode')
            if not self.synthetic_only:
                require(Path(c['body']['source_root']).resolve().parent==ORIGINAL_RUN,'Wrong original execution root')
                cap=Path(c['body']['capture_root']).resolve();require(cap.is_relative_to(CAPTURES) and cap!=CAPTURES,'Wrong WAL capture root')
                require(c['body']['origin']['variant'] in set(a['authorized_variants']),'Grant omits continuation instance')
    def certificate(self):
        self.assert_ready();require(self.certificate_path is not None,'Missing predecessor certificate')
        return json.loads(self.certificate_path.read_bytes())
    def permits_variant(self,variant):
        if self.synthetic_only:return self.fixture_variants is None or variant in self.fixture_variants
        return variant in self.approval_metadata()['authorized_variants']
    def check_variant(self,variant,org):
        Scope.check_variant(self,variant,org)
        require(self.permits_variant(variant),'Instance outside explicit v3 execution grant')
    @property
    def full_execution_grant(self):
        return self.fixture_variants is None if self.synthetic_only else self.approval_metadata()['execution_scope']=='ALL_171'
    def authorization_reference(self):
        self.assert_ready()
        if self.synthetic_only:
            return dict(status='SYNTHETIC_NONAUTHORIZING_PERMISSION_REFERENCE',executor=self.adapter_identity,variants=list(self.fixture_variants) if self.fixture_variants else None)
        a=self.approval_metadata()
        return dict(status='AUTHORIZATION_REFERENCE_ONLY',executor=self.adapter_identity,certificate_id=self.certificate_id,
            authorization_path=str(self.execution_approval),authorization_sha256=self.execution_approval_sha256,
            execution_scope=a['execution_scope'],authorized_variants=a['authorized_variants'])

class OriginGridScope:
    """Narrow offline-only identity adapter for a certified legacy raw grid."""
    def __init__(self,scope,raw,expected_digest,origin):
        require(digest(raw)==expected_digest and raw['adapter_identity']==origin,'Uncertified legacy grid')
        self._scope,self._raw,self._expected=scope,raw,expected_digest
        self.catalog,self.adapter_identity=scope.catalog,origin
    def assert_ready(self):
        self._scope.assert_ready();require(digest(self._raw)==self._expected,'Legacy raw changed')

def eligible_compat(scope,context,raw,rows,seal,reader=None):
    from src.phase6.heldout_grid_v2 import eligible_predictions
    scope.assert_ready()
    if raw['adapter_identity']==scope.adapter_identity:return eligible_predictions(scope,context,raw,rows,seal)
    require(reader is not None,'Legacy raw requires verified predecessor')
    expected=reader.grid(context.branch.organization,raw['asof'],raw['detector'])
    require(expected is not None and expected['raw']==raw,'Legacy raw not in certified committed grid')
    old=OriginGridScope(scope,raw,digest(expected['raw']),reader.body['origin']['adapter'])
    return eligible_predictions(old,context,raw,rows,seal)
