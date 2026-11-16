"""Documentation-only acceptance and curated Git instructions. No TEST payloads."""
from pathlib import Path
import json,hashlib,subprocess
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');FINAL=ROOT/'reports/phase6/final';REPORT=FINAL/'v1';OUT=ROOT/'outputs/phase6_final_v1'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,value):
 with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,indent=2);f.write('\n')
def text(p,value):
 with p.open('x',encoding='utf-8',newline='\n') as f:f.write(value)
accept=FINAL/'acceptance_v1.json';progress=ROOT/'reports/phase6/progress_v20.json';events=ROOT/'reports/phase6/progress_events';event=events/'subphase9_option_a_user_approval_v1.json'
assert not any(p.exists() for p in [accept,progress,event]),'Append-only destinations already exist'
events.mkdir(exist_ok=True);probe=events/'write_access_probe.tmp';probe.write_text('verified');assert probe.read_text()=='verified';probe.unlink()
delivery=load(REPORT/'delivery_manifest.json')
for p,h in delivery['artifact_sha256'].items():assert sha(ROOT/p)==h,'Sealed reporting artifact changed: '+p
input_hashes=load(REPORT/'tables/input_sha256.json');input_hashes.update(load(REPORT/'additional_source_sha256.json'))
for p,h in input_hashes.items():
 assert '_TEST' not in p.upper(),'Do not open TEST payload';assert sha(Path(p))==h,'Original numerical input changed: '+p
matrix=load(REPORT/'research_alignment.json');assert [r['id'] for r in matrix['rows']]==['RQ1','RQ2','RQ3','RQ4','C1','C2','C3','C4','C5','C6']
assert all(all(r[k] for k in ['designed','implemented','evidence','unsupported','subsequent_phases','paper_can_claim','paper_cannot_claim']) for r in matrix['rows'])
figures=load(REPORT/'figure_manifest_v2.json');assert len(figures['figures'])==11
for r in figures['figures']:
 assert r['caption'] and r['source']
 for field in ['png','pdf']:assert (OUT/r[field]).is_file() and (OUT/r[field]).stat().st_size>0
