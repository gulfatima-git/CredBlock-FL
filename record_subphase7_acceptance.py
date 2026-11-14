"""Record acceptance only. Do not begin Subphase 8 until the user's 'done'."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parent
BASE=ROOT/'reports/phase6/indicator_baseline'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def append(p,value):
 with p.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
acceptance=BASE/'acceptance_v1.json';progress_path=ROOT/'reports/phase6/progress_v10.json'
assert not acceptance.exists() and not progress_path.exists(),'Acceptance/progress are append-only'
manifest_path=BASE/'delivery_manifest_v1.json';manifest=load(manifest_path)
assert manifest['status']=='PASS_SUBPHASE7_DELIVERY_SEALED_AWAITING_USER_ACCEPTANCE'
for p,h in manifest['artifact_sha256'].items():assert sha(ROOT/p)==h,p
prior=load(BASE/'accepted_inputs_before_subphase7_v1.json')
for p,h in prior.items():assert sha(ROOT/p)==h,p
append(acceptance,dict(version='phase6-subphase7-user-acceptance-v1',status='USER_ACCEPTED',accepted_on_local_date='2026-11-14',timezone='Asia/Karachi',
 user_statement='I accept Phase 6 Subphase 7 (6.5): Immediate Indicator-Sharing Baseline, based on the reported technical validation and independent delivery audit.',
 evidence='reports/phase6/indicator_baseline/TECHNICAL_ACCEPTANCE_REPORT_v1.md',evidence_sha256=sha(BASE/'TECHNICAL_ACCEPTANCE_REPORT_v1.md'),
 delivery_manifest='reports/phase6/indicator_baseline/delivery_manifest_v1.json',delivery_manifest_sha256=sha(manifest_path),
 independent_audit_sha256=sha(BASE/'delivery_audit_v1.json'),policy_sha256=manifest['policy_sha256'],protocol_sha256=manifest['protocol_sha256'],
 preservation_verification='PASS',prior_files_preserved=len(prior),delivery_artifacts_preserved=len(manifest['artifact_sha256']),
 authorized_next='Subphase 8 (6.6) only AFTER user says done following supplied git add/commit commands',subphase8_started=False))
progress=load(ROOT/'reports/phase6/progress_v9.json');progress['version']='phase6-progress-v10'
progress['subphases']['7']={'status':'USER_ACCEPTED','evidence':'reports/phase6/indicator_baseline/acceptance_v1.json'}
assert progress['subphases']['8']['status']=='NOT_STARTED' and progress['subphases']['9']['status']=='NOT_STARTED'
progress['next_exact_action']='User commits the accepted Subphase 7 files and says done; only then begin Subphase 8.'
progress['subphase8_start_gate']={'status':'WAITING_FOR_USER_DONE','implementation_started':False}
append(progress_path,progress)
print(json.dumps(dict(status='SUBPHASE7_USER_ACCEPTED',prior_files_preserved=len(prior),delivery_artifacts_preserved=len(manifest['artifact_sha256']),subphase8='NOT_STARTED_WAITING_FOR_USER_DONE')))
