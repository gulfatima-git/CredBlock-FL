from pathlib import Path
import duckdb

start = "2020-08-01 12:00:00"
end = "2020-08-01 13:00:00"

for path in sorted(
    Path("data/organizations").glob(
        "organization=*/data_0.parquet"
    )
):
    count = duckdb.sql(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{path.as_posix()}')
        WHERE "Login Timestamp" >= TIMESTAMP '{start}'
          AND "Login Timestamp" < TIMESTAMP '{end}'
        """
    ).fetchone()[0]

    print(path.parent.name, count)