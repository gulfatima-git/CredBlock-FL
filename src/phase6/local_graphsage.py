"""Local GraphSAGE over accepted sampled blocks, with no ID embeddings."""
import hashlib
import json
import torch
from torch import nn
from torch.nn import functional as F
from torch_geometric.nn import SAGEConv

from src.phase6.temporal_protocol import require


class LocalGraphSAGE(nn.Module):
    def __init__(self,hidden_dim=16,num_layers=2,dropout=0.1):
        super().__init__()
        require(type(hidden_dim) is int and hidden_dim>0 and num_layers>0,'Invalid architecture')
        require(0<=dropout<1,'Invalid dropout')
        self.dropout=dropout
        self.layers=nn.ModuleList([SAGEConv(8 if i==0 else hidden_dim,hidden_dim,
            aggr='mean',normalize=False,root_weight=True,project=False) for i in range(num_layers)])
        self.head=nn.Linear(hidden_dim,1)

    def forward(self,batch):
        require(len(batch.packets)==len(self.layers)==len(batch.routing),'Model/sampler layer mismatch')
        require(all(set(p.keys())=={'x','edge_index','num_nodes'} for p in batch.packets),'Unexpected model input fields')
        root_count=len(batch.routing[-1].destination_rows)
        require((batch.packets[-1].x[:root_count,7]==0).all().item(),'Only User roots may be classified')
        h=batch.packets[0].x
        for i,(layer,packet,route) in enumerate(zip(self.layers,batch.packets,batch.routing)):
            n_dst=len(route.destination_rows)
            require(len(h)==len(route.source_rows),'Hidden-state/block alignment failure')
            if i:
                require(torch.equal(torch.as_tensor(batch.routing[i-1].destination_rows.copy()),
                                    torch.as_tensor(route.source_rows.copy())),'Broken layer routing')
            h=F.relu(layer((h,h[:n_dst]),packet.edge_index,size=(len(h),n_dst)))
            if i+1<len(self.layers):
                h=F.dropout(h,p=self.dropout,training=self.training)
        return self.head(h).squeeze(-1)


def masked_bce(logits,y,mask,pos_weight=None):
    require(logits.shape==y.shape==mask.shape,'Supervision shape mismatch')
    require(mask.dtype==torch.bool and torch.equal(mask,y!=-1),'Invalid supervision mask')
    require(((y[mask]==0)|(y[mask]==1)).all().item(),'Invalid eligible labels')
    if not mask.any():
        return None
    return F.binary_cross_entropy_with_logits(logits[mask],y[mask].float(),pos_weight=pos_weight)


def state_digest(state):
    digest=hashlib.sha256()
    for name,tensor in sorted(state.items()):
        data=tensor.detach().cpu().contiguous()
        digest.update(json.dumps([name,str(data.dtype),list(data.shape)],separators=(',',':')).encode())
        digest.update(data.numpy().tobytes())
    return digest.hexdigest()


def classification_metrics(y,logits,mask):
    """No threshold tuning; nominal .5 precision/recall only; tied-score AP."""
    import numpy as np
    y=np.asarray(y);logits=np.asarray(logits,dtype=np.float64);mask=np.asarray(mask,dtype=bool)
    require(y.shape==logits.shape==mask.shape,'Metric shape mismatch')
    require(np.isfinite(logits).all(),'Nonfinite predictions')
    target=y[mask].astype(np.int64);score=logits[mask]
    require(np.isin(target,[0,1]).all(),'Invalid metric target')
    if not len(target):
        return dict(eligible=0,positive=0,negative=0,bce=None,average_precision=None,
                    precision_at_0_5=None,recall_at_0_5=None,f1_at_0_5=None)
    loss=np.maximum(score,0)-score*target+np.log1p(np.exp(-np.abs(score)))
    predicted=score>=0
    tp=int((predicted&(target==1)).sum());fp=int((predicted&(target==0)).sum());fn=int((~predicted&(target==1)).sum())
    order=np.argsort(-score,kind='stable');ordered=target[order];s=score[order]
    ends=np.r_[np.flatnonzero(s[:-1]!=s[1:]),len(s)-1]
    cumulative=np.cumsum(ordered)[ends]
    ap=float((np.diff(np.r_[0,cumulative])*cumulative/(ends+1)).sum()/target.sum()) if target.sum() else None
    precision=tp/(tp+fp) if tp+fp else 0.0
    recall=tp/(tp+fn) if tp+fn else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0
    return dict(eligible=len(target),positive=int(target.sum()),negative=int((target==0).sum()),bce=float(loss.mean()),
                average_precision=ap,precision_at_0_5=precision,recall_at_0_5=recall,f1_at_0_5=f1)
