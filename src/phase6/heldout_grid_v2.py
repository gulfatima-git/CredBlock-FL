"""Verified grid context. Raw predictions are label-free; labels join after seal."""
from dataclasses import dataclass
import json
import weakref
import sys
from src.phase6.heldout_contract_v2 import canonical,digest,Branch,Catalog,BundleSeal
from src.phase6.temporal_protocol import require,validate_target

class _ViewTicket:pass
_issued_views=weakref.WeakKeyDictionary()

def verified_port_type(port):
    """A -m driver has __main__ classes but retains its canonical module spec."""
    cls=type(port);canonical_module='src.phase6.heldout_driver_v2'
    if cls.__qualname__!='LocalPort':return False
    if cls.__module__==canonical_module:return True
    spec=getattr(sys.modules.get('__main__'),'__spec__',None)
    return cls.__module__=='__main__' and getattr(spec,'name',None)==canonical_module

@dataclass(frozen=True)
class EvaluationContext:
    branch:Branch
    catalog_identity:str
    graph_seal:BundleSeal
    tabular_seal:BundleSeal
    schema_sha256:str
    sampler_json:str
    inference_config_json:str

    @classmethod
    def bind(cls,catalog,branch):
        branch.validate(catalog)
        return cls(branch,catalog.identity,catalog.seal(branch.organization,'graphsage'),
                   catalog.seal(branch.organization,'tabular_mlp'),catalog.schema_sha256,
                   catalog.sampler_json,catalog.inference_config_json)
    @property
    def identity(self):return digest(dict(branch=self.branch.identity,catalog=self.catalog_identity,
        graph=self.graph_seal.identity_json,tabular=self.tabular_seal.identity_json,
        schema=self.schema_sha256,sampler=self.sampler_json,config=self.inference_config_json))
    def validate(self,catalog):require(self==EvaluationContext.bind(catalog,self.branch),'Invalid or modified evaluation context')
    def seal(self,detector):
        require(detector in ('graphsage','tabular_mlp'),'Unknown fixed detector')
        return self.graph_seal if detector=='graphsage' else self.tabular_seal
    def capture(self,scope,port,at):
        scope.assert_ready();self.validate(scope.catalog)
        require(port.branch==self.branch and port.organization==self.branch.organization,'Foreign branch-view origin')
        require(at in self.branch.grid,'Arbitrary snapshot outside six primary grids')
        if not scope.synthetic_only:
            require(verified_port_type(port),'Unverified production view producer')
            port.attest(self)
        view=port.view(at)
        require(view.asof==at and view.organization==self.branch.organization,'View clock/organization mismatch')
        ticket=_ViewTicket();proof=(self.identity,at.isoformat(),view.digest(),id(view))
        _issued_views[ticket]=proof
        return BoundView(self.identity,at.isoformat(),view.digest(),view,ticket)

@dataclass(frozen=True)
class BoundView:
    context_identity:str
    asof:str
    view_digest:str
    view:object
    _ticket:object=None

    def validate(self,context):
        require(self._ticket in _issued_views and _issued_views[self._ticket]==
                (context.identity,self.asof,self.view_digest,id(self.view)),'Snapshot was not issued by the verified context')
        require(self.context_identity==context.identity and self.asof==self.view.asof.isoformat() and
                self.view_digest==self.view.digest() and self.view.asof in context.branch.grid and
                self.view.organization==context.branch.organization,'Unbound/modified graph snapshot')

