# Project Summary Report - DDOT Maintenance Operations GIS Analysis

_Generated 2026-10-27T01:44:07+00:00 (UTC) by `01_pull_and_process_data.py` v2.3.0, run `e4c1488c-8a9a-4daa-82f4-b85d693a57ee`._

## Purpose

Identify roadway subblocks where **active excavation/paving renewal permits** coincide with
**open roadway repair, pothole and paving service requests**, so Maintenance Operations can
coordinate repairs with permitted work and avoid duplicate or wasted effort.

## Key Findings

| Metric | Value |
| --- | --- |
| Roadway subblocks analysed (Street / Service Road / Ramp) | 23,104 |
| Qualifying permit work-location records retrieved | 9,341 |
| Distinct qualifying permits (`PermitNumber`) | 2,086 |
| Permit records snapped to a centerline (<= 150 ft) | 9,286 (99.4%) |
| Open service requests retrieved | 666 |
| Service requests matched to a subblock (<= 150 ft) | 649 (97.4%) |
| Distinct locations among matched service requests | 606 |
| Subblocks with at least one permit | 2,621 |
| Subblocks with at least one open SR | 534 |
| **Dual-conflict subblocks (permit AND open SR)** | **96** |
| Roadway blocks (BLOCKID) analysed | 14,541 |
| Blocks with both permits and open SRs (any subblock) | 134 |

### Subblocks by activity class

| Activity class | Subblocks |
| --- | --- |
| Permit + SR | 96 |
| Permit only | 2525 |
| SR only | 438 |
| No activity | 20045 |

### Activity class by roadway type

| ACTIVITY_CLASS | ROADWAY_TYPE | SUBBLOCKS | CENTERLINE_MILES |
| --- | --- | --- | --- |
| Permit + SR | STREET | 96 | 8.76 |
| Permit only | RAMP | 3 | 0.28 |
| Permit only | SERVICE LANE | 4 | 0.38 |
| Permit only | STREET | 2518 | 145.98 |
| SR only | RAMP | 4 | 0.55 |
| SR only | SERVICE LANE | 3 | 0.25 |
| SR only | STREET | 431 | 32.55 |
| No activity | RAMP | 583 | 43.17 |
| No activity | SERVICE LANE | 114 | 8.53 |
| No activity | STREET | 19348 | 992.74 |

### Activity by ward

| WARD | SUBBLOCKS | SUBBLOCKS_WITH_PERMITS | SUBBLOCKS_WITH_SRS | DUAL_CONFLICT_SUBBLOCKS | DISTINCT_PERMITS | PERMIT_LOCATIONS | OPEN_SRS | DISTINCT_SR_LOCATIONS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1422 | 274 | 46 | 17 | 242 | 1152 | 56 | 52 |
| 2 | 2699 | 332 | 35 | 5 | 286 | 585 | 36 | 36 |
| 3 | 3151 | 253 | 77 | 10 | 239 | 462 | 91 | 85 |
| 4 | 3723 | 340 | 72 | 12 | 244 | 892 | 83 | 81 |
| 5 | 3579 | 503 | 87 | 12 | 361 | 2220 | 103 | 96 |
| 6 | 2409 | 400 | 82 | 24 | 311 | 1654 | 110 | 101 |
| 7 | 3430 | 329 | 65 | 9 | 251 | 1485 | 81 | 76 |
| 8 | 2691 | 190 | 70 | 7 | 153 | 836 | 89 | 79 |

### Top 25 dual-conflict subblocks (ranked by distinct permits + distinct SR locations)

The full ranked list is in the `insight_top_conflicts` table. `DISTINCT_PERMIT_COUNT` counts unique
permits; `PERMIT_COUNT` counts their work-location addresses on the subblock. `DISTINCT_SR_LOCATIONS`
counts unique SR locations; `SR_COUNT` includes repeat reports geocoded to the same point.
`MIN_PERMIT_EFF_DATE` -> `MAX_PERMIT_EXP_DATE` is the permitted work window on the subblock;
`MIN_SR_INIT_DATE` is the oldest open SR (how long the defect has waited).

