#!/usr/bin/env python3
"""
02_create_qgis_project.py - DDOT Maintenance Operations GIS Analysis

Exports one shapefile per filter / question in the data request to
shapefiles/, builds the QGIS project `ddot_maintenance_operations.qgz` from the
GeoPackage produced by 01_pull_and_process_data.py, validates the saved project
by reloading it, and packages the project folder as
<First>_<MI>_<Last>_GIS[_V<n>].zip.

Layer tree (V2):
    Analysis (local GeoPackage)
        Subblocks with BOTH permits and open SRs
        Permits - snapped to roadway subblock                  (SNAPPED = 1)
        Service requests - open roadway/pothole/paving
        Roadway subblock - enriched
        Roadway block (BLOCKID) - enriched                    (off)
    Shapefile exports (one per PDF filter / question)         (layers off)
    Source - live DC GIS REST services (filtered)             (layers off)
    QA - snapping & original locations                         (alley/driveway permits on, rest off)
    Insights & geoprocessing history (tables)
    Basemap: Esri World Light Gray (on), OpenStreetMap (off)

Must run with a Python interpreter that can import PyQGIS (QGIS >= 3.28):
    Linux   : python3 (system QGIS install)
    Windows : "C:\\Program Files\\QGIS 3.40.x\\bin\\python-qgis-ltr.bat"
    macOS   : /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3

Usage:
    python 02_create_qgis_project.py --first-name Jane --middle-initial Q --last-name Public --version-label V2
    python 02_create_qgis_project.py --no-package          # shapefiles + project only
    python 02_create_qgis_project.py --no-package --no-shapefiles
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Sequence

__version__ = "2.5.0"

LOG = logging.getLogger("ddot_gis.project")

PROJECT_TITLE = "DDOT Maintenance Operations - Permits, Service Requests & Subblocks"
QGZ_NAME = "ddot_maintenance_operations.qgz"
GPKG_REL = Path("data") / "ddot_maintenance_operations.gpkg"

LAYER_SUBBLOCKS = "roadway_subblock_enriched"
LAYER_BLOCKS = "roadway_block_enriched"
LAYER_PERMITS = "permits_snapped"
LAYER_SERVICE_REQUESTS = "service_requests_filtered"
LAYER_PERMITS_ORIGINAL = "permits_original"
LAYER_QA_PERMIT_SNAP = "qa_permit_snap_displacement"
LAYER_QA_SR_ASSIGN = "qa_sr_subblock_assignment"
TABLE_TOP_CONFLICTS = "insight_top_conflicts"
TABLE_WARD_SUMMARY = "insight_ward_summary"
TABLE_ACTIVITY_SUMMARY = "insight_activity_summary"
TABLE_HISTORY = "geoprocessing_history"

# Every GeoPackage layer the project must reference (checked after save).
REQUIRED_LAYERS = frozenset({
    LAYER_SUBBLOCKS, LAYER_BLOCKS, LAYER_PERMITS, LAYER_SERVICE_REQUESTS, LAYER_PERMITS_ORIGINAL,
    LAYER_QA_PERMIT_SNAP, LAYER_QA_SR_ASSIGN, TABLE_TOP_CONFLICTS, TABLE_WARD_SUMMARY,
    TABLE_ACTIVITY_SUMMARY, TABLE_HISTORY,
})

GROUP_ANALYSIS = "Analysis (local GeoPackage)"
GROUP_SHAPEFILES = "Shapefile exports (one per PDF filter / question)"
GROUP_SOURCE = "Source - live DC GIS REST services (filtered)"
GROUP_QA = "QA - snapping & original locations"
GROUP_INSIGHTS = "Insights & geoprocessing history (tables)"
GROUP_BASEMAP = "Basemap"

# -----------------------------------------------------------------------------
# Shapefile exports - one per filter / question in the data request
# -----------------------------------------------------------------------------
# Shapefiles cap field names at 10 characters and store dates without a time, so
# each export carries a curated field set under explicit short names (listed in
# shapefiles/field_crosswalk.csv). The GeoPackage keeps every source attribute.
SHP_DIR = "shapefiles"
SHP_CROSSWALK = "field_crosswalk.csv"

# (GeoPackage field, shapefile field) - fields absent from an older GeoPackage are skipped.
SHP_SUBBLOCK_FIELDS = (
    ("SUBBLOCK_UID", "SUBBLK_UID"), ("SUBBLOCKID", "SUBBLK_ID"), ("BLOCKID", "BLOCKID"),
    ("ROUTENAME", "ROUTENAME"), ("STREETNAME", "STREETNAME"), ("FROMSTREET", "FROMSTREET"),
    ("TOSTREET", "TOSTREET"), ("ROADTYPE", "ROADTYPE"), ("ROADWAY_TYPE", "ROAD_CLASS"),
    ("WARD_ID", "WARD_ID"), ("PCI_SCORE", "PCI_SCORE"), ("LENGTH", "LENGTH"),
    ("PERMIT_COUNT", "PRMT_CNT"), ("DISTINCT_PERMIT_COUNT", "PRMT_DIST"),
    ("MIN_PERMIT_EFF_DATE", "PRMT_EFFMN"), ("MAX_PERMIT_EXP_DATE", "PRMT_EXPMX"),
    ("EXCLUDED_ROADWAY_PERMIT_COUNT", "PRMT_EXCL"),
    ("SR_COUNT", "SR_CNT"), ("DISTINCT_SR_LOCATIONS", "SR_LOC_CNT"),
    ("MIN_SR_INIT_DATE", "SR_INITMN"), ("MAX_SR_INIT_DATE", "SR_INITMX"),
    ("FLAG_BOTH_PERMIT_AND_SR", "FLAG_BOTH"), ("ACTIVITY_CLASS", "ACTIVITY"),
)
SHP_PERMIT_FIELDS = (
    ("PermitNumber", "PERMIT_NO"), ("TrackingNumber", "TRACK_NO"), ("StatusDescription", "STATUS"),
    ("RenewalDescription", "RENEWAL"), ("PermitTypeDescription", "PRMT_TYPE"),
    ("IsExcavation", "IS_EXCAV"), ("IsPaving", "IS_PAVING"), ("IssueDate", "ISSUE_DATE"),
    ("EffectiveDate", "EFF_DATE"), ("ExpirationDate", "EXP_DATE"),
    ("WorkLocationFullAddress", "ADDRESS"), ("Ward", "WARD"),
    ("SUBBLOCK_UID", "SUBBLK_UID"), ("NEAR_DIST_FT", "NEAR_FT"), ("ORIG_X", "ORIG_X"),
    ("ORIG_Y", "ORIG_Y"), ("SNAPPED", "SNAPPED"), ("SOURCE_ROADWAY_TYPE", "SRC_RDTYPE"),
    ("ON_EXCLUDED_ROADWAY", "ON_EXCL_RD"),
)
SHP_SR_FIELDS = (
    ("REQUESTID", "REQUEST_ID"), ("CSRNUMBER", "CSR_NUMBER"), ("WORKORDERID", "WO_ID"),
    ("DESCRIPTION", "DESCRIPT"), ("STATUS", "STATUS"), ("PRIORITY", "PRIORITY"),
    ("INITIATEDDATE", "INIT_DATE"), ("INSPECTIONCOMPLETE", "INSP_DONE"), ("ADDRESS", "ADDRESS"),
    ("WARD", "WARD"), ("SUBBLOCK_UID", "SUBBLK_UID"), ("NEAR_DIST_FT", "NEAR_FT"),
)

# (shapefile stem, display name, source layer, filter, field map, PDF item it answers)
SHAPEFILE_EXPORTS = (
    ("permits_filtered_snapped", "SHP - Permits: renewal excavation/paving, issued, exp >= 2025-10-01 (snapped)",
     LAYER_PERMITS, None, SHP_PERMIT_FIELDS, "Construction permit filter, snapped to the roadway"),
    ("roadway_subblock_filtered", "SHP - Roadway subblocks: streets, service lanes, ramps (enriched)",
     LAYER_SUBBLOCKS, None, SHP_SUBBLOCK_FIELDS, "Roadway subblock filter, enriched"),
    ("service_requests_filtered", "SHP - Service requests: open roadway/pothole/paving, init >= 2025-10-01",
     LAYER_SERVICE_REQUESTS, None, SHP_SR_FIELDS, "Cityworks service request filter"),
    ("subblocks_with_permits", "SHP - Subblocks with permits (count, latest expiration)",
     LAYER_SUBBLOCKS, '"PERMIT_COUNT" > 0', SHP_SUBBLOCK_FIELDS,
     "Blocks with a count of permits / latest permit expiration date"),
    ("subblocks_with_open_srs", "SHP - Subblocks with open service requests (count, latest initiation)",
     LAYER_SUBBLOCKS, '"SR_COUNT" > 0', SHP_SUBBLOCK_FIELDS,
     "Blocks with a count of open SRs / latest SR creation date"),
    ("subblocks_with_permits_and_srs", "SHP - Subblocks with BOTH permits and open SRs",
     LAYER_SUBBLOCKS, '"FLAG_BOTH_PERMIT_AND_SR" = 1', SHP_SUBBLOCK_FIELDS,
     "Blocks with these permits and open service requests"),
)

# (category value, label, colour, width mm, render pass) - conflicts drawn on top.
SUBBLOCK_CLASSES = [
    ("No activity", "No activity", "#c8c8c8", 0.26, 0),
    ("Permit only", "Permit only", "#1b9e77", 0.6, 1),
    ("SR only", "Open SR only", "#3b75af", 0.6, 2),
    ("Permit + SR", "Permit + open SR (conflict)", "#d7191c", 1.2, 3),
]

ESRI_LIGHT_GRAY_URI = (
    "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/"
    "MapServer/tile/%7Bz%7D/%7By%7D/%7Bx%7D&zmin=0&zmax=16"
)
OSM_URI = "type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmin=0&zmax=19"

# Files never shipped in the deliverable archive (incl. source-repo tooling when
# the project folder is the repository root).
EXCLUDE_PATTERNS = (
    re.compile(r"^(\.git|\.venv|\.idea|\.pytest_cache|build|tests)(/|$)"),
    re.compile(r"^(pytest\.ini|requirements[^/]*\.txt|\.gitignore|\.gitattributes)$"),
    re.compile(r"^(?!01_)[^/]+\.py$"),  # working scripts (this one, the runner); only 01_ ships
    re.compile(r"(^|/)__pycache__(/|$)"),
    re.compile(r"\.pyc$"),
    re.compile(r"(^|/)\.[^/]*\.tmp\.gpkg$"),
    re.compile(r"^\.shp-[^/]*(/|$)"),  # interrupted shapefile export
    re.compile(r"-(wal|shm|journal)$"),
    re.compile(r"\.(qgz|qgs)~$"),
    re.compile(r"(^|/)\.DS_Store$"),
)

NAME_PART = re.compile(r"^[A-Za-z][A-Za-z'\-]*$")
VERSION_LABEL = re.compile(r"^[Vv][1-9][0-9]*$")


# -----------------------------------------------------------------------------
# Packaging (stdlib only - importable without PyQGIS)
# -----------------------------------------------------------------------------
def package_name(first: str, middle_initial: str, last: str, version: str | None = None) -> str:
    """Return '<First>_<MI>_<Last>_GIS' (plus '_V<n>' when ``version`` is given), validating each part."""
    parts = {"first name": first, "middle initial": middle_initial, "last name": last}
    for label, value in parts.items():
        if not value or not NAME_PART.match(value):
            raise ValueError(f"Invalid {label} {value!r}: letters, hyphen or apostrophe only")
    if len(middle_initial) != 1:
        raise ValueError(f"Middle initial must be a single letter, got {middle_initial!r}")
    if version is not None and not VERSION_LABEL.match(version):
        raise ValueError(f"Version label must look like V2, got {version!r}")

    def clean(s: str) -> str:  # drop apostrophes (awkward in file names), capitalise
        s = s.replace("'", "")
        return s[:1].upper() + s[1:]

    name = f"{clean(first)}_{middle_initial.upper()}_{clean(last)}_GIS"
    return f"{name}_{version.upper()}" if version else name


def _excluded(rel_posix: str) -> bool:
    return any(p.search(rel_posix) for p in EXCLUDE_PATTERNS)


def package_project(project_dir: Path, zip_path: Path, root_name: str) -> list[str]:
    """Zip ``project_dir`` into ``zip_path`` under ``root_name/``; returns archive names.

    The archive is written to a temp file and moved into place so a failed run
    never leaves a truncated deliverable behind.
    """
    project_dir = project_dir.resolve()
    zip_path = zip_path.resolve()
    if zip_path.is_relative_to(project_dir):
        raise ValueError("The zip must be written outside the project folder")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in project_dir.rglob("*")
        if p.is_file() and not _excluded(p.relative_to(project_dir).as_posix())
    )
    names: list[str] = []
    fd, tmp_name = tempfile.mkstemp(prefix=".pkg-", suffix=".zip", dir=zip_path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for f in files:
                arc = f"{root_name}/{f.relative_to(project_dir).as_posix()}"
                zf.write(f, arcname=arc)
                names.append(arc)
        with zipfile.ZipFile(tmp) as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"Archive verification failed at {bad}")
        os.chmod(tmp, 0o644)
        os.replace(tmp, zip_path)
    finally:
        tmp.unlink(missing_ok=True)
    return names


# -----------------------------------------------------------------------------
# QGIS helpers
# -----------------------------------------------------------------------------
def _start_qgis():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from qgis.core import QgsApplication
    except ImportError as exc:
        raise SystemExit(
            "PyQGIS is not importable from this interpreter "
            f"({sys.executable}). Run this script with QGIS's Python (see --help)."
        ) from exc
    app = QgsApplication([], False)
    app.initQgis()
    return app


def _read_latest_history(gpkg: Path) -> dict:
    from qgis.core import QgsVectorLayer

    lyr = QgsVectorLayer(f"{gpkg}|layername={TABLE_HISTORY}", TABLE_HISTORY, "ogr")
    if not lyr.isValid():
        return {}
    rows = [f.attributes() for f in lyr.getFeatures()]
    if not rows:
        return {}
    names = lyr.fields().names()
    latest = max((dict(zip(names, r)) for r in rows), key=lambda d: str(d.get("run_started_utc") or ""))
    return {k: (None if v is None or str(v) == "NULL" else v) for k, v in latest.items()}


def _has_field(gpkg: Path, layer: str, field: str) -> bool:
    """True when ``layer`` in ``gpkg`` has ``field`` (older GeoPackages predate some QA fields)."""
    from qgis.core import QgsVectorLayer

    lyr = QgsVectorLayer(f"{gpkg}|layername={layer}", layer, "ogr")
    return lyr.isValid() and lyr.fields().indexOf(field) >= 0


def _categorized_activity_renderer(width_scale: float = 1.0, field: str = "ACTIVITY_CLASS"):
    from qgis.core import QgsCategorizedSymbolRenderer, QgsLineSymbol, QgsRendererCategory

    cats = []
    for value, label, colour, width, render_pass in SUBBLOCK_CLASSES:
        sym = QgsLineSymbol.createSimple(
            {"line_color": colour, "line_width": str(round(width * width_scale, 2)), "capstyle": "round"}
        )
        sym.symbolLayer(0).setRenderingPass(render_pass)
        cats.append(QgsRendererCategory(value, sym, label))
    renderer = QgsCategorizedSymbolRenderer(field, cats)
    renderer.setUsingSymbolLevels(True)
    return renderer


def _conflict_renderer():
    """Thick red line over a yellow halo so conflicts read against any basemap."""
    from qgis.core import QgsLineSymbol, QgsSimpleLineSymbolLayer, QgsSingleSymbolRenderer
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QColor

    sym = QgsLineSymbol.createSimple({"line_color": "#ffd400", "line_width": "2.6", "capstyle": "round"})
    top = QgsSimpleLineSymbolLayer(QColor("#d7191c"), 1.3)
    top.setPenCapStyle(Qt.RoundCap)
    sym.appendSymbolLayer(top)
    return QgsSingleSymbolRenderer(sym)


def _line_renderer(colour: str, width: float, dash: bool = False):
    from qgis.core import QgsLineSymbol, QgsSingleSymbolRenderer

    props = {"line_color": colour, "line_width": str(width), "capstyle": "round"}
    if dash:
        props["line_style"] = "dash"
    return QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(props))


def _marker_renderer(shape: str, colour: str, size: float, hollow: bool = False, outline: str = "#ffffff"):
    from qgis.core import QgsMarkerSymbol, QgsSingleSymbolRenderer

    props = {"name": shape, "size": str(size)}
    if hollow:
        props.update({"color": "0,0,0,0", "outline_color": colour, "outline_width": "0.5"})
    else:
        props.update({"color": colour, "outline_color": outline, "outline_width": "0.3"})
    return QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(props))


def _local_layer(gpkg: Path, layer: str, display: str, subset: str | None = None):
    from qgis.core import QgsVectorLayer

    lyr = QgsVectorLayer(f"{gpkg}|layername={layer}", display, "ogr")
    if not lyr.isValid():
        raise RuntimeError(f"Layer {layer!r} could not be loaded from {gpkg}")
    if subset and not lyr.setSubsetString(subset):
        raise RuntimeError(f"Invalid filter on {layer!r}: {subset}")
    return lyr


def _set_display(lyr, field: str) -> None:
    if lyr.fields().indexOf(field) >= 0:
        lyr.setDisplayExpression(f'"{field}"')


# -----------------------------------------------------------------------------
# Shapefile export
# -----------------------------------------------------------------------------
def _text_widths(lyr, fields: Sequence[str]) -> dict[str, int]:
    """Longest value of each text field, so the .dbf is not padded to 254 characters per column."""
    from qgis.core import QgsFeatureRequest

    widths = dict.fromkeys(fields, 1)
    req = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry).setSubsetOfAttributes(list(fields), lyr.fields())
    for f in lyr.getFeatures(req):
        for name in fields:
            v = f[name]
            if v is not None and str(v) != "NULL":
                widths[name] = max(widths[name], len(str(v)))
    return widths


def _shp_converter(field_map, widths: dict[str, int]):
    """FieldValueConverter that renames to the 10-char shapefile names, sizes text fields
    to ``widths`` (capped at the 254-character DBF limit) and turns DateTime into Date."""
    from qgis.core import Qgis, QgsField, QgsVectorFileWriter
    from qgis.PyQt.QtCore import QDateTime, QMetaType, QVariant

    names = {src: dst for src, dst in field_map}
    date_type = QMetaType.QDate if Qgis.QGIS_VERSION_INT >= 33800 else QVariant.Date  # setType(QVariant) deprecated

    class _Converter(QgsVectorFileWriter.FieldValueConverter):
        def fieldDefinition(self, field):
            out = QgsField(field)
            out.setName(names[field.name()])
            if field.type() == QVariant.DateTime:
                out.setType(date_type)
                out.setTypeName("Date")
            elif field.type() == QVariant.String:
                out.setLength(min(widths[field.name()], 254))
            return out

        def convert(self, idx, value):
            if isinstance(value, QDateTime):
                return value.date() if value.isValid() else None
            return value

        def clone(self):
            return _Converter()

    return _Converter()


def export_shapefiles(project_dir: Path) -> list[Path]:
    """Write one shapefile per PDF filter / question to ``shapefiles/`` plus a field crosswalk.

    The folder is built in a temp directory and swapped in, so a failed export
    never leaves a half-written set behind.
    """
    import csv
    import shutil

    from qgis.core import QgsCoordinateTransformContext, QgsVectorFileWriter, QgsVectorLayer
    from qgis.PyQt.QtCore import QVariant

    gpkg = (project_dir / GPKG_REL).resolve()
    out_dir = project_dir / SHP_DIR
    tmp_dir = Path(tempfile.mkdtemp(prefix=".shp-", dir=project_dir))
    crosswalk = []
    try:
        for stem, _display, layer, subset, field_map, answers in SHAPEFILE_EXPORTS:
            lyr = _local_layer(gpkg, layer, stem, subset)
            fields = lyr.fields()
            present = [(src, dst) for src, dst in field_map if fields.indexOf(src) >= 0]
            skipped = [src for src, _ in field_map if fields.indexOf(src) < 0]
            if skipped:
                LOG.warning("%s: fields not in the GeoPackage, skipped: %s", stem, ", ".join(skipped))

            opts = QgsVectorFileWriter.SaveVectorOptions()
            opts.driverName = "ESRI Shapefile"
            opts.fileEncoding = "UTF-8"
            opts.attributes = [fields.indexOf(src) for src, _ in present]
            text = [src for src, _ in present if fields.field(src).type() == QVariant.String]
            widths = _text_widths(lyr, text)
            for src in (n for n in text if widths[n] > 254):
                LOG.warning("%s: %s values up to %d chars truncated to 254", stem, src, widths[src])
            converter = _shp_converter(present, widths)  # keep a reference: QGIS does not own it
            opts.fieldValueConverter = converter
            err, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                lyr, str(tmp_dir / f"{stem}.shp"), QgsCoordinateTransformContext(), opts
            )
            del lyr  # release the GeoPackage handle before the next export
            if err != QgsVectorFileWriter.NoError:
                raise RuntimeError(f"Shapefile export of {stem} failed: {msg}")
            written = QgsVectorLayer(str(tmp_dir / f"{stem}.shp"), stem, "ogr").featureCount()
            LOG.info("Exported %s.shp (%d features, filter: %s)", stem, written, subset or "none")
            crosswalk += [
                {"shapefile": f"{stem}.shp", "shp_field": dst, "gpkg_layer": layer, "gpkg_field": src,
                 "type": fields.field(src).typeName(), "filter": subset or "", "answers": answers}
                for src, dst in present
            ]

        with open(tmp_dir / SHP_CROSSWALK, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(crosswalk[0]))
            writer.writeheader()
            writer.writerows(crosswalk)

        os.chmod(tmp_dir, 0o755)  # mkdtemp creates 0700
        if out_dir.exists():
            shutil.rmtree(out_dir)
        os.replace(tmp_dir, out_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return [out_dir / f"{stem}.shp" for stem, *_ in SHAPEFILE_EXPORTS]


# -----------------------------------------------------------------------------
# QGIS project construction
# -----------------------------------------------------------------------------
def build_project(project_dir: Path, include_live: bool = True, include_basemap: bool = True,
                  include_shapefiles: bool = True) -> Path:
    from qgis.core import Qgis, QgsProject, QgsRasterLayer, QgsReferencedRectangle, QgsVectorLayer

    gpkg = (project_dir / GPKG_REL).resolve()
    if not gpkg.exists():
        raise FileNotFoundError(f"{gpkg} not found - run 01_pull_and_process_data.py first")
    qgz = project_dir / QGZ_NAME
    history = _read_latest_history(gpkg)

    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(qgz))
    project.setTitle(PROJECT_TITLE)
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    root = project.layerTreeRoot()

    def add(group, lyr, visible: bool = True):
        project.addMapLayer(lyr, False)
        node = group.addLayer(lyr)
        node.setItemVisibilityChecked(visible)
        node.setExpanded(False)
        return lyr

    # --- Analysis -------------------------------------------------------------
    analysis = root.addGroup(GROUP_ANALYSIS)
    conflicts = _local_layer(gpkg, LAYER_SUBBLOCKS, "Subblocks with BOTH permits and open SRs",
                             '"FLAG_BOTH_PERMIT_AND_SR" = 1')
    conflicts.setRenderer(_conflict_renderer())
    permits = _local_layer(gpkg, LAYER_PERMITS, "Permits - snapped to roadway subblock", '"SNAPPED" = 1')
    permits.setRenderer(_marker_renderer("circle", "#8e0152", 2.4))
    srs = _local_layer(gpkg, LAYER_SERVICE_REQUESTS, "Service requests - open roadway/pothole/paving")
    srs.setRenderer(_marker_renderer("triangle", "#542788", 2.8))
    subblocks = _local_layer(gpkg, LAYER_SUBBLOCKS, "Roadway subblock - enriched")
    subblocks.setRenderer(_categorized_activity_renderer())
    blocks = _local_layer(gpkg, LAYER_BLOCKS, "Roadway block (BLOCKID) - enriched")
    blocks.setRenderer(_categorized_activity_renderer(width_scale=1.6))
    for lyr, visible in ((conflicts, True), (permits, True), (srs, True), (subblocks, True), (blocks, False)):
        add(analysis, lyr, visible)
    for lyr, field in ((conflicts, "SUBBLOCK_UID"), (subblocks, "SUBBLOCK_UID"), (blocks, "BLOCK_UID"),
                       (permits, "PermitNumber"), (srs, "REQUESTID")):
        _set_display(lyr, field)

    crs = subblocks.crs()
    project.setCrs(crs)
    project.setEllipsoid(crs.ellipsoidAcronym() or "EPSG:7019")

    # --- Shapefile exports (same data as Analysis, one file per filter) -------
    if include_shapefiles:
        shp_group = root.addGroup(GROUP_SHAPEFILES)
        shp_group.setExpanded(False)
        styles = {LAYER_PERMITS: lambda: _marker_renderer("circle", "#8e0152", 2.4),
                  LAYER_SERVICE_REQUESTS: lambda: _marker_renderer("triangle", "#542788", 2.8)}
        for stem, display, layer, *_ in SHAPEFILE_EXPORTS:
            shp = QgsVectorLayer(str(project_dir / SHP_DIR / f"{stem}.shp"), display, "ogr")
            if not shp.isValid():
                raise RuntimeError(f"Shapefile {stem}.shp could not be loaded - export it first")
            if layer in styles:
                shp.setRenderer(styles[layer]())
            elif stem == "subblocks_with_permits_and_srs":
                shp.setRenderer(_conflict_renderer())
            else:
                shp.setRenderer(_categorized_activity_renderer(field="ACTIVITY"))
            add(shp_group, shp, visible=False)

    # --- Live REST sources ---------------------------------------------------
    if include_live:
        source = root.addGroup(GROUP_SOURCE)
        source.setExpanded(True)
        feeds = [
            ("REST - Construction permits (DDOT TOPS)", "permit_url", "permit_where",
             _marker_renderer("square", "#1f78b4", 2.6, hollow=True)),
            ("REST - Cityworks service requests", "sr_url", "sr_where",
             _marker_renderer("triangle", "#e31a1c", 2.8, hollow=True)),
            ("REST - Roadway SubBlock", "subblock_url", "subblock_where",
             _line_renderer("#505050", 0.4, dash=True)),
        ]
        for name, url_key, where_key, renderer in feeds:
            url, where = history.get(url_key), history.get(where_key)
            if not url:
                LOG.warning("No source URL recorded in %s; skipping %s", TABLE_HISTORY, name)
                continue
            lyr = QgsVectorLayer(f"crs='EPSG:3857' url='{url}'", name, "arcgisfeatureserver")
            if not lyr.isValid():
                LOG.warning("Live feed %s is unavailable (%s); skipping", name, url)
                continue
            if where and not lyr.setSubsetString(where):
                LOG.warning("Server rejected filter for %s; skipping", name)
                continue
            lyr.setRenderer(renderer)
            add(source, lyr, visible=False)

    # --- QA ------------------------------------------------------------------
    qa = root.addGroup(GROUP_QA)
    qa.setExpanded(True)
    qa_snap = _local_layer(gpkg, LAYER_QA_PERMIT_SNAP, "QA - permit snap displacement (original -> snapped)")
    qa_snap.setRenderer(_line_renderer("#e7298a", 0.5))
    qa_sr = _local_layer(gpkg, LAYER_QA_SR_ASSIGN, "QA - SR to subblock assignment")
    qa_sr.setRenderer(_line_renderer("#ff7f00", 0.5, dash=True))
    unsnapped = _local_layer(gpkg, LAYER_PERMITS, "Permits - NOT snapped (> tolerance, original location)",
                             '"SNAPPED" = 0')
    unsnapped.setRenderer(_marker_renderer("diamond", "#ff7f00", 3.0))
    excluded_src = None
    if _has_field(gpkg, LAYER_PERMITS, "ON_EXCLUDED_ROADWAY"):
        excluded_src = _local_layer(gpkg, LAYER_PERMITS,
                                    "Permits - sited on alley/driveway, snapped onto a street",
                                    '"ON_EXCLUDED_ROADWAY" = 1 AND "SNAPPED" = 1')
        excluded_src.setRenderer(_marker_renderer("star", "#d95f02", 3.4, outline="#000000"))
        add(qa, excluded_src, visible=True)
        _set_display(excluded_src, "PermitNumber")
    orig = _local_layer(gpkg, LAYER_PERMITS_ORIGINAL, "Permits - original source location (unsnapped)")
    orig.setRenderer(_marker_renderer("cross2", "#404040", 2.4, outline="#404040"))
    for lyr in (unsnapped, qa_snap, qa_sr, orig):
        add(qa, lyr, visible=False)
    _set_display(unsnapped, "PermitNumber")
    _set_display(qa_snap, "PermitNumber")
    _set_display(qa_sr, "REQUESTID")
    _set_display(orig, "PermitNumber")

    # --- Tables --------------------------------------------------------------
    insights = root.addGroup(GROUP_INSIGHTS)
    insights.setExpanded(False)
    for table, display in ((TABLE_TOP_CONFLICTS, "Insight - ranked dual-conflict subblocks"),
                           (TABLE_WARD_SUMMARY, "Insight - activity by ward"),
                           (TABLE_ACTIVITY_SUMMARY, "Insight - activity class by roadway type"),
                           (TABLE_HISTORY, "Geoprocessing history (one row per run)")):
        tbl = _local_layer(gpkg, table, display)
        project.addMapLayer(tbl, False)
        insights.addLayer(tbl)

    # --- Basemaps ------------------------------------------------------------
    if include_basemap:
        basemap = root.addGroup(GROUP_BASEMAP)
        basemap.setExpanded(True)
        for name, uri, visible in (("Esri World Light Gray", ESRI_LIGHT_GRAY_URI, True),
                                   ("OpenStreetMap", OSM_URI, False)):
            lyr = QgsRasterLayer(uri, name, "wms")
            if lyr.isValid():
                add(basemap, lyr, visible)
            else:
                LOG.warning("Basemap %s could not be created; continuing without it", name)

    extent = subblocks.extent()
    if not extent.isEmpty():
        extent.scale(1.05)
        project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, crs))

    md = project.metadata()
    md.setTitle(PROJECT_TITLE)
    md.setAbstract(
        "Overlap of excavation/paving renewal permits and open roadway service requests on DC roadway "
        f"subblocks and blocks. Data run {history.get('run_id', 'n/a')} at "
        f"{history.get('run_finished_utc', 'n/a')} UTC (pipeline v{history.get('script_version', 'n/a')})."
    )
    project.setMetadata(md)

    if not project.write(str(qgz)):
        raise RuntimeError(f"QGIS failed to write {qgz}: {project.error()}")
    LOG.info("Wrote %s", qgz.name)
    return qgz


def validate_project(qgz: Path) -> None:
    """Reload the saved project and check that every local layer resolves via a relative path."""
    from qgis.core import QgsProject

    proj = QgsProject()
    if not proj.read(str(qgz)):
        raise RuntimeError(f"Saved project {qgz} cannot be re-opened: {proj.error()}")
    found = set()
    for lyr in proj.mapLayers().values():
        src = lyr.source()
        if lyr.providerType() == "ogr":
            if not lyr.isValid():
                raise RuntimeError(f"Layer {lyr.name()!r} is invalid after reload ({src})")
            found.update(n for n in REQUIRED_LAYERS if src.split("|layername=")[-1].split("|")[0] == n)
            if src.split("|")[0].endswith(".shp"):
                found.add(Path(src.split("|")[0]).name)
    groups = {g.name() for g in proj.layerTreeRoot().children()}
    required = set(REQUIRED_LAYERS)
    if GROUP_SHAPEFILES in groups:
        required |= {f"{stem}.shp" for stem, *_ in SHAPEFILE_EXPORTS}
    missing = required - found
    if missing:
        raise RuntimeError(f"Saved project is missing layers: {sorted(missing)}")
    if GROUP_ANALYSIS not in groups:
        raise RuntimeError(f"Saved project is missing the {GROUP_ANALYSIS!r} group")

    with zipfile.ZipFile(qgz) as zf:
        qgs = next(n for n in zf.namelist() if n.endswith(".qgs"))
        xml = zf.read(qgs).decode("utf-8")
    if str(qgz.parent.resolve()) in xml:
        raise RuntimeError("Project stores absolute paths; it would break once unzipped elsewhere")
    LOG.info("Validated %s (%d layers in %d groups, relative paths)", qgz.name, len(proj.mapLayers()), len(groups))
    proj.clear()


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build ddot_maintenance_operations.qgz and package the deliverable zip.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with QGIS's Python - see the module docstring for interpreter locations.",
    )
    ap.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parent,
                    help="project folder containing data/ (default: this script's folder)")
    ap.add_argument("--first-name")
    ap.add_argument("--middle-initial")
    ap.add_argument("--last-name")
    ap.add_argument("--version-label", help="deliverable version suffix, e.g. V2 -> <First>_<MI>_<Last>_GIS_V2.zip")
    ap.add_argument("--zip-dir", type=Path, help="where to write the zip (default: parent of --project-dir)")
    ap.add_argument("--no-package", action="store_true", help="build the project only, do not zip")
    ap.add_argument("--no-live-layers", action="store_true", help="omit live REST feeds")
    ap.add_argument("--no-basemap", action="store_true", help="omit the basemaps")
    ap.add_argument("--no-shapefiles", action="store_true",
                    help="skip the per-filter shapefile export (and its project group)")
    ap.add_argument("--log-file", type=Path, help="also write this script's log to a file")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    names = (args.first_name, args.middle_initial, args.last_name)
    if not args.no_package and not all(names):
        ap.error("--first-name, --middle-initial and --last-name are required unless --no-package is given")
    return args


def _configure_logging(log_file: Path | None) -> None:
    """Console logging, plus ``log_file`` if given. This working script does not write to the
    deliverable's logs/geoprocessing_history.log, which records the data pipeline only."""
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_dir = args.project_dir.resolve()
    _configure_logging(args.log_file)
    try:
        root_name = None
        if not args.no_package:
            root_name = package_name(args.first_name, args.middle_initial, args.last_name, args.version_label)
    except ValueError as exc:
        LOG.error("%s", exc)
        return 2

    app = _start_qgis()
    try:
        from qgis.core import Qgis

        LOG.info("QGIS %s - building project v%s in %s/", Qgis.version(), __version__, project_dir.name)
        if not args.no_shapefiles:
            export_shapefiles(project_dir)
        qgz = build_project(project_dir, include_live=not args.no_live_layers, include_basemap=not args.no_basemap,
                            include_shapefiles=not args.no_shapefiles)
        validate_project(qgz)
    except Exception as exc:
        LOG.exception("Project build failed: %s", exc)
        return 1
    finally:
        from qgis.core import QgsProject

        QgsProject.instance().clear()
        app.exitQgis()

    if root_name:
        zip_dir = (args.zip_dir or project_dir.parent).resolve()
        zip_path = zip_dir / f"{root_name}.zip"
        try:
            names = package_project(project_dir, zip_path, root_name)
        except Exception as exc:
            LOG.exception("Packaging failed: %s", exc)
            return 1
        LOG.info("Packaged %d files -> %s", len(names), zip_path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
