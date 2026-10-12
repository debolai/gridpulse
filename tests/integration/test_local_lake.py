"""A1 check: Trino can create, write and read an Iceberg table in the local lake.

Each run uses its own `test_<run_id>` schema and drops it afterwards, even on failure.
"""

import uuid

import pytest
import trino

pytestmark = pytest.mark.integration


@pytest.fixture
def cursor():
    try:
        conn = trino.dbapi.connect(
            host="localhost", port=8080, user="gridpulse-test", catalog="lake"
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()
    except Exception as exc:
        pytest.fail(f"Trino not reachable on localhost:8080 — run `make up-lake` first ({exc})")
    yield cur
    conn.close()


@pytest.fixture
def schema(cursor):
    name = f"test_{uuid.uuid4().hex[:8]}"
    cursor.execute(f"CREATE SCHEMA lake.{name}")
    cursor.fetchall()
    yield name
    cursor.execute(f"SHOW TABLES FROM lake.{name}")
    for (table,) in cursor.fetchall():
        cursor.execute(f"DROP TABLE lake.{name}.{table}")
        cursor.fetchall()
    cursor.execute(f"DROP SCHEMA lake.{name}")
    cursor.fetchall()


def test_iceberg_round_trip(cursor, schema):
    table = f"lake.{schema}.grid_probe"
    cursor.execute(
        f"""
        CREATE TABLE {table} (ba_code varchar, period_utc timestamp(6), demand_mwh double)
        WITH (partitioning = ARRAY['month(period_utc)'])
        """
    )
    cursor.fetchall()
    cursor.execute(
        f"""
        INSERT INTO {table} VALUES
            ('PJM', TIMESTAMP '2026-10-01 00:00:00', 80956.0),
            ('ERCO', TIMESTAMP '2026-10-01 00:00:00', 45120.5)
        """
    )
    cursor.fetchall()

    cursor.execute(f"SELECT ba_code, demand_mwh FROM {table} ORDER BY ba_code")
    assert cursor.fetchall() == [["ERCO", 45120.5], ["PJM", 80956.0]]

    # The table really is Iceberg: its metadata tables exist and show the write.
    cursor.execute(f'SELECT count(*) FROM {table.rsplit(".", 1)[0]}."grid_probe$snapshots"')
    assert cursor.fetchall()[0][0] >= 1
