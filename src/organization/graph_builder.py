from pathlib import Path

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
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


# ---------------------------------------------------------
# Main graph-building function
# ---------------------------------------------------------

def build_graph(org_id: int):
    """
    Build one organization's local User-IP authentication graph.

    Example:
        build_graph(2)
    """

    org_name = f"Org{org_id}"

    input_path = (
        ORGANIZATIONS_DIR
        / f"organization={org_name}"
        / "*.parquet"
    )

    output_dir = PROCESSED_DIR / org_name.lower()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"Building graph for {org_name}")
    print("=" * 60)
    print("Input:", input_path)

    con = duckdb.connect()

    parquet_path = str(input_path).replace("\\", "/")


    # =====================================================
    # 1. USER NODE MAPPING
    # =====================================================

    print("\n[1/10] Creating user-node mapping...")

    users = con.execute(f"""
        SELECT DISTINCT "User ID"
        FROM read_parquet('{parquet_path}')
        ORDER BY "User ID"
    """).df()

    users["user_node_id"] = np.arange(
        len(users),
        dtype=np.int64
    )

    num_users = len(users)

    print("Users:", num_users)


    # =====================================================
    # 2. IP NODE MAPPING
    # =====================================================

    print("\n[2/10] Creating IP-node mapping...")

    ips = con.execute(f"""
        SELECT DISTINCT "IP Address"
        FROM read_parquet('{parquet_path}')
        ORDER BY "IP Address"
    """).df()

    ips["ip_node_id"] = np.arange(
        len(ips),
        dtype=np.int64
    )

    # Shift IP IDs so User and IP node IDs do not overlap
    ips["global_ip_node_id"] = (
        ips["ip_node_id"] + num_users
    )

    num_ips = len(ips)
    num_nodes = num_users + num_ips

    print("IPs:", num_ips)
    print("Total nodes:", num_nodes)


    # Register mappings with DuckDB
    con.register("users_mapping", users)
    con.register("ips_mapping", ips)


    # =====================================================
    # 3. STRUCTURAL USER-IP EDGES
    # =====================================================

    print("\n[3/10] Creating structural User-IP edges...")

    edges = con.execute(f"""
        SELECT DISTINCT
            u.user_node_id,
            i.global_ip_node_id AS ip_node_id

        FROM read_parquet('{parquet_path}') d

        JOIN users_mapping u
            ON d."User ID" = u."User ID"

        JOIN ips_mapping i
            ON d."IP Address" = i."IP Address"
    """).df()

    edges["user_node_id"] = edges["user_node_id"].astype(
        np.int64
    )
    edges["ip_node_id"] = edges["ip_node_id"].astype(
        np.int64
    )

    print("Structural edges:", len(edges))


    # =====================================================
    # 4. BASIC EDGE FEATURES
    # =====================================================

    print("\n[4/10] Creating edge features...")

    edge_features = con.execute(f"""
        SELECT
            u.user_node_id,
            i.global_ip_node_id AS ip_node_id,

            COUNT(*) AS total_interactions,

            SUM(
                CASE
                    WHEN d."Login Successful" = TRUE
                    THEN 1
                    ELSE 0
                END
            ) AS successful_interactions,

            SUM(
                CASE
                    WHEN d."Login Successful" = FALSE
                    THEN 1
                    ELSE 0
                END
            ) AS failed_interactions,

            SUM(
                CASE
                    WHEN d."Login Successful" = FALSE
                    THEN 1
                    ELSE 0
                END
            )::DOUBLE / COUNT(*) AS failure_ratio,

            MIN(d."Login Timestamp") AS first_seen,
            MAX(d."Login Timestamp") AS last_seen

        FROM read_parquet('{parquet_path}') d

        JOIN users_mapping u
            ON d."User ID" = u."User ID"

        JOIN ips_mapping i
            ON d."IP Address" = i."IP Address"

        GROUP BY
            u.user_node_id,
            i.global_ip_node_id
    """).df()


    # =====================================================
    # 5. 10-MINUTE TEMPORAL EDGE FEATURES
    # =====================================================

    print("\n[5/10] Creating temporal edge features...")

    temporal_edges = con.execute(f"""
        WITH window_activity AS (

            SELECT
                u.user_node_id,
                i.global_ip_node_id AS ip_node_id,

                time_bucket(
                    INTERVAL '10 minutes',
                    d."Login Timestamp"
                ) AS window_start,

                COUNT(*) AS interactions_10min,

                SUM(
                    CASE
                        WHEN d."Login Successful" = FALSE
                        THEN 1
                        ELSE 0
                    END
                ) AS failed_interactions_10min

            FROM read_parquet('{parquet_path}') d

            JOIN users_mapping u
                ON d."User ID" = u."User ID"

            JOIN ips_mapping i
                ON d."IP Address" = i."IP Address"

            GROUP BY
                u.user_node_id,
                i.global_ip_node_id,
                window_start
        )

        SELECT
            user_node_id,
            ip_node_id,

            COUNT(*) AS active_10min_windows,

            MAX(interactions_10min)
                AS max_interactions_10min,

            MAX(failed_interactions_10min)
                AS max_failed_interactions_10min

        FROM window_activity

        GROUP BY
            user_node_id,
            ip_node_id
    """).df()


    edge_features = edge_features.merge(
        temporal_edges,
        on=["user_node_id", "ip_node_id"],
        how="left"
    )

    edge_features["relationship_duration_hours"] = (
        (
            edge_features["last_seen"]
            - edge_features["first_seen"]
        ).dt.total_seconds()
        / 3600
    )

    print("Edge-feature rows:", len(edge_features))


    # =====================================================
    # 6. USER NODE FEATURES
    # =====================================================

    print("\n[6/10] Creating User-node features...")

    user_features = con.execute(f"""
        WITH base AS (

            SELECT
                u.user_node_id,

                COUNT(*) AS total_logins,

                SUM(
                    CASE
                        WHEN d."Login Successful" = TRUE
                        THEN 1
                        ELSE 0
                    END
                ) AS successful_logins,

                SUM(
                    CASE
                        WHEN d."Login Successful" = FALSE
                        THEN 1
                        ELSE 0
                    END
                ) AS failed_logins,

                COUNT(DISTINCT d."IP Address")
                    AS distinct_ips

            FROM read_parquet('{parquet_path}') d

            JOIN users_mapping u
                ON d."User ID" = u."User ID"

            GROUP BY u.user_node_id
        ),

        window_activity AS (

            SELECT
                u.user_node_id,

                time_bucket(
                    INTERVAL '10 minutes',
                    d."Login Timestamp"
                ) AS window_start,

                COUNT(*) AS logins_10min,

                COUNT(DISTINCT d."IP Address")
                    AS distinct_ips_10min

            FROM read_parquet('{parquet_path}') d

            JOIN users_mapping u
                ON d."User ID" = u."User ID"

            GROUP BY
                u.user_node_id,
                window_start
        ),

        temporal AS (

            SELECT
                user_node_id,

                MAX(logins_10min)
                    AS max_logins_10min,

                MAX(distinct_ips_10min)
                    AS max_distinct_ips_10min

            FROM window_activity

            GROUP BY user_node_id
        )

        SELECT
            b.user_node_id,
            b.total_logins,
            b.successful_logins,
            b.failed_logins,

            b.failed_logins::DOUBLE
                / b.total_logins AS failure_ratio,

            b.distinct_ips,
            t.max_logins_10min,
            t.max_distinct_ips_10min

        FROM base b

        JOIN temporal t
            ON b.user_node_id = t.user_node_id

        ORDER BY b.user_node_id
    """).df()

    print("User feature rows:", len(user_features))


    # =====================================================
    # 7. IP NODE FEATURES
    # =====================================================

    print("\n[7/10] Creating IP-node features...")

    ip_features = con.execute(f"""
        WITH base AS (

            SELECT
                i.global_ip_node_id AS ip_node_id,

                COUNT(*) AS total_logins,

                SUM(
                    CASE
                        WHEN d."Login Successful" = TRUE
                        THEN 1
                        ELSE 0
                    END
                ) AS successful_logins,

                SUM(
                    CASE
                        WHEN d."Login Successful" = FALSE
                        THEN 1
                        ELSE 0
                    END
                ) AS failed_logins,

                COUNT(DISTINCT d."User ID")
                    AS distinct_users

            FROM read_parquet('{parquet_path}') d

            JOIN ips_mapping i
                ON d."IP Address" = i."IP Address"

            GROUP BY i.global_ip_node_id
        ),

        window_activity AS (

            SELECT
                i.global_ip_node_id AS ip_node_id,

                time_bucket(
                    INTERVAL '10 minutes',
                    d."Login Timestamp"
                ) AS window_start,

                COUNT(*) AS logins_10min,

                COUNT(DISTINCT d."User ID")
                    AS distinct_users_10min

            FROM read_parquet('{parquet_path}') d

            JOIN ips_mapping i
                ON d."IP Address" = i."IP Address"

            GROUP BY
                i.global_ip_node_id,
                window_start
        ),

        temporal AS (

            SELECT
                ip_node_id,

                MAX(logins_10min)
                    AS max_logins_10min,

                MAX(distinct_users_10min)
                    AS max_distinct_users_10min

            FROM window_activity

            GROUP BY ip_node_id
        )

        SELECT
            b.ip_node_id,
            b.total_logins,
            b.successful_logins,
            b.failed_logins,

            b.failed_logins::DOUBLE
                / b.total_logins AS failure_ratio,

            b.distinct_users,
            t.max_logins_10min,
            t.max_distinct_users_10min

        FROM base b

        JOIN temporal t
            ON b.ip_node_id = t.ip_node_id

        ORDER BY b.ip_node_id
    """).df()

    print("IP feature rows:", len(ip_features))


    # =====================================================
    # 8. COMBINE USER + IP NODE FEATURES
    # =====================================================

    print("\n[8/10] Combining node features...")

    user_nodes = user_features.rename(
        columns={
            "user_node_id": "node_id",
            "distinct_ips": "distinct_neighbors",
            "max_distinct_ips_10min":
                "max_distinct_neighbors_10min"
        }
    )

    user_nodes["node_type"] = 0

    ip_nodes = ip_features.rename(
        columns={
            "ip_node_id": "node_id",
            "distinct_users": "distinct_neighbors",
            "max_distinct_users_10min":
                "max_distinct_neighbors_10min"
        }
    )

    ip_nodes["node_type"] = 1

    node_features = pd.concat(
        [user_nodes, ip_nodes],
        ignore_index=True
    )

    node_features = node_features.sort_values(
        "node_id"
    ).reset_index(drop=True)


    # =====================================================
    # 9. FEATURE TRANSFORMATION
    # =====================================================

    print("\n[9/10] Transforming model features...")

    count_features = [
        "total_logins",
        "successful_logins",
        "failed_logins",
        "distinct_neighbors",
        "max_logins_10min",
        "max_distinct_neighbors_10min",
    ]

    node_features[count_features] = np.log1p(
        node_features[count_features]
    )

    model_feature_columns = [
        "total_logins",
        "successful_logins",
        "failed_logins",
        "failure_ratio",
        "distinct_neighbors",
        "max_logins_10min",
        "max_distinct_neighbors_10min",
        "node_type",
    ]

    x_numpy = node_features[
        model_feature_columns
    ].to_numpy(dtype=np.float32)

    if not np.isfinite(x_numpy).all():
        raise ValueError(
            "Non-finite values detected in node features."
        )


    # =====================================================
    # 10. EDGE INDEX + PYTORCH GEOMETRIC GRAPH
    # =====================================================

    print("\n[10/10] Creating PyTorch graph...")

    forward_edges = edges[
        ["user_node_id", "ip_node_id"]
    ].to_numpy(dtype=np.int64).T

    reverse_edges = forward_edges[
        [1, 0], :
    ]

    edge_index_numpy = np.concatenate(
        [forward_edges, reverse_edges],
        axis=1
    )

    x = torch.from_numpy(x_numpy)

    edge_index = torch.from_numpy(
        edge_index_numpy
    )

    graph = Data(
        x=x,
        edge_index=edge_index
    )

    graph_is_valid = graph.validate(
        raise_on_error=False
    )

    if not graph_is_valid:
        raise ValueError(
            f"{org_name} PyG graph validation failed."
        )


    # =====================================================
    # SAVE ARTIFACTS
    # =====================================================

    print("\nSaving graph artifacts...")

    torch.save(
        x,
        output_dir / f"{org_name.lower()}_node_features.pt"
    )

    torch.save(
        edge_index,
        output_dir / f"{org_name.lower()}_edge_index.pt"
    )

    torch.save(
        graph,
        output_dir / f"{org_name.lower()}_graph.pt"
    )

    user_mapping_path = (
    output_dir / f"{org_name.lower()}_user_mapping.parquet"
    )

    ip_mapping_path = (
        output_dir / f"{org_name.lower()}_ip_mapping.parquet"
    )

    con.execute(
        f"COPY users_mapping TO '{user_mapping_path.as_posix()}' "
        "(FORMAT PARQUET)"
    )

    con.execute(
        f"COPY ips_mapping TO '{ip_mapping_path.as_posix()}' "
        "(FORMAT PARQUET)"
    )


    # =====================================================
    # FINAL SUMMARY
    # =====================================================

    print("\n" + "=" * 60)
    print(f"{org_name} GRAPH COMPLETE")
    print("=" * 60)

    print("Users:", num_users)
    print("IPs:", num_ips)
    print("Nodes:", graph.num_nodes)
    print("Structural edges:", len(edges))
    print("Directed edges:", graph.num_edges)
    print("Node features:", graph.num_node_features)
    print("Feature values finite:", np.isfinite(x_numpy).all())
    print("Graph validation:", graph_is_valid)

    print("\nSaved to:")
    print(output_dir)

    con.close()

    return graph


# ---------------------------------------------------------
# Command-line execution
# ---------------------------------------------------------

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(
        description="Build a local CredBlock-FL User-IP graph."
    )

    parser.add_argument(
        "--org-id",
        type=int,
        required=True,
        choices=[1, 2, 3, 4, 5],
        help="Organization number (1-5)"
    )

    args = parser.parse_args()

    build_graph(args.org_id)