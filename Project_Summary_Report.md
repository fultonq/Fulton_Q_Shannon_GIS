# Project Summary Report - DDOT Maintenance Operations GIS Analysis

_Generated 2026-10-14T15:17:32+00:00 (UTC) by `01_pull_and_process_data.py` v2.0.0, run `a8a3aaba-0ad9-4544-8479-7e609b4d19a6`._

## Purpose

Identify roadway subblocks where **active excavation/paving renewal permits** coincide with
**open roadway repair, pothole and paving service requests**, so Maintenance Operations can
coordinate repairs with permitted work and avoid duplicate or wasted effort.

## Key Findings

| Metric | Value |
| --- | --- |
| Roadway subblocks analysed (Street / Service Road / Ramp) | 23,104 |
| Qualifying permits retrieved | 7,934 |
| Permits snapped to a centerline (<= 150 ft) | 7,829 (98.7%) |
| Open service requests retrieved | 692 |
| Service requests matched to a subblock (<= 150 ft) | 674 (97.4%) |
| Subblocks with at least one permit | 2,462 |
| Subblocks with at least one open SR | 567 |
| **Dual-conflict subblocks (permit AND open SR)** | **106** |
| Roadway blocks (BLOCKID) analysed | 14,541 |
| Blocks with both permits and open SRs (any subblock) | 139 |

### Subblocks by activity class

| Activity class | Subblocks |
| --- | --- |
| Permit + SR | 106 |
| Permit only | 2356 |
| SR only | 461 |
| No activity | 20181 |

### Activity class by roadway type

| ACTIVITY_CLASS | ROADWAY_TYPE | SUBBLOCKS | CENTERLINE_MILES |
| --- | --- | --- | --- |
| Permit + SR | STREET | 106 | 8.74 |
| Permit only | RAMP | 2 | 0.25 |
| Permit only | SERVICE LANE | 6 | 0.45 |
| Permit only | STREET | 2348 | 137.65 |
| SR only | RAMP | 5 | 0.66 |
| SR only | SERVICE LANE | 3 | 0.25 |
| SR only | STREET | 453 | 35.43 |
| No activity | RAMP | 583 | 43.09 |
| No activity | SERVICE LANE | 112 | 8.46 |
| No activity | STREET | 19486 | 998.21 |

### Activity by ward

| WARD | SUBBLOCKS | SUBBLOCKS_WITH_PERMITS | SUBBLOCKS_WITH_SRS | DUAL_CONFLICT_SUBBLOCKS | PERMITS | OPEN_SRS |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1422 | 236 | 49 | 18 | 776 | 59 |
| 2 | 2699 | 327 | 39 | 7 | 518 | 40 |
| 3 | 3151 | 251 | 84 | 10 | 451 | 98 |
| 4 | 3723 | 334 | 70 | 8 | 825 | 81 |
| 5 | 3579 | 440 | 93 | 14 | 1788 | 106 |
| 6 | 2409 | 370 | 82 | 27 | 1367 | 105 |
| 7 | 3430 | 320 | 71 | 11 | 1322 | 88 |
| 8 | 2691 | 184 | 79 | 11 | 782 | 97 |

### Top 25 dual-conflict subblocks (ranked by permits + SRs)

The full ranked list is in the `insight_top_conflicts` table.

