from pathlib import Path

import duckdb

from src.phase6.audit_splits import input_view


def test_file_allowlist_view_uses_bindable_relation_api():
    root = Path(__file__).resolve().parents[2]
    file = root / 'data/phase5/controlled_replay_labels_all_orgs_causal_v1/CFV1_SO_CS_027_SEED1001_TRAIN/Org1_labels.parquet'
    with duckdb.connect(':memory:') as db:
        input_view(db, 'labels', [file.as_posix()])
        count, names = db.execute('SELECT count(*),count(DISTINCT filename) FROM labels').fetchone()
        assert count > 0 and names == 1
