"""Frozen full-inventory metadata and mixed-origin completion gates."""
from pathlib import Path
import json
import pytest
from wal_fixture_worker_v4 import make_world,Backend
from src.phase6.heldout_contract_v2 import digest,ORGS
from src.phase6.continuation_contract_v4 import ContinuationScope
from src.phase6.continuation_manifest_v4 import FullRunManifest,frozen_rows

def test_all171_metadata_and_incomplete_seal_rejection(tmp_path):
    _,old,bundles=make_world(tmp_path/'wal_v4_meta');scope=ContinuationScope.synthetic(tmp_path/'run',old.catalog)
    original=Backend(scope,bundles).inventory()[0];rows=[]
    for seed in (1001,1002,1003):
        for n in range(57):
            rows.append(dict(original,variant_id=f'SYNTHETIC_{n:03d}_SEED{seed}_TEST',seed=str(seed)))
    rows=frozen_rows(scope,rows);assert len(rows)==171 and len(rows)*len(ORGS)==855
    ledger=FullRunManifest(scope,rows,scope.output_root/'mixed_manifest')
    with pytest.raises(ValueError,match='Incomplete'):ledger.seal()
    assert not (ledger.root/'full_run_completion.json').exists()
    changed=[dict(r) for r in rows];changed[-1]['seed']='1001'
    with pytest.raises(ValueError):frozen_rows(scope,changed)
    changed=[dict(r) for r in rows];changed[-1]['variant_id']=changed[0]['variant_id']
    with pytest.raises(ValueError):frozen_rows(scope,changed)

def test_v4_certificate_required_before_any_legacy_reader(tmp_path,monkeypatch):
    from src.phase6.continuation_reader_v4 import PredecessorReader
    _,old,bundles=make_world(tmp_path/'wal_v4_meta')
    with pytest.raises((KeyError,ValueError)):
        PredecessorReader(dict(format='phase6-continuation-certificate-v3',certificate_id='wrong',body={}),old.catalog)
