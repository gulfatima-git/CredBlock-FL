"""CredBlock-FL Phase 5: READ-ONLY controlled comparison planning audit.

From the CredBlock-FL project root, after the background feasibility V2 audit:
    python plan_phase5_controlled_comparisons.py

Requires: duckdb (pip install duckdb). Reads existing campaign manifests and
background reports, and local organization Parquet for source-flag counts.
Writes ONLY reports/phase5_controlled_comparison_*_v1.{json,csv,txt}.
No attack generation, replay, source-data editing, or architecture changes.

Key limitations: Planning is NOT proof of exact background identity, matching,
label validity, correct temporal replay, privacy, or Phase 5 acceptance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path

try:
    import duckdb
except ImportError:
    raise SystemExit("Missing dependency: pip install duckdb")

SPLITS = {
    'TRAIN': (datetime(2020, 2, 3), datetime(2020, 10, 1)),
    'VAL': (datetime(2020, 10, 1), datetime(2020, 12, 1)),
    'TEST': (datetime(2020, 12, 1), datetime(2021, 3, 1)),
}
ORGS = [f'Org{i}' for i in range(1, 6)]
LEVELS = (0.2, 0.5, 0.8)
MAX_PER_USER = 3
MIN_PER_USER = 1
CRED_IDENTITIES = 100
OUTPUT_BASE = 'phase5_controlled_comparison'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def fingerprint(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def dt(value):
    return datetime.fromisoformat(str(value))


def date_text(value):
    return value.isoformat(timespec='seconds')


def as_bool(value):
    return str(value).strip().lower() == 'true'


def write_csv(path, rows, fieldnames=None):
    columns = fieldnames or list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True)
                             if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})


def load_campaigns(root):
    directory = root / 'data' / 'phase5' / 'synthetic_events'
    if not directory.is_dir():
        raise FileNotFoundError(f'Expected campaign directory: {directory}')
    items, errors = {}, []
    for folder in sorted(directory.iterdir()):
        if not folder.is_dir() or not folder.name.endswith(('_TRAIN', '_VAL', '_TEST')):
            continue
        try:
            source = folder / 'manifest.json'
            manifest = read_json(source)
            cid = manifest['campaign_id']
            split = str(manifest['split']).upper()
            if cid != folder.name or split not in SPLITS or not cid.endswith('_' + split):
                raise ValueError('Campaign ID, folder, or split mismatch')
            start = dt(manifest['campaign_start'])
            end = dt(manifest['campaign_end'])
            if not start < end:
                raise ValueError('Invalid campaign window')
            organizations = sorted(set(manifest['targeted_organizations']))
            if not organizations or any(x not in ORGS for x in organizations):
                raise ValueError('Invalid targeted organizations')
            if len(organizations) != int(manifest['Sorg_target']):
                raise ValueError('Sorg disagrees with target organization list')
            if cid in items:
                raise ValueError('Duplicate campaign ID')
            per_org = {o: int(manifest['events_per_organization'][o]) for o in organizations}
            if sum(per_org.values()) != int(manifest['total_events']):
                raise ValueError('Total attempts disagree with per-org attempts')
            if not list(folder.glob('*.parquet')):
                raise ValueError('No synthetic Parquet present')
            items[cid] = dict(
                id=cid, scenario=manifest['scenario_id'], split=split,
                seed=int(manifest['seed']), sorg=len(organizations),
                rip=float(manifest['RIP_target']),
                raccount=(None if manifest.get('Raccount_target') is None
                          else float(manifest['Raccount_target'])),
                start=start, end=end, organizations=organizations,
                per_org=per_org, total=sum(per_org.values()),
                manifest_sha256=fingerprint(source),
                min_attempts=int(manifest.get('min_attempts_per_account', MIN_PER_USER)),
                max_attempts=int(manifest.get('max_attempts_per_account', MAX_PER_USER)),
                credential_identities=int(manifest.get('credential_identities', CRED_IDENTITIES)),
            )
        except Exception as exc:
            errors.append({'folder': folder.name, 'error': f'{type(exc).__name__}: {exc}'})
    return items, errors


def find_report(root, base):
    path = root / 'reports' / base
    if not path.exists():
        raise FileNotFoundError(f'Missing required V2 report: {path}\nRun python audit_phase5_background_windows_v2.py first.')
    return path


def load_windows(root):
    path = find_report(root, 'phase5_background_windows.csv')
    windows = {}
    with path.open('r', newline='', encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            key = (row['campaign_id'], row['organization'])
            if key in windows:
                raise ValueError(f'Duplicate background-window row: {key}')
            windows[key] = dict(
                status=row['status'], split=row['split'].upper(),
                start=dt(row['start']), end=dt(row['end']),
                background=int(row['background_events']) if row['background_events'] else None,
                history=int(row['history_7day_events']) if row['history_7day_events'] else None,
                active_hours=int(row['history_7day_active_hours']) if row['history_7day_active_hours'] else None,
                history_168=as_bool(row['history_7day_hours_with_activity']),
                split_valid=as_bool(row['split_window_valid']),
                targeted_users=int(row['targeted_users']) if row['targeted_users'] else None,
                target_history_active_fraction=float(row['target_history_active_fraction'])
                    if row['target_history_active_fraction'] else None,
                background_success_rate=float(row['background_success_rate'])
                    if row['background_success_rate'] else None,
                attack=int(row['attack_events']) if row['attack_events'] else None,
            )
    return windows, fingerprint(path)


def load_comparison_report(root):
    path = find_report(root, 'phase5_background_comparisons.csv')
    pairs = {}
    with path.open('r', newline='', encoding='utf-8-sig') as stream:
        for r in csv.DictReader(stream):
            key = frozenset((r['campaign_a'], r['campaign_b']))
            if key in pairs:
                raise ValueError('Duplicate comparison pair in background report')
            pairs[key] = dict(status=r['background_status'], factor=r['factor_changed'],
                              volume_gap=float(r['max_background_volume_relative_gap'])
                                  if r['max_background_volume_relative_gap'] else None)
    return pairs, fingerprint(path)


def dimension(c):
    return (c['split'], c['seed'], c['sorg'])


def factor_pairs(campaigns):
    groups = defaultdict(list)
    for c in campaigns.values():
        groups[dimension(c)].append(c)
    for group in groups.values():
        for a, b in combinations(sorted(group, key=lambda c: c['id']), 2):
            varying_rip = not math.isclose(a['rip'], b['rip'])
            varying_raccount = a['raccount'] != b['raccount']
            if varying_rip == varying_raccount:
                continue
            yield a, b, ('RIP' if varying_rip else 'Raccount')


def cohort_counts(sorg, reuse):
    """Match the uploaded generator's calculate_local_target_counts logic.

    Org ordering is the generator's original selection order; for planning
    feasibility only we require per-org range/summary, not index-specific IDs.
    """
    if sorg == 1:
        return [CRED_IDENTITIES]
    reused = round(CRED_IDENTITIES * reuse)
    distinct_local = CRED_IDENTITIES - reused
    base, rem = divmod(distinct_local, sorg)
    return [reused + base + (1 if i < rem else 0) for i in range(sorg)]


def budget_feasibility(sorg):
    """Integers N attempts with N_i in [n_i, 3*n_i] for every local mapping.

    Fixed total AND per-position-organization budgets are feasible if the
    per-position integer intervals intersect across all three reuse levels.
    This is necessary/sufficient for attempt counts, not equal user cohorts.
    """
    if sorg == 1:
        return None
    targets = {f'{r:.2f}': cohort_counts(sorg, r) for r in LEVELS}
    total_low = max(sum(v) for v in targets.values())
    total_high = min(sum(v) * MAX_PER_USER for v in targets.values())
    per_pos = []
    for i in range(sorg):
        floor = max(x[i] for x in targets.values())
        ceiling = min(x[i] * MAX_PER_USER for x in targets.values())
        per_pos.append({'organization_position': i + 1, 'minimum_budget': floor,
                        'maximum_budget': ceiling, 'feasible': floor <= ceiling})
    fixed_per_org_possible = all(x['feasible'] for x in per_pos)
    fixed_total_possible = total_low <= total_high
    combined_low = sum(x['minimum_budget'] for x in per_pos)
    combined_high = sum(x['maximum_budget'] for x in per_pos)
    return dict(
        sorg=sorg, per_org_target_counts_by_reuse=targets,
        fixed_total_attempts_interval=[total_low, total_high],
        fixed_total_feasible=fixed_total_possible,
        fixed_per_org_attempts_intervals=per_pos,
        fixed_total_and_per_org_feasible=fixed_per_org_possible,
        compatible_total_budget_interval=[combined_low, combined_high]
            if fixed_per_org_possible else None,
        illustrative_per_org_budget=[x['minimum_budget'] for x in per_pos]
            if fixed_per_org_possible else None,
        changing_target_cohorts_unresolved=True,
        caveat='Attempt-count feasibility only; not identical target cohorts, identical timing, or a causal isolated reuse effect.'
    )


def required_source_bounds(organization, relevant, windows):
    """Identify the earliest required 7-day timestamp and newest window end."""
    starts = [c['start'] - timedelta(days=7) for c in relevant]
    ends = [c['end'] for c in relevant]
    return min(starts), max(ends)


def inspect_background_flags(con, root, campaigns):
    """Aggregated source flags ONLY; never export raw User IDs or records."""
    result = []
    problems = []
    for org in ORGS:
        folder = root / 'data' / 'organizations' / f'organization={org}'
        files = sorted(str(x) for x in folder.rglob('*.parquet')) if folder.exists() else []
        if not files:
            problems.append(f'{org}: missing source Parquet files')
            continue
        try:
            schema = {name for name, *_ in con.execute('DESCRIBE SELECT * FROM read_parquet(?)', [files]).fetchall()}
            required = {'Login Timestamp', 'Is Attack IP', 'Is Account Takeover'}
            if not required.issubset(schema):
                problems.append(f'{org}: missing columns {sorted(required-schema)}')
                continue
            # Avoid coercing null flags to false; expose missingness separately.
            query = '''
              SELECT COUNT(*)::BIGINT AS n,
                     COUNT(*) FILTER (WHERE "Is Attack IP" IS TRUE)::BIGINT AS attack_ip,
                     COUNT(*) FILTER (WHERE "Is Account Takeover" IS TRUE)::BIGINT AS takeover,
                     COUNT(*) FILTER (WHERE "Is Attack IP" IS TRUE AND "Is Account Takeover" IS TRUE)::BIGINT AS both,
                     COUNT(*) FILTER (WHERE "Is Attack IP" IS TRUE OR "Is Account Takeover" IS TRUE)::BIGINT AS either,
                     COUNT(*) FILTER (WHERE "Is Attack IP" IS NULL)::BIGINT AS ip_null,
                     COUNT(*) FILTER (WHERE "Is Account Takeover" IS NULL)::BIGINT AS takeover_null,
                     MIN("Login Timestamp"), MAX("Login Timestamp")
              FROM read_parquet(?)
              WHERE "Login Timestamp" >= ? AND "Login Timestamp" < ?
            '''
            for split, (start, end) in SPLITS.items():
                r = con.execute(query, [files, start, end]).fetchone()
                n, attack_ip, takeover, both, either, ip_null, takeover_null, min_dt, max_dt = r
                result.append(dict(organization=org, split=split, events=n,
                    is_attack_ip_true=attack_ip, is_account_takeover_true=takeover,
                    either_flag_true=either, both_flags_true=both,
                    is_attack_ip_null=ip_null, is_account_takeover_null=takeover_null,
                    either_flag_fraction=(either/n if n else None),
                    min_timestamp=date_text(min_dt) if min_dt else None,
                    max_timestamp=date_text(max_dt) if max_dt else None,
                    warning='Source flags are NOT synthetic credential-stuffing ground truth'))
            full = con.execute('SELECT MIN("Login Timestamp"), MAX("Login Timestamp") FROM read_parquet(?)', [files]).fetchone()
            relevant = [c for c in campaigns.values() if org in c['organizations']]
            if relevant:
                min_needed, max_needed = required_source_bounds(org, relevant, None)
                result.append(dict(organization=org, split='SOURCE_COVERAGE', events=None,
                    min_timestamp=date_text(full[0]) if full[0] else None,
                    max_timestamp=date_text(full[1]) if full[1] else None,
                    earliest_7day_required=date_text(min_needed), latest_campaign_end=date_text(max_needed),
                    covers_earliest_history=(full[0] is not None and full[0] <= min_needed),
                    note='Source min/max bounding coverage is not proof of complete event coverage'))
        except Exception as exc:
            problems.append(f'{org}: {type(exc).__name__}: {exc}')
    return result, problems


def evaluate_anchor(c, windows, source_coverage):
    """An EXISTING campaign's background window can be an anchor candidate.

    We DO NOT call any anchor READY: exact source coverage, background replay,
    isolation and causal label eligibility need separate validation.
    """
    reasons, org_summary = [], {}
    if not (SPLITS[c['split']][0] <= c['start'] < c['end'] <= SPLITS[c['split']][1]):
        reasons.append('SPLIT_BOUNDARY_VIOLATION')
    for org in c['organizations']:
        w = windows.get((c['id'], org))
        if w is None:
            reasons.append('BACKGROUND_WINDOW_MISSING')
            continue
        if w['start'] != c['start'] or w['end'] != c['end']:
            reasons.append('BACKGROUND_WINDOW_TIMESTAMP_MISMATCH')
        if w['status'] != 'MEASURED' or not w['split_valid']:
            reasons.append('BACKGROUND_WINDOW_UNVERIFIED')
        if w['background'] is None or w['background'] <= 0:
            reasons.append('BACKGROUND_WINDOW_EMPTY')
        if w['active_hours'] is None:
            reasons.append('HISTORY_UNVERIFIED')
        if w['active_hours'] != 168:
            reasons.append('HISTORY_PARTIAL_HOURLY_ACTIVITY')
        coverage = source_coverage.get(org)
        if coverage and coverage['start'] is not None and coverage['start'] > c['start'] - timedelta(days=7):
            reasons.append('SOURCE_BEGINS_AFTER_REQUIRED_HISTORY')
        org_summary[org] = {'background_events': w['background'],
                            'history_active_hours': w['active_hours'],
                            'attack_events': c['per_org'][org],
                            'attack_background_ratio': (c['per_org'][org]/w['background'])
                                if w['background'] else None,
                            'target_history_active_fraction': w['target_history_active_fraction']}
    return dict(eligible_for_planning=not reasons, reason_codes=sorted(set(reasons)),
                organization_windows=org_summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(),
                        help='CredBlock-FL project root (default: current directory)')
    args = parser.parse_args()
    root = args.root.resolve()
    campaigns, loading_errors = load_campaigns(root)
    if loading_errors or len(campaigns) != 270:
        raise SystemExit(f'Campaigns loaded {len(campaigns)}/270; errors: {loading_errors[:5]}. '
                         'Original campaign files were NOT modified.')
    windows, windows_hash = load_windows(root)
    comparison_report, comparisons_hash = load_comparison_report(root)
    if len(windows) != 837 or len(comparison_report) != 513:
        raise SystemExit(f'Expected V2 reports (837 windows, 513 comparisons), got '
                         f'{len(windows)} and {len(comparison_report)}. Rerun background V2 audit.')
    # Check source artifact measured rows agree with loaded campaign manifests.
    for (cid, org), w in windows.items():
        c = campaigns.get(cid)
        if not c or org not in c['organizations']:
            raise SystemExit(f'Background audit contains unexpected key: {cid}/{org}')
        if w['attack'] != c['per_org'][org]:
            raise SystemExit(f'Synthetic attempts differ from prior audit: {cid}/{org}')
    con = duckdb.connect(':memory:')
    print('CRED BLOCK-FL PHASE 5 — CONTROLLED-COMPARISON PLANNER')
    print('Campaigns:', len(campaigns), '| Background windows:', len(windows))
    print('Analyzing original source flags (aggregate counts only) ...')
    flag_rows, source_errors = inspect_background_flags(con, root, campaigns)
    source_coverage = {}
    for r in flag_rows:
        if r['split'] == 'SOURCE_COVERAGE':
            source_coverage[r['organization']] = {
                'start': dt(r['min_timestamp']) if r.get('min_timestamp') else None,
                'end': dt(r['max_timestamp']) if r.get('max_timestamp') else None}
    feasibility = {str(s): budget_feasibility(s) for s in (2, 3, 5)}
    candidate_anchors = {cid: evaluate_anchor(c, windows, source_coverage)
                         for cid, c in campaigns.items()}
    rows, counts, issues = [], Counter(), Counter()
    for a, b, factor in factor_pairs(campaigns):
        report = comparison_report.get(frozenset((a['id'], b['id'])))
        reason = []
        if report is None or report['factor'] != factor:
            reason.append('BACKGROUND_PAIR_AUDIT_MISSING')
        if a['organizations'] != b['organizations']:
            reason.append('ORGANIZATION_MISMATCH')
        # The original generator offers exact synthetic attempt matching for RIP;
        # verify actual per-organization counts, not just their config values.
        synthetic_match = a['total'] == b['total'] and a['per_org'] == b['per_org']
        if factor == 'RIP' and not synthetic_match:
            reason.append('SYNTHETIC_ATTEMPT_MISMATCH')
        if factor == 'Raccount':
            reason.append('RACCOUNT_TARGET_COHORT_CHANGE_BY_DESIGN')
            if not feasibility[str(a['sorg'])]['fixed_total_and_per_org_feasible']:
                reason.append('NO_COMMON_PER_ORG_ATTEMPT_BUDGET')
        anchors = [c for c in (a, b) if candidate_anchors[c['id']]['eligible_for_planning']]
        if not anchors:
            reason.append('NO_EXISTING_ELIGIBLE_ANCHOR')
        anchor = min(anchors, key=lambda c: (c['start'], c['id'])) if anchors else None
        if anchor is not None and anchor['start'] != a['start'] and anchor['start'] != b['start']:
            raise AssertionError('Anchor must be an existing candidate')
        if anchor is not None and anchor['start'] != a['start']:
            reason.append('A_REQUIRES_TIMESTAMP_REBASING')
        if anchor is not None and anchor['start'] != b['start']:
            reason.append('B_REQUIRES_TIMESTAMP_REBASING')
        if factor == 'RIP':
            if anchor and synthetic_match and a['organizations'] == b['organizations']:
                status = 'INSUFFICIENT_EVIDENCE'  # no cohort/event equivalence verified here
                action = 'DERIVED_REPLAY_CANDIDATE_PENDING_EXACT_COHORT_AND_TIMING_AUDIT'
            else:
                status = 'INSUFFICIENT_EVIDENCE'
                action = 'REVIEW_RIP_MATCHING_AND_ANCHOR'
        else:
            status = 'NEEDS_CONTROLLED_VARIANT'
            action = ('DESIGN_FIXED_INTENSITY_VARIANTS_WITH_COHORT_CAVEAT'
                      if feasibility[str(a['sorg'])]['fixed_total_and_per_org_feasible']
                      else 'REVIEW_INFEASIBLE_FIXED_INTENSITY_AND_USE_SENSITIVITY_ANALYSIS')
        # Flags describe uncertainty, not positive credential-stuffing labels.
        if source_errors:
            reason.append('BACKGROUND_SOURCE_FLAG_PREVALENCE_PARTIALLY_UNVERIFIED')
        counts[(factor, status)] += 1
        for code in set(reason):
            if not code.endswith('REQUIRES_TIMESTAMP_REBASING'):
                issues[code] += 1
        row = dict(matched_group_id=f'{a["split"]}_S{a["sorg"]}_SEED{a["seed"]}_{factor}',
                   campaign_a=a['id'], campaign_b=b['id'], factor_changed=factor,
                   split=a['split'], seed=a['seed'], sorg=a['sorg'],
                   organizations=a['organizations'],
                   factor_a=a['rip'] if factor == 'RIP' else a['raccount'],
                   factor_b=b['rip'] if factor == 'RIP' else b['raccount'],
                   anchor_campaign=anchor['id'] if anchor else None,
                   anchor_start=date_text(anchor['start']) if anchor else None,
                   anchor_end=date_text(anchor['end']) if anchor else None,
                   shared_background_policy='ISOLATED_REPLAY_BRANCHES_NOT_MERGED',
                   history_start=date_text(anchor['start']-timedelta(days=7)) if anchor else None,
                   original_start_a=date_text(a['start']), original_start_b=date_text(b['start']),
                   attempt_total_a=a['total'], attempt_total_b=b['total'],
                   attempts_per_org_a=a['per_org'], attempts_per_org_b=b['per_org'],
                   synthetic_intensity_match=synthetic_match,
                   provisional_background_status=report['status'] if report else 'UNVERIFIED',
                   provisional_background_volume_gap=report['volume_gap'] if report else None,
                   raccount_attempt_budget_feasible=(None if factor == 'RIP' else
                       feasibility[str(a['sorg'])]['fixed_total_and_per_org_feasible']),
                   anchor_planning_evidence=(candidate_anchors[anchor['id']]['organization_windows']
                       if anchor else None),
                   source_manifest_sha256_a=a['manifest_sha256'],
                   source_manifest_sha256_b=b['manifest_sha256'],
                   status=status, next_action=action, reason_codes=sorted(set(reason)))
        rows.append(row)
    if len(rows) != 513:
        raise SystemExit(f'Expected 513 factor pairs, got {len(rows)}; stopping.')
    # Expose selected candidate anchor counts; DO NOT claim actual replay readiness.
    anchor_count = sum(x['eligible_for_planning'] for x in candidate_anchors.values())
    summary = dict(expected_campaigns=270, campaigns_loaded=len(campaigns),
        targeted_windows_loaded=len(windows), pair_candidates=len(rows),
        by_factor_status={f'{k[0]}:{k[1]}': v for k, v in sorted(counts.items())},
        reason_counts=dict(sorted(issues.items())),
        existing_campaign_anchor_candidates=anchor_count,
        early_or_partial_history_anchor_candidates=270-anchor_count,
        flag_rows_measured=sum(x['split'] in SPLITS for x in flag_rows),
        source_flag_errors=source_errors,
        budget_feasibility=feasibility,
        statuses_provisional_only=True,
        label_policy='Source flags are ambiguous-source metadata, NOT credential-stuffing target labels',
        cautions=[
          'Dry-run only: no campaign rewrites, new events, or replay branches created.',
          'Same source background is planned, NOT yet instantiated or independently replay validated.',
          'RIP pairs need explicit per-org cohort, timestamps and event equivalence checks.',
          'Raccount fixed attempt budgets do NOT fix changed target user populations.',
          'Active-hours=168 only shows at least one event per hour, not source-data completeness.',
          'Original Is Attack IP / Is Account Takeover flags are not credential-stuffing ground truth.',
          'Sorg evaluation needs an independent fixed-per-org policy and sensitivity analysis.',
          'Source min/max timestamps alone cannot prove full seven-day history coverage.',
          'Do not claim READY_FOR_DERIVED_REPLAY or Phase 5 completion from this report.'
        ])
    output = root / 'reports'
    output.mkdir(parents=True, exist_ok=True)
    json_file = output / f'{OUTPUT_BASE}_plan_v1.json'
    pairs_file = output / f'{OUTPUT_BASE}_pairs_v1.csv'
    flags_file = output / 'phase5_label_policy_impact_v1.csv'
    text_file = output / f'{OUTPUT_BASE}_feasibility_v1.txt'
    plan = dict(summary=summary,
                input_report_sha256={'background_windows_csv': windows_hash,
                                     'background_comparisons_csv': comparisons_hash},
                source_coverage={org: {'start': date_text(v['start']) if v['start'] else None,
                                       'end': date_text(v['end']) if v['end'] else None}
                                 for org, v in source_coverage.items()},
                anchor_candidates={cid: dict(eligible_for_planning=x['eligible_for_planning'],
                                             reason_codes=x['reason_codes'])
                                   for cid, x in sorted(candidate_anchors.items())},
                comparisons=rows, source_flag_statistics=flag_rows)
    json_file.write_text(json.dumps(plan, indent=2), encoding='utf-8')
    write_csv(pairs_file, rows)
    write_csv(flags_file, flag_rows)
    lines = [
        'CRED BLOCK-FL — PHASE 5 CONTROLLED-COMPARISON PLANNING AUDIT',
        '=' * 68,
        f'Campaigns loaded: {len(campaigns)}/270',
        f'Background windows: {len(windows)}/837',
        f'One-factor pairs: {len(rows)}',
        'Pair classifications: ' + str(summary['by_factor_status']),
        f'Existing background anchor candidates (provisional): {anchor_count}/270',
        'Background source flag measurement errors: ' + str(len(source_errors)),
        'Raccount budget feasibility (attempt counts, NOT cohort equality):',
    ]
    for sorg, f in feasibility.items():
        lines.append(f'  Sorg={sorg}: fixed total feasible={f["fixed_total_feasible"]}; '
                     f'fixed per-org feasible={f["fixed_total_and_per_org_feasible"]}; '
                     f'illustrative per-org budget={f["illustrative_per_org_budget"]}')
    lines.append('Open issues:')
    lines += [f'  - {k}: {v}' for k, v in sorted(issues.items())]
    lines += ['', 'Interpretation and cautions:'] + [f'  - {x}' for x in summary['cautions']]
    lines += ['', 'Reports:', str(json_file), str(pairs_file), str(flags_file), str(text_file)]
    text_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
