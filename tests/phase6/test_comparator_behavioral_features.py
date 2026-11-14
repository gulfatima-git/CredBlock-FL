"""Independent event-count oracle for the non-graph User feature interpretation."""
from datetime import datetime,timedelta
import numpy as np
import pytest
from src.organization.rolling_graph_v1 import OrganizationGraphRuntime,OBSERVABLE

def user_row(runtime):
    view=runtime.training_view()
    return view.x[view.private_keys.index(('U',1)),:7]

def build(add_other_users=False):
    t=datetime(2020,3,1,13)
    runtime=OrganizationGraphRuntime('Org1')
    groups=[(t-timedelta(days=8),[(1,'expired',False)]),
            (t-timedelta(hours=1),[(1,'a',True)]),
            (t-timedelta(minutes=5),[(1,'a',False),(1,'b',False)]),
            (t,[(1,'c',False)]+([(2,'a',False),(3,'a',False),(4,'c',True)] if add_other_users else []))]
    for j,(clock,events) in enumerate(groups):
        rows=[dict(zip(OBSERVABLE,['Org1',clock,u,ip,success])) for u,ip,success in events]
        runtime.apply_timestamp_batch(clock,rows,[f'{j}-{i}' for i in range(len(rows))])
    return runtime

def test_root_features_equal_user_own_observed_event_counts():
    # Expired event is absent. Seven-day totals=4, success=1, failure=3;
    # own distinct IPs=3; ten-minute attempts=3, distinct IPs=3.
    expected=np.array([np.log1p(4),np.log1p(1),np.log1p(3),3/4,np.log1p(3),np.log1p(3),np.log1p(3)],dtype=np.float32)
    np.testing.assert_allclose(user_row(build()),expected,rtol=1e-6,atol=1e-7)

def test_other_users_sharing_ips_do_not_change_tabular_user_features():
    np.testing.assert_array_equal(user_row(build()),user_row(build(True)))
