from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import torch
from torch_geometric.data import Data


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ORGANIZATIONS_DIR = PROJECT_ROOT / "data" / "organizations"
TEMPORAL_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed_temporal"
EVENT_STREAMS_DIR = PROJECT_ROOT / "data" / "phase5" / "event_streams"
UPDATED_GRAPHS_DIR = PROJECT_ROOT / "data" / "phase5" / "updated_graphs"


def _sql_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _read_graph(path: Path) -> Data:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:  # compatibility with older PyTorch releases
        return torch.load(path, map_location="cpu")




def _read_parquet(path: Path) -> pd.DataFrame:
    """Read Parquet through DuckDB so pyarrow/fastparquet are not required."""
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Parquet file not found: {path}")
    escaped = path.as_posix().replace("'", "''")
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT * FROM read_parquet('{escaped}')").df()
    finally:
        con.close()


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write Parquet through DuckDB so pyarrow is not required."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.register("output_frame", frame)
        escaped = path.as_posix().replace("'", "''")
        con.execute(
            f"COPY output_frame TO '{escaped}' (FORMAT PARQUET)"
        )
        con.unregister("output_frame")
    finally:
        con.close()


def _resolve_success_column(columns: set[str]) -> str:
    for candidate in ("LoginSuccessful", "Login Successful"):
        if candidate in columns:
            return candidate
    raise ValueError(
        "Could not find the login-success column. Expected "
        "'LoginSuccessful' or 'Login Successful'."
    )


def _load_recent_seed_events(
    org_id: int,
    base_dir: Path,
    base_cutoff: datetime,
    window_minutes: int,
    user_to_node: dict[Any, int],
    ip_to_node: dict[str, int],
) -> pd.DataFrame:
    """Load the active rolling window from a prior state or original data."""
    org_name = f"Org{org_id}"
    saved_buffer = base_dir / f"{org_name.lower()}_recent_event_buffer.parquet"

    if saved_buffer.exists():
        seed = _read_parquet(saved_buffer)
    else:
        parquet_glob = (
            ORGANIZATIONS_DIR / f"organization={org_name}" / "*.parquet"
        ).as_posix()
        con = duckdb.connect()
        try:
            columns = {
                row[0]
                for row in con.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{parquet_glob}')"
                ).fetchall()
            }
            success_col = _resolve_success_column(columns)
            cutoff_literal = _sql_timestamp(base_cutoff)
            start_literal = _sql_timestamp(
                base_cutoff - timedelta(minutes=window_minutes)
            )
            seed = con.execute(
                f"""
                SELECT
                    '{org_name}'::VARCHAR AS organization,
                    "Login Timestamp"::TIMESTAMP AS "Login Timestamp",
                    "User ID"::BIGINT AS "User ID",
                    "IP Address"::VARCHAR AS "IP Address",
                    "{success_col}"::BOOLEAN AS LoginSuccessful,
                    FALSE::BOOLEAN AS is_synthetic,
                    0::INTEGER AS credential_stuffing_label,
                    NULL::VARCHAR AS scenario_id,
                    NULL::VARCHAR AS campaign_id,
                    NULL::VARCHAR AS synthetic_credential_id,
                    NULL::BOOLEAN AS is_reused_credential,
                    NULL::VARCHAR AS campaign_event_id
                FROM read_parquet('{parquet_glob}')
                WHERE "Login Timestamp" > TIMESTAMP '{start_literal}'
                  AND "Login Timestamp" <= TIMESTAMP '{cutoff_literal}'
                ORDER BY "Login Timestamp"
                """
            ).df()
        finally:
            con.close()

    if seed.empty:
        return pd.DataFrame(
            columns=[
                "organization", "Login Timestamp", "User ID", "IP Address",
                "LoginSuccessful", "is_synthetic", "credential_stuffing_label",
                "scenario_id", "campaign_id", "synthetic_credential_id",
                "is_reused_credential", "campaign_event_id",
            ]
        )

    seed["Login Timestamp"] = pd.to_datetime(seed["Login Timestamp"])
    seed = seed.sort_values("Login Timestamp", kind="stable").reset_index(drop=True)
    lower_bound = base_cutoff - timedelta(minutes=window_minutes)
    seed = seed[
        (seed["Login Timestamp"] > lower_bound)
        & (seed["Login Timestamp"] <= base_cutoff)
    ].copy()

    # Every seed event must already belong to the graph state at base_cutoff.
    missing_users = [value for value in seed["User ID"].unique() if value not in user_to_node]
    missing_ips = [value for value in seed["IP Address"].unique() if value not in ip_to_node]
    if missing_users or missing_ips:
        raise ValueError(
            "The saved recent-event buffer contains users/IPs missing from its "
            f"base graph (missing users={len(missing_users)}, "
            f"missing IPs={len(missing_ips)})."
        )

    return seed


