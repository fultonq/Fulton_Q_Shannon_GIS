# Building a QGIS Dashboard from the Shapefiles

This guide turns the six shapefiles in `shapefiles/` into a working dashboard in **QGIS 3.40 / 3.44 LTR**:

* an **interactive map** with street names, pop-ups on hover, filters, live totals and charts;
* a **one-page printable dashboard** (map, KPI tiles, chart, top-10 table) exported to PDF;
* optional **drill-down pages**, one per conflict subblock.

No Python is needed. There are two ways in:

| Route | Start from | Time |
| --- | --- | --- |
| **A. Quick start** (recommended) | `shapefiles_map.qgz`: already styled, labelled, with a basemap | 25-30 min |
| **B. From scratch** | an empty project, to learn every step | 60 min |

Both routes meet at **Step 5**.

---

## Before you start

* **Windows + WSL users:** open the project from a Windows folder (e.g. the Desktop copy), **not**
  from `\\wsl.localhost\...`. Over that share QGIS cannot open the GeoPackage, and layers show as
  unavailable. The shapefiles themselves are fine, but keep everything on one drive.
* **Field names** are the 10-character shapefile names. `shapefiles/field_crosswalk.csv` maps each
  one to its full GeoPackage name. The ones you will use most:

  | Field | Meaning |
  | --- | --- |
  | `ROUTENAME` | Full street name, e.g. `13TH ST NW` |
  | `WARD_ID` / `WARD` | Ward, stored as **text** (`'6'`, not `6`) |
  | `PRMT_CNT`, `PRMT_EXPMX` | Permits on the subblock; latest permit expiration date |
  | `SR_CNT`, `SR_INITMX` | Open service requests on the subblock; latest SR creation date |
  | `FLAG_BOTH` | 1 = the subblock has both permits and open SRs |
  | `ACTIVITY` | `Permit + SR`, `Permit only`, `SR only`, `No activity` |
  | `SNAPPED` | Permits: 1 = moved onto a centerline, 0 = beyond 150 ft, left in place |

* **Expected numbers** for the current data run (use them to check your work): 23,104 subblocks;
  2,637 with permits; 526 with open SRs; **90 with both**; 9,345 permits; 651 open SRs.

---

## Route A - Quick start

1. In QGIS: **Project ▸ Open…** → `shapefiles_map.qgz` (in the project folder).
2. **Check:** the Layers panel shows two groups:

   | Group | Layer | On? |
   | --- | --- | --- |
   | Shapefile exports | Permits, Service requests, Subblocks with BOTH, Subblocks with open SRs, Subblocks with permits, Roadway subblocks | first three and the roadway layer on |
   | Basemap | OpenStreetMap (street names), Esri World Light Gray | OSM on |

3. Zoom in past about **1:20,000** (see the *Scale* box on the status bar). Street names appear
   along the centerlines.
4. **Project ▸ Save As…** → `ddot_dashboard.qgz` in the same folder, so later re-builds of
   `shapefiles_map.qgz` don't overwrite your work.

Continue at **Step 5**.

---

## Route B - From scratch

### Step 1 - Project setup

1. **Project ▸ New**.
2. **Project ▸ Properties ▸ CRS**: search `2248` → *NAD83 / Maryland (ftUS)* → **OK**.
3. **Project ▸ Properties ▸ General ▸ Save paths: Relative**, so the project keeps working when
   the folder is moved or zipped.
4. **Project ▸ Save As…** → `ddot_dashboard.qgz` in the project folder (next to `shapefiles/`).

### Step 2 - Load the shapefiles

1. **Layer ▸ Add Layer ▸ Add Vector Layer…** (Ctrl+Shift+V) → `…` → open `shapefiles/`, select all
   six `.shp` files → **Add**. (Or drag them in from the Browser panel.)
2. Arrange them top to bottom: points above lines. Leave the two question layers off.

   1. `permits_filtered_snapped`
   2. `service_requests_filtered`
   3. `subblocks_with_permits_and_srs`
   4. `subblocks_with_open_srs` (off)
   5. `subblocks_with_permits` (off)
   6. `roadway_subblock_filtered`

