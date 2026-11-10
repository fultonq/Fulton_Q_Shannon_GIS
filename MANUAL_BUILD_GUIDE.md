# Manual Build Guide: rebuilding the project by hand in QGIS

This guide is for anyone, such as the Deputy Chief of the Maintenance Operations
Administration, who wants to build the project themselves in the **QGIS desktop GUI**
without running the Python scripts. It was written against **QGIS 4.2**, and menu names
are the same in QGIS 3.34 and later.

There are two paths:

| Path | Use it when | Time |
|---|---|---|
| **A. Open the finished shapefiles** (or the GeoPackage) | You only want to view and explore the results | about 5 min |
| **B. Rebuild everything from the REST feeds** | You want to repeat the analysis, for example next month | about 45 to 60 min |

---

## Are shapefiles generated?

**Yes.** The pipeline writes the results twice:

1. **`data/output/CS12_Roadway_Enrichment.gpkg`** is the authoritative copy. A GeoPackage
   is QGIS's equivalent of an ArcGIS file geodatabase: one file, many layers, full
   date and time values, long field names.
2. **`data/output/shapefiles/*.shp`** are shapefile copies of every result layer, for anyone
   who prefers shapefiles or needs them in other software:

| Shapefile | Features | What it is |
|---|---:|---|
| `roadway_subblock_enriched.shp` | 23,104 | Street / service lane / ramp subblocks with counts, max dates and flags |
| `roadway_subblock_permits_and_sr.shp` | 98 | Only the subblocks that have **both** permits and service requests |
| `permits_filtered_snapped.shp` | 10,008 | Filtered permits **snapped onto the roadway centerline** |
| `permits_filtered_original.shp` | 10,008 | The same permits at their original (unsnapped) location |
| `cityworks_sr_filtered.shp` | 653 | Filtered Cityworks service requests, each tagged with its subblock |
| `permit_snap_lines.shp` | 10,008 | QA lines from each original permit location to its snapped location |

**Shapefile limitations to know about:**
- **Field names are cut to 10 characters.** For example `SB_SUBBLOCKKEY` becomes
  `SB_SUBBLOC` and `ExpirationDate` becomes `Expiration`. The enrichment fields were named to
  fit on purpose: `PRMT_CNT`, `PRMT_MAXEX`, `SR_CNT`, `SR_MAXINIT`, `HAS_PRMT`, `HAS_SR`,
  `BOTH_FLAG`, `FLAG_CAT`.
- **Date and time values become date only.** `PRMT_MAXEX` and `SR_MAXINIT` keep the date
  but lose the time. The GeoPackage keeps both.
- **Text is cut to 254 characters** (for example long `WorkDetail` descriptions).
- **Each shapefile is a set of files.** `.shp`, `.shx`, `.dbf`, `.prj` and `.cpg` must stay
  together in the same folder.

---

## Path A: Open the results (shapefiles)

1. Start QGIS and choose **Project > New**.
2. Set the project CRS: **Project > Properties > CRS**, search **3857**, choose
   *WGS 84 / Pseudo-Mercator*, then **OK**. The data itself is in EPSG:26985 (NAD83 /
   Maryland, metres) and QGIS reprojects it on the fly.
3. Add a basemap (optional): in the **Browser** panel, expand **XYZ Tiles** and double-click
   **OpenStreetMap**.
4. **Layer > Add Layer > Add Vector Layer…** (Ctrl+Shift+V)
   - Source type: **File**
   - Click **…** and browse to `data/output/shapefiles/`
   - Select the six `.shp` files (Ctrl+click), then click **Add**.
5. Put the layers in this order in the **Layers** panel by dragging them:
   points on top, then lines.
   1. `cityworks_sr_filtered`
   2. `permits_filtered_snapped`
   3. `roadway_subblock_permits_and_sr`
   4. `roadway_subblock_enriched`
   5. `OpenStreetMap`
6. Style the subblocks by category:
   1. Right-click `roadway_subblock_enriched`, choose **Properties > Symbology**.
   2. Change *Single Symbol* to **Categorized**.
   3. Set **Value** to `FLAG_CAT`, click **Classify**, then **OK**.
   4. Optional: color *Permits + SRs* red, *Permits only* blue, *SRs only* orange,
      *Neither* light grey.
