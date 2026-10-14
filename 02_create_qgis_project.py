#!/usr/bin/env python3
"""
02_create_qgis_project.py - DDOT Maintenance Operations GIS Analysis

Builds the QGIS project `ddot_maintenance_operations.qgz` from the GeoPackage
produced by 01_pull_and_process_data.py, validates the saved project by
reloading it, and packages the project folder as
<First>_<MI>_<Last>_GIS[_V<n>].zip.

Layer tree (V2):
    Analysis (local GeoPackage)
        Subblocks with BOTH permits and open SRs
        Permits - snapped to roadway subblock
        Service requests - open roadway/pothole/paving
        Roadway subblock - enriched
        Roadway block (BLOCKID) - enriched                    (off)
    Source - live DC GIS REST services (filtered)             (layers off)
    QA - snapping & original locations                         (layers off)
    Insights & geoprocessing history (tables)
    Basemap: Esri World Light Gray (on), OpenStreetMap (off)

Must run with a Python interpreter that can import PyQGIS (QGIS >= 3.28):
    Linux   : python3 (system QGIS install)
    Windows : "C:\\Program Files\\QGIS 3.40.x\\bin\\python-qgis-ltr.bat"
    macOS   : /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3

Usage:
    python 02_create_qgis_project.py --first-name Jane --middle-initial Q --last-name Public --version-label V2
    python 02_create_qgis_project.py --no-package          # project only
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

__version__ = "2.0.0"

LOG = logging.getLogger("ddot_gis.project")

PROJECT_TITLE = "DDOT Maintenance Operations - Permits, Service Requests & Subblocks"
QGZ_NAME = "ddot_maintenance_operations.qgz"
GPKG_REL = Path("data") / "ddot_maintenance_operations.gpkg"
LOG_REL = Path("logs") / "geoprocessing_history.log"

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
GROUP_SOURCE = "Source - live DC GIS REST services (filtered)"
GROUP_QA = "QA - snapping & original locations"
GROUP_INSIGHTS = "Insights & geoprocessing history (tables)"
GROUP_BASEMAP = "Basemap"

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
    re.compile(r"^(generate_and_launch_gis\.py|pytest\.ini|requirements[^/]*\.txt|\.gitignore|\.gitattributes)$"),
    re.compile(r"(^|/)__pycache__(/|$)"),
    re.compile(r"\.pyc$"),
    re.compile(r"(^|/)\.[^/]*\.tmp\.gpkg$"),
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


def _categorized_activity_renderer(width_scale: float = 1.0):
    from qgis.core import QgsCategorizedSymbolRenderer, QgsLineSymbol, QgsRendererCategory

    cats = []
    for value, label, colour, width, render_pass in SUBBLOCK_CLASSES:
        sym = QgsLineSymbol.createSimple(
            {"line_color": colour, "line_width": str(round(width * width_scale, 2)), "capstyle": "round"}
        )
        sym.symbolLayer(0).setRenderingPass(render_pass)
        cats.append(QgsRendererCategory(value, sym, label))
    renderer = QgsCategorizedSymbolRenderer("ACTIVITY_CLASS", cats)
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
# QGIS project construction
# -----------------------------------------------------------------------------
def build_project(project_dir: Path, include_live: bool = True, include_basemap: bool = True) -> Path:
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
    permits = _local_layer(gpkg, LAYER_PERMITS, "Permits - snapped to roadway subblock")
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
                       (permits, "PermitNumber"), (srs, "CSRNUMBER")):
        _set_display(lyr, field)

    crs = subblocks.crs()
    project.setCrs(crs)
    project.setEllipsoid(crs.ellipsoidAcronym() or "EPSG:7019")

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
    orig = _local_layer(gpkg, LAYER_PERMITS_ORIGINAL, "Permits - original source location (unsnapped)")
    orig.setRenderer(_marker_renderer("cross2", "#404040", 2.4, outline="#404040"))
    for lyr in (qa_snap, qa_sr, orig):
        add(qa, lyr, visible=False)
    _set_display(qa_snap, "PermitNumber")
    _set_display(qa_sr, "CSRNUMBER")
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
    missing = REQUIRED_LAYERS - found
    if missing:
        raise RuntimeError(f"Saved project is missing layers: {sorted(missing)}")
    groups = {g.name() for g in proj.layerTreeRoot().children()}
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
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    names = (args.first_name, args.middle_initial, args.last_name)
    if not args.no_package and not all(names):
        ap.error("--first-name, --middle-initial and --last-name are required unless --no-package is given")
    return args


def _configure_logging(project_dir: Path) -> None:
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    log_path = project_dir / LOG_REL
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_dir = args.project_dir.resolve()
    _configure_logging(project_dir)
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
        qgz = build_project(project_dir, include_live=not args.no_live_layers, include_basemap=not args.no_basemap)
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
