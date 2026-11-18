"""Disposable synthetic subprocess only; no actual model/data reader is invoked."""
from pathlib import Path
from types import SimpleNamespace
import json,os,sys
PROJECT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(PROJECT),str(PROJECT/'tests/phase6')]
from test_continuation_v3 import world,RealStoreBackend
from src.phase6.heldout_driver_v2 import Driver as V2Driver
from src.phase6.continuation_contract_v4 import ContinuationScope
from src.phase6.continuation_driver_v4 import Driver as V4Driver

def make_world(root):return world.__wrapped__(SimpleNamespace(mktemp=lambda _:root))

class Backend(RealStoreBackend):
    def prepare(self,row,root):
        ports,schedules,contexts=super().prepare(row,root)
        for p in ports.values():p.service.db.execute('PRAGMA wal_autocheckpoint=0')
        return ports,schedules,contexts

def main():
    root=Path(sys.argv[1]).resolve();stage=sys.argv[2];version=sys.argv[3]
    assert not root.is_relative_to(PROJECT) and not PROJECT.is_relative_to(root)
    assert 'wal_v4' in str(root).lower(),'Dedicated synthetic directory required'
    _,old,bundles=make_world(root/'metadata')
    if version=='v2':scope=old;driver=V2Driver
    else:
        scope=ContinuationScope.synthetic(root/'continuation',old.catalog,Path(sys.argv[4]));driver=V4Driver
    backend=Backend(scope,bundles);row=backend.inventory()[0]
    def snapshot(reason):
        value=dict(stage=reason,model_calls=sum(b.model.calls for b in bundles.values()),variant=row['variant_id'],source=str(scope.output_root/row['variant_id']))
        with (root/'child_exit.json').open('x') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
        os._exit(73) # intentional synthetic crash; no signal to any process
    if stage=='after_expiry':
        from src.phase6.indicator_sharing import Network
        original=Network.advance
        def advance(network,t):
            before=len(network.expired);original(network,t)
            if len(network.expired)>before:snapshot('after_expiry')
        Network.advance=advance
    def fail(s):
        if s==stage:snapshot(s)
    driver(scope,backend).run_instance(row,fail)
    raise RuntimeError('Requested synthetic crash stage was not reached')

if __name__=='__main__':main()
