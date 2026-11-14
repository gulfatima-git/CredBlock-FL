"""Independent CPU local training. No TEST, calibration or federated operations."""
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import random
import time

import numpy as np
import psutil
import torch

from src.phase6.local_graphsage import LocalGraphSAGE,masked_bce,state_digest,classification_metrics
from src.phase6.readiness import load,sha
from src.phase6.temporal_protocol import bounds,require,require_use
from src.phase6.training_data import cached_batches,dump_json


def seed_all(seed):
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def evaluate(model,directory,protocol,organization,save_path=None,split='VAL'):
    require(split in {'TRAIN','VAL'},'Evaluation subsystem never opens TEST')
    require_use(protocol,split,'model_selection' if split=='VAL' else 'integrity_audit')
    model.eval()
    labels=[];logits=[];masks=[];new_users=[];new_ips=[]
    output=None;writer=None
    if save_path is not None:
        output=Path(save_path).open('x',newline='',encoding='utf-8')
        writer=csv.writer(output)
        writer.writerow(['organization','split','variant_id','asof','local_user_id','node_label','eligible_mask','logit','probability','unseen_user','has_unseen_ip'])
    try:
        with torch.no_grad():
            for batch,payload in cached_batches(directory,protocol,split,organization):
                score=model(batch).cpu().numpy()
                y=batch.supervision.y.numpy();mask=batch.supervision.eligible_mask.numpy()
                user=payload['unseen_user'].numpy();ip=payload['unseen_ip'].numpy()
                labels.append(y);logits.append(score);masks.append(mask);new_users.append(user);new_ips.append(ip)
                if writer is not None:
                    probabilities=torch.sigmoid(torch.from_numpy(score)).numpy()
                    p=batch.provenance
                    for values in zip(payload['user_ids'].tolist(),y.tolist(),mask.tolist(),score.tolist(),probabilities.tolist(),user.tolist(),ip.tolist()):
                        writer.writerow([organization,split,p['variant_id'],p['asof'],*values])
    finally:
        if output is not None: output.close()
    require(bool(labels),'Empty validation cache')
    y,z,mask,user,ip=(np.concatenate(v) for v in [labels,logits,masks,new_users,new_ips])
    result=classification_metrics(y,z,mask)
    result['masked_recent_roots']=int((~mask).sum())
    result['inductive_unseen_user']=classification_metrics(y,z,mask&user)
    result['inductive_unseen_ip_context']=classification_metrics(y,z,mask&ip)
    result['inductive_unseen_user_and_ip']=classification_metrics(y,z,mask&user&ip)
    return result,z


