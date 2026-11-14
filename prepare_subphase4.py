from pathlib import Path
import json,hashlib,shutil
root=Path(__file__).resolve().parent
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,o):
 with p.open('x',encoding='utf-8') as f:json.dump(o,f,indent=2)
out=root/'reports/phase6/comparator'
assert not out.exists(),'Preparation is append-only'
old=read(root/'reports/phase6/training/accepted_inputs_before_subphase3_v1.json')
assert all(sha(root/p)==h for p,h in old.items())
baseline=dict(old)
for directory in ['reports/phase6','configs/phase6','src/phase6','tests/phase6','outputs']:
 for p in (root/directory).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts:
   baseline[p.relative_to(root).as_posix()]=sha(p)
out.mkdir()
write(out/'accepted_inputs_before_subphase4_v1.json',baseline)
final=root/'reports/phase6/training/final_v1'
for p,h in read(final/'artifact_sha256.json').items():assert sha(final/p)==h
write(root/'reports/phase6/training/acceptance_v1.json',dict(
 version='phase6-subphase3-user-acceptance-v1',status='USER_ACCEPTED',accepted_on_local_date='2026-11-14',timezone='Asia/Karachi',
 user_statement='I accept Phase 6 Subphase 3 (6.2B): Five Independent Local GraphSAGE Models, based on the reported full TRAIN/VAL training and validation evidence.',
 evidence='reports/phase6/training/final_v1/ACCEPTANCE_REPORT.md',summary_sha256=sha(final/'summary.json'),
 selected_checkpoints={p.name:sha(p) for p in (final/'models').glob('*.pt')},
 preservation_manifest='reports/phase6/comparator/accepted_inputs_before_subphase4_v1.json',
 authorized_next='Subphase 4 (6.2C) only',protocol_sha256=old['configs/phase6/split_protocol_v1.json']))
config=root/'configs/phase6/non_graph_comparator_v1.json'
sources=['src/phase6/non_graph_comparator.py','src/phase6/comparator_data.py','src/phase6/run_local_comparator.py']
source_hashes={p:sha(root/p) for p in sources}
documents={}
for name in ['CredBlock_FL_Phase6_Implementation_Roadmap.md','CredBlock_Implementation_Plan.pdf','CredBlock-FL_Final_Framework_Explained.pdf','CredBlock-FL-detection-mechanism (2).png','CredBlock-FL-workflow (1).png']:
 p=Path('C:/Users/Gulso/Downloads')/name;documents[str(p)]=sha(p)
write(out/'preregistration_v1.json',dict(status='FROZEN_BEFORE_COMPARATOR_TRAINING_OR_COMPARISON',recorded_on_local_date='2026-11-14',
 config=str(config.relative_to(root)),config_sha256=sha(config),source_sha256=source_hashes,design_document_sha256=documents,
 selection=read(config)['selection'],no_comparison_outcomes_examined=True,
 primary_evaluation_unit='eligible organization-local User-time/window on unchanged exact grid',primary_fpr_target=0.01,
 test_access=False,final_threshold_calibration=False,prior_graphsage_validation_already_accepted=True,
 interpretation='This preregisters a new comparator against already accepted GraphSAGE results, not a blind re-analysis of GraphSAGE. No post-outcome search or feature changes permitted without new version.'))
print(json.dumps(dict(status='PREPARED',preserved_files=len(baseline),config_sha256=sha(config))))
