from pathlib import Path
import json,hashlib,re,shutil
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');BASE=ROOT/'reports/phase6/detectability';REVIEW=BASE/'technical_review_v2';FINAL=REVIEW/'final_v1';AUD=REVIEW/'continuation_00004';WORK=Path(r'C:\Users\Gulso\OneDrive\Documents\ChatGPT\research')
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,x):
 with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(x,f,indent=2);f.write('\n')
summary=load(FINAL/'summary.json');assert summary['status']=='PASS' and not summary['user_accepted'] and not summary['subphase9_started']
qa=load(ROOT/'outputs/phase6_subphase8_technical_review_20261116_v1/saved_file_verification.json');assert qa['status']=='PASS_SAVED_WORKBOOK_VERIFICATION'
text=(FINAL/'TECHNICAL_ACCEPTANCE_REPORT.md').read_text()
# Keep the generated draft intact. Issue a clean, additive final report.
text=re.sub(r'\n{3,}','\n\n',text)
append='''
## Audit completion supplement

Real saved-alert attribution across both policies contains **120,418 unique matches**, **325,851 unattributed alert rows**, and **zero ambiguous matches**. Each real branch contains one campaign, so zero observed ambiguity does not demonstrate overlapping-campaign behavior; frozen boundary tests cover ambiguous overlap and prevent double credit. Unattributed rows are not automatically verified false positives.

The two organization-policy records without detection refer to the same Org5 trial in CFV1_RA_CS_030_SEED1002_VAL. Each has 84 exposed Users, zero qualifying detections and a 3,598.321715-second censor horizon. All other targeted organization trials detect. The local-only User coverage is 38.147222%; indicator-assisted coverage is 41.975000%, a 3.827778 percentage-point increase over local branch-specific User occurrences. These are operational coverage statistics, not the primary fixed-grid recall or operational FPR.

Frozen primary protocol SHA256: `9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b`.

Frozen campaign-detectability protocol SHA256: `f63e0bb73253eea4a8c8d7abc4231f94069aaf15c3eef68eeb3fa1b00d49bc55`.

### Excel documentation and verification

The separate six-sheet workbook is `outputs/phase6_subphase8_technical_review_20261116_v1/CredBlock_FL_Phase6_Subphase8_Technical_Review_v1.xlsx`. It contains campaign, organization, factor, operational and complete sidecar evidence with a formula-based summary. Prior all-phases master workbooks remain unchanged; the v4 master hash was independently reconfirmed.

All 51,235 source data cells, 14 formulas and their summary caches, seven native tables and the six-sheet structure were checked directly in the saved XLSX. No formula-error cells were found. Summary previews were visually inspected. The exporter saved the workbook and then terminated with Windows exit code -1073740791. This export-runtime anomaly is retained in saved_file_verification.json; the saved workbook passed independent structural/data checks. An initial duplicate native-table name was corrected before any delivered workbook was created.

### Final disposition

**Technical PASS; ready for explicit user acceptance.** The pending-review tracker has been superseded append-only by TECHNICAL_PASS_AWAITING_USER_ACCEPTANCE after validation completed. No USER_ACCEPTED record is created. Subphase 9 remains NOT_STARTED. No expensive detector inference, model fitting, threshold calibration, campaign evaluation batch or TEST outcome analysis was repeated.
'''
destination=FINAL/'FINAL_TECHNICAL_ACCEPTANCE_REPORT.md'
with destination.open('x',encoding='utf-8',newline='\n') as f:f.write(text.rstrip()+'\n\n'+append.strip()+'\n')
history=[dict(attempt='technical_review_v1',disposition='PRESERVED_INITIAL_REVIEW_REQUIRED',issue='Strict equality of sealed and actual file sets rejected SQLite auxiliary sidecars.'),dict(attempt='technical_review_v2 initial attempt',disposition='PRESERVED_CHECKER_FAILURE',issue='Logical LF decision digest incorrectly compared with CRLF file-byte digest.'),dict(attempt='continuation_00002',disposition='PRESERVED_CHECKER_FAILURE',issue='Independent organization serialization omitted existing coverage/status/local-onset fields; campaign outcome had matched.'),dict(attempt='continuation_00003',disposition='PRESERVED_SUPERSEDED_CHECKER_STOPPED',issue='Stopped after recognizing missing exact UNDETECTED_WITHIN_HORIZON serialization; no detector evaluation was stopped.'),dict(attempt='continuation_00004',disposition='PASS_ALL_171',issue=None),dict(attempt='issuance_and_observation_audit_v1',disposition='PASS_ALL_855_ORGANIZATION_REPLAYS',issue=None)]
write(REVIEW/'audit_history_v1.json',history)
sources=FINAL/'audit_sources';sources.mkdir()
for name in ['subphase8_independent_review.py','subphase8_independent_review_v2.py','subphase8_independent_review_v3.py','subphase8_independent_review_v4.py','subphase8_independent_review_v5.py','subphase8_independent_issuance_audit.py','finalize_subphase8_technical_review.py','prepare_subphase8_workbook.py','verify_subphase8_workbook.py','seal_subphase8_review.py']:
 shutil.copyfile(WORK/name,sources/name)
shutil.copyfile(WORK/'excel_all_phases_v1/build_subphase8_review.mjs',sources/'build_subphase8_review.mjs')
p=load(ROOT/'reports/phase6/progress_v14.json');p['version']='phase6-progress-v15';p['recorded_on_local_date']='2026-11-16';p['subphases']['8'].update(status='TECHNICAL_PASS_AWAITING_USER_ACCEPTANCE',validated_val_instances=171,pending_val_instances=0,full_run_launched=True,technical_report=str(destination.relative_to(ROOT)).replace('\\','/'),independent_completion_manifests=1362,verified_artifact_hash_entries=15302);p['subphases']['9']['status']='NOT_STARTED';p['next_exact_action']='User reviews and explicitly accepts Subphase 8. Do not record USER_ACCEPTED or start Subphase 9 without that approval.';write(ROOT/'reports/phase6/progress_v15.json',p)
write(REVIEW/'review_status_completed.json',dict(technical_status='PASS',subphase8_status='TECHNICAL_PASS_AWAITING_USER_ACCEPTANCE',independently_validated=171,organization_replays=855,user_accepted=False,subphase9_started=False,report=str(destination.relative_to(ROOT)).replace('\\','/'),prior_files_preserved=12182,sidecars_preserved=1710,nonempty_wals=0,workbook_sha256=qa['sha256']))
paths=[p for p in REVIEW.rglob('*') if p.is_file()]+[ROOT/'reports/phase6/progress_v14.json',ROOT/'reports/phase6/progress_v15.json']+[p for p in (ROOT/'outputs/phase6_subphase8_technical_review_20261116_v1').iterdir() if p.is_file() and p.suffix in ['.xlsx','.json','.ndjson']]
manifest={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
write(REVIEW/'delivery_manifest_v1.json',dict(status='PASS_TECHNICAL_DELIVERY_AWAITING_USER_ACCEPTANCE',artifact_sha256=manifest,original_failed_review_manifest={p.relative_to(ROOT).as_posix():sha(p) for p in (BASE/'technical_review_v1').rglob('*') if p.is_file()},original_run_untouched=True))
for path,h in manifest.items():assert sha(ROOT/path)==h,path
print(json.dumps(dict(technical_status='PASS',new_delivery_artifacts=len(manifest),report=str(destination),user_accepted=False,subphase9_started=False)))
