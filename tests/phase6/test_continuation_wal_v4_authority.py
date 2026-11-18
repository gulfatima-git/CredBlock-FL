"""Negative-only authority tests; no approval artifact is created."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.phase6.heldout_contract_v2 import ROOT,Catalog
from src.phase6.continuation_contract_v4 import CapturePermit,ContinuationScope

@pytest.mark.parametrize('role',['capture','execution'])
def test_forbidden_existing_approval_path_denied_before_lookup(role,monkeypatch,tmp_path):
    catalog=SimpleNamespace(fixture_only=False,identity='synthetic-metadata-only')
    monkeypatch.setattr(Catalog,'permitted_metadata',classmethod(lambda cls:catalog))
    def forbidden(*a,**kw):raise AssertionError('Excluded approval path touched')
    monkeypatch.setattr(Path,'is_file',forbidden);monkeypatch.setattr(Path,'read_bytes',forbidden)
    path=ROOT/'data2/NEVER_OPEN_SYNTHETIC_DENIAL.json'
    with pytest.raises(ValueError):
        if role=='capture':CapturePermit.production(tmp_path,catalog,path)
        else:ContinuationScope.production(tmp_path,catalog,tmp_path/'no-certificate.json',path)
