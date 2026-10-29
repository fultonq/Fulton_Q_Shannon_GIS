# DDOT Maintenance Operations GIS Analysis: Permits, Service Requests, and Subblock Integration

**Version 2** - adds the block-level (BLOCKID) view, snapping/assignment QA layers, insight tables,
a reorganised QGIS layer tree and the Esri World Light Gray basemap.

## 1. Project Overview

This project fulfils the operational GIS data request submitted by the Deputy Chief of the
Maintenance Operations Administration to the Analytics, Assets, and Performance Branch. It
evaluates spatial and temporal overlap between active excavation/paving **renewal permits** and
**open roadway service requests** across the District's roadway subblock network.

Deliverables:

* Construction permit renewal locations snapped to roadway subblock centerlines.
* An enriched roadway subblock layer with permit counts, open service-request counts, latest
  expiration / initiation dates and a dual-conflict flag, plus the same metrics rolled up to blocks.
* QA layers that show every snap and assignment as a line from the source location.
* A QGIS project (`ddot_maintenance_operations.qgz`) with the local processed layers and the
  filtered live DC GIS REST feeds.
* One shapefile per filter / question in the data request (`shapefiles/`), for use outside the
  project or in ArcGIS, with a field crosswalk back to the GeoPackage.
* `QGIS_Dashboard_Guide.md` - step-by-step instructions for building an interactive and a printable
  dashboard in QGIS from those shapefiles.
* A geoprocessing log, a per-run history table, the automated Python processing script, and this documentation.

Results for the current run are summarised in **`Project_Summary_Report.md`**.

## 2. Directory Structure & File Manifest

```text
Fulton_Q_Shannon_GIS_V2/
├── README.md                          # This file: technical documentation and data dictionary
├── Project_Summary_Report.md          # Executive report generated from the latest run
├── 01_pull_and_process_data.py        # REST extraction, snapping, enrichment, GeoPackage + report
├── ddot_maintenance_operations.qgz    # QGIS project (relative paths - open directly after unzipping)
├── QGIS_Dashboard_Guide.md            # Step-by-step: build a QGIS dashboard from shapefiles/
├── shapefiles_map.qgz                 # Shapefile-only project: street labels + OpenStreetMap basemap
├── data/
│   └── ddot_maintenance_operations.gpkg
│       ├── roadway_subblock_enriched    # Enriched roadway centerlines (MultiLineString)
│       ├── roadway_block_enriched       # Subblocks rolled up by BLOCKID (MultiLineString)
│       ├── permits_snapped              # Snapped excavation/paving renewal permits (Point)
│       ├── service_requests_filtered    # Open Cityworks roadway service requests (Point)
│       ├── permits_original             # Permits at their source (unsnapped) location (Point)
│       ├── qa_permit_snap_displacement  # Original -> snapped permit location (LineString)
│       ├── qa_sr_subblock_assignment    # SR -> nearest point on assigned subblock (LineString)
│       ├── insight_top_conflicts        # Ranked dual-conflict subblocks (table)
│       ├── insight_ward_summary         # Activity by ward (table)
│       ├── insight_activity_summary     # Activity class x roadway type, with miles (table)
│       └── geoprocessing_history        # One row per pipeline run: parameters, queries, audit counts
├── shapefiles/                        # One shapefile per PDF filter / question (EPSG:2248)
│   ├── permits_filtered_snapped.shp       # Permit filter, snapped to the roadway
│   ├── roadway_subblock_filtered.shp      # Subblock filter (street / service lane / ramp), enriched
│   ├── service_requests_filtered.shp      # Cityworks SR filter
│   ├── subblocks_with_permits.shp         # PRMT_CNT > 0: permit count + latest expiration
│   ├── subblocks_with_open_srs.shp        # SR_CNT > 0: SR count + latest initiation
│   ├── subblocks_with_permits_and_srs.shp # FLAG_BOTH = 1
│   └── field_crosswalk.csv                # Shapefile field -> GeoPackage field, filter, PDF item
└── logs/
    └── geoprocessing_history.log      # Timestamped execution log (appended on every run)
```

