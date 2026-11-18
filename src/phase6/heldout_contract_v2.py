"""Additive frozen identities and policy boundaries. No payload/weight IO at import."""
from dataclasses import dataclass,asdict
from datetime import datetime,timedelta
import hashlib,json
from pathlib import Path
from functools import lru_cache
from src.phase6.temporal_protocol import require,bounds

ROOT=Path(__file__).resolve().parents[2]
ORGS=tuple(f'Org{i}' for i in range(1,6))
MODULES=tuple(f'src/phase6/heldout_{n}_v2.py' for n in ('contract','grid','barrier','driver'))

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

@dataclass(frozen=True)
class BundleSeal:
    organization:str
    detector:str
    identity_json:str
    state_digest:str
    threshold_json:str
    model_class:str
    sampler_json:str
    protocol_json:str
    fixture_only:bool=False

    def validate(self,bundle):
        from src.phase6.local_graphsage import state_digest
        model=bundle.model
        require(bundle.organization==self.organization,'Nonlocal bundle')
        require(canonical(bundle.identity)==self.identity_json,'Bundle identity changed')
        require(canonical(bundle.threshold)==self.threshold_json,'Threshold changed')
        require(canonical(bundle.sampler)==self.sampler_json and canonical(bundle.protocol)==self.protocol_json,'Sampler/protocol changed')
        require(type(model).__module__+'.'+type(model).__qualname__==self.model_class,'Model class changed')
        require(state_digest(model.state_dict())==self.state_digest,'Model state differs from sealed authority')
        require(not model.training and all(not p.requires_grad for p in model.parameters()),'Model must remain frozen/eval')

@dataclass(frozen=True)
class Catalog:
    protocol_json:str
    sampler_json:str
    schema_sha256:str
    inference_config_json:str
    indicator_json:str
    seals:tuple
    source_hashes:tuple=()
    fixture_only:bool=False
    manifest_pins:tuple=()

    @property
    def identity(self):return digest(asdict(self))
    @property
    def protocol(self):return json.loads(self.protocol_json)
    @property
    def policy(self):return json.loads(self.indicator_json)
    def seal(self,org,detector):
        found=[s for s in self.seals if s.organization==org and s.detector==detector]
        require(len(found)==1,'Missing/duplicate original bundle seal');return found[0]

    @classmethod
    @lru_cache(maxsize=1)
    def permitted_metadata(cls):
        """Only explicit configuration/threshold/preregistration metadata reads."""
        from src.phase6.adapter_metadata_audit_v1 import MetadataReader
        config='configs/phase6/adapter_metadata_audit_v1.json'
        boot=MetadataReader(ROOT,[config]);approved=boot.json(config)
        paths=['configs/phase6/split_protocol_v1.json','configs/phase6/neighbor_sampling_v1.json',
               'configs/phase6/feature_allowlist_v1.json','configs/phase6/continuous_inference_v1.json',
               'configs/phase6/indicator_sharing_v1.json','reports/phase6/inference/preregistration_v1.json']
        paths += [f'reports/phase6/calibration/v1/thresholds/{o}_{d}.json' for o in ORGS for d in ('graphsage','tabular_mlp')]
        reader=MetadataReader(ROOT,paths);raw={p:reader.read(p) for p in paths}
        for p,value in raw.items():require(hashlib.sha256(value).hexdigest()==approved['expected_sha256'][p],'Accepted metadata changed: '+p)
        values={p:json.loads(b) for p,b in raw.items()};registry=values[paths[5]]['registry'];seals=[]
        proto=canonical(values[paths[0]]);sampler=canonical(values[paths[1]])
        for org in ORGS:
            for detector in ('graphsage','tabular_mlp'):
                path=f'reports/phase6/calibration/v1/thresholds/{org}_{detector}.json';t=values[path]
                if detector=='graphsage':
                    entry=registry['models'][org]
                    identity=dict(organization=org,model_sha256=entry['model_sha256'],threshold_sha256=entry['threshold_sha256'],threshold_seal=t['seal_sha256'],model_version=t['model_version'],feature_schema_sha256=t['feature_schema_sha256'],protocol_sha256=registry['protocol_sha256'],sampler_sha256=hashlib.sha256(raw[paths[1]]).hexdigest(),calibration_configuration_sha256=t['configuration_sha256'])
                    model_class='src.phase6.local_graphsage.LocalGraphSAGE'
                else:
                    identity=dict(organization=org,detector=detector,model_sha256=t['model_sha256'],threshold_sha256=hashlib.sha256(raw[path]).hexdigest(),protocol_sha256=t['protocol_sha256'])
                    model_class='src.phase6.non_graph_comparator.LocalTabularMLP'
                seals.append(BundleSeal(org,detector,canonical(identity),t['model_version']['state_digest'],canonical(t['calibration']['threshold']),model_class,sampler,proto))
        sources=[p for p in approved['allowlist'] if p.startswith(('src/','tests/'))]
        source_reader=MetadataReader(ROOT,sources)
        for p in sources:
            raw[p]=source_reader.read(p)
            require(hashlib.sha256(raw[p]).hexdigest()==approved['expected_sha256'][p],'Accepted source changed: '+p)
        # Global freeze inventory contains path/size/hash metadata only, NOT
        # campaign manifest bodies or observations. Never follow these paths.
        freeze='reports/phase5_graph_retention_v1/dataset_freeze_reference/dataset_freeze_manifest.json'
        freeze_raw=MetadataReader(ROOT,[freeze]).read(freeze)
        require(hashlib.sha256(freeze_raw).hexdigest()==json.loads(proto)['dataset_freeze_sha256'],'Global freeze metadata changed')
        manifest_pins=tuple(sorted((entry['path_relative_to_project'].replace('\\','/').split('/')[-2],entry['sha256'])
            for entry in json.loads(freeze_raw)['files'] if '_TEST/replay_manifest.json' in entry['path_relative_to_project'].replace('\\','/')))
        require(len(manifest_pins)==171 and len(dict(manifest_pins))==171,'Global freeze metadata missing 171 TEST manifest identities')
        raw[freeze]=freeze_raw
        return cls(proto,sampler,hashlib.sha256(raw[paths[2]]).hexdigest(),canonical(values[paths[3]]),canonical(values[paths[4]]),tuple(seals),tuple((p,hashlib.sha256(v).hexdigest()) for p,v in raw.items()),False,manifest_pins)