| RANK | SUBBLOCK_UID | ROUTENAME | ROADWAY_TYPE | FROMSTREET | TOSTREET | WARD_ID | DISTINCT_PERMIT_COUNT | PERMIT_COUNT | DISTINCT_SR_LOCATIONS | SR_COUNT | MIN_PERMIT_EFF_DATE | MAX_PERMIT_EXP_DATE | MIN_SR_INIT_DATE | MAX_SR_INIT_DATE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 77bfe3cd2cf15a87899243563c51f616 | BRANCH AVE SE | STREET | Block Only | Block Only | 7 | 1 | 2 | 6 | 9 | 2026-09-14 | 2026-11-12 | 2026-04-08 | 2026-10-08 |
| 2 | d735ae7ae8b7d7ddd3e1f0b4cb86ff29 | PARKER ST NE | STREET | Block Only | Block Only | 6 | 1 | 1 | 3 | 3 | 2026-09-20 | 2026-11-18 | 2026-05-12 | 2026-09-02 |
| 3 | 378334b6686b78f531493d64f1e2b32c | MOUNT PLEASANT ST NW | STREET | Block Only | Block Only | 1 | 2 | 2 | 2 | 2 | 2026-09-13 | 2026-11-25 | 2025-10-08 | 2026-10-15 |
| 4 | cfb9370629e483ed43abb4333a1ecaa0 | IRVING ST NE | STREET | Block Only | Block Only | 5 | 3 | 14 | 1 | 1 | 2026-08-30 | 2026-12-27 | 2026-08-16 | 2026-08-16 |
| 5 | e37390f4ebfd137745b1131c493c9cef | RHODE ISLAND AVE NE | STREET | Block Only | Block Only | 5 | 3 | 3 | 1 | 1 | 2026-09-29 | 2027-01-13 | 2026-10-25 | 2026-10-25 |
| 6 | e10deeafbaf9dcb255bfac2fd246a243 | HAWAII AVE NE | STREET | Block Only | Block Only | 5 | 1 | 1 | 2 | 4 | 2026-03-19 | 2027-03-18 | 2025-12-29 | 2026-09-27 |
| 7 | 5a83ea43146dd3f8f5b511fb04de1c1f | C ST SE | STREET | Block Only | Block Only | 6 | 1 | 1 | 2 | 3 | 2026-10-14 | 2026-12-12 | 2026-07-10 | 2026-09-29 |
| 8 | 5d332fe51293ecf482f0e357d46dd737 | RESERVOIR RD NW | STREET | Block Only | Block Only | 2 | 1 | 22 | 2 | 2 | 2026-09-20 | 2026-11-18 | 2025-10-13 | 2026-09-28 |
| 9 | 52d5fe9948370228babf675f1297f3cf | DAHLIA ST NW | STREET | Block Only | Block Only | 4 | 1 | 3 | 2 | 2 | 2026-10-05 | 2026-12-03 | 2026-06-15 | 2026-09-17 |
| 10 | ac69328a4c542af91403a9eae58dacc4 | D ST SE | STREET | Block Only | Block Only | 6 | 1 | 3 | 2 | 2 | 2026-09-12 | 2026-11-10 | 2026-04-28 | 2026-10-25 |
| 11 | 379671b0212526e68032c8f02a3ae9af | 17TH ST NW | STREET | Block Only | Block Only | 1 | 1 | 1 | 2 | 2 | 2026-09-06 | 2026-11-04 | 2026-06-02 | 2026-06-04 |
| 12 | 886c0697f520ca152ddc91ba0d2ed176 | A ST SE | STREET | Block Only | Block Only | 7 | 1 | 1 | 2 | 2 | 2026-09-01 | 2026-10-30 | 2026-03-16 | 2026-09-02 |
| 13 | a15303de3a4a885e9f757577a2900f6b | IRVING ST NW | STREET | Block Only | Block Only | 1 | 1 | 1 | 2 | 2 | 2026-07-30 | 2026-10-27 | 2026-06-18 | 2026-10-22 |
| 14 | c51c84b380f92f35d1cfb6101f5a8a3c | 13TH ST NW | STREET | Block Only | Block Only | 4 | 1 | 1 | 2 | 2 | 2026-09-14 | 2026-12-31 | 2026-06-03 | 2026-09-22 |
| 15 | f11918e96a4bd95fd8df1c08347aacb1 | BRENTWOOD RD NE | STREET | Block Only | Block Only | 5 | 1 | 1 | 2 | 2 | 2026-08-30 | 2026-11-27 | 2026-08-23 | 2026-10-19 |
| 16 | f6a34e1a04f0126515c0c7990cf8e45f | OGLETHORPE ST NE | STREET | Block Only | Block Only | 4 | 1 | 1 | 2 | 2 | 2026-09-16 | 2026-11-16 | 2026-07-06 | 2026-07-06 |
| 17 | 735d51c6f7576925a4b4ff940c84ce7d | QUEBEC PL NW | STREET | Block Only | Block Only | 1 | 2 | 51 | 1 | 2 | 2026-09-03 | 2026-11-09 | 2026-09-17 | 2026-10-03 |
| 18 | c0b0ab911de8bb16c0a342158aead74a | K ST NE | STREET | Block Only | Block Only | 6 | 2 | 2 | 1 | 2 | 2026-09-21 | 2027-01-18 | 2026-10-08 | 2026-10-10 |
| 19 | 5da23f27bb623ec7b3158a9886ff4e6e | 10TH ST NW | STREET | Block Only | Block Only | 1 | 2 | 39 | 1 | 1 | 2026-09-18 | 2026-12-06 | 2026-10-22 | 2026-10-22 |
| 20 | 6c136b7900c1d187f38bdb5b57646013 | COLUMBIA RD NW | STREET | Block Only | Block Only | 1 | 2 | 34 | 1 | 1 | 2026-10-07 | 2026-12-12 | 2026-09-03 | 2026-09-03 |
| 21 | 1badce50290e8f6ebbf000af7843cf75 | KRAMER ST NE | STREET | Block Only | Block Only | 7 | 2 | 3 | 1 | 1 | 2026-08-18 | 2026-11-15 | 2026-09-03 | 2026-09-03 |
| 22 | 7c0eae28dac7d6476523d552f550ca6d | PENNSYLVANIA AVE SE | STREET | Block Only | Block Only | 6 | 2 | 3 | 1 | 1 | 2026-09-30 | 2026-11-29 | 2026-08-17 | 2026-08-17 |
| 23 | 983941833a23f2ec33709ac7f818b579 | 9TH ST NE | STREET | Block Only | Block Only | 6 | 2 | 3 | 1 | 1 | 2026-08-15 | 2026-12-15 | 2026-05-29 | 2026-05-29 |
| 24 | 0789db615b847b1d1da455fa2e620914 | 1ST ST NE | STREET | Block Only | Block Only | 4 | 2 | 2 | 1 | 1 | 2026-09-09 | 2026-11-07 | 2026-02-13 | 2026-02-13 |
| 25 | 1de7d81850bf9cf65bf9cae00a1233ae | CALVERT ST NW | STREET | Block Only | Block Only | 3 | 2 | 2 | 1 | 1 | 2026-09-20 | 2026-12-21 | 2026-06-22 | 2026-06-22 |

