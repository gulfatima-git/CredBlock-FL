from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ORGANIZATIONS_DIR = PROJECT_ROOT / "data" / "organizations"
PHASE5_DIR = PROJECT_ROOT / "data" / "phase5"
SYNTHETIC_EVENTS_DIR = PHASE5_DIR / "synthetic_events"
EVENT_STREAMS_DIR = PHASE5_DIR / "event_streams"



def _columns_for_parquet(con: duckdb.DuckDBPyConnection, path: str) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}')"
        ).fetchall()
    }



def _resolve_success_column(columns: set[str]) -> str:
    for candidate in ("LoginSuccessful", "Login Successful"):
        if candidate in columns:
            return candidate
    raise ValueError(
        "Could not resolve login-success column. Expected "
        "'LoginSuccessful' or 'Login Successful'."
    )



def build_local_event_stream(
    org_id: int,
    start: datetime,
    end: datetime,
    campaign_id: Optional[str] = None,
    save: bool = True,
):
    """
    Build one organization's chronological authentication-event stream.

    Original local authentication records are combined with that
    organization's synthetic campaign records, when available.  The output is
    deliberately narrow: it contains exactly the fields needed by the temporal
    graph updater and evaluation layer.

    The interval is [start, end): start-inclusive and end-exclusive.
    """
    if end <= start:
        raise ValueError("end must be later than start")

    org_name = f"Org{org_id}"
    original_glob = (
        ORGANIZATIONS_DIR
        / f"organization={org_name}"
        / "*.parquet"
    ).as_posix()

    con = duckdb.connect()

    try:
        original_columns = _columns_for_parquet(con, original_glob)
        original_success = _resolve_success_column(original_columns)

        start_literal = start.strftime("%Y-%m-%d %H:%M:%S.%f")
        end_literal = end.strftime("%Y-%m-%d %H:%M:%S.%f")

        original_sql = f"""
            SELECT
                '{org_name}'::VARCHAR AS organization,
                \"Login Timestamp\"::TIMESTAMP AS \"Login Timestamp\",
                \"User ID\"::BIGINT AS \"User ID\",
                \"IP Address\"::VARCHAR AS \"IP Address\",
                \"{original_success}\"::BOOLEAN AS \"LoginSuccessful\",
                FALSE::BOOLEAN AS is_synthetic,
                0::INTEGER AS credential_stuffing_label,
                NULL::VARCHAR AS scenario_id,
                NULL::VARCHAR AS campaign_id,
                NULL::VARCHAR AS synthetic_credential_id,
                NULL::BOOLEAN AS is_reused_credential,
                NULL::VARCHAR AS campaign_event_id
            FROM read_parquet('{original_glob}')
            WHERE \"Login Timestamp\" >= TIMESTAMP '{start_literal}'
              AND \"Login Timestamp\" < TIMESTAMP '{end_literal}'
        """

        synthetic_sql = None
        synthetic_path = None

        if campaign_id:
            candidate = (
                SYNTHETIC_EVENTS_DIR
                / campaign_id
                / f"{org_name}.parquet"
            )

            if candidate.exists():
                synthetic_path = candidate
                synthetic_columns = _columns_for_parquet(
                    con,
                    candidate.as_posix(),
                )
                synthetic_success = _resolve_success_column(synthetic_columns)

                synthetic_sql = f"""
                    SELECT
                        organization::VARCHAR AS organization,
                        \"Login Timestamp\"::TIMESTAMP AS \"Login Timestamp\",
                        \"User ID\"::BIGINT AS \"User ID\",
                        \"IP Address\"::VARCHAR AS \"IP Address\",
                        \"{synthetic_success}\"::BOOLEAN AS \"LoginSuccessful\",
                        COALESCE(is_synthetic, TRUE)::BOOLEAN AS is_synthetic,
                        COALESCE(credential_stuffing_label, 1)::INTEGER
                            AS credential_stuffing_label,
                        scenario_id::VARCHAR AS scenario_id,
                        campaign_id::VARCHAR AS campaign_id,
                        synthetic_credential_id::VARCHAR
                            AS synthetic_credential_id,
                        is_reused_credential::BOOLEAN
                            AS is_reused_credential,
                        campaign_event_id::VARCHAR AS campaign_event_id
                    FROM read_parquet('{candidate.as_posix()}')
                    WHERE \"Login Timestamp\" >= TIMESTAMP '{start_literal}'
                      AND \"Login Timestamp\" < TIMESTAMP '{end_literal}'
                """

        if synthetic_sql:
            union_sql = f"({original_sql}) UNION ALL ({synthetic_sql})"
        else:
            union_sql = original_sql

        stream_sql = f"""
            SELECT *
            FROM ({union_sql}) combined_events
            ORDER BY \"Login Timestamp\", is_synthetic, \"User ID\", \"IP Address\"
        """

        stream = con.execute(stream_sql).df()

        if len(stream) > 1 and not stream["Login Timestamp"].is_monotonic_increasing:
            raise ValueError("Chronological stream ordering check failed.")

        original_count = int((~stream["is_synthetic"]).sum()) if len(stream) else 0
        synthetic_count = int(stream["is_synthetic"].sum()) if len(stream) else 0

        print("=" * 60)
        print(f"{org_name} CHRONOLOGICAL EVENT STREAM")
        print("=" * 60)
        print("Window:", start, "->", end)
        print("Original events:", original_count)
        print("Synthetic events:", synthetic_count)
        print("Total events:", len(stream))
        print("Chronological ordering: True")

        if campaign_id:
            if synthetic_path:
                print("Synthetic campaign source:", synthetic_path)
            else:
                print(
                    "Synthetic campaign source: none for this organization "
                    f"({campaign_id})"
                )

        output_path = None
        if save:
            output_scope = campaign_id or "background_only"
            output_dir = EVENT_STREAMS_DIR / output_scope
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{org_name}.parquet"

            con.register("event_stream_df", stream)
            con.execute(
                f"COPY event_stream_df TO '{output_path.as_posix()}' "
                "(FORMAT PARQUET)"
            )
            con.unregister("event_stream_df")

            print("Saved:", output_path)

        return stream, output_path

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Create a chronological local authentication stream by combining "
            "original and synthetic events."
        )
    )

    parser.add_argument(
        "--org-id",
        type=int,
        required=True,
        choices=[1, 2, 3, 4, 5],
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Inclusive ISO start timestamp.",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Exclusive ISO end timestamp.",
    )
    parser.add_argument(
        "--campaign-id",
        default=None,
        help="Optional synthetic campaign realization ID.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Verify the stream without writing a Parquet output.",
    )

    args = parser.parse_args()

    build_local_event_stream(
        org_id=args.org_id,
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        campaign_id=args.campaign_id,
        save=not args.no_save,
    )
