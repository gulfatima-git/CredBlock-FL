from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
import torch
from torch_geometric.data import Data


# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ORGANIZATIONS_DIR = PROJECT_ROOT / "data" / "organizations"
TEMPORAL_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed_temporal"


# ---------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------


def _get_parquet_columns(con: duckdb.DuckDBPyConnection, parquet_path: str) -> set[str]:
    """Return the column names exposed by a Parquet source."""
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{parquet_path}')"
    ).fetchall()
    return {row[0] for row in rows}



def _resolve_column(columns: set[str], *candidates: str) -> str:
    """Resolve one logical field across known source-schema variants."""
    for candidate in candidates:
        if candidate in columns:
            return candidate

    raise ValueError(
        "None of the expected columns were found. "
        f"Expected one of: {', '.join(candidates)}"
    )



def _sql_timestamp(value: datetime) -> str:
    """Format a Python datetime for a DuckDB TIMESTAMP literal."""
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")



def _prepare_auth_view(
    con: duckdb.DuckDBPyConnection,
    parquet_path: str,
    cutoff: Optional[datetime],
) -> tuple[datetime, str]:
    """
    Create a canonical local authentication view.

    The organizational files seen during development have used both
    `Login Successful` and `LoginSuccessful`.  The rest of the graph code
    therefore consumes the canonical alias `login_successful` rather than
    depending on one physical spelling.

    If ``cutoff`` is supplied, only events available at or before that time
    are exposed.  This gives us the graph state G(t) required by the temporal
    CredBlock-FL design and prevents future-data leakage.
    """
    columns = _get_parquet_columns(con, parquet_path)

    user_col = _resolve_column(columns, "User ID")
    ip_col = _resolve_column(columns, "IP Address")
    timestamp_col = _resolve_column(columns, "Login Timestamp")
    success_col = _resolve_column(
        columns,
        "LoginSuccessful",
        "Login Successful",
    )

    if cutoff is None:
        max_timestamp = con.execute(
            f"""
            SELECT MAX(\"{timestamp_col}\")
            FROM read_parquet('{parquet_path}')
            """
        ).fetchone()[0]

        if max_timestamp is None:
            raise ValueError("The organization dataset contains no authentication events.")

        cutoff = max_timestamp

    cutoff_literal = _sql_timestamp(cutoff)

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW auth_events AS
        SELECT
            \"{user_col}\" AS user_id,
            \"{ip_col}\" AS ip_address,
            \"{timestamp_col}\" AS login_timestamp,
            \"{success_col}\" AS login_successful
        FROM read_parquet('{parquet_path}')
        WHERE \"{timestamp_col}\" <= TIMESTAMP '{cutoff_literal}'
        """
    )

    event_count = con.execute(
        "SELECT COUNT(*) FROM auth_events"
    ).fetchone()[0]

    if event_count == 0:
        raise ValueError(
            f"No authentication events exist at or before cutoff {cutoff_literal}."
        )

    return cutoff, success_col


# ---------------------------------------------------------
# Main graph-building function
# ---------------------------------------------------------


def build_temporal_graph_state(
    org_id: int,
    cutoff: Optional[datetime] = None,
    recent_window_minutes: int = 10,
    save_artifacts: bool = True,
):
    """
    Build one organization's local temporal User-IP graph state G(t).

    The graph is cumulative up to ``cutoff`` while the two short-term model
    features are computed only from the most recent window ending at that
    cutoff.  Calling the same logic at later cutoffs represents the same
    persistent graph as it evolves over time; the later incremental updater
    can optimize this without changing feature semantics.

    Parameters
    ----------
    org_id:
        Organization number from 1 to 5.
    cutoff:
        Latest authentication timestamp allowed into the graph.  ``None``
        means the latest timestamp present in that organization's dataset.
    recent_window_minutes:
        Width of the short-term activity window used by the live detector.
    save_artifacts:
        Whether to persist tensors/mappings/state artifacts to disk.
    """

    if recent_window_minutes <= 0:
        raise ValueError("recent_window_minutes must be greater than zero.")

    org_name = f"Org{org_id}"

    input_path = (
        ORGANIZATIONS_DIR
        / f"organization={org_name}"
        / "*.parquet"
    )

    output_dir = TEMPORAL_PROCESSED_DIR / org_name.lower()
    if save_artifacts:
        output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"Building temporal graph state for {org_name}")
    print("=" * 60)
    print("Input:", input_path)

    con = duckdb.connect()
    parquet_path = str(input_path).replace("\\", "/")

    try:
        cutoff, physical_success_column = _prepare_auth_view(
            con=con,
            parquet_path=parquet_path,
            cutoff=cutoff,
        )

        recent_window_start = cutoff - timedelta(minutes=recent_window_minutes)
        recent_start_literal = _sql_timestamp(recent_window_start)
        cutoff_literal = _sql_timestamp(cutoff)

        print("Graph cutoff:", cutoff)
        print(
            f"Recent activity window: {recent_window_start} -> {cutoff} "
            f"({recent_window_minutes} minutes)"
        )
        print("Resolved login-success column:", physical_success_column)

        # =====================================================
        # 1. USER NODE MAPPING
        # =====================================================

        print("\n[1/10] Creating user-node mapping...")

        users = con.execute(
            """
            SELECT DISTINCT user_id AS "User ID"
            FROM auth_events
            ORDER BY user_id
            """
        ).df()

        users["user_node_id"] = np.arange(
            len(users),
            dtype=np.int64,
        )

        num_users = len(users)
        print("Users:", num_users)

        # =====================================================
        # 2. IP NODE MAPPING
        # =====================================================

        print("\n[2/10] Creating IP-node mapping...")

        ips = con.execute(
            """
            SELECT DISTINCT ip_address AS "IP Address"
            FROM auth_events
            ORDER BY ip_address
            """
        ).df()

        ips["ip_node_id"] = np.arange(
            len(ips),
            dtype=np.int64,
        )

        # Shift IP IDs so User and IP node IDs do not overlap.
        # For a specific G(t), the export is contiguous and deterministic.
        ips["global_ip_node_id"] = ips["ip_node_id"] + num_users

        num_ips = len(ips)
        num_nodes = num_users + num_ips

        print("IPs:", num_ips)
        print("Total nodes:", num_nodes)

        con.register("users_mapping", users)
        con.register("ips_mapping", ips)

        # =====================================================
        # 3. STRUCTURAL USER-IP EDGES
        # =====================================================

        print("\n[3/10] Creating structural User-IP edges...")

        edges = con.execute(
            """
            SELECT DISTINCT
                u.user_node_id,
                i.global_ip_node_id AS ip_node_id
            FROM auth_events d
            JOIN users_mapping u
                ON d.user_id = u."User ID"
            JOIN ips_mapping i
                ON d.ip_address = i."IP Address"
            """
        ).df()

        edges["user_node_id"] = edges["user_node_id"].astype(np.int64)
        edges["ip_node_id"] = edges["ip_node_id"].astype(np.int64)

        print("Structural edges:", len(edges))

        # =====================================================
        # 4. CUMULATIVE EDGE STATE
        # =====================================================

        print("\n[4/10] Creating cumulative edge state...")

        edge_features = con.execute(
            """
            SELECT
                u.user_node_id,
                i.global_ip_node_id AS ip_node_id,
                COUNT(*) AS total_interactions,
                SUM(CASE WHEN d.login_successful = TRUE THEN 1 ELSE 0 END)
                    AS successful_interactions,
                SUM(CASE WHEN d.login_successful = FALSE THEN 1 ELSE 0 END)
                    AS failed_interactions,
                SUM(CASE WHEN d.login_successful = FALSE THEN 1 ELSE 0 END)::DOUBLE
                    / COUNT(*) AS failure_ratio,
                MIN(d.login_timestamp) AS first_seen,
                MAX(d.login_timestamp) AS last_seen
            FROM auth_events d
            JOIN users_mapping u
                ON d.user_id = u."User ID"
            JOIN ips_mapping i
                ON d.ip_address = i."IP Address"
            GROUP BY
                u.user_node_id,
                i.global_ip_node_id
            """
        ).df()

        # =====================================================
        # 5. CURRENT 10-MINUTE EDGE FEATURES
        # =====================================================

        print("\n[5/10] Creating current temporal edge features...")

        temporal_edges = con.execute(
            f"""
            SELECT
                u.user_node_id,
                i.global_ip_node_id AS ip_node_id,
                COUNT(*) AS recent_interactions_{recent_window_minutes}min,
                SUM(CASE WHEN d.login_successful = FALSE THEN 1 ELSE 0 END)
                    AS recent_failed_interactions_{recent_window_minutes}min
            FROM auth_events d
            JOIN users_mapping u
                ON d.user_id = u."User ID"
            JOIN ips_mapping i
                ON d.ip_address = i."IP Address"
            WHERE d.login_timestamp > TIMESTAMP '{recent_start_literal}'
              AND d.login_timestamp <= TIMESTAMP '{cutoff_literal}'
            GROUP BY
                u.user_node_id,
                i.global_ip_node_id
            """
        ).df()

        edge_features = edge_features.merge(
            temporal_edges,
            on=["user_node_id", "ip_node_id"],
            how="left",
        )

        recent_edge_columns = [
            f"recent_interactions_{recent_window_minutes}min",
            f"recent_failed_interactions_{recent_window_minutes}min",
        ]
        edge_features[recent_edge_columns] = edge_features[
            recent_edge_columns
        ].fillna(0)

        edge_features["relationship_duration_hours"] = (
            (edge_features["last_seen"] - edge_features["first_seen"]).dt.total_seconds()
            / 3600
        )

        print("Edge-state rows:", len(edge_features))

        # =====================================================
        # 6. USER NODE FEATURES
        # =====================================================

        print("\n[6/10] Creating User-node state features...")

        user_features = con.execute(
            f"""
            WITH cumulative AS (
                SELECT
                    u.user_node_id,
                    COUNT(*) AS total_logins,
                    SUM(CASE WHEN d.login_successful = TRUE THEN 1 ELSE 0 END)
                        AS successful_logins,
                    SUM(CASE WHEN d.login_successful = FALSE THEN 1 ELSE 0 END)
                        AS failed_logins,
                    COUNT(DISTINCT d.ip_address) AS distinct_ips
                FROM auth_events d
                JOIN users_mapping u
                    ON d.user_id = u."User ID"
                GROUP BY u.user_node_id
            ),
            recent AS (
                SELECT
                    u.user_node_id,
                    COUNT(*) AS recent_logins_{recent_window_minutes}min,
                    COUNT(DISTINCT d.ip_address)
                        AS recent_distinct_ips_{recent_window_minutes}min
                FROM auth_events d
                JOIN users_mapping u
                    ON d.user_id = u."User ID"
                WHERE d.login_timestamp > TIMESTAMP '{recent_start_literal}'
                  AND d.login_timestamp <= TIMESTAMP '{cutoff_literal}'
                GROUP BY u.user_node_id
            )
            SELECT
                c.user_node_id,
                c.total_logins,
                c.successful_logins,
                c.failed_logins,
                c.failed_logins::DOUBLE / c.total_logins AS failure_ratio,
                c.distinct_ips,
                COALESCE(r.recent_logins_{recent_window_minutes}min, 0)
                    AS recent_logins_{recent_window_minutes}min,
                COALESCE(r.recent_distinct_ips_{recent_window_minutes}min, 0)
                    AS recent_distinct_ips_{recent_window_minutes}min
            FROM cumulative c
            LEFT JOIN recent r
                ON c.user_node_id = r.user_node_id
            ORDER BY c.user_node_id
            """
        ).df()

        print("User feature rows:", len(user_features))

        # =====================================================
        # 7. IP NODE FEATURES
        # =====================================================

        print("\n[7/10] Creating IP-node state features...")

        ip_features = con.execute(
            f"""
            WITH cumulative AS (
                SELECT
                    i.global_ip_node_id AS ip_node_id,
                    COUNT(*) AS total_logins,
                    SUM(CASE WHEN d.login_successful = TRUE THEN 1 ELSE 0 END)
                        AS successful_logins,
                    SUM(CASE WHEN d.login_successful = FALSE THEN 1 ELSE 0 END)
                        AS failed_logins,
                    COUNT(DISTINCT d.user_id) AS distinct_users
                FROM auth_events d
                JOIN ips_mapping i
                    ON d.ip_address = i."IP Address"
                GROUP BY i.global_ip_node_id
            ),
            recent AS (
                SELECT
                    i.global_ip_node_id AS ip_node_id,
                    COUNT(*) AS recent_logins_{recent_window_minutes}min,
                    COUNT(DISTINCT d.user_id)
                        AS recent_distinct_users_{recent_window_minutes}min
                FROM auth_events d
                JOIN ips_mapping i
                    ON d.ip_address = i."IP Address"
                WHERE d.login_timestamp > TIMESTAMP '{recent_start_literal}'
                  AND d.login_timestamp <= TIMESTAMP '{cutoff_literal}'
                GROUP BY i.global_ip_node_id
            )
            SELECT
                c.ip_node_id,
                c.total_logins,
                c.successful_logins,
                c.failed_logins,
                c.failed_logins::DOUBLE / c.total_logins AS failure_ratio,
                c.distinct_users,
                COALESCE(r.recent_logins_{recent_window_minutes}min, 0)
                    AS recent_logins_{recent_window_minutes}min,
                COALESCE(r.recent_distinct_users_{recent_window_minutes}min, 0)
                    AS recent_distinct_users_{recent_window_minutes}min
            FROM cumulative c
            LEFT JOIN recent r
                ON c.ip_node_id = r.ip_node_id
            ORDER BY c.ip_node_id
            """
        ).df()

        print("IP feature rows:", len(ip_features))

        # =====================================================
        # 8. COMBINE USER + IP NODE FEATURES
        # =====================================================

        print("\n[8/10] Combining node features...")

        recent_logins_col = f"recent_logins_{recent_window_minutes}min"
        user_recent_neighbors_col = (
            f"recent_distinct_ips_{recent_window_minutes}min"
        )
        ip_recent_neighbors_col = (
            f"recent_distinct_users_{recent_window_minutes}min"
        )
        combined_recent_neighbors_col = (
            f"recent_distinct_neighbors_{recent_window_minutes}min"
        )

        user_nodes = user_features.rename(
            columns={
                "user_node_id": "node_id",
                "distinct_ips": "distinct_neighbors",
                user_recent_neighbors_col: combined_recent_neighbors_col,
            }
        )
        user_nodes["node_type"] = 0

        ip_nodes = ip_features.rename(
            columns={
                "ip_node_id": "node_id",
                "distinct_users": "distinct_neighbors",
                ip_recent_neighbors_col: combined_recent_neighbors_col,
            }
        )
        ip_nodes["node_type"] = 1

        node_features = pd.concat(
            [user_nodes, ip_nodes],
            ignore_index=True,
        )
        node_features = node_features.sort_values("node_id").reset_index(drop=True)

        # =====================================================
        # 9. FEATURE TRANSFORMATION
        # =====================================================

        print("\n[9/10] Transforming model features...")

        count_features = [
            "total_logins",
            "successful_logins",
            "failed_logins",
            "distinct_neighbors",
            recent_logins_col,
            combined_recent_neighbors_col,
        ]

        node_features[count_features] = np.log1p(
            node_features[count_features]
        )

        # Keep the same eight-dimensional model input used by the existing
        # Phase-4 pipeline, but make the short-term features genuinely current
        # at G(t) rather than historical maxima over the entire dataset.
        model_feature_columns = [
            "total_logins",
            "successful_logins",
            "failed_logins",
            "failure_ratio",
            "distinct_neighbors",
            recent_logins_col,
            combined_recent_neighbors_col,
            "node_type",
        ]

        x_numpy = node_features[
            model_feature_columns
        ].to_numpy(dtype=np.float32)

        if not np.isfinite(x_numpy).all():
            raise ValueError("Non-finite values detected in node features.")

        # =====================================================
        # 10. EDGE INDEX + PYTORCH GEOMETRIC GRAPH
        # =====================================================

        print("\n[10/10] Creating PyTorch graph...")

        forward_edges = edges[
            ["user_node_id", "ip_node_id"]
        ].to_numpy(dtype=np.int64).T

        reverse_edges = forward_edges[[1, 0], :]

        edge_index_numpy = np.concatenate(
            [forward_edges, reverse_edges],
            axis=1,
        )

        x = torch.from_numpy(x_numpy)
        edge_index = torch.from_numpy(edge_index_numpy)

        graph = Data(
            x=x,
            edge_index=edge_index,
        )

        # Metadata used later by local inference / temporal replay.
        graph.num_user_nodes = int(num_users)
        graph.num_ip_nodes = int(num_ips)
        graph.cutoff_timestamp = cutoff.isoformat()
        graph.recent_window_minutes = int(recent_window_minutes)
        graph.feature_names = model_feature_columns

        graph_is_valid = graph.validate(raise_on_error=False)

        if not graph_is_valid:
            raise ValueError(f"{org_name} PyG graph validation failed.")

        # =====================================================
        # SAVE ARTIFACTS
        # =====================================================

        if save_artifacts:
            print("\nSaving graph artifacts...")

            torch.save(
                x,
                output_dir / f"{org_name.lower()}_node_features.pt",
            )
            torch.save(
                edge_index,
                output_dir / f"{org_name.lower()}_edge_index.pt",
            )
            torch.save(
                graph,
                output_dir / f"{org_name.lower()}_graph.pt",
            )

            # Mappings are retained so a later event can be linked back to the
            # persistent graph state using its local User ID or IP address.
            user_mapping_path = output_dir / f"{org_name.lower()}_user_mapping.parquet"
            ip_mapping_path = output_dir / f"{org_name.lower()}_ip_mapping.parquet"

            con.execute(
                f"COPY users_mapping TO '{user_mapping_path.as_posix()}' (FORMAT PARQUET)"
            )
            con.execute(
                f"COPY ips_mapping TO '{ip_mapping_path.as_posix()}' (FORMAT PARQUET)"
            )

            # Persist untransformed graph state as the seed for the upcoming
            # incremental updater.  This is new relative to the original
            # Phase-4 implementation.
            state_frames = {
                "structural_edges": edges,
                "edge_state": edge_features,
                "user_state": user_features,
                "ip_state": ip_features,
            }

            for state_name, state_frame in state_frames.items():
                relation_name = f"state_{state_name}"
                state_path = (
                    output_dir
                    / f"{org_name.lower()}_{state_name}.parquet"
                )

                con.register(relation_name, state_frame)
                con.execute(
                    f"COPY {relation_name} TO '{state_path.as_posix()}' "
                    "(FORMAT PARQUET)"
                )
                con.unregister(relation_name)

            metadata = {
                "organization": org_name,
                "graph_type": "persistent_temporal_user_ip",
                "cutoff_timestamp": cutoff.isoformat(),
                "recent_window_minutes": recent_window_minutes,
                "num_users": num_users,
                "num_ips": num_ips,
                "num_nodes": int(graph.num_nodes),
                "num_structural_edges": int(len(edges)),
                "num_directed_edges": int(graph.num_edges),
                "num_node_features": int(graph.num_node_features),
                "model_feature_columns": model_feature_columns,
                "login_success_source_column": physical_success_column,
            }

            with open(
                output_dir / f"{org_name.lower()}_graph_metadata.json",
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(metadata, handle, indent=2)

        # =====================================================
        # FINAL SUMMARY
        # =====================================================

        print("\n" + "=" * 60)
        print(f"{org_name} TEMPORAL GRAPH STATE COMPLETE")
        print("=" * 60)

        print("Cutoff:", cutoff)
        print("Users:", num_users)
        print("IPs:", num_ips)
        print("Nodes:", graph.num_nodes)
        print("Structural edges:", len(edges))
        print("Directed edges:", graph.num_edges)
        print("Node features:", graph.num_node_features)
        print("Feature values finite:", np.isfinite(x_numpy).all())
        print("Graph validation:", graph_is_valid)

        if save_artifacts:
            print("\nSaved to:")
            print(output_dir)

        return graph

    finally:
        con.close()


# ---------------------------------------------------------
# Command-line execution
# ---------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Build a local CredBlock-FL temporal User-IP graph state G(t)."
        )
    )

    parser.add_argument(
        "--org-id",
        type=int,
        required=True,
        choices=[1, 2, 3, 4, 5],
        help="Organization number (1-5)",
    )

    parser.add_argument(
        "--cutoff",
        type=str,
        default=None,
        help=(
            "Optional ISO timestamp. Only authentication events at or before "
            "this time are included, e.g. 2020-08-01T12:30:00."
        ),
    )

    parser.add_argument(
        "--recent-window-minutes",
        type=int,
        default=10,
        help="Short-term activity window used for live temporal features.",
    )

    args = parser.parse_args()

    cutoff_value = (
        datetime.fromisoformat(args.cutoff)
        if args.cutoff
        else None
    )

    build_temporal_graph_state(
        org_id=args.org_id,
        cutoff=cutoff_value,
        recent_window_minutes=args.recent_window_minutes,
    )
