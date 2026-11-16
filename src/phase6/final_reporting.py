"""Additive saved-evidence reporting. No models, training or campaign execution."""
import csv,hashlib,json,math
from collections import defaultdict
from pathlib import Path
import numpy as np
from src.phase6.fpr_calibration import decisions

ALLOWED_SPLITS={'TRAIN','VAL'}
def require(value,message):
    if not value:raise ValueError(message)
def guard_split(split):require(split in ALLOWED_SPLITS,'Reporting authorizes TRAIN/VAL only; TEST is forbidden before I/O')
def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')
def csv_save(path,rows):
    require(bool(rows),'Cannot silently emit empty table')
    with Path(path).open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def read_csv(path):
    with Path(path).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def read_predictions(path,split,organization,expected_sha=None):
    guard_split(split)
    require('_TEST' not in str(path).upper(),'Forbidden prediction path')
    if expected_sha:require(digest(path)==expected_sha,'Prediction input hash changed')
    rows=read_csv(path);keys=[];y=[];z=[];mask=[];unseen=[];ip=[];seeds=[];variants=set();grids=set()
    for r in rows:
        require(r['split']==split and r['organization']==organization,'Prediction split/organization mismatch')
        require(r['variant_id'].endswith('_'+split),'Prediction branch split mismatch')
        key=(r['variant_id'],r['asof'],r['local_user_id']);keys.append(key);variants.add(r['variant_id']);grids.add(key[:2])
        label=int(r['node_label']);m=r['eligible_mask']=='True';require(r['eligible_mask'] in ['True','False'] and label in [-1,0,1] and m==(label!=-1),'Label/mask inconsistency')
        y.append(label);mask.append(m);score=float(r['logit']);require(math.isfinite(score),'Nonfinite saved logit');z.append(score)
        require(r['unseen_user'] in ['True','False'] and r['has_unseen_ip'] in ['True','False'],'Inductive flag mismatch')
        unseen.append(r['unseen_user']=='True');ip.append(r['has_unseen_ip']=='True')
        seeds.append(int(r['variant_id'].rsplit('_SEED',1)[1].split('_')[0]))
    require(len(keys)==len(set(keys)),'Duplicate private prediction key')
    return dict(keys=keys,y=np.array(y,dtype=np.int8),z=np.array(z,dtype=np.float64),mask=np.array(mask,dtype=bool),unseen=np.array(unseen,dtype=bool),ip=np.array(ip,dtype=bool),seed=np.array(seeds),variants=len(variants),grids=len(grids))
def ranking(y,z):
    y=np.asarray(y);z=np.asarray(z,dtype=np.float64);require(y.shape==z.shape and np.isfinite(z).all(),'Ranking input mismatch')
    require(np.isin(y,[0,1]).all(),'Ranking requires eligible binary targets')
    n=len(y);p=int(y.sum());neg=n-p
    if not n:return dict(average_precision=None,roc_auc=None,bce=None,curve=[])
    order=np.argsort(-z,kind='stable');yy=y[order];zz=z[order];ends=np.r_[np.flatnonzero(zz[:-1]!=zz[1:]),n-1];tp=np.cumsum(yy)[ends];fp=ends+1-tp
    precision=tp/(ends+1);recall=tp/p if p else np.full(len(tp),np.nan);fpr=fp/neg if neg else np.full(len(fp),np.nan)
    ap=float(np.sum(np.diff(np.r_[0,tp])*precision)/p) if p else None
    auc=float(np.trapezoid(np.r_[0,recall],np.r_[0,fpr])) if p and neg else None
    loss=np.maximum(z,0)-z*y+np.log1p(np.exp(-np.abs(z)))
    curve=[dict(logit_threshold=float(zz[e]),precision=float(pr),recall=float(re) if p else None,fpr=float(fr) if neg else None) for e,pr,re,fr in zip(ends,precision,recall,fpr)]
    return dict(average_precision=ap,roc_auc=auc,bce=float(loss.mean()),curve=curve)
