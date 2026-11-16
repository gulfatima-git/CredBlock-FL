from pathlib import Path
import json,hashlib
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');OUT=ROOT/'reports/phase6/final/v1'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):
 with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(v,f,indent=2);f.write('\n')
assert load(ROOT/'reports/phase6/detectability/acceptance_v1.json')['status']=='USER_ACCEPTED'
baseline=load(ROOT/'reports/phase6/detectability/accepted_inputs_before_subphase8_v1.json')
paths=set(baseline)
for mf in ['reports/phase6/detectability/technical_review_v2/delivery_manifest_v1.json','reports/phase6/subphase9_plan_v1/documentation_manifest_v1.json']:
 m=load(ROOT/mf);paths.update(m['artifact_sha256']);paths.add(mf)
paths.update(['reports/phase6/detectability/acceptance_v1.json','reports/phase6/progress_v16.json'])
paths.update(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'src').rglob('*.py'))
paths.update(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'configs').rglob('*') if p.is_file())
paths.update(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'outputs').rglob('*.xlsx'))
snapshot={p:dict(size=(ROOT/p).stat().st_size,mtime_ns=(ROOT/p).stat().st_mtime_ns) for p in sorted(paths)}
if not (OUT/'preservation_metadata_before.json').exists():write(OUT/'preservation_metadata_before.json',snapshot)
else:assert load(OUT/'preservation_metadata_before.json')==snapshot,'Original preservation snapshot changed'
thresholds=load(ROOT/'reports/phase6/calibration/v1/summary.json')['thresholds'];predictions=[]
for r in thresholds:
 org,det=r['organization'],r['detector'];train=(Path(r['prediction_source']).parent.parent/'selected_train_predictions.csv') if det=='graphsage' else (ROOT/'reports/phase6/comparator/full_v1'/org/'models/selected_train_predictions.csv')
 for split,path in [('TRAIN',train),('VAL',Path(r['prediction_source']))]:
  assert '_TEST' not in str(path);h=sha(path)
  if split=='VAL':assert h==r['prediction_source_sha256']
  predictions.append(dict(organization=org,detector=det,split=split,path=str(path),sha256=h,threshold_path=str(ROOT/'reports/phase6/calibration/v1/thresholds'/f'{org}_{det}.json')))
inputs=['reports/phase6/training/final_v1/summary.json','reports/phase6/comparator/final_v1/summary.json','reports/phase6/calibration/v1/summary.json','reports/phase6/detectability/technical_review_v2/final_v1/summary.json','reports/phase6/detectability/technical_review_v2/final_v1/per_organization_results.csv','reports/phase6/detectability/technical_review_v2/final_v1/factor_results.csv','reports/phase6/detectability/technical_review_v2/final_v1/paired_campaign_changes.csv','reports/phase6/detectability/technical_review_v2/final_v1/resource_summary.csv','reports/phase6/detectability/technical_review_v2/final_v1/undetected_organization_trials.csv','reports/phase6/detectability/technical_review_v2/continuation_00004/campaign_results.csv','reports/phase6/detectability/technical_review_v2/continuation_00004/organization_results.csv','reports/phase6/detectability/technical_review_v2/continuation_00004/factor_seed_results.csv','reports/phase6/detectability/technical_review_v2/continuation_00004/resource_measurements.json','reports/phase6/detectability/technical_review_v2/continuation_00004/user_occurrence_statistics_no_ids.json','reports/phase6/subphase9_plan_v1/SCIENTIFIC_CARRY_FORWARD.json','configs/phase6/split_protocol_v1.json']
config=dict(version='phase6-final-reporting-v1',approval='OPTION_A_TRAIN_VAL_ONLY',approved_on_local_date='2026-11-17',allowed_splits=['TRAIN','VAL'],test_access=False,stage_c_implemented=False,phase6_complete=False,phase7_started=False,primary_protocol_sha256=sha(ROOT/'configs/phase6/split_protocol_v1.json'),predictions=predictions,saved_inputs={p:sha(ROOT/p) for p in inputs},metric_contract=dict(primary_unit='eligible fixed-grid organization/variant/User/time',mask='eligible_mask must exactly equal node_label != -1',threshold='original binary64 logits >= original binary64 hex threshold',average_precision='Tied-score grouped noninterpolated AP; not trapezoidal PR-AUC',roc_auc='Tied-score trapezoidal ROC, descriptive reporting only',aggregation='Equal-weight per-organization macro primary; pooled confusion counts secondary',undefined='null, never zero-fill; list undefined organizations',training='Restored selected model in-sample diagnostic, thresholds selected on later VAL',seed='Campaign seed extracted from frozen variant identity, distinct from initialization seed',inductive='Use accepted TRAIN-unseen flags; do not refit or redefine',uncertainty='Descriptive seed/block variability only; no new IID CI or significance claim'),additional_descriptive_analysis='PR/ROC curves, subgroup and factor summaries from saved predictions; no new operating points or selection; figures display existing frozen thresholds only',prohibited_calls=['training','calibration','GNN forward inference','campaign evaluation runner','TEST adapter'],output='reports/phase6/final/v1',warnings_expected=['TRAIN threshold diagnostics use thresholds calibrated on later VAL and are not deployment estimates','Subgroup-mask totals in prior calibration summaries may include out-of-subgroup rows; report subgroup exclusion and original masks separately'])
write(ROOT/'configs/phase6/final_reporting_v1.json',config)
write(OUT/'authorization_v1.json',dict(status='AUTHORIZED_OPTION_A',stages=['A','B'],stage_c=False,test=False,models_retrained=False,thresholds_recalibrated=False,repeat_completed_evaluations=False,phase7=False,user_acceptance=False))
p=load(ROOT/'reports/phase6/progress_v16.json');p['version']='phase6-progress-v17';p['recorded_on_local_date']='2026-11-17';p['subphases']['9'].update(status='IN_PROGRESS',implementation_authorized=True,execution_scope='OPTION_A_TRAIN_VAL_REPORTING_ONLY',stage_c='DEFERRED_UNAUTHORIZED',test_outcome_access_authorized=False);p['next_exact_action']='Implement and validate saved TRAIN/VAL reporting; TEST and full Phase 6 completion remain pending.';write(ROOT/'reports/phase6/progress_v17.json',p)
print(json.dumps(dict(status='STAGE_A_CONTRACT_FROZEN',prediction_files=len(predictions),prior_paths_metadata_snapshotted=len(snapshot),test_payloads_opened=0)))
