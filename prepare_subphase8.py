"""Preserve accepted work; start methodology/pilot only, never the full sweep."""
from pathlib import Path
import json,hashlib,subprocess
ROOT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def write(p,v):
 with p.open('x',encoding='utf-8') as f:json.dump(v,f,indent=2)
base=ROOT/'reports/phase6/detectability';assert not base.exists()
accepted=ROOT/'reports/phase6/indicator_baseline/acceptance_v1.json';assert read(accepted)['status']=='USER_ACCEPTED'
previous=read(ROOT/'reports/phase6/indicator_baseline/accepted_inputs_before_subphase7_v1.json')
for p,h in previous.items():assert sha(ROOT/p)==h,p
sealed=read(ROOT/'reports/phase6/indicator_baseline/delivery_manifest_v1.json')
for p,h in sealed['artifact_sha256'].items():assert sha(ROOT/p)==h,p
baseline=dict(previous)
for folder in ['reports/phase6','configs/phase6','src/phase6','tests/phase6','outputs']:
 for p in (ROOT/folder).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts:baseline[p.relative_to(ROOT).as_posix()]=sha(p)
base.mkdir();write(base/'accepted_inputs_before_subphase8_v1.json',baseline)
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
blob=subprocess.check_output(['git','show','HEAD:configs/phase6/split_protocol_v1.json'],cwd=ROOT)
protocol=read(ROOT/'configs/phase6/split_protocol_v1.json');digest=hashlib.sha256(blob).hexdigest();assert digest==sha(ROOT/'configs/phase6/split_protocol_v1.json')
progress=read(ROOT/'reports/phase6/progress_v10.json');progress['version']='phase6-progress-v11'
progress['subphases']['8']={'status':'IN_PROGRESS','scope':'Freeze evaluator and verify predetermined representative; full 171-instance run requires later review','evidence':'reports/phase6/detectability'}
progress['subphase8_start_gate']={'status':'USER_DONE_RECEIVED','verified_commit':commit}
progress['version_control_before_final_test']={'status':'FROZEN_PROTOCOL_VERIFIED_IN_COMMIT','commit':commit,'protocol_sha256':digest,'final_test_evaluation_authorized':False}
progress['next_exact_action']='Freeze/test offline evaluator; verify predetermined VAL instance and prepare resumable 171-instance execution plan. Do not launch full run before review.'
write(ROOT/'reports/phase6/progress_v11.json',progress)
write(base/'execution_scope_v1.json',dict(status='PILOT_ONLY_AUTHORIZED_FULL_SCOPE_UNCHANGED',full_required_val_instances=171,predetermined_representative='CFV1_SO_CS_027_SEED1001_VAL',full_sweep_launch_authorized=False,user_direction='Option 2: freeze evaluator, verify representative, examine exact-equivalent reuse/optimization and prepare append-only resumable full-run plan before review',accepted_commit=commit,protocol_sha256=digest,prior_files_preserved=len(baseline)))
print(json.dumps(dict(status='SUBPHASE8_METHOD_AND_PILOT_PREPARED',prior_files=len(baseline),full_run_authorized=False,commit=commit)))
