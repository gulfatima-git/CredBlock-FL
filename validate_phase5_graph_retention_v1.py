#!/usr/bin/env python3
"""Test and integrate the versioned rolling graph using frozen Phase 5 data.

No campaign/label regeneration, model training or modifications to old modules.
Representative protocol: Sorg-family Sorg5, RIP=.50, Raccount=.50 for every
split/seed, all five organizations (45 attack branches + 45 background controls).
Independent SQL checks every feature and edge at six grid times plus hour end.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import groupby
import argparse
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

CODE = Path(__file__).resolve().parent / 'src/organization/rolling_graph_v1.py'
spec = importlib.util.spec_from_file_location('credblock_rolling_graph_v1', CODE)
G = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = G
spec.loader.exec_module(G)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, default=str)
        f.write('\n')


def observation(org, time, user=1, ip='192.0.2.1', success=False):
    return dict(zip(G.OBSERVABLE, (org, time, user, ip, success)))


def feed(runtime, rows):
    for time, grouped in groupby(rows, key=lambda r: r['Login Timestamp']):
        batch = list(grouped)
        runtime.apply_timestamp_batch(time, [{c: r[c] for c in G.OBSERVABLE} for r in batch],
                                      [r['token'] for r in batch])


def sql_snapshot_check(db, graph, view):
    """Independent event-table oracle; does not reuse incremental counters."""
    import numpy as np
    t = view.asof
    def aggregate(window):
        return db.execute('''WITH a AS (SELECT * FROM oracle_events WHERE ts > ? AND ts <= ?)
            SELECT 'U' kind, CAST(uid AS VARCHAR) entity_key, COUNT(*) n,
                   SUM(CAST(success AS INTEGER)) successful, COUNT(DISTINCT ip) neighbors
            FROM a GROUP BY uid UNION ALL
            SELECT 'I',ip,COUNT(*),SUM(CAST(success AS INTEGER)),COUNT(DISTINCT uid)
            FROM a GROUP BY ip''', [t-window, t]).fetchall()
    retained = {(kind, int(key) if kind == 'U' else key): (n, successful, degree)
                for kind, key, n, successful, degree in aggregate(G.HISTORY)}
    recent = {(kind, int(key) if kind == 'U' else key): (n, successful, degree)
              for kind, key, n, successful, degree in aggregate(G.RECENT)}
    keys = tuple(sorted(retained, key=lambda k: (0 if k[0] == 'U' else 1, k[1])))
    G.require(keys == view.private_keys, 'As-of graph contains missing/future/orphan nodes')
    G.require(all(graph.retained.nodes[k]==[n,s] and graph.retained.degree[k]==d
                  for k,(n,s,d) in retained.items()), 'Retained raw counts differ from SQL')
    G.require(all(graph.recent.nodes[k]==[n,s] and graph.recent.degree[k]==d
                  for k,(n,s,d) in recent.items()), 'Recent raw counts differ from SQL')
    expected = []
    for key in keys:
        n, successful, degree = retained[key]
        rn, rs, rd = recent.get(key, (0, 0, 0))
        expected.append([math.log1p(n), math.log1p(successful), math.log1p(n-successful),
            (n-successful)/n, math.log1p(degree), math.log1p(rn), math.log1p(rd), 0 if key[0] == 'U' else 1])
    expected = np.asarray(expected, dtype=np.float32).reshape((-1, len(G.FEATURES)))
    G.require(np.allclose(expected, view.x, rtol=1e-6,atol=1e-7),
              'Observable feature differs from independent as-of SQL')
    edges = {(u, ip): n for u, ip, n in db.execute('''SELECT uid,ip,COUNT(*)
        FROM oracle_events WHERE ts > ? AND ts <= ? GROUP BY uid,ip''', [t-G.HISTORY, t]).fetchall()}
    G.require(edges == dict(graph.retained.edges), 'Retained structural edge/count mismatch')
    row_index = {k: i for i, k in enumerate(keys)}
    directed = {(row_index[('U', u)], row_index[('I', ip)]) for u, ip in edges}
    directed |= {(b, a) for a, b in directed.copy()}
    G.require(directed == set(map(tuple, view.edge_index.T.tolist())), 'PyG adjacency mismatch')
    G.require(len(view.edge_index.T) == 2*len(edges), 'Duplicate/missing directed edges')
    return len(keys), len(edges)


def labels_at(rows, time):
    latest = {}
    for row in rows:
        if row['label_time'] > time:
            break
        latest[row['User ID']] = dict(row, label_time=time)
    return list(latest.values())


def run(root, output, freeze_dir):
    import duckdb
    import numpy as np
    import pandas as pd
    import torch
    G.require(not output.exists(), 'Output exists; refusing overwrite')
    replay = root / 'data/phase5/controlled_replay_labels_all_orgs_causal_v1'
    summary = load(replay / 'summary.json')
    G.require(summary['status'] == 'PASS_FULL_CONTROLLED_REPLAY_AND_TEMPORAL_LABELS', 'Replay acceptance missing')
    G.require(summary['all_input_hashes_unchanged'] is True, 'Replay preservation gate failed')
    freeze = load(freeze_dir / 'dataset_freeze_manifest.json')
    G.require(freeze['status'] == 'DATASET_BYTES_FROZEN_GRAPH_INTEGRATION_OPEN', 'Expected conditional dataset freeze')
    frozen = {str(root / f['path_relative_to_project']): f['sha256'] for f in freeze['files']}
    tracked = {str(freeze_dir / 'dataset_freeze_manifest.json'): sha(freeze_dir / 'dataset_freeze_manifest.json')}
    for name in ['temporal_graph_builder.py', 'temporal_graph_updater.py', 'client.py']:
        p = root / 'src/organization' / name
        tracked[str(p)] = sha(p)
    manifests = [load(p) for p in replay.glob('CFV1*/replay_manifest.json')]
    # Chosen in advance, identically for all splits; no model or TEST-policy selection.
    chosen = []
    inv = Path(summary['inventory_input'])
    for m in manifests:
        original = load(inv / m['variant_id'] / 'manifest.json')
        if (original['family'] == 'Sorg_fixed_per_org_attempts' and original['Sorg_target'] == 5
                and original['RIP_target'] == .5 and original['Raccount_target'] == .5):
            chosen.append(m)
    G.require(len(chosen) == 9 and len({(m['split'],m['seed']) for m in chosen}) == 9, 'Representative protocol incomplete')
    output.mkdir(parents=True, exist_ok=False)
    db = duckdb.connect(':memory:')
    results, snapshots = [], []
    def check_input(path):
        path = path.resolve()
        actual = sha(path)
        G.require(frozen.get(str(path)) == actual, 'Frozen input changed: ' + str(path))
        tracked[str(path)] = actual
    try:
        for m in sorted(chosen, key=lambda m: (['TRAIN','VAL','TEST'].index(m['split']),m['seed'])):
            vid, anchor = m['variant_id'], datetime.fromisoformat(m['anchor'])
            end = datetime.fromisoformat(m['end_exclusive'])
            block = f"{m['split']}_SEED{m['seed']}"
            for org in [f'Org{i}' for i in range(1, 6)]:
                ref_path = replay / 'history_references' / block / (org + '.json')
                check_input(ref_path)
                ref = load(ref_path)
                sources = [root / f for f in ref['source_files_relative_to_root']]
                for f in sources:
                    if str(f.resolve()) not in tracked:
                        check_input(f)
                cols = {r[0] for r in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',
                                               [[str(f) for f in sources]]).fetchall()}
                success = 'LoginSuccessful' if 'LoginSuccessful' in cols else 'Login Successful'
                raw = db.execute(f'''SELECT CAST("Login Timestamp" AS TIMESTAMP), CAST("User ID" AS BIGINT),
                    CAST("IP Address" AS VARCHAR), CAST("{success}" AS BOOLEAN)
                    FROM read_parquet(?) WHERE "Login Timestamp" >= ? AND "Login Timestamp" < ?
                    ORDER BY 1,2,3,4''', [[str(f) for f in sources], anchor-G.HISTORY, anchor]).fetchall()
                G.require(len(raw) == ref['history_event_count'], 'Historical source view count changed')
                history = [dict(observation(org, t, uid, ip, success), token=f'H_{block}_{org}_{i}')
                           for i,(t,uid,ip,success) in enumerate(raw)]
                base = G.OrganizationGraphRuntime(org)
                feed(base, history)
                base.advance(anchor-timedelta(microseconds=1))
                replay_path = replay / vid / (org + '_replay.parquet')
                label_path = replay / vid / (org + '_labels.parquet')
                check_input(replay_path);check_input(label_path)
                cur = db.execute('''SELECT organization,"Login Timestamp","User ID","IP Address",LoginSuccessful,
                    replay_event_id,is_synthetic FROM read_parquet(?)
                    ORDER BY "Login Timestamp",replay_event_id''', [str(replay_path)])
                stream = [dict(zip(G.OBSERVABLE, r[:5]), token=r[5], synthetic=r[6]) for r in cur.fetchall()]
                G.require(all(anchor <= r['Login Timestamp'] < end for r in stream), 'Replay end is exclusive')
                cur = db.execute('''SELECT organization,"User ID",label_time,node_label FROM read_parquet(?)
                                  ORDER BY label_time,"User ID"''', [str(label_path)])
                labels = [dict(zip(['organization','User ID','label_time','node_label'],r)) for r in cur.fetchall()]
                oracle_frame = pd.DataFrame([(r['Login Timestamp'],r['User ID'],r['IP Address'],r['LoginSuccessful'])
                    for r in history+stream], columns=['ts','uid','ip','success'])
                db.register('oracle_frame', oracle_frame)
                db.execute('CREATE OR REPLACE TEMP TABLE oracle_events AS SELECT * FROM oracle_frame')
                db.unregister('oracle_frame')
                runtime = G.OrganizationGraphRuntime(org, base.graph.fork())
                batches = [(t,list(rows)) for t,rows in groupby(stream,key=lambda r:r['Login Timestamp'])]
                cursor = 0
                query_times = [anchor + k*G.RECENT for k in range(6)] + [end-timedelta(microseconds=1)]
                init_history_count = len(runtime.graph.history_events)
                for t in query_times:
                    while cursor < len(batches) and batches[cursor][0] <= t:
                        feed(runtime, batches[cursor][1]);cursor += 1
                    runtime.advance(t)
                    view = runtime.detection_view()
                    nnode,nedge = sql_snapshot_check(db, runtime.graph, view)
                    G.require(view.digest() == runtime.training_view().digest(), 'Trainer/detector do not share as-of state')
                    before = view.digest()
                    y, mask = view.supervision(labels_at(labels, t))
                    G.require(before == view.digest() == runtime.detection_view().digest(), 'Labels affected graph features')
                    G.require(all(y[i] == -1 for i,key in enumerate(view.private_keys) if key[0]=='I'), 'IP nodes received target supervision')
                    snapshots.append({'variant_id':vid,'organization':org,'split':m['split'],'seed':m['seed'],
                        'asof':t,'nodes':nnode,'structural_edges':nedge,'positive_users':int((y==1).sum()),
                        'eligible_negative_users':int((y==0).sum()),'supervised_users':int(mask.sum()),
                        'feature_sha256':before,'status':'PASS_SQL_FEATURE_EDGE_AND_LABEL_INTEGRATION'})
                    if t == anchor + 3*G.RECENT:
                        restarted = G.RollingGraph.from_checkpoint_bytes(runtime.graph.checkpoint_bytes())
                        G.require(restarted.view().digest() == view.digest(), 'Real-source checkpoint restart mismatch')
                        # Continue through the runtime with the restored persistent state.
                        runtime = G.OrganizationGraphRuntime(org, restarted)
                dropped = init_history_count + len(stream) - len(runtime.graph.history_events)
                G.require(dropped >= 0, 'Invalid retention accounting')
                # A pure-background control is derived from this same source hour.
                # No accepted file is edited or rewritten to create it.
                baseline = G.OrganizationGraphRuntime(org, base.graph.fork())
                feed(baseline, [r for r in stream if not r['synthetic']])
                baseline.advance(end-timedelta(microseconds=1))
                base_frame = pd.DataFrame([(r['Login Timestamp'],r['User ID'],r['IP Address'],r['LoginSuccessful'])
                    for r in history+[r for r in stream if not r['synthetic']]], columns=['ts','uid','ip','success'])
                db.register('oracle_frame',base_frame)
                db.execute('CREATE OR REPLACE TEMP TABLE oracle_events AS SELECT * FROM oracle_frame')
                db.unregister('oracle_frame')
                sql_snapshot_check(db,baseline.graph,baseline.detection_view())
                packet = runtime.detection_view().to_pyg()
                if m['split']=='TRAIN' and m['seed']==1001:
                    folder = output / 'representative_graphs' / org
                    folder.mkdir(parents=True)
                    torch.save(packet,folder/'graph.pt')
                    (folder/'checkpoint.json.gz').write_bytes(runtime.graph.checkpoint_bytes())
                    save(folder/'private_node_mapping.json',runtime.detection_view().private_keys)
                    # Supervision is explicitly separate from the model packet.
                    np.savez_compressed(folder/'supervision.npz',y=y,eligible_mask=mask)
                results.append({'variant_id':vid,'organization':org,'split':m['split'],'seed':m['seed'],
                    'history_events':len(history),'replay_events':len(stream),'expired_events_during_hour':dropped,
                    'final_nodes':len(runtime.graph.retained.nodes),'final_structural_edges':len(runtime.graph.retained.edges),
                    'feature_and_edge_oracle_snapshots':7,'checkpoint_resume':'PASS',
                    'background_control':'PASS','pyg_validation':'PASS','status':'PASS_GRAPH_INTEGRATION'})
                print(f'{block}/{org}: PASS (7 as-of checks; expired={dropped})',flush=True)
        G.require(len(results)==45 and len(snapshots)==315,'Incomplete representative validation')
        G.require(sum(r['expired_events_during_hour'] for r in results)>0,'No real retention boundary exercised')
        G.require(all(sha(Path(p))==h for p,h in tracked.items()),'An input or legacy source changed')
        pd.DataFrame(results).to_csv(output/'branches.csv',index=False)
        pd.DataFrame(snapshots).to_csv(output/'asof_feature_checks.csv',index=False)
        new_code={'src/organization/rolling_graph_v1.py':sha(CODE),
                  'validate_phase5_graph_retention_v1.py':sha(Path(__file__).resolve())}
        save(output/'graph_runtime_contract.json',{'version':G.VERSION,
            'active_entrypoint':'src.organization.rolling_graph_v1.OrganizationGraphRuntime',
            'legacy_modules_used':False,'history_interval':'(t-7 days,t]', 'recent_interval':'(t-10 minutes,t]',
            'features':list(G.FEATURES),'count_feature_scope':'retained seven-day history, not lifetime',
            'orphan_policy':'Remove inactive nodes and edges; dense tensor indices are per-view; private entity keys remain the identity',
            'dedup_policy':'Reject late batches and duplicate retained ingestion tokens; token memory expires with history',
            'preprocessing':'Fixed log1p for counts; no fitted statistics',
            'supervision':'Separate evaluator join; no labels/masks/metadata in model Data',
            'shared_state':'training_view and detection_view export the same persistent graph state',
            'checkpoint':'Hashed JSON/GZIP retained observable events and clock; no truth flags',
            'code_sha256':new_code})
        result={'version':'phase5-graph-retention-integration-v1','status':'PASS_PHASE5_GRAPH_RETENTION_REPRESENTATIVE_INTEGRATION',
            'phase5_data_preparation_complete':True,'phase5_graph_integration_gate_resolved':True,
            'ready_for_phase6_implementation':True,'graphsage_training_implemented':False,'training_performed':False,
            'unit_tests_passed':20,'representative_attack_branches':45,'pure_background_controls':45,
            'all_five_organizations_validated':True,'asof_feature_edge_label_checks':315,
            'legacy_sources_modified':False,'all_read_input_hashes_unchanged':True,
            'frozen_dataset_manifest_sha256':sha(freeze_dir/'dataset_freeze_manifest.json'),
            'read_input_sha256':tracked,'accepted_graph_code_sha256':new_code,
            'model_input_allowlist_verified_in_this_graph_adapter':True,
            'expired_events_exercised':sum(r['expired_events_during_hour'] for r in results),
            'scope':'45 fixed representative branches across every split/seed/org plus 45 background controls; not graph-feature replay of all 2565 branches',
            'next_step':'Phase 6 GraphSAGE implementation must use the new versioned runtime, not the legacy cumulative adapter',
            'limitations':['Existing frozen event/label data is unchanged.',
                'No model effectiveness, FL, DP, poisoning robustness or Fabric claim is made.',
                'Train-only fitted preprocessing and actual training/evaluation isolation remain model-pipeline gates.',
                'The new files must be copied into the project before that project can import the new runtime.']}
        save(output/'summary.json',result)
        save(output/'output_sha256.json',{str(f.relative_to(output)):sha(f) for f in sorted(output.rglob('*')) if f.is_file()})
        print('PASS_PHASE5_GRAPH_RETENTION_REPRESENTATIVE_INTEGRATION\n'+str(output))
    except Exception as e:
        save(output/'FAILED.json',{'status':'FAIL_INCOMPLETE_OUTPUT','error':str(e)})
        raise
    finally:
        db.close()


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.t=datetime(2020,3,1)
    def graph(self):
        return G.RollingGraph('Org1')
    def add(self,g,t,user=1,ip='192.0.2.1',success=False,token='1'):
        g.ingest_batch(t,[observation('Org1',t,user,ip,success)],[token])
    def test_exact_seven_day_expiry(self):
        g=self.graph();self.add(g,self.t);g.advance(self.t+G.HISTORY)
        self.assertFalse(g.retained.edges);self.assertFalse(g.retained.nodes)
    def test_repeated_edge_survives(self):
        g=self.graph();self.add(g,self.t);self.add(g,self.t+timedelta(days=1),token='2')
        g.advance(self.t+G.HISTORY);self.assertEqual(g.retained.edges[(1,'192.0.2.1')],1)
        g.advance(self.t+G.HISTORY+timedelta(days=1));self.assertFalse(g.retained.edges)
    def test_exact_recent_expiry(self):
        g=self.graph();self.add(g,self.t);g.advance(self.t+G.RECENT)
        self.assertFalse(g.recent.nodes);self.assertEqual(len(g.retained.edges),1)
    def test_idle_memory_bound(self):
        g=self.graph();self.add(g,self.t);g.advance(self.t+timedelta(days=8))
        self.assertFalse(g.history_events or g.recent_events or g.seen or g.retained.nodes or g.recent.nodes)
    def test_truth_columns_rejected(self):
        g=self.graph();r=observation('Org1',self.t);r['credential_stuffing_label']=1
        with self.assertRaises(ValueError):g.ingest_batch(self.t,[r],['x'])
        self.assertIsNone(g.clock)
    def test_org_scope(self):
        g=self.graph()
        with self.assertRaises(ValueError):g.ingest_batch(self.t,[observation('Org2',self.t)],['x'])
    def test_late_batch_rejected_without_mutation(self):
        g=self.graph();self.add(g,self.t);before=g.view().digest()
        with self.assertRaises(ValueError):self.add(g,self.t-timedelta(seconds=1),token='2')
        self.assertEqual(before,g.view().digest())
    def test_duplicate_rejected(self):
        g=self.graph();self.add(g,self.t);before=g.view().digest()
        with self.assertRaises(ValueError):self.add(g,self.t+timedelta(seconds=1),token='1')
        self.assertEqual(before,g.view().digest())
    def test_ties_order_invariant(self):
        rows=[observation('Org1',self.t,1),observation('Org1',self.t,2)]
        a=self.graph();b=self.graph();a.ingest_batch(self.t,rows,['a','b']);b.ingest_batch(self.t,rows[::-1],['b','a'])
        self.assertEqual(a.view().digest(),b.view().digest())
    def test_closed_time_rejected(self):
        g=self.graph();self.add(g,self.t)
        with self.assertRaises(ValueError):self.add(g,self.t,token='2')
    def test_training_detection_share_state(self):
        r=G.OrganizationGraphRuntime('Org1');self.add(r.graph,self.t)
        self.assertEqual(r.training_view().digest(),r.detection_view().digest())
        self.assertIs(r.graph,r.graph)
    def test_supervision_separate_and_ip_masked(self):
        import numpy as np
        g=self.graph();self.add(g,self.t);v=g.view();before=v.digest()
        y,mask=v.supervision([{'organization':'Org1','User ID':1,'label_time':self.t,'node_label':1}])
        self.assertTrue(np.array_equal(y,[1,-1]));self.assertEqual(before,v.digest())
    def test_supervision_time_scope(self):
        g=self.graph();self.add(g,self.t)
        with self.assertRaises(ValueError):g.view().supervision([{'organization':'Org1','User ID':1,'label_time':self.t+G.RECENT,'node_label':1}])
    def test_features_do_not_encode_numeric_ids(self):
        import numpy as np
        a=self.graph();b=self.graph();self.add(a,self.t,user=1);self.add(b,self.t,user=99999999)
        self.assertTrue(np.array_equal(a.view().x,b.view().x))
    def test_checkpoint_resume(self):
        a=self.graph();self.add(a,self.t);b=G.RollingGraph.from_checkpoint_bytes(a.checkpoint_bytes())
        self.assertEqual(a.view().digest(),b.view().digest())
        for g in [a,b]:self.add(g,self.t+G.RECENT,token='2')
        self.assertEqual(a.view().digest(),b.view().digest())
    def test_checkpoint_tampering(self):
        g=self.graph();self.add(g,self.t);p=json.loads(gzip.decompress(g.checkpoint_bytes()));p['payload']['events'][0][2]=2
        with self.assertRaises(ValueError):G.RollingGraph.from_checkpoint_bytes(gzip.compress(json.dumps(p).encode()))
    def test_fork_isolation(self):
        a=self.graph();self.add(a,self.t);b=a.fork();self.add(b,self.t+G.RECENT,user=2,token='2')
        self.assertEqual(len(a.retained.nodes),2);self.assertEqual(len(b.retained.nodes),3)
    def test_cannot_rewind(self):
        g=self.graph();self.add(g,self.t);g.advance(self.t+G.RECENT)
        with self.assertRaises(ValueError):g.advance(self.t)
    def test_feature_values(self):
        g=self.graph();self.add(g,self.t,success=True);self.add(g,self.t+timedelta(seconds=1),token='2')
        self.assertAlmostEqual(float(g.view().x[0,3]),.5)
        self.assertAlmostEqual(float(g.view().x[0,0]),math.log1p(2),places=6)
    def test_model_packet_allowlist(self):
        g=self.graph();self.add(g,self.t)
        self.assertEqual(set(g.view().to_pyg().keys()),{'x','edge_index','num_nodes'})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--output',type=Path)
    p.add_argument('--freeze-dir',type=Path)
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoreTests))
    G.require(result.wasSuccessful(),'Rolling graph unit tests failed')
    if not a.self_test:
        root=a.root.resolve()
        run(root,(a.output or root/'reports/phase5_graph_retention_v1').resolve(),
            (a.freeze_dir or root/'reports/phase5_dataset_freeze_v1').resolve())


if __name__=='__main__':
    try:main()
    except Exception as e:
        print('STOPPED: '+type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(1)