primary='configs/phase6/split_protocol_v1.json';expected='9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b';commit='5de030316176a27889054d0e782cb1ad92171cb5'
assert sha(ROOT/primary)==expected
assert hashlib.sha256(subprocess.check_output(['git','show',commit+':'+primary],cwd=ROOT)).hexdigest()==expected
previous=load(ROOT/'reports/phase6/progress_v19.json');summary=load(REPORT/'summary.json');assert summary['tests_passed']==57 and summary['independent_metric_components_verified']==20
assert summary['VAL_wholly_undetected_campaigns']==0 and summary['VAL_campaign_denominator']==171
approval=dict(version='phase6-progress-event-subphase9-option-a-user-approval-v1',event='EXPLICIT_USER_APPROVAL_RECORDED',recorded_on_local_date='2026-11-17',timezone='Asia/Karachi',subphase=9,scope='OPTION_A_STAGES_A_B_TRAIN_VAL_REPORTING',user_statement='I approve Subphase 9 Option A, subject to the following final documentation requirements.',approval_boundaries=dict(TEST_unauthorized=True,stage_c_deferred=True,phase6_scientific_completion_pending=True,phase7_not_authorized=True,federation_DP_robust_aggregation_blockchain_not_authorized=True,no_protocol_amendment=True,no_accepted_evidence_modification=True),requested_next_action='Provide Git add/commit commands. When user says done, stop and wait for further instructions.')
# Record explicit approval as an append-only progress event before marking accepted.
write(event,approval);assert load(event)['event']=='EXPLICIT_USER_APPROVAL_RECORDED'
record=dict(version='phase6-subphase9-option-a-user-acceptance-v1',status='USER_ACCEPTED',accepted_on_local_date='2026-11-17',timezone='Asia/Karachi',scope='OPTION_A_STAGES_A_B_TRAIN_VAL_REPORTING_ONLY',approval_progress_event=str(event.relative_to(ROOT)).replace('\\','/'),approval_progress_event_sha256=sha(event),technical_report='reports/phase6/final/v1/TECHNICAL_ACCEPTANCE_REPORT.md',technical_report_sha256=sha(REPORT/'TECHNICAL_ACCEPTANCE_REPORT.md'),technical_delivery_manifest_sha256=sha(REPORT/'delivery_manifest.json'),sealed_reporting_artifacts_verified=len(delivery['artifact_sha256']),saved_numerical_input_hashes_verified=len(input_hashes),alignment=dict(research_questions=4,contributions=6,design_implementation_supported_unsupported_separated=True),figures=dict(accepted_sets=11,publication_files=22,captions_and_sources_preserved=True,manifest_sha256=sha(REPORT/'figure_manifest_v2.json')),tests_passed=57,independent_prediction_components=20,frozen_primary_protocol_sha256=expected,verified_protocol_git_commit=commit,VAL_wholly_undetected_campaigns=0,VAL_campaign_denominator=171,no_federated_recovery_claim=True,stage_c='DEFERRED_UNAUTHORIZED',TEST_execution_authorized=False,TEST_payloads_accessed=False,phase6_status='PENDING_HELD_OUT_TEST_EVALUATION',phase6_complete=False,phase7_started=False,preservation='All accepted evidence remains immutable; this record supersedes historical pending-user-acceptance metadata without editing it.')
write(accept,record)
previous.update(version='phase6-progress-v20',recorded_on_local_date='2026-11-17',phase6_status='PENDING_HELD_OUT_TEST_EVALUATION',phase6_completion_status='PENDING_HELD_OUT_TEST_EVALUATION',phase6_complete=False)
previous['subphases']['9'].update(status='USER_ACCEPTED',acceptance_scope='OPTION_A_STAGES_A_B_ONLY',evidence='reports/phase6/final/acceptance_v1.json',approval_progress_event='reports/phase6/progress_events/subphase9_option_a_user_approval_v1.json',scope_completion='STAGES_A_B_COMPLETE',stage_c='DEFERRED_UNAUTHORIZED',test_outcome_access_authorized=False)
previous['next_exact_action']='User commits the curated accepted Subphase 8/9 documentation and reporting files. On done, stop and wait. No TEST or Phase 7 authorization.'
write(progress,previous)
acceptance_summary='''# Phase 6 Subphase 9 Option A — Final user acceptance

Recorded 17 November 2026, Asia/Karachi.

**USER_ACCEPTED: Stages A–B TRAIN/VAL reporting only. Phase 6 remains PENDING_HELD_OUT_TEST_EVALUATION. TEST is unauthorized; Stage C is deferred. Phase 7 has not started.**

The explicit user approval was first written to the append-only progress event `reports/phase6/progress_events/subphase9_option_a_user_approval_v1.json`, followed by `reports/phase6/final/acceptance_v1.json` and `reports/phase6/progress_v20.json`. Historical reports retain their original technical/pending statuses; these records establish the later user acceptance.

## Accepted deliverables

- TRAIN/VAL reporting configuration, additive reporting/figure modules and tests.
- Exact fixed-grid, calibration, prevalence/mask, inductive, seed/factor, training-history, resource, campaign-context and detection-time tables, with provenance.
- All four research questions and six user-supplied contributions, distinguishing design intent, implementation, experimental support, missing evidence, later-phase responsibility, and permitted/prohibited paper claims.
- Eleven final publication figure sets (22 PNG/PDF files), captions, source manifest and numerical source evidence. Initial drafts remain preserved and are not substituted for final figure_manifest_v2 entries.
- Nineteen-sheet final research workbook v2 with independent cell/formula/table verification; the earlier formatting draft and all previous workbooks remain unchanged.
- Technical acceptance report, independent reconciliation, test evidence, limitations, discrepancy register, delivery hashes and this acceptance documentation.

## Verification and preservation

57 tests passed (26 new reporting and 31 existing temporal-contract tests). Independent saved-score checks cover all 20 detector/organization/TRAIN-VAL components, with exact confusion counts and AP/ROC/loss agreement within 1e-12. All 10 threshold artifacts and 10 paired organization/split cohorts reconcile. This is saved-evidence reporting, not repeated model inference or campaign evaluation.

The reporting preservation check recorded 12,254 unchanged pre-existing metadata paths, 241 critical accepted file hashes and 254 reporting-input hashes. Acceptance additionally rechecks the sealed reporting delivery and original numerical inputs without reading TEST payloads. The workbook's exporter post-save failure is documented; the final file passed 58,578 source-cell comparisons, 12 formula/cache checks and 21 native-table checks. No remaining numerical discrepancy was hidden or repaired by changing accepted evidence.

Primary frozen protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

Verified Git commit: `5de030316176a27889054d0e782cb1ad92171cb5`. Its protocol blob and the working file have the same SHA256. No protocol amendment was made.

## Scientific limits carried forward

- The accepted VAL inventory has **0/171 campaigns undetected by every targeted organization**, under both policies. It does not demonstrate federated recovery of campaigns missed everywhere locally.
- Detection anywhere, detection at all targeted organizations, organization-trial detection, local target-User coverage and detection time remain separate. Both policies detect 548/549 organization trials; User coverage is 13,733/36,000 locally and 15,111/36,000 with indicators.
- VAL selected models and calibrated thresholds; no held-out generalization result exists here. TRAIN frozen-threshold metrics are retrospective in-sample diagnostics.
- The 1% target belongs to eligible fixed-grid negative User-times, not operational event/campaign FPR. AP is tied-score average precision; macro and pooled summaries remain separate.
- Shared background, three temporal seed blocks, controlled-family confounding, evaluator-only credential reuse and RIP's diversity-per-attempt definition limit inference. No naive IID confidence interval or causal attribution claim is made.
- Temporal attribution, null/right-censored detection times, ambiguous-match rules and final-ten-minute operational coverage remain unchanged. Detected-only User-delay medians compare different detected populations, not a paired causal speedup.
- Indicators are locally alerted suspicious IPs, not oracle attacker lists, and zero simulated delay is not realistic network latency.
- Future federation transfers learned patterns through model updates; current local GraphSAGE does not reconstruct a cross-organization graph or IP relationships. Privacy, robustness, integrated ledger guarantees/overhead, production latency and cyber-physical effectiveness remain unsupported by this local evaluation.

## Next authorized action

The user may commit the curated accepted code, protocols, reports, figures, workbook and acceptance records. This documentation approval does not authorize TEST, Stage C, Phase 7 or any later implementation. After the user says **done**, stop and wait for further instructions.

Large private replay journals, raw records, graphs and model/prediction archives remain preserved locally. A curated Git commit contains reporting/code/public aggregate evidence and their hash references, not those private archives. It is not claimed to be a self-contained archive of every raw research artifact.
'''
text(FINAL/'acceptance_summary_v1.md',acceptance_summary)
# Curate the pending Subphase 8 prerequisites because HEAD still points to Subphase 7.
selected=set()
def add(p):
 p=Path(p)
 if p.is_file():selected.add(p.relative_to(ROOT).as_posix())
