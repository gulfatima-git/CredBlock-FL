"""
CredBlock-FL Phase 5 master validator.

Run from the CredBlock-FL project root:
    python validate_phase5.py

Read-only with respect to campaign data. It runs the existing campaign audit,
then performs additional Parquet schema, data-quality, cross-campaign IP,
and statistical checks. It writes reports only under reports/.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("ERROR: DuckDB is required. Install it with: pip install duckdb")
    raise SystemExit(2)

EXPECTED_COLUMNS = {
    "organization": "VARCHAR",
    "User ID": "BIGINT",
    "Login Timestamp": "TIMESTAMP",
    "LoginSuccessful": "BOOLEAN",
    "synthetic_credential_id": "VARCHAR",
    "is_reused_credential": "BOOLEAN",
    "is_synthetic": "BOOLEAN",
    "credential_stuffing_label": "BIGINT",
    "scenario_id": "VARCHAR",
    "campaign_id": "VARCHAR",
    "IP Address": "VARCHAR",
    "campaign_event_id": "VARCHAR",
}

REQUIRED_NON_NULL = [
    "organization", "User ID", "Login Timestamp", "LoginSuccessful",
    "synthetic_credential_id", "is_synthetic", "credential_stuffing_label",
    "scenario_id", "campaign_id", "IP Address", "campaign_event_id",
]


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def add_check(checks: list, name: str, passed: bool, detail="") -> None:
    checks.append({
        "check": name,
        "status": "PASS" if passed else "FAIL",
        "detail": str(detail),
    })


def main() -> int:
    root = Path.cwd()
    data_root = root / "data" / "phase5" / "synthetic_events"
    report_dir = root / "reports"
    audit_script = root / "audit_270_campaigns.py"
    audit_json = report_dir / "phase5_270_campaign_audit.json"

    report_dir.mkdir(parents=True, exist_ok=True)

    if not data_root.is_dir():
        print(f"ERROR: Campaign data directory not found: {data_root}")
        return 2
    if not audit_script.is_file():
        print(f"ERROR: Existing audit script not found: {audit_script}")
        return 2

    print("=== CRED BLOCK-FL PHASE 5 MASTER VALIDATION ===")
    print("\n[1/5] Running the existing 270-campaign audit...")

    audit_result = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=root,
        text=True,
        capture_output=True,
    )
    print(audit_result.stdout)
    if audit_result.stderr:
        print("Existing audit warnings/errors:")
        print(audit_result.stderr)

    if not audit_json.is_file():
        print("ERROR: Existing audit did not produce its JSON report.")
        return 2

    audit = json.loads(audit_json.read_text(encoding="utf-8"))
    campaign_records = audit.get("campaigns", [])
    checks: list[dict] = []
    campaign_stats: list[dict] = []
    split_totals: dict[str, dict] = {}
    global_ip_owners: dict[str, set[str]] = {}
    global_event_ids: set[str] = set()
    duplicate_event_ids_global: list[str] = []

    print("[2/5] Checking Parquet schema and campaign-level data quality...")

    for index, record in enumerate(campaign_records, start=1):
        campaign_id = record["campaign_id"]
        campaign_dir = data_root / campaign_id
        parquet_files = sorted(campaign_dir.glob("*.parquet"))
        if not parquet_files:
            add_check(checks, f"{campaign_id}:parquet_present", False, "No Parquet files")
            continue

        con = duckdb.connect()
        try:
            file_list = [str(p) for p in parquet_files]
            schema_rows = con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)",
                [file_list],
            ).fetchall()
            actual_schema = {row[0]: row[1].upper() for row in schema_rows}

            missing_columns = sorted(set(EXPECTED_COLUMNS) - set(actual_schema))
            add_check(
                checks, f"{campaign_id}:required_schema",
                not missing_columns,
                f"Missing columns: {missing_columns}" if missing_columns else "All expected columns present",
            )

            wrong_types = {
                name: {"expected": expected, "actual": actual_schema.get(name)}
                for name, expected in EXPECTED_COLUMNS.items()
                if name in actual_schema and actual_schema[name] != expected
            }
            add_check(
                checks, f"{campaign_id}:schema_types", not wrong_types,
                wrong_types if wrong_types else "Expected data types confirmed",
            )
            if missing_columns:
                continue

            table = "read_parquet(?)"
            total = con.execute(
                f"SELECT COUNT(*) FROM {table}", [file_list]
            ).fetchone()[0]

            null_counts = {}
            for column in REQUIRED_NON_NULL:
                null_counts[column] = con.execute(
                    f'SELECT COUNT(*) FROM {table} WHERE "{column}" IS NULL',
                    [file_list],
                ).fetchone()[0]
            null_columns = {k: v for k, v in null_counts.items() if v}
            add_check(
                checks, f"{campaign_id}:required_fields_non_null",
                not null_columns,
                null_columns if null_columns else "No nulls in required fields",
            )

            campaign_values = con.execute(
                f"SELECT DISTINCT campaign_id FROM {table}", [file_list]
            ).fetchall()
            campaign_values = {row[0] for row in campaign_values}
            add_check(
                checks, f"{campaign_id}:event_campaign_id",
                campaign_values == {campaign_id},
                sorted(str(x) for x in campaign_values),
            )

            scenario_expected = record.get("scenario_id")
            scenario_values = con.execute(
                f"SELECT DISTINCT scenario_id FROM {table}", [file_list]
            ).fetchall()
            scenario_values = {row[0] for row in scenario_values}
            add_check(
                checks, f"{campaign_id}:event_scenario_id",
                scenario_values == {scenario_expected},
                sorted(str(x) for x in scenario_values),
            )

            synthetic_values = con.execute(
                f"SELECT DISTINCT is_synthetic FROM {table}", [file_list]
            ).fetchall()
            synthetic_values = {row[0] for row in synthetic_values}
            add_check(
                checks, f"{campaign_id}:synthetic_flag",
                synthetic_values == {True},
                sorted(str(x) for x in synthetic_values),
            )

            invalid_labels = con.execute(
                f"""SELECT COUNT(*) FROM {table}
                    WHERE credential_stuffing_label NOT IN (0, 1)""",
                [file_list],
            ).fetchone()[0]
            add_check(
                checks, f"{campaign_id}:binary_labels",
                invalid_labels == 0, f"Invalid label rows: {invalid_labels}",
            )

            invalid_boolean_values = con.execute(
                f"""SELECT COUNT(*) FROM {table}
                    WHERE LoginSuccessful NOT IN (TRUE, FALSE)
                       OR is_reused_credential NOT IN (TRUE, FALSE)
                       OR is_synthetic NOT IN (TRUE, FALSE)""",
                [file_list],
            ).fetchone()[0]
            add_check(
                checks, f"{campaign_id}:boolean_fields",
                invalid_boolean_values == 0,
                f"Invalid boolean rows: {invalid_boolean_values}",
            )

            duplicate_ids = con.execute(
                f"""SELECT COUNT(*) FROM (
                    SELECT campaign_event_id FROM {table}
                    GROUP BY campaign_event_id HAVING COUNT(*) > 1
                )""",
                [file_list],
            ).fetchone()[0]
            add_check(
                checks, f"{campaign_id}:unique_event_ids",
                duplicate_ids == 0, f"Duplicated event IDs: {duplicate_ids}",
            )

            event_ids = con.execute(
                f"SELECT campaign_event_id FROM {table}", [file_list]
            ).fetchall()
            for (event_id,) in event_ids:
                if event_id in global_event_ids:
                    duplicate_event_ids_global.append(str(event_id))
                global_event_ids.add(event_id)

            ip_rows = con.execute(
                f"""SELECT DISTINCT "IP Address" FROM {table}
                    WHERE "IP Address" IS NOT NULL""",
                [file_list],
            ).fetchall()
            for (ip_address,) in ip_rows:
                global_ip_owners.setdefault(str(ip_address), set()).add(campaign_id)

            stats = con.execute(
                f"""SELECT
                    COUNT(*) AS event_count,
                    SUM(CASE WHEN LoginSuccessful THEN 1 ELSE 0 END),
                    SUM(CASE WHEN NOT LoginSuccessful THEN 1 ELSE 0 END),
                    COUNT(DISTINCT "IP Address"),
                    COUNT(DISTINCT "User ID"),
                    COUNT(DISTINCT synthetic_credential_id),
                    COUNT(DISTINCT organization),
                    SUM(CASE WHEN is_reused_credential THEN 1 ELSE 0 END),
                    SUM(CASE WHEN credential_stuffing_label = 1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN credential_stuffing_label = 0 THEN 1 ELSE 0 END),
                    MIN("Login Timestamp"),
                    MAX("Login Timestamp")
                FROM {table}""",
                [file_list],
            ).fetchone()

            (
                event_count, successes, failures, unique_ips, unique_users,
                unique_credentials, org_count, reused_events, label_1,
                label_0, first_event, last_event
            ) = stats

            event_count = int(event_count or 0)
            successes = int(successes or 0)
            failures = int(failures or 0)
            campaign_stat = {
                "campaign_id": campaign_id,
                "split": record.get("split"),
                "scenario_id": scenario_expected,
                "event_count": event_count,
                "successful_events": successes,
                "failed_events": failures,
                "success_rate": successes / event_count if event_count else None,
                "failure_rate": failures / event_count if event_count else None,
                "unique_ips": int(unique_ips or 0),
                "unique_users": int(unique_users or 0),
                "unique_credentials": int(unique_credentials or 0),
                "organization_count": int(org_count or 0),
                "reused_credential_events": int(reused_events or 0),
                "label_1_events": int(label_1 or 0),
                "label_0_events": int(label_0 or 0),
                "events_per_minute": event_count / 60,
                "first_event": first_event.isoformat() if first_event else None,
                "last_event": last_event.isoformat() if last_event else None,
            }
            campaign_stats.append(campaign_stat)

            split = str(record.get("split", "UNKNOWN")).upper()
            bucket = split_totals.setdefault(
                split,
                {
                    "campaigns": 0, "events": 0,
                    "successful_events": 0, "failed_events": 0,
                    "unique_ip_observations": 0, "unique_user_observations": 0,
                },
            )
            bucket["campaigns"] += 1
            bucket["events"] += event_count
            bucket["successful_events"] += successes
            bucket["failed_events"] += failures
            bucket["unique_ip_observations"] += int(unique_ips or 0)
            bucket["unique_user_observations"] += int(unique_users or 0)

            add_check(
                checks, f"{campaign_id}:event_count_positive",
                event_count > 0, f"Events: {event_count}",
            )
            add_check(
                checks, f"{campaign_id}:success_failure_total",
                successes + failures == event_count,
                f"success={successes}, failure={failures}, total={event_count}",
            )

        except Exception as exc:
            add_check(
                checks, f"{campaign_id}:parquet_validation", False,
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            con.close()

        if index % 30 == 0:
            print(f"  Processed {index}/{len(campaign_records)} campaign records")

    print("[3/5] Checking cross-campaign IP and event-ID reuse...")

    overlapping_ips = {
        ip: sorted(owners)
        for ip, owners in global_ip_owners.items()
        if len(owners) > 1
    }
    add_check(
        checks, "dataset:ip_addresses_not_reused_across_campaigns",
        not overlapping_ips, f"Overlapping IPs: {len(overlapping_ips)}",
    )
    add_check(
        checks, "dataset:event_ids_unique_across_campaigns",
        not duplicate_event_ids_global,
        f"Cross-campaign duplicate event IDs: {len(duplicate_event_ids_global)}",
    )

    print("[4/5] Summarizing split distributions...")

    for values in split_totals.values():
        count = values["events"]
        values["success_rate"] = values["successful_events"] / count if count else None
        values["failure_rate"] = values["failed_events"] / count if count else None

    expected_splits = {"TRAIN", "VAL", "TEST"}
    add_check(
        checks, "dataset:all_three_splits_present",
        set(split_totals) == expected_splits, sorted(split_totals),
    )

    audit_statuses = Counter(
        record.get("status", "UNKNOWN") for record in campaign_records
    )
    add_check(
        checks, "dataset:existing_270_campaign_audit_passed",
        len(campaign_records) == 270 and audit_statuses == Counter({"PASS": 270}),
        dict(audit_statuses),
    )

    print("[5/5] Writing reports...")

    check_counts = Counter(item["status"] for item in checks)
    overall_pass = (
        check_counts.get("FAIL", 0) == 0
        and len(campaign_records) == 270
        and audit_statuses == Counter({"PASS": 270})
    )

    report = {
        "project": "CredBlock-FL",
        "phase": 5,
        "validation_timestamp": datetime.now().isoformat(timespec="seconds"),
        "read_only_campaign_data": True,
        "overall_status": "PASS" if overall_pass else "REVIEW_REQUIRED",
        "existing_audit_status": dict(audit_statuses),
        "additional_check_status": dict(check_counts),
        "additional_checks": checks,
        "split_statistics": split_totals,
        "campaign_statistics": campaign_stats,
        "cross_campaign_ip_overlaps": overlapping_ips,
        "cross_campaign_duplicate_event_ids": duplicate_event_ids_global[:100],
        "notes": [
            "Label values are counted as 0 and 1; their semantic meaning is not inferred.",
            "Split unique-IP and unique-user observations are sums of campaign-level counts, not split-wide distinct counts.",
            "The validator does not modify campaign Parquet files or manifests.",
        ],
    }

    json_path = report_dir / "phase5_validation_report.json"
    stats_path = report_dir / "phase5_statistics.json"
    csv_path = report_dir / "phase5_campaign_statistics.csv"
    checks_path = report_dir / "phase5_validation_checks.csv"
    txt_path = report_dir / "phase5_validation_summary.txt"

    write_json(json_path, report)
    write_json(stats_path, {
        "split_statistics": split_totals,
        "campaign_statistics": campaign_stats,
    })

    if campaign_stats:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(campaign_stats[0]))
            writer.writeheader()
            writer.writerows(campaign_stats)

    with checks_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "status", "detail"])
        writer.writeheader()
        writer.writerows(checks)

    lines = [
        "CRED BLOCK-FL PHASE 5 VALIDATION SUMMARY",
        "=" * 48,
        f"Overall status: {report['overall_status']}",
        f"Campaign records audited: {len(campaign_records)}",
        f"Existing audit statuses: {dict(audit_statuses)}",
        f"Additional checks: {dict(check_counts)}",
        "",
        "Split statistics:",
    ]
    for split, values in sorted(split_totals.items()):
        lines.append(
            f"{split}: campaigns={values['campaigns']}, events={values['events']}, "
            f"successes={values['successful_events']}, failures={values['failed_events']}, "
            f"success_rate={values['success_rate']}"
        )
    lines.extend([
        "", "Reports:",
        str(json_path), str(stats_path), str(csv_path), str(checks_path), str(txt_path),
        "", "Campaign data was not modified.",
    ])
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n=== PHASE 5 MASTER VALIDATION RESULT ===")
    print("Overall status:", report["overall_status"])
    print("Existing audit:", dict(audit_statuses))
    print("Additional checks:", dict(check_counts))
    print("Reports:")
    for output_path in (json_path, stats_path, csv_path, checks_path, txt_path):
        print(" ", output_path)

    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
