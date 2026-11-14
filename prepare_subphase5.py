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
 with p.open('x',encoding='utf-8') as f:json.dump(o,f,indent=2,allow_nan=False)
out=root/'reports/phase6/calibration';assert not out.exists(),'Append-only preparation'
previous=read(root/'reports/phase6/comparator/accepted_inputs_before_subphase4_v1.json')
assert all(sha(root/p)==h for p,h in previous.items())
for folder in ['reports/phase6/training/final_v1','reports/phase6/comparator/final_v1']:
 base=root/folder
 for p,h in read(base/'artifact_sha256.json').items():assert sha(base/p)==h
baseline=dict(previous)
for directory in ['reports/phase6','configs/phase6','src/phase6','tests/phase6','outputs']:
 for p in (root/directory).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts:baseline[p.relative_to(root).as_posix()]=sha(p)
out.mkdir()
write(out/'accepted_inputs_before_subphase5_v1.json',baseline)
accepted=root/'reports/phase6/comparator/final_v1'
write(root/'reports/phase6/comparator/acceptance_v1.json',dict(version='phase6-subphase4-user-acceptance-v1',status='USER_ACCEPTED',accepted_on_local_date='2026-11-14',timezone='Asia/Karachi',
 user_statement='I accept Phase 6 Subphase 4 (6.2C): Non-Graph Local Comparator and Best-Local Selection, based on the reported complete TRAIN/VAL comparison and validation evidence.',
 evidence='reports/phase6/comparator/final_v1/ACCEPTANCE_REPORT.md',summary_sha256=sha(accepted/'summary.json'),
 best_local='GraphSAGE for Org1-Org5; locked before fixed-FPR calibration',preservation_manifest='reports/phase6/calibration/accepted_inputs_before_subphase5_v1.json',authorized_next='Subphase 5 (6.3) only'))
config=root/'configs/phase6/fpr_calibration_v1.json'
write(out/'preregistration_v1.json',dict(status='FROZEN_BEFORE_THRESHOLD_CALCULATION',recorded_on_local_date='2026-11-14',configuration_sha256=sha(config),
 source_sha256={p:sha(root/p) for p in ['src/phase6/fpr_calibration.py','src/phase6/run_fpr_calibration.py']},
 protocol_sha256=read(config)['protocol_sha256'],design_document_sha256=read(root/'reports/phase6/comparator/preregistration_v1.json')['design_document_sha256'],
 target=dict(numerator=1,denominator=100),negative_only=True,score_domain='binary64 logit',threshold_rule=read(config)['threshold_rule'],
 changes_to_accepted_protocol=False,best_local_locked='GraphSAGE Org1-Org5',test_access=False))
print(json.dumps(dict(status='PREPARED',preserved_files=len(baseline),configuration_sha256=sha(config))))
