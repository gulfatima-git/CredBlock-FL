"""Read-only chronological audit. No model fitting, prediction, or label regeneration.

Run: python -B -m src.phase6.audit_splits --output reports/phase6/splits/v1
Existing outputs are refused. All read Phase 5 files are checked against freeze.
"""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
from itertools import combinations
import platform

from src.phase6.readiness import ROOT, REPLAY, FREEZE, load, sha
from src.phase6.temporal_protocol import require, validate_branch, scoring_times

PROTOCOL = 'configs/phase6/split_protocol_v1.json'


def save(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, default=str)
        stream.write('\n')


def input_view(db, name, files):
    """DuckDB CREATE VIEW cannot bind file-list parameters; relation API can."""
    db.read_parquet(files, filename=True).create_view(name)


def run(output):
    import duckdb
    import pandas as pd

    require(not output.exists(), 'Output already exists; choose a new version')
    output.mkdir(parents=True)
    protocol = load(ROOT / PROTOCOL)
    protocol_hash = sha(ROOT / PROTOCOL)
    require(sha(ROOT / protocol['data_contract']) == protocol['data_contract_sha256'], 'Accepted contract changed')
    require(sha(ROOT / FREEZE) == protocol['dataset_freeze_sha256'], 'Dataset freeze changed')
    accepted = load(ROOT / 'reports/phase5_final_acceptance_v2/summary.json')
    for name, digest in accepted['graph_code'].items():
        require(sha(ROOT / name) == digest, 'Accepted graph code changed: ' + name)
    freeze = {str((ROOT / f['path_relative_to_project']).resolve()): f for f in load(ROOT / FREEZE)['files']}
    tracked = {}

    def check(path):
        path = path.resolve()
        key = path.relative_to(ROOT).as_posix()
        if key in tracked:
            return
        digest = sha(path)
        entry = freeze.get(str(path))
        require(entry is not None and digest == entry['sha256'] and path.stat().st_size == entry['size_bytes'],
                'Frozen input changed or unpinned: ' + key)
        tracked[key] = digest

    # Save the policy hash before any TEST descriptive tables are queried.
    save(output / 'preregistration.json', {
        'version': protocol['version'], 'protocol_sha256': protocol_hash,
        'recorded_at_source_host': datetime.now().isoformat(),
        'event': 'Protocol bytes pinned before audit including TEST descriptive counts',
        'subphase0_acceptance': 'User explicitly accepted Subphase 0 and authorized Subphase 1',
        'test_predictions_or_model_selection': False,
        'git_commit': 'Pending protocol review; required before later final TEST evaluation'})
    root = ROOT / REPLAY
    branches = []
    for path in sorted(root.glob('CFV1*/replay_manifest.json')):
        check(path)
        m = load(path)
        source = ROOT / 'data2/phase5/controlled_inventory_causal_v1' / m['variant_id'] / 'manifest.json'
        check(source)
        require(sha(source) == m['source_inventory_manifest_sha256'], 'Generation manifest mismatch')
        generation = load(source)
        require((generation['split'], generation['seed'], generation['campaign_start'], generation['campaign_end']) ==
                (m['split'], m['seed'], m['anchor'], m['end_exclusive']), 'Generation/replay assignment mismatch')
        require(sorted(b['organization'] for b in m['branches']) == protocol['organizations'], 'Organization coverage mismatch')
        for b in m['branches']:
            org = b['organization']
            ref_path = root / b['history_reference']
            check(ref_path)
            ref = load(ref_path)
            require(ref['organization'] == org and ref['block'] == f"{m['split']}_SEED{m['seed']}", 'Wrong history branch')
            validate_branch(protocol, m['split'], datetime.fromisoformat(m['anchor']), datetime.fromisoformat(m['end_exclusive']),
                            datetime.fromisoformat(ref['history_start_inclusive']), datetime.fromisoformat(ref['history_end_exclusive']))
            item = dict(variant_id=m['variant_id'], organization=org, split=m['split'], seed=m['seed'],
                        family=generation['family'], RIP=generation['RIP_target'],
                        Sorg=generation['Sorg_target'], Raccount=generation['Raccount_target'],
                        anchor=datetime.fromisoformat(m['anchor']), end_exclusive=datetime.fromisoformat(m['end_exclusive']),
                        history_reference=ref_path.relative_to(ROOT).as_posix())
            for suffix in ('labels', 'observations', 'replay'):
                p = path.parent / f'{org}_{suffix}.parquet'
                check(p)
                require(tracked[p.relative_to(ROOT).as_posix()] == b[suffix + '_parquet_sha256'], 'Branch hash mismatch')
                item[suffix + '_path'] = p.resolve().as_posix()
            branches.append(item)
    require(len(branches) == 2565, 'Incomplete branch inventory')
    print('Manifest/hash checks complete: 513 instances, 2565 branches', flush=True)

    db = duckdb.connect(':memory:', config={'threads': 2})
    branch_frame = pd.DataFrame(branches)
    db.register('branch_frame', branch_frame)
    db.execute('CREATE TABLE branches AS SELECT * FROM branch_frame')
    for name, suffix in [('labels', 'labels'), ('observations', 'observations'), ('events', 'replay')]:
        files = [b[suffix + '_path'] for b in branches]
        # Explicit file allowlists prevent accidental inclusion of old pilots.
        input_view(db, name, files)
    def zero(sql, message):
        n = db.execute(sql).fetchone()[0]
        require(n == 0, message + ': ' + str(n))

    zero('''SELECT count(*) FROM labels l LEFT JOIN branches b ON l.filename=b.labels_path
        WHERE b.variant_id IS NULL OR l.organization IS DISTINCT FROM b.organization
        OR l.variant_id IS DISTINCT FROM b.variant_id OR l.split IS DISTINCT FROM b.split
        OR l.label_time IS NULL OR l.label_time < b.anchor OR l.label_time >= b.end_exclusive
        OR l.node_label IS NULL OR l.node_label NOT IN (-1,0,1)
        OR l.supervision_eligible IS DISTINCT FROM (l.node_label != -1)
        OR l."User ID" IS NULL''', 'Label identity/time/mask failure')
    zero('''SELECT count(*) FROM (SELECT filename,"User ID",label_time FROM labels
        GROUP BY ALL HAVING count(*) != 1)''', 'Duplicate User/time labels')
    zero('''SELECT count(*) FROM labels WHERE
        (node_label=1 AND (latest_positive_evidence IS NULL OR positive_expires_at IS NULL
        OR latest_positive_evidence > label_time
        OR latest_positive_evidence <= label_time-INTERVAL '10 minutes'
        OR positive_expires_at != latest_positive_evidence+INTERVAL '10 minutes'
        OR label_time >= positive_expires_at OR recent_synthetic_count <= 0
        OR reason != 'synthetic_targeting'))
        OR (node_label != 1 AND (latest_positive_evidence IS NOT NULL OR positive_expires_at IS NOT NULL
        OR recent_synthetic_count != 0))
        OR (node_label=0 AND (recent_event_count <= 0 OR recent_ambiguous_count != 0 OR reason != 'clean_negative_candidate'))
        OR (node_label=-1 AND reason NOT IN ('ambiguous_source','no_recent_evidence_context_only'))''',
        'Label future/onset/expiry/policy failure')
    zero('''SELECT count(*) FROM observations o JOIN branches b ON o.filename=b.observations_path
        WHERE o.organization IS DISTINCT FROM b.organization OR o."Login Timestamp" IS NULL
        OR o."Login Timestamp" < b.anchor OR o."Login Timestamp" >= b.end_exclusive''', 'Observation cutoff failure')
    zero('''SELECT count(*) FROM events e JOIN branches b ON e.filename=b.replay_path
        WHERE e.organization IS DISTINCT FROM b.organization OR e."Login Timestamp" IS NULL
        OR e."Login Timestamp" < b.anchor OR e."Login Timestamp" >= b.end_exclusive''', 'Evaluator event cutoff failure')
    print('All stored label and event cutoff/as-of checks passed', flush=True)

    # Audit only synthetic infrastructure; never match organization-local User IDs.
    ips = db.execute('''SELECT DISTINCT b.split,e."IP Address" FROM events e
        JOIN branches b ON e.filename=b.replay_path WHERE e.is_synthetic''').fetchall()
    sets = {s: {ip for split, ip in ips if split == s} for s in protocol['splits_half_open']}
    intersections = {f'{a}__{b}': len(sets[a] & sets[b]) for a, b in combinations(sets, 2)}
    require(all(n == 0 for n in intersections.values()), 'Cross-split synthetic attacker-IP overlap')
    save(output / 'infrastructure_intersections.json', dict(synthetic_ip_counts={s: len(v) for s,v in sets.items()},
        cross_split_intersection_counts=intersections, raw_ip_values_exported=False,
        scope='Evaluator-only split audit; background IP overlap is allowed; no User or credential alignment'))

    # Historical raw context is loaded once per frozen reference, not per variant.
    history_rows = []
    db.execute('CREATE TABLE context_users(organization VARCHAR,split VARCHAR,block VARCHAR,uid BIGINT,last_ts TIMESTAMP)')
    for ref_name in sorted({b['history_reference'] for b in branches}):
        ref = load(ROOT / ref_name)
        files = [(ROOT / f).resolve() for f in ref['source_files_relative_to_root']]
        for f in files:
            check(f)
        lo = datetime.fromisoformat(ref['history_start_inclusive'])
        hi = datetime.fromisoformat(ref['history_end_exclusive'])
        stats = db.execute('''SELECT min(CAST("Login Timestamp" AS TIMESTAMP)), max(CAST("Login Timestamp" AS TIMESTAMP)),
            count(*) FILTER (WHERE CAST("Login Timestamp" AS TIMESTAMP)>=? AND CAST("Login Timestamp" AS TIMESTAMP)<?)
            FROM read_parquet(?)''', [lo, hi, [f.as_posix() for f in files]]).fetchone()
        require(stats[0] <= lo and stats[1] >= hi and stats[2] == ref['history_event_count'], 'History coverage/count mismatch')
        split = ref['block'].split('_')[0]
        db.execute('''INSERT INTO context_users SELECT ?,?,?,CAST("User ID" AS BIGINT),max(CAST("Login Timestamp" AS TIMESTAMP))
            FROM read_parquet(?) WHERE CAST("Login Timestamp" AS TIMESTAMP)>? AND CAST("Login Timestamp" AS TIMESTAMP)<?
            GROUP BY "User ID"''', [ref['organization'], split, ref['block'], [f.as_posix() for f in files], lo, hi])
        history_rows.append(dict(reference=ref_name, organization=ref['organization'], split=split, block=ref['block'],
                                 history_start=lo, history_end=hi, history_event_count=stats[2], status='PASS'))
    save(output / 'warmup_coverage.json', history_rows)
    print('45 seven-day warm-up source views verified', flush=True)

    grid_path = root / 'grid_snapshots.csv'
    check(grid_path)
    grids = pd.read_csv(grid_path, parse_dates=['label_time'])
    db.register('grid_frame', grids)
    db.execute('CREATE TABLE grid AS SELECT * FROM grid_frame')
    zero('''SELECT count(*) FROM grid g LEFT JOIN branches b USING(variant_id,organization)
        WHERE b.variant_id IS NULL OR g.split != b.split OR g.seed != b.seed
        OR g.label_time < b.anchor OR g.label_time >= b.end_exclusive
        OR date_diff('second',b.anchor,g.label_time) NOT IN (0,600,1200,1800,2400,3000)
        OR g.graph_user_nodes_asof != g.recent_active_users+g.older_context_only_users
        OR g.recent_active_users != g.positive_users+g.negative_candidate_users+g.ambiguous_users''', 'Invalid grid partition')
    zero('''SELECT count(*) FROM (SELECT b.variant_id,b.organization,count(g.label_time) n,count(DISTINCT g.label_time) d
        FROM branches b LEFT JOIN grid g USING(variant_id,organization) GROUP BY ALL HAVING n!=6 OR d!=6)''', 'Grid coverage mismatch')
    db.execute('''CREATE TABLE label_grid AS SELECT b.variant_id,b.organization,l.label_time,
        count(*) FILTER(WHERE l.node_label=1) positives,
        count(*) FILTER(WHERE l.node_label=0) negatives,
        count(*) FILTER(WHERE l.reason='ambiguous_source') ambiguous
        FROM labels l JOIN branches b ON l.filename=b.labels_path
        WHERE contains(l.query_kind,'grid_snapshot') GROUP BY ALL''')
    zero('''SELECT count(*) FROM grid g FULL OUTER JOIN label_grid l USING(variant_id,organization,label_time)
        WHERE g.variant_id IS NULL OR l.variant_id IS NULL OR g.positive_users!=l.positives
        OR g.negative_candidate_users!=l.negatives OR g.ambiguous_users!=l.ambiguous''', 'Grid labels differ from frozen census')
    # Count organization-local identities only; branch copies are deliberately not independent users.
    users = db.execute('''WITH u AS (
        SELECT organization,split,uid FROM context_users
        UNION SELECT b.organization,b.split,o."User ID" FROM observations o
        JOIN branches b ON o.filename=b.observations_path
        WHERE o."Login Timestamp" <= b.anchor+INTERVAL '50 minutes')
        SELECT organization,split,count(DISTINCT uid) distinct_graph_users_across_grids FROM u GROUP BY ALL''').fetchdf()
    primary = db.execute('''SELECT organization,split,count(DISTINCT variant_id) campaign_instances,
        count(DISTINCT seed) campaign_seeds,count(*) grid_snapshots,
        min(graph_user_nodes_asof) min_graph_user_nodes,max(graph_user_nodes_asof) max_graph_user_nodes,
        sum(graph_user_nodes_asof) user_time_exposures,sum(positive_users) positive_user_times,
        sum(negative_candidate_users) clean_negative_user_times,sum(ambiguous_users) ambiguous_user_times,
        sum(older_context_only_users) context_only_user_times
        FROM grid GROUP BY ALL ORDER BY split,organization''').fetchdf().merge(users, on=['organization','split'])
    primary['eligible_user_times'] = primary.positive_user_times + primary.clean_negative_user_times
    primary['masked_user_times'] = primary.ambiguous_user_times + primary.context_only_user_times
    primary['positive_prevalence_eligible'] = primary.positive_user_times / primary.eligible_user_times
    primary['clean_negative_prevalence_eligible'] = primary.clean_negative_user_times / primary.eligible_user_times
    primary['negative_to_positive_ratio'] = primary.clean_negative_user_times / primary.positive_user_times
    primary['fpr_resolution'] = 1 / primary.clean_negative_user_times
    require((primary.campaign_instances == 171).all() and (primary.campaign_seeds == 3).all(), 'Missing organization split/seed coverage')
    primary.to_csv(output / 'per_organization_prevalence.csv', index=False)
    sparse = db.execute('''SELECT b.organization,b.split,count(*) sparse_label_states,
        count(*) FILTER(WHERE l.node_label=1) positive_states,count(*) FILTER(WHERE l.node_label=0) negative_states,
        count(*) FILTER(WHERE l.node_label=-1) masked_states,
        count(*) FILTER(WHERE l.reason='ambiguous_source') ambiguous_states,
        count(*) FILTER(WHERE l.reason='no_recent_evidence_context_only') context_transition_states
        FROM labels l JOIN branches b ON l.filename=b.labels_path GROUP BY ALL ORDER BY b.split,b.organization''').fetchdf()
    sparse.to_csv(output / 'sparse_schedule_counts.csv', index=False)
    pooled = primary.groupby('split', sort=True)[['user_time_exposures','positive_user_times','clean_negative_user_times',
        'ambiguous_user_times','context_only_user_times','eligible_user_times','masked_user_times',
        'distinct_graph_users_across_grids']].sum()
    pooled['positive_prevalence_eligible'] = pooled.positive_user_times / pooled.eligible_user_times
    pooled['negative_to_positive_ratio'] = pooled.clean_negative_user_times / pooled.positive_user_times
    pooled.to_csv(output / 'pooled_prevalence.csv')
    # Persist assignments explicitly; input paths remain private project-local provenance.
    branch_frame.to_csv(output / 'frozen_branch_assignments.csv', index=False)
    require(sha(ROOT / PROTOCOL) == protocol_hash, 'Protocol changed during audit')
    for name, digest in tracked.items():
        require(sha(ROOT / name) == digest, 'Input changed during audit: ' + name)
    save(output / 'input_sha256.json', tracked)
    summary = dict(version='phase6-chronological-audit-v1', status='PASS_TECHNICAL_GATE_AWAITING_USER_ACCEPTANCE',
        protocol_sha256=protocol_hash, frozen_inputs_verified=len(tracked), instances=513, organization_branches=len(branches),
        grid_snapshots=len(grids), sparse_label_states=int(sparse.sparse_label_states.sum()), history_views=len(history_rows),
        synthetic_infrastructure_intersections=intersections, all_five_organizations_valid=True,
        primary_unit=protocol['scoring']['primary_unit'], fpr_target=protocol['fpr']['target'],
        test_policy='Integrity/descriptive audits only; no predictions, fitting, tuning or selection',
        feature_asof_evidence='Accepted runtime code hash and Phase 5 representative SQL graph oracle reused; new temporal prefix tests exercise future exclusion. Not a full 2565-branch feature replay.',
        runtime_training_preprocessing_isolation='Policy guards tested; integration with future sampler/trainer remains Subphases 2/3',
        environment=dict(python=platform.python_version(), duckdb=duckdb.__version__),
        version_control='Protocol hash frozen for review; git commit required before later final TEST evaluation')
    save(output / 'summary.json', summary)
    files = {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()}
    save(output / 'output_sha256.json', files)
    db.close()
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve())
