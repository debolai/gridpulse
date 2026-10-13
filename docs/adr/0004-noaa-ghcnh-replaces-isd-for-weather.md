# ADR-0004: NOAA GHCNh replaces ISD (Global Hourly) as the weather source

Status: Accepted
Date: 2026-10-13

## Context
The blueprint reads hourly station weather from NOAA's Integrated Surface Database (ISD,
"Global Hourly") on the AWS Open Data Registry (`noaa-global-hourly-pds`). NOAA stopped
updating ISD in August 2025: the bucket has no 2026 folder and its newest files date from
October 2025, so it cannot supply the July 2026 onward window the platform loads. NCEI points
users to its successor, GHCNh (Global Historical Climatology Network hourly), published in the
public bucket `noaa-ghcnh-pds` as one Parquet file per station and year, refreshed daily
(2026 files were updated 2026-10-12; latest observations about 1.5 days old).

## Decision
Read weather from GHCNh (`noaa-ghcnh-pds/hourly/access/by-year/<year>/parquet/`) anonymously.
The blueprint's reasons for NOAA on AWS Open Data still hold (public domain, in AWS, no rate
limits), so only the dataset changes:
- Units are SI and missing values are null, so the ISD tenths-of-a-degree and `9999` parsing
  is not needed.
- Quality codes follow NOAA's GHCNh documentation: lower-case letters are GHCNh's failed checks,
  legacy source codes 2/6 are suspect and 3/7 erroneous. Failed readings are kept and flagged.
- Stations report several times an hour; every report is kept raw, and the hourly value is the
  mean of the QC-passed reports in the hour.
- The raw copy is the append-only Iceberg table `raw.noaa_ghcnh_observations`; the source files
  are not copied again to the raw bucket (NOAA's archive is the original).
- Station ids are GHCNh ids (`USW000` + WBAN for U.S. airports), checked against NOAA's
  `ghcnh-station-list.csv`.

## Alternatives considered
- Stay on ISD: no data after August 2025.
- Open-Meteo (the blueprint's fallback): a modelled reanalysis behind a rate-limited API, not
  station observations; kept as the fallback if GHCNh coverage proves thin.
- NCEI's Access Data Service API: rate-limited, and the AWS bucket is the same data.

## Consequences
- Weather lags EIA by about 1.5 days; `fct_grid_hourly` rebuilds hours whose weather changed
  on a later run, so temperatures fill in without a full refresh.
- History before 2026 is also in GHCNh (by-year files back to the station's start), so the
  July 2018 backfill works the same way.
- GHCNh is versioned (v1.1.0 at the time of writing); a column change would fail the reader's
  fixed column list loudly rather than load wrong values.