> Keep the file names as layer names for now. The KPI expressions in Step 10 refer to layers by
> name. If you rename later, update those expressions to match.

### Step 3 - Basemap with street names

1. Browser panel → **XYZ Tiles** → double-click **OpenStreetMap**. It shows street names at every
   zoom level.
2. *Optional, quieter background:* right-click **XYZ Tiles ▸ New Connection…**, name
   `Esri World Light Gray`, URL
   `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
   max zoom `16`. This one has **no** street names, so pair it with the labels in Step 4.
3. Drag the basemaps to the **bottom** of the Layers panel.

### Step 4 - Symbology and street labels

Open each layer's **Properties** (double-click it) ▸ **Symbology**.

| Layer | Renderer | Settings |
| --- | --- | --- |
| `roadway_subblock_filtered` | **Categorized** on `ACTIVITY` → **Classify** | No activity `#c8c8c8` 0.26 mm · Permit only `#1b9e77` 0.6 · SR only `#3b75af` 0.6 · Permit + SR `#d7191c` 1.2. Then **Advanced ▸ Symbol Levels ▸ Enable** so conflicts draw on top. |
| `subblocks_with_permits_and_srs` | **Single Symbol** | Line `#ffd400` 2.6 mm, then **+** add a second line `#d7191c` 1.3 mm (a red line on a yellow halo) |
| `permits_filtered_snapped` | **Rule-based** | `"SNAPPED" = 1` magenta circle `#8e0152` 2.4 · `"SNAPPED" = 0` orange diamond `#ff7f00` 3.0 |
| `service_requests_filtered` | **Categorized** on `STATUS` | Triangles, size 2.8 (`OPEN`, `PENDING`, `INSPCOMP`, …) |
| `subblocks_with_permits` | **Graduated** on `PRMT_CNT` | Natural Breaks (Jenks), 5 classes, ramp *Greens* |
| `subblocks_with_open_srs` | **Graduated** on `SR_CNT` | 5 classes, ramp *Blues* |

**Street-name labels** on `roadway_subblock_filtered` (**Properties ▸ Labels**):

1. Choose **Single Labels**. Next to *Value*, click **ε** and enter
   `CASE WHEN "ROUTENAME" NOT LIKE 'Ramp-%' THEN "ROUTENAME" END`
   (ramps have generated names such as `Ramp-36005282`, so they are skipped).
2. **Text**: size 8, colour dark grey. **Buffer**: tick *Draw text buffer*, 0.8 mm white.
3. **Placement**: Mode **Curved**.
4. **Rendering**: tick *Scale dependent visibility*, Minimum `1:20,000`, so labels don't clutter
   the city-wide view. Tick *Merge connected lines to avoid duplicate labels*.
5. **OK**, then zoom in to check.

Optional: also label `subblocks_with_permits_and_srs` with `ROUTENAME` in bold red, with no scale
limit, so the 90 conflicts are named even when zoomed out.

**Points only when zoomed in:** for permits and service requests, **Properties ▸ Rendering ▸
Scale Dependent Visibility**, Minimum `1:50,000`.

**Save** (Ctrl+S).

---

## Step 5 - Pop-ups on hover (Map Tips)

1. **Properties ▸ Display ▸ HTML Map Tip** for each layer, and paste:

   **Subblock layers**
   ```html
   <b>[% "ROUTENAME" %]</b> - Ward [% "WARD_ID" %] ([% "ROAD_CLASS" %])<br>
   Permits: <b>[% "PRMT_CNT" %]</b>, latest expiry [% format_date("PRMT_EXPMX", 'yyyy-MM-dd') %]<br>
   Open SRs: <b>[% "SR_CNT" %]</b>, latest [% format_date("SR_INITMX", 'yyyy-MM-dd') %]<br>
   [% "ACTIVITY" %]
   ```

   **Permits**
   ```html
   <b>[% "PERMIT_NO" %]</b><br>[% "ADDRESS" %]<br>
   Expires [% format_date("EXP_DATE", 'yyyy-MM-dd') %] · moved [% round("NEAR_FT", 1) %] ft when snapped
   ```

   **Service requests**
   ```html
   <b>SR [% "REQUEST_ID" %]</b> - [% "DESCRIPT" %]<br>
   [% "STATUS" %] since [% format_date("INIT_DATE", 'yyyy-MM-dd') %]<br>[% "ADDRESS" %]
   ```

