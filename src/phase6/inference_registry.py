"""Hash-pinned local inference bundle; no training or remote model adoption."""
from pathlib import Path
import torch
from src.organization.rolling_graph_v1 import FEATURES
from src.phase6.readiness import load,sha
from src.phase6.temporal_protocol import require
from src.phase6.local_graphsage import LocalGraphSAGE,state_digest
from src.phase6.fpr_calibration import load_frozen_threshold,canonical_digest

class InferenceBundle:
    def __init__(self,root,organization,registry):
        self.root=Path(root);self.organization=organization
        require(organization in registry['models'],'Organization absent from pinned registry')
        entry=registry['models'][organization]
        for path,digest in registry['shared_sha256'].items():require(sha(self.root/path)==digest,'Shared inference identity mismatch: '+path)
        for name in ['model_path','threshold_path']:
            require(sha(self.root/entry[name])==entry[name.replace('_path','_sha256')],'Pinned '+name+' mismatch')
        schema=load(self.root/'configs/phase6/feature_allowlist_v1.json');sampler=load(self.root/'configs/phase6/neighbor_sampling_v1.json')
        require(tuple(f['name'] for f in schema['features'])==FEATURES,'Feature schema/order mismatch')
        require(sha(self.root/'src/organization/rolling_graph_v1.py')==schema['runtime_sha256'],'Graph runtime mismatch')
        self.protocol=load(self.root/'configs/phase6/split_protocol_v1.json');self.sampler=sampler
        self.threshold_artifact=load_frozen_threshold(self.root/entry['threshold_path'],organization=organization,detector='graphsage',
            model_sha256=entry['model_sha256'],protocol_sha256=registry['protocol_sha256'],configuration_sha256=sha(self.root/'configs/phase6/fpr_calibration_v1.json'))
        t=self.threshold_artifact
        require(t['feature_schema_sha256']==sha(self.root/'configs/phase6/feature_allowlist_v1.json') and t['model_configuration_sha256']==sha(self.root/'configs/phase6/local_training_v1.json'),'Model/schema configuration mismatch')
        for path,digest in t['source_sha256'].items():require(sha(self.root/path)==digest,'Threshold source mismatch')
        saved=torch.load(self.root/entry['model_path'],map_location='cpu',weights_only=True)
        require(saved['organization']==organization and saved['split_fitted']=='TRAIN' and saved['split_selected']=='VAL','Model lineage mismatch')
        require({k:saved[k] for k in t['model_version']}==t['model_version'],'Model version mismatch')
        require(state_digest(saved['model_state'])==saved['state_digest'] and all(torch.isfinite(v).all().item() for v in saved['model_state'].values()),'Model tensor integrity failure')
        config=load(self.root/'configs/phase6/local_training_v1.json')
        require(config['model']['num_layers']==sampler['num_layers']==2,'Model/sampler layer mismatch')
        self.model=LocalGraphSAGE(saved['candidate']['hidden_dim'],2,config['model']['dropout'])
        self.model.load_state_dict(saved['model_state'],strict=True);self.model.eval();self.model.requires_grad_(False)
        self.state_digest=saved['state_digest'];self.threshold=t['calibration']['threshold']
        self.identity=dict(organization=organization,model_sha256=entry['model_sha256'],threshold_sha256=entry['threshold_sha256'],
             threshold_seal=t['seal_sha256'],model_version=t['model_version'],feature_schema_sha256=t['feature_schema_sha256'],
             protocol_sha256=registry['protocol_sha256'],sampler_sha256=sha(self.root/'configs/phase6/neighbor_sampling_v1.json'),calibration_configuration_sha256=t['configuration_sha256'])
        self.fingerprint=canonical_digest(self.identity)

class LocalModelRegistry:
    def __init__(self,root,organization,pinned):
        self.root,self.organization,self.pinned=root,organization,pinned
        self.current=InferenceBundle(root,organization,pinned)

    def try_candidate(self,pinned):
        """Validate fully before replacement; this subphase accepts only the original pins."""
        try:
            require(pinned==self.pinned,'Only the original accepted local bundle is authorized')
            candidate=InferenceBundle(self.root,self.organization,pinned)
        except Exception as error:return dict(status='REJECTED_RETAINED_LAST_USABLE',error_type=type(error).__name__,message=str(error))
        self.current=candidate
        return dict(status='RELOADED_ORIGINAL_ACCEPTED_BUNDLE',fingerprint=candidate.fingerprint)
