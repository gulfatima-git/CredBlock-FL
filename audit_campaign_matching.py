"""CredBlock-FL Phase 5 factorial campaign matching audit.

Run from the project root: python audit_campaign_matching.py
Read-only with respect to synthetic data. Creates three reports in reports/.

The audit compares paired campaigns that differ in *only one* primary factor
(RIP or Raccount), for the same split, seed and organization spread.
A pair is not declared scientifically matched when background data is missing.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import duckdb

BASE = Path.cwd()
DATA = BASE / "data" / "phase5" / "synthetic_events"
REPORTS = BASE / "reports"
# Screening tolerance only, NOT an official experimental acceptance criterion.
INTENSITY_RELATIVE_TOLERANCE = 0.05


def close(a, b):
    if a == b:
        return True
    if not a or not b:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= INTENSITY_RELATIVE_TOLERANCE


def relative_gap(a, b):
    if a is None or b is None:
        return None
    den = max(abs(a), abs(b))
    return round(abs(a - b) / den, 6) if den else 0.0


def load_campaign(folder, db):
    manifest_file = folder / "manifest.json"
    files = sorted(folder.glob("*.parquet"))
    if not manifest_file.is_file() or not files:
        raise ValueError("Missing manifest or Parquet files")
    m = json.loads(manifest_file.read_text(encoding="utf-8"))
    cid = m["campaign_id"]
    rows = db.execute('''
        SELECT organization, "User ID", COUNT(*) AS attempts
        FROM read_parquet(?)
        GROUP BY organization, "User ID"
    ''', [[str(f) for f in files]]).fetchall()
    cohorts = defaultdict(set)
    for org, user, n in rows:
        cohorts[str(org)].add(str(user))
    # Parquet rows in these campaign directories are synthetic attack events,
    # not background events. This audit cannot establish background equivalence.
    return {
        "id": cid,
        "split": str(m["split"]).upper(),
        "seed": int(m["seed"]),
        "scenario": m["scenario_id"],
        "sorg": int(m["Sorg_target"]),
        "rip": float(m["RIP_target"]),
        "raccount": None if m.get("Raccount_target") is None else float(m["Raccount_target"]),
        "start": m["campaign_start"],
        "organizations": set(map(str, m["targeted_organizations"])),
        "cohorts": cohorts,
        "total": int(m["total_events"]),
        "per_org": {str(k): int(v) for k, v in m["events_per_organization"].items()},
        "duration": float(m["duration_minutes"]),
    }


def test_pair(a, b, factor):
    organizations_match = a["organizations"] == b["organizations"]
    cohort_match = (organizations_match and all(a["cohorts"].get(org, set()) ==
                                               b["cohorts"].get(org, set())
                                               for org in a["organizations"]))
    # Intensity is measured by attack volume over an equal duration, with
    # a separate check for each organization when organization sets match.
    total_rates = [a["total"] / a["duration"], b["total"] / b["duration"]]
    total_intensity_match = close(*total_rates)
    org_gaps = {org: relative_gap(a["per_org"].get(org), b["per_org"].get(org))
                for org in sorted(a["organizations"] | b["organizations"])}
    per_org_intensity_match = (organizations_match and all(
        org_gaps[org] is not None and org_gaps[org] <= INTENSITY_RELATIVE_TOLERANCE
        for org in org_gaps))
    same_start = a["start"] == b["start"]
    # Same start timestamp alone would not demonstrate same background events.
    background_status = "NOT_VERIFIED" if same_start else "UNMATCHED_WINDOW"
    if not organizations_match or not cohort_match or not total_intensity_match or not per_org_intensity_match or not same_start:
        status = "UNMATCHED"
    else:
        status = "PROVISIONAL_ONLY"
    return {
        "factor_changed": factor,
        "campaign_a": a["id"], "campaign_b": b["id"],
        "split": a["split"], "seed": a["seed"], "sorg": a["sorg"],
        "rip_a": a["rip"], "rip_b": b["rip"],
        "raccount_a": a["raccount"], "raccount_b": b["raccount"],
        "organizations_a": ";".join(sorted(a["organizations"])),
        "organizations_b": ";".join(sorted(b["organizations"])),
        "organizations_match": organizations_match,
        "target_cohorts_match": cohort_match,
        "total_attempts_a": a["total"], "total_attempts_b": b["total"],
        "attack_intensity_relative_gap": relative_gap(*total_rates),
        "total_intensity_within_5pct": total_intensity_match,
        "per_org_intensity_within_5pct": per_org_intensity_match,
        "per_org_attempt_gaps": json.dumps(org_gaps, sort_keys=True),
        "start_a": a["start"], "start_b": b["start"],
        "same_start": same_start,
        "background_matching": background_status,
        "status": status,
    }


def main():
    if not DATA.is_dir():
        raise SystemExit(f"No campaign directory: {DATA}")
    REPORTS.mkdir(exist_ok=True)
    db = duckdb.connect()
    campaigns = []
    errors = []
    for folder in sorted(DATA.iterdir()):
        if not folder.is_dir() or not folder.name.endswith(("_TRAIN", "_VAL", "_TEST")):
            continue
        try:
            campaigns.append(load_campaign(folder, db))
        except Exception as exc:
            errors.append({"campaign": folder.name, "error": f"{type(exc).__name__}: {exc}"})
    db.close()

    groups = defaultdict(list)
    for campaign in campaigns:
        groups[(campaign["split"], campaign["seed"], campaign["sorg"])].append(campaign)

    comparisons = []
    for group in groups.values():
        for a, b in combinations(group, 2):
            if a["rip"] != b["rip"] and a["raccount"] == b["raccount"]:
                comparisons.append(test_pair(a, b, "RIP"))
            elif a["rip"] == b["rip"] and a["raccount"] != b["raccount"]:
                comparisons.append(test_pair(a, b, "Raccount"))

    counts = Counter(x["status"] for x in comparisons)
    issue_counts = Counter()
    for p in comparisons:
        for column in ("organizations_match", "target_cohorts_match",
                       "total_intensity_within_5pct", "per_org_intensity_within_5pct", "same_start"):
            if not p[column]:
                issue_counts[column] += 1

    summary = {
        "purpose": "Controlled factorial comparison screening; not a claim of causal isolation",
        "campaigns_loaded": len(campaigns),
        "campaign_load_errors": errors,
        "candidate_pair_count": len(comparisons),
        "candidate_pairs_by_factor": dict(Counter(p["factor_changed"] for p in comparisons)),
        "pair_status_counts": dict(counts),
        "unmatched_condition_counts": dict(issue_counts),
        "intensity_relative_tolerance_provisional": INTENSITY_RELATIVE_TOLERANCE,
        "background_comparability_verified": False,
        "notes": [
            "Only same-split, same-seed, same-Sorg pairs changing exactly one factor are compared.",
            "A target cohort is approximated as the unique local User IDs found in synthetic attack events.",
            "Cross-split or cross-seed pairs are not used as matched factorial counterparts.",
            "Distinct campaign starts do not imply matched background; source background is not present in these campaign manifests.",
            "5 percent is a screening tolerance only; approve an experimental acceptance threshold before claiming matching.",
            "No campaign data was modified.",
        ],
    }
    (REPORTS / "phase5_campaign_matching_audit.json").write_text(
        json.dumps({"summary": summary, "comparisons": comparisons}, indent=2), encoding="utf-8")
    csv_path = REPORTS / "phase5_campaign_matching_audit.csv"
    if comparisons:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(comparisons[0]))
            writer.writeheader()
            writer.writerows(comparisons)
    txt_lines = [
        "CRED BLOCK-FL PHASE 5 — CAMPAIGN MATCHING AUDIT",
        "=" * 55,
        f"Campaigns loaded: {len(campaigns)}",
        f"Loading errors: {len(errors)}",
        f"One-factor comparison candidates: {len(comparisons)}",
        f"Factors: {dict(summary['candidate_pairs_by_factor'])}",
        f"Pair statuses: {dict(counts)}",
        f"Condition failures: {dict(issue_counts)}",
        "Background match: NOT VERIFIED (requires source background/replay evidence)",
        "Only provisional comparison candidates can pass this screen; do not infer causal isolation.",
    ]
    (REPORTS / "phase5_campaign_matching_summary.txt").write_text("\n".join(txt_lines)+"\n", encoding="utf-8")
    print("\n".join(txt_lines))
    print("Reports:")
    print(" -", REPORTS / "phase5_campaign_matching_audit.json")
    print(" -", csv_path)
    print(" -", REPORTS / "phase5_campaign_matching_summary.txt")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