7. Explore the data:
   - **Identify Features** (Ctrl+Shift+I): click a block to see `PRMT_CNT`, `PRMT_MAXEX`,
     `SR_CNT`, `SR_MAXINIT` and `BOTH_FLAG`.
   - **Open Attribute Table** (F6), then click a column header to sort, for example by
     `PRMT_CNT`.
   - **Filter**: right-click a layer, choose **Filter…** and type `"BOTH_FLAG" = 1`.
8. **Project > Save As…** and save as `.qgz` in the same parent folder.

> **The GeoPackage alternative is easier.** Drag `data/output/CS12_Roadway_Enrichment.gpkg`
> onto the map, tick the layers you want, and click **Add Layers**. Each layer already has a
> default style saved inside the GeoPackage. Or open the finished project:
> **`CS12_Roadway_Enrichment.qgz`**.

---

## Path B: Rebuild the analysis from the REST feeds

Every tool below is in the **Processing Toolbox** (**Processing > Toolbox**, Ctrl+Alt+T).
Type the tool name in the toolbox search box. After each run, QGIS records the step in
**Processing > History**. That history is the "geoprocessing history" the request asks for.

**Distances need a metre-based CRS.** Steps B3 to B5 measure distances, so all layers must
be in **EPSG:26985** (NAD83 / Maryland), not 3857. Step B2 takes care of this.

### B1. Add the three REST service feeds

1. **Layer > Data Source Manager** (Ctrl+L), then **ArcGIS REST Server** on the left.
2. Click **New** and create the connection:
   - Name: `DC GIS`
   - URL: `https://maps2.dcgis.dc.gov/dcgis/rest/services`
   - Click **OK**, then **Connect**.
3. Expand the folders and add each layer:

| Folder / service | Layer | Map name |
|---|---|---|
| `DCGIS_APPS / DDOT_TOPS (MapServer)` | **23 - DDOT - Public Space Construction Permits - Status** | `REST - Construction Permits` |
| `DCGIS_DATA / Transportation_WebMercator (MapServer)` | **162 - Roadway SubBlock** | `REST - Roadway SubBlock` |
| `DDOT / Cityworks (MapServer)` | **1 - CityworksRequest** | `REST - Cityworks Service Requests` |

   Add each one as a **feature** layer (vector), not as a map image.

   > The Cityworks layer has about 1.5 million records. Turn on **Only request features
   > overlapping the current view extent** if QGIS offers it. You can also set
   > *Properties > Rendering > Scale-dependent visibility* so the layer only draws below
   > 1:25,000.

### B2. Make local copies in a GeoPackage (and filter Cityworks while copying)

For each REST layer, right-click it, choose **Export > Save Features As…**, and set:

| Setting | Value |
|---|---|
| Format | **GeoPackage** |
| File name | `data/raw/raw_downloads.gpkg` (use the same file each time) |
| Layer name | `permits_raw`, `roadway_subblock_raw`, `cityworks_sr_raw` |
| CRS | **EPSG:26985 - NAD83 / Maryland** |

For Cityworks, first set a filter so you only copy the recent records. Right-click the layer,
choose **Filter…**, and enter:

```sql
"INITIATEDDATE" >= '2025-10-01 00:00:00'
```

Then export it.

The local copies run the rest of the steps quickly and give you a fixed snapshot of the data.

### B3. Apply the data requirement filters (Extract by expression)

Run **Vector selection > Extract by expression** three times. Click the **ε** button to open
the expression builder, then paste the expression:

**1. Construction permits** (input `permits_raw`, output `permits_filtered`)
```
"ExpirationDate" >= to_datetime('2025-10-01 00:00:00')
AND "RenewalDescription" = 'Renewal'
AND "StatusDescription" = 'Issued'
AND ("IsExcavation" = 1 OR "IsPaving" = 1)
```
Expected result: **10,008** features.

