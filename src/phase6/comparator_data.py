"""Root-only projection of immutable accepted TRAIN/VAL cache; no replay changes."""
from dataclasses import dataclass
from datetime import datetime
import hashlib,json
import numpy as np
import torch
from src.phase6.readiness import load,sha
from src.phase6.temporal_protocol import require,bounds,require_use
from src.phase6.training_data import cached_batches,guarded_split

FEATURES=('total_logins','successful_logins','failed_logins','failure_ratio','distinct_neighbors','recent_logins_10min','recent_distinct_neighbors_10min')

def root_features(batch):
    """Only the raw destination-prefix User rows; never inspect edges or neighbors."""
    count=len(batch.routing[-1].destination_rows)
    x=batch.packets[-1].x[:count]
    require(x.ndim==2 and x.shape[1]==8 and (x[:,7]==0).all().item(),'Expected eight-column User root schema')
    require(torch.isfinite(x).all().item(),'Nonfinite root features')
    return x[:,:7].clone()

@dataclass
class TabularSplit:
    x:torch.Tensor
    y:torch.Tensor
    mask:torch.Tensor
    keys:list
    unseen_user:np.ndarray
    unseen_ip:np.ndarray
    slices:list
    split:str
    organization:str
    manifest:dict

def identity_digest(keys,y,mask):
    h=hashlib.sha256()
    for key,label,eligible in zip(keys,y.tolist(),mask.tolist()):
        h.update((json.dumps([*key,label,eligible],separators=(',',':'))+'\n').encode())
    return h.hexdigest()

def validate_identity(keys,y,mask,organization,split,protocol):
    guarded_split(protocol,split)
    require(len(keys)==len(y)==len(mask),'Identity length mismatch')
    require(mask.dtype==torch.bool and torch.equal(mask,y!=-1),'Invalid root supervision mask')
    require(((y==-1)|(y==0)|(y==1)).all().item(),'Invalid labels')
    require(len(set(keys))==len(keys),'Duplicate User-time examples')
    lo,hi=bounds(protocol,split)
    offsets=set(protocol['scoring']['grid_offsets_minutes'])
    for org,s,variant,asof,uid in keys:
        t=datetime.fromisoformat(asof)
        require(org==organization and s==split and variant.endswith('_'+split),'Cross-organization/split identity')
        require(lo<=t<hi and t.minute in offsets and t.second==0 and t.microsecond==0,'Off-grid or future example')
        require(type(uid) is int,'Local User ID must remain audit-only integer')

def load_tabular(directory,protocol,split,organization,graph_model=None):
    guarded_split(protocol,split) # before manifest/path access, including nonexistent TEST paths
    manifest=load(directory/'manifest.json')
    require(manifest['scope']=='FULL' and manifest['variants']==171 and manifest['grids']==1026,'Full accepted cache required')
    xs=[];ys=[];masks=[];keys=[];users=[];ips=[];slices=[];graph=[];offset=0
    for batch,payload in cached_batches(directory,protocol,split,organization,verify_files=True):
        x=root_features(batch);y=batch.supervision.y.clone();mask=batch.supervision.eligible_mask.clone()
        p=batch.provenance;n=len(y)
        require(len(x)==n,'Root feature/label alignment failed')
        xs.append(x);ys.append(y);masks.append(mask)
        keys.extend((organization,split,p['variant_id'],p['asof'],int(u)) for u in payload['user_ids'])
        users.append(payload['unseen_user'].numpy());ips.append(payload['unseen_ip'].numpy())
        slices.append((offset,offset+n));offset+=n
        if graph_model is not None:
            with torch.no_grad(): graph.append(graph_model(batch).numpy())
    require(bool(xs),'Empty tabular split')
    x,y,mask=(torch.cat(a) for a in (xs,ys,masks))
    validate_identity(keys,y,mask,organization,split,protocol)
    require(int((y[mask]==1).sum())==manifest['positive'] and int((y[mask]==0).sum())==manifest['negative'] and int((~mask).sum())==manifest['masked_recent_roots'],'Full eligible/masked census mismatch')
    return TabularSplit(x,y,mask,keys,np.concatenate(users),np.concatenate(ips),slices,split,organization,manifest),np.concatenate(graph) if graph else None

def require_training(data,protocol,organization):
    require_use(protocol,data.split,'fit')
    require(data.organization==organization,'Nonlocal training data')
    validate_identity(data.keys,data.y,data.mask,organization,'TRAIN',protocol)

def export_tensor_data(path,data):
    torch.save(dict(x=data.x,y=data.y,mask=data.mask,keys=data.keys,slices=data.slices,
        unseen_user=torch.from_numpy(data.unseen_user.copy()),unseen_ip=torch.from_numpy(data.unseen_ip.copy()),
        split=data.split,organization=data.organization,manifest_sha256=identity_digest(data.keys,data.y,data.mask)),path)