def confusion(y,z,eligible,threshold,population=None):
    y=np.asarray(y);eligible=np.asarray(eligible,dtype=bool);population=np.ones(len(y),dtype=bool) if population is None else np.asarray(population,dtype=bool)
    require(y.shape==eligible.shape==population.shape and np.isin(y,[-1,0,1]).all() and np.array_equal(eligible,y!=-1),'Invalid reporting supervision')
    m=eligible&population;pred=decisions(z,threshold)[m];target=y[m];tp=int(np.sum(pred&(target==1)));fp=int(np.sum(pred&(target==0)));tn=int(np.sum(~pred&(target==0)));fn=int(np.sum(~pred&(target==1)))
    return dict(eligible=int(m.sum()),positive=tp+fn,negative=fp+tn,original_masked_inside_population=int(np.sum(~eligible&population)),outside_population=int(np.sum(~population)),tp=tp,fp=fp,tn=tn,fn=fn,precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,fpr=fp/(fp+tn) if fp+tn else None,specificity=tn/(tn+fp) if tn+fp else None,accuracy=(tp+tn)/len(target) if len(target) else None)
def aggregate_metrics(rows):
    output=[]
    for split in ['TRAIN','VAL']:
        for detector in ['graphsage','tabular_mlp']:
            rs=[r for r in rows if r['split']==split and r['detector']==detector];require(len(rs)==5 and {r['organization'] for r in rs}=={'Org1','Org2','Org3','Org4','Org5'},'Aggregation must retain all five organizations')
            metrics=['precision','recall','f1','fpr','specificity','accuracy','average_precision','roc_auc','bce'];macro={k:float(np.mean([r[k] for r in rs])) if all(r[k] is not None for r in rs) else None for k in metrics}
            output.append(dict(split=split,detector=detector,aggregation='equal_weight_macro',organizations=5,**macro,undefined_organizations={k:[r['organization'] for r in rs if r[k] is None] for k in metrics}))
            c={k:sum(r[k] for r in rs) for k in ['tp','fp','tn','fn','eligible','positive','negative']};tp,fp,tn,fn=(c[k] for k in ['tp','fp','tn','fn'])
            output.append(dict(split=split,detector=detector,aggregation='pooled_confusion_counts',organizations=5,**c,precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,fpr=fp/(fp+tn) if fp+tn else None,average_precision=None,roc_auc=None,bce=None))
    return output