2. Turn on **View ▸ Show Map Tips** (speech-bubble button) and hover over a feature.
3. **Check:** hovering a red/yellow conflict line shows both a permit count and an SR count above 0.

## Step 6 - Filters

| Goal | How | Expression |
| --- | --- | --- |
| One ward only | Right-click layer ▸ **Filter…** (a funnel icon marks it) | `"WARD_ID" = '6'` (service requests and permits: `"WARD" = '6'`) |
| Permits expiring this year | Filter on `permits_filtered_snapped` | `"EXP_DATE" <= to_date('2026-12-31')` |
| Subblocks with recent SRs | Filter on a subblock layer | `"SR_INITMX" >= to_date('2026-10-01')` |
| Worst conflicts, without hiding the rest | **Select by Expression** (Ctrl+F3) | `"FLAG_BOTH" = 1 AND "SR_CNT" >= 3` |
| Find a street | Attribute table (F6) ▸ search box, or the **Locator** bar (bottom-left) | `ROUTENAME` contains `GEORGIA` |

To remove a filter, open **Filter…** again and clear the box.

**Map Themes** save a set of visible layers as a named view. Click the eye icon at the top of the
Layers panel ▸ **Add Theme…**, e.g. *Conflicts only* and *All activity*, then switch between them.

## Step 7 - Live totals (Statistics panel)

1. **View ▸ Panels ▸ Statistics**.
2. Layer `roadway_subblock_filtered`:
   * field `FLAG_BOTH` → **Sum** = conflict subblocks (**90**);
   * field `PRMT_CNT` → **Sum** = permit records on the network (**9,294**);
   * field `SR_CNT` → **Sum** = open SRs on the network (**634**).
3. Tick **Selected features only** to get totals for whatever you selected in Step 6.