## 3. Data Sources & Definition Queries

All inputs come from public DC GIS REST endpoints. Filters are applied **server-side**, and every
matching feature is retrieved (object-ID batching; no record-count truncation).

| Dataset | REST endpoint | Definition query (as executed) |
| --- | --- | --- |
| Construction Permits (DDOT TOPS) | `https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/DDOT_TOPS/MapServer/23` | `ExpirationDate >= timestamp '2025-10-01 00:00:00' AND Renewal = 2 AND StatusDescription IN ('Issued') AND (IsExcavation = 1 OR IsPaving = 1)` |
| Roadway Subblock Centerlines | `https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/162` | `ROADTYPE IN ('1', '2', '3')` |
| Cityworks Service Requests | `https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/Cityworks/MapServer/1` | `STATUS NOT IN ('CLOSED', 'CANCEL', 'COMPLETE') AND DESCRIPTION IN ('ROADWAY REPAIR', 'POTHOLES', 'STREET REPAVING', 'STREET REPAIR', 'STREET PAVING SCHEDU') AND INITIATEDDATE >= timestamp '2025-10-01 00:00:00'` |

### Mapping of requested criteria to the live schemas

Some field names in the original request are not present on the published services. They were
mapped to the equivalent published fields (verified against each layer's REST metadata):

| Requested criterion | Published field and value used | Notes |
| --- | --- | --- |
| Renewal permits only (`IS_RENEWAL = 1` / `PERMIT_TYPE_NAME LIKE '%RENEW%'`) | `Renewal = 2` | Domain: 1 = New, 2 = Renewal (`RenewalDescription`) |
| Status is issued (`STATUS LIKE '%ISSUED%'`) | `StatusDescription IN ('Issued')` | `Issued` is the only status value containing "ISSUED" |
| Work category is excavation or paving | `IsExcavation = 1 OR IsPaving = 1` | Boolean work-type flags |
| Subblock type in (`STREET`, `SERVICE LANE`, `RAMP`) | `ROADTYPE IN ('1','2','3')` | Coded domain: 1 Street, 2 Service Road, 3 Ramp (4 Alley, 5 Driveway, 6 Trail, 7 Walkway, 8 Streetcar excluded) |

The executed queries are also recorded per run in the `geoprocessing_history` table.

## 4. Methodology & Geoprocessing Pipeline

1. **Extraction & reprojection** - each layer is queried for matching object IDs, then features are
   fetched in batches (≤ the server's `maxRecordCount`) as GeoJSON (EPSG:4326) with automatic
   retry/back-off on transient HTTP errors. Features are projected to **EPSG:2248 (NAD83 / Maryland,
   US survey feet)** so distances and snapping are planar and in feet. Null/empty geometries are
   dropped and counted.
2. **Snapping construction permits** - each permit is matched to the nearest qualifying subblock
   centerline within **150 ft** (`sjoin_nearest`). Matched points are moved onto the centerline by
   linear referencing (`line_locate_point` → `line_interpolate_point`). Original coordinates are kept
   in `ORIG_X` / `ORIG_Y`; permits beyond the tolerance are retained with `SNAPPED = 0`.
3. **Service request assignment** - open SRs are assigned to the nearest qualifying subblock within
   150 ft (geometry unchanged).
4. **Subblock enrichment** - per subblock:
   * `PERMIT_COUNT` - snapped permit work-location records on the subblock (TOPS stores one row per
     address of a permit, so a multi-address permit contributes several)
   * `DISTINCT_PERMIT_COUNT` - unique permits (`PermitNumber`) on the subblock
   * `MIN_PERMIT_EFF_DATE` - earliest permit effective (start) date
   * `MAX_PERMIT_EXP_DATE` - latest permit expiration date
   * `SR_COUNT` - open service requests on the subblock
   * `DISTINCT_SR_LOCATIONS` - unique SR locations (repeat reports geocoded to one point count once)
   * `MIN_SR_INIT_DATE` - oldest open SR initiation date
   * `MAX_SR_INIT_DATE` - latest SR initiation date
   * `FLAG_BOTH_PERMIT_AND_SR` - 1 if `PERMIT_COUNT > 0` and `SR_COUNT > 0`, else 0
5. **Block roll-up** - enriched subblocks are dissolved by `BLOCKID` (line-merged). Subblocks with
   no `BLOCKID` become single-subblock blocks keyed `SB:<SUBBLOCK_UID>`, so block totals always equal
   subblock totals.
6. **QA & insights** - displacement lines (permit original → snapped), assignment lines (SR → nearest
   point on its subblock), the original permit points, and the three `insight_*` tables are derived.
7. **Output** - layers, insight tables and a run-history row are written to `ddot_maintenance_operations.gpkg`
   atomically (temp file + rename; prior run history is carried forward), and
   `Project_Summary_Report.md` is regenerated.
8. **Shapefile exports** - the GeoPackage layers are exported to `shapefiles/`, one file per filter or
   question in the request (see 5. Data Dictionary, *Shapefile exports*).
9. **QGIS project** - `ddot_maintenance_operations.qgz` (QGIS 3.40 LTR) references the GeoPackage
   layers and shapefiles by relative path, so the project opens anywhere once the folder is unzipped.

Equidistant ties are resolved deterministically (first match). Metrics are attributed per subblock
feature, so duplicate subblock keys (none in the current data) cannot double-count.

## 5. Data Dictionary

### `roadway_subblock_enriched` (MultiLineString, EPSG:2248)

All published Roadway SubBlock attributes are retained (e.g. `ROUTENAME`, `STREETNAME`,
`FROMSTREET`, `TOSTREET`, `WARD_ID`, `ROADTYPE`, `PCI_SCORE`; `SHAPE.LEN` is renamed `SHAPE_LEN`).
Derived fields:

| Field | Type | Description |
| --- | --- | --- |
| `SUBBLOCK_UID` | Text | Unique subblock identifier (`SUBBLOCKKEY`; falls back to `OID-<OBJECTID>` if blank). |
| `ROADWAY_TYPE` | Text | Decoded road classification: `STREET`, `SERVICE LANE`, or `RAMP`. |
| `PERMIT_COUNT` | Integer | Count of filtered excavation/paving renewal permit work-location records (one per address) snapped to the subblock. |
| `DISTINCT_PERMIT_COUNT` | Integer | Count of unique permits (`PermitNumber`) among those records. |
| `MIN_PERMIT_EFF_DATE` | DateTime (UTC) | Earliest effective (start) date among those permits; null when `PERMIT_COUNT = 0`. |
| `MAX_PERMIT_EXP_DATE` | DateTime (UTC) | Latest expiration date among those permits; null when `PERMIT_COUNT = 0`. |
| `SR_COUNT` | Integer | Count of open roadway repair / pothole / paving service requests on the subblock. |
| `DISTINCT_SR_LOCATIONS` | Integer | Unique locations among those requests (rounded to 1 ft); repeat reports at one point count once. |
| `MIN_SR_INIT_DATE` | DateTime (UTC) | Oldest initiation date among those requests (how long the defect has waited); null when `SR_COUNT = 0`. |
| `MAX_SR_INIT_DATE` | DateTime (UTC) | Latest initiation date among those requests; null when `SR_COUNT = 0`. |
| `FLAG_BOTH_PERMIT_AND_SR` | Integer | 1 = both permits and open service requests present; 0 otherwise. |
| `ACTIVITY_CLASS` | Text | `Permit + SR`, `Permit only`, `SR only`, or `No activity` (drives map styling). |

### `permits_snapped` (Point, EPSG:2248)

All published TOPS permit attributes (e.g. `PermitNumber`, `StatusDescription`, `ExpirationDate`,
`WorkLocationFullAddress`, `IsExcavation`, `IsPaving`) plus:

| Field | Type | Description |
| --- | --- | --- |
| `SUBBLOCK_UID` | Text | Subblock the permit was snapped to; null if none within tolerance. |
| `NEAR_DIST_FT` | Real | Distance (ft) from the original location to the centerline. |
| `ORIG_X`, `ORIG_Y` | Real | Original (pre-snap) coordinates in EPSG:2248 feet. |
| `SNAPPED` | Integer | 1 = moved onto a centerline; 0 = beyond tolerance, original location kept. |

### `service_requests_filtered` (Point, EPSG:2248)

All published Cityworks attributes (e.g. `REQUESTID`, `DESCRIPTION`, `STATUS`, `INITIATEDDATE`,
`ADDRESS`, `WARD`) plus `SUBBLOCK_UID` and `NEAR_DIST_FT` as above (geometry not moved).

### `roadway_block_enriched` (MultiLineString, EPSG:2248)

| Field | Type | Description |
| --- | --- | --- |
| `BLOCK_UID` | Text | `BLOCKID`, or `SB:<SUBBLOCK_UID>` for subblocks without one. |
| `BLOCKID`, `BLOCKKEY`, `ROUTENAME`, `STREETNAME`, `ROADWAY_TYPE` | Text | From the block's subblocks (constant within a block). |
| `WARD_ID` | Text | Most common ward among the block's subblocks (28 blocks span two wards). |
| `SUBBLOCK_COUNT` | Integer | Subblocks in the block. |
| `PERMIT_COUNT`, `SR_COUNT`, `DISTINCT_SR_LOCATIONS` | Integer | Sums over the block's subblocks. |
| `DISTINCT_PERMIT_COUNT` | Integer | Unique permits on the block (a permit spanning several of its subblocks counts once). |
| `MIN_PERMIT_EFF_DATE`, `MIN_SR_INIT_DATE` | DateTime (UTC) | Earliest dates over the block. |
| `MAX_PERMIT_EXP_DATE`, `MAX_SR_INIT_DATE` | DateTime (UTC) | Latest dates over the block. |
| `SUBBLOCKS_WITH_BOTH` | Integer | Subblocks in the block whose own `FLAG_BOTH_PERMIT_AND_SR = 1`. |
| `FLAG_BOTH_PERMIT_AND_SR` | Integer | 1 = the block has permits **and** open SRs, possibly on different subblocks. |
| `ACTIVITY_CLASS` | Text | As for subblocks, evaluated at block level. |
| `LENGTH_FT` | Real | Block centerline length (ft). |

### QA layers

| Layer | Geometry | Fields |
| --- | --- | --- |
| `permits_original` | Point | All `permits_snapped` attributes, at the source location from the REST service. |
| `qa_permit_snap_displacement` | LineString | `PermitNumber`, `SUBBLOCK_UID`, `NEAR_DIST_FT`, `LENGTH_FT` (= displacement). One line per snapped permit. |
| `qa_sr_subblock_assignment` | LineString | `REQUESTID`, `DESCRIPTION`, `STATUS`, `SUBBLOCK_UID`, `NEAR_DIST_FT`, `LENGTH_FT`. One line per matched SR. |

### Insight tables (snapshot of the latest run)

| Table | Contents |
| --- | --- |
| `insight_top_conflicts` | Every dual-conflict subblock: `RANK`, identifiers, street, ward, `BLOCKID`, counts, latest dates, `DISTINCT_PERMIT_COUNT`, `PERMIT_COUNT`, `DISTINCT_SR_LOCATIONS`, `SR_COUNT`, `ACTIVITY_SCORE` (= distinct permits + distinct SR locations; ties broken by distinct SR locations, SR count, distinct permits, then permit records). |
| `insight_ward_summary` | Per ward: `SUBBLOCKS`, `SUBBLOCKS_WITH_PERMITS`, `SUBBLOCKS_WITH_SRS`, `DUAL_CONFLICT_SUBBLOCKS`, `DISTINCT_PERMITS`, `PERMIT_LOCATIONS` (records), `OPEN_SRS`, `DISTINCT_SR_LOCATIONS`. |
| `insight_activity_summary` | Per `ACTIVITY_CLASS` × `ROADWAY_TYPE`: `SUBBLOCKS`, `CENTERLINE_MILES`. |

### `geoprocessing_history` (attribute table)

One row per run: `run_id`, `run_started_utc`, `run_finished_utc`, `duration_s`, `script_version`,
`target_crs`, `snap_tolerance_ft`, fetched/valid/matched/unmatched counts for each source, `permits_distinct`, `srs_distinct_locations_matched`, `sr_status_counts`,
`subblocks_with_permits`, `subblocks_with_srs`, `dual_conflict_subblocks`, `blocks_written`,
`dual_conflict_blocks`, `subblocks_without_blockid`, permit snap displacement median / 95th percentile /
max (ft), source URLs, and the exact definition queries executed.

### Shapefile exports (`shapefiles/`, EPSG:2248)

One shapefile per filter or question in the data request. They hold the same features as the
GeoPackage layers but carry a curated field set: shapefile field names are limited to 10 characters,
and dates are stored as dates (the UTC calendar day, without the time). The GeoPackage keeps every
source attribute and full timestamps; `field_crosswalk.csv` maps each shapefile field back to it.

| Shapefile | Source layer | Filter | Answers |
| --- | --- | --- | --- |
| `permits_filtered_snapped` | `permits_snapped` | all | Construction permit filter, snapped to the roadway (`SNAPPED` = 0 rows keep their original location) |
| `roadway_subblock_filtered` | `roadway_subblock_enriched` | all | Roadway subblock filter, enriched |
| `service_requests_filtered` | `service_requests_filtered` | all | Cityworks service request filter |
| `subblocks_with_permits` | `roadway_subblock_enriched` | `PERMIT_COUNT > 0` | Blocks with a permit count; latest expiration date |
| `subblocks_with_open_srs` | `roadway_subblock_enriched` | `SR_COUNT > 0` | Blocks with an open SR count; latest creation date |
| `subblocks_with_permits_and_srs` | `roadway_subblock_enriched` | `FLAG_BOTH_PERMIT_AND_SR = 1` | Blocks with both |

Key subblock fields: `SUBBLK_UID` (`SUBBLOCK_UID`), `PRMT_CNT` (`PERMIT_COUNT`), `PRMT_DIST`
(`DISTINCT_PERMIT_COUNT`), `PRMT_EXPMX` (`MAX_PERMIT_EXP_DATE`), `SR_CNT` (`SR_COUNT`), `SR_INITMX`
(`MAX_SR_INIT_DATE`), `FLAG_BOTH` (`FLAG_BOTH_PERMIT_AND_SR`), `ACTIVITY` (`ACTIVITY_CLASS`).

## 6. QGIS Project Contents

| Group | Layer | Default | Styling |
| --- | --- | --- | --- |
| Analysis (local GeoPackage) | Subblocks with BOTH permits and open SRs | on | Red line on a yellow halo (`FLAG_BOTH_PERMIT_AND_SR = 1`) |
| | Permits - snapped to roadway subblock | on | Magenta circles (`SNAPPED = 1` only) |
| | Service requests - open roadway/pothole/paving | on | Purple triangles |
| | Roadway subblock - enriched | on | Categorised by `ACTIVITY_CLASS` |
| | Roadway block (BLOCKID) - enriched | off | Categorised by `ACTIVITY_CLASS`, wider lines |
| Shapefile exports (one per PDF filter / question) | The six `shapefiles/*.shp` layers | off | Same styling as the matching Analysis layer |
| Source - live DC GIS REST services (filtered) | REST - Construction permits (DDOT TOPS) | off | Hollow blue squares |
| | REST - Cityworks service requests | off | Hollow red triangles |
| | REST - Roadway SubBlock | off | Dashed grey line |
| QA - snapping & original locations | Permits - NOT snapped (> tolerance, original location) | off | Orange diamonds (`SNAPPED = 0`) |
| | QA - permit snap displacement (original -> snapped) | off | Pink lines |
| | QA - SR to subblock assignment | off | Dashed orange lines |
| | Permits - original source location (unsnapped) | off | Grey × |
| Insights & geoprocessing history (tables) | 3 insight tables + geoprocessing history | - | Attribute tables |
| Basemap | Esri World Light Gray | on | XYZ tiles |
| | OpenStreetMap | off | XYZ tiles |

Street names (`ROUTENAME`, e.g. `13TH ST NW`) label the roadway subblock layers once zoomed in past
1:20,000; ramps are left unlabelled. `shapefiles_map.qgz` is a companion project with only the six
shapefiles, the same labels and an OpenStreetMap basemap (street names at every zoom).

The live REST layers apply the same definition queries as the analysis.
Project CRS is EPSG:2248. All local paths are relative, so the project opens anywhere once unzipped.
The live feeds and basemaps require internet access; the analysis layers do not.

## 7. Reproducing the Analysis

Requirements: Python ≥ 3.10 with `geopandas>=1.0 shapely>=2.0 pyogrio pyproj requests`, and
QGIS ≥ 3.28 (3.40 LTR recommended) to open the project.

```bash
# Refresh data, GeoPackage, log and summary report (run from this folder)
python 01_pull_and_process_data.py
#   options: --tolerance-ft 150 --crs EPSG:2248 --permit-min-expiration 2025-10-01 --sr-min-initiated 2025-10-01
```

The script exits non-zero on failure and logs to `logs/geoprocessing_history.log`. Re-opening
`ddot_maintenance_operations.qgz` afterwards shows the refreshed GeoPackage layers. The shapefiles
are a static export: they are regenerated when the project is rebuilt, not by this script.

**Windows QGIS with WSL:** open the project from a Windows folder, not from `\\wsl.localhost\...`.
The GeoPackage is a SQLite database and cannot be opened over the WSL network share, so every
GeoPackage layer shows as unavailable there (the shapefiles still load). After a rebuild in WSL, copy
the folder across first, e.g.

```bash
rsync -a --exclude='.venv/' --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='build/' \
  ./ /mnt/c/Users/<you>/OneDrive/Desktop/python_qgis/
```

## 8. Limitations

* Results are a snapshot of the live services at run time; re-run to refresh.
* The 150 ft tolerance can assign a point at an intersection to a cross street. `NEAR_DIST_FT` and
  `ORIG_X`/`ORIG_Y` support review of borderline cases.
* SRs on alleys or driveways are excluded by design because those road types are filtered out.
* "Open" SRs use the supplied SQL (`STATUS NOT IN ('CLOSED', 'CANCEL', 'COMPLETE')`). That keeps
  `OPEN`, `PENDING` and `INSPCOMP` (inspection completed), as the request asks, and also admits the odd
  status outside that list (currently one `GEO ISSUE`); the report counts these.
* Permits sited on an alley or driveway within the tolerance of a street are snapped onto that street
  and counted on it. `ON_EXCLUDED_ROADWAY` / `SOURCE_ROADWAY_TYPE` on `permits_snapped` and
  `EXCLUDED_ROADWAY_PERMIT_COUNT` on the subblocks identify them; whether they should count is open.
* `CSRNUMBER` is published but empty on every service request; `REQUESTID` is the identifier used.
* The permits service appears to publish current permits only (earliest expiration = run date), so the
  `ExpirationDate >= 2025-10-01` clause does not reduce the set. About 45% of permits expire within
  30 days, so re-run frequently.
* Dates are stored in UTC; the summary report presents them in America/New_York.

## 9. Tests

The processing and packaging logic is covered by a pytest suite in `tests/` (not part of the zip).

```bash
python -m pip install -r requirements-dev.txt
python -m pytest                    # one test queries the live REST services
python -m pytest -m "not network"   # offline only
```
