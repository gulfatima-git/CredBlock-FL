"""Subphase 5: ten VAL-only frozen thresholds; no model fitting or reselection."""
import argparse,csv,json,math,platform,re,shutil,time
from pathlib import Path
import numpy as np
import psutil,torch
from src.phase6.readiness import ROOT,load,sha
from src.phase6.temporal_protocol import require
from src.phase6.comparator_data import validate_identity,identity_digest
from src.phase6.local_graphsage import classification_metrics,state_digest
from src.phase6.training_data import dump_json
from src.phase6.fpr_calibration import require_val,calibrate_negatives,threshold_metrics,seal_threshold,load_frozen_threshold,decisions,canonical_digest

BASE=ROOT/'reports/phase6/calibration'
CONFIG=ROOT/'configs/phase6/fpr_calibration_v1.json'
COLUMNS=['organization','split','variant_id','asof','local_user_id','node_label','eligible_mask','logit','probability','unseen_user','has_unseen_ip']

def read_val_predictions(path,protocol,organization,split='VAL'):
    require_val(protocol,split) # reject TEST before any filesystem access
    require(not any(p.upper()=='TEST' or '_TEST' in p.upper() for p in Path(path).parts),'TEST path forbidden')
    keys=[];labels=[];masks=[];scores=[];users=[];ips=[]
    with Path(path).open(newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f);require(reader.fieldnames==COLUMNS,'Prediction schema mismatch')
        for row in reader:
            require(row['organization']==organization and row['split']=='VAL','Nonlocal or non-VAL prediction')
            require(all(row[k] in {'True','False'} for k in ['eligible_mask','unseen_user','has_unseen_ip']),'Invalid boolean metadata')
            keys.append((organization,'VAL',row['variant_id'],row['asof'],int(row['local_user_id'])))
            labels.append(int(row['node_label']));masks.append(row['eligible_mask']=='True');scores.append(float(row['logit']))
            users.append(row['unseen_user']=='True');ips.append(row['has_unseen_ip']=='True')
    y=np.asarray(labels,dtype=np.int64);mask=np.asarray(masks,dtype=bool);z=np.asarray(scores,dtype=np.float64)
    require(len(z)>0 and np.isfinite(z).all(),'Empty/nonfinite prediction source')
    validate_identity(keys,torch.from_numpy(y),torch.from_numpy(mask),organization,'VAL',protocol)
    return dict(keys=keys,y=y,mask=mask,z=z,unseen_user=np.asarray(users,dtype=bool),unseen_ip=np.asarray(ips,dtype=bool))

def verify_pair(a,b):
    require(a['keys']==b['keys'] and all(np.array_equal(a[k],b[k]) for k in ['y','mask','unseen_user','unseen_ip']),'Detector examples/labels/masks differ')

def metric_groups(data,threshold):
    flags={f'seed_{seed}':np.asarray([f'_SEED{seed}_' in key[2] for key in data['keys']],dtype=bool) for seed in [1001,1002,1003]}
    flags.update(unseen_user=data['unseen_user'],unseen_ip_context=data['unseen_ip'])
    return {name:threshold_metrics(np.where(flag,data['y'],-1),data['mask']&flag,data['z'],threshold) for name,flag in flags.items()}

def verify_freeze():
    p=load(BASE/'preregistration_v1.json');require(sha(CONFIG)==p['configuration_sha256'],'Frozen calibration configuration changed')
    for path,h in p['source_sha256'].items():require(sha(ROOT/path)==h,'Calibration source changed: '+path)
    config=load(CONFIG);protocol=load(ROOT/'configs/phase6/split_protocol_v1.json')
    require(sha(ROOT/'configs/phase6/split_protocol_v1.json')==config['protocol_sha256'],'Accepted protocol changed')
    require(config['target_fpr']=={'numerator':1,'denominator':100} and config['calibration_split']=='VAL','Changed operating point')
    return config,protocol,p

