"""Subphase 4 only: root MLP, paired validation and frozen best-local selection."""
import argparse,csv,json,platform,shutil,time
from pathlib import Path
import numpy as np
import psutil,torch,torch_geometric
from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.training_data import dump_json
from src.phase6.local_graphsage import LocalGraphSAGE,classification_metrics,state_digest
from src.phase6.comparator_data import FEATURES,load_tabular,identity_digest,export_tensor_data,TabularSplit
from src.phase6.non_graph_comparator import train_select_repeat,best_local,LocalTabularMLP,evaluate_tabular,write_predictions,select_candidate

BASE=ROOT/'reports/phase6/comparator'
CONFIG=ROOT/'configs/phase6/non_graph_comparator_v1.json'

def verify_preregistration():
    p=load(BASE/'preregistration_v1.json')
    require(sha(CONFIG)==p['config_sha256'],'Frozen comparator config changed')
    for path,digest in p['source_sha256'].items():require(sha(ROOT/path)==digest,'Preregistered source changed: '+path)
    config=load(CONFIG)
    require(config['features']==list(FEATURES) and config['feature_indices']==list(range(7)),'Feature allowlist changed')
    require(sha(ROOT/'configs/phase6/split_protocol_v1.json')==config['protocol_sha256'],'Frozen split protocol changed')
    return config

def verify_graph_predictions(path,data,recomputed,expected):
    """Paired key/label/mask equality BEFORE model comparison; counts alone insufficient."""
    z=[];n=0
    with path.open(newline='',encoding='utf-8') as f:
        for i,row in enumerate(csv.DictReader(f)):
            require(i<len(data.keys),'Extra GraphSAGE rows')
            key=(row['organization'],row['split'],row['variant_id'],row['asof'],int(row['local_user_id']))
            require(key==data.keys[i] and int(row['node_label'])==int(data.y[i]) and (row['eligible_mask']=='True')==bool(data.mask[i]),'Paired evaluation key/label/mask mismatch')
            require((row['unseen_user']=='True')==bool(data.unseen_user[i]) and (row['has_unseen_ip']=='True')==bool(data.unseen_ip[i]),'Evaluator subgroup mismatch')
            z.append(float(row['logit']));n+=1
    require(n==len(data.keys),'Missing GraphSAGE rows')
    z=np.asarray(z,dtype=np.float32)
    require(np.array_equal(z,recomputed),'Accepted GraphSAGE checkpoint/cache predictions differ')
    metrics=classification_metrics(data.y.numpy(),z,data.mask.numpy())
    require(all(metrics[k]==expected[k] for k in metrics),'Accepted GraphSAGE metrics differ')
    return dict(rows=n,eligible=int(data.mask.sum()),masked=int((~data.mask).sum()),
                identity_sha256=identity_digest(data.keys,data.y,data.mask),accepted_prediction_sha256=sha(path),
                exact_checkpoint_scores=True,paired_keys_labels_masks_equal=True)

def representative(data):
    # One predeclared real branch, matching the earlier integration branch policy.
    indices=[i for i,k in enumerate(data.keys) if k[2].startswith('CFV1_SO_CS_027_SEED1001_')]
    require(bool(indices),'No fixed representative branch')
    a,b=indices[0],indices[-1]+1
    require(indices==list(range(a,b)),'Representative rows not contiguous')
    m=dict(data.manifest);y=data.y[a:b];mask=data.mask[a:b]
    m.update(positive=int((y[mask]==1).sum()),negative=int((y[mask]==0).sum()),masked_recent_roots=int((~mask).sum()),scope='REPRESENTATIVE')
    slices=[(max(l,a)-a,min(r,b)-a) for l,r in data.slices if l<b and r>a]
    return TabularSplit(data.x[a:b],y,mask,data.keys[a:b],data.unseen_user[a:b],data.unseen_ip[a:b],slices,data.split,data.organization,m)

