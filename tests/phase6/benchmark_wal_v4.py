"""End-to-end production-path synthetic workload. Never imports a real model bundle."""
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace
import json,sys,time,os
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/phase6')]
from wal_fixture_worker_v4 import make_world,Backend
from test_continuation_wal_v4 import science
from src.phase6.heldout_contract_v2 import ORGS,Scope as V2Scope
from src.phase6.continuation_contract_v3 import ContinuationScope as V3Scope
from src.phase6.continuation_contract_v4 import ContinuationScope as V4Scope
from src.phase6.heldout_driver_v2 import Driver as V2Driver
from src.phase6.continuation_driver_v3 import Driver as V3Driver
from src.phase6.continuation_driver_v4 import Driver as V4Driver
import test_heldout_remediation_v2 as fixture

class Workload(Backend):
    def __init__(self,scope,bundles,count):super().__init__(scope,bundles);self.count=count
    def prepare(self,row,root):
        ports,schedules,contexts=super().prepare(row,root)
        for org in ORGS:
            for n in range(self.count):
                t=ports[org].branch.start+timedelta(seconds=2+n)
                schedules[org][t]=dict(observations=[fixture.observable(t,org)],tokens=['B'+str(n)],heartbeat=False,final=False)
        return ports,schedules,contexts

def main():
    base=Path(sys.argv[1]).resolve();require=not base.is_relative_to(ROOT)
    assert require and 'wal_v4' in str(base).lower();base.mkdir(parents=True,exist_ok=False)
    count=int(sys.argv[2]);cases=[];expected=None
    for version,Scope,Driver in [('v2',V2Scope,V2Driver),('v3',V3Scope,V3Driver),('wal_v4',V4Scope,V4Driver)]:
        _,old,bundles=make_world(base/(version+'_meta'));scope=Scope.synthetic(base/version,old.catalog)
        backend=Workload(scope,bundles,count);row=backend.inventory()[0];wall=time.perf_counter();cpu=time.process_time()
        Driver(scope,backend).run_instance(row)
        elapsed=time.perf_counter()-wall;seconds=time.process_time()-cpu;root=scope.output_root/row['variant_id']
        value=science(root)
        if expected is None:expected=value
        assert value==expected
        import psutil
        cases.append(dict(version=version,seconds=elapsed,cpu_seconds=seconds,model_calls=sum(b.model.calls for b in bundles.values()),peak_rss_bytes=getattr(psutil.Process().memory_info(),'peak_wset',psutil.Process().memory_info().rss),extra_events_per_org=count,organizations=5,primary_grid_predictions=60,root=str(root)))
        print(json.dumps(cases[-1]),flush=True)
    assert len({c['model_calls'] for c in cases})==1
    result=dict(status='PASS_SYNTHETIC_END_TO_END_EQUIVALENCE',cases=cases,
                v2_over_v4_ratio=cases[0]['seconds']/cases[2]['seconds'],v3_over_v4_ratio=cases[1]['seconds']/cases[2]['seconds'],
                scope='One synthetic sample per version, shared host, toy RAM models, full graph/sampler/persistence/grid/indicator/offline-metrics path; not a production ETA')
    with (base/'benchmark.json').open('x') as f:json.dump(result,f,indent=2)

if __name__=='__main__':main()
