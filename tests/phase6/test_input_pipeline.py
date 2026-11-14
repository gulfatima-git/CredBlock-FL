from datetime import datetime,timedelta
from pathlib import Path

import numpy as np
import pytest
import torch

from src.organization.rolling_graph_v1 import OrganizationGraphRuntime, OBSERVABLE
from src.phase6.input_pipeline import BranchPipeline, PinnedInputs, TemporalNeighborSampler
from src.phase6.readiness import load

ROOT=Path(__file__).resolve().parents[2]
PROTOCOL=load(ROOT/'configs/phase6/split_protocol_v1.json')
T=datetime(2020,3,1,13)


def observation(t,user,ip):
    return dict(zip(OBSERVABLE,['Org1',t,user,ip,False]))


def graph():
    runtime=OrganizationGraphRuntime('Org1')
    rows=[observation(T,1,f'192.0.2.{i}') for i in range(1,31)]
    rows += [observation(T,i+1,f'192.0.2.{i}') for i in range(1,31)]
    runtime.apply_timestamp_batch(T,rows,[str(i) for i in range(len(rows))])
    return runtime


def sampler(seed=1,fanouts=(3,4)):
    return TemporalNeighborSampler(graph().training_view(),'fixture','TRAIN',fanouts,seed)


def state(label=1,org='Org1',time=T,variant='fixture'):
    return dict(organization=org,variant_id=variant,split='TRAIN',**{'User ID':1},label_time=time,
                node_label=label,supervision_eligible=label!=-1,
                latest_positive_evidence=T if label==1 else None,
                positive_expires_at=T+timedelta(minutes=10) if label==1 else None)


def edges(batch):
    return [set((int(route.source_rows[a]),int(route.destination_rows[b]))
                for a,b in packet.edge_index.T.tolist()) for packet,route in zip(batch.packets,batch.routing)]


def test_layer_blocks_match_all_neighbors_without_truncation():
    s=sampler(fanouts=(100,100))
    b=s.sample([0])
    for packet,route in zip(b.packets,b.routing):
        assert set(packet.keys())=={'x','edge_index','num_nodes'}
        assert packet.x.dtype==torch.float32 and packet.edge_index.dtype==torch.int64
        assert np.array_equal(route.source_rows[:len(route.destination_rows)],route.destination_rows)
        for j,node in enumerate(route.destination_rows):
            found={int(route.source_rows[a]) for a,d in packet.edge_index.T.tolist() if d==j}
            expected=set(s.neighbors[s.indptr[node]:s.indptr[node+1]].tolist())
            assert found==expected
    assert np.array_equal(b.routing[0].destination_rows,b.routing[1].source_rows)
    assert b.root_rows.tolist()==[0]


def test_seed_reproducible_across_calls_and_instances():
    a=sampler().sample([0,1])
    b=sampler().sample([0,1])
    assert edges(a)==edges(b)
    assert all(torch.equal(x.x,y.x) for x,y in zip(a.packets,b.packets))
    assert edges(sampler(seed=2).sample([0]))!=edges(sampler(seed=3).sample([0]))


def test_neighbor_choices_do_not_depend_on_root_batch_partition():
    s=sampler()
    alone=s.sample([0])
    together=s.sample([1,0])
    for layer,(a,b) in enumerate(zip(edges(alone),edges(together))):
        common=set(alone.routing[layer].destination_rows)&set(together.routing[layer].destination_rows)
        assert {e for e in a if e[1] in common}=={e for e in b if e[1] in common}


def test_labels_and_masks_cannot_influence_sampling_or_model_fields():
    s=sampler()
    positive=s.sample([0],[state()],PROTOCOL)
    negative=s.sample([0],[state(0)],PROTOCOL)
    masked=s.sample([0],[state(-1)],PROTOCOL)
    assert edges(positive)==edges(negative)==edges(masked)
    for p,n in zip(positive.packets,negative.packets):
        assert torch.equal(p.x,n.x)
    assert positive.supervision.y.tolist()==[1]
    assert negative.supervision.eligible_mask.tolist()==[True]
    assert masked.supervision.eligible_mask.tolist()==[False]


