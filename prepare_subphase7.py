"""Append-only Subphase 6 acceptance and preservation inventory before Subphase 7."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parent
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def write(p,value):
 with p.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
base=ROOT/'reports/phase6/indicator_baseline';assert not base.exists()
sealed=load(ROOT/'reports/phase6/inference/delivery_manifest_v1.json')
assert sealed['status']=='PASS_SUBPHASE6_DELIVERY_SEALED_AWAITING_USER_ACCEPTANCE'
for p,h in sealed['artifact_sha256'].items():assert sha(ROOT/p)==h,p
previous=load(ROOT/'reports/phase6/inference/accepted_inputs_before_subphase6_v1.json')
for p,h in previous.items():assert sha(ROOT/p)==h,p
baseline=dict(previous)
for directory in ['reports/phase6','configs/phase6','src/phase6','tests/phase6','outputs']:
 for p in (ROOT/directory).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts:baseline[p.relative_to(ROOT).as_posix()]=sha(p)
base.mkdir();write(base/'accepted_inputs_before_subphase7_v1.json',baseline)
write(ROOT/'reports/phase6/inference/acceptance_v1.json',dict(version='phase6-subphase6-user-acceptance-v1',status='USER_ACCEPTED',accepted_on_local_date='2026-11-14',timezone='Asia/Karachi',
 user_statement='I accept Phase 6 Subphase 6 (6.4): Continuous Local Inference, based on the reported technical validation results and independent-process startup supplement.',
 evidence='reports/phase6/inference/TECHNICAL_ACCEPTANCE_REPORT_v1.md',evidence_sha256=sha(ROOT/'reports/phase6/inference/TECHNICAL_ACCEPTANCE_REPORT_v1.md'),
 sealed_delivery_manifest_sha256=sha(ROOT/'reports/phase6/inference/delivery_manifest_v1.json'),
 preservation_manifest='reports/phase6/indicator_baseline/accepted_inputs_before_subphase7_v1.json',authorized_next='Subphase 7 (6.5) only',protocol_sha256=sealed['protocol_sha256']))
progress=load(ROOT/'reports/phase6/progress_v7.json');progress['version']='phase6-progress-v8'
progress['subphases']['6']={'status':'USER_ACCEPTED','evidence':'reports/phase6/inference/acceptance_v1.json'}
progress['subphases']['7']={'status':'IN_PROGRESS_POLICY_FREEZE_PENDING'};progress['next_exact_action']='Freeze and test Subphase 7 policy; no Subphase 8.'
write(ROOT/'reports/phase6/progress_v8.json',progress)
print(json.dumps(dict(status='SUBPHASE6_USER_ACCEPTED_SUBPHASE7_PREPARED',prior_files=len(baseline))))
