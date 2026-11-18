"""Load the original non-graph comparator for fixed-grid comparison only."""
import torch
from src.phase6.readiness import load,sha
from src.phase6.temporal_protocol import require
from src.phase6.fpr_calibration import load_frozen_threshold
from src.phase6.local_graphsage import state_digest
from src.phase6.non_graph_comparator import LocalTabularMLP
from src.phase6.comparator_data import FEATURES
from src.phase6.heldout_scope_v1 import PROJECT


class HeldOutTabularBundle:
    detector='tabular_mlp'

    def __init__(self, organization):
        require(organization in ('Org1','Org2','Org3','Org4','Org5'),'Unknown organization')
        self.organization=organization
        threshold_path=PROJECT/f'reports/phase6/calibration/v1/thresholds/{organization}_tabular_mlp.json'
        # Calibration summary pins the original threshold byte identity.
        accepted=load(PROJECT/'reports/phase6/test_adapter_v1/preservation_before.json')
        require(sha(threshold_path)==accepted[threshold_path.relative_to(PROJECT).as_posix()],
                'Comparator threshold changed')
        meta=load(threshold_path)
        self.threshold_artifact=load_frozen_threshold(threshold_path,organization=organization,detector=self.detector,
            model_sha256=meta['model_sha256'],protocol_sha256=load(PROJECT/'configs/phase6/heldout_test_adapter_v1.json')['protocol_sha256'],
            configuration_sha256=sha(PROJECT/'configs/phase6/fpr_calibration_v1.json'))
        from pathlib import Path
        path=Path(meta['model_path']).resolve()
        require(path.is_relative_to(PROJECT) and sha(path)==meta['model_sha256'],'Comparator model changed')
        require(meta['model_configuration_sha256']==sha(PROJECT/'configs/phase6/non_graph_comparator_v1.json') and
                meta['feature_schema_sha256']==sha(PROJECT/'configs/phase6/feature_allowlist_v1.json'),
                'Comparator configuration/schema changed')
        for relative,digest in meta['source_sha256'].items():
            require(sha(PROJECT/relative)==digest,'Comparator threshold source changed')
        saved=torch.load(path,map_location='cpu',weights_only=True)
        require(saved['organization']==organization and saved['split_fitted']=='TRAIN' and saved['split_selected']=='VAL',
                'Comparator lineage mismatch')
        require({k:saved[k] for k in meta['model_version']}==meta['model_version'] and
                tuple(saved['feature_names'])==FEATURES and state_digest(saved['model_state'])==saved['state_digest'],
                'Comparator version/feature/state mismatch')
        config=load(PROJECT/'configs/phase6/non_graph_comparator_v1.json')
        self.model=LocalTabularMLP(saved['candidate']['hidden_dim'],config['model']['dropout'])
        self.model.load_state_dict(saved['model_state'],strict=True);self.model.eval();self.model.requires_grad_(False)
        require(all(torch.isfinite(p).all() for p in self.model.parameters()),'Nonfinite comparator weights')
        self.state_digest=saved['state_digest'];self.threshold=meta['calibration']['threshold']
        self.protocol=load(PROJECT/'configs/phase6/split_protocol_v1.json')
        self.sampler=load(PROJECT/'configs/phase6/neighbor_sampling_v1.json')
        self.identity=dict(organization=organization,detector=self.detector,model_sha256=meta['model_sha256'],
                           threshold_sha256=sha(threshold_path),protocol_sha256=meta['protocol_sha256'])
