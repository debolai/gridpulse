# A data issue the platform caught: EIA's regional totals posing as balancing authorities

**In one line:** loaded for every balancing authority, EIA's API also returned its own regional
and national totals as if they were BAs, which would have made "total U.S. demand" exactly three
times too high. Data tests stopped the build before any metric was served.

## What happened

The EIA-930 API serves hourly demand, generation and interchange per *respondent*. During
development the pipeline asked for six named BAs, so every respondent was a BA. The one-year
backfill on AWS asked for **all** respondents instead (ADR-0005), and EIA answered with three
kinds:

| Respondent kind | Count | Example codes | July 2026 demand |
| --- | --- | --- | --- |
| Balancing authorities | 53 | PJM, ERCO, CISO, MISO | 445.6 TWh |
| EIA regions (sums of BAs) | 13 | CAL, TEX, MIDA, NY | 445.6 TWh |
| Lower 48 (sum of everything) | 1 | US48 | 445.6 TWh |

Each line already contains the others' energy. Summed together, as any `SUM(demand)` over the
table would, July demand reads **1,336.8 TWh instead of 445.6**. The same applied to generation
by fuel and to interchange, where the aggregates appear as region-to-region flows.

## How it was caught

Not by a person reading numbers: by the dbt tests on the first all-BA build on Athena. Every fact
table has a `relationships` test from `ba_code` to `dim_balancing_authority`, which is built from
EIA's reference list of real BAs. The aggregate codes aren't in that list, so the build stopped:

| Test | Rows failing |
| --- | --- |
| `relationships` `fct_grid_hourly.ba_code` → `dim_balancing_authority` | 126,672 |
| `relationships` `fct_interchange_hourly.ba_code` → `dim_balancing_authority` | 336,464 |
| `relationships` `fct_generation_by_fuel_hourly.ba_code` → `dim_balancing_authority` | 1,342,791 |

The six-BA sample had never exercised this path, which is the point of running the same tests
at full scale.

## The fix

- A seed, `eia_aggregate_respondents` (13 regions and US48, with their level), lists EIA's
  aggregate codes. Staging drops those respondents in all three routes; **raw keeps them**, so
  nothing is deleted and a regional mart can use them later.
- A singular test, `assert_aggregate_respondents_are_not_bas`, fails if a code in the seed is
  ever also a real BA, because then the filter would silently remove a balancing authority.
- After the fix the tests passed on both engines (Athena PASS=111, Trino PASS=114 at the time).

## Turned into a check

Kept in raw, EIA's own totals became an **independent reference**. The coincident-peak metric
sums BAs per hour itself (ADR-0008); compared with EIA's published aggregates over a year, the
peaks match exactly (US48 753,630 MW at 2026-07-02 22:00 UTC, all 53 BAs reporting; CAL 61,700;
TEX 91,075), the median hourly gap is 0, and the 99th percentile gap is 1.1%. After flagged
values were excluded from metrics (B3), the same comparison still matched.

## Lessons

- Test **referential integrity** to a curated dimension, not just `not_null`. A code that "looks
  like" a BA is the dangerous case.
- Run the full-scale load through the same tests as the sample; the sample's shape hid this.
- Filter in staging, keep raw untouched, and test the filter itself.