@dataclass(frozen=True)
class Branch:
    variant:str
    organization:str
    anchor:str
    end:str
    manifest_sha256:str
    observations_sha256:str
    history_sha256:str

    @property
    def identity(self):return digest(self.__dict__)
    @property
    def start(self):return datetime.fromisoformat(self.anchor)
    @property
    def stop(self):return datetime.fromisoformat(self.end)
    @property
    def grid(self):return tuple(self.start+timedelta(minutes=n) for n in (0,10,20,30,40,50))
    def validate(self,catalog):
        require(self.organization in ORGS and self.variant.endswith('_TEST') and Path(self.variant).name==self.variant and '/' not in self.variant and '\\' not in self.variant,'Invalid TEST branch')
        lo,hi=bounds(catalog.protocol,'TEST')
        require(self.start.tzinfo is None and lo<=self.start<self.stop<=hi and self.stop-self.start==timedelta(hours=1),'Invalid TEST horizon')
        require(self.start-timedelta(days=7)>=lo,'Warm-up crosses another split')
        require(all(len(v)==64 and all(c in '0123456789abcdef' for c in v) for v in (self.manifest_sha256,self.observations_sha256,self.history_sha256)),'Unsealed branch sources')
        if not catalog.fixture_only:require(dict(catalog.manifest_pins).get(self.variant)==self.manifest_sha256,'Branch manifest absent from frozen assignment metadata')

