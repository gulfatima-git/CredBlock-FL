import argparse
from pathlib import Path
import duckdb


def load_organization(org_id):
    org_name = f"Org{org_id}"

    project_root = Path(__file__).resolve().parents[2]

    data_path = (
        project_root
        / "data"
        / "organizations"
        / f"organization={org_name}"
        / "*.parquet"
    )

    return org_name, data_path


def show_local_statistics(org_name, data_path):

    data_path = data_path.as_posix()

    result = duckdb.sql(f"""
        SELECT
            COUNT(*) AS login_records,
            COUNT(DISTINCT "User ID") AS unique_users,

            SUM(
                CASE WHEN "Login Successful" = TRUE
                THEN 1 ELSE 0 END
            ) AS successful_logins,

            SUM(
                CASE WHEN "Login Successful" = FALSE
                THEN 1 ELSE 0 END
            ) AS failed_logins,

            SUM(
                CASE WHEN "Is Attack IP" = TRUE
                THEN 1 ELSE 0 END
            ) AS attack_ip_logins,

            SUM(
                CASE WHEN "Is Account Takeover" = TRUE
                THEN 1 ELSE 0 END
            ) AS account_takeover_logins

        FROM read_parquet('{data_path}')
    """).fetchone()

    print(f"\n--- {org_name} LOCAL DATA ---")
    print(f"Login records: {result[0]:,}")
    print(f"Unique users: {result[1]:,}")
    print(f"Successful logins: {result[2]:,}")
    print(f"Failed logins: {result[3]:,}")
    print(f"Attack-IP logins: {result[4]:,}")
    print(f"Account-takeover logins: {result[5]:,}")


def main():

    parser = argparse.ArgumentParser(
        description="CredBlock-FL Organization Client"
    )

    parser.add_argument(
        "--org-id",
        type=int,
        required=True,
        choices=[1, 2, 3, 4, 5]
    )

    args = parser.parse_args()

    org_name, data_path = load_organization(args.org_id)

    print(f"Starting {org_name} client...")
    print(f"Local data source: {data_path}")

    show_local_statistics(org_name, data_path)


if __name__ == "__main__":
    main()