def run(org,mode):
    config=verify_preregistration();require(org in config['organizations'] and mode in {'full','representative'},'Unknown org/mode')
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    protocol=load(ROOT/'configs/phase6/split_protocol_v1.json')
    graph_record=next(r for r in load(ROOT/'reports/phase6/training/final_v1/summary.json')['models'] if r['organization']==org)
    out=BASE/(mode+'_v1')/org;require(not out.exists(),'Run exists; use new version');out.mkdir(parents=True)
    start=time.perf_counter();cpu=time.process_time()
    dump_json(out/'config_snapshot.json',config)
    dump_json(out/'feature_schema.json',dict(feature_names=list(FEATURES),root_only=True,accepted_schema_sha256=sha(ROOT/'configs/phase6/feature_allowlist_v1.json'),preprocessing=config['preprocessing'],feature_policy=config['feature_policy']))
    shutil.copyfile(ROOT/'configs/phase6/split_protocol_v1.json',out/'split_protocol.json')
    shutil.copyfile(BASE/'preregistration_v1.json',out/'preregistration_snapshot.json')
    checkpoint=Path(graph_record['checkpoint']);require(sha(checkpoint)==graph_record['checkpoint_sha256'],'Accepted graph checkpoint changed')
    saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
    graph=LocalGraphSAGE(graph_record['selected_candidate']['hidden_dim'],2,.1);graph.load_state_dict(saved['model_state']);graph.eval()
    require(state_digest(graph.state_dict())==graph_record['selected_state_digest'],'Graph weights changed')
    component=Path(graph_record['component_directory']);cache=component/'cache'/org
    require(saved['train_cache_sha256']==sha(cache/'TRAIN/manifest.json') and saved['validation_cache_sha256']==sha(cache/'VAL/manifest.json'),'Graph cache lineage changed')
    for split in ['TRAIN','VAL']:
        m=load(cache/split/'manifest.json')
        require(m['feature_schema_sha256']==sha(ROOT/'configs/phase6/feature_allowlist_v1.json') and m['sampler_config_sha256']==sha(ROOT/'configs/phase6/neighbor_sampling_v1.json'),'Accepted input contract changed')
    train,_=load_tabular(cache/'TRAIN',protocol,'TRAIN',org)
    val,gz=load_tabular(cache/'VAL',protocol,'VAL',org,graph)
    graph_csv=component/'models'/org/graph_record['selected_candidate']['id']/'validation_predictions.csv'
    fairness=verify_graph_predictions(graph_csv,val,gz,graph_record['validation'])
    preparation=time.perf_counter()-start
    if mode=='representative':
        train=representative(train);val=representative(val)
        config['training']['max_epochs']=3;config['training']['early_stopping_patience']=1
        dump_json(out/'representative_config_override.json',config)
    export_tensor_data(out/'train_root_features.pt',train);export_tensor_data(out/'validation_root_features.pt',val)
    dump_json(out/'input_provenance.json',dict(mode=mode,organization=org,protocol_sha256=config['protocol_sha256'],
        original_graph_checkpoint=str(checkpoint),original_graph_checkpoint_sha256=sha(checkpoint),
        cache_manifests={s:sha(cache/s/'manifest.json') for s in ['TRAIN','VAL']},
        cache_files_verified=2046,train_identity_sha256=identity_digest(train.keys,train.y,train.mask),validation_identity_sha256=identity_digest(val.keys,val.y,val.mask),
        full_paired_graph_validation=fairness,train_features_sha256=sha(out/'train_root_features.pt'),validation_features_sha256=sha(out/'validation_root_features.pt'),
        source_sha256=load(BASE/'preregistration_v1.json')['source_sha256'],test_inputs_opened=0))
    del graph
    selection,z=train_select_repeat(config,train,val,protocol,out/'models')
    write_predictions(out/'validation_predictions.csv',val,z)
    winner=best_local(graph_record['validation'],selection['selected']['validation'],protocol) if mode=='full' else None
    if winner:
        best_checkpoint=str(checkpoint) if winner=='graphsage' else selection['checkpoint']
        choice=dict(status='FROZEN_VAL_BEST_LOCAL_SELECTION',organization=org,detector=winner,checkpoint=best_checkpoint,checkpoint_sha256=sha(Path(best_checkpoint)),selection_rule=config['selection'],graphsage_validation=graph_record['validation'],comparator_validation=selection['selected']['validation'],paired_identity_sha256=fairness['identity_sha256'],calibrated_threshold=None)
        dump_json(out/'best_local_selection.json',choice)
    metrics=selection['selected']['validation']
    result=dict(status='PASS_FULL_SINGLE_ORGANIZATION_COMPARATOR' if mode=='full' else 'PASS_REPRESENTATIVE_ONLY',mode=mode,organization=org,
        comparator=selection,graphsage_validation=graph_record['validation'],best_local=winner,
        fairness=fairness,train_eligible=int(train.mask.sum()),validation_eligible=int(val.mask.sum()),
        train_masked=int((~train.mask).sum()),validation_masked=int((~val.mask).sum()),
        resources=dict(preparation_and_graph_verification_seconds=preparation,total_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu,
        peak_rss_bytes=getattr(psutil.Process().memory_info(),'peak_wset',psutil.Process().memory_info().rss),training_peak_rss_bytes=max(r['observed_training_rss_peak_bytes'] for r in selection['trials']+[selection['reproduction']]),
        logical_cpus=psutil.cpu_count(),torch_threads=2,device='cpu'),
        environment=dict(python=platform.python_version(),torch=torch.__version__,pyg=torch_geometric.__version__,numpy=np.__version__,platform=platform.platform()),
        protocol_sha256=config['protocol_sha256'],test_inputs_opened=0,threshold_calibration_performed=False)
    verify_preregistration();dump_json(out/'summary.json',result)
    dump_json(out/'artifact_sha256.json',{p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()})
    print(json.dumps(dict(event='completed',organization=org,mode=mode,best_local=winner,comparator_val_ap=metrics['average_precision'],seconds=result['resources']['total_seconds'])),flush=True)

