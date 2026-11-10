# Approach, data findings and assumptions

There was no data dictionary, so every filter and method below comes from profiling the
three REST layers. Profiling scripts: `scripts/explore_schema.py`, `scripts/explore_values.py`
and `scripts/diag_snap_distance.py`. The data was pulled on **2026-11-09**.

## 1. Data sources

| Layer | REST endpoint | Records on the server | Downloaded |
|---|---|---:|---:|
| Construction permits (TOPS) | `DCGIS_APPS/DDOT_TOPS/MapServer/23` | 55,345 | all 55,345 |
| Roadway SubBlock | `DCGIS_DATA/Transportation_WebMercator/MapServer/162` | 34,964 | all 34,964 |
| Cityworks service requests | `DDOT/Cityworks/MapServer/1` | 1,524,187 | 79,313 (`INITIATEDDATE >= 2025-10-01`) |

- **Paging.** Each layer allows at most 2,000 records per request, so the download fetches
  object IDs first and then requests them in chunks of 1,000.
- **Coordinate system.** Geometry is requested in **EPSG:26985 (NAD83 / Maryland State
  Plane, metres)**, so every distance is in true metres. Web Mercator overstates distances by
  about 30% at DC's latitude.
- **Where filtering happens.** The only server-side filter is the Cityworks date cut, used
  to avoid downloading 1.5 million rows. Every business filter runs locally in QGIS
  Processing, so it appears in the geoprocessing history.

## 2. Filters, and how each requirement maps to the data

### Construction permits: 55,345 → 10,008

| Requirement | Field / expression | Notes from profiling |
|---|---|---|
| Expiration on or after Oct 1, 2025 | `ExpirationDate >= 2025-10-01` | |
| Renewal permits only | `RenewalDescription = 'Renewal'` (`Renewal = 2`) | `PermitType` (New / Replace / Repair) describes the work, not renewals, so it was not used. |
| That have been issued | `StatusDescription = 'Issued'` (Status domain code 9) | Other statuses among renewals: *Permit Expired* 9,793, *Approved (Pending Payment)* 7,682, *Assigned* 95, and a few others. These are excluded. |
| Excavation and paving only | `IsExcavation = 1 OR IsPaving = 1` | Excavation only 9,685; paving only 265; both 58. |

Every issued renewal that matches has its expiration date on or after today. Once a permit
lapses, TOPS changes its status to *Permit Expired*, so the latest `PRMT_MAXEX` dates run
from Nov 2026 to Nov 2027.

### Roadway subblocks: 34,964 → 23,104

`ROADTYPE` is a coded-value domain: 1 = Street, 2 = Service Road, 3 = Ramp, 4 = Alley,
5 = Driveway, 6 = Trail, 7 = Walkway, 8 = Streetcar.

- Kept: `ROADTYPE IN ('1','2','3')`.
- Result: 22,393 streets, 121 service roads (the "service lanes" in the request) and
  590 ramps.
- `SUBBLOCKKEY` is unique across all 34,964 rows, so it is the join key.

### Cityworks service requests: 79,313 → 653

The definition query provided in the assignment was applied word for word. In this date
window, the requests with roadway descriptions break down as follows:

| STATUS | Count | Kept? |
|---|---:|---|
| CLOSED | 6,819 | No |
| INSPCOMP (inspection complete) | 288 | Yes |
| OPEN | 182 | Yes |
| PENDING | 182 | Yes |
| COMPLETE | 3 | No |
| GEO ISSUE | 1 | Yes (see note) |

- **Only two descriptions occur in this window: POTHOLES and ROADWAY REPAIR.** The other
  three values in the provided query (`STREET REPAVING`, `STREET REPAIR`,
  `STREET PAVING SCHEDU`) have no records since Oct 1, 2025. They stay in the filter so it
  still works on future data.
- **One "GEO ISSUE" record is included.** The provided `NOT IN` query lets it through even
  though it is not strictly open, pending or inspection-complete. It is also more than 50 m
  from any street, so it is not assigned to a block and doesn't change any count.

## 3. Snapping permits to the roadway

**The problem.** A permit's point geometry is identical to its `OnSegX / OnSegY` fields:
the address projected onto DC's MAR *street-segment* network. That network was digitised
separately from the Roadway Subblock centerlines. Measured against the filtered subblocks:

