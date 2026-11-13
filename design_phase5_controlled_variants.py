#!/usr/bin/env python3
"""CredBlock-FL Phase 5: DESIGN-ONLY controlled Raccount/Sorg experiment recipes.

Reads the completed Phase-5 planning and exact RIP audits. Writes *only* new
versioned JSON/CSV/TXT recipes to reports/. Does not read or modify campaign
Parquet, original background, generator, graphs, or framework.

This is an experimental recipe, not a campaign generator or replay engine.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

RLEVELS = (0.2, 0.5, 0.8)
RIPS = (0.2, 0.5, 0.8)
SORGS = (2, 3, 5)
SPLITS = ("TRAIN", "VAL", "TEST")
SEEDS = (1001, 1002, 1003)
VERSION = "v1"


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Required report not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keynum(value: object) -> str:
    return f"{float(value):.2f}"


def target_counts(sorg: int, reuse: float) -> list[int]:
    """Exactly reproduce the planned local cohort cardinality model.

    100 credential identities; round(100*Raccount) reused at every org.
    Remaining credentials partitioned across organizations, remainder first.
    """
    if sorg == 1:
        return [100]
    shared = round(100 * reuse)
    unique = 100 - shared
    q, remainder = divmod(unique, sorg)
    return [shared + q + (i < remainder) for i in range(sorg)]


def attempt_allocation(n_users: int, budget: int) -> dict:
    """An exact integer feasibility *certificate* for 1..3 attempts/user.

    Deterministic recipe: each user receives 1 attempt; add up to 2 to each
    user in local cohort order. No actual IDs are selected here.
    """
    if budget < n_users or budget > 3 * n_users:
        raise ValueError(f"Cannot give {budget} attempts to {n_users} users (1..3 each)")
    extra = budget - n_users
    n3, remainder = divmod(extra, 2)
    n2 = remainder
    n1 = n_users - n3 - n2
    assert n1 + 2 * n2 + 3 * n3 == budget
    assert n1 >= 0 and n2 >= 0 and n3 >= 0
    return {"one_attempt_users": n1, "two_attempt_users": n2,
            "three_attempt_users": n3, "total_attempts": budget}


def add_campaign(records: dict, campaign_id: str, *, split: str, seed: int,
                 sorg: int, rip: float, raccount: float | None,
                 orgs: list[str], manifest_hash: str) -> None:
    if campaign_id not in records:
        records[campaign_id] = {
            "campaign_id": campaign_id, "split": split, "seed": seed,
            "sorg": sorg, "rip": keynum(rip),
            "raccount": keynum(raccount) if raccount is not None else None,
            "organizations": sorted(orgs), "manifest_sha256": manifest_hash,
        }
    else:
        old = records[campaign_id]
        assert (old["split"], old["seed"], old["sorg"], old["rip"],
                old["raccount"], old["organizations"], old["manifest_sha256"]) == (
                split, seed, sorg, keynum(rip),
                keynum(raccount) if raccount is not None else None,
                sorted(orgs), manifest_hash), f"Conflicting planner metadata for {campaign_id}"


def collect_campaigns(plan: dict) -> dict:
    """Merge pair observations, enforcing agreement on every observed attribute."""
    result = {}
    for pair in plan["comparisons"]:
        for suffix in ("a", "b"):
            cid = pair[f"campaign_{suffix}"]
            observed = {
                "campaign_id": cid,
                "split": pair["split"],
                "seed": int(pair["seed"]),
                "sorg": int(pair["sorg"]),
                "organizations": sorted(pair["organizations"]),
                "manifest_sha256": pair[f"source_manifest_sha256_{suffix}"],
            }
            if pair["factor_changed"] == "RIP":
                observed["rip"] = keynum(pair[f"factor_{suffix}"])
            elif pair["factor_changed"] == "Raccount":
                observed["raccount"] = keynum(pair[f"factor_{suffix}"])
            else:
                raise ValueError(f"Unknown factor {pair['factor_changed']}")
            old = result.setdefault(cid, {})
            for field, value in observed.items():
                if field in old and old[field] != value:
                    raise ValueError(f"Conflicting {field} for {cid}: {old[field]} != {value}")
                old[field] = value
    for record in result.values():
        if "rip" not in record:
            raise ValueError(f"RIP not inferred for {record['campaign_id']}")
        if "raccount" not in record:
            if record["sorg"] != 1:
                raise ValueError(f"Raccount not inferred for {record['campaign_id']}")
            record["raccount"] = None
        if len(record["organizations"]) != record["sorg"]:
            raise ValueError(f"Org count mismatch for {record['campaign_id']}")
    return result


def choose_anchor(campaigns: list[dict], anchor_info: dict) -> dict:
    # The planned anchor must be checked against ALL organizations in a group.
    # With Sorg comparisons, member organization sets differ, so a single
    # campaign-level eligibility flag is insufficient to select a shared anchor.
    org_sets = {tuple(x["organizations"]) for x in campaigns}
    if len(org_sets) > 1:
        return {"anchor_campaign_candidate": None,
                "anchor_status": "REQUIRES_MULTI_ORG_SHARED_ANCHOR_VALIDATION",
                "source_campaigns": sorted(x["campaign_id"] for x in campaigns),
                "shared_background_policy": "SAME_SOURCE_WINDOW_IN_SEPARATE_ISOLATED_REPLAYS"}
    eligible = [x for x in campaigns if anchor_info.get(x["campaign_id"], {})
                .get("eligible_for_planning")]
    return {"anchor_campaign_candidate": eligible[0]["campaign_id"] if eligible else None,
            "anchor_status": "CANDIDATE_ONLY" if eligible else "NO_ELIGIBLE_EXISTING_ANCHOR",
            "source_campaigns": sorted(x["campaign_id"] for x in campaigns),
            "shared_background_policy": "SAME_SOURCE_WINDOW_IN_SEPARATE_ISOLATED_REPLAYS"}


def build_recipes(campaigns: dict, plan: dict) -> tuple[list[dict], list[dict]]:
    all_campaigns = list(campaigns.values())
    by_exact = {(c["split"], c["seed"], c["sorg"], c["rip"], c["raccount"]): c
                for c in all_campaigns}
    if len(by_exact) != len(all_campaigns):
        raise ValueError("Multiple campaigns found for a factorial cell")
    if len(all_campaigns) != 270:
        raise ValueError(f"Expected 270 campaigns; got {len(all_campaigns)}")
    by_anchor = plan["anchor_candidates"]
    recipes = []
    # Raccount: same split, seed, Sorg, RIP. Fixed attempt count per org
    # chosen at the lower bound of the feasible intersection. It is *not* a
    # causal Raccount-only comparison: target cohorts change by definition.
    for split in SPLITS:
        for seed in SEEDS:
            for sorg in SORGS:
                for rip in RIPS:
                    members = [by_exact[(split, seed, sorg, keynum(rip), keynum(r))]
                               for r in RLEVELS]
                    if len({tuple(x["organizations"]) for x in members}) != 1:
                        raise ValueError(f"Raccount org set mismatch: {split}/{seed}/{sorg}/{rip}")
                    counts = {keynum(r): target_counts(sorg, r) for r in RLEVELS}
                    budgets = [max(v[i] for v in counts.values()) for i in range(sorg)]
                    for r, nums in counts.items():
                        for idx, n in enumerate(nums):
                            if not n <= budgets[idx] <= 3*n:
                                raise ValueError(f"Infeasible Raccount budget {sorg},{r},{idx}")
                    variants = []
                    for m in members:
                        r = m["raccount"]
                        variants.append({"source_campaign": m["campaign_id"],
                                         "raccount": r, "rip_target": m["rip"],
                                         "target_users_per_org": counts[r],
                                         "attempts_per_org": budgets,
                                         "user_attempt_allocation_per_org": [
                                             attempt_allocation(n, budget)
                                             for n, budget in zip(counts[r], budgets)],
                                         "requires_new_synthetic_events": True})
                    recipes.append({"recipe_id": f"RA_{split}_SEED{seed}_S{sorg}_RIP{keynum(rip)}",
                                    "family": "Raccount_fixed_per_org_attempts",
                                    "split": split, "seed": seed, "sorg": sorg,
                                    "rip_target": keynum(rip),
                                    "organizations": members[0]["organizations"],
                                    **choose_anchor(members, by_anchor),
                                    "budget_attempts_per_org": budgets,
                                    "budget_total_attempts": sum(budgets),
                                    "variants": variants,
                                    "interpretation": "Adjusted reuse/coverage comparison, NOT isolated reuse causal effect",
                                    "status": "PROPOSED_REQUIRES_IMPLEMENTATION_VALIDATION"})
    # Sorg: same split/seed/RIP/Raccount, compare 2,3,5 organizations.
    # The Sorg1 condition has N/A Raccount and cannot be silently treated
    # as sharing the same Raccount level; we specify it separately.
    for split in SPLITS:
        for seed in SEEDS:
            for rip in RIPS:
                for reuse in RLEVELS:
                    members = [by_exact[(split, seed, s, keynum(rip), keynum(reuse))]
                               for s in SORGS]
                    fixed_per_org = 100
                    variant_rows = []
                    for m in members:
                        nums = target_counts(m["sorg"], reuse)
                        certs = [attempt_allocation(n, fixed_per_org) for n in nums]
                        variant_rows.append({"source_campaign": m["campaign_id"],
                                             "sorg": m["sorg"],
                                             "organizations": m["organizations"],
                                             "target_users_per_org": nums,
                                             "attempts_per_org": [fixed_per_org] * m["sorg"],
                                             "total_attempts": fixed_per_org * m["sorg"],
                                             "user_attempt_allocation_per_org": certs,
                                             "requires_new_synthetic_events": True})
                    # Sensitivity: common total attack budget across 2,3,5 orgs.
                    min_total = max(sum(target_counts(s, reuse)) for s in SORGS)
                    max_total = min(3*sum(target_counts(s, reuse)) for s in SORGS)
                    recipes.append({"recipe_id": f"SO_{split}_SEED{seed}_RIP{keynum(rip)}_RA{keynum(reuse)}",
                                    "family": "Sorg_fixed_per_org_attempts",
                                    "split": split, "seed": seed,
                                    "raccount": keynum(reuse), "rip_target": keynum(rip),
                                    "sorg_levels": list(SORGS),
                                    **choose_anchor(members, by_anchor),
                                    "fixed_per_org_budget": fixed_per_org,
                                    "fixed_total_sensitivity_feasible": min_total <= max_total,
                                    "fixed_total_sensitivity_budget_interval": [min_total, max_total]
                                      if min_total <= max_total else None,
                                    "variants": variant_rows,
                                    "interpretation": "Org spread and total volume vary together; fixed-total is a separate sensitivity test; org composition differs",
                                    "status": "PROPOSED_REQUIRES_IMPLEMENTATION_VALIDATION"})
    # Special Sorg=1 is NOT part of the primary controlled-Sorg series.
    reference = []
    for split in SPLITS:
        for seed in SEEDS:
            for rip in RIPS:
                one = by_exact[(split, seed, 1, keynum(rip), None)]
                reference.append({"split": split, "seed": seed, "rip": keynum(rip),
                                  "campaign_id": one["campaign_id"],
                                  "raccount": "NOT_APPLICABLE",
                                  "interpretation": "Sorg=1 descriptive reference, not matched to an Raccount level"})
    return recipes, reference


def write_exclusive(path: Path, content: str) -> None:
    # Do not silently overwrite research outputs.
    with path.open("x", encoding="utf-8", newline="") as f:
        f.write(content)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--output-stem", default="phase5_controlled_variant_recipes_v1")
    args = ap.parse_args()
    root = args.root.resolve()
    report_dir = root / "reports"
    plan_path = report_dir / "phase5_controlled_comparison_plan_v1.json"
    rip_path = report_dir / "phase5_rip_exact_equivalence_summary.json"
    plan, rip = load_json(plan_path), load_json(rip_path)
    if not (rip.get("rip_pairs_found") == 270 and
            rip.get("statuses", {}).get("PASS_SYNTHETIC_RIP_EQUIVALENCE") == 270 and
            not rip.get("inventory_errors") and not rip.get("source_read_errors")):
        raise ValueError("Exact RIP audit not fully PASS; controlled recipes blocked")
    if plan.get("summary", {}).get("campaigns_loaded") != 270:
        raise ValueError("Planning report does not contain all 270 campaigns")
    campaigns = collect_campaigns(plan)
    recipes, reference = build_recipes(campaigns, plan)
    assert len(recipes) == 162 and len(reference) == 27
    output = {
        "purpose": "PRE-IMPLEMENTATION CONTROLLED EXPERIMENT RECIPES ONLY",
        "version": VERSION,
        "input_checksums_sha256": {plan_path.name: digest(plan_path), rip_path.name: digest(rip_path)},
        "source_campaign_count": len(campaigns),
        "raccount_recipe_count": sum(x["family"].startswith("Raccount") for x in recipes),
        "sorg_recipe_count": sum(x["family"].startswith("Sorg") for x in recipes),
        "source_sorg1_references": reference,
        "recipes": recipes,
        "requirements_before_generation": [
            "Freeze protocol using TRAIN/VAL information; no TEST score-based anchor selection",
            "Use same historical background in isolated branches, never combine alternatives",
            "Validate per-event RIP, reuse mapping, fixed budgets and 1..3 attempts per target",
            "Validate split and seven-day history at every proposed anchor for all orgs",
            "Define event-time placement and local target-user sampling without future knowledge",
            "Resolve source flag negative-label mask and graph feature exclusion",
            "Use new directories, manifests, hashes; do not modify existing 270 campaigns",
            "Report change in target cohorts and mean attempts/user for Raccount",
            "Report organization composition and changed total intensity for Sorg",
            "Do not claim implemented, controlled or causal outcomes from recipes alone",
        ],
        "note": "Planning only. No Parquet or variant files generated.",
    }
    if not report_dir.is_dir():
        raise FileNotFoundError(f"Expected reports directory is absent: {report_dir}")
    json_out = report_dir / f"{args.output_stem}.json"
    csv_out = report_dir / f"{args.output_stem}.csv"
    txt_out = report_dir / f"{args.output_stem}.txt"
    if any(x.exists() for x in (json_out, csv_out, txt_out)):
        raise FileExistsError("Versioned report already exists; choose --output-stem with a new name")
    # Prepare all contents before writing.
    import io
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["recipe_id", "family", "split", "seed", "rip", "sorg_or_levels",
                     "raccount", "source_campaigns", "attempts_per_org", "total_attempts",
                     "candidate_anchor", "status", "caveat"])
    for recipe in recipes:
        writer.writerow([recipe["recipe_id"], recipe["family"], recipe["split"],
                         recipe["seed"], recipe["rip_target"],
                         recipe.get("sorg", recipe.get("sorg_levels")),
                         recipe.get("raccount", "VARIES"),
                         ";".join(recipe["source_campaigns"]),
                         recipe.get("budget_attempts_per_org", recipe.get("fixed_per_org_budget")),
                         recipe.get("budget_total_attempts", "VARIES_BY_SORG"),
                         recipe["anchor_campaign_candidate"], recipe["status"],
                         recipe["interpretation"]])
    issues = Counter(x["anchor_status"] for x in recipes)
    text = "\n".join([
        "CRED BLOCK-FL — PHASE 5 CONTROLLED VARIANT RECIPE DESIGN",
        "="*65,
        "STATUS: PROPOSED ONLY — no attack events, replays or model data generated",
        f"Original campaigns preserved: {len(campaigns)}",
        f"Raccount matched-budget group recipes: {output['raccount_recipe_count']}",
        f"Sorg fixed-per-org group recipes: {output['sorg_recipe_count']}",
        f"Sorg=1 descriptive references: {len(reference)}",
        f"Planning-level anchors: {dict(issues)}",
        "Raccount per-org fixed minimum budgets: Sorg2=[90,90], Sorg3=[87,87,86], Sorg5=[84,84,84,84,84]",
        "Sorg primary: 100 attempts per targeted organization; total grows with Sorg",
        "Sorg fixed-total sensitivity: per-level budget intervals calculated, NOT generated",
        "CRITICAL: Raccount alters target cohorts; equal attempts cannot isolate reuse alone.",
        "CRITICAL: Sorg1 Raccount is N/A; use as descriptive reference, not an equal-reuse cell.",
        "CRITICAL: anchors are candidates only, not replay-validated.",
        "Next: review/freeze protocol; implement strictly versioned variant generator + replay.",
        "",
    ])
    # Outputs only; no input/report rewriting.
    write_exclusive(json_out, json.dumps(output, indent=2) + "\n")
    write_exclusive(csv_out, stream.getvalue())
    write_exclusive(txt_out, text)
    print(text)
    for out in (json_out, csv_out, txt_out):
        print(out)

if __name__ == "__main__":
    main()
