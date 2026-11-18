"""WAL capture+resume benchmark on already generated quiescent synthetic evidence."""
from pathlib import Path
import json,shutil,sys,time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests/phase6')]
from wal_fixture_worker_v4 import make_world,Backend
from test_continuation_wal_v4 import science,physical_files
from src.phase6.continuation_contract_v3 import CapturePermit as P3,ContinuationScope as S3
from src.phase6.continuation_contract_v4 import CapturePermit as P4,ContinuationScope as S4
from src.phase6.continuation_reader_v3 import build_certificate as C3
from src.phase6.continuation_reader_v4 import build_certificate as C4
from src.phase6.continuation_driver_v3 import Driver as D3
from src.phase6.continuation_driver_v4 import Driver as D4

def main():
    certpath=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve()
    research=Path(r'C:\Users\Gulso\OneDrive\Documents\ChatGPT\research')
    assert certpath.is_relative_to(research/'wal_v4_c') and output.is_relative_to(research) and output.name.startswith('wal_v4_')
    original=json.loads(certpath.read_bytes());source=Path(original['body']['source_root']);row=original['body']['row'];before=physical_files(source)
    output.mkdir(exist_ok=False);legacy=output/'selfcontained_reference/original'/source.name;legacy.mkdir(parents=True)
    for rel in original['body']['files']:
        if rel.endswith(('.sqlite','.sqlite-wal','.sqlite-shm','.sqlite-journal')):continue
        dest=legacy/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/rel,dest)
    for org in original['body']['stores']:
        dest=legacy/org/'private/local.sqlite';dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(original['body']['capture_root'])/org/'derived.sqlite',dest)
    (legacy.parent/'execution.lock').write_bytes(b'\n')
    cases=[];expected=None
    for label,src,Permit,Scope,Capture,Driver in [('v3_selfcontained_logical_reference',legacy,P3,S3,C3,D3),('wal_v4_physical_original',source,P4,S4,C4,D4)]:
        _,old,bundles=make_world(output/(label+'_meta'));assert old.catalog.identity==original['body']['origin']['catalog']
        capfile=output/(label+'.json');start=time.perf_counter();cpu=time.process_time()
        permit=Permit.synthetic(src,old.catalog) if Permit is P3 else Permit.synthetic(src,old.catalog,output/'capture_v4')
        Capture(permit,old.catalog,row,capfile);capture_seconds=time.perf_counter()-start
        scope=Scope.synthetic(output/(label+'_run'),old.catalog,capfile);resume=time.perf_counter()
        Driver(scope,Backend(scope,bundles)).run_instance(row)
        elapsed=time.perf_counter()-start;science_value=science(scope.output_root/row['variant_id'])
        if expected is None:expected=science_value
        assert science_value==expected
        cases.append(dict(version=label,capture_seconds=capture_seconds,resume_seconds=time.perf_counter()-resume,end_to_end_seconds=elapsed,cpu_seconds=time.process_time()-cpu,remaining_model_calls=sum(b.model.calls for b in bundles.values())))
        print(json.dumps(cases[-1]),flush=True)
    assert before==physical_files(source) and cases[0]['remaining_model_calls']==cases[1]['remaining_model_calls']
    result=dict(status='PASS_SYNTHETIC_CAPTURE_AND_RESUME_EQUIVALENCE',cases=cases,source_unchanged=True,scope='Single sample; v3 uses a separately constructed self-contained logical-reference fixture, not a substituted original certificate; no full-run ETA')
    with (output/'benchmark.json').open('x') as f:json.dump(result,f,indent=2)

if __name__=='__main__':main()
