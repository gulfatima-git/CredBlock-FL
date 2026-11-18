"""Crash at each recipient using generated RAM-only all-alert detectors."""
from pathlib import Path
import json,subprocess,sys
import pytest
from wal_fixture_allpositive_v4 import make_world
from wal_fixture_worker_v4 import Backend
from test_continuation_wal_v4 import physical_files,science
from src.phase6.heldout_contract_v2 import ROOT,ORGS
from src.phase6.heldout_driver_v2 import Driver as V2Driver
from src.phase6.continuation_driver_v4 import Driver as V4Driver
from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope
from src.phase6.continuation_reader_v4 import build_certificate

@pytest.fixture(scope='module')
def positive_reference(tmp_path_factory):
    root=tmp_path_factory.mktemp('wal_v4_positive_ref');_,old,bundles=make_world(root)
    row=Backend(old,bundles).inventory()[0];V2Driver(old,Backend(old,bundles)).run_instance(row)
    return old,row,sum(b.model.calls for b in bundles.values())

@pytest.mark.parametrize('org',ORGS)
def test_each_org_receipt_crash_is_exact(tmp_path,positive_reference,org):
    reference,row,calls=positive_reference;root=tmp_path/'wal_v4_p';stage='after_receipt:'+org
    r=subprocess.run([sys.executable,'-B',str(ROOT/'tests/phase6/wal_fixture_allpositive_v4.py'),str(root),stage,'v2'],capture_output=True,text=True,timeout=180)
    assert r.returncode==73,r.stderr
    exit=json.loads((root/'child_exit.json').read_text());source=Path(exit['source']);before=physical_files(source)
    _,old,bundles=make_world(root/'p');assert old.catalog==reference.catalog
    cert=root/'c.json';build_certificate(CapturePermit.synthetic(source,old.catalog),old.catalog,row,cert)
    scope=ContinuationScope.synthetic(root/'n',old.catalog,cert);V4Driver(scope,Backend(scope,bundles)).run_instance(row)
    assert science(scope.output_root/row['variant_id'])==science(reference.output_root/row['variant_id'])
    assert exit['model_calls']+sum(b.model.calls for b in bundles.values())==calls and physical_files(source)==before
