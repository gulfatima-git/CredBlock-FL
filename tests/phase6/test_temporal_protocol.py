import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from build_phase5_temporal_user_labels_v1 import TemporalLabels
from src.organization.rolling_graph_v1 import OrganizationGraphRuntime, OBSERVABLE
from src.phase6.temporal_protocol import (
    require_checkpoint, require_use, scoring_times, validate_branch, validate_target,
)

PROTOCOL = json.loads((Path(__file__).resolve().parents[2] / 'configs/phase6/split_protocol_v1.json').read_text())
T = datetime(2020, 3, 1, 13)


def event(t, user=1, positive=False, org='Org1', token='1'):
    return dict(organization=org, **{'Login Timestamp': t, 'User ID': user, 'IP Address': '192.0.2.1'},
                LoginSuccessful=False, is_synthetic=positive, credential_stuffing_label=int(positive),
                source_is_attack_ip=None if positive else False,
                source_is_account_takeover=None if positive else False, replay_event_id=token)


@pytest.mark.parametrize('split,anchor', [('TRAIN',T),('VAL',datetime(2020,10,10)),('TEST',datetime(2020,12,12))])
def test_valid_chronological_hour_and_grid(split, anchor):
    validate_branch(PROTOCOL, split, anchor, anchor+timedelta(hours=1), anchor-timedelta(days=7), anchor)
    times = scoring_times(PROTOCOL, anchor)
    assert len(times) == 6 and times[0] == anchor and times[-1] == anchor+timedelta(minutes=50)


@pytest.mark.parametrize('split,anchor', [('TRAIN', datetime(2020,9,30,23,30)),
                                        ('VAL',datetime(2020,9,30)),('TEST',datetime(2021,3,1))])
def test_cross_split_or_exclusive_end_rejected(split, anchor):
    with pytest.raises(ValueError):
        validate_branch(PROTOCOL, split, anchor, anchor+timedelta(hours=1), anchor-timedelta(days=7), anchor)


def test_short_or_future_warmup_rejected():
    for start,end in [(T-timedelta(days=6),T), (T-timedelta(days=7), T+timedelta(seconds=1))]:
        with pytest.raises(ValueError):
            validate_branch(PROTOCOL, 'TRAIN', T, T+timedelta(hours=1), start, end)


@pytest.mark.parametrize('purpose', PROTOCOL['test_seal']['forbidden'])
def test_test_split_forbidden_for_all_selection_and_fit(purpose):
    with pytest.raises(ValueError):
        require_use(PROTOCOL, 'TEST', purpose)


@pytest.mark.parametrize('purpose', ['fit','preprocessing_fit'])
def test_val_cannot_fit_learned_state(purpose):
    with pytest.raises(ValueError):
        require_use(PROTOCOL, 'VAL', purpose)
    require_use(PROTOCOL, 'TRAIN', purpose)


@pytest.mark.parametrize('purpose', ['early_stopping','model_selection','comparator_selection','threshold_calibration'])
def test_selection_requires_validation(purpose):
    require_use(PROTOCOL, 'VAL', purpose)
    with pytest.raises(ValueError):
        require_use(PROTOCOL, 'TRAIN', purpose)


def test_unknown_purpose_and_final_test_evaluation_fail_closed():
    for purpose in ['anything', 'final_evaluation']:
        with pytest.raises(ValueError):
            require_use(PROTOCOL, 'TEST', purpose)


def test_positive_future_onset_and_exact_expiry():
    rows = [event(T-timedelta(minutes=1)), event(T+timedelta(minutes=2), positive=True, token='2')]
    engine = TemporalLabels(rows)
    assert engine.state('Org1',1,T)['node_label'] == 0
    assert engine.state('Org1',1,T+timedelta(minutes=2))['node_label'] == 1
    assert engine.state('Org1',1,T+timedelta(minutes=12))['node_label'] == -1
    assert engine.state('Org2',1,T+timedelta(minutes=2))['node_label'] == -1


def test_label_prefix_invariance_with_future_evidence():
    past = [event(T-timedelta(seconds=1)),event(T,positive=True,token='2')]
    full = TemporalLabels(past + [event(T+timedelta(microseconds=1),user=2,positive=True,token='3')])
    prefix = TemporalLabels(past)
    for uid in [1,2]:
        assert full.state('Org1',uid,T) == prefix.state('Org1',uid,T)


def test_target_exact_time_and_evidence_validation():
    row = TemporalLabels([event(T,positive=True)]).state('Org1',1,T)
    row['split'] = 'TRAIN'
    validate_target(PROTOCOL,row,'Org1','TRAIN',T)
    for changes in [dict(organization='Org2'),dict(label_time=T+timedelta(seconds=1)),
                    dict(latest_positive_evidence=T+timedelta(microseconds=1)),
                    dict(latest_positive_evidence=T-timedelta(minutes=10)),dict(split='VAL')]:
        with pytest.raises(ValueError):
            validate_target(PROTOCOL,dict(row,**changes),'Org1','TRAIN',T)


def test_future_graph_events_cannot_change_saved_asof_view():
    runtime = OrganizationGraphRuntime('Org1')
    first = event(T)
    runtime.apply_timestamp_batch(T,[{c:first[c] for c in OBSERVABLE}],['first'])
    snapshot = runtime.training_view()
    x,edges = snapshot.x.copy(),snapshot.edge_index.copy()
    future = event(T+timedelta(microseconds=1),user=2)
    runtime.apply_timestamp_batch(future['Login Timestamp'],[{c:future[c] for c in OBSERVABLE}],['future'])
    assert np.array_equal(snapshot.x,x) and np.array_equal(snapshot.edge_index,edges)
    assert len(runtime.detection_view().private_keys) > len(snapshot.private_keys)
    with pytest.raises(ValueError):
        runtime.advance(T)


def test_persistent_graph_exact_history_and_recent_boundaries():
    runtime = OrganizationGraphRuntime('Org1')
    row=event(T-timedelta(days=7))
    runtime.apply_timestamp_batch(row['Login Timestamp'],[{c:row[c] for c in OBSERVABLE}],['old'])
    runtime.advance(T)
    assert not runtime.training_view().private_keys
    recent=event(T+timedelta(seconds=1))
    runtime.apply_timestamp_batch(recent['Login Timestamp'],[{c:recent[c] for c in OBSERVABLE}],['new'])
    runtime.advance(T+timedelta(minutes=10,seconds=1))
    assert len(runtime.detection_view().private_keys) == 2
    assert not runtime.detection_view().x[:,5].any()


@pytest.mark.parametrize('org,clock,branch', [('Org2',T,'A'),('Org1',T+timedelta(seconds=1),'A'),('Org1',T,'B')])
def test_future_cross_org_or_cross_branch_checkpoint_rejected(org,clock,branch):
    with pytest.raises(ValueError):
        require_checkpoint('Org1',org,clock,T,'A',branch)


def test_matching_past_checkpoint_allowed():
    require_checkpoint('Org1','Org1',T-timedelta(seconds=1),T,'A','A')