**2. Roadway subblocks** (input `roadway_subblock_raw`, output `roadway_subblock_filtered`)
```
"ROADTYPE" IN ('1', '2', '3')
```
`ROADTYPE` stores domain codes: 1 = Street, 2 = Service Road, 3 = Ramp. Identify Features
shows the descriptions. Expected result: **23,104** features.

**3. Cityworks service requests** (input `cityworks_sr_raw`, output `cityworks_sr_filtered`).
This is the definition query provided in the assignment:
```
"STATUS" NOT IN ('CLOSED', 'CANCEL', 'COMPLETE')
AND "DESCRIPTION" IN ('ROADWAY REPAIR', 'POTHOLES', 'STREET REPAVING', 'STREET REPAIR', 'STREET PAVING SCHEDU')
AND "INITIATEDDATE" >= to_datetime('2025-10-01 00:00:00')
```
Expected result: **653** features. You can also paste this SQL straight into the REST
layer's **Filter…** dialog.

### B4. Snap the permits to the roadway

**Why permits need snapping.** The permit points are placed on DC's MAR *street-segment*
network (`OnSegX` / `OnSegY`), which doesn't line up with the Roadway Subblock centerlines.
The median offset is 0.67 m, and only 332 of the 10,008 permits sit exactly on a subblock
line.

**Option 1 (simplest GUI method): Snap geometries to layer**
- Input: `permits_filtered`
- Reference layer: `roadway_subblock_filtered`
- Tolerance: **10** metres
- Behavior: **Prefer closest point, insert extra vertices where required**
- Output: `permits_filtered_snapped`

This moves every point within 10 m onto the nearest centerline. It doesn't record which
block each point snapped to, so Option 2 is what the scripts use.

**Option 2 (used by the scripts): Join attributes by nearest, then Geometry by expression**
1. **Join attributes by nearest**
   - Input: `permits_filtered`
   - Input layer 2: `roadway_subblock_filtered`
   - Layer 2 fields to copy: `SUBBLOCKKEY`, `SUBBLOCKID`, `ROUTENAME`, `ROADTYPE`
   - Joined field prefix: `SB_`
   - Maximum nearest neighbors: **1**
   - Maximum distance: **10**
   - Discard records which could not be joined: **ticked**
   - Output: `permits_near`
   - Also save the **Unjoinable features** output as `permits_unmatched`.

   This produces the fields `nearest_x`, `nearest_y` (the closest point on the line) and
   `distance`.
2. **Optional fallback for the 74 permits on alleys or driveways.** Run *Join attributes by
   nearest* again with `permits_unmatched` as input and the **unfiltered**
   `roadway_subblock_raw` as layer 2, using the same settings. Then run **Merge vector
   layers** on both outputs. These 74 permits are snapped too but are **not counted**,
   because their blocks are outside the Street / Service / Ramp filter.
3. **Delete duplicates by attribute** with field `OBJECTID`. Two blocks at exactly the same
   distance, such as at an intersection, can return two rows for one permit.
4. **Field calculator**: create a new Integer field `COUNTED`:
   `if("SB_ROADTYPE" IN ('1','2','3'), 1, 0)`
5. **Geometry by expression**
   - Output geometry type: **Point**
   - Expression: `make_point("nearest_x", "nearest_y")`
   - Output: save to `CS12_Roadway_Enrichment.gpkg`, layer `permits_filtered_snapped`

   The points now sit exactly on the subblock lines.
6. **Optional QA**: run **Geometry by expression** again with type **Line** and expression
   `make_line($geometry, make_point("nearest_x","nearest_y"))` to draw how far each point
   moved.

### B5. Assign service requests to subblocks

Service requests are geocoded to addresses, so they sit further from the centerline (90%
are within 22 m).

1. **Join attributes by nearest**
   - Input: `cityworks_sr_filtered`
   - Layer 2: `roadway_subblock_filtered`
   - Fields: `SUBBLOCKKEY` (and others)
   - Prefix: `SB_`
   - Neighbors: **1**
   - Maximum distance: **50**
   - Discard: **unticked**
2. **Delete duplicates by attribute** with field `OBJECTID`.

Result: 643 of 653 SRs are assigned. Ten are more than 50 m from any street and are left
unassigned.

### B6. Summarise per subblock (Aggregate)

Run **Aggregate** twice.