for p in ['prepare_subphase8.py','configs/phase6/detectability_protocol_v1.json','configs/phase6/final_reporting_v1.json','src/phase6/detectability.py','src/phase6/run_detectability.py','src/phase6/detectability_batch.py','src/phase6/final_reporting.py','src/phase6/run_final_reporting.py','src/phase6/final_reporting_figures.py','tests/phase6/test_detectability.py','tests/phase6/test_detectability_batch.py','tests/phase6/test_final_reporting.py']:add(ROOT/p)
for folder in [ROOT/'reports/phase6/subphase9_plan_v1',REPORT]:
 for p in folder.rglob('*'):add(p)
for p in FINAL.glob('*'):add(p)
add(event)
for p in (ROOT/'reports/phase6').glob('progress_v*.json'):
 if int(p.stem.split('_v')[1])>=11:add(p)
base=ROOT/'reports/phase6/detectability'
for p in base.rglob('*'):
 if not p.is_file():continue
 relative=p.relative_to(base)
 if 'private' in relative.parts or 'full_v1' in relative.parts:continue
 if p.name=='user_occurrence_statistics_no_ids.json':continue
 if p.suffix in ['.json','.md','.csv','.py','.mjs','.txt']:add(p)
for name in ['summary.json','complete.json']:add(base/'full_v1/validated_171/attempt_00001'/name)
add(base/'full_v1/progress.jsonl')
for folder in [OUT,ROOT/'outputs/phase6_subphase8_technical_review_20261116_v1',ROOT/'outputs/all_phases_20261114_v4']:
 for p in folder.rglob('*'):
  if p.is_file() and not p.name.endswith('.xlsx.inspect.ndjson') and p.suffix in ['.xlsx','.png','.pdf','.json','.ndjson']:add(p)
pathfile=FINAL/'COMMIT_PATHS_v1.txt';selected.add(pathfile.relative_to(ROOT).as_posix())
text(pathfile,'\n'.join(sorted(selected))+'\n')
assert all('/private/' not in p and not any(x in p for x in ['.sqlite','_TEST']) for p in selected)
assert not any((ROOT/p).stat().st_size>=100*1024**2 for p in selected),'Oversize Git artifact'
verification=dict(status='PASS_ACCEPTANCE_DOCUMENTATION',scope='USER_ACCEPTED_OPTION_A_STAGES_A_B',sealed_reporting_artifacts_unchanged=len(delivery['artifact_sha256']),original_numerical_input_hashes_unchanged=len(input_hashes),four_research_questions_and_six_contributions_verified=True,eleven_final_figures_and_captions_preserved=True,frozen_protocol_sha256=expected,verified_git_commit=commit,current_progress='reports/phase6/progress_v20.json',TEST_access=False,phase6_status='PENDING_HELD_OUT_TEST_EVALUATION',phase7_started=False,git_staging_performed=False,git_commit_performed=False,curated_commit_file_count=len(selected),curated_commit_bytes=sum((ROOT/p).stat().st_size for p in selected),acceptance_record_sha256=sha(accept),approval_event_sha256=sha(event),current_progress_sha256=sha(progress),commit_pathspec_sha256=sha(pathfile))
write(FINAL/'acceptance_documentation_verification_v1.json',verification)
# The verification record belongs to the same curated commit; update only the newly prepared pathspec before delivery.
paths=sorted(selected|{'reports/phase6/final/acceptance_documentation_verification_v1.json'})
with pathfile.open('w',encoding='utf-8',newline='\n') as f:f.write('\n'.join(paths)+'\n')
print(json.dumps(dict(status='USER_ACCEPTED_OPTION_A',commit_files=len(paths),total_mib=sum((ROOT/p).stat().st_size for p in paths)/1048576,progress=str(progress),TEST_authorized=False,phase7_started=False)))
