# Building a QGIS Dashboard from the Shapefiles

Step-by-step instructions for building an interactive map dashboard and a printable one-page
dashboard by hand in **QGIS 3.40 LTR**, using only the six files in `shapefiles/`. No Python is
needed. Allow 45-60 minutes.

The finished project has:

* an interactive map with the conflict subblocks, permits and service requests, with pop-up details
  for any feature you hover over;
* live KPI totals and charts that update as you filter or select;
* a one-page **Print Layout dashboard** (map, KPIs, chart and a top-10 table) that exports to PDF;
* an **Atlas** that prints one zoomed page per conflict subblock.

> Field names are the 10-character shapefile names. `shapefiles/field_crosswalk.csv` maps each one
> to its full GeoPackage name and description (see also README section 5).

---

## Part 1 - Project setup

1. Start QGIS → **Project ▸ New**.
2. **Project ▸ Properties ▸ CRS**: search `2248` and pick *NAD83 / Maryland (ftUS)*. Click **OK**.
3. **Project ▸ Properties ▸ General**: set *Save paths* to **Relative**. The project then still
   works after the folder is zipped or moved.
4. **Project ▸ Save As…** → save `ddot_dashboard.qgz` in the project folder (next to `shapefiles/`).

## Part 2 - Basemap

1. In the **Browser** panel, right-click **XYZ Tiles ▸ New Connection…**
2. Name `Esri World Light Gray`, URL:
   `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
   Max. Zoom Level `16` → **OK**.
3. Double-click the new connection to add it. Keep it at the **bottom** of the Layers panel.

## Part 3 - Load the shapefiles

1. **Layer ▸ Add Layer ▸ Add Vector Layer…** (Ctrl+Shift+V) → *Source* `…` → browse to
   `shapefiles/`, multi-select all six `.shp` files → **Add**.
   (Alternatively drag them from the Browser panel.)
2. Create groups (right-click in the Layers panel ▸ **Add Group**) and arrange top-to-bottom:

   | Group | Layers (top → bottom) | Visible |
   | --- | --- | --- |
   | **Dashboard** | `subblocks_with_permits_and_srs`, `permits_filtered_snapped`, `service_requests_filtered`, `roadway_subblock_filtered` | all on |
   | **Question layers** | `subblocks_with_permits`, `subblocks_with_open_srs` | off |
   | **Basemap** | Esri World Light Gray | on |

3. Rename layers for readers (right-click ▸ **Rename Layer**), e.g.
   `Conflict subblocks (permit + open SR)`, `Permits (snapped)`, `Open service requests`,
   `Roadway subblocks`. **Note:** the expressions below use the *original file names*. If you rename,
   use the new names in Parts 7-9, or use the layer ID from the expression builder's *Map Layers* list.

## Part 4 - Symbology

Open each layer's **Properties ▸ Symbology** (double-click the layer).

**Roadway subblocks** (`roadway_subblock_filtered`)
1. Choose **Categorized**, *Value* `ACTIVITY` → **Classify**.
2. Set the colours/widths:

   | Value | Colour | Width (mm) |
   | --- | --- | --- |
   | No activity | `#c8c8c8` | 0.26 |
   | Permit only | `#1b9e77` | 0.6 |
   | SR only | `#3b75af` | 0.6 |
   | Permit + SR | `#d7191c` | 1.2 |

3. **Advanced ▸ Symbol Levels…** → tick *Enable symbol levels* so conflicts draw on top.

**Conflict subblocks** (`subblocks_with_permits_and_srs`)
1. **Single Symbol** → simple line `#ffd400`, width 2.6 mm.
2. Click **+** (Add symbol layer) → simple line `#d7191c`, width 1.3 mm. This draws a red line on a
   yellow halo.

**Permits** (`permits_filtered_snapped`)
1. **Rule-based**. Edit the default rule: filter `"SNAPPED" = 1`, label `Snapped`, magenta circle
   `#8e0152`, size 2.4.
2. Add a rule: filter `"SNAPPED" = 0`, label `Not snapped (> 150 ft)`, orange diamond `#ff7f00`,
   size 3.

**Open service requests** (`service_requests_filtered`)
1. **Categorized** on `STATUS` → **Classify** (`OPEN`, `PENDING`, `INSPCOMP`, …), triangle markers,
   size 2.8.

**Question layers** (optional, for answering the request directly)
* `subblocks_with_permits`: **Graduated**, *Value* `PRMT_CNT`, mode *Natural Breaks (Jenks)*,
  5 classes, colour ramp *Greens*.
* `subblocks_with_open_srs`: **Graduated**, *Value* `SR_CNT`, ramp *Blues*.

