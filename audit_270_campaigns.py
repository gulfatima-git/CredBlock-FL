"""Read-only audit of all 270 CredBlock-FL Phase 5 campaign instances.

Run from the CredBlock-FL project root:
    python audit_270_campaigns.py

The script does not generate, modify, or delete campaign data. Missing campaigns
are reported as NOT_GENERATED, not PASS. Reports are written under reports/.
"""
from __future__ import annotations

import csv
import ipaddress
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


def add_check(checks, name, passed, detail=""):
    checks.append({
        "check": name,
        "status": "PASS" if passed else "FAIL",
        "detail": str(detail),
    })


def parse_dt(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def main():
    try:
        from src.simulation import credential_stuffing_generator as g
    except Exception as exc:
        print(f"Could not import generator: {type(exc).__name__}: {exc}")
        return 2

    project_root = Path.cwd()
    data_root = project_root / "data/phase5/synthetic_events"
    schedule_path = project_root / "data/phase5/metadata/split_campaign_schedule.json"
    report_dir = project_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not schedule_path.is_file():
        print(f"Schedule not found: {schedule_path}")
        return 2
    if not data_root.is_dir():
        print(f"Campaign data directory not found: {data_root}")
        return 2

    try:
        import duckdb
    except ImportError:
        duckdb = None

    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    base_ids = [name for name, _ in sorted(g.CAMPAIGN_SLOTS.items(), key=lambda x: x[1])]
    expected_ids = set(g.SPLIT_IP_ALLOCATIONS)
    ip_base = int(g.IP_NETWORK.network_address)
    duration = timedelta(minutes=g.CAMPAIGN_DURATION_MINUTES)

    records = []
    check_counts = Counter()

    for split in ("TRAIN", "VAL", "TEST"):
        schedule_values = schedule.get(split.lower(), [])
        if len(schedule_values) != len(base_ids):
            print(f"WARNING: {split} schedule has {len(schedule_values)} timestamps; expected {len(base_ids)}")

        for index, base_id in enumerate(base_ids):
            campaign_id = f"{base_id}_{split}"
            folder = data_root / campaign_id
            checks = []
            record = {
                "campaign_id": campaign_id,
                "split": split,
                "scenario_id": base_id.split("_SEED")[0],
                "status": None,
                "event_count": None,
                "scheduled_start": None,
                "manifest_start": None,
                "observed_event_start": None,
                "observed_event_end": None,
                "ip_min_offset": None,
                "ip_max_offset": None,
                "failed_checks": [],
                "checks": checks,
            }

            if index >= len(schedule_values):
                add_check(checks, "schedule_entry_exists", False, "No timestamp at this campaign index")
            else:
                try:
                    scheduled_start = parse_dt(schedule_values[index])
                    record["scheduled_start"] = scheduled_start.isoformat()
                    add_check(checks, "schedule_entry_exists", True, record["scheduled_start"])
                except Exception as exc:
                    scheduled_start = None
                    add_check(checks, "schedule_timestamp_valid", False, f"{type(exc).__name__}: {exc}")

            if not folder.is_dir():
                record["status"] = "NOT_GENERATED"
                record["failed_checks"] = [c["check"] for c in checks if c["status"] == "FAIL"]
                records.append(record)
                continue

            manifest_path = folder / "manifest.json"
            if not manifest_path.is_file():
                add_check(checks, "manifest_exists", False, str(manifest_path))
                manifest = None
            else:
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    add_check(checks, "manifest_exists", True, "manifest.json")
                except Exception as exc:
                    manifest = None
                    add_check(checks, "manifest_json_valid", False, f"{type(exc).__name__}: {exc}")

            if manifest is not None:
                add_check(checks, "manifest_campaign_id", manifest.get("campaign_id") == campaign_id, manifest.get("campaign_id"))
                add_check(checks, "manifest_split", str(manifest.get("split", "")).upper() == split, manifest.get("split"))
                add_check(checks, "manifest_scenario", manifest.get("scenario_id") == record["scenario_id"], manifest.get("scenario_id"))
                try:
                    manifest_start = parse_dt(manifest["campaign_start"])
                    manifest_end = parse_dt(manifest["campaign_end"])
                    record["manifest_start"] = manifest_start.isoformat()
                    add_check(checks, "manifest_start_matches_schedule", scheduled_start is not None and manifest_start == scheduled_start,
                              f"manifest={manifest_start.isoformat()}, scheduled={scheduled_start.isoformat() if scheduled_start else 'INVALID'}")
                    add_check(checks, "manifest_duration", manifest_end - manifest_start == duration,
                              f"actual={manifest_end - manifest_start}, expected={duration}")
                    lower, upper = (parse_dt(x) for x in g.CHRONOLOGICAL_SPLITS[split.lower()])
                    add_check(checks, "manifest_within_chronological_split", lower <= manifest_start < manifest_end <= upper,
                              f"{manifest_start.isoformat()} to {manifest_end.isoformat()}")
                except Exception as exc:
                    manifest_start = manifest_end = None
                    add_check(checks, "manifest_timestamps_valid", False, f"{type(exc).__name__}: {exc}")

                required = {"total_events", "RIP_target", "RIP_actual", "Sorg_target", "Sorg_actual", "Raccount_target", "Raccount_actual"}
                add_check(checks, "manifest_required_measurements", required <= set(manifest), sorted(required - set(manifest)))
                scenario = g.SCENARIOS[record["scenario_id"]]
                add_check(checks, "manifest_org_spread_matches_scenario", manifest.get("Sorg_actual") == scenario["org_spread"],
                          f"actual={manifest.get('Sorg_actual')}, expected={scenario['org_spread']}")
                if manifest.get("total_events") is not None and manifest.get("RIP_target") is not None and manifest.get("RIP_actual") is not None:
                    tol = 1 / max(1, int(manifest["total_events"])) + 1e-10
                    add_check(checks, "manifest_rip_measurement_consistent", abs(float(manifest["RIP_actual"]) - float(manifest["RIP_target"])) <= tol,
                              f"target={manifest['RIP_target']}, actual={manifest['RIP_actual']}, tolerance={tol}")

            parquet_files = sorted(folder.glob("*.parquet"))
            add_check(checks, "parquet_files_present", bool(parquet_files), f"{len(parquet_files)} files")

            if duckdb is None:
                checks.append({"check": "parquet_event_audit", "status": "UNTESTED", "detail": "Install duckdb to inspect Parquet events"})
            elif parquet_files:
                start_offset, capacity = g.SPLIT_IP_ALLOCATIONS[campaign_id]
                observed_offsets = []
                observed_times = []
                observed_campaign_ids = set()
                event_ids = set()
                duplicate_event_ids = []
                total_events = 0
                event_errors = []
                for parquet_path in parquet_files:
                    con = duckdb.connect()
                    try:
                        rows = con.execute(
                            'SELECT "IP Address", "Login Timestamp", campaign_id, campaign_event_id FROM read_parquet(?)',
                            [str(parquet_path)],
                        ).fetchall()
                    except Exception as exc:
                        event_errors.append(f"{parquet_path.name}: {type(exc).__name__}: {exc}")
                        con.close()
                        continue
                    finally:
                        try:
                            con.close()
                        except Exception:
                            pass
                    for ip_value, timestamp, event_campaign_id, event_id in rows:
                        total_events += 1
                        try:
                            offset = int(ipaddress.ip_address(str(ip_value))) - ip_base
                            observed_offsets.append(offset)
                            if not (start_offset <= offset < start_offset + capacity):
                                event_errors.append(f"IP outside reservation: {ip_value} offset={offset}")
                        except Exception as exc:
                            event_errors.append(f"Invalid IP {ip_value}: {exc}")
                        try:
                            stamp = parse_dt(timestamp)
                            observed_times.append(stamp)
                            if manifest_start is not None and manifest_end is not None and not (manifest_start <= stamp < manifest_end):
                                event_errors.append(f"Event timestamp outside manifest window: {stamp.isoformat()}")
                        except Exception as exc:
                            event_errors.append(f"Invalid event timestamp {timestamp}: {exc}")
                        observed_campaign_ids.add(event_campaign_id)
                        if event_campaign_id != campaign_id:
                            event_errors.append(f"Event campaign_id mismatch: {event_campaign_id}")
                        if event_id in event_ids:
                            duplicate_event_ids.append(str(event_id))
                        event_ids.add(event_id)

                record["event_count"] = total_events
                if observed_offsets:
                    record["ip_min_offset"] = min(observed_offsets)
                    record["ip_max_offset"] = max(observed_offsets)
                if observed_times:
                    record["observed_event_start"] = min(observed_times).isoformat()
                    record["observed_event_end"] = max(observed_times).isoformat()
                add_check(checks, "actual_ips_within_reserved_range", not event_errors or not any("IP " in e or "Invalid IP" in e for e in event_errors),
                          f"observed offsets={record['ip_min_offset']}..{record['ip_max_offset']}; reservation={start_offset}..{start_offset + capacity - 1}")
                add_check(checks, "event_campaign_ids_consistent", observed_campaign_ids == {campaign_id}, sorted(str(x) for x in observed_campaign_ids))
                add_check(checks, "event_timestamps_within_manifest_window", not any("timestamp" in e.lower() for e in event_errors),
                          f"observed={record['observed_event_start']}..{record['observed_event_end']}")
                add_check(checks, "event_ids_unique_within_campaign", not duplicate_event_ids, f"duplicates={len(duplicate_event_ids)}")
                if manifest is not None and manifest.get("total_events") is not None:
                    add_check(checks, "event_count_matches_manifest", total_events == int(manifest["total_events"]),
                              f"events={total_events}, manifest={manifest['total_events']}")
                else:
                    checks.append({"check": "event_count_matches_manifest", "status": "UNTESTED", "detail": "Manifest total_events unavailable"})
                add_check(checks, "parquet_read_errors", not any("read_parquet" in e for e in event_errors), event_errors[:5])
            else:
                checks.append({"check": "parquet_event_audit", "status": "UNTESTED", "detail": "No Parquet files available"})

            statuses = [c["status"] for c in checks]
            if "FAIL" in statuses:
                record["status"] = "FAIL"
            elif "UNTESTED" in statuses:
                record["status"] = "INCOMPLETE"
            else:
                record["status"] = "PASS"
            record["failed_checks"] = [c["check"] for c in checks if c["status"] == "FAIL"]
            records.append(record)

    # A directory not corresponding to an expected campaign is also reported.
    actual_dirs = {p.name for p in data_root.iterdir() if p.is_dir() and p.name.endswith(("_TRAIN", "_VAL", "_TEST"))}
    unexpected = sorted(actual_dirs - expected_ids)

    counts = Counter(r["status"] for r in records)
    all_check_counts = Counter(c["status"] for r in records for c in r["checks"])
    summary = {
        "expected_campaigns": len(expected_ids),
        "audited_campaign_records": len(records),
        "campaign_status_counts": dict(counts),
        "check_status_counts": dict(all_check_counts),
        "unexpected_campaign_directories": unexpected,
        "reports_are_read_only": True,
        "campaigns": records,
    }

    json_path = report_dir / "phase5_270_campaign_audit.json"
    csv_path = report_dir / "phase5_270_campaign_audit.csv"
    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    fieldnames = ["campaign_id", "split", "status", "event_count", "scheduled_start", "manifest_start",
                  "observed_event_start", "observed_event_end", "ip_min_offset", "ip_max_offset", "failed_checks"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            row = {k: r.get(k) for k in fieldnames}
            row["failed_checks"] = "; ".join(r["failed_checks"])
            writer.writerow(row)

    print("\n=== CRED BLOCK-FL PHASE 5: 270-CAMPAIGN AUDIT ===")
    print(f"Expected campaigns: {len(expected_ids)}")
    print(f"Campaign statuses: {dict(counts)}")
    print(f"Individual check statuses: {dict(all_check_counts)}")
    print(f"Unexpected campaign directories: {len(unexpected)}")
    print(f"JSON report: {json_path}")
    print(f"CSV report:  {csv_path}")
    print("\nCampaigns requiring attention:")
    for r in records:
        if r["status"] != "PASS":
            print(f"- {r['campaign_id']}: {r['status']}; failed={r['failed_checks']}")
    return 1 if counts.get("FAIL", 0) or unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