def trial(config,candidate,organization,train_directory,val_directory,protocol,output,journal=None):
    require_use(protocol,'TRAIN','fit')
    require_use(protocol,'VAL','early_stopping')
    require(not output.exists(),'Trial exists; refusing overwrite')
    output.mkdir(parents=True)
    seed=config['training']['initial_seed_base']+config['organizations'].index(organization)
    seed_all(seed)
    model=LocalGraphSAGE(candidate['hidden_dim'],config['model']['num_layers'],config['model']['dropout'])
    initial_digest=state_digest(model.state_dict())
    optimizer=torch.optim.Adam(model.parameters(),lr=config['optimizer']['learning_rate'],weight_decay=config['optimizer']['weight_decay'])
    train_manifest=load(train_directory/'manifest.json')
    require(train_manifest['split']=='TRAIN' and train_manifest['organization']==organization,'Class weight input not local TRAIN')
    weight=train_manifest['negative']/train_manifest['positive']
    pos_weight=torch.tensor(weight,dtype=torch.float32)
    best_ap=-math.inf;stale=0;best=None;history=[];updates=0;first_layer_gradient_updates=0
    max_rss=psutil.Process().memory_info().rss
    start=time.perf_counter();cpu_start=time.process_time()
    for epoch in range(1,config['training']['max_epochs']+1):
        epoch_start=time.perf_counter()
        model.train();total_loss=0.0;eligible=0;epoch_updates=0
        for batch,_ in cached_batches(train_directory,protocol,'TRAIN',organization):
            require_use(protocol,batch.provenance['split'],'fit')
            require(batch.provenance['organization']==organization,'Nonlocal optimizer input')
            _,cutoff=bounds(protocol,'TRAIN')
            require(datetime.fromisoformat(batch.provenance['asof'])<cutoff,'Future training example')
            optimizer.zero_grad(set_to_none=True)
            prediction=model(batch)
            loss=masked_bce(prediction,batch.supervision.y,batch.supervision.eligible_mask,pos_weight)
            if loss is None: continue
            require(torch.isfinite(loss).item(),'Nonfinite loss')
            loss.backward()
            first_layer_gradient_updates+=int(any(p.grad is not None and p.grad.abs().sum().item()>0 for p in model.layers[0].parameters()))
            torch.nn.utils.clip_grad_norm_(model.parameters(),config['training']['gradient_clip_norm'])
            optimizer.step()
            count=int(batch.supervision.eligible_mask.sum())
            total_loss+=loss.item()*count;eligible+=count;epoch_updates+=1;updates+=1
            max_rss=max(max_rss,psutil.Process().memory_info().rss)
        require(eligible==train_manifest['positive']+train_manifest['negative'],'Incomplete TRAIN epoch')
        metrics,_=evaluate(model,val_directory,protocol,organization)
        ap=metrics['average_precision']
        require(ap is not None and math.isfinite(ap),'Undefined VAL selection metric')
        row=dict(epoch=epoch,train_weighted_bce=total_loss/eligible,train_eligible=eligible,
                 optimizer_updates=epoch_updates,validation=metrics,epoch_seconds=time.perf_counter()-epoch_start,
                 process_rss_bytes=psutil.Process().memory_info().rss)
        history.append(row)
        with (output/'epochs.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(row)+'\n')
        if ap>best_ap+config['training']['min_ap_improvement']:
            best_ap=ap;stale=0
            checkpoint=output/f'epoch_{epoch:03}.pt'
            state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            checkpoint_data=dict(format='phase6-local-graphsage-checkpoint-v1',organization=organization,
                split_fitted='TRAIN',split_selected='VAL',candidate=candidate,epoch=epoch,seed=seed,
                model_state=state,optimizer_state=optimizer.state_dict(),state_digest=state_digest(state),
                model_config=config['model'],train_cache_sha256=sha(train_directory/'manifest.json'),
                validation_cache_sha256=sha(val_directory/'manifest.json'),train_cutoff=protocol['splits_half_open']['TRAIN'][1],
                positive_weight=weight,validation_metrics=metrics)
            torch.save(checkpoint_data,checkpoint)
            best=dict(path=str(checkpoint),epoch=epoch,validation_metrics=metrics,state_digest=checkpoint_data['state_digest'])
        else:
            stale+=1
        if journal is not None:
            journal(dict(event='epoch',organization=organization,candidate=candidate['id'],run=output.name,
                         epoch=epoch,train_loss=row['train_weighted_bce'],val_ap=ap,val_bce=metrics['bce'],stale=stale))
        if stale>=config['training']['early_stopping_patience']:
            break
    require(best is not None and updates>0 and first_layer_gradient_updates>0,'No trained checkpoint or first-layer gradient')
    saved=torch.load(best['path'],map_location='cpu',weights_only=True)
    model.load_state_dict(saved['model_state'],strict=True)
    require(state_digest(model.state_dict())==best['state_digest']!=initial_digest,'Checkpoint load/update verification failed')
    final_metrics,final_scores=evaluate(model,val_directory,protocol,organization,output/'validation_predictions.csv')
    require(abs(final_metrics['average_precision']-best['validation_metrics']['average_precision'])<1e-12,'Restored checkpoint metrics differ')
    summary=dict(organization=organization,candidate=candidate,initialization_seed=seed,initial_state_digest=initial_digest,
        selected_state_digest=best['state_digest'],selected_epoch=best['epoch'],epochs_completed=len(history),
        optimizer_updates=updates,positive_weight_train_only=weight,training_seconds=time.perf_counter()-start,
        first_layer_gradient_updates=first_layer_gradient_updates,
        process_cpu_seconds=time.process_time()-cpu_start,observed_training_rss_peak_bytes=max_rss,
        process_peak_rss_bytes=getattr(psutil.Process().memory_info(),'peak_wset',max_rss),
        checkpoint=best['path'],validation=final_metrics,device='cpu',early_stop_split='VAL',selection_split='VAL')
    dump_json(output/'summary.json',summary)
    return summary,final_scores


def select_and_repeat(config,organization,train_directory,val_directory,protocol,output,journal=None):
    require(not output.exists(),'Organization training output exists')
    output.mkdir(parents=True)
    trials=[];scores={}
    for candidate in config['candidates']:
        summary,prediction=trial(config,candidate,organization,train_directory,val_directory,protocol,output/candidate['id'],journal)
        trials.append(summary);scores[candidate['id']]=prediction
    require_use(protocol,'VAL','hyperparameter_selection')
    winner=sorted(trials,key=lambda t:(-t['validation']['average_precision'],t['validation']['bce'],t['candidate']['id']))[0]
    repeated,repeated_scores=trial(config,winner['candidate'],organization,train_directory,val_directory,protocol,output/'reproducibility_repeat',journal)
    require(winner['selected_state_digest']==repeated['selected_state_digest'] and winner['selected_epoch']==repeated['selected_epoch']
            and np.array_equal(scores[winner['candidate']['id']],repeated_scores),'Full training reproducibility failed')
    # Save a standalone selected state only after repeated training verifies it.
    checkpoint=torch.load(winner['checkpoint'],map_location='cpu',weights_only=True)
    destination=output/'selected_model.pt'
    torch.save(checkpoint,destination)
    require(sha(destination),'Checkpoint missing')
    selected_model=LocalGraphSAGE(winner['candidate']['hidden_dim'],config['model']['num_layers'],config['model']['dropout'])
    selected_model.load_state_dict(checkpoint['model_state'],strict=True)
    train_metrics,_=evaluate(selected_model,train_directory,protocol,organization,output/'selected_train_predictions.csv',split='TRAIN')
    result=dict(organization=organization,status='PASS_LOCAL_TRAINING_AND_EXACT_REPRODUCTION',selected_candidate=winner['candidate'],
        checkpoint=str(destination),checkpoint_sha256=sha(destination),selected_epoch=winner['selected_epoch'],
        initialization_seed=winner['initialization_seed'],selected_state_digest=winner['selected_state_digest'],
        validation=winner['validation'],exact_repeat_state_and_validation_scores=True,
        selected_model_train_metrics=train_metrics,
        trial_summaries=trials,reproduction_summary=repeated,
        all_trials_seconds=sum(t['training_seconds'] for t in trials)+repeated['training_seconds'],
        selected_run_seconds=winner['training_seconds'],observed_training_rss_peak_bytes=max(t['observed_training_rss_peak_bytes'] for t in trials+[repeated]))
    dump_json(output/'selection.json',result)
    return result
