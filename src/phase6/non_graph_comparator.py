"""Local tabular detector accepts only seven scalar root-User features."""
import csv,math,time
from pathlib import Path
import numpy as np
import psutil,torch
from torch import nn
from src.phase6.local_graphsage import masked_bce,state_digest,classification_metrics
from src.phase6.local_training import seed_all
from src.phase6.temporal_protocol import require,require_use
from src.phase6.readiness import sha
from src.phase6.training_data import dump_json
from src.phase6.comparator_data import require_training,identity_digest

class LocalTabularMLP(nn.Module):
    def __init__(self,hidden_dim=16,dropout=.1):
        super().__init__()
        require(type(hidden_dim)is int and hidden_dim>0 and 0<=dropout<1,'Invalid comparator architecture')
        self.network=nn.Sequential(nn.Linear(7,hidden_dim),nn.ReLU(),nn.Dropout(dropout),nn.Linear(hidden_dim,hidden_dim),nn.ReLU(),nn.Linear(hidden_dim,1))
    def forward(self,x):
        require(isinstance(x,torch.Tensor) and x.ndim==2 and x.shape[1]==7 and x.dtype==torch.float32,'Comparator input must be seven float32 behavioral features only')
        require(torch.isfinite(x).all().item(),'Nonfinite comparator input')
        return self.network(x).squeeze(-1)

def evaluate_tabular(model,data,protocol):
    require(data.split in {'TRAIN','VAL'},'No TEST evaluation')
    require_use(protocol,data.split,'model_selection' if data.split=='VAL' else 'integrity_audit')
    model.eval()
    with torch.no_grad():z=np.concatenate([model(data.x[a:b]).numpy() for a,b in data.slices])
    metrics=classification_metrics(data.y.numpy(),z,data.mask.numpy())
    metrics['masked_recent_roots']=int((~data.mask).sum())
    for name,flag in [('inductive_unseen_user',data.unseen_user),('inductive_unseen_ip_context',data.unseen_ip),('inductive_unseen_user_and_ip',data.unseen_user&data.unseen_ip)]:
        metrics[name]=classification_metrics(data.y.numpy(),z,data.mask.numpy()&flag)
    return metrics,z

def write_predictions(path,data,z):
    with Path(path).open('x',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['organization','split','variant_id','asof','local_user_id','node_label','eligible_mask','logit','probability','unseen_user','has_unseen_ip'])
        probability=torch.sigmoid(torch.from_numpy(z)).numpy()
        for key,y,m,s,p,u,ip in zip(data.keys,data.y.tolist(),data.mask.tolist(),z.tolist(),probability.tolist(),data.unseen_user.tolist(),data.unseen_ip.tolist()):w.writerow([*key,y,m,s,p,u,ip])

def select_candidate(trials):
    require(bool(trials),'No comparator candidates')
    require(all(t['validation']['average_precision'] is not None and math.isfinite(t['validation']['average_precision']) and math.isfinite(t['validation']['bce']) for t in trials),'Undefined selection metrics')
    return sorted(trials,key=lambda t:(-t['validation']['average_precision'],t['validation']['bce'],t['candidate']['id']))[0]

def best_local(graph,comparator,protocol):
    require_use(protocol,'VAL','comparator_selection')
    a=graph['average_precision'];b=comparator['average_precision']
    require(a is not None and b is not None and math.isfinite(a) and math.isfinite(b),'Undefined best-local AP')
    require(graph['eligible']==comparator['eligible'] and graph['positive']==comparator['positive'] and graph['negative']==comparator['negative'],'Unequal evaluation populations')
    if b>a:return 'tabular_mlp'
    if b<a:return 'graphsage'
    return 'tabular_mlp' if comparator['bce']<graph['bce'] else 'graphsage'