@dataclass(frozen=True)
class Scope:
    root:Path
    output_root:Path
    catalog:Catalog
    synthetic_only:bool=False
    adapter_identity:str=''

    @staticmethod
    def current_adapter_identity():
        return digest(dict(sources={p:file_hash(ROOT/p) for p in MODULES},configuration_sha256=file_hash(ROOT/'configs/phase6/heldout_remediation_v2.json')))

    @classmethod
    def synthetic(cls,directory,catalog):
        root=Path(directory).resolve()
        require(catalog.fixture_only and all(s.fixture_only for s in catalog.seals) and not root.is_relative_to(ROOT) and not ROOT.is_relative_to(root),'Isolated synthetic catalog/root required')
        return cls(root,root/'outputs',catalog,True,cls.current_adapter_identity())
    @classmethod
    def production(cls,output,catalog):return cls(ROOT,Path(output).resolve(),catalog,False,cls.current_adapter_identity())
    def assert_ready(self):
        require(self.adapter_identity==self.current_adapter_identity(),'Adapter code/config changed during run; select a reviewed version')
        if self.synthetic_only:
            require(self.catalog.fixture_only and all(s.fixture_only for s in self.catalog.seals) and not self.root.is_relative_to(ROOT) and not ROOT.is_relative_to(self.root),'Fixture scope escaped')
            require(self.output_root==self.root/'outputs','Invalid fixture output');return
        require(not self.catalog.fixture_only and all(not s.fixture_only for s in self.catalog.seals) and self.root==ROOT and self.output_root.is_relative_to(ROOT/'reports/phase6/heldout_test_v2'),'Invalid production scope')
        # This remediation never creates this record. Check before register,
        # manifests, shared Parquet, labels or model weight access.
        path=ROOT/'reports/phase6/test_adapter_remediation_v2/execution_approval.json'
        require(path.is_file(),'TEST execution blocked pending explicit v2 review approval')
        approval=json.loads(path.read_bytes())
        require(approval.get('status')=='USER_APPROVED_TEST_EXECUTION_V2' and approval.get('explicit_user_decision') and
                approval.get('catalog_identity')==self.catalog.identity and
                approval.get('source_sha256')=={p:file_hash(ROOT/p) for p in MODULES} and
                approval.get('configuration_sha256')==file_hash(ROOT/'configs/phase6/heldout_remediation_v2.json') and
                approval.get('shared_parquet_isolation')=='EXPLICITLY_REVIEWED_LOGICAL_ROWS_NOT_PHYSICAL_BYTES',
                'Missing/stale v2 execution or shared-Parquet review approval')
        for p,h in self.catalog.source_hashes:require(file_hash(ROOT/p)==h,'Accepted metadata changed')
    def check_output(self,path):require(Path(path).resolve().is_relative_to(self.output_root),'Output escaped scope')
    def check_variant(self,variant,org):
        require(org in ORGS and isinstance(variant,str) and variant.endswith('_TEST') and
                Path(variant).name==variant and '/' not in variant and '\\' not in variant,'TEST variant/org required')
    def check_input(self,path,variant,org,*,labels=False):
        self.check_variant(variant,org);p=Path(path).resolve()
        require(p.is_relative_to(self.root),'Input escaped scope')
        from src.phase6.readiness import REPLAY
        folder=self.root/REPLAY/variant
        permitted={folder/f'{org}_labels.parquet'} if labels else {folder/'replay_manifest.json',folder/f'{org}_observations.parquet'}
        if p in {x.resolve() for x in permitted}:return p
        ref=self.root/REPLAY/'history_references'
        require(not labels and p.is_relative_to(ref.resolve()) and p.parent.name in ('TEST_SEED1001','TEST_SEED1002','TEST_SEED1003') and p.name==org+'.json','Nonlocal/cross-split input')
        return p
    def check_history_source(self,path,authorized_sources):
        p=Path(path).resolve();require(p.is_relative_to(self.root) and p in {Path(s).resolve() for s in authorized_sources} and
            p.suffix=='.parquet' and '_TRAIN' not in str(p) and '_VAL' not in str(p),'Unpinned history source');return p
    @property
    def inference_config_sha256(self):return digest(json.loads(self.catalog.inference_config_json))
    def verify_bundle(self,bundle,org):self.catalog.seal(org,'graphsage').validate(bundle)

def verify_five_org_policy(catalog,branches,issuers,network):
    require(set(branches)==set(issuers)==set(network.recipients)==set(ORGS),'Exactly Org1-Org5 required')
    require(canonical(network.config)==catalog.indicator_json,'Frozen network policy drift')
    common=set()
    for org in ORGS:
        branch=branches[org];branch.validate(catalog)
        require(branch.organization==org and issuers[org].organization==org and network.recipients[org].organization==org,'Organization identity mismatch')
        require(canonical(issuers[org].config)==catalog.indicator_json and canonical(network.recipients[org].config)==catalog.indicator_json,'Issuer/recipient policy drift')
        common.add((branch.variant,branch.anchor,branch.end,branch.manifest_sha256))
    require(len(common)==1,'Mixed campaign variant/horizon/manifest')
