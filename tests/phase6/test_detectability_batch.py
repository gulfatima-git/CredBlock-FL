import json
from pathlib import Path
import pytest
from src.phase6 import detectability_batch as b

def sandbox(tmp_path,monkeypatch):
 monkeypatch.setattr(b,'ROOT',tmp_path);monkeypatch.setattr(b,'FULL',tmp_path/'full')
 p=tmp_path/'configs/phase6/detectability_protocol_v1.json';p.parent.mkdir(parents=True);p.write_text('{}')
 monkeypatch.setattr(b,'pinned',lambda:({},{}))

def test_unreviewed_full_launch_fails_before_any_plan_or_dataset_access(monkeypatch):
 monkeypatch.setattr(b,'pinned',lambda:pytest.fail('Review gate must precede source access'))
 with pytest.raises(ValueError,match='review-gated'):b.authorize(False)

def test_attempts_append_without_overwriting_failed_partial_files(tmp_path):
 a=b.new_attempt(tmp_path/'trial');(a/'partial.txt').write_text('preserve')
 c=b.new_attempt(tmp_path/'trial');assert c!=a and (a/'partial.txt').read_text()=='preserve'

def test_incomplete_attempt_not_a_completion_and_sealed_next_attempt_resumes(tmp_path,monkeypatch):
 sandbox(tmp_path,monkeypatch);parent=tmp_path/'trial';a=b.new_attempt(parent);(a/'partial').write_text('keep')
 assert b.completed(parent) is None
 second=b.new_attempt(parent);(second/'result.json').write_text('{}');b.seal(second,'synthetic_fixture')
 assert b.completed(parent)==second and (a/'partial').read_text()=='keep'

def test_tampered_completed_result_fails_closed(tmp_path,monkeypatch):
 sandbox(tmp_path,monkeypatch);parent=tmp_path/'trial';a=b.new_attempt(parent);(a/'r').write_text('original');b.seal(a,'fixture');(a/'r').write_text('tampered')
 with pytest.raises(ValueError,match='Completed artifact changed'):b.completed(parent)

def test_completion_cannot_be_overwritten(tmp_path,monkeypatch):
 sandbox(tmp_path,monkeypatch);a=b.new_attempt(tmp_path/'trial');b.seal(a,'fixture')
 with pytest.raises(ValueError,match='immutable'):b.seal(a,'fixture')

def test_process_lock_released_after_failure_and_prevents_concurrent_owner(tmp_path,monkeypatch):
 sandbox(tmp_path,monkeypatch)
 with b.exclusive('fixture'):
  with pytest.raises(OSError):
   with b.exclusive('fixture'):pass
 with pytest.raises(RuntimeError):
  with b.exclusive('fixture'):raise RuntimeError('simulated crash inside owner')
 with b.exclusive('fixture'):pass

def test_generality_only_replaces_adapter_initialization():
 from src.phase6.run_indicator_baseline import LocalAdapter
 assert b.BatchAdapter.prepare is LocalAdapter.prepare and b.BatchAdapter.finish is LocalAdapter.finish and b.BatchAdapter.close is LocalAdapter.close
