"""Re-record the NOAA GHCNh fixture from the public bucket (no credentials needed).

Keeps two days of Chicago O'Hare (USW00094846) reports, only the columns the extractor reads,
so tests run on real GHCNh rows: several reports per hour, rows without temperature, and
quality codes. Re-record if NOAA changes the file layout:

    uv run python ingestion/tests/fixtures/record_noaa.py
"""

import io
from pathlib import Path

import boto3
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from botocore import UNSIGNED
from botocore.config import Config

from gridpulse_ingestion.noaa import ghcnh

OUT = Path(__file__).parent / "noaa_ghcnh" / "GHCNh_USW00094846_2026.parquet"
STATION, YEAR, MONTH, DAYS = "USW00094846", 2026, "10", ("09", "10")


def main() -> None:
    s3 = boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED))
    body = s3.get_object(Bucket=ghcnh.BUCKET, Key=ghcnh.station_year_key(STATION, YEAR))
    table = pq.read_table(io.BytesIO(body["Body"].read()), columns=list(ghcnh.SOURCE_COLUMNS))
    in_days = pc.is_in(table["Day"], value_set=pa.array(DAYS))
    keep = pc.and_(pc.equal(table["Month"], MONTH), in_days)
    OUT.parent.mkdir(exist_ok=True)
    pq.write_table(table.filter(keep), OUT)
    print(OUT, table.filter(keep).num_rows, "rows")


if __name__ == "__main__":
    main()