def trial(config,candidate,train,val,protocol,output):
    require_training(train,protocol,train.organization)
    require(val.split=='VAL' and val.organization==train.organization,'Validation lineage mismatch')
    require_use(protocol,'VAL','early_stopping')
    require(not output.exists(),'Refusing to overwrite trial');output.mkdir(parents=True)
    seed=config['training']['initial_seed_base']+config['organizations'].index(train.organization)
    seed_all(seed);model=LocalTabularMLP(candidate['hidden_dim'],config['model']['dropout'])
    initial=state_digest(model.state_dict());weight=train.manifest['negative']/train.manifest['positive']
    pos_weight=torch.tensor(weight,dtype=torch.float32)
    opt=torch.optim.Adam(model.parameters(),lr=config['optimizer']['learning_rate'],weight_decay=config['optimizer']['weight_decay'])
    start=time.perf_counter();cpu=time.process_time();peak=psutil.Process().memory_info().rss
    best=None;best_ap=-math.inf;stale=0;updates=0
    for epoch in range(1,config['training']['max_epochs']+1):
        model.train();loss_total=0.;eligible=0;epoch_start=time.perf_counter()
        require_use(protocol,train.split,'fit')
        for a,b in train.slices:
            opt.zero_grad(set_to_none=True);z=model(train.x[a:b])
            loss=masked_bce(z,train.y[a:b],train.mask[a:b],pos_weight)
            if loss is None:continue
            require(torch.isfinite(loss).item(),'Nonfinite training loss');loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),config['training']['gradient_clip_norm']);opt.step();updates+=1
            n=int(train.mask[a:b].sum());eligible+=n;loss_total+=loss.item()*n
        require(eligible==train.manifest['positive']+train.manifest['negative'],'Missing TRAIN examples')
        metrics,_=evaluate_tabular(model,val,protocol);ap=metrics['average_precision']
        require(ap is not None and math.isfinite(ap),'Undefined validation AP')
        peak=max(peak,psutil.Process().memory_info().rss)
        row=dict(epoch=epoch,train_weighted_bce=loss_total/eligible,train_eligible=eligible,validation=metrics,epoch_seconds=time.perf_counter()-epoch_start,process_rss_bytes=psutil.Process().memory_info().rss)
        with (output/'epochs.jsonl').open('a',encoding='utf-8') as f: f.write(__import__('json').dumps(row)+'\n')
        if ap>best_ap+config['training']['min_ap_improvement']:
            best_ap=ap;stale=0
            state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            checkpoint=output/f'epoch_{epoch:03}.pt'
            saved=dict(format='phase6-local-tabular-checkpoint-v1',organization=train.organization,split_fitted='TRAIN',split_selected='VAL',candidate=candidate,epoch=epoch,seed=seed,model_state=state,state_digest=state_digest(state),model_config=config['model'],feature_names=config['features'],positive_weight=weight,train_identity_sha256=identity_digest(train.keys,train.y,train.mask),validation_identity_sha256=identity_digest(val.keys,val.y,val.mask),validation_metrics=metrics)
            torch.save(saved,checkpoint);best=dict(path=str(checkpoint),epoch=epoch,state_digest=saved['state_digest'])
        else:stale+=1
        print(__import__('json').dumps(dict(event='comparator_epoch',organization=train.organization,run=output.name,candidate=candidate['id'],epoch=epoch,val_ap=ap,stale=stale)),flush=True)
        if stale>=config['training']['early_stopping_patience']:break
    require(best is not None and updates>0 and best['state_digest']!=initial,'No parameter updates')
    saved=torch.load(best['path'],map_location='cpu',weights_only=True);model.load_state_dict(saved['model_state'],strict=True)
    metrics,z=evaluate_tabular(model,val,protocol)
    require(metrics==saved['validation_metrics'],'Safe reload metrics differ')
    write_predictions(output/'validation_predictions.csv',val,z)
    result=dict(organization=train.organization,candidate=candidate,seed=seed,initial_state_digest=initial,selected_state_digest=best['state_digest'],selected_epoch=best['epoch'],epochs_completed=epoch,optimizer_updates=updates,checkpoint=best['path'],validation=metrics,positive_weight_train_only=weight,training_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu,observed_training_rss_peak_bytes=peak,parameters=sum(p.numel() for p in model.parameters()))
    dump_json(output/'summary.json',result)
    return result,z

def train_select_repeat(config,train,val,protocol,output):
    trials=[];predictions={}
    for candidate in config['candidates']:
        r,z=trial(config,candidate,train,val,protocol,output/candidate['id']);trials.append(r);predictions[candidate['id']]=z
    winner=select_candidate(trials)
    repeat,rz=trial(config,winner['candidate'],train,val,protocol,output/'reproducibility_repeat')
    require(winner['selected_epoch']==repeat['selected_epoch'] and winner['selected_state_digest']==repeat['selected_state_digest'] and np.array_equal(predictions[winner['candidate']['id']],rz),'Exact comparator reproduction failed')
    require(sha(output/winner['candidate']['id']/'validation_predictions.csv')==sha(output/'reproducibility_repeat/validation_predictions.csv'),'Repeat CSV mismatch')
    saved=torch.load(winner['checkpoint'],map_location='cpu',weights_only=True);destination=output/'selected_model.pt';torch.save(saved,destination)
    model=LocalTabularMLP(winner['candidate']['hidden_dim'],config['model']['dropout']);model.load_state_dict(saved['model_state'])
    tr_metrics,tz=evaluate_tabular(model,train,protocol);write_predictions(output/'selected_train_predictions.csv',train,tz)
    result=dict(organization=train.organization,selected=winner,trials=trials,reproduction=repeat,exact_reproduction=True,checkpoint=str(destination),checkpoint_sha256=sha(destination),train_metrics=tr_metrics,total_trials_seconds=sum(t['training_seconds'] for t in trials)+repeat['training_seconds'])
    dump_json(output/'selection.json',result)
    return result,predictions[winner['candidate']['id']]