**Scale-dependent visibility** (keeps the city-wide view readable): for permits and service requests,
**Properties ▸ Rendering ▸ Scale Dependent Visibility**, Minimum `1:50,000`.

## Part 5 - Labels and pop-ups

**Labels on conflict subblocks**
1. **Properties ▸ Labels ▸ Single Labels**, *Value* `STREETNAME`.
2. **Buffer**: tick *Draw text buffer*, 1 mm white. **Placement**: *Curved*.
3. **Rendering**: scale-based visibility, Minimum `1:25,000`.

**Hover pop-ups (Map Tips)**
1. **Properties ▸ Display ▸ HTML Map Tip**. For `subblocks_with_permits_and_srs` and
   `roadway_subblock_filtered` paste:

   ```html
   <b>[% "STREETNAME" %]</b> ([% "FROMSTREET" %] to [% "TOSTREET" %])<br>
   Ward [% "WARD_ID" %] · [% "ROAD_CLASS" %]<br>
   Permits: <b>[% "PRMT_CNT" %]</b> (latest expiry [% format_date("PRMT_EXPMX", 'yyyy-MM-dd') %])<br>
   Open SRs: <b>[% "SR_CNT" %]</b> (latest [% format_date("SR_INITMX", 'yyyy-MM-dd') %])<br>
   Class: [% "ACTIVITY" %]
   ```

2. For permits:
   `<b>[% "PERMIT_NO" %]</b><br>[% "ADDRESS" %]<br>Expires [% format_date("EXP_DATE",'yyyy-MM-dd') %]<br>Snap distance [% round("NEAR_FT",1) %] ft`
3. For service requests:
   `<b>SR [% "REQUEST_ID" %]</b> - [% "DESCRIPT" %]<br>[% "STATUS" %] since [% format_date("INIT_DATE",'yyyy-MM-dd') %]<br>[% "ADDRESS" %]`
4. **View ▸ Show Map Tips** (or the speech-bubble toolbar button). Hover a feature to see its pop-up.

## Part 6 - Interactive filters

QGIS has no slicer widget, but these three methods give the same result:

| To… | Do this |
| --- | --- |
| Filter a layer permanently (e.g. one ward) | Right-click layer ▸ **Filter…** → `"WARD_ID" = '6'` (wards are text). A funnel icon marks filtered layers; clear the box to remove the filter. |
| Filter by date | `"PRMT_EXPMX" <= to_date('2026-12-31')` (permits expiring this year), or `"SR_INITMX" >= to_date('2026-10-01')` |
| Select without hiding | **Edit ▸ Select ▸ Select Features by Expression** (Ctrl+F3), e.g. `"SR_CNT" >= 3`. KPIs and charts can be set to *selected features only*. |
| Find a street | Type in the **Locator** bar (bottom-left) after enabling *Active layer features* in **Settings ▸ Options ▸ Locator**, or use the attribute table search. |

Tip: **Map Themes** (the eye icon in the Layers panel ▸ *Add Theme…*) save
named views such as "Conflicts only" or "Permits by ward" that you can switch between with one click.

## Part 7 - KPI panel

1. **View ▸ Panels ▸ Statistics**.
2. Choose layer `roadway_subblock_filtered`, field `PRMT_CNT` → shows **Sum** (total permit records on
   the network), Count, Max, etc. Switch the field to `SR_CNT` or `FLAG_BOTH` (Sum = number of conflict
   subblocks).
3. Tick **Selected features only** to get KPIs for whatever you selected in Part 6.

Expected totals for the current data run: 9,294 permit records on subblocks, 634 open SRs,
90 conflict subblocks.

## Part 8 - Charts (DataPlotly plugin)

1. **Plugins ▸ Manage and Install Plugins…** → search **DataPlotly** → **Install**.
2. **View ▸ Panels ▸ DataPlotly**. Build these charts (click **Create Plot** after each; tick
   *Use only selected features* / *Use only visible features* in the plot's **Properties** to make
   charts follow the map):

   | Chart | Plot type | Layer | X | Y / setting |
   | --- | --- | --- | --- | --- |
   | Open SRs by ward | Histogram | `service_requests_filtered` | `WARD` | - |
   | SRs by status | Pie chart | `service_requests_filtered` | `STATUS` | - |
   | Permit expirations over time | Histogram | `permits_filtered_snapped` | `EXP_DATE` | Bins 24 |
   | Activity mix | Bar plot | `roadway_subblock_filtered` | `ACTIVITY` | `$length / 5280` with *Aggregation*: sum (miles) |

3. Clicking a bar in a DataPlotly chart selects the matching features on the map.

## Part 9 - Attribute table "top conflicts"

