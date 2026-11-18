"""Independent negative review and repeated working-WAL restart."""
from pathlib import Path
import json
import pytest
from wal_fixture_worker_v4 import make_world,Backend
from test_continuation_wal_v4 import crashed,physical_files,science
from src.phase6.heldout_driver_v2 import Driver as V2Driver
from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope
from src.phase6.continuation_reader_v4 import build_certificate
from src.phase6.continuation_driver_v4 import Driver as V4Driver,run_lease
from src.phase6.continuation_recovery_v4 import Workspace

def prepare(root,stage='after_local:Org3'):
    first=crashed(root/'a',stage);source=Path(first['source']);_,old,bundles=make_world(root/'m')
    row=Backend(old,bundles).inventory()[0];cert=root/'c.json';build_certificate(CapturePermit.synthetic(source,old.catalog),old.catalog,row,cert)
    return first,source,old,bundles,row,cert

def test_unexpected_working_sidecars_cannot_poison_initial_restore(tmp_path_factory):
    root=tmp_path_factory.mktemp('wal_v4_guard');first,source,old,bundles,row,cert=prepare(root)
    new=ContinuationScope.synthetic(root/'n',old.catalog,cert)
    target=new.output_root/row['variant_id']/'Org1/private/local.sqlite-shm';target.parent.mkdir(parents=True);target.write_bytes(b'UNEXPECTED_SYNTHETIC_SIDECAR')
    with run_lease(new.output_root):
        workspace=Workspace(new)
        with pytest.raises(ValueError,match='sidecar'):workspace.prepare()

def test_second_crash_with_nonempty_working_wal_reuses_committed_scores(tmp_path_factory):
    root=tmp_path_factory.mktemp('wal_v4_restart');first,source,old,bundles,row,cert=prepare(root)
    before=physical_files(source)
    second=crashed(root/'b','after_local:Org4','v4',cert)
    target=Path(second['source']);assert any(p.stat().st_size for p in target.rglob('local.sqlite-wal'))
    new=ContinuationScope.synthetic(root/'b/continuation',old.catalog,cert)
    V4Driver(new,Backend(new,bundles)).run_instance(row)
    new_calls=sum(b.model.calls for b in bundles.values())
    _,reference,ref_models=make_world(root/'r');V2Driver(reference,Backend(reference,ref_models)).run_instance(row)
    assert science(target)==science(reference.output_root/row['variant_id'])
    assert first['model_calls']+second['model_calls']+new_calls==sum(b.model.calls for b in ref_models.values())
    assert before==physical_files(source)
    with (root/'second_restart_evidence.json').open('x') as f:json.dump(dict(status='PASS',original_calls=first['model_calls'],first_continuation_calls=second['model_calls'],final_continuation_calls=new_calls,reference_calls=sum(b.model.calls for b in ref_models.values()),extra_committed_calls=0,original_physical_unchanged=True),f,indent=2)