def score_grid(scope,context,bound,bundle,detector):
    """All recent User roots, unchanged sampler/chunks; no truth/label arguments."""
    import numpy as np
    import torch
    import time
    from src.phase6.input_pipeline import TemporalNeighborSampler
    from src.phase6.fpr_calibration import decisions
    scope.assert_ready();context.validate(scope.catalog);bound.validate(context)
    seal=context.seal(detector);seal.validate(bundle)
    started=time.perf_counter()
    view=bound.view;cfg=json.loads(context.sampler_json)
    sampler=TemporalNeighborSampler(view,context.branch.variant,'TEST',tuple(cfg['fanouts_model_order']),cfg['seed'],bundle.protocol)
    roots=sampler.user_rows[view.x[sampler.user_rows,5]>0]
    require(len(set(roots.tolist()))==len(roots),'Duplicate observable root')
    values=[]
    with torch.inference_mode():
        for start in range(0,len(roots),cfg['batch_size']):
            packet=sampler.sample(roots[start:start+cfg['batch_size']])
            require(not packet.supervision.eligible_mask.any(),'Supervision entered raw scoring')
            if detector=='tabular_mlp':
                from src.phase6.comparator_data import root_features
                z=bundle.model(root_features(packet))
            else:z=bundle.model(packet)
            values.extend(z.numpy().tolist())
    scores=np.asarray(values,dtype=np.float64)
    require(len(scores)==len(roots) and np.isfinite(scores).all(),'Invalid raw output')
    flags=decisions(scores,bundle.threshold)
    return dict(version='sealed-grid-raw-v2',context_identity=context.identity,
        adapter_identity=scope.adapter_identity,
        branch_identity=context.branch.identity,organization=context.branch.organization,
        variant_id=context.branch.variant,asof=bound.asof,detector=detector,
        manifest_sha256=context.branch.manifest_sha256,view_digest=bound.view_digest,
        model_identity=json.loads(seal.identity_json),model_state_digest=seal.state_digest,
        threshold=json.loads(seal.threshold_json),sampler_configuration_identity_sha256=digest(json.loads(seal.sampler_json)),
        feature_schema_sha256=context.schema_sha256,
        sampling_and_model_seconds=time.perf_counter()-started,
        roots=[dict(user_id=view.private_keys[int(r)][1],logit_hex=float(z).hex(),alert=bool(a)) for r,z,a in zip(roots,scores,flags)])

def eligible_predictions(scope,context,raw,rows,score_seal):
    """Validate EVERY mask/label identity after raw seal, before eligible metrics.

    No model call is reachable here. Raw scores are never recomputed after truth.
    """
    scope.assert_ready();context.validate(scope.catalog)
    require(score_seal.get('status')=='SCORES_SEALED_BEFORE_LABELS' and
            digest(raw) in score_seal.get('raw_score_digests',()),'Raw score is not in pre-label seal')
    require(raw['context_identity']==context.identity and raw['branch_identity']==context.branch.identity and
            raw['organization']==context.branch.organization and raw['variant_id']==context.branch.variant and
            raw['adapter_identity']==scope.adapter_identity,'Raw score identity mismatch')
    from datetime import datetime
    at=datetime.fromisoformat(raw['asof']);require(at in context.branch.grid,'Invalid raw grid time')
    seal=context.seal(raw['detector'])
    require(raw['model_identity']==json.loads(seal.identity_json) and raw['model_state_digest']==seal.state_digest and
            raw['threshold']==json.loads(seal.threshold_json),'Unsealed raw model/threshold')
    values={r['user_id']:r for r in raw['roots']}
    require(len(values)==len(raw['roots']),'Duplicate raw User')
    result=[];seen=set()
    for row in rows:
        validate_target(scope.catalog.protocol,row,context.branch.organization,'TEST',at)
        require(row['variant_id']==context.branch.variant and 'grid_snapshot' in row['query_kind'],'Wrong branch/grid label')
        u=row['User ID'];require(type(u)is int and u not in seen,'Duplicate/invalid User-time label');seen.add(u)
        if row['supervision_eligible']:
            require(u in values,'Eligible label omitted from accepted recent roots')
            result.append(dict(organization=context.branch.organization,variant_id=context.branch.variant,
                asof=raw['asof'],user_id=u,detector=raw['detector'],node_label=row['node_label'],
                logit_hex=values[u]['logit_hex'],alert=values[u]['alert'],threshold=raw['threshold']))
    return result