## Recommendations

1. Review the dual-conflict subblocks above with permit holders before dispatching crews; where the
   permittee's restoration obligation covers the reported defect, route the SR to permit enforcement.
2. Hold planned repaving on subblocks with permits expiring after the planned work date.
3. Use the block view (`roadway_block_enriched`) to bundle nearby work on the same block into one dispatch.
4. Re-run the pipeline on a regular cadence (it is fully automated) to keep the overlap list current.

## Data Quality Notes

* The permits service stores one row per work-location address, so a multi-address permit appears
  several times: 9,341 rows represent 2,086 distinct permits.
  `PERMIT_COUNT` counts rows (work footprint); `DISTINCT_PERMIT_COUNT` counts permits and drives the ranking.
* Repeat service requests at the same location (often block-range addresses such as
  "2900 - 2999 BLOCK OF ...", geocoded to one point) count once in `DISTINCT_SR_LOCATIONS`:
  649 matched requests sit at 606 distinct locations.
* Open SR status mix: INSPCOMP 272; OPEN 203; PENDING 190; GEO ISSUE 1. Only CLOSED / CANCEL / COMPLETE are
  excluded, so `INSPCOMP` (inspection complete) counts as open - **confirm this definition with the requester**.
* `CSRNUMBER` is published but empty on every service request; `REQUESTID` is used as the request identifier.
* Permit records further than 150 ft from any qualifying subblock are kept in `permits_snapped`
  with `SNAPPED = 0` and no `SUBBLOCK_UID`: 55 record(s).
* Service requests further than 150 ft from a qualifying subblock (e.g. located on
  alleys or driveways) are not counted: 17 request(s).
* Permit snap displacement: median 2.4 ft, 95th percentile 44.8 ft, max 149.8 ft (see `qa_permit_snap_displacement`).
* Subblocks without a BLOCKID are treated as single-subblock blocks: 711.
* Features with null geometry dropped: permits 0, service requests 0.
* Dates are stored in UTC in the GeoPackage and shown here in America/New_York.

## Definition Queries Used

* **Subblocks:** `ROADTYPE IN ('1', '2', '3')`
* **Permits:** `ExpirationDate >= timestamp '2025-10-01 00:00:00' AND Renewal = 2 AND StatusDescription IN ('Issued') AND (IsExcavation = 1 OR IsPaving = 1)`
* **Service requests:** `STATUS NOT IN ('CLOSED', 'CANCEL', 'COMPLETE') AND DESCRIPTION IN ('ROADWAY REPAIR', 'POTHOLES', 'STREET REPAVING', 'STREET REPAIR', 'STREET PAVING SCHEDU') AND INITIATEDDATE >= timestamp '2025-10-01 00:00:00'`
