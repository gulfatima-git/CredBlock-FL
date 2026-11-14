"""Read-only artifact checks plus new append-only delivery/progress records."""
from pathlib import Path
import hashlib,json,math,zipfile,xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[3]
def load(p): return json.loads((root/p).read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,obj):
    with (root/p).open('x',encoding='utf-8') as f: json.dump(obj,f,indent=2)
baseline=load('reports/phase6/training/accepted_inputs_before_subphase3_v1.json')
assert len(baseline)==92
assert all(sha(root/p)==h for p,h in baseline.items())
base=root/'reports/phase6/training/final_v1'
manifest=load('reports/phase6/training/final_v1/artifact_sha256.json')
assert all(sha(base/p)==h for p,h in manifest.items())
summary=load('reports/phase6/training/final_v1/summary.json')
book=root/'outputs/phase6_subphase3_v1/CredBlock_FL_Phase6_Local_Training_v1.xlsx'
ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(book) as z:
    assert z.testzip() is None
    tree=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    cells={c.attrib['r']:c for c in tree.findall('.//s:c',ns)}
    assert not any(c.attrib.get('t')=='e' for c in cells.values())
    def val(a): return float(cells[a].find('s:v',ns).text)
    for i,m in enumerate(summary['models'],7):
        for col,v in [('B',m['selected_candidate']['hidden_dim']),('C',m['selected_epoch']),('D',m['selected_model_train_metrics']['eligible']),('E',m['validation']['eligible']),('F',m['validation']['average_precision']),('G',m['validation']['bce']),('H',m['selected_run_seconds']),('I',m['observed_training_rss_peak_bytes']/1048576)]:
            assert math.isclose(val(f'{col}{i}'),v,rel_tol=1e-12)
    for a,v in [('B14',sum(m['validation']['average_precision'] for m in summary['models'])/5),('B16',414573),('B17',285918)]:
        assert cells[a].find('s:f',ns) is not None
        assert math.isclose(val(a),v,rel_tol=1e-12)
    assert val('B18')==10260
progress=load('reports/phase6/progress_v3.json')
progress.update(version='phase6-progress-v4',model_training_performed=True,next_exact_action='User review and acceptance of Subphase 3; do not start Subphase 4 before acceptance')
progress['subphases']['2']={'status':'USER_ACCEPTED','evidence':'reports/phase6/pipeline/acceptance_v1.json'}
progress['subphases']['3']={'status':'TECHNICAL_GATE_PASS_AWAITING_USER_ACCEPTANCE','evidence':'reports/phase6/training/final_v1/ACCEPTANCE_REPORT.md','organizations':5,'verified_cache_files':10260,'distinct_tests_passed':116,'exact_model_reproductions':5,'test_branches_opened':0}
write('reports/phase6/progress_v4.json',progress)
write('reports/phase6/training/verification_v1.json',{
 'status':'PASS_DELIVERY_VERIFICATION','recorded_on_local_date':'2026-11-14',
 'accepted_files_preserved':92,'final_manifest_files_verified':len(manifest),
 'full_training_gate':summary['status'],'verified_cache_files':10260,
 'workbook':str(book),'workbook_sha256':sha(book),'xlsx_zip_integrity':'PASS',
 'xlsx_model_values_match_final_summary':True,'xlsx_error_cells':0,
 'xlsx_formula_caches_match':True,'live_formula_dependency_test':'PASS in builder',
 'workbook_export_process_exit_code':1,
 'export_anomaly':'Artifact Tool exported and saved the workbook but exited 1 without an error message; ZIP integrity, source values and formula caches independently verified.',
 'optional_curve_plot':'Not generated: matplotlib is absent from both existing Python environments. Per-epoch curves remain available in original epochs.jsonl logs; no dependency was installed.',
 'user_acceptance_subphase3':'PENDING','test_evaluation':'NOT_PERFORMED',
 'final_artifact_manifest_sha256':sha(base/'artifact_sha256.json')})
print(json.dumps({'status':'PASS','accepted_files_preserved':92,'workbook_verified':True,'progress':'reports/phase6/progress_v4.json'}))