def run(root,output,config_path,splits=('TRAIN','VAL')):
    for split in splits:guard_split(split)
    require(set(splits)==ALLOWED_SPLITS,'Full Option A report requires TRAIN and VAL')
    root=Path(root);out=Path(output);require(not (out/'summary.json').exists(),'Existing report output cannot be overwritten');out.mkdir(parents=True,exist_ok=True)
    cfg=load(config_path);require(cfg['allowed_splits']==['TRAIN','VAL'] and not cfg['test_access'] and not cfg['stage_c_implemented'],'Unauthorized reporting configuration')
    hashes={};checks=[];warnings=[]
    def pinned(p,h=None):
        path=Path(p) if Path(p).is_absolute() else root/p
        require('_TEST' not in str(path).upper(),'TEST payload path rejected')
        got=digest(path)
        if h:require(got==h,'Saved input hash mismatch: '+str(path))
        hashes[str(path)]=got;return path
    for p,h in cfg['saved_inputs'].items():pinned(p,h)
    primary=load(root/'configs/phase6/split_protocol_v1.json');require(digest(root/'configs/phase6/split_protocol_v1.json')==cfg['primary_protocol_sha256'],'Primary protocol changed')
    train=load(root/'reports/phase6/training/final_v1/summary.json');comp=load(root/'reports/phase6/comparator/final_v1/summary.json');cal=load(root/'reports/phase6/calibration/v1/summary.json')
    ts={r['organization']:r for r in train['models']};cs={r['organization']:r for r in comp['models']}
    metrics=[];prevalence=[];subgroups=[];curves=[];cohorts={};histories=[];resources=[];calibration=[];seeds=[];factor_metrics=[]
    frozen_inventory=load(pinned('reports/phase6/detectability/required_val_inventory_v1.json'));factor_by_id={r['variant_id']:r['factors'] for r in frozen_inventory}
    for item in cfg['predictions']:
        split,org,det=(item[k] for k in ['split','organization','detector']);guard_split(split);p=pinned(item['path'],item['sha256']);data=read_predictions(p,split,org);threshold_artifact=load(pinned(item['threshold_path']));require(threshold_artifact['organization']==org and threshold_artifact['detector']==det,'Threshold identity')
        pinned(threshold_artifact['model_path'],threshold_artifact['model_sha256']);threshold=threshold_artifact['calibration']['threshold'];m=data['mask']
        require(data['variants']==171 and data['grids']==1026,'Full frozen branch/grid coverage missing')
        identity=(org,split);identity_value=(data['keys'],data['y'].tolist(),m.tolist(),data['unseen'].tolist(),data['ip'].tolist())
        if identity in cohorts:require(identity_value==cohorts.pop(identity),'Paired detector cohorts differ')
        else:cohorts[identity]=identity_value
        rank=ranking(data['y'][m],data['z'][m]);row=dict(organization=org,split=split,detector=det,**confusion(data['y'],data['z'],m,threshold),average_precision=rank['average_precision'],roc_auc=rank['roc_auc'],bce=rank['bce']);metrics.append(row)
        ref=(ts[org]['validation' if split=='VAL' else 'selected_model_train_metrics'] if det=='graphsage' else cs[org]['comparator']['selected']['validation'] if split=='VAL' else cs[org]['comparator']['train_metrics'])
        for k in ['eligible','positive','negative']:require(row[k]==ref[k],'Accepted metric count mismatch '+org+split+det+k)
        for k in ['bce','average_precision']:require(abs(row[k]-ref[k])<1e-12,'Accepted ranking metric mismatch '+org+split+det+k)
        if split=='VAL':
            accepted=threshold_artifact['operating_metrics']
            for k in ['tp','fp','tn','fn','fpr','precision','recall','f1']:require(row[k]==accepted[k],'Accepted calibration metric mismatch '+org+det+k)
            require(row['fp']<=threshold_artifact['calibration']['fp_budget'],'Frozen VAL FP budget exceeded')
            calibration.append(dict(organization=org,detector=det,threshold_decimal_text='binary64: '+repr(threshold['value']),threshold_hex=threshold['hex'],negative_count=row['negative'],fp_budget=threshold_artifact['calibration']['fp_budget'],achieved_fp=row['fp'],achieved_fpr=row['fpr'],recall=row['recall'],precision=row['precision'],f1=row['f1'],boundary_tie_count=threshold_artifact['calibration']['boundary_tie_count']))
            for c in rank['curve']:curves.append(dict(organization=org,detector=det,split=split,**c))
            for name,pop in [('unseen_user',data['unseen']),('unseen_ip_context',data['ip']),('unseen_user_and_ip',data['unseen']&data['ip'])]:
                sm=confusion(data['y'],data['z'],m,threshold,pop);rr=ranking(data['y'][m&pop],data['z'][m&pop]);subgroups.append(dict(organization=org,detector=det,subgroup=name,**sm,average_precision=rr['average_precision'],bce=rr['bce']))
            for seed in [1001,1002,1003]:seeds.append(dict(organization=org,detector=det,seed=seed,**confusion(data['y'],data['z'],m,threshold,data['seed']==seed)))
            # Descriptive family/factor strata; never change models or thresholds.
            for field in ['RIP_target','Raccount_target','Sorg_target']:
                groups=defaultdict(list)
                for i,key in enumerate(data['keys']):
                    factors=factor_by_id[key[0]];groups[(factors['family'],factors[field])].append(i)
                for (family,level),indices in groups.items():
                    pop=np.zeros(len(m),dtype=bool);pop[indices]=True;factor_metrics.append(dict(organization=org,detector=det,design_family=family,factor=field,level=level,**confusion(data['y'],data['z'],m,threshold,pop)))
        if det=='graphsage':prevalence.append(dict(organization=org,split=split,eligible=row['eligible'],positive=row['positive'],negative=row['negative'],masked_recent_roots=row['original_masked_inside_population'],prediction_rows=len(m),positive_fraction=row['positive']/row['eligible'],variants=data['variants'],grids=data['grids'],context_only='Older graph context omitted from saved supervised roots; not counted as eligible negatives'))
        checks.append(dict(organization=org,split=split,detector=det,status='PASS_EXACT_ACCEPTED_METRIC_RECONCILIATION',prediction_sha256=hashes[str(p)]))
    require(not cohorts,'Unpaired detector cohort')
    for org in sorted(ts):
        t=ts[org];c=cs[org]['comparator'];require(cs[org]['best_local']=='graphsage','Frozen best-local selection changed')
        for det,candidates in [('graphsage',t['trial_summaries']),('tabular_mlp',c['trials'])]:
            for trial in candidates:
                ep=Path(trial['checkpoint']).parent/'epochs.jsonl';pinned(ep)
                for line in ep.read_text().splitlines():
                    e=json.loads(line);histories.append(dict(organization=org,detector=det,candidate=trial['candidate']['id'],epoch=e['epoch'],train_weighted_bce=e['train_weighted_bce'],validation_bce=e['validation']['bce'],validation_ap=e['validation']['average_precision'],selected_candidate=(trial['candidate']['id']==(t['selected_candidate']['id'] if det=='graphsage' else c['selected']['candidate']['id'])),selected_epoch=(t['selected_epoch'] if det=='graphsage' else c['selected']['selected_epoch'])))
        resources.extend([dict(organization=org,detector='graphsage',selected_trial_seconds=t['selected_run_seconds'],all_trials_and_repeat_seconds=t['all_trials_seconds'],observed_training_rss_mib=t['observed_training_rss_peak_bytes']/1048576,preparation_seconds=t['cache_build_seconds'],scope='Original concurrent CPU run; preparation separate'),dict(organization=org,detector='tabular_mlp',selected_trial_seconds=c['selected']['training_seconds'],all_trials_and_repeat_seconds=c['total_trials_seconds'],observed_training_rss_mib=cs[org]['resources']['training_peak_rss_bytes']/1048576,preparation_seconds=cs[org]['resources']['preparation_and_graph_verification_seconds'],scope='Original CPU run; input-array overhead included')])
    tables=dict(fixed_grid_metrics=metrics,prevalence_and_masks=prevalence,inductive_subgroups=subgroups,calibration=calibration,seed_metrics=seeds,fixed_grid_factor_metrics=factor_metrics,training_histories=histories,training_resources=resources)
    for name,rs in tables.items():csv_save(out/(name+'.csv'),rs)
    save(out/'aggregation.json',aggregate_metrics(metrics));save(out/'validation_curves.json',curves);save(out/'reconciliation.json',dict(status='PASS',components=checks,paired_organization_splits=10,fp_budgets_verified=10))
    for p,h in hashes.items():require(digest(p)==h,'Reporting input changed during execution')
    warnings.extend(['TRAIN metrics are in-sample; applying a later VAL threshold is retrospective diagnostic only.','Subgroup excluded rows are split into original masked-inside-population and outside-population; prior calibration subgroup masked counts conflate those categories.','AP is tied-score grouped; ROC-AUC is descriptive and not the primary operating metric.','Confidence intervals omitted because alternate branches share background and only three temporal blocks exist.'])
    save(out/'input_sha256.json',hashes);save(out/'summary.json',dict(status='PASS_TRAIN_VAL_REPORTING_RECONCILIATION',reporting_scope='OPTION_A',fixed_grid_rows=len(metrics),thresholds_unchanged=True,paired_eligible_train=sum(r['eligible'] for r in metrics if r['split']=='TRAIN' and r['detector']=='graphsage'),paired_eligible_val=sum(r['eligible'] for r in metrics if r['split']=='VAL' and r['detector']=='graphsage'),warnings=warnings,test_outcomes_accessed=False,stage_c_implemented=False,phase6_complete=False,user_accepted=False,phase7_started=False))
    return tables