(651 SRs and 9,345 permits were downloaded. The few that were too far from any street to assign to
a subblock aren't counted in these sums.)

## Step 8 - Charts (DataPlotly plugin)

1. **Plugins ▸ Manage and Install Plugins…** → search **DataPlotly** → **Install**.
2. **View ▸ Panels ▸ DataPlotly**. For each chart: pick the plot type and layer, set the fields,
   then **Create Plot**.

   | Chart | Type | Layer | X field | Notes |
   | --- | --- | --- | --- | --- |
   | Open SRs by ward | Histogram | `service_requests_filtered` | `WARD` | |
   | SRs by status | Pie | `service_requests_filtered` | `STATUS` | |
   | Permit expirations | Histogram | `permits_filtered_snapped` | `EXP_DATE` | 24 bins |
   | Conflicts by ward | Histogram | `subblocks_with_permits_and_srs` | `WARD_ID` | |

3. In each plot's **Properties**, tick **Use only selected features** (or *visible features*). The
   chart then follows your filters and selections, and clicking a bar selects those features on
   the map.

## Step 9 - Top-conflicts table

1. Open the attribute table of `subblocks_with_permits_and_srs` (select it, press F6).
2. Click the `SR_CNT` header twice to sort high to low.
3. Right-click a row ▸ **Zoom to Feature**.
4. **Conditional formatting** (palette button) → **Full row** → **+** → condition
   `"SR_CNT" >= 3 AND "PRMT_CNT" >= 3`, light red background.

## Step 10 - One-page printable dashboard

1. **Project ▸ New Print Layout…** → `Dashboard`. Right-click the page ▸ **Page Properties** →
   A3, Landscape.
2. **Title** - **Add Item ▸ Add Label**:
   `DDOT Maintenance Operations - Permits vs Open Service Requests` (20 pt bold). A second label:
   `Data as of [% format_date(now(), 'MMMM d, yyyy') %]`.
3. **Map** - **Add Item ▸ Add Map**, drawn over the left ~60% of the page.
4. **KPI tiles** - four labels across the top right, each with a coloured *Background*. Use
   **Insert/Edit Expression** to enter:

   | Tile | Expression |
   | --- | --- |
   | Subblocks with permits | `[% aggregate('subblocks_with_permits', 'count', "SUBBLK_UID") %]` |
   | Subblocks with open SRs | `[% aggregate('subblocks_with_open_srs', 'count', "SUBBLK_UID") %]` |
   | **Conflict subblocks** | `[% aggregate('subblocks_with_permits_and_srs', 'count', "SUBBLK_UID") %]` |
   | Latest permit expiry | `[% format_date(aggregate('roadway_subblock_filtered', 'max', "PRMT_EXPMX"), 'yyyy-MM-dd') %]` |

   The first argument is the **layer name as shown in the Layers panel**. In Route A the layers
   have descriptive names, so either rename them to the file names or pick the layer from the
   expression builder's *Map Layers* list.
5. **Chart** - **Add Item ▸ Add Plot Item** (DataPlotly) → *Setup Selected Plot* → *Open SRs by
   ward*.
6. **Top-10 table** - **Add Item ▸ Add Attribute Table**, layer `subblocks_with_permits_and_srs`:
   * **Attributes…**: keep `ROUTENAME`, `WARD_ID`, `PRMT_CNT`, `PRMT_EXPMX`, `SR_CNT`, `SR_INITMX`;
     give them readable headings; *Sorting* → `SR_CNT` descending, then `PRMT_CNT` descending.
   * *Maximum rows* `10`; tick *Show only features visible within a map* → your map.
7. **Legend** (untick *Auto update*, then remove the basemaps and question layers), **Scale Bar**
   (feet) and **North Arrow**.
8. **Layout ▸ Export as PDF…** → `dashboard.pdf`.

## Step 11 - Drill-down pages (Atlas, optional)

1. In the Dashboard layout: **Atlas ▸ Atlas Settings** → tick *Generate an atlas*.
   * Coverage layer: `subblocks_with_permits_and_srs`
   * Page name: `"ROUTENAME" || ' (Ward ' || "WARD_ID" || ')'`
   * Sort by: `SR_CNT`, descending
2. Select the map item → **Item Properties** → tick **Controlled by Atlas**, margin 300%.
3. Set the title label to `[% @atlas_pagename %]`. In the table's *Feature filtering*, tick
   *Show only features intersecting atlas feature*.
4. Preview with the Atlas toolbar arrows, then **Atlas ▸ Export Atlas as PDF…**. You get one page
   per conflict subblock (**90 pages**).

## Step 12 - Save, share, refresh

* **Save** (Ctrl+S). Paths are relative, so zip `ddot_dashboard.qgz` with the `shapefiles/` folder
  and it opens on any machine with QGIS 3.28 or later.
* **New data:** re-run `01_pull_and_process_data.py`, then `02_create_qgis_project.py`. The
  shapefiles are rewritten with the same names and fields, so reopening `ddot_dashboard.qgz`
  shows the new data with your styling, filters and layout intact. (On Windows + WSL, copy the
  folder to the Windows drive afterwards; see README section 7.)

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Many layers unavailable, `database is locked` | Project opened from `\\wsl.localhost\...`. Open the copy on the Windows drive. |
| Layer shows a red **!** after moving the folder | Right-click ▸ **Change Data Source…** → point it to `shapefiles/`. |
| No street names | Zoom in past 1:20,000 (Step 4), or turn on the OpenStreetMap basemap. The Esri Light Gray basemap has no street names. |
| Basemap blank | Basemaps need internet; the shapefiles work offline. |
| KPI tile shows `NULL` or 0 | The layer name in `aggregate()` doesn't match the Layers panel name. |
| Ward filter returns nothing | Wards are text: `'6'`, not `6`. |
| Date filter returns nothing | Use `to_date('YYYY-MM-DD')`; shapefile dates have no time. |
| DataPlotly item missing from the layout | Install the plugin (Step 8) and restart QGIS. |
