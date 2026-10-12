"""Build seeds/ba_reference.csv from EIA's official EIA-930 reference tables.

    uv run --no-project --with openpyxl python transform/scripts/build_ba_reference.py

Source: https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx (sheet "BAs").
Only U.S. balancing authorities are kept. Two columns are GridPulse modeling choices, not EIA data:

- time_zone: the IANA zone where the BA operates, used for local hour/date and peak flags.
  EIA's "Time Zone" (kept as eia_time_zone) is the reporting convention, and "Arizona" there
  means MST all year even for BAs in places that observe DST (EPE, PNM, WACM).
- interconnection: derived from EIA region (TEX = ERCOT; CAL/NW/SW = Western; else Eastern),
  with WAUE overridden to Eastern (WAPA Upper Great Plains East sits in the Eastern
  Interconnection).
"""

import csv
import io
import urllib.request
from datetime import datetime
from pathlib import Path

import openpyxl

URL = "https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx"
OUT = Path(__file__).resolve().parents[1] / "seeds" / "ba_reference.csv"

LABEL_TO_IANA = {
    "Eastern": "America/New_York",
    "Central": "America/Chicago",
    "Mountain": "America/Denver",
    "Pacific": "America/Los_Angeles",
    "Arizona": "America/Phoenix",
}
# EIA reports these in "Arizona" time (MST, no DST) but they are located where DST applies.
IANA_OVERRIDES = {"EPE": "America/Denver", "PNM": "America/Denver", "WACM": "America/Denver"}
WESTERN_REGIONS = {"CAL", "NW", "SW"}
INTERCONNECTION_OVERRIDES = {"WAUE": "Eastern"}


def iso_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return datetime.strptime(str(value).strip(), "%m/%d/%Y").date().isoformat()


def yes(value) -> str:
    return "true" if str(value).strip().lower() == "yes" else "false"


def main() -> None:
    with urllib.request.urlopen(URL, timeout=60) as resp:
        wb = openpyxl.load_workbook(io.BytesIO(resp.read()), read_only=True, data_only=True)
    rows = list(wb["BAs"].iter_rows(values_only=True))
    header = rows[0]
    records = [dict(zip(header, r, strict=False)) for r in rows[1:] if r and r[0]]

    out = []
    for r in records:
        if yes(r["U.S. BA"]) != "true":
            continue
        code, region = r["BA Code"].strip(), r["Region/Country Code"].strip()
        label = (r["Time Zone"] or "").strip()
        if region == "TEX":
            interconnection = "ERCOT"
        elif region in WESTERN_REGIONS:
            interconnection = "Western"
        else:
            interconnection = "Eastern"
        out.append(
            {
                "ba_code": code,
                "ba_name": r["BA Name"].strip(),
                "region_code": region,
                "region_name": r["Region/Country Name"].strip(),
                "interconnection": INTERCONNECTION_OVERRIDES.get(code, interconnection),
                "eia_time_zone": label,
                "time_zone": IANA_OVERRIDES.get(code, LABEL_TO_IANA[label]),
                "is_generation_only": yes(r["Generation Only BA"]),
                "is_active": yes(r["Active BA"]),
                "activation_date": iso_date(r["Activation Date"]),
                "retirement_date": iso_date(r["Retirement Date"]),
            }
        )
    out.sort(key=lambda x: x["ba_code"])
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(out[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(out)
    OUT.write_text(buf.getvalue())
    print(f"wrote {len(out)} BAs to {OUT}")


if __name__ == "__main__":
    main()