| Distance to nearest street / service / ramp subblock | Permits |
|---|---:|
| exactly on a line (< 1 cm) | 332 |
| ≤ 5 m | 9,934 (median 0.67 m, p99 0.89 m) |
| between 5 and 15 m | 0 |
| > 15 m | 74 (maximum 109 m) |

All 74 of the far-off permits are within 4.8 m of a non-street subblock: **alley** (67),
**driveway** (5) or **walkway** (2). They are alley and driveway cuts.

**Method** (`scripts/02_process.py`, steps 04 to 13):

1. **Join attributes by nearest** (k = 1, max 10 m) to the filtered subblocks. This returns
   the closest point on the line (`nearest_x`, `nearest_y`), the distance and the subblock
   key. The 5 to 15 m gap means any tolerance in that range gives the same answer.
2. **Fallback.** Permits not matched in step 1 are joined to the nearest subblock of *any*
   road type, so the snapped layer is complete. They are marked
   `SNAP_STAT = 'SNAPPED - alley/driveway/other (not counted)'` and `COUNTED = 0`.
3. **Remove duplicates by OBJECTID.** This handles ties where two blocks are exactly the
   same distance away.
4. **Geometry by expression** `make_point(nearest_x, nearest_y)` moves each point onto the
   centerline. The QA layer `permit_snap_lines` draws the move.

**Verification.** All 9,934 counted permits lie within 1 cm of the subblock they are
assigned to, and every permit appears exactly once.

Using join-by-nearest instead of *Snap geometries to layer* means the snapped location and
the block assignment always agree.

## 4. Assigning service requests

Service requests are geocoded to addresses rather than street segments. Their distance to
the filtered subblocks: median 0.16 m, p90 21.6 m, p99 72 m.

- **Method.** Join attributes by nearest with a **50 m** tolerance.
- **Result.** 643 of 653 are assigned. The 10 left over are more than 50 m from any street,
  service road or ramp.
- **Geometry.** Service request points keep their original location, because the request
  only asks for the permits to be snapped. The assigned block is stored in
  `SB_SUBBLOCKKEY` and the distance in `SB_DIST`.

## 5. Enrichment fields on `roadway_subblock_enriched`

| Field | Meaning |
|---|---|
| `PRMT_CNT` | Count of filtered, snapped permits on the subblock (0 if none) |
| `PRMT_MAXEX` | Latest `ExpirationDate` among those permits |
| `SR_CNT` | Count of filtered Cityworks SRs assigned to the subblock (0 if none) |
| `SR_MAXINIT` | Latest `INITIATEDDATE` among those SRs |
| `HAS_PRMT`, `HAS_SR` | 1 / 0 |
| `BOTH_FLAG` | **1 when the block has both permits and service requests** |
| `FLAG_CAT` | `Permits + SRs` / `Permits only` / `SRs only` / `Neither` (for symbology) |

All field names are 10 characters or fewer, so they survive the shapefile export.

**Results:**

| Measure | Value |
|---|---:|
| Blocks with permits | 2,525 (9,934 permits) |
| Blocks with SRs | 541 (643 SRs) |
| Blocks with both (`BOTH_FLAG = 1`) | **98** |

The block with the most permits is 13th St NE (70 permits and 1 SR).

## 6. Assumptions and limitations

- **Dates are compared as the REST service stores them** (UTC epoch). Oct 1, 2025 at
  00:00 UTC is Sept 30 at 8 pm Eastern. This is the same convention as the provided
  Cityworks SQL, which uses a server-side `timestamp` literal.
- **Each permit and SR is counted on one block**, its nearest. Permits whose work spans
  several blocks are counted once, at their recorded location.
- **The REST data is live.** Re-running `run_all.bat` refreshes everything; counts will
  change as permits and requests are updated.
- **Possible next steps with more time:**
  - Use `StreetSegID` / `RoadwaySegID` to cross-check block assignment against the MAR
    segment-to-subblock relationship.
  - Split permits that span several blocks, using their `MultiAddresses` field.
  - Publish the enriched layer as a hosted service with a scheduled refresh.
