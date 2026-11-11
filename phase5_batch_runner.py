"""
CredBlock-FL Phase 5 schedule-driven batch runner.

Safe defaults:
- Dry-run unless --execute is supplied.
- Never overwrites an existing campaign directory.
- --execute requires --limit so generation is always explicitly bounded.
- Stops at the first failed generation or manifest verification.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.simulation import credential_stuffing_generator as g


def load_schedule(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Schedule file not found: {path}")
    schedule = json.loads(path.read_text(encoding="utf-8"))

    expected_splits = ("train", "val", "test")
    for split in expected_splits:
        values = schedule.get(split)
        if not isinstance(values, list) or len(values) != 90:
            raise ValueError(
                f"Schedule '{split}' must contain exactly 90 timestamps."
            )
        parsed = [datetime.fromisoformat(value) for value in values]
        if len(set(parsed)) != 90:
            raise ValueError(f"Schedule '{split}' contains duplicate timestamps.")
        if parsed != sorted(parsed):
            raise ValueError(f"Schedule '{split}' is not chronologically sorted.")

        split_start, split_end = g.CHRONOLOGICAL_SPLITS[split]
        lower = datetime.fromisoformat(split_start)
        upper = datetime.fromisoformat(split_end)
        duration = timedelta(minutes=g.CAMPAIGN_DURATION_MINUTES)
        for start in parsed:
            if not (lower <= start and start + duration <= upper):
                raise ValueError(
                    f"{split} timestamp {start.isoformat()} falls outside "
                    f"the configured chronological split."
                )
    return schedule


def build_jobs(schedule: dict, selected_split: str | None):
    ordered_base_ids = [
        campaign_id
        for campaign_id, _slot in sorted(
            g.CAMPAIGN_SLOTS.items(), key=lambda item: item[1]
        )
    ]
    jobs = []
    for split in ("train", "val", "test"):
        if selected_split and split != selected_split:
            continue
        for base_id, timestamp in zip(ordered_base_ids, schedule[split]):
            scenario_id, seed_part = base_id.split("_SEED")
            seed = int(seed_part)
            campaign_id = f"{base_id}_{split.upper()}"

            if campaign_id not in g.SPLIT_IP_ALLOCATIONS:
                raise ValueError(f"No IP reservation for {campaign_id}")

            config = g.build_campaign_config(scenario_id, seed)
            expected_base_id = config["campaign_id"]
            if expected_base_id != base_id:
                raise ValueError(
                    f"Campaign registry mismatch: {base_id} != {expected_base_id}"
                )

            jobs.append({
                "campaign_id": campaign_id,
                "scenario": scenario_id,
                "seed": seed,
                "split": split,
                "start": timestamp,
                "output_dir": str(g.SYNTHETIC_EVENTS_DIR / campaign_id),
            })
    return jobs


def verify_generated_job(job: dict):
    output_dir = Path(job["output_dir"])
    manifest_path = output_dir / "manifest.json"
    if not output_dir.is_dir():
        raise RuntimeError(f"Generator returned success but directory is missing: {output_dir}")
    if not manifest_path.is_file():
        raise RuntimeError(f"Manifest missing after generation: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = {
        "campaign_id": manifest.get("campaign_id") == job["campaign_id"],
        "split": manifest.get("split") == job["split"],
        "campaign_start": manifest.get("campaign_start") == job["start"],
        "duration_minutes": manifest.get("duration_minutes") == g.CAMPAIGN_DURATION_MINUTES,
        "scenario_id": manifest.get("scenario_id") == job["scenario"],
        "seed": manifest.get("seed") == job["seed"],
        "parquet_present": any(output_dir.glob("*.parquet")),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"Post-generation verification failed for {job['campaign_id']}: {failed}"
        )
    return checks


def main():
    parser = argparse.ArgumentParser(
        description="Generate scheduled CredBlock-FL Phase 5 campaigns safely."
    )
    parser.add_argument(
        "--schedule",
        type=Path,
        default=g.METADATA_DIR / "split_campaign_schedule.json",
        help="Path to split_campaign_schedule.json",
    )
    parser.add_argument(
        "--split", choices=("train", "val", "test"),
        help="Optionally restrict generation to one split.",
    )
    parser.add_argument(
        "--limit", type=int,
        help="Maximum number of NEW campaigns to generate in this run.",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually run generation. Without this flag, the runner only previews.",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1.")
    if args.execute and args.limit is None:
        parser.error(
            "--execute requires --limit. Use a small limit for a controlled batch."
        )

    project_root = g.PROJECT_ROOT
    schedule = load_schedule(args.schedule)
    jobs = build_jobs(schedule, args.split)

    pending = []
    already_present = []
    for job in jobs:
        if Path(job["output_dir"]).exists():
            already_present.append(job)
        else:
            pending.append(job)

    selected = pending[:args.limit] if args.limit else pending

    print("=== CRED BLOCK-FL SCHEDULE-DRIVEN BATCH RUNNER ===")
    print("Mode:", "EXECUTE" if args.execute else "DRY RUN")
    print("Expected jobs in selected scope:", len(jobs))
    print("Existing directories (will NOT be changed):", len(already_present))
    print("New campaigns available:", len(pending))
    print("Campaigns selected this run:", len(selected))
    print("Historical campaign directories are outside this runner's target set.")

    if not args.execute:
        print("\nPreview (first 15 selected campaigns):")
        for job in selected[:15]:
            print(
                job["campaign_id"], "|", job["start"],
                "|", job["output_dir"]
            )
        if len(selected) > 15:
            print(f"... and {len(selected) - 15} more.")
        print("\nNo campaign data was generated or modified.")
        print("To generate a controlled batch, add --execute --limit 1.")
        return 0

    log_dir = project_root / "reports"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "phase5_batch_generation_log.json"
    records = []

    for index, job in enumerate(selected, start=1):
        command = [
            sys.executable, "-m",
            "src.simulation.credential_stuffing_generator",
            "--scenario", job["scenario"],
            "--seed", str(job["seed"]),
            "--split", job["split"],
            "--start", job["start"],
        ]
        print(f"\n[{index}/{len(selected)}] Generating {job['campaign_id']}")
        print("Scheduled start:", job["start"])
        print("Command:", subprocess.list2cmdline(command))

        result = subprocess.run(command, cwd=project_root)
        record = {
            "campaign_id": job["campaign_id"],
            "scheduled_start": job["start"],
            "return_code": result.returncode,
        }

        if result.returncode != 0:
            record["status"] = "FAILED"
            records.append(record)
            log_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
            print("Generation failed. Stopping; no later campaigns will be attempted.")
            print("Log:", log_path)
            return result.returncode or 1

        try:
            checks = verify_generated_job(job)
            record["status"] = "PASS"
            record["checks"] = checks
        except Exception as exc:
            record["status"] = "POST_GENERATION_VERIFY_FAILED"
            record["error"] = str(exc)
            records.append(record)
            log_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
            print(record["error"])
            print("Stopping after post-generation verification failure.")
            print("Log:", log_path)
            return 2

        records.append(record)
        log_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print("Post-generation verification: PASS")

    print("\nBatch completed.")
    print("Generated and verified:", sum(r["status"] == "PASS" for r in records))
    print("Log:", log_path)
    print("Run the 270-campaign audit after reviewing this batch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
