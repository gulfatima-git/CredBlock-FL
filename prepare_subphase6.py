from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parent
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,o):
 with p.open('x',encoding='utf-8') as f:json.dump(o,f,indent=2)
out=root/'reports/phase6/inference';assert not out.exists(),'Append-only preparation'
previous=read(root/'reports/phase6/calibration/accepted_inputs_before_subphase5_v1.json')
assert all(sha(root/p)==h for p,h in previous.items())
for folder in ['reports/phase6/training/final_v1','reports/phase6/comparator/final_v1','reports/phase6/calibration/v1']:
 base=root/folder
 for p,h in read(base/'artifact_sha256.json').items():assert sha(base/p)==h
baseline=dict(previous)
for directory in ['reports/phase6','configs/phase6','src/phase6','tests/phase6','outputs']:
 for p in (root/directory).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts:baseline[p.relative_to(root).as_posix()]=sha(p)
out.mkdir();write(out/'accepted_inputs_before_subphase6_v1.json',baseline)
write(root/'reports/phase6/calibration/acceptance_v1.json',dict(version='phase6-subphase5-user-acceptance-v1',status='USER_ACCEPTED',accepted_on_local_date='2026-11-14',timezone='Asia/Karachi',
 user_statement='I accept Phase 6 Subphase 5 (6.3): Fixed-FPR Threshold Calibration, based on the reported technical validation results.',
 evidence='reports/phase6/calibration/v1/ACCEPTANCE_REPORT.md',summary_sha256=sha(root/'reports/phase6/calibration/v1/summary.json'),
 preservation_manifest='reports/phase6/inference/accepted_inputs_before_subphase6_v1.json',authorized_next='Subphase 6 (6.4) only',threshold_artifacts_preserved=10,
 protocol_sha256=read(root/'configs/phase6/continuous_inference_v1.json')['protocol_sha256']))
shared=['configs/phase6/split_protocol_v1.json','configs/phase6/feature_allowlist_v1.json','configs/phase6/neighbor_sampling_v1.json','configs/phase6/local_training_v1.json','configs/phase6/fpr_calibration_v1.json',
 'src/organization/rolling_graph_v1.py','src/phase6/local_graphsage.py','src/phase6/input_pipeline.py','src/phase6/fpr_calibration.py']
models={}
for r in read(root/'reports/phase6/calibration/v1/summary.json')['thresholds']:
 if r['detector']!='graphsage':continue
 org=r['organization'];p=f'reports/phase6/calibration/v1/thresholds/{org}_graphsage.json'
 models[org]=dict(model_path=str(Path(r['model_path']).relative_to(root)),model_sha256=r['model_sha256'],threshold_path=p,threshold_sha256=sha(root/p))
config=root/'configs/phase6/continuous_inference_v1.json'
sources=['src/phase6/inference_registry.py','src/phase6/local_inference.py','src/phase6/inference_replay.py','src/phase6/run_continuous_inference.py']
documents=read(root/'reports/phase6/comparator/preregistration_v1.json')['design_document_sha256']
assert all(sha(Path(p))==h for p,h in documents.items())
write(out/'preregistration_v1.json',dict(status='FROZEN_BEFORE_OPERATIONAL_REPLAY',recorded_on_local_date='2026-11-14',configuration_sha256=sha(config),source_sha256={p:sha(root/p) for p in sources},
 design_document_sha256=documents,registry=dict(protocol_sha256=read(config)['protocol_sha256'],shared_sha256={p:sha(root/p) for p in shared},models=models),
 operating_policy=read(config),research_boundary='No TEST, labels, threshold/model selection or event-driven FPR claim; one representative full VAL hour per org plus exact restart repeat'))
print(json.dumps(dict(status='PREPARED',preserved_files=len(baseline),configuration_sha256=sha(config))))