def run(output):
    require(not output.exists(),'Threshold output already exists; frozen artifacts cannot be recalibrated or overwritten')
    config,protocol,prereg=verify_freeze()
    require(load(ROOT/'reports/phase6/comparator/acceptance_v1.json')['status']=='USER_ACCEPTED','Subphase 4 not accepted')
    tests=load(BASE/'testing_results_v1.json');require(tests['status']=='PASS','Calibration tests not complete')
    graph_summary=load(ROOT/'reports/phase6/training/final_v1/summary.json')
    comparison=load(ROOT/'reports/phase6/comparator/final_v1/summary.json')
    require(graph_summary['organizations']==comparison['organizations']==5 and comparison['status'].startswith('PASS_SUBPHASE4_FULL'),'Full accepted results required')
    start=time.perf_counter();cpu=time.process_time();records=[];inputs={};locked={}
    for org in config['organizations']:
        g=next(r for r in graph_summary['models'] if r['organization']==org)
        c=next(r for r in comparison['models'] if r['organization']==org)
        choice_path=ROOT/'reports/phase6/comparator/full_v1'/org/'best_local_selection.json';choice=load(choice_path)
        require(choice['detector']=='graphsage' and choice['checkpoint_sha256']==g['checkpoint_sha256'],'Accepted best-local changed')
        locked[org]=dict(detector='graphsage',checkpoint_sha256=choice['checkpoint_sha256'],selection_record_sha256=sha(choice_path),threshold_reselection=False)
        graph_csv=Path(g['component_directory'])/'models'/org/g['selected_candidate']['id']/'validation_predictions.csv'
        mlp_csv=ROOT/'reports/phase6/comparator/full_v1'/org/'validation_predictions.csv'
        sources=[('graphsage',graph_csv,Path(g['checkpoint']),g['checkpoint_sha256'],g['validation']),
                 ('tabular_mlp',mlp_csv,ROOT/'reports/phase6/comparator/final_v1/models'/f'{org}.pt',c['comparator']['checkpoint_sha256'],c['comparator']['selected']['validation'])]
        paired=[]
        for detector,path,checkpoint,expected_hash,expected_metrics in sources:
            require(sha(checkpoint)==expected_hash,'Accepted checkpoint hash mismatch')
            data=read_val_predictions(path,protocol,org);paired.append(data)
            metrics=classification_metrics(data['y'],data['z'],data['mask'])
            require(all(metrics[k]==expected_metrics[k] for k in metrics),'Accepted validation metrics changed')
            require(len({key[2] for key in data['keys']})==171 and len({key[2:4] for key in data['keys']})==1026,'Incomplete fixed-grid validation coverage')
            saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
            require(saved['organization']==org and saved['split_fitted']=='TRAIN' and saved['split_selected']=='VAL' and state_digest(saved['model_state'])==saved['state_digest'],'Accepted model version mismatch')
            negative=data['z'][data['mask']&(data['y']==0)]
            calibrated=calibrate_negatives(negative,protocol)
            repeated=calibrate_negatives(negative[::-1],protocol)
            permuted=calibrate_negatives(np.random.default_rng(65050).permutation(negative),protocol)
            require(calibrated==repeated==permuted,'Threshold depends on input order')
            operating=threshold_metrics(data['y'],data['mask'],data['z'],calibrated['threshold'])
            require(operating['fp']==calibrated['achieved_fp']<=calibrated['fp_budget'] and operating['negative']==len(negative),'Calibration denominator/budget mismatch')
            for item in [path,checkpoint,choice_path]:inputs[str(item.relative_to(ROOT))]=sha(item)
            model_config_path=ROOT/('configs/phase6/local_training_v1.json' if detector=='graphsage' else 'configs/phase6/non_graph_comparator_v1.json')
            payload=dict(status='FROZEN_VAL_THRESHOLD',version='phase6-val-threshold-v1',organization=org,detector=detector,
                calibration_split='VAL',validation_period=protocol['splits_half_open']['VAL'],
                observed_first_grid=min(k[3] for k in data['keys']),observed_last_grid=max(k[3] for k in data['keys']),
                primary_unit=protocol['scoring']['primary_unit'],denominator_definition=config['negative_denominator'],
                target_fpr=config['target_fpr'],score_domain=config['score_domain'],decision=config['decision'],
                configuration_sha256=sha(CONFIG),protocol_sha256=config['protocol_sha256'],source_sha256=prereg['source_sha256'],
                model_path=str(checkpoint),model_sha256=expected_hash,model_configuration_sha256=sha(model_config_path),
                model_version={k:saved[k] for k in ['format','candidate','epoch','seed','state_digest']},
                feature_schema_sha256=sha(ROOT/'configs/phase6/feature_allowlist_v1.json'),
                prediction_source=str(path),prediction_source_sha256=sha(path),
                paired_example_identity_sha256=identity_digest(data['keys'],torch.from_numpy(data['y']),torch.from_numpy(data['mask'])),
                calibration=calibrated,operating_metrics=operating,unthresholded_metrics=metrics,
                subgroup_metrics=metric_groups(data,calibrated['threshold']),
                reproducibility=dict(reversed_negatives_identical=True,permuted_negatives_identical=True,seed=65050),
                best_local_locked=locked[org],test_used=False)
            records.append(seal_threshold(payload))
        verify_pair(*paired)
        require(records[-2]['paired_example_identity_sha256']==records[-1]['paired_example_identity_sha256']==c['fairness']['identity_sha256'],'Accepted comparison example identity changed')
        print(json.dumps(dict(event='organization_calibrated',organization=org,best_local='graphsage',detectors=2)),flush=True)
    preserved=load(BASE/'accepted_inputs_before_subphase5_v1.json')
    for path,h in preserved.items():require(sha(ROOT/path)==h,'Accepted artifact changed: '+path)
    verify_freeze();require(len(records)==10,'Ten thresholds required')
    output.mkdir(parents=True);(output/'thresholds').mkdir()
    shutil.copyfile(CONFIG,output/'config_snapshot.json')
    shutil.copyfile(ROOT/'configs/phase6/split_protocol_v1.json',output/'split_protocol.json')
    shutil.copyfile(BASE/'preregistration_v1.json',output/'preregistration_snapshot.json')
    for r in records:
        path=output/'thresholds'/f"{r['organization']}_{r['detector']}.json";dump_json(path,r)
        restored=load_frozen_threshold(path,organization=r['organization'],detector=r['detector'],model_sha256=r['model_sha256'],protocol_sha256=r['protocol_sha256'],configuration_sha256=sha(CONFIG))
        data=read_val_predictions(Path(r['prediction_source']),protocol,r['organization'])
        actual=threshold_metrics(data['y'],data['mask'],data['z'],restored['calibration']['threshold'])
        require(actual==r['operating_metrics'],'Frozen loader decision/metric reproduction failed')
    aggregate={}
    for detector in config['detectors']:
        rows=[r['operating_metrics'] for r in records if r['detector']==detector]
        counts={k:sum(row[k] for row in rows) for k in ['tp','fp','tn','fn']};tp,fp,tn,fn=(counts[k] for k in ['tp','fp','tn','fn'])
        aggregate[detector]=dict(macro={k:sum(row[k] for row in rows)/5 if all(row[k] is not None for row in rows) else None for k in ['fpr','recall','precision','f1']},
          pooled=dict(**counts,fpr=fp/(fp+tn),recall=tp/(tp+fn),precision=tp/(tp+fp) if tp+fp else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None),
          per_organization_fp_budget_enforced=True,interpretation='Descriptive dependent benchmark counts; no cross-organization identity join or IID uncertainty claim')
    summary=dict(status='PASS_SUBPHASE5_TEN_VAL_THRESHOLDS_AWAITING_USER_ACCEPTANCE',organizations=5,detectors=2,
        thresholds=records,aggregation=aggregate,best_local_locked=locked,accepted_files_preserved=len(preserved),
        protocol_sha256=config['protocol_sha256'],configuration_sha256=sha(CONFIG),tests=tests,
        resources=dict(elapsed_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu,peak_rss_bytes=getattr(psutil.Process().memory_info(),'peak_wset',psutil.Process().memory_info().rss)),
        environment=dict(python=platform.python_version(),numpy=np.__version__,torch=torch.__version__),
        test_inputs_opened=0,model_training_or_selection_performed=False,continuous_inference_started=False,
        next_action='User acceptance of Subphase 5; Subphase 6 not started',version_control_before_test='REQUIRED; not certified by this calibration')
    dump_json(output/'summary.json',summary);dump_json(output/'input_sha256.json',inputs)
    dump_json(output/'best_local_locked.json',locked)
    lines=['# Phase 6 Subphase 5 (6.3): Fixed-FPR Threshold Calibration','',
      '**Technical gate: PASS; user acceptance pending.** Subphase 4 is USER_ACCEPTED in the new append-only comparator/acceptance_v1.json record.','',
      '## Frozen operating rule','',
      'The primary target remains 1% empirical FPR on eligible y=0 VAL User-windows. Each organization and detector is calibrated separately using negative logits only. FP budget is exact integer division N_negative // 100. Masks, fixed-grid User-time identities, alternative branches and split bounds are unchanged. Positives are used only after the threshold is fixed to calculate operating metrics.','',
      'Decision: **binary64 logit >= binary64 threshold**. Promote model scores before comparison using the supplied helper. Thresholds are the immediate binary64 successor of the first disallowed negative-score boundary; all equal-score ties stay together. Lowering a threshold by one binary64 ULP admits more negatives than permitted. The probability column is not used because sigmoid rounding can merge distinct logits. Authoritative hexadecimal encodings are saved beside round-trip decimal values. An explicit no-alert sentinel handles the case with no qualifying finite threshold.','',
      'With fewer than 100 eligible negatives, the protocol permits only zero FPs and flags the target as unresolvable at resolution 1/N. Zero eligible negatives is an error, not a fabricated threshold. Undefined metrics are null. No extra FPR sensitivity targets were introduced.','',
      '## Full validation calibration','',
      '| Organization | Detector | Authoritative logit threshold | FP / N negative | FP budget | Achieved FPR | Recall | Precision | F1 |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in records:
        c=r['calibration'];m=r['operating_metrics'];t=c['threshold'];threshold=repr(t['value']) if t['kind']=='finite' else 'NO_ALERT'
        show=lambda x:'N/A' if x is None else f'{x:.12f}'
        lines.append(f"| {r['organization']} | {r['detector']} | {threshold} | {m['fp']} / {m['negative']} | {c['fp_budget']} | {show(m['fpr'])} | {show(m['recall'])} | {show(m['precision'])} | {show(m['f1'])} |")
    lines+=['','All ten thresholds satisfy their integer budgets. Full TP/FP/TN/FN counts, negative-score tie sizes, unused budgets, 1/N resolution, unchanged AP/BCE, campaign-seed and unseen-node-context breakdowns, per-organization macro and pooled results are in summary.json. **GraphSAGE remains the accepted best-local detector for Org1–Org5, irrespective of calibrated recall.**','',
      '## Provenance and reproducibility','',
      'thresholds/ contains ten sealed JSON artifacts keyed by organization/detector. Each records the selected model version/checkpoint hash, source/configuration/protocol/schema hashes, accepted prediction hash, declared VAL period and observed grid range, denominator definition, boundary and tie policy, metrics, locked best-local record and reproducibility evidence. input_sha256.json records every model, prediction and selection input. Original model/configuration files remain authoritative and unchanged; no models were trained.','',
      'Each calibration reproduced identically with reversed negatives and a fixed random permutation. All ten sealed artifacts were reloaded through an API with no prediction/label/recalibration parameters; decisions and every confusion-derived metric reproduced exactly on the accepted full VAL files. Calibration guards reject TRAIN and TEST before file access. Existing output directories are rejected before inputs are opened. Model selection is not called by this subsystem.','',
      f"{len(preserved)} inventoried prior accepted/support files were verified byte-identical, including both model families, full predictions, histories, repeats, selected model records and prior acceptance evidence.",'',
      '## Tests and limitations','',
      'See ../testing_results_v1.json for exact commands and scope. Unit tests cover integer budgets, tied boundaries, maximal permissiveness, binary32 downcast protection, no-alert sentinel, empty negatives, small samples, masking, no positives, reproducibility, seals and identity checks, TEST-before-I/O guards, paired-cohort checks and overwrite rejection. The actual full run independently verifies all ten thresholds and loaders; synthetic tests alone are not calibration evidence.','',
      'These achieved rates are empirical VAL rates, not population guarantees or held-out TEST performance. VAL was already used for model selection, and alternate branches share background across only three temporal blocks per split. Clean-negative candidates do not certify benignness. No IID confidence intervals are claimed. Ties and integer budgets can yield an FPR below 1%; no tie splitting or post-hoc model reselection is permitted. The frozen grid excludes the exclusive hour end, so the final ten minutes have no endpoint primary score. Continuous event-driven FPR is outside this subphase.','',
      'The threshold domain is logit, not rounded probability. Future consumers must use the provided binary64 comparison helper and verify model/configuration/protocol identity when loading. Threshold files and their manifests are integrity records, not external signatures. Fixed thresholds do not imply continuous inference has been implemented.','',
      f"Frozen protocol SHA256: `{config['protocol_sha256']}`. Its version-control gate remains required before any later authorized final TEST evaluation; this subphase does not certify a commit.",'',
      'No TEST branch outcomes were accessed, no continuous inference, indicator sharing, federation, DP or blockchain component was implemented. Next action: explicit user acceptance of Subphase 5. Subphase 6 remains NOT_STARTED.']
    (output/'ACCEPTANCE_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    dump_json(output/'artifact_sha256.json',{p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()})
    progress=load(ROOT/'reports/phase6/progress_v5.json');progress['version']='phase6-progress-v6'
    progress['subphases']['4']={'status':'USER_ACCEPTED','evidence':'reports/phase6/comparator/acceptance_v1.json'}
    progress['subphases']['5']={'status':'TECHNICAL_GATE_PASS_AWAITING_USER_ACCEPTANCE','evidence':str((output/'ACCEPTANCE_REPORT.md').relative_to(ROOT)),'thresholds':10}
    progress['next_exact_action']=summary['next_action'];dump_json(ROOT/'reports/phase6/progress_v6.json',progress)
    print(json.dumps(dict(status=summary['status'],thresholds=10,preserved=len(preserved))),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=BASE/'v1');args=parser.parse_args();run(args.output.resolve())