def restored_data(path,manifest):
    p=torch.load(path,map_location='cpu',weights_only=True)
    return TabularSplit(p['x'],p['y'],p['mask'],p['keys'],p['unseen_user'].numpy(),p['unseen_ip'].numpy(),p['slices'],p['split'],p['organization'],manifest)

def finalize():
    config=verify_preregistration();protocol=load(ROOT/'configs/phase6/split_protocol_v1.json');out=BASE/'final_v1'
    require(not out.exists(),'Final output already exists')
    records=[]
    for org in config['organizations']:
        directory=BASE/'full_v1'/org;r=load(directory/'summary.json')
        require(r['status']=='PASS_FULL_SINGLE_ORGANIZATION_COMPARATOR' and r['mode']=='full' and r['test_inputs_opened']==0 and not r['threshold_calibration_performed'],'Not a completed full component')
        for p,h in load(directory/'artifact_sha256.json').items():require(sha(directory/p)==h,'Comparator artifact changed: '+p)
        require(r['fairness']['paired_keys_labels_masks_equal'] and r['fairness']['exact_checkpoint_scores'],'No fair paired validation')
        s=r['comparator'];w=s['selected'];repeat=s['reproduction']
        require(select_candidate(s['trials'])==w and w['selected_state_digest']==repeat['selected_state_digest'] and w['selected_epoch']==repeat['selected_epoch'] and s['exact_reproduction'],'VAL selection/repeat failed')
        require(sha(directory/'models'/w['candidate']['id']/'validation_predictions.csv')==sha(directory/'models/reproducibility_repeat/validation_predictions.csv')==sha(directory/'validation_predictions.csv'),'Exact prediction reproduction failed')
        require(sha(Path(s['checkpoint']))==s['checkpoint_sha256'],'Comparator checkpoint hash failed')
        cp=torch.load(s['checkpoint'],map_location='cpu',weights_only=True)
        require(cp['organization']==org and cp['split_fitted']=='TRAIN' and cp['split_selected']=='VAL' and cp['feature_names']==list(FEATURES) and cp['state_digest']==state_digest(cp['model_state']),'Comparator checkpoint lineage failed')
        require(all(torch.isfinite(t).all().item() for t in cp['model_state'].values()),'Nonfinite weights')
        source=next(x for x in load(ROOT/'reports/phase6/training/final_v1/summary.json')['models'] if x['organization']==org)
        cache=Path(source['component_directory'])/'cache'/org
        trm=load(cache/'TRAIN/manifest.json');vam=load(cache/'VAL/manifest.json')
        require(trm['variants']==vam['variants']==171 and trm['grids']==vam['grids']==1026,'Incomplete full inventory')
        require(r['train_eligible']==trm['positive']+trm['negative'] and r['validation_eligible']==vam['positive']+vam['negative'],'Incomplete eligible census')
        require(cp['positive_weight']==trm['negative']/trm['positive'],'Class weight leakage')
        data=restored_data(directory/'validation_root_features.pt',vam)
        require(identity_digest(data.keys,data.y,data.mask)==cp['validation_identity_sha256']==r['fairness']['identity_sha256'],'Paired identity digest failed')
        model=LocalTabularMLP(w['candidate']['hidden_dim'],config['model']['dropout']);model.load_state_dict(cp['model_state'])
        actual,z=evaluate_tabular(model,data,protocol);require(actual==w['validation'],'Independent safe reload evaluation differs')
        with (directory/'validation_predictions.csv').open(newline='',encoding='utf-8') as f:expected=np.asarray([float(row['logit']) for row in csv.DictReader(f)],dtype=np.float32)
        require(np.array_equal(expected,z),'Saved predictions differ after independent reload')
        require(r['best_local']==best_local(source['validation'],actual,protocol),'Incorrect best-local winner')
        records.append(r)
    preserved=load(BASE/'accepted_inputs_before_subphase4_v1.json')
    for path,h in preserved.items():require(sha(ROOT/path)==h,'Accepted artifact changed: '+path)
    require(load(ROOT/'reports/phase6/training/acceptance_v1.json')['status']=='USER_ACCEPTED','Subphase 3 not accepted')
    tests=load(BASE/'testing_results_v1.json');require(tests['status']=='PASS','Tests not complete')
    out.mkdir();(out/'models').mkdir()
    for r in records:
        org=r['organization'];src=Path(r['comparator']['checkpoint']);dst=out/'models'/f'{org}.pt';shutil.copyfile(src,dst)
        require(sha(src)==sha(dst),'Final checkpoint copy mismatch')
    summary=dict(status='PASS_SUBPHASE4_FULL_FIVE_COMPARATORS_AWAITING_USER_ACCEPTANCE',organizations=5,models=records,
        accepted_files_preserved=len(preserved),paired_val_examples=sum(r['validation_eligible'] for r in records),train_eligible=sum(r['train_eligible'] for r in records),
        protocol_sha256=config['protocol_sha256'],preregistration_sha256=sha(BASE/'preregistration_v1.json'),tests=tests,
        test_inputs_opened=0,threshold_calibration_performed=False,next_action='User acceptance of Subphase 4; Subphase 5 is not started')
    dump_json(out/'summary.json',summary)
    lines=['# Phase 6 Subphase 4 (6.2C): Non-Graph Local Comparator and Best-Local Selection','',
      '**Technical gate: PASS; user acceptance pending.** Subphase 3 is USER_ACCEPTED in the new append-only training/acceptance_v1.json record.','',
      '## Frozen design and fairness','',
      'The versioned preregistration was written before comparator training or comparison. Each organization independently fits a two-hidden-layer tabular MLP using the seven unchanged root User behavioral features. The constant node type is omitted. Distinct-IP counts describe only the User\'s own login history; no IP-node attributes, neighbor-user behavior, graph edges or neighborhood aggregation enters the comparator. Input projection reuses immutable accepted caches. No accepted pipeline, graph runtime, dataset, split, grid, mask or feature transform changed.','',
      'Two widths (16/32), two hidden transformations, dropout 0.1, Adam learning rate 0.003, weight decay 0.0001, maximum 12 epochs, patience 3, weighted TRAIN BCE and deterministic chronological minibatches match the accepted GraphSAGE search budget. Class weight uses only that local TRAIN split. No learned preprocessing is fitted. Seed base 64040 plus organization index; CPU two Torch threads, deterministic algorithms. Parameter counts differ because graph aggregation is removed.','',
      'Per-organization best-local rule: greatest VAL tied-score average precision, then lowest unweighted VAL BCE, then GraphSAGE on an exact tie. Candidate ties use candidate ID. Early stopping retains the earlier epoch unless AP improves by more than 1e-6. The primary 1% FPR target is unchanged; no final thresholds or fixed-FPR recall are computed here.','',
      'All five accepted GraphSAGE checkpoints were reloaded without retraining. Every full VAL logit matched the preserved original CSV exactly, together with ordered organization/branch/User/time keys, labels, masks and inductive flags. Both detectors use exactly the same eligible examples, metrics and evaluation unit.','',
      '## Exact full-data comparison','',
      '| Org | TRAIN eligible | VAL eligible | MLP width / epoch | GraphSAGE AP | MLP AP | GraphSAGE BCE | MLP BCE | Best local |','|---|---:|---:|---|---:|---:|---:|---:|---|']
    for r in records:
        c=r['comparator']['selected'];g=r['graphsage_validation'];v=c['validation']
        lines.append(f"| {r['organization']} | {r['train_eligible']} | {r['validation_eligible']} | {c['candidate']['hidden_dim']} / {c['selected_epoch']} | {g['average_precision']:.12f} | {v['average_precision']:.12f} | {g['bce']:.12f} | {v['bce']:.12f} | {r['best_local']} |")
    lines+=['','## Supporting nominal diagnostics and resources','',
      'Precision/recall/F1 below use nominal probability 0.5 only, not calibrated alert operating points. The complete unrounded values, TRAIN metrics and inductive subgroup metrics are saved in summary.json. Training RSS includes in-memory input arrays and host allocator overhead. Timings are observed on the shared host, not an exclusive benchmark. Preparation includes loading/hashing caches and recomputing GraphSAGE VAL scores.','',
      '| Org | MLP P@.5 | MLP R@.5 | MLP F1@.5 | Selected trial s | All trials+repeat s | Preparation s | Training RSS MiB | Whole-process peak MiB |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in records:
        c=r['comparator'];w=c['selected'];v=w['validation'];rs=r['resources']
        lines.append(f"| {r['organization']} | {v['precision_at_0_5']:.9f} | {v['recall_at_0_5']:.9f} | {v['f1_at_0_5']:.9f} | {w['training_seconds']:.3f} | {c['total_trials_seconds']:.3f} | {rs['preparation_and_graph_verification_seconds']:.3f} | {rs['training_peak_rss_bytes']/1048576:.3f} | {rs['peak_rss_bytes']/1048576:.3f} |")
    lines+=['','## Artifacts and reproducibility','']
    for r in records:
        org=r['organization'];lines.append(f'- {org}: selected comparator `reports/phase6/comparator/final_v1/models/{org}.pt`; all candidate epochs/checkpoints, repeated fit and predictions, configuration/schema/protocol snapshots, resource measurements, paired provenance and best-local record: `reports/phase6/comparator/full_v1/{org}/`.')
    lines+=['','Every selected candidate was independently retrained from its fixed seed; selected epoch, tensor-state digest, every VAL score and the full VAL prediction CSV reproduced exactly. Final verification safely reloads all five models and independently recomputes every saved VAL score. Both model families remain preserved regardless of the winner.','',
      f"The full inventory is 171 TRAIN + 171 VAL branches and 1026 grid times per split per organization; {summary['train_eligible']} TRAIN and {summary['paired_val_examples']} paired eligible VAL User-times in total. All 10260 original cache files were hash-verified. {len(preserved)} pre-existing accepted/support artifacts remained byte-identical.",'',
      '## Tests and evidence scope','',
      'See ../testing_results_v1.json for exact commands, pass counts and exclusions. Tiny synthetic training checks are smoke tests. representative_v1/Org1 is one predetermined real TRAIN/VAL branch, capped at three epochs, and cannot satisfy the full gate. Only the five completed full_v1 components supply the comparison table and final gate. Tests check input allowlisting, independence from graph edges/context, labels/metadata isolation, masks, chronological guards, same-example fairness, metric ties, selection, and exact repetition.','',
      '## Limitations and next action','',
      'VAL selects candidates and best-local models; these are not final TEST performance estimates. Repeated backgrounds and only three temporal blocks per split are dependent. Clean-negative candidates do not prove benignness. AP is average precision with tied scores grouped, not trapezoidal PR-AUC. Two modest architectures and one initialization per organization do not exhaust tabular methods or provide initialization confidence intervals. This is an eligible comparator, not a claim of globally optimal local detection. Accepted GraphSAGE metrics were already visible before this new preregistration. Root tabular arrays are local private audit artifacts, never a cross-organization identity index. No million-node training-scale claim is inferred.','',
      'Best-local selection by AP does not assert the same ordering at the later 1% FPR operating point. Preserve the recorded choice and both families for Subphase 5 calibration without choosing from TEST outcomes. No TEST branch files/outcomes were opened, no final thresholds were calibrated, and no continuous inference, indicator sharing, federation, DP or blockchain was implemented.','',
      f"Frozen protocol SHA256: `{config['protocol_sha256']}`. Its version-control gate remains required before final TEST evaluation; this subphase does not certify a commit.",'',
      'Next exact action: user review and acceptance of Subphase 4. Subphase 5 has not started.']
    (out/'ACCEPTANCE_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    dump_json(out/'artifact_sha256.json',{p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()})
    progress=load(ROOT/'reports/phase6/progress_v4.json');progress['version']='phase6-progress-v5'
    progress['subphases']['3']={'status':'USER_ACCEPTED','evidence':'reports/phase6/training/acceptance_v1.json'}
    progress['subphases']['4']={'status':'TECHNICAL_GATE_PASS_AWAITING_USER_ACCEPTANCE','evidence':'reports/phase6/comparator/final_v1/ACCEPTANCE_REPORT.md','organizations':5}
    progress['next_exact_action']=summary['next_action'];dump_json(ROOT/'reports/phase6/progress_v5.json',progress)
    print(json.dumps(dict(status=summary['status'],organizations=5,preserved=len(preserved))),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--organization');p.add_argument('--mode',choices=['full','representative'],default='full');p.add_argument('--finalize',action='store_true');a=p.parse_args()
    if a.finalize:
        torch.set_num_threads(2);torch.set_num_interop_threads(1);finalize()
    else:run(a.organization,a.mode)
