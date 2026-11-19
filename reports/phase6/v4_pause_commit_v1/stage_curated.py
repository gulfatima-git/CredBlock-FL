"""Prepare/stage an explicit metadata-only allowlist. Never commit or run inference."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys
import psutil
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
MANIFESTS=[
 'reports/phase6/v4_pilot_capacity_reassessment_v1/delivery_manifest_v1.json',
 'reports/phase6/v4_pilot_execution_v1/delivery_manifest_v1.json',
 'reports/phase6/v4_pilot_execution_v1/delivery_manifest_v2.json',
 'reports/phase6/v4_pilot_preparation_v1/delivery_manifest_v1.json',
 'reports/phase6/v4_pilot_readiness_review_v1/delivery_manifest_v1.json']
EXTRAS=[
 'reports/phase6/v4_pilot_preflight_v1/TECHNICAL_PREFLIGHT_REPORT.md',
 'reports/phase6/v4_pilot_preflight_v1/committed_allowlist_verification.json',
 'reports/phase6/v4_pilot_preflight_v1/preflight_verification.json',
 'reports/phase6/v4_pilot_preparation_v1/final_delivery_reconciliation.json',
 'reports/phase6/v4_remaining165_manual_v1/prepare_execution_grant.py',
 'reports/phase6/v4_remaining165_manual_v1/user_execution_authorization.json',
 'reports/phase6/v4_remaining165_manual_v1/pause_milestone_v1.json',
 'reports/phase6/heldout_test_v2/wal_v4_authorizations/remaining165_execution_APPROVED_v1.json']
EXCLUDED={'untracked_exclusion_inventory.json','evaluator_stdout.log','evaluator_stderr.log'}
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True)
def put_once(path,data):
    if path.exists():assert path.read_bytes()==data,'Existing preparation differs: '+str(path)
    else:
        with path.open('xb') as f:f.write(data)
def main():
    a=argparse.ArgumentParser();a.add_argument('--stage',action='store_true');args=a.parse_args()
    assert not git('diff','--name-only').strip(),'Tracked modifications exist; review before staging'
    assert not git('diff','--cached','--name-only').strip(),'Existing staged files; do not mix commits'
    for p in psutil.process_iter(['cmdline']):
        try:assert not any(x in ('src.phase6.continuation_driver_v4','src.phase6.heldout_driver_v2') for x in (p.info['cmdline'] or [])),'Evaluator is running'
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    expected={};paths=set()
    def manifest(name):
        d=read(ROOT/name);paths.add(name)
        for key in ('files_sha256','additional_files_sha256'):
            for p,h in d.get(key,{}).items():
                if p in expected:assert expected[p]==h,'Conflicting published hash: '+p
                expected[p]=h;paths.add(p)
    for m in MANIFESTS:manifest(m)
    paths.update(EXTRAS);paths.update(f'reports/phase6/progress_v{v}.json' for v in range(35,43))
    paths={p for p in paths if Path(p).name not in EXCLUDED}
    certificate='reports/phase6/heldout_test_v2/wal_v4_captures/pilot_preparation_v1/CFV1_RA_CS_005_SEED1003_TEST/predecessor_certificate.json'
    approved_roots=('reports/phase6/v4_pilot_capacity_reassessment_v1/',
      'reports/phase6/v4_pilot_execution_v1/','reports/phase6/v4_pilot_preflight_v1/',
      'reports/phase6/v4_pilot_preparation_v1/','reports/phase6/v4_pilot_readiness_review_v1/',
      'reports/phase6/v4_remaining165_manual_v1/')
    approved_auth={'source_quiescence_preparation_v1.json','capture_preparation_only_v1.json',
      'pilot_campaign6_execution_DRAFT_v1.json','pilot_campaign6_execution_APPROVED_v1.json',
      'remaining165_execution_APPROVED_v1.json'}
    for p in paths:
        assert '\\' not in p and '..' not in Path(p).parts and not Path(p).is_absolute(),p
        q=ROOT/p;assert q.is_file() and not q.is_symlink(),p
        allowed=p.startswith(approved_roots) or p in {f'reports/phase6/progress_v{v}.json' for v in range(35,43)} or p==certificate
        allowed|=p.startswith('reports/phase6/heldout_test_v2/wal_v4_authorizations/') and Path(p).name in approved_auth
        assert allowed,'Outside curated scope: '+p
        assert q.suffix in {'.json','.jsonl','.md','.py','.csv'},p
        assert not any(x in Path(p).parts for x in ('private','physical','oracles','wal_oracle_copies','__pycache__')),p
        if p in expected:assert sha(q)==expected[p],'Published evidence changed: '+p
    pause=read(ROOT/'reports/phase6/v4_remaining165_manual_v1/pause_milestone_v1.json')
    assert pause['runner_recorded_complete']==30 and pause['remaining_instances']==141
    assert pause['previously_independently_validated']==6 and pause['additional_instances_pending_external_validation']==24
    assert sha(Path(pause['source_pause_record']))==pause['source_sha256'],'Native pause record changed'
    run=ROOT/'reports/phase6/heldout_test_v2/wal_v4_transition/pilot_campaign6_v1'
    assert (run/'stop_after_current.request.json').is_file(),'Pause request missing'
    p42=read(ROOT/'reports/phase6/progress_v42.json');assert p42['remaining_TEST_pause']==pause
    controls=['reports/phase6/v4_pause_commit_v1/'+n for n in ('stage_curated.py','candidate_manifest_v1.json','curated_paths_v1.txt')]
    staged_paths=sorted(paths|set(controls)|{'.gitattributes'})
    rows=[dict(path=p,bytes=(ROOT/p).stat().st_size,sha256=sha(ROOT/p)) for p in sorted(paths)]
    plan=dict(status='CURATED_PAUSED_30_METADATA_ONLY',files=rows,existing_delivery_manifests=MANIFESTS,
        packaging_controls=controls,scientific_results_modified=False,original_and_forensic_payloads_included=False,
        exclusions=['Untracked-path inventory','Raw logs','Actual TEST observations, labels, row-level prediction archives, graphs and database/sidecar files','Forensic snapshot','Older unrelated progress v21-v32'],
        gitattributes_change='Append exact-byte -text rules for allowlisted new files only; preserve existing rules',
        runner_recorded_complete=30,external_independent_validation_complete=6,additional_external_validation_pending=24,remaining=141)
    put_once(HERE/'candidate_manifest_v1.json',(json.dumps(plan,indent=2)+'\n').encode())
    put_once(HERE/'curated_paths_v1.txt',('\n'.join(staged_paths)+'\n').encode())
    print(f'ALLOWLIST VERIFIED: {len(staged_paths)} files; {sum(x["bytes"] for x in rows):,} evidence bytes plus packaging metadata.')
    print('No raw TEST payload, forensic file, model archive or untracked-path inventory is selected.')
    print('Exact list:',HERE/'curated_paths_v1.txt')
    if not args.stage:
        print('PREVIEW ONLY: no index, tracked file, runtime control or scientific artifact changed.');return
    attrs=ROOT/'.gitattributes';old=attrs.read_bytes();new=old
    if new and not new.endswith(b'\n'):new+=b'\n'
    additions=[]
    for p in staged_paths:
        rule=('/'+p+' -text').encode()
        if rule not in old.splitlines():additions.append(rule)
    if additions:new+=b'\n# Exact bytes for additive v4 pilot/pause evidence.\n'+b'\n'.join(additions)+b'\n'
    assert new.startswith(old),'Existing attributes must remain unchanged'
    if new!=old:attrs.write_bytes(new)
    subprocess.run(['git','-c','core.autocrlf=false','--literal-pathspecs','add','--pathspec-from-file='+str(HERE/'curated_paths_v1.txt')],cwd=ROOT,check=True)
    actual=set(git('diff','--cached','--name-only').splitlines())
    assert actual==set(staged_paths),'Staged set differs from exact allowlist; STOP before committing'
    for r in rows:
        blob=subprocess.check_output(['git','show',':'+r['path']],cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest()==r['sha256'],'Staged byte conversion: '+r['path']
    print(git('diff','--cached','--stat'))
    print('PASS: exact staging and staged hashes. No commit created. Pause request preserved.')
if __name__=='__main__':
    try:main()
    except Exception as e:print('STOP:',str(e),file=sys.stderr);sys.exit(1)