**Permits**
- Input: `permits_filtered_snapped` with `"COUNTED" = 1`. Run *Extract by expression* first,
  or use the **Selected features only** box.
- Group by expression: `"SB_SUBBLOCKKEY"`
- Aggregates (use the **+** button):

| Source expression | Aggregate function | Output field | Type |
|---|---|---|---|
| `"SB_SUBBLOCKKEY"` | first_value | `SUBBLOCKKEY` | Text |
| `"OBJECTID"` | count | `PRMT_CNT` | Integer |
| `"ExpirationDate"` | maximum | `PRMT_MAXEX` | Date & Time |

- Output: `summary_permits_by_subblock`. Expect **2,525** rows.

**Service requests**: the same steps on the assigned SRs, with `SR_CNT` = count of
`OBJECTID` and `SR_MAXINIT` = maximum of `INITIATEDDATE`. Expect **541** rows.

(Optional) Run **Drop geometries** on both outputs so they become plain tables.

### B7. Enrich the Roadway Subblock layer (Join attributes by field value)

1. **Join attributes by field value**
   - Input: `roadway_subblock_filtered`, field `SUBBLOCKKEY`
   - Layer 2: `summary_permits_by_subblock`, field `SUBBLOCKKEY`
   - Fields to copy: `PRMT_CNT`, `PRMT_MAXEX`
   - Join type: **one-to-one**
   - Discard: **unticked**
2. Repeat on that output with `summary_sr_by_subblock`, copying `SR_CNT` and `SR_MAXINIT`.

### B8. Fill zero counts and add the flags (Refactor fields or Field calculator)

Use **Refactor fields**, or **Field calculator** once per field.

| Field | Type | Expression |
|---|---|---|
| `PRMT_CNT` | Integer | `coalesce("PRMT_CNT", 0)` |
| `SR_CNT` | Integer | `coalesce("SR_CNT", 0)` |
| `HAS_PRMT` | Integer | `if("PRMT_CNT" > 0, 1, 0)` |
| `HAS_SR` | Integer | `if("SR_CNT" > 0, 1, 0)` |
| `BOTH_FLAG` | Integer | `if("PRMT_CNT" > 0 AND "SR_CNT" > 0, 1, 0)` |
| `FLAG_CAT` | Text (20) | `CASE WHEN "PRMT_CNT">0 AND "SR_CNT">0 THEN 'Permits + SRs' WHEN "PRMT_CNT">0 THEN 'Permits only' WHEN "SR_CNT">0 THEN 'SRs only' ELSE 'Neither' END` |

Save the result to `CS12_Roadway_Enrichment.gpkg` as layer `roadway_subblock_enriched`.
Expect **23,104** blocks, of which **98** have `BOTH_FLAG = 1`.

Optional: run **Extract by expression** with `"BOTH_FLAG" = 1` and save the result as
`roadway_subblock_permits_and_sr`.

### B9. Make shapefile copies (optional)

Right-click each result layer and choose **Export > Save Features As…**:
- Format: **ESRI Shapefile**
- Folder: `data/output/shapefiles/`
- Under **Layer Options**, set `RESIZE=YES` to keep the `.dbf` small.

### B10. Check the results

Each of these should hold:

| Check | Expected |
|---|---|
| Sum of `PRMT_CNT` | equals the number of permits with `COUNTED = 1` (9,934) |
| Sum of `SR_CNT` | equals the number of SRs with an `SB_SUBBLOCKKEY` (643) |
| Each snapped permit | lies on its block's line (Identify plus the Measure tool, or the QA lines) |

### B11. Save the project and the geoprocessing history

1. **Processing > History**: every algorithm you ran is listed with its parameters. Select
   all entries, right-click and copy them, or use **Save As…** to keep a log file next to
   the project.
2. **Project > Save As…** saves a `.qgz` in the project folder.
3. **Project > Properties > General**: make sure **Save paths** is set to **Relative**.
4. To package everything, zip the whole project folder as
   `FirstName_MiddleInitial_LastName_GIS.zip`. Alternatively, run **Package layers** to put
   all result layers into one GeoPackage, then zip that file together with the `.qgz`.