@pytest.mark.parametrize('roots', [[],[0,0],[99999],[-1],[31],[0.5],[True]])
def test_invalid_or_ip_targets_rejected(roots):
    with pytest.raises(ValueError):
        sampler().sample(roots)


@pytest.mark.parametrize('row', [state(org='Org2'),state(time=T+timedelta(seconds=1)),state(variant='another')])
def test_cross_scope_supervision_rejected(row):
    with pytest.raises(ValueError):
        sampler().sample([0],[row],PROTOCOL)


def test_inductive_new_user_and_ip_and_future_snapshot_isolation():
    runtime=graph()
    old=TemporalNeighborSampler(runtime.training_view(),'fixture','TRAIN',(3,4),1)
    before=edges(old.sample([0]))
    later=datetime(2020,10,1)
    runtime.apply_timestamp_batch(later,[observation(later,999,'unseen-ip')],['new-event'])
    new=TemporalNeighborSampler(runtime.training_view(),'fixture','VAL',(3,4),1)
    row=runtime.training_view().private_keys.index(('U',999))
    b=new.sample([row])
    assert b.packets[-1].num_nodes==2
    assert ('I','unseen-ip') in runtime.training_view().private_keys
    assert b.supervision.y.tolist()==[-1]
    assert before==edges(old.sample([0]))
    assert all(set(p.keys())=={'x','edge_index','num_nodes'} for p in b.packets)


def test_expired_edge_is_never_sampled():
    runtime=graph()
    runtime.advance(T+timedelta(days=7))
    t=T+timedelta(days=7,seconds=1)
    runtime.apply_timestamp_batch(t,[observation(t,999,'only-active-ip')],['new-event'])
    s=TemporalNeighborSampler(runtime.training_view(),'fixture','TRAIN',(3,4),1)
    b=s.sample([0])
    assert len(s.view.private_keys)==2
    assert edges(b)==[{(0,1),(1,0)},{(1,0)}]


def test_minibatches_cover_users_once_without_context_targets():
    s=sampler()
    batches=list(s.batches(batch_size=8))
    assert np.concatenate([b.root_rows for b in batches]).tolist()==s.user_rows.tolist()
    assert all(not b.supervision.eligible_mask.any() for b in batches)


def test_real_pipeline_grid_monotonicity_and_exact_supervision():
    pins=PinnedInputs(ROOT)
    with BranchPipeline(pins,'CFV1_SO_CS_027_SEED1001_TRAIN','Org1',purpose='fit') as pipeline:
        runtime_id=id(pipeline.runtime)
        s=pipeline.sampler(pipeline.grid[0])
        states=pipeline.supervision_at(pipeline.grid[0])
        b=s.sample(s.user_rows[:32],states,pins.protocol)
        assert b.provenance['asof']==pipeline.grid[0].isoformat()
        assert id(pipeline.runtime)==runtime_id
        assert pipeline.runtime.training_view() is pipeline.runtime.detection_view()
        pipeline.snapshot(pipeline.grid[1])
        with pytest.raises(ValueError):
            pipeline.snapshot(pipeline.grid[0])
        with pytest.raises(ValueError):
            pipeline.snapshot(pipeline.anchor+timedelta(minutes=1))
    pins.verify_unchanged()


def test_real_test_branch_cannot_be_opened_for_fitting():
    pins=PinnedInputs(ROOT)
    with pytest.raises(ValueError,match='Split forbidden'):
        BranchPipeline(pins,'CFV1_SO_CS_027_SEED1001_TEST','Org1',purpose='fit')


def test_unlabeled_sampler_also_checks_split_time():
    with pytest.raises(ValueError,match='Snapshot outside chronological split'):
        TemporalNeighborSampler(graph().training_view(),'fixture','VAL')
