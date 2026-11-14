import json
import pytest

from src.phase6.finalize_local_training import run


def test_representative_results_cannot_create_full_acceptance_report(tmp_path):
    component=tmp_path/'representative'
    component.mkdir()
    (component/'summary.json').write_text(json.dumps(dict(mode='representative',organizations=['Org1'],
        status='PASS_REPRESENTATIVE_INTEGRATION_ONLY')),encoding='utf-8')
    plan=tmp_path/'plan.json'
    plan.write_text(json.dumps({'components':{f'Org{i}':str(component) for i in range(1,6)}}),encoding='utf-8')
    output=tmp_path/'full_acceptance'
    with pytest.raises(ValueError,match='not a completed full local run'):
        run(output,plan)
    assert not output.exists()
