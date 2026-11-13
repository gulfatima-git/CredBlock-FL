"""CredBlock-FL Phase 5: read-only background-window feasibility audit.

From the CredBlock-FL repository root:
    python audit_phase5_background_windows.py

Requires: duckdb. Reads all 270 split campaign manifests, organization background
Parquet, and synthetic campaign Parquet. Never changes these inputs. Writes only
reports/phase5_background_*. No regeneration or architecture changes.

This is an AVAILABILITY / COMPARABILITY SCREEN, not proof of matched background,
valid replay, subthreshold detection, seven-day graph retention, or no leakage.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    import duckdb
except ImportError:
    raise SystemExit("DuckDB is required: pip install duckdb")

ORGS = [f"Org{i}" for i in range(1, 6)]
SPLITS = {
    "TRAIN": ("2020-02-03", "2020-10-01"),
    "VAL": ("2020-10-01", "2020-12-01"),
    "TEST": ("2020-12-01", "2021-03-01"),
}
PERIOD = timedelta(days=7)


def dt(x):
    return datetime.fromisoformat(str(x).replace("Z", "+00:00"))


def iso(x):
    return x.isoformat(timespec="seconds") if isinstance(x, datetime) else None


def qident(s):
    return '"' + str(s).replace('"', '""') + '"'


def safe_rate(a, b):
    return (a / b) if a is not None and b else None


def rel_gap(a, b):
    if a is None or b is None:
        return None
    den = max(abs(a), abs(b))
    return abs(a - b) / den if den else 0.0


def to_csv(path, records):
    if not records:
        path.write_text("No records\n", encoding="utf-8")
        return
    columns = list(dict.fromkeys(k for r in records for k in r))
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v
                             for k, v in rec.items()})


def locate_background(root, org):
    folder = root / "data" / "organizations" / f"organization={org}"
    if not folder.is_dir():
        return []
    return sorted(str(p) for p in folder.rglob("*.parquet") if p.is_file())


def load_campaigns(root, con):
    base = root / "data" / "phase5" / "synthetic_events"
    if not base.is_dir():
        raise RuntimeError(f"Campaign directory missing: {base}")
    campaigns, errors, cohorts = [], [], defaultdict(set)
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or not folder.name.endswith(("_TRAIN", "_VAL", "_TEST")):
            continue
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            cid = str(manifest["campaign_id"])
            if cid != folder.name:
                raise ValueError("Folder and manifest campaign IDs differ")
            split = str(manifest["split"]).upper()
            if split not in SPLITS or not cid.endswith("_" + split):
                raise ValueError("Split mismatch")
            start, end = dt(manifest["campaign_start"]), dt(manifest["campaign_end"])
            if end <= start:
                raise ValueError("Non-positive campaign duration")
            campaign = {
                "campaign_id": cid, "scenario_id": manifest["scenario_id"],
                "split": split, "seed": int(manifest["seed"]),
                "start": start, "end": end,
                "sorg": int(manifest["Sorg_target"]),
                "rip": float(manifest["RIP_target"]),
                "raccount": (None if manifest.get("Raccount_target") is None
                             else float(manifest["Raccount_target"])),
                "targeted_orgs": sorted(str(x) for x in manifest["targeted_organizations"]),
                "attack_total": int(manifest["total_events"]),
                "attack_per_org": {str(k): int(v) for k, v in
                                   manifest["events_per_organization"].items()},
            }
            files = sorted(str(p) for p in folder.glob("*.parquet"))
            if not files:
                raise ValueError("No synthetic Parquet files")
            targets = con.execute(
                'SELECT DISTINCT organization, CAST("User ID" AS VARCHAR) '
                'FROM read_parquet(?) WHERE "User ID" IS NOT NULL', [files]
            ).fetchall()
            for org, user in targets:
                cohorts[(cid, str(org))].add(str(user))
            campaigns.append(campaign)
        except Exception as exc:
            errors.append({"campaign": folder.name, "error": f"{type(exc).__name__}: {exc}"})
    return campaigns, errors, cohorts


def load_candidate_pairs(root, campaigns):
    """Rebuild one-factor pairs from manifests; independent of other audit CSV."""
    groups = defaultdict(list)
    for c in campaigns:
        groups[(c["split"], c["seed"], c["sorg"])].append(c)
    pairs = []
    from itertools import combinations
    for group in groups.values():
        for a, b in combinations(group, 2):
            changed_rip = a["rip"] != b["rip"]
            changed_reuse = a["raccount"] != b["raccount"]
            if changed_rip == changed_reuse:
                continue
            pairs.append((a, b, "RIP" if changed_rip else "Raccount"))
    return pairs


def compute_background_for_org(con, root, org, campaigns, cohorts, warnings):
    """One scan builds hourly aggregates; a second computes per-cohort history.

    Exactness: Campaign start/end must be hour aligned; nonaligned windows are
    marked UNVERIFIED rather than estimated from hourly buckets.
    """
    relevant = [c for c in campaigns if org in c["targeted_orgs"]]
    results = {}
    if not relevant:
        return results, {"organization": org, "status": "NOT_TARGETED"}
    files = locate_background(root, org)
    if not files:
        warnings.append(f"{org}: no background Parquet files located")
        return results, {"organization": org, "status": "MISSING_BACKGROUND_FILES"}

    try:
        columns = con.execute('DESCRIBE SELECT * FROM read_parquet(?)', [files]).fetchall()
        names = {r[0]: str(r[1]).upper() for r in columns}
    except Exception as exc:
        warnings.append(f"{org}: unable to read background Parquet schema: {exc}")
        return results, {"organization": org, "status": "SCHEMA_ERROR"}
    if "Login Timestamp" not in names or "User ID" not in names:
        warnings.append(f"{org}: required User ID / Login Timestamp missing: {list(names)}")
        return results, {"organization": org, "status": "SCHEMA_MISMATCH", "columns": list(names)}

    min_start = min(c["start"] for c in relevant) - PERIOD
    max_end = max(c["end"] for c in relevant)
    # The original organization data uses "Login Successful" (with a space),
    # whereas synthetic campaign events use "LoginSuccessful".
    outcome_column = next((x for x in ("Login Successful", "LoginSuccessful") if x in names), None)
    outcome_id = qident(outcome_column) if outcome_column else None
    success_expr = (f'SUM(CASE WHEN {outcome_id} IS TRUE THEN 1 ELSE 0 END)'
                    if outcome_column else 'NULL')
    fail_expr = (f'SUM(CASE WHEN {outcome_id} IS FALSE THEN 1 ELSE 0 END)'
                 if outcome_column else 'NULL')
    # Exact hour count for hour-aligned windows, after one scan per org.
    hourly = con.execute(f'''
        SELECT DATE_TRUNC('hour', "Login Timestamp") AS hr,
               COUNT(*)::BIGINT AS events,
               {success_expr} AS successes,
               {fail_expr} AS failures
        FROM read_parquet(?)
        WHERE "Login Timestamp" >= ? AND "Login Timestamp" < ?
        GROUP BY 1 ORDER BY 1
    ''', [files, min_start, max_end]).fetchall()
    hours = [r[0] for r in hourly]
    events = [int(r[1]) for r in hourly]
    successes = [int(r[2]) if r[2] is not None else None for r in hourly]
    failures = [int(r[3]) if r[3] is not None else None for r in hourly]
    total_prefix, success_prefix, fail_prefix = [0], [0], [0]
    for n, s, f in zip(events, successes, failures):
        total_prefix.append(total_prefix[-1] + n)
        success_prefix.append(success_prefix[-1] + (s or 0))
        fail_prefix.append(fail_prefix[-1] + (f or 0))

    def sum_interval(prefix, low, high):
        x = bisect.bisect_left(hours, low)
        y = bisect.bisect_left(hours, high)
        return prefix[y] - prefix[x], y - x

    # Cohort user background history: aggregate only selected users, using
    # one source Parquet scan per org and one equijoin to target identities.
    # This measures historical activity, not an exact equality of cohort histories.
    cohort_rows = []
    windows_rows = []
    for c in relevant:
        cid = c["campaign_id"]
        for uid in cohorts[(cid, org)]:
            cohort_rows.append((cid, uid))
        windows_rows.append((cid, c["start"] - PERIOD, c["start"], c["end"]))
    cohort_summary = {}
    cohort_query_ok = False
    try:
        con.execute('CREATE OR REPLACE TEMP TABLE _cohort (campaign_id VARCHAR, uid VARCHAR)')
        con.executemany('INSERT INTO _cohort VALUES (?, ?)', cohort_rows)
        con.execute('CREATE OR REPLACE TEMP TABLE _win (campaign_id VARCHAR, hist_start TIMESTAMP, started TIMESTAMP, ended TIMESTAMP)')
        con.executemany('INSERT INTO _win VALUES (?, ?, ?, ?)', windows_rows)
        # Intersect once with all selected user IDs; limit source range to windows.
        # DISTINCT campaign-user rows prevent accidental duplicate inflation.
        con.execute('''CREATE OR REPLACE TEMP VIEW _unique_target AS
                       SELECT DISTINCT campaign_id, uid FROM _cohort''')
        summary_rows = con.execute('''
            SELECT t.campaign_id,
                   COUNT(*) FILTER (WHERE b."Login Timestamp" >= w.hist_start
                                         AND b."Login Timestamp" < w.started) AS history_events,
                   COUNT(DISTINCT t.uid) FILTER (WHERE b."Login Timestamp" >= w.hist_start
                                                      AND b."Login Timestamp" < w.started) AS history_active_users,
                   COUNT(*) FILTER (WHERE b."Login Timestamp" >= w.started
                                         AND b."Login Timestamp" < w.ended) AS window_events,
                   COUNT(DISTINCT t.uid) FILTER (WHERE b."Login Timestamp" >= w.started
                                                      AND b."Login Timestamp" < w.ended) AS window_active_users
            FROM _unique_target t
            JOIN _win w ON t.campaign_id = w.campaign_id
            JOIN read_parquet(?) b
              ON CAST(b."User ID" AS VARCHAR) = t.uid
             AND b."Login Timestamp" >= w.hist_start
             AND b."Login Timestamp" < w.ended
            GROUP BY t.campaign_id
        ''', [files]).fetchall()
        cohort_summary = {r[0]: {"target_history_events": int(r[1]),
                                  "target_history_active_users": int(r[2]),
                                  "target_window_events": int(r[3]),
                                  "target_window_active_users": int(r[4])}
                          for r in summary_rows}
        cohort_query_ok = True
    except Exception as exc:
        warnings.append(f"{org}: target-cohort history unavailable: {type(exc).__name__}: {exc}")

    for c in relevant:
        cid, start, end = c["campaign_id"], c["start"], c["end"]
        aligned = (start.minute == start.second == start.microsecond == 0 and
                   end.minute == end.second == end.microsecond == 0)
        if not aligned:
            warnings.append(f"{cid}/{org}: window not hour-aligned; no approximate event counts reported")
            results[cid] = {"status": "UNVERIFIED_ALIGNMENT"}
            continue
        attack_count = c["attack_per_org"].get(org, 0)
        bg_events, n_hours = sum_interval(total_prefix, start, end)
        hist_events, hist_nonempty = sum_interval(total_prefix, start - PERIOD, start)
        success_events, _ = sum_interval(success_prefix, start, end)
        failed_events, _ = sum_interval(fail_prefix, start, end)
        # "hours" contains only nonempty bins, so min(168) means evidence of
        # activity in all 168 hourly intervals, NOT proof a graph retained it.
        full_hist = hist_nonempty == 168
        # A successful inner-join query does not return campaigns whose
        # targeted users had zero background records. Those are true zeros,
        # not missing measurements; query failure is still NOT VERIFIED.
        cohort = cohort_summary.get(cid, {})
        if cohort_query_ok and cid not in cohort_summary:
            cohort = {"target_history_events": 0,
                      "target_history_active_users": 0,
                      "target_window_events": 0,
                      "target_window_active_users": 0}
        target_count = len(cohorts[(cid, org)])
        results[cid] = {
            "status": "MEASURED",
            "organization": org,
            "background_events": bg_events,
            "background_events_per_minute": bg_events / ((end-start).total_seconds()/60),
            "background_successes": success_events if outcome_column else None,
            "background_failures": failed_events if outcome_column else None,
            "background_success_rate": safe_rate(success_events, bg_events) if outcome_column else None,
            "history_7day_events": hist_events,
            "history_7day_active_hours": hist_nonempty,
            "history_7day_hours_with_activity": full_hist,
            "targeted_users": target_count,
            "target_history_events": cohort.get("target_history_events"),
            "target_history_active_users": cohort.get("target_history_active_users"),
            "target_history_active_fraction": safe_rate(cohort.get("target_history_active_users"), target_count),
            "target_window_events": cohort.get("target_window_events"),
            "target_window_active_users": cohort.get("target_window_active_users"),
            "attack_events": attack_count,
            "attack_to_background_ratio": safe_rate(attack_count, bg_events),
            "background_empty": bg_events == 0,
            "history_empty": hist_events == 0,
        }
    return results, {"organization": org, "status": "MEASURED", "file_count": len(files),
                     "schema": names, "windows": len(relevant),
                     "cohort_history_available": cohort_query_ok,
                     "outcome_column": outcome_column}


def comparison(a, b, factor, by_campaign_org, volume_tolerance):
    orgs = sorted(set(a["targeted_orgs"]) | set(b["targeted_orgs"]))
    issues = []
    org_data = {}
    background_gaps = []
    attack_background_gaps = []
    if a["targeted_orgs"] != b["targeted_orgs"]:
        issues.append("TARGETED_ORGANIZATION_MISMATCH")
    for org in orgs:
        left = by_campaign_org.get((a["campaign_id"], org))
        right = by_campaign_org.get((b["campaign_id"], org))
        if not left or not right or left.get("status") != "MEASURED" or right.get("status") != "MEASURED":
            issues.append("BACKGROUND_UNVERIFIED")
            org_data[org] = {"status": "BACKGROUND_UNVERIFIED"}
            continue
        gap = rel_gap(left["background_events"], right["background_events"])
        ratio_gap = rel_gap(left["attack_to_background_ratio"], right["attack_to_background_ratio"])
        history_gap = rel_gap(left["history_7day_events"], right["history_7day_events"])
        background_gaps.append(gap)
        if ratio_gap is not None:
            attack_background_gaps.append(ratio_gap)
        org_data[org] = {
            "background_a": left["background_events"],
            "background_b": right["background_events"],
            "background_volume_relative_gap": gap,
            "history_7day_a": left["history_7day_events"],
            "history_7day_b": right["history_7day_events"],
            "history_volume_relative_gap": history_gap,
            "attack_to_background_ratio_a": left["attack_to_background_ratio"],
            "attack_to_background_ratio_b": right["attack_to_background_ratio"],
            "attack_to_background_ratio_relative_gap": ratio_gap,
            "target_history_active_fraction_a": left["target_history_active_fraction"],
            "target_history_active_fraction_b": right["target_history_active_fraction"],
        }
        if left["background_events"] == 0 or right["background_events"] == 0:
            issues.append("EMPTY_BACKGROUND")
        if left["history_7day_events"] == 0 or right["history_7day_events"] == 0:
            issues.append("MISSING_PREVIOUS_HISTORY")
        if gap > volume_tolerance:
            issues.append("BACKGROUND_VOLUME_GAP")
    # Even if volume matches, underlying user/IP behavioral distributions may differ.
    # No pair is automatically declared fully matched on the basis of volume.
    if "BACKGROUND_UNVERIFIED" in issues:
        status = "INSUFFICIENT_DATA"
    elif issues:
        status = "REVIEW_REQUIRED"
    else:
        status = "SIMILAR_VOLUME_ONLY"
    return {
        "campaign_a": a["campaign_id"], "campaign_b": b["campaign_id"],
        "factor_changed": factor, "split": a["split"], "seed": a["seed"],
        "sorg": a["sorg"], "rip_a": a["rip"], "rip_b": b["rip"],
        "raccount_a": a["raccount"], "raccount_b": b["raccount"],
        "background_status": status, "issues": sorted(set(issues)),
        "org_comparisons": org_data,
        "max_background_volume_relative_gap": max(background_gaps) if background_gaps else None,
        "max_attack_to_background_ratio_relative_gap": (max(attack_background_gaps)
            if attack_background_gaps else None),
        "same_timestamp": a["start"] == b["start"],
        "note": "Similar traffic counts do not prove identical background or causal matching",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="CredBlock-FL repository root")
    parser.add_argument("--volume-tolerance", type=float, default=0.20,
                        help="Provisional relative gap threshold for screening background volumes; default 0.20")
    args = parser.parse_args()
    if not 0 <= args.volume_tolerance < 1:
        parser.error("--volume-tolerance must be in [0, 1)")
    root = args.root.resolve()
    con = duckdb.connect()
    try:
        campaigns, errors, cohorts = load_campaigns(root, con)
        if not campaigns:
            raise RuntimeError("No campaigns could be loaded")
        warnings = []
        by_campaign_org = {}
        org_info = []
        print("CRED BLOCK-FL PHASE 5 — BACKGROUND-WINDOW FEASIBILITY AUDIT")
        print(f"Campaigns loaded: {len(campaigns)} | Load errors: {len(errors)}")
        if len(campaigns) != 270 or errors:
            warnings.append("Incomplete campaign inventory; findings are provisional")
        for org in ORGS:
            print(f"  Scanning background for {org} ...", flush=True)
            results, info = compute_background_for_org(con, root, org, campaigns, cohorts, warnings)
            org_info.append(info)
            for cid, result in results.items():
                by_campaign_org[(cid, org)] = result

        window_rows = []
        for c in campaigns:
            bounds = SPLITS[c["split"]]
            split_start, split_end = dt(bounds[0]), dt(bounds[1])
            within = split_start <= c["start"] < c["end"] <= split_end
            for org in c["targeted_orgs"]:
                metrics = by_campaign_org.get((c["campaign_id"], org), {"status": "NO_MEASUREMENT"})
                window_rows.append({
                    "campaign_id": c["campaign_id"], "scenario_id": c["scenario_id"],
                    "split": c["split"], "seed": c["seed"],
                    "start": iso(c["start"]), "end": iso(c["end"]),
                    "split_window_valid": within,
                    **{"organization": org, **metrics},
                })
        pairs = [comparison(a, b, f, by_campaign_org, args.volume_tolerance)
                 for a, b, f in load_candidate_pairs(root, campaigns)]
        statuses = Counter(p["background_status"] for p in pairs)
        issue_counts = Counter(issue for p in pairs for issue in p["issues"])
        window_counts = Counter(r["status"] for r in window_rows)
        summary = {
            "campaigns_loaded": len(campaigns), "expected_campaigns": 270,
            "load_errors": errors, "organizations": org_info,
            "targeted_organization_windows": len(window_rows),
            "window_statuses": dict(window_counts),
            "candidate_pairs": len(pairs), "comparison_statuses": dict(statuses),
            "comparison_issue_counts": dict(issue_counts),
            "split_window_violations": sum(not r["split_window_valid"] for r in window_rows),
            "missing_or_empty_background_windows": sum(
                r.get("background_empty", False) for r in window_rows if r.get("status") == "MEASURED"),
            "missing_or_empty_history_windows": sum(
                r.get("history_empty", False) for r in window_rows if r.get("status") == "MEASURED"),
            "provisional_background_volume_tolerance": args.volume_tolerance,
            "warnings": warnings,
            "window_full_hourly_history_coverage": sum(
                r.get("history_7day_active_hours") == 168 for r in window_rows),
            "window_partial_hourly_history_coverage": sum(
                isinstance(r.get("history_7day_active_hours"), int)
                and r["history_7day_active_hours"] < 168 for r in window_rows),
            "window_missing_outcome_measurements": sum(
                r.get("background_successes") is None for r in window_rows),
            "window_unverified_target_cohort_measurements": sum(
                r.get("target_history_events") is None for r in window_rows),
            "interpretation": [
                "Measurements describe historical data availability, not a working seven-day graph retention implementation.",
                "Similar volume does not prove identical background, equal target cohorts, or causal isolation.",
                "Attack/background ratios come from separate synthetic and original background files; no replay merge is performed.",
                "Raccount cohort/intensity confounding remains independent of this background audit.",
                "Seven-day history may legitimately cross a split boundary; leakage depends on whether earlier events are used causally.",
                "Hourly aggregation is exact only for hour-aligned windows; others are marked unverified.",
                "Targeted cohort historical activity counts are reported only if the additional source-data query succeeds.",
            ],
        }
        report_dir = root / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report = {"summary": summary, "windows": window_rows, "comparison_pairs": pairs}
        (report_dir / "phase5_background_feasibility.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8")
        to_csv(report_dir / "phase5_background_windows.csv", window_rows)
        to_csv(report_dir / "phase5_background_comparisons.csv", pairs)
        lines = [
            "CRED BLOCK-FL — PHASE 5 BACKGROUND FEASIBILITY AUDIT", "=" * 58,
            f"Campaigns loaded: {len(campaigns)}/270; loading errors: {len(errors)}",
            f"Targeted organization windows: {len(window_rows)}",
            f"Window statuses: {dict(window_counts)}",
            f"One-factor comparison candidates: {len(pairs)}",
            f"Comparison statuses: {dict(statuses)}",
            f"Comparison issue counts: {dict(issue_counts)}",
            f"Split boundary violations: {summary['split_window_violations']}",
            f"Background zero-event windows: {summary['missing_or_empty_background_windows']}",
            f"Seven-day history zero-event windows: {summary['missing_or_empty_history_windows']}",
            f"Full 168-hour history activity coverage: {summary['window_full_hourly_history_coverage']}",
            f"Partial seven-day hourly coverage: {summary['window_partial_hourly_history_coverage']}",
            f"Background outcome measurements unavailable: {summary['window_missing_outcome_measurements']}",
            f"Target-cohort measurements unverified: {summary['window_unverified_target_cohort_measurements']}",
            "", "Organization sources:",
            *[f" - {i['organization']}: {i['status']} ({i.get('file_count', 0)} Parquet files)"
              for i in org_info],
            "", "Warnings:", *([" - " + x for x in warnings] if warnings else [" - None"]),
            "", "IMPORTANT: This audit does not prove matched background, label validity,",
            "graph retention, replay correctness, absence of leakage, or final Phase 5 completion.",
        ]
        (report_dir / "phase5_background_summary.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        print("\nReports:")
        for name in ("phase5_background_feasibility.json", "phase5_background_windows.csv",
                     "phase5_background_comparisons.csv", "phase5_background_summary.txt"):
            print(" -", report_dir / name)
        complete = (len(campaigns) == 270 and not errors
                    and all(i["status"] == "MEASURED" for i in org_info)
                    and not summary["split_window_violations"])
        return 0 if complete else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
