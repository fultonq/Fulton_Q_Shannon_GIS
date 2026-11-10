"""
Step 2 - Geoprocessing (QGIS Processing, headless).

Inputs : data/raw/raw_downloads.gpkg  (from 01_download.py)
Outputs: data/output/CS12_Roadway_Enrichment.gpkg  (local "geodatabase")
         data/output/shapefiles/*.shp              (shapefile copies)
         docs/geoprocessing_history.json            (every processing.run call)

Run with:  X:\\QGIS\\bin\\python-qgis.bat 02_process.py
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env as Q  # noqa: E402

Q.start()
from qgis.core import QgsProcessingFeatureSourceDefinition, QgsVectorLayer  # noqa: E402,F401

# --------------------------------------------------------------------------------------
# Parameters (documented in docs/APPROACH.md)
# --------------------------------------------------------------------------------------
# Tolerances chosen from scripts/diag_snap_distance.py (see docs/APPROACH.md):
#  - permits: 9,934 / 10,008 are <= 5 m from a street/service/ramp subblock and none fall
#    between 5 and 15 m, so 10 m is a clean break. All 10,008 are <= 4.8 m from *some*
#    subblock, so the remainder (alley/driveway/walkway permits) snap to that line instead.
#  - SRs are address-geocoded (p90 = 21.6 m), so they are assigned with 50 m (643 / 653).
SNAP_TOL_M = 10.0
SR_TOL_M = 50.0
DATE_CUTOFF = "2025-10-01 00:00:00"

PERMIT_FILTER = (
    f"\"ExpirationDate\" >= to_datetime('{DATE_CUTOFF}') "
    "AND \"RenewalDescription\" = 'Renewal' "
    "AND \"StatusDescription\" = 'Issued' "
    "AND (\"IsExcavation\" = 1 OR \"IsPaving\" = 1)"
)
# ROADTYPE coded-value domain: 1 Street, 2 Service Road, 3 Ramp (4 Alley, 5 Driveway, ...)
SUBBLOCK_FILTER = "\"ROADTYPE\" IN ('1', '2', '3')"
# Provided Cityworks definition query, translated to QGIS expression syntax
SR_FILTER = (
    "\"STATUS\" NOT IN ('CLOSED', 'CANCEL', 'COMPLETE') "
    "AND \"DESCRIPTION\" IN ('ROADWAY REPAIR', 'POTHOLES', 'STREET REPAVING', "
    "'STREET REPAIR', 'STREET PAVING SCHEDU') "
    f"AND \"INITIATEDDATE\" >= to_datetime('{DATE_CUTOFF}')"
)

RAW = Q.RAW_GPKG
OUT = Q.OUT_GPKG
TMP = "TEMPORARY_OUTPUT"


def src(layer):
    return f"{RAW}|layername={layer}"


def dst(layer):
    return f"ogr:dbname='{OUT}' table=\"{layer}\" (geom)"


def dst_tab(layer):
    return f"ogr:dbname='{OUT}' table=\"{layer}\""


if os.path.exists(OUT):
    os.remove(OUT)
os.makedirs(os.path.dirname(OUT), exist_ok=True)

# --------------------------------------------------------------------------------------
# 1. Filters
# --------------------------------------------------------------------------------------
permits_f = Q.run("01 Filter permits", "native:extractbyexpression", {
    "INPUT": src("permits_raw"), "EXPRESSION": PERMIT_FILTER, "OUTPUT": TMP},
    "Renewal + Issued + Excavation/Paving + ExpirationDate >= 2025-10-01")["OUTPUT"]

subblock_f = Q.run("02 Filter roadway subblocks", "native:extractbyexpression", {
    "INPUT": src("roadway_subblock_raw"), "EXPRESSION": SUBBLOCK_FILTER, "OUTPUT": TMP},
    "ROADTYPE Street(1) / Service Road(2) / Ramp(3)")["OUTPUT"]

sr_f = Q.run("03 Filter Cityworks service requests", "native:extractbyexpression", {
    "INPUT": src("cityworks_sr_raw"), "EXPRESSION": SR_FILTER, "OUTPUT": TMP},
    "Provided definition query (open/pending/inspection, roadway descriptions, >= 2025-10-01)")["OUTPUT"]

Q.run("03b Spatial index on subblocks", "native:createspatialindex", {"INPUT": subblock_f})

# --------------------------------------------------------------------------------------
# 2. Snap permits to the nearest filtered subblock centerline
#    Join-by-nearest returns the closest point on the line (nearest_x / nearest_y) and the
#    distance, plus the subblock key, so snapping and block assignment stay consistent.
# --------------------------------------------------------------------------------------
SB_FIELDS = ["SUBBLOCKKEY", "SUBBLOCKID", "ROUTENAME", "ROADTYPE"]

j1 = Q.run("04 Nearest street/service/ramp subblock for each permit", "native:joinbynearest", {
    "INPUT": permits_f, "INPUT_2": subblock_f, "FIELDS_TO_COPY": SB_FIELDS,
    "DISCARD_NONMATCHING": True, "PREFIX": "SB_", "NEIGHBORS": 1,
    "MAX_DISTANCE": SNAP_TOL_M, "OUTPUT": TMP, "NON_MATCHING": TMP},
    f"k=1 within {SNAP_TOL_M} m of the filtered roadway")

j2 = Q.run("05 Fallback: nearest subblock of ANY road type (alley/driveway/walkway permits)",
           "native:joinbynearest", {
    "INPUT": j1["NON_MATCHING"], "INPUT_2": src("roadway_subblock_raw"), "FIELDS_TO_COPY": SB_FIELDS,
    "DISCARD_NONMATCHING": False, "PREFIX": "SB_", "NEIGHBORS": 1,
    "MAX_DISTANCE": SNAP_TOL_M, "OUTPUT": TMP},
    "these are snapped but NOT counted on the filtered blocks")

p_near = Q.run("06 Merge snap results", "native:mergevectorlayers", {
    "LAYERS": [j1["OUTPUT"], j2["OUTPUT"]], "CRS": "EPSG:26985", "OUTPUT": TMP})["OUTPUT"]

# ties (equidistant subblocks at intersections) can return >1 row per permit - keep one
p_near = Q.run("07 Drop nearest-join ties (permits)", "native:removeduplicatesbyattribute", {
    "INPUT": p_near, "FIELDS": ["OBJECTID"], "OUTPUT": TMP})["OUTPUT"]

p_near = Q.run("08 Snap distance (permits)", "native:fieldcalculator", {
    "INPUT": p_near, "FIELD_NAME": "SNAP_DIST", "FIELD_TYPE": 0, "FIELD_LENGTH": 12,
    "FIELD_PRECISION": 3, "FORMULA": "round(\"distance\", 3)", "OUTPUT": TMP})["OUTPUT"]
p_near = Q.run("09 Snap status (permits)", "native:fieldcalculator", {
    "INPUT": p_near, "FIELD_NAME": "SNAP_STAT", "FIELD_TYPE": 2, "FIELD_LENGTH": 60,
    "FIELD_PRECISION": 0,
    "FORMULA": "CASE WHEN \"nearest_x\" IS NULL THEN 'NOT SNAPPED' "
               "WHEN \"SB_ROADTYPE\" IN ('1','2','3') THEN 'SNAPPED - street/service lane/ramp' "
               "ELSE 'SNAPPED - alley/driveway/other (not counted)' END",
    "OUTPUT": TMP})["OUTPUT"]
p_near = Q.run("10 COUNTED flag (permit is on a filtered subblock)", "native:fieldcalculator", {
    "INPUT": p_near, "FIELD_NAME": "COUNTED", "FIELD_TYPE": 1, "FIELD_LENGTH": 1,
    "FIELD_PRECISION": 0, "FORMULA": "if(\"SB_ROADTYPE\" IN ('1','2','3'), 1, 0)",
    "OUTPUT": TMP})["OUTPUT"]

Q.run("11 QA lines: original -> snapped location", "native:geometrybyexpression", {
    "INPUT": p_near, "OUTPUT_GEOMETRY": 1, "WITH_Z": False, "WITH_M": False,
    "EXPRESSION": "if(\"nearest_x\" IS NULL, NULL, make_line($geometry, make_point(\"nearest_x\", \"nearest_y\")))",
    "OUTPUT": dst("permit_snap_lines")})

permits_snapped = Q.run("12 Move permits onto the roadway (snapped geometry)",
                        "native:geometrybyexpression", {
    "INPUT": p_near, "OUTPUT_GEOMETRY": 2, "WITH_Z": False, "WITH_M": False,
    "EXPRESSION": "if(\"nearest_x\" IS NULL, $geometry, make_point(\"nearest_x\", \"nearest_y\"))",
    "OUTPUT": TMP})["OUTPUT"]

permits_snapped = Q.run("13 Tidy helper fields (permits)", "native:deletecolumn", {
    "INPUT": permits_snapped, "COLUMN": ["n", "distance", "feature_x", "feature_y", "layer", "path"],
    "OUTPUT": dst("permits_filtered_snapped")})["OUTPUT"]

Q.run("14 Save filtered permits (original location)", "native:savefeatures", {
    "INPUT": permits_f, "OUTPUT": OUT, "LAYER_NAME": "permits_filtered_original",
    "ACTION_ON_EXISTING_FILE": 1})

# --------------------------------------------------------------------------------------
# 3. Assign each service request to its nearest filtered subblock
# --------------------------------------------------------------------------------------
s_near = Q.run("15 Nearest subblock for each service request", "native:joinbynearest", {
    "INPUT": sr_f, "INPUT_2": subblock_f, "FIELDS_TO_COPY": SB_FIELDS,
    "DISCARD_NONMATCHING": False, "PREFIX": "SB_", "NEIGHBORS": 1,
    "MAX_DISTANCE": SR_TOL_M, "OUTPUT": TMP},
    f"k=1 within {SR_TOL_M} m")["OUTPUT"]
s_near = Q.run("16 Drop nearest-join ties (SRs)", "native:removeduplicatesbyattribute", {
    "INPUT": s_near, "FIELDS": ["OBJECTID"], "OUTPUT": TMP})["OUTPUT"]
s_near = Q.run("17 Distance to subblock (SRs)", "native:fieldcalculator", {
    "INPUT": s_near, "FIELD_NAME": "SB_DIST", "FIELD_TYPE": 0, "FIELD_LENGTH": 12,
    "FIELD_PRECISION": 3, "FORMULA": "round(\"distance\", 3)", "OUTPUT": TMP})["OUTPUT"]
Q.run("18 Save filtered SRs with subblock assignment", "native:deletecolumn", {
    "INPUT": s_near, "COLUMN": ["n", "distance", "feature_x", "feature_y", "nearest_x", "nearest_y"],
    "OUTPUT": dst("cityworks_sr_filtered")})

# --------------------------------------------------------------------------------------
# 4. Summaries per subblock
# --------------------------------------------------------------------------------------
STR, INT, DT = 10, 2, 16  # QMetaType ids: QString, Int, QDateTime


def agg(input_layer, key, count_name, date_field, date_name, step, out_name):
    a = Q.run(step, "native:aggregate", {
        "INPUT": input_layer,
        "GROUP_BY": f"\"{key}\"",
        "AGGREGATES": [
            {"aggregate": "first_value", "delimiter": ",", "input": f"\"{key}\"",
             "length": 255, "name": "SUBBLOCKKEY", "precision": 0, "type": STR},
            {"aggregate": "count", "delimiter": ",", "input": "\"OBJECTID\"",
             "length": 0, "name": count_name, "precision": 0, "type": INT},
            {"aggregate": "maximum", "delimiter": ",", "input": f"\"{date_field}\"",
             "length": 0, "name": date_name, "precision": 0, "type": DT},
        ],
        "OUTPUT": TMP})["OUTPUT"]
    return Q.run(step.split(" ")[0] + "b Drop geometry -> attribute table", "native:dropgeometries", {
        "INPUT": a, "OUTPUT": dst_tab(out_name)})["OUTPUT"]


p_ok = Q.run("19 Permits counted on a filtered subblock (COUNTED = 1)", "native:extractbyexpression", {
    "INPUT": permits_snapped, "EXPRESSION": "\"COUNTED\" = 1", "OUTPUT": TMP})["OUTPUT"]
p_sum = agg(p_ok, "SB_SUBBLOCKKEY", "PRMT_CNT", "ExpirationDate", "PRMT_MAXEX",
            "20 Permit count + max ExpirationDate per subblock", "summary_permits_by_subblock")

s_ok = Q.run("21 SRs assigned to a subblock", "native:extractbyexpression", {
    "INPUT": f"{OUT}|layername=cityworks_sr_filtered", "EXPRESSION": "\"SB_SUBBLOCKKEY\" IS NOT NULL",
    "OUTPUT": TMP})["OUTPUT"]
s_sum = agg(s_ok, "SB_SUBBLOCKKEY", "SR_CNT", "INITIATEDDATE", "SR_MAXINIT",
            "22 SR count + max INITIATEDDATE per subblock", "summary_sr_by_subblock")

# --------------------------------------------------------------------------------------
# 5. Enrich the subblocks
# --------------------------------------------------------------------------------------
e1 = Q.run("23 Join permit summary to subblocks", "native:joinattributestable", {
    "INPUT": subblock_f, "FIELD": "SUBBLOCKKEY", "INPUT_2": p_sum, "FIELD_2": "SUBBLOCKKEY",
    "FIELDS_TO_COPY": ["PRMT_CNT", "PRMT_MAXEX"], "METHOD": 1, "DISCARD_NONMATCHING": False,
    "PREFIX": "", "OUTPUT": TMP})["OUTPUT"]
e2 = Q.run("24 Join SR summary to subblocks", "native:joinattributestable", {
    "INPUT": e1, "FIELD": "SUBBLOCKKEY", "INPUT_2": s_sum, "FIELD_2": "SUBBLOCKKEY",
    "FIELDS_TO_COPY": ["SR_CNT", "SR_MAXINIT"], "METHOD": 1, "DISCARD_NONMATCHING": False,
    "PREFIX": "", "OUTPUT": TMP})["OUTPUT"]

lyr = e2 if isinstance(e2, QgsVectorLayer) else QgsVectorLayer(e2)
mapping = []
for f in lyr.fields():
    nm = f.name()
    expr = f"\"{nm}\""
    if nm in ("PRMT_CNT", "SR_CNT"):
        expr = f"coalesce(\"{nm}\", 0)"
    mapping.append({"name": nm, "type": f.type(), "sub_type": f.subType(), "type_name": f.typeName(),
                    "length": f.length(), "precision": f.precision(), "expression": expr})
mapping += [
    {"name": "HAS_PRMT", "type": INT, "length": 0, "precision": 0,
     "expression": "if(coalesce(\"PRMT_CNT\",0) > 0, 1, 0)"},
    {"name": "HAS_SR", "type": INT, "length": 0, "precision": 0,
     "expression": "if(coalesce(\"SR_CNT\",0) > 0, 1, 0)"},
    {"name": "BOTH_FLAG", "type": INT, "length": 0, "precision": 0,
     "expression": "if(coalesce(\"PRMT_CNT\",0) > 0 AND coalesce(\"SR_CNT\",0) > 0, 1, 0)"},
    {"name": "FLAG_CAT", "type": STR, "length": 20, "precision": 0,
     "expression": "CASE WHEN coalesce(\"PRMT_CNT\",0) > 0 AND coalesce(\"SR_CNT\",0) > 0 THEN 'Permits + SRs' "
                   "WHEN coalesce(\"PRMT_CNT\",0) > 0 THEN 'Permits only' "
                   "WHEN coalesce(\"SR_CNT\",0) > 0 THEN 'SRs only' ELSE 'Neither' END"},
]
enriched = Q.run("25 Fill zero counts + flag fields", "native:refactorfields", {
    "INPUT": e2, "FIELDS_MAPPING": mapping, "OUTPUT": dst("roadway_subblock_enriched")},
    "PRMT_CNT/SR_CNT nulls -> 0; HAS_PRMT, HAS_SR, BOTH_FLAG (1 = permits AND SRs), FLAG_CAT")["OUTPUT"]

Q.run("26 Subblocks with BOTH permits and SRs", "native:extractbyexpression", {
    "INPUT": f"{OUT}|layername=roadway_subblock_enriched", "EXPRESSION": "\"BOTH_FLAG\" = 1",
    "OUTPUT": dst("roadway_subblock_permits_and_sr")})

# --------------------------------------------------------------------------------------
# 6. Shapefile copies (for manual use; field names are cut to 10 characters)
# --------------------------------------------------------------------------------------
if os.path.isdir(Q.SHP_DIR):
    shutil.rmtree(Q.SHP_DIR)
os.makedirs(Q.SHP_DIR)
for i, name in enumerate(["roadway_subblock_enriched", "roadway_subblock_permits_and_sr",
                          "permits_filtered_snapped", "permits_filtered_original",
                          "cityworks_sr_filtered", "permit_snap_lines"]):
    # Shapefiles (DBF) have no datetime type, so OGR would write datetimes as text.
    # Convert them to true DBF Date fields; the GeoPackage keeps full date+time.
    src_lyr = QgsVectorLayer(f"{OUT}|layername={name}", name, "ogr")
    fmap = []
    for f in src_lyr.fields():
        if f.name().lower() == "fid":
            continue
        if f.type() == 16:  # QDateTime
            fmap.append({"name": f.name(), "type": 14, "length": 0, "precision": 0,
                         "expression": f"to_date(\"{f.name()}\")"})
        else:
            fmap.append({"name": f.name(), "type": f.type(), "sub_type": f.subType(),
                         "type_name": f.typeName(), "length": f.length(),
                         "precision": f.precision(), "expression": f"\"{f.name()}\""})
    shp_in = Q.run(f"{27 + i}a Shapefile prep (datetime -> date): {name}", "native:refactorfields", {
        "INPUT": src_lyr, "FIELDS_MAPPING": fmap, "OUTPUT": TMP})["OUTPUT"]
    Q.run(f"{27 + i}b Export shapefile: {name}", "native:savefeatures", {
        "INPUT": shp_in,
        "OUTPUT": os.path.join(Q.SHP_DIR, f"{name}.shp"),
        "LAYER_NAME": "", "DATASOURCE_OPTIONS": "", "LAYER_OPTIONS": "ENCODING=UTF-8;RESIZE=YES"})

Q.save_history()
print("\nHistory written to", Q.HISTORY_JSON)