1. Open the attribute table of `subblocks_with_permits_and_srs` (F6).
2. Click the `SR_CNT` header twice to sort descending.
3. Right-click a row ▸ **Zoom to Feature** to fly the map there.
4. **Conditional Styling** (the paint-palette button in the table toolbar) → *Rows* → rule
   `"SR_CNT" >= 3 AND "PRMT_CNT" >= 3` with a light red background to highlight the worst cases.

## Part 10 - One-page printable dashboard (Print Layout)

1. **Project ▸ New Print Layout…** → name `Dashboard`. Right-click the page ▸ **Page Properties**:
   A3 Landscape.
2. **Title**: **Add Item ▸ Add Label**, text
   `DDOT Maintenance Operations - Permits vs Open Service Requests`, 20 pt bold.
   Add a second label for the date: `Data as of [% format_date(now(), 'MMMM d, yyyy') %]`.
3. **Map**: **Add Item ▸ Add Map**, drag over the left ~60% of the page. In *Item Properties* tick
   *Lock layers* only if you want it to ignore later changes to the Layers panel.
4. **KPI tiles**: add four labels across the top-right, each with a coloured background
   (*Item Properties ▸ Background*), using these expressions (Insert/Edit Expression):

   | Tile | Expression |
   | --- | --- |
   | Subblocks with permits | `[% aggregate('subblocks_with_permits', 'count', "SUBBLK_UID") %]` |
   | Subblocks with open SRs | `[% aggregate('subblocks_with_open_srs', 'count', "SUBBLK_UID") %]` |
   | **Conflict subblocks** | `[% aggregate('subblocks_with_permits_and_srs', 'count', "SUBBLK_UID") %]` |
   | Latest permit expiry | `[% format_date(aggregate('roadway_subblock_filtered', 'max', "PRMT_EXPMX"), 'yyyy-MM-dd') %]` |

5. **Chart**: with DataPlotly installed, **Add Item ▸ Add Plot Item**. In its properties, click
   *Setup Selected Plot* and choose *Open SRs by ward* (as in Part 8). Tick
   *Use only features inside map item* so the chart follows the map extent.
6. **Top-10 table**: **Add Item ▸ Add Attribute Table**, layer `subblocks_with_permits_and_srs`.
   * **Attributes…** → keep `STREETNAME`, `WARD_ID`, `PRMT_CNT`, `PRMT_EXPMX`, `SR_CNT`, `SR_INITMX`;
     rename headings; under *Sorting* add `SR_CNT` descending, then `PRMT_CNT` descending.
   * *Maximum rows*: `10`. Tick *Show only features visible within a map* → the map from step 3.
7. **Legend** (**Add Item ▸ Add Legend**): untick *Auto update*, remove the basemap and question
   layers. Add a **Scale Bar** (feet) and **North Arrow**.
8. **Layout ▸ Export as PDF…** (or Image) → `dashboard.pdf`.

## Part 11 - Drill-down pages with Atlas (optional)

1. In the Dashboard layout: **Atlas ▸ Atlas Settings** → tick *Generate an atlas*.
   *Coverage layer* `subblocks_with_permits_and_srs`, *Page name* `"STREETNAME" || ' (Ward ' || "WARD_ID" || ')'`,
   *Sort by* `SR_CNT` descending.
2. Select the map item → *Item Properties ▸ Controlled by Atlas* → *Margin around feature* 300%.
3. Change the title label to `[% @atlas_pagename %]` and the table to *Filter with* the atlas feature
   (*Attribute table ▸ Feature filtering ▸ Show only features intersecting atlas feature*).
4. Use the Atlas toolbar arrows to preview, then **Atlas ▸ Export Atlas as PDF…** → one page per
   conflict subblock (90 pages for the current run).

## Part 12 - Save and share

1. **Project ▸ Save** (Ctrl+S). Because paths are relative (Part 1), zip `ddot_dashboard.qgz`
   together with the `shapefiles/` folder and it opens on any machine with QGIS 3.28+.
2. Re-running `02_create_qgis_project.py` regenerates the shapefiles in place with the same names
   and fields, so the dashboard picks up new data on reopen. Layout styling is kept, but any
   *Filter…* expressions are re-applied to the new data.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Layer shows a red "!" after moving the folder | Right-click ▸ **Change Data Source…**, or reopen the project with *Handle Bad Layers* and point to `shapefiles/`. |
| KPI label shows `NULL` | Layer name in `aggregate()` doesn't match the Layers panel name (see Part 3 note). |
| Date filter returns nothing | Compare with `to_date('YYYY-MM-DD')`, not a plain string; shapefile dates have no time part. |
| Basemap is blank | It needs internet access; the analysis layers work offline. |
| Ward filter returns nothing | Wards are text: `'6'`, not `6`. |