def _decrement(counter: Counter, key: Any) -> None:
    counter[key] -= 1
    if counter[key] <= 0:
        del counter[key]


def update_temporal_graph(
    org_id: int,
    campaign_id: str,
    start: datetime,
    end: datetime,
    base_dir: Path | None = None,
    stream_path: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Incrementally apply a chronological local stream to graph state G(t)."""
    if end <= start:
        raise ValueError("end must be later than start")

    org_name = f"Org{org_id}"
    base_dir = base_dir or (TEMPORAL_PROCESSED_DIR / org_name.lower())
    stream_path = stream_path or (
        EVENT_STREAMS_DIR / campaign_id / f"{org_name}.parquet"
    )
    output_dir = output_dir or (
        UPDATED_GRAPHS_DIR / campaign_id / org_name.lower()
    )

    required = [
        base_dir / f"{org_name.lower()}_graph.pt",
        base_dir / f"{org_name.lower()}_graph_metadata.json",
        base_dir / f"{org_name.lower()}_user_mapping.parquet",
        base_dir / f"{org_name.lower()}_ip_mapping.parquet",
        base_dir / f"{org_name.lower()}_structural_edges.parquet",
        base_dir / f"{org_name.lower()}_edge_state.parquet",
        base_dir / f"{org_name.lower()}_user_state.parquet",
        base_dir / f"{org_name.lower()}_ip_state.parquet",
        stream_path,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Required input files are missing:\n" + "\n".join(missing))

    with open(base_dir / f"{org_name.lower()}_graph_metadata.json", encoding="utf-8") as handle:
        metadata = json.load(handle)

    base_cutoff = datetime.fromisoformat(metadata["cutoff_timestamp"])
    window_minutes = int(metadata.get("recent_window_minutes", 10))
    is_incremental_base = "incrementally_updated" in str(metadata.get("graph_type", ""))
    expected_start = (
        base_cutoff
        if is_incremental_base
        else base_cutoff + timedelta(microseconds=1)
    )
    if start != expected_start:
        raise ValueError(
            f"Stream start ({start}) does not immediately follow the base graph "
            f"cutoff ({base_cutoff}). Expected start: {expected_start}. "
            "This check prevents replaying events or silently skipping events "
            "between graph states."
        )

    stream = _read_parquet(stream_path)
    if stream.empty:
        raise ValueError("The event stream is empty; no graph update was performed.")

    needed_stream_columns = {
        "Login Timestamp", "User ID", "IP Address", "is_synthetic",
        "credential_stuffing_label",
    }
    missing_stream_columns = needed_stream_columns - set(stream.columns)
    if missing_stream_columns:
        raise ValueError(
            "Event stream is missing required columns: "
            + ", ".join(sorted(missing_stream_columns))
        )

    success_col = _resolve_success_column(set(stream.columns))
    if success_col != "LoginSuccessful":
        stream = stream.rename(columns={success_col: "LoginSuccessful"})

    stream["Login Timestamp"] = pd.to_datetime(stream["Login Timestamp"])
    stream = stream.sort_values(
        ["Login Timestamp", "is_synthetic", "User ID", "IP Address"],
        kind="stable",
    ).reset_index(drop=True)

    if (stream["Login Timestamp"] < pd.Timestamp(start)).any():
        raise ValueError("Stream contains events earlier than --start.")
    if (stream["Login Timestamp"] >= pd.Timestamp(end)).any():
        raise ValueError("Stream contains events at or after --end; end is exclusive.")
    if not stream["Login Timestamp"].is_monotonic_increasing:
        raise ValueError("Event stream is not chronologically ordered.")

    graph = _read_graph(base_dir / f"{org_name.lower()}_graph.pt")
    users_mapping = _read_parquet(
        base_dir / f"{org_name.lower()}_user_mapping.parquet"
    )
    ips_mapping = _read_parquet(
        base_dir / f"{org_name.lower()}_ip_mapping.parquet"
    )
    structural_edges_df = _read_parquet(
        base_dir / f"{org_name.lower()}_structural_edges.parquet"
    )
    edge_state = _read_parquet(
        base_dir / f"{org_name.lower()}_edge_state.parquet"
    ).set_index(["user_node_id", "ip_node_id"]).sort_index()
    user_state = _read_parquet(
        base_dir / f"{org_name.lower()}_user_state.parquet"
    ).set_index("user_node_id").sort_index()
    ip_state = _read_parquet(
        base_dir / f"{org_name.lower()}_ip_state.parquet"
    ).set_index("ip_node_id").sort_index()

    user_to_node = {
        user_id: int(node_id)
        for user_id, node_id in zip(
            users_mapping["User ID"], users_mapping["user_node_id"]
        )
    }
    ip_to_node = {
        ip: int(node_id)
        for ip, node_id in zip(
            ips_mapping["IP Address"], ips_mapping["global_ip_node_id"]
        )
    }
    structural_edge_set = {
        (int(user_id), int(ip_id))
        for user_id, ip_id in zip(
            structural_edges_df["user_node_id"],
            structural_edges_df["ip_node_id"],
        )
    }

    next_node_id = int(graph.num_nodes)
    next_ip_local_id = int(ips_mapping["ip_node_id"].max()) + 1 if len(ips_mapping) else 0

    user_recent_logins: Counter = Counter()
    ip_recent_logins: Counter = Counter()
    edge_recent_interactions: Counter = Counter()
    edge_recent_failed: Counter = Counter()
    user_recent_neighbors: Counter = Counter()
    ip_recent_neighbors: Counter = Counter()
    recent_events = deque()

    recent_user_col = f"recent_logins_{window_minutes}min"
    recent_user_neighbors_col = f"recent_distinct_ips_{window_minutes}min"
    recent_ip_col = f"recent_logins_{window_minutes}min"
    recent_ip_neighbors_col = f"recent_distinct_users_{window_minutes}min"
    recent_edge_col = f"recent_interactions_{window_minutes}min"
    recent_edge_failed_col = f"recent_failed_interactions_{window_minutes}min"

    def set_user_recent(node_id: int) -> None:
        user_state.at[node_id, recent_user_col] = int(user_recent_logins[node_id])
        user_state.at[node_id, recent_user_neighbors_col] = int(user_recent_neighbors[node_id])

    def set_ip_recent(node_id: int) -> None:
        ip_state.at[node_id, recent_ip_col] = int(ip_recent_logins[node_id])
        ip_state.at[node_id, recent_ip_neighbors_col] = int(ip_recent_neighbors[node_id])

    def set_edge_recent(key: tuple[int, int]) -> None:
        edge_state.at[key, recent_edge_col] = int(edge_recent_interactions[key])
        edge_state.at[key, recent_edge_failed_col] = int(edge_recent_failed[key])

    def add_recent_event(event: dict[str, Any]) -> None:
        user_node = int(event["user_node_id"])
        ip_node = int(event["ip_node_id"])
        key = (user_node, ip_node)
        if edge_recent_interactions[key] == 0:
            user_recent_neighbors[user_node] += 1
            ip_recent_neighbors[ip_node] += 1
        user_recent_logins[user_node] += 1
        ip_recent_logins[ip_node] += 1
        edge_recent_interactions[key] += 1
        if not bool(event["LoginSuccessful"]):
            edge_recent_failed[key] += 1
        recent_events.append(event)
        set_user_recent(user_node)
        set_ip_recent(ip_node)
        set_edge_recent(key)

    def expire_events(threshold: datetime) -> None:
        while recent_events and recent_events[0]["Login Timestamp"] <= threshold:
            old = recent_events.popleft()
            user_node = int(old["user_node_id"])
            ip_node = int(old["ip_node_id"])
            key = (user_node, ip_node)

            _decrement(user_recent_logins, user_node)
            _decrement(ip_recent_logins, ip_node)
            _decrement(edge_recent_interactions, key)
            if not bool(old["LoginSuccessful"]):
                _decrement(edge_recent_failed, key)

            if edge_recent_interactions.get(key, 0) == 0:
                _decrement(user_recent_neighbors, user_node)
                _decrement(ip_recent_neighbors, ip_node)

            set_user_recent(user_node)
            set_ip_recent(ip_node)
            set_edge_recent(key)

    def ensure_user(user_id: Any) -> int:
        nonlocal next_node_id
        if user_id in user_to_node:
            return user_to_node[user_id]
        node_id = next_node_id
        next_node_id += 1
        user_to_node[user_id] = node_id
        users_mapping.loc[len(users_mapping)] = {
            "User ID": user_id,
            "user_node_id": node_id,
        }
        user_state.loc[node_id, :] = [
            0, 0, 0, 0.0, 0, 0, 0,
        ]
        set_user_recent(node_id)
        return node_id

    def ensure_ip(ip: str) -> int:
        nonlocal next_node_id, next_ip_local_id
        if ip in ip_to_node:
            return ip_to_node[ip]
        node_id = next_node_id
        next_node_id += 1
        ip_to_node[ip] = node_id
        ips_mapping.loc[len(ips_mapping)] = {
            "IP Address": ip,
            "ip_node_id": next_ip_local_id,
            "global_ip_node_id": node_id,
        }
        next_ip_local_id += 1
        ip_state.loc[node_id, :] = [
            0, 0, 0, 0.0, 0, 0, 0,
        ]
        set_ip_recent(node_id)
        return node_id

    def apply_event(event_row: pd.Series) -> dict[str, Any]:
        event = event_row.to_dict()
        timestamp = pd.Timestamp(event["Login Timestamp"])
        user_id = event["User ID"]
        ip_address = event["IP Address"]
        success_value = event["LoginSuccessful"]
        if pd.isna(success_value):
            raise ValueError("A stream event has a missing login-success value.")
        event["LoginSuccessful"] = bool(success_value)
        event["Login Timestamp"] = timestamp

        expire_events((timestamp - pd.Timedelta(minutes=window_minutes)).to_pydatetime())

        user_node = ensure_user(user_id)
        ip_node = ensure_ip(ip_address)
        key = (user_node, ip_node)
        is_new_edge = key not in structural_edge_set

        if is_new_edge:
            structural_edge_set.add(key)
            defaults = {
                "total_interactions": 0,
                "successful_interactions": 0,
                "failed_interactions": 0,
                "failure_ratio": 0.0,
                "first_seen": timestamp,
                "last_seen": timestamp,
                recent_edge_col: 0,
                recent_edge_failed_col: 0,
                "relationship_duration_hours": 0.0,
            }
            edge_state.loc[key, :] = [defaults[col] for col in edge_state.columns]
            user_state.at[user_node, "distinct_ips"] += 1
            ip_state.at[ip_node, "distinct_users"] += 1

        # Cumulative user-node state.
        user_state.at[user_node, "total_logins"] += 1
        if event["LoginSuccessful"]:
            user_state.at[user_node, "successful_logins"] += 1
        else:
            user_state.at[user_node, "failed_logins"] += 1
        user_total = float(user_state.at[user_node, "total_logins"])
        user_state.at[user_node, "failure_ratio"] = (
            float(user_state.at[user_node, "failed_logins"]) / user_total
        )

        # Cumulative IP-node state.
        ip_state.at[ip_node, "total_logins"] += 1
        if event["LoginSuccessful"]:
            ip_state.at[ip_node, "successful_logins"] += 1
        else:
            ip_state.at[ip_node, "failed_logins"] += 1
        ip_total = float(ip_state.at[ip_node, "total_logins"])
        ip_state.at[ip_node, "failure_ratio"] = (
            float(ip_state.at[ip_node, "failed_logins"]) / ip_total
        )

        # Cumulative User-IP edge state.
        edge_state.at[key, "total_interactions"] += 1
        if event["LoginSuccessful"]:
            edge_state.at[key, "successful_interactions"] += 1
        else:
            edge_state.at[key, "failed_interactions"] += 1
        edge_total = float(edge_state.at[key, "total_interactions"])
        edge_state.at[key, "failure_ratio"] = (
            float(edge_state.at[key, "failed_interactions"]) / edge_total
        )
        previous_first = pd.Timestamp(edge_state.at[key, "first_seen"])
        previous_last = pd.Timestamp(edge_state.at[key, "last_seen"])
        edge_state.at[key, "first_seen"] = min(previous_first, timestamp)
        edge_state.at[key, "last_seen"] = max(previous_last, timestamp)
        edge_state.at[key, "relationship_duration_hours"] = (
            (pd.Timestamp(edge_state.at[key, "last_seen"])
             - pd.Timestamp(edge_state.at[key, "first_seen"])).total_seconds()
            / 3600.0
        )

        event["user_node_id"] = user_node
        event["ip_node_id"] = ip_node
        add_recent_event(event)

        # Snapshot the current local neighborhood/activity features for this event.
        event_update = dict(event)
        event_update.update({
            "user_recent_logins_10min": int(user_recent_logins[user_node]),
            "user_recent_distinct_ips_10min": int(user_recent_neighbors[user_node]),
            "ip_recent_logins_10min": int(ip_recent_logins[ip_node]),
            "ip_recent_distinct_users_10min": int(ip_recent_neighbors[ip_node]),
            "edge_recent_interactions_10min": int(edge_recent_interactions[key]),
            "edge_recent_failed_interactions_10min": int(edge_recent_failed[key]),
        })
        return event_update

    print("=" * 60)
    print(f"Incrementally updating {org_name} temporal User-IP graph")
    print("=" * 60)
    print("Base graph directory:", base_dir)
    print("Base graph cutoff:", base_cutoff)
    print("Event stream:", stream_path)
    print("Stream interval:", start, "->", end, "(end exclusive)")
    print("Recent activity window:", window_minutes, "minutes")

    # Seed rolling-window counters with events already represented in the base graph.
    seed = _load_recent_seed_events(
        org_id=org_id,
        base_dir=base_dir,
        base_cutoff=base_cutoff,
        window_minutes=window_minutes,
        user_to_node=user_to_node,
        ip_to_node=ip_to_node,
    )
    for _, row in seed.iterrows():
        user_id = row["User ID"]
        ip_address = row["IP Address"]
        event = {
            "Login Timestamp": pd.Timestamp(row["Login Timestamp"]),
            "User ID": user_id,
            "IP Address": ip_address,
            "LoginSuccessful": bool(row["LoginSuccessful"]),
            "user_node_id": user_to_node[user_id],
            "ip_node_id": ip_to_node[ip_address],
        }
        add_recent_event(event)

    # The seed counters must agree with the graph state at its cutoff.
    # Correct the loaded state to the counters derived from the event buffer.
    for node_id in list(user_state.index):
        set_user_recent(int(node_id))
    for node_id in list(ip_state.index):
        set_ip_recent(int(node_id))
    for key in list(edge_state.index):
        set_edge_recent((int(key[0]), int(key[1])))

    event_updates = []
    for _, event_row in stream.iterrows():
        event_updates.append(apply_event(event_row))

    # Set the final state at the end of the observation period, not merely at
    # the timestamp of the last event. End is exclusive, matching event_stream.py.
    expire_events((end - timedelta(minutes=window_minutes)))
    final_cutoff = end

    # Assemble model features in stable node-ID order. New nodes are appended,
    # so previously assigned node IDs do not change during this replay.
    recent_user_neighbors_col = f"recent_distinct_ips_{window_minutes}min"
    recent_ip_neighbors_col = f"recent_distinct_users_{window_minutes}min"
    recent_logins_col = f"recent_logins_{window_minutes}min"
    combined_recent_neighbors_col = f"recent_distinct_neighbors_{window_minutes}min"

    user_nodes = user_state.reset_index().rename(
        columns={
            "user_node_id": "node_id",
            "distinct_ips": "distinct_neighbors",
            recent_user_neighbors_col: combined_recent_neighbors_col,
        }
    )
    user_nodes["node_type"] = 0
    ip_nodes = ip_state.reset_index().rename(
        columns={
            "ip_node_id": "node_id",
            "distinct_users": "distinct_neighbors",
            recent_ip_neighbors_col: combined_recent_neighbors_col,
        }
    )
    ip_nodes["node_type"] = 1

    node_features = pd.concat([user_nodes, ip_nodes], ignore_index=True)
    node_features = node_features.sort_values("node_id").reset_index(drop=True)
    model_feature_columns = metadata["model_feature_columns"]
    count_features = [
        "total_logins", "successful_logins", "failed_logins",
        "distinct_neighbors", recent_logins_col, combined_recent_neighbors_col,
    ]
    node_features[count_features] = np.log1p(node_features[count_features])
    x_numpy = node_features[model_feature_columns].to_numpy(dtype=np.float32)
    if not np.isfinite(x_numpy).all():
        raise ValueError("Non-finite values found after incremental feature update.")

    structural_edges = pd.DataFrame(
        sorted(structural_edge_set),
        columns=["user_node_id", "ip_node_id"],
    ).astype(np.int64)
    forward_edges = structural_edges.to_numpy(dtype=np.int64).T
    reverse_edges = forward_edges[[1, 0], :]
    edge_index_numpy = np.concatenate([forward_edges, reverse_edges], axis=1)

    updated_graph = Data(
        x=torch.from_numpy(x_numpy),
        edge_index=torch.from_numpy(edge_index_numpy),
    )
    updated_graph.num_user_nodes = int(len(users_mapping))
    updated_graph.num_ip_nodes = int(len(ips_mapping))
    updated_graph.user_node_ids = torch.tensor(
        users_mapping["user_node_id"].to_numpy(dtype=np.int64), dtype=torch.long
    )
    updated_graph.ip_node_ids = torch.tensor(
        ips_mapping["global_ip_node_id"].to_numpy(dtype=np.int64), dtype=torch.long
    )
    updated_graph.cutoff_timestamp = final_cutoff.isoformat()
    updated_graph.recent_window_minutes = int(window_minutes)
    updated_graph.feature_names = model_feature_columns
    updated_graph.node_id_mapping_stable = True

    graph_valid = updated_graph.validate(raise_on_error=False)
    if not graph_valid:
        raise ValueError("Updated PyTorch Geometric graph failed validation.")

    # The recent buffer is persisted so a later stream chunk can continue from
    # this graph state without losing rolling-window history.
    recent_buffer_records = []
    recent_buffer_columns = [
        "organization", "Login Timestamp", "User ID", "IP Address",
        "LoginSuccessful", "is_synthetic", "credential_stuffing_label",
        "scenario_id", "campaign_id", "synthetic_credential_id",
        "is_reused_credential", "campaign_event_id",
    ]
    for event in recent_events:
        label_value = event.get("credential_stuffing_label", 0)
        if pd.isna(label_value):
            label_value = 0
        synthetic_value = event.get("is_synthetic", False)
        if pd.isna(synthetic_value):
            synthetic_value = False
        recent_buffer_records.append({
            "organization": event.get("organization", org_name),
            "Login Timestamp": event["Login Timestamp"],
            "User ID": event["User ID"],
            "IP Address": event["IP Address"],
            "LoginSuccessful": bool(event["LoginSuccessful"]),
            "is_synthetic": bool(synthetic_value),
            "credential_stuffing_label": int(label_value),
            "scenario_id": event.get("scenario_id"),
            "campaign_id": event.get("campaign_id"),
            "synthetic_credential_id": event.get("synthetic_credential_id"),
            "is_reused_credential": event.get("is_reused_credential"),
            "campaign_event_id": event.get("campaign_event_id"),
        })
    recent_buffer = pd.DataFrame(recent_buffer_records, columns=recent_buffer_columns)

    synthetic_mask = stream["is_synthetic"].fillna(False).astype(bool)
    label_mask = stream["credential_stuffing_label"].fillna(0).astype(int).eq(1)
    targeted_user_ids = set(stream.loc[synthetic_mask & label_mask, "User ID"].tolist())
    user_labels = users_mapping.copy()
    user_labels["y"] = user_labels["User ID"].isin(targeted_user_ids).astype(np.int64)
    user_labels["campaign_id"] = campaign_id
    user_labels["observation_start"] = start.isoformat()
    user_labels["observation_end"] = end.isoformat()

    output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(updated_graph.x, output_dir / f"{org_name.lower()}_node_features.pt")
    torch.save(updated_graph.edge_index, output_dir / f"{org_name.lower()}_edge_index.pt")
    torch.save(updated_graph, output_dir / f"{org_name.lower()}_graph.pt")

    _write_parquet(users_mapping, output_dir / f"{org_name.lower()}_user_mapping.parquet")
    _write_parquet(ips_mapping, output_dir / f"{org_name.lower()}_ip_mapping.parquet")
    _write_parquet(structural_edges, output_dir / f"{org_name.lower()}_structural_edges.parquet")
    _write_parquet(edge_state.reset_index(), output_dir / f"{org_name.lower()}_edge_state.parquet")
    _write_parquet(user_state.reset_index(), output_dir / f"{org_name.lower()}_user_state.parquet")
    _write_parquet(ip_state.reset_index(), output_dir / f"{org_name.lower()}_ip_state.parquet")
    _write_parquet(pd.DataFrame(event_updates), output_dir / f"{org_name.lower()}_event_state_updates.parquet")
    _write_parquet(user_labels, output_dir / f"{org_name.lower()}_user_labels.parquet")
    _write_parquet(recent_buffer, output_dir / f"{org_name.lower()}_recent_event_buffer.parquet")

    updated_metadata = dict(metadata)
    updated_metadata.update({
        "organization": org_name,
        "graph_type": "persistent_temporal_user_ip_incrementally_updated",
        "base_cutoff_timestamp": base_cutoff.isoformat(),
        "cutoff_timestamp": final_cutoff.isoformat(),
        "recent_window_minutes": window_minutes,
        "num_users": int(len(users_mapping)),
        "num_ips": int(len(ips_mapping)),
        "num_nodes": int(updated_graph.num_nodes),
        "num_structural_edges": int(len(structural_edges)),
        "num_directed_edges": int(updated_graph.num_edges),
        "num_node_features": int(updated_graph.num_node_features),
        "campaign_id": campaign_id,
        "stream_start": start.isoformat(),
        "stream_end_exclusive": end.isoformat(),
        "stream_event_count": int(len(stream)),
        "synthetic_event_count": int(synthetic_mask.sum()),
        "targeted_user_count": int(user_labels["y"].sum()),
        "new_node_count": int(updated_graph.num_nodes - graph.num_nodes),
        "graph_validation": bool(graph_valid),
        "node_id_mapping_stable": True,
    })
    with open(output_dir / f"{org_name.lower()}_graph_metadata.json", "w", encoding="utf-8") as handle:
        json.dump(updated_metadata, handle, indent=2)

    print("\n" + "=" * 60)
    print(f"{org_name} TEMPORAL GRAPH UPDATE COMPLETE")
    print("=" * 60)
    print("Base cutoff:", base_cutoff)
    print("Final cutoff:", final_cutoff)
    print("Stream events applied:", len(stream))
    print("Synthetic events:", int(synthetic_mask.sum()))
    print("New users:", len(users_mapping) - int(metadata["num_users"]))
    print("New IPs:", len(ips_mapping) - int(metadata["num_ips"]))
    print("Final users:", len(users_mapping))
    print("Final IPs:", len(ips_mapping))
    print("Final nodes:", updated_graph.num_nodes)
    print("Final structural edges:", len(structural_edges))
    print("Final directed edges:", updated_graph.num_edges)
    print("Targeted users labelled y=1:", int(user_labels["y"].sum()))
    print("Feature values finite:", bool(np.isfinite(x_numpy).all()))
    print("Graph validation:", bool(graph_valid))
    print("Saved updated graph to:", output_dir)
    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally apply a chronological local event stream to an "
            "existing temporal User-IP graph state."
        )
    )
    parser.add_argument("--org-id", type=int, required=True, choices=[1, 2, 3, 4, 5])
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--start", required=True, help="Inclusive ISO stream start timestamp.")
    parser.add_argument("--end", required=True, help="Exclusive ISO stream end timestamp.")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Optional prior graph-state directory; defaults to data/processed_temporal/orgN.",
    )
    parser.add_argument("--stream-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    update_temporal_graph(
        org_id=args.org_id,
        campaign_id=args.campaign_id,
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        base_dir=args.base_dir,
        stream_path=args.stream_path,
        output_dir=args.output_dir,
    )