| RANK | SUBBLOCK_UID | ROUTENAME | ROADWAY_TYPE | FROMSTREET | TOSTREET | WARD_ID | PERMIT_COUNT | SR_COUNT | MAX_PERMIT_EXP_DATE | MAX_SR_INIT_DATE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 735d51c6f7576925a4b4ff940c84ce7d | QUEBEC PL NW | STREET | Block Only | Block Only | 1 | 54 | 2 | 2026-11-09 | 2026-10-03 |
| 2 | d730f0518e4f6077825a0745c8613078 | FARRAGUT ST NW | STREET | Block Only | Block Only | 4 | 25 | 1 | 2026-12-06 | 2026-09-05 |
| 3 | 5d332fe51293ecf482f0e357d46dd737 | RESERVOIR RD NW | STREET | Block Only | Block Only | 2 | 22 | 2 | 2026-11-18 | 2026-09-28 |
| 4 | 6c3a1f4813c371cfc4ef52754e91e7a4 | RHODE ISLAND AVE NW | STREET | Block Only | Block Only | 1 | 19 | 2 | 2026-11-13 | 2026-09-04 |
| 5 | f8c7b6d88bc6b5a77bdff560b495a0b8 | S ST SE | STREET | Block Only | Block Only | 7 | 19 | 2 | 2026-11-29 | 2026-07-24 |
| 6 | 2a3406eeb12428c444355e8fdc4513c8 | S ST SE | STREET | Block Only | Block Only | 7 | 17 | 1 | 2026-11-29 | 2026-07-30 |
| 7 | 608aaea07f4f16a0183bb182391fbc52 | 31ST PL NW | STREET | Block Only | Block Only | 4 | 17 | 1 | 2027-03-28 | 2026-06-29 |
| 8 | cfb9370629e483ed43abb4333a1ecaa0 | IRVING ST NE | STREET | Block Only | Block Only | 5 | 14 | 1 | 2026-12-27 | 2026-08-16 |
| 9 | 77bfe3cd2cf15a87899243563c51f616 | BRANCH AVE SE | STREET | Block Only | Block Only | 7 | 2 | 10 | 2026-11-12 | 2026-10-13 |
| 10 | 1cbc7331935dd6c7a7324a859b26809f | 5TH ST NE | STREET | Block Only | Block Only | 6 | 11 | 1 | 2026-10-16 | 2026-08-20 |
| 11 | 8671acee8b705fae98600b5637735e6d | PERRY ST NE | STREET | Block Only | Block Only | 5 | 10 | 1 | 2026-11-26 | 2026-10-07 |
| 12 | d6cd5ecc541b87ce2a610132fa514843 | 4TH ST NE | STREET | Block Only | Block Only | 6 | 10 | 1 | 2026-12-05 | 2026-07-10 |
| 13 | c15bcfb8378ead433aa4e7626e45323b | 18TH ST NE | STREET | Block Only | Block Only | 5 | 6 | 3 | 2026-11-30 | 2026-10-12 |
| 14 | d77cfe4c75b550c90dd4e29da415aede | 15TH ST NE | STREET | Block Only | Block Only | 6 | 8 | 1 | 2026-11-20 | 2026-09-23 |
| 15 | 09e09a5055680d4d2611f9b1bc6be5f9 | EAST CAPITOL ST NE | STREET | Block Only | Block Only | 7 | 6 | 1 | 2026-11-16 | 2026-03-18 |
| 16 | 4712d02bf1d1c7524e484df55e7f4dc3 | 6TH ST NE | STREET | Block Only | Block Only | 6 | 5 | 1 | 2026-12-05 | 2026-08-05 |
| 17 | 987ddccf00d9366540beb522476e7618 | D ST NE | STREET | Block Only | Block Only | 6 | 5 | 1 | 2026-10-21 | 2026-08-30 |
| 18 | e10deeafbaf9dcb255bfac2fd246a243 | HAWAII AVE NE | STREET | Block Only | Block Only | 5 | 1 | 4 | 2027-03-18 | 2026-09-27 |
| 19 | ff4631905ca85b15de0cfc018535b285 | M ST NW | STREET | Block Only | Block Only | 2 | 4 | 1 | 2026-12-16 | 2026-08-22 |
| 20 | 6885ff0fa2f62ed418e5f63fbbfd34c5 | 2ND ST NE | STREET | Block Only | Block Only | 6 | 1 | 3 | 2026-11-30 | 2026-08-06 |
| 21 | a6be4ee26571dd36f85e4c2e63f50374 | HOWARD RD SE | STREET | Block Only | Block Only | 8 | 1 | 3 | 2026-11-29 | 2026-07-27 |
| 22 | d735ae7ae8b7d7ddd3e1f0b4cb86ff29 | PARKER ST NE | STREET | Block Only | Block Only | 6 | 1 | 3 | 2026-11-18 | 2026-09-02 |
| 23 | 7f50ace658510fd203b2c935440d5b4f | 14TH ST NW | STREET | Block Only | Block Only | 1 | 2 | 2 | 2026-10-31 | 2026-01-25 |
| 24 | 1badce50290e8f6ebbf000af7843cf75 | KRAMER ST NE | STREET | Block Only | Block Only | 7 | 3 | 1 | 2026-11-15 | 2026-09-03 |
| 25 | 43c028cf63a950ec1b84bec46dd71210 | 2ND ST NE | STREET | Block Only | Block Only | 5 | 3 | 1 | 2026-11-26 | 2026-06-06 |

## Recommendations

1. Review the dual-conflict subblocks above with permit holders before dispatching crews; where the
   permittee's restoration obligation covers the reported defect, route the SR to permit enforcement.
2. Hold planned repaving on subblocks with permits expiring after the planned work date.
3. Use the block view (`roadway_block_enriched`) to bundle nearby work on the same block into one dispatch.
4. Re-run the pipeline on a regular cadence (it is fully automated) to keep the overlap list current.

## Data Quality Notes

* Permits further than 150 ft from any qualifying subblock are kept in `permits_snapped`
  with `SNAPPED = 0` and no `SUBBLOCK_UID`: 105 permit(s).
* Service requests further than 150 ft from a qualifying subblock (e.g. located on
  alleys or driveways) are not counted: 18 request(s).
* Permit snap displacement: median 2.2 ft, 95th percentile 91.3 ft, max 149.8 ft (see `qa_permit_snap_displacement`).
* Subblocks without a BLOCKID are treated as single-subblock blocks: 711.
* Features with null geometry dropped: permits 0, service requests 0.
* Dates are stored in UTC in the GeoPackage and shown here in America/New_York.

## Definition Queries Used

* **Subblocks:** `ROADTYPE IN ('1', '2', '3')`
* **Permits:** `ExpirationDate >= timestamp '2025-10-01 00:00:00' AND Renewal = 2 AND StatusDescription IN ('Issued') AND (IsExcavation = 1 OR IsPaving = 1)`
* **Service requests:** `STATUS NOT IN ('CLOSED', 'CANCEL', 'COMPLETE') AND DESCRIPTION IN ('ROADWAY REPAIR', 'POTHOLES', 'STREET REPAVING', 'STREET REPAIR', 'STREET PAVING SCHEDU') AND INITIATEDDATE >= timestamp '2025-10-01 00:00:00'`
