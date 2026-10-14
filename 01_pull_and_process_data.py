#!/usr/bin/env python3
"""
01_pull_and_process_data.py - DDOT Maintenance Operations GIS Analysis

Pulls construction permits, roadway subblocks and Cityworks service requests
from the DC GIS REST services, snaps permits to subblock centerlines, enriches
each subblock with permit / service-request metrics, and writes:

    data/ddot_maintenance_operations.gpkg
        roadway_subblock_enriched     (MultiLineString) subblock metrics + conflict flag
        roadway_block_enriched        (MultiLineString) subblocks aggregated by BLOCKID
        permits_snapped               (Point)  permits moved onto centerlines
        service_requests_filtered     (Point)  open roadway SRs with subblock assignment
        permits_original              (Point)  permits at their source (unsnapped) location
        qa_permit_snap_displacement   (LineString) original -> snapped permit location
        qa_sr_subblock_assignment     (LineString) SR -> nearest point on assigned subblock
        insight_top_conflicts         (table)  ranked dual-conflict subblocks
        insight_ward_summary          (table)  activity by ward
        insight_activity_summary      (table)  activity class x roadway type
        geoprocessing_history         (table)  one row per run
    logs/geoprocessing_history.log
    Project_Summary_Report.md

Requirements: Python >= 3.10, geopandas >= 1.0, shapely >= 2.0, pyogrio,
pyproj, requests.

Usage:
    python 01_pull_and_process_data.py [--out-dir DIR] [--tolerance-ft 150] ...
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import requests
import shapely
from pyproj import CRS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__version__ = "2.0.0"

LOG = logging.getLogger("ddot_gis.process")

# -----------------------------------------------------------------------------
# Sources and output names
# -----------------------------------------------------------------------------
PERMITS_URL = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/DDOT_TOPS/MapServer/23"
SUBBLOCKS_URL = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/162"
CITYWORKS_URL = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/Cityworks/MapServer/1"

GPKG_NAME = "ddot_maintenance_operations.gpkg"
LAYER_SUBBLOCKS = "roadway_subblock_enriched"
LAYER_PERMITS = "permits_snapped"
LAYER_SERVICE_REQUESTS = "service_requests_filtered"
LAYER_BLOCKS = "roadway_block_enriched"
LAYER_PERMITS_ORIGINAL = "permits_original"
LAYER_QA_PERMIT_SNAP = "qa_permit_snap_displacement"
LAYER_QA_SR_ASSIGN = "qa_sr_subblock_assignment"
TABLE_TOP_CONFLICTS = "insight_top_conflicts"
TABLE_WARD_SUMMARY = "insight_ward_summary"
TABLE_ACTIVITY_SUMMARY = "insight_activity_summary"
TABLE_HISTORY = "geoprocessing_history"
LOG_NAME = "geoprocessing_history.log"
REPORT_NAME = "Project_Summary_Report.md"

# Source schema fields the pipeline depends on.
SUBBLOCK_KEY_FIELD = "SUBBLOCKKEY"
PERMIT_DATE_FIELD = "ExpirationDate"
SR_DATE_FIELD = "INITIATEDDATE"

# Derived fields.
UID = "SUBBLOCK_UID"
BLOCK_UID = "BLOCK_UID"
SUBBLOCK_IDX = "_SUBBLOCK_IDX"  # internal row pointer, never written
ACTIVITY_CLASSES = ("Permit + SR", "Permit only", "SR only", "No activity")
# ROADTYPE coded domain -> ROADWAY_TYPE label (only the analysed classes).
ROADWAY_TYPE_LABELS = {"1": "STREET", "2": "SERVICE LANE", "3": "RAMP"}

DEFAULT_CRS = "EPSG:2248"  # NAD83 / Maryland (ftUS)
DEFAULT_TOLERANCE_FT = 150.0
FOOT_M = 0.3048


# -----------------------------------------------------------------------------
# Filters / definition queries
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Filters:
    """Definition queries applied server-side to each REST layer.

    Field mapping against the live schemas (the request's nominal field names
    do not exist on these services):
      * Subblock type  -> ROADTYPE coded domain: 1 Street, 2 Service Road, 3 Ramp
      * Renewal permit -> Renewal = 2 ("Renewal"; 1 = "New")
      * Issued status  -> StatusDescription = 'Issued'
      * Excavation/paving work -> IsExcavation = 1 OR IsPaving = 1
    """

    road_types: tuple[str, ...] = ("1", "2", "3")
    permit_min_expiration: date = date(2025, 10, 1)
    permit_statuses: tuple[str, ...] = ("Issued",)
    permit_renewal_code: int = 2
    sr_min_initiated: date = date(2025, 10, 1)
    sr_excluded_statuses: tuple[str, ...] = ("CLOSED", "CANCEL", "COMPLETE")
    sr_descriptions: tuple[str, ...] = (
        "ROADWAY REPAIR",
        "POTHOLES",
        "STREET REPAVING",
        "STREET REPAIR",
        "STREET PAVING SCHEDU",
    )


def sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_list(values: Iterable[str]) -> str:
    items = [sql_literal(v) for v in values]
    if not items:
        raise ValueError("SQL IN-list must not be empty")
    return "(" + ", ".join(items) + ")"


def sql_timestamp(d: date) -> str:
    return f"timestamp '{d:%Y-%m-%d} 00:00:00'"


def subblock_where(f: Filters) -> str:
    return f"ROADTYPE IN {sql_list(f.road_types)}"


def permit_where(f: Filters) -> str:
    return (
        f"{PERMIT_DATE_FIELD} >= {sql_timestamp(f.permit_min_expiration)}"
        f" AND Renewal = {int(f.permit_renewal_code)}"
        f" AND StatusDescription IN {sql_list(f.permit_statuses)}"
        " AND (IsExcavation = 1 OR IsPaving = 1)"
    )


def service_request_where(f: Filters) -> str:
    return (
        f"STATUS NOT IN {sql_list(f.sr_excluded_statuses)}"
        f" AND DESCRIPTION IN {sql_list(f.sr_descriptions)}"
        f" AND {SR_DATE_FIELD} >= {sql_timestamp(f.sr_min_initiated)}"
    )


# -----------------------------------------------------------------------------
# ArcGIS REST client
# -----------------------------------------------------------------------------
class ArcGISError(RuntimeError):
    """The ArcGIS server returned an error payload or an unusable response."""


_ESRI_GEOMETRY_TO_OGR = {
    "esriGeometryPoint": "Point",
    "esriGeometryMultipoint": "MultiPoint",
    "esriGeometryPolyline": "MultiLineString",
    "esriGeometryPolygon": "MultiPolygon",
}


class ArcGISClient:
    """Minimal, resilient client for ArcGIS MapServer/FeatureServer layer queries.

    Features are fetched by object ID in chunks, which is deterministic and not
    subject to the server's maxRecordCount truncation that affects plain
    offset paging on some services.
    """

    def __init__(
        self,
        timeout: float = 60.0,
        retries: int = 5,
        backoff: float = 1.0,
        chunk_size: int = 1000,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.chunk_size = chunk_size
        if session is None:
            session = requests.Session()
            retry = Retry(
                total=retries,
                backoff_factor=backoff,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers["User-Agent"] = f"ddot-gis-pipeline/{__version__}"
        self.session = session

    def _post(self, url: str, data: dict) -> dict:
        try:
            resp = self.session.post(url, data=data, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise ArcGISError(f"Request to {url} failed: {exc}") from exc
        except ValueError as exc:
            raise ArcGISError(f"Non-JSON response from {url}") from exc
        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
            raise ArcGISError(f"{url}: {err.get('code')} {err.get('message')} {err.get('details') or ''}".strip())
        return payload

    def layer_info(self, url: str) -> dict:
        return self._post(url, {"f": "json"})

    def object_ids(self, url: str, where: str) -> list[int]:
        payload = self._post(f"{url}/query", {"where": where, "returnIdsOnly": "true", "f": "json"})
        return sorted(payload.get("objectIds") or [])

    def fetch(self, url: str, where: str, out_sr: int = 4326) -> tuple[gpd.GeoDataFrame, dict]:
        """Return all features matching ``where`` plus the layer metadata."""
        info = self.layer_info(url)
        ids = self.object_ids(url, where)
        chunk = max(1, min(self.chunk_size, int(info.get("maxRecordCount") or self.chunk_size)))
        LOG.info("  %s: %d matching features (%d request(s))", info.get("name", url), len(ids), -(-len(ids) // chunk))

        features: list[dict] = []
        for start in range(0, len(ids), chunk):
            batch = ids[start : start + chunk]
            payload = self._post(
                f"{url}/query",
                {
                    "objectIds": ",".join(map(str, batch)),
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": str(out_sr),
                    "f": "geojson",
                },
            )
            got = payload.get("features") or []
            if len(got) != len(batch):
                raise ArcGISError(
                    f"{url}: requested {len(batch)} object IDs, received {len(got)} features"
                )
            features.extend(got)

        fields = [f for f in info.get("fields", []) if f.get("type") != "esriFieldTypeGeometry"]
        columns = [f["name"] for f in fields]
        if features:
            gdf = gpd.GeoDataFrame.from_features(features, crs=f"EPSG:{out_sr}", columns=columns + ["geometry"])
        else:
            gdf = gpd.GeoDataFrame({c: pd.Series(dtype="object") for c in columns}, geometry=[], crs=f"EPSG:{out_sr}")

        for f in fields:
            if f.get("type") == "esriFieldTypeDate" and f["name"] in gdf.columns:
                gdf[f["name"]] = pd.to_datetime(pd.to_numeric(gdf[f["name"]], errors="coerce"), unit="ms", utc=True)
        gdf.attrs["geometry_type"] = _ESRI_GEOMETRY_TO_OGR.get(info.get("geometryType"), "Unknown")
        return gdf, info


# -----------------------------------------------------------------------------
# Geoprocessing (pure functions - no I/O)
# -----------------------------------------------------------------------------
def crs_units_per_foot(crs: CRS) -> float:
    """Number of CRS linear units in one foot; rejects geographic CRSs."""
    crs = CRS.from_user_input(crs)
    if not crs.is_projected:
        raise ValueError(f"{crs.to_string()} is not a projected CRS; distances would not be planar")
    metres_per_unit = crs.axis_info[0].unit_conversion_factor
    return FOOT_M / metres_per_unit


def drop_invalid_geometry(gdf: gpd.GeoDataFrame, label: str) -> tuple[gpd.GeoDataFrame, int]:
    bad = gdf.geometry.isna() | gdf.geometry.is_empty
    n = int(bad.sum())
    if n:
        LOG.warning("  %s: dropped %d feature(s) with null/empty geometry", label, n)
    return gdf.loc[~bad].copy(), n


def sanitize_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Make column names GeoPackage-friendly and unique (case-insensitively)."""
    gdf = gdf.rename(columns=lambda c: c if c == gdf.geometry.name else str(c).replace(".", "_"))
    lowered = [c.lower() for c in gdf.columns]
    dupes = {c for c in lowered if lowered.count(c) > 1}
    if dupes:
        raise ValueError(f"Column names collide case-insensitively: {sorted(dupes)}")
    return gdf


def prepare_subblocks(raw: gpd.GeoDataFrame, crs: str) -> gpd.GeoDataFrame:
    gdf, _ = drop_invalid_geometry(raw, "subblocks")
    gdf = sanitize_columns(gdf).to_crs(crs).reset_index(drop=True)
    if SUBBLOCK_KEY_FIELD in gdf.columns:
        key = gdf[SUBBLOCK_KEY_FIELD].astype("string")
    else:
        key = pd.Series(pd.NA, index=gdf.index, dtype="string")
    fallback = "OID-" + gdf["OBJECTID"].astype("string") if "OBJECTID" in gdf.columns else "ROW-" + gdf.index.astype(str)
    gdf[UID] = key.fillna(fallback).astype(str)
    if "ROADTYPE" in gdf.columns:
        code = gdf["ROADTYPE"].astype("string").str.strip()
        gdf["ROADWAY_TYPE"] = code.map(ROADWAY_TYPE_LABELS).fillna("OTHER (" + code.fillna("NULL") + ")")
    dupes = int(gdf[UID].duplicated().sum())
    if dupes:
        LOG.warning("  subblocks: %d duplicated %s value(s); metrics are attributed per feature", dupes, UID)
    return gdf


def match_to_subblocks(
    points: gpd.GeoDataFrame,
    subblocks: gpd.GeoDataFrame,
    tolerance: float,
    units_per_foot: float,
    snap: bool,
) -> gpd.GeoDataFrame:
    """Assign each point to its nearest subblock within ``tolerance`` (CRS units).

    Adds SUBBLOCK_UID, NEAR_DIST_FT and an internal row pointer. When ``snap``
    is true, matched points are moved onto the centerline via linear
    referencing (project + interpolate), the original coordinates are kept in
    ORIG_X / ORIG_Y and SNAPPED is set to 1.

    ``subblocks`` must have a RangeIndex (as returned by prepare_subblocks).
    """
    if points.crs != subblocks.crs:
        raise ValueError(f"CRS mismatch: points {points.crs} vs subblocks {subblocks.crs}")
    pts = points.reset_index(drop=True)
    out = pts.copy()

    if pts.empty or subblocks.empty:
        idx = pd.Series(pd.NA, index=pts.index, dtype="Int64")
        dist = pd.Series(np.nan, index=pts.index, dtype="float64")
    else:
        joined = gpd.sjoin_nearest(
            pts[[pts.geometry.name]],
            subblocks[[subblocks.geometry.name]],
            how="left",
            max_distance=tolerance,
            distance_col="_dist",
        )
        # Equidistant ties produce duplicate rows; keep the first deterministically.
        joined = joined[~joined.index.duplicated(keep="first")].reindex(pts.index)
        idx = joined["index_right"].astype("Int64")
        dist = joined["_dist"].astype("float64")

    matched = idx.notna().to_numpy()
    out[SUBBLOCK_IDX] = idx
    out[UID] = pd.Series(pd.NA, index=pts.index, dtype="string")
    if matched.any():
        rows = idx[matched].to_numpy(dtype="int64")
        out.loc[matched, UID] = subblocks[UID].to_numpy()[rows]
    out["NEAR_DIST_FT"] = (dist / units_per_foot).round(2)

    if snap:
        geoms = out.geometry.to_numpy()
        out["ORIG_X"] = shapely.get_x(geoms)
        out["ORIG_Y"] = shapely.get_y(geoms)
        if matched.any():
            lines = subblocks.geometry.to_numpy()[rows]
            pts_m = geoms[matched]
            snapped = shapely.line_interpolate_point(lines, shapely.line_locate_point(lines, pts_m))
            new_geoms = geoms.copy()
            new_geoms[matched] = snapped
            out = out.set_geometry(gpd.GeoSeries(new_geoms, index=out.index, crs=out.crs))
        out["SNAPPED"] = matched.astype("int32")
    return out


def enrich_subblocks(
    subblocks: gpd.GeoDataFrame,
    permits: gpd.GeoDataFrame,
    service_requests: gpd.GeoDataFrame,
    permit_date_field: str = PERMIT_DATE_FIELD,
    sr_date_field: str = SR_DATE_FIELD,
) -> gpd.GeoDataFrame:
    """Aggregate matched permits/SRs onto subblocks and derive the conflict flag."""

    def aggregate(df: pd.DataFrame, count_name: str, date_field: str, date_name: str) -> pd.DataFrame:
        m = df[df[SUBBLOCK_IDX].notna()]
        return m.groupby(m[SUBBLOCK_IDX].astype("int64")).agg(
            **{count_name: (SUBBLOCK_IDX, "size"), date_name: (date_field, "max")}
        )

    p = aggregate(permits, "PERMIT_COUNT", permit_date_field, "MAX_PERMIT_EXP_DATE")
    s = aggregate(service_requests, "SR_COUNT", sr_date_field, "MAX_SR_INIT_DATE")

    out = subblocks.join(p, how="left").join(s, how="left")
    out["PERMIT_COUNT"] = out["PERMIT_COUNT"].fillna(0).astype("int32")
    out["SR_COUNT"] = out["SR_COUNT"].fillna(0).astype("int32")
    has_p = out["PERMIT_COUNT"] > 0
    has_s = out["SR_COUNT"] > 0
    out["FLAG_BOTH_PERMIT_AND_SR"] = (has_p & has_s).astype("int32")
    out["ACTIVITY_CLASS"] = _activity_class(has_p, has_s)
    return out


def _activity_class(has_p: pd.Series, has_s: pd.Series) -> np.ndarray:
    return np.select([has_p & has_s, has_p, has_s], list(ACTIVITY_CLASSES[:3]), default=ACTIVITY_CLASSES[3])


def original_points(snapped: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Permits at their source location, from the ORIG_X/ORIG_Y kept by match_to_subblocks."""
    geom = gpd.points_from_xy(snapped["ORIG_X"], snapped["ORIG_Y"], crs=snapped.crs)
    return snapped.drop(columns=["ORIG_X", "ORIG_Y"]).set_geometry(geom)


def connector_lines(
    points: gpd.GeoDataFrame,
    subblocks: gpd.GeoDataFrame,
    keep: Sequence[str],
    units_per_foot: float,
    origin_xy: tuple[str, str] | None = None,
) -> gpd.GeoDataFrame:
    """QA lines from each matched point's source location to its nearest point on the assigned subblock.

    ``origin_xy`` names columns holding the source coordinates (used for permits,
    whose geometry has already been snapped). Unmatched points produce no line.
    """
    keep = [c for c in keep if c in points.columns]
    m = points[points[SUBBLOCK_IDX].notna()]
    if m.empty:
        return gpd.GeoDataFrame(
            {**{c: pd.Series(dtype=points[c].dtype) for c in keep}, "LENGTH_FT": pd.Series(dtype="float64")},
            geometry=gpd.GeoSeries([], crs=points.crs),
        )
    if origin_xy:
        start = shapely.points(m[origin_xy[0]].to_numpy(), m[origin_xy[1]].to_numpy())
    else:
        start = m.geometry.to_numpy()
    lines = subblocks.geometry.to_numpy()[m[SUBBLOCK_IDX].to_numpy(dtype="int64")]
    end = shapely.line_interpolate_point(lines, shapely.line_locate_point(lines, start))
    coords = np.stack([shapely.get_coordinates(start), shapely.get_coordinates(end)], axis=1)
    geoms = shapely.linestrings(coords)
    out = gpd.GeoDataFrame(m[keep].reset_index(drop=True), geometry=geoms, crs=points.crs)
    out["LENGTH_FT"] = (shapely.length(geoms) / units_per_foot).round(2)
    return out


def _mode(s: pd.Series):
    s = s.dropna()
    return s.mode().iat[0] if len(s) else None


def aggregate_blocks(enriched: gpd.GeoDataFrame, units_per_foot: float) -> gpd.GeoDataFrame:
    """Roll enriched subblocks up to roadway blocks (BLOCKID).

    Subblocks without a BLOCKID become single-subblock blocks keyed
    ``SB:<SUBBLOCK_UID>`` so no permit or SR is lost from the block view.
    Block-level FLAG_BOTH_PERMIT_AND_SR means the block has permits and SRs,
    possibly on different subblocks; SUBBLOCKS_WITH_BOTH counts subblock-level
    conflicts.
    """
    df = enriched.copy()
    block_id = df["BLOCKID"].astype("string") if "BLOCKID" in df.columns else pd.Series(pd.NA, index=df.index, dtype="string")
    df[BLOCK_UID] = block_id.fillna("SB:" + df[UID].astype(str))

    first_cols = [c for c in ("BLOCKID", "BLOCKKEY", "ROUTENAME", "STREETNAME", "ROADWAY_TYPE") if c in df.columns]
    g = df.groupby(BLOCK_UID, sort=True)
    attrs = g.agg(
        **{c: (c, "first") for c in first_cols},
        SUBBLOCK_COUNT=(UID, "size"),
        PERMIT_COUNT=("PERMIT_COUNT", "sum"),
        MAX_PERMIT_EXP_DATE=("MAX_PERMIT_EXP_DATE", "max"),
        SR_COUNT=("SR_COUNT", "sum"),
        MAX_SR_INIT_DATE=("MAX_SR_INIT_DATE", "max"),
        SUBBLOCKS_WITH_BOTH=("FLAG_BOTH_PERMIT_AND_SR", "sum"),
    )
    if "WARD_ID" in df.columns:
        attrs["WARD_ID"] = g["WARD_ID"].agg(_mode)
    geoms = df[[BLOCK_UID, df.geometry.name]].dissolve(by=BLOCK_UID).geometry
    out = gpd.GeoDataFrame(attrs, geometry=geoms.reindex(attrs.index).line_merge(), crs=enriched.crs).reset_index()

    for c in ("SUBBLOCK_COUNT", "PERMIT_COUNT", "SR_COUNT", "SUBBLOCKS_WITH_BOTH"):
        out[c] = out[c].astype("int32")
    has_p, has_s = out["PERMIT_COUNT"] > 0, out["SR_COUNT"] > 0
    out["FLAG_BOTH_PERMIT_AND_SR"] = (has_p & has_s).astype("int32")
    out["ACTIVITY_CLASS"] = _activity_class(has_p, has_s)
    out["LENGTH_FT"] = (out.geometry.length / units_per_foot).round(1)
    return out


def top_conflicts(enriched: gpd.GeoDataFrame) -> pd.DataFrame:
    """All dual-conflict subblocks ranked by permits + SRs (ties: SRs, then permits)."""
    cols = [c for c in (UID, "ROUTENAME", "ROADWAY_TYPE", "FROMSTREET", "TOSTREET", "WARD_ID", "BLOCKID")
            if c in enriched.columns]
    c = enriched.loc[enriched["FLAG_BOTH_PERMIT_AND_SR"] == 1,
                     [*cols, "PERMIT_COUNT", "SR_COUNT", "MAX_PERMIT_EXP_DATE", "MAX_SR_INIT_DATE"]].copy()
    c["ACTIVITY_SCORE"] = (c["PERMIT_COUNT"] + c["SR_COUNT"]).astype("int32")
    c = c.sort_values(["ACTIVITY_SCORE", "SR_COUNT", "PERMIT_COUNT", UID], ascending=[False, False, False, True])
    c.insert(0, "RANK", np.arange(1, len(c) + 1, dtype="int32"))
    return pd.DataFrame(c).reset_index(drop=True)


def ward_summary(enriched: gpd.GeoDataFrame) -> pd.DataFrame:
    if "WARD_ID" not in enriched.columns:
        return pd.DataFrame()
    df = enriched.assign(WARD=enriched["WARD_ID"].fillna("Unknown").astype(str))
    g = df.groupby("WARD", sort=True)
    return pd.DataFrame(
        {
            "SUBBLOCKS": g.size(),
            "SUBBLOCKS_WITH_PERMITS": g["PERMIT_COUNT"].apply(lambda s: int((s > 0).sum())),
            "SUBBLOCKS_WITH_SRS": g["SR_COUNT"].apply(lambda s: int((s > 0).sum())),
            "DUAL_CONFLICT_SUBBLOCKS": g["FLAG_BOTH_PERMIT_AND_SR"].sum(),
            "PERMITS": g["PERMIT_COUNT"].sum(),
            "OPEN_SRS": g["SR_COUNT"].sum(),
        }
    ).astype("int64").reset_index()


def activity_summary(enriched: gpd.GeoDataFrame, units_per_foot: float) -> pd.DataFrame:
    df = enriched.assign(_LEN_MI=enriched.geometry.length / units_per_foot / 5280.0)
    rt = "ROADWAY_TYPE" if "ROADWAY_TYPE" in df.columns else None
    keys = ["ACTIVITY_CLASS", rt] if rt else ["ACTIVITY_CLASS"]
    out = df.groupby(keys, sort=False).agg(SUBBLOCKS=(UID, "size"), CENTERLINE_MILES=("_LEN_MI", "sum")).reset_index()
    out["CENTERLINE_MILES"] = out["CENTERLINE_MILES"].round(2)
    order = {c: i for i, c in enumerate(ACTIVITY_CLASSES)}
    return out.sort_values(keys, key=lambda s: s.map(order) if s.name == "ACTIVITY_CLASS" else s).reset_index(drop=True)


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------
def _write_layer(gdf: gpd.GeoDataFrame, path: Path, layer: str, geometry_type: str | None) -> None:
    gdf = gdf.drop(columns=[c for c in gdf.columns if c.startswith("_")])
    kwargs = {}
    if gdf.empty and geometry_type:
        kwargs["geometry_type"] = geometry_type
    elif geometry_type in {"MultiLineString", "MultiPolygon", "MultiPoint"}:
        kwargs["promote_to_multi"] = True
    gdf.to_file(path, layer=layer, driver="GPKG", engine="pyogrio", **kwargs)


def write_geopackage(
    path: Path,
    layers: dict[str, tuple[gpd.GeoDataFrame, str | None]],
    history_row: dict,
    tables: dict[str, pd.DataFrame] | None = None,
) -> None:
    """Atomically (re)write the GeoPackage, carrying forward the run history.

    ``layers`` maps layer name -> (GeoDataFrame, OGR geometry type);
    ``tables`` maps name -> non-spatial DataFrame (snapshot of the current run).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.tmp{path.suffix}")
    for stale in (tmp, Path(f"{tmp}-wal"), Path(f"{tmp}-shm")):
        stale.unlink(missing_ok=True)

    history = pd.DataFrame([history_row])
    if path.exists():
        try:
            existing = {name for name, _ in pyogrio.list_layers(path)}
            if TABLE_HISTORY in existing:
                prior = pyogrio.read_dataframe(path, layer=TABLE_HISTORY, read_geometry=False)
                history = pd.concat([prior, history], ignore_index=True)
        except Exception as exc:  # corrupt/locked prior file must not block a fresh build
            LOG.warning("Could not carry forward prior run history from %s: %s", path, exc)

    try:
        for name, (gdf, geometry_type) in layers.items():
            _write_layer(gdf, tmp, name, geometry_type)
        for name, df in (tables or {}).items():
            pyogrio.write_dataframe(pd.DataFrame(df), tmp, layer=name, driver="GPKG")
        pyogrio.write_dataframe(history, tmp, layer=TABLE_HISTORY, driver="GPKG")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _fmt(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "-"
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("America/New_York").strftime("%Y-%m-%d") if value.tzinfo else value.strftime("%Y-%m-%d")
    return str(value).replace("|", "\\|")


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_None._"
    header = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([header, sep, *rows])


def build_summary_report(
    enriched: gpd.GeoDataFrame,
    history: dict,
    insights: dict[str, pd.DataFrame] | None = None,
    top_n: int = 25,
) -> str:
    """Markdown executive report; ``insights`` holds the insight_* tables (computed if omitted)."""
    insights = insights or {}
    ranked = insights.get(TABLE_TOP_CONFLICTS)
    if ranked is None:
        ranked = top_conflicts(enriched)
    ward = insights.get(TABLE_WARD_SUMMARY)
    if ward is None:
        ward = ward_summary(enriched)
    activity = insights.get(TABLE_ACTIVITY_SUMMARY)

    top_table = ranked.drop(columns=[c for c in ("BLOCKID", "ACTIVITY_SCORE") if c in ranked.columns]).head(top_n)
    by_ward = markdown_table(ward) if not ward.empty else "_Ward attribute not available._"
    class_counts = enriched["ACTIVITY_CLASS"].value_counts().reindex(ACTIVITY_CLASSES, fill_value=0)
    h = history
    pct = lambda n, d: f"{(100.0 * n / d):.1f}%" if d else "n/a"  # noqa: E731
    g = lambda k, default=0: h.get(k, default)  # noqa: E731 - tolerate partial history in tests

    block_rows = ""
    if "blocks_written" in h:
        block_rows = (
            f"| Roadway blocks (BLOCKID) analysed | {h['blocks_written']:,} |\n"
            f"| Blocks with both permits and open SRs (any subblock) | {h['dual_conflict_blocks']:,} |\n"
        )
    qa_rows = ""
    if "permit_snap_median_ft" in h:
        qa_rows = (
            f"* Permit snap displacement: median {h['permit_snap_median_ft']:.1f} ft, "
            f"95th percentile {h['permit_snap_p95_ft']:.1f} ft, max {h['permit_snap_max_ft']:.1f} ft "
            "(see `qa_permit_snap_displacement`).\n"
        )
    activity_section = ""
    if activity is not None and not activity.empty:
        activity_section = f"\n### Activity class by roadway type\n\n{markdown_table(activity)}\n"

    return f"""# Project Summary Report - DDOT Maintenance Operations GIS Analysis

_Generated {h['run_finished_utc']} (UTC) by `01_pull_and_process_data.py` v{h['script_version']}, run `{h['run_id']}`._

## Purpose

Identify roadway subblocks where **active excavation/paving renewal permits** coincide with
**open roadway repair, pothole and paving service requests**, so Maintenance Operations can
coordinate repairs with permitted work and avoid duplicate or wasted effort.

## Key Findings

| Metric | Value |
| --- | --- |
| Roadway subblocks analysed (Street / Service Road / Ramp) | {g('subblocks_written'):,} |
| Qualifying permits retrieved | {g('permits_fetched'):,} |
| Permits snapped to a centerline (<= {h['snap_tolerance_ft']:g} ft) | {g('permits_snapped'):,} ({pct(g('permits_snapped'), g('permits_valid'))}) |
| Open service requests retrieved | {g('srs_fetched'):,} |
| Service requests matched to a subblock (<= {h['snap_tolerance_ft']:g} ft) | {g('srs_matched'):,} ({pct(g('srs_matched'), g('srs_valid'))}) |
| Subblocks with at least one permit | {g('subblocks_with_permits'):,} |
| Subblocks with at least one open SR | {g('subblocks_with_srs'):,} |
| **Dual-conflict subblocks (permit AND open SR)** | **{g('dual_conflict_subblocks'):,}** |
{block_rows}
### Subblocks by activity class

{markdown_table(class_counts.rename_axis("Activity class").reset_index(name="Subblocks"))}
{activity_section}
### Activity by ward

{by_ward}

### Top {min(top_n, len(ranked))} dual-conflict subblocks (ranked by permits + SRs)

The full ranked list is in the `{TABLE_TOP_CONFLICTS}` table.

{markdown_table(top_table)}

## Recommendations

1. Review the dual-conflict subblocks above with permit holders before dispatching crews; where the
   permittee's restoration obligation covers the reported defect, route the SR to permit enforcement.
2. Hold planned repaving on subblocks with permits expiring after the planned work date.
3. Use the block view (`{LAYER_BLOCKS}`) to bundle nearby work on the same block into one dispatch.
4. Re-run the pipeline on a regular cadence (it is fully automated) to keep the overlap list current.

## Data Quality Notes

* Permits further than {h['snap_tolerance_ft']:g} ft from any qualifying subblock are kept in `permits_snapped`
  with `SNAPPED = 0` and no `SUBBLOCK_UID`: {g('permits_unmatched'):,} permit(s).
* Service requests further than {h['snap_tolerance_ft']:g} ft from a qualifying subblock (e.g. located on
  alleys or driveways) are not counted: {g('srs_unmatched'):,} request(s).
{qa_rows}* Subblocks without a BLOCKID are treated as single-subblock blocks: {g('subblocks_without_blockid'):,}.
* Features with null geometry dropped: permits {g('permits_null_geometry'):,}, service requests {g('srs_null_geometry'):,}.
* Dates are stored in UTC in the GeoPackage and shown here in America/New_York.

## Definition Queries Used

* **Subblocks:** `{h['subblock_where']}`
* **Permits:** `{h['permit_where']}`
* **Service requests:** `{h['sr_where']}`
"""


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------
@dataclass
class RunOptions:
    out_dir: Path
    target_crs: str = DEFAULT_CRS
    tolerance_ft: float = DEFAULT_TOLERANCE_FT
    filters: Filters = field(default_factory=Filters)
    timeout: float = 60.0
    retries: int = 5


def configure_logging(log_path: Path, verbose: bool = False) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(file_handler)
    for noisy in ("urllib3", "pyogrio", "fiona"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _require_fields(gdf: pd.DataFrame, fields: Sequence[str], label: str) -> None:
    missing = [f for f in fields if f not in gdf.columns]
    if missing:
        raise ArcGISError(f"{label}: source schema is missing required field(s) {missing}")


def run(opts: RunOptions, client: ArcGISClient | None = None) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    client = client or ArcGISClient(timeout=opts.timeout, retries=opts.retries)
    f = opts.filters
    crs = CRS.from_user_input(opts.target_crs)
    per_ft = crs_units_per_foot(crs)
    tolerance = opts.tolerance_ft * per_ft
    where = {"subblock": subblock_where(f), "permit": permit_where(f), "sr": service_request_where(f)}

    LOG.info("=" * 72)
    LOG.info("DDOT GIS pipeline v%s - run started", __version__)
    LOG.info("Target CRS %s (%s); snap tolerance %.1f ft", crs.to_string(), crs.name, opts.tolerance_ft)

    LOG.info("[1/5] Extracting from DC GIS REST services")
    sb_raw, _ = client.fetch(SUBBLOCKS_URL, where["subblock"])
    p_raw, p_info = client.fetch(PERMITS_URL, where["permit"])
    sr_raw, sr_info = client.fetch(CITYWORKS_URL, where["sr"])
    if sb_raw.empty:
        raise ArcGISError("Subblock query returned no features; cannot continue")
    _require_fields(p_raw, [PERMIT_DATE_FIELD], "permits")
    _require_fields(sr_raw, [SR_DATE_FIELD], "service requests")

    LOG.info("[2/5] Cleaning and reprojecting to %s", crs.to_string())
    subblocks = prepare_subblocks(sb_raw, crs)
    permits, p_null = drop_invalid_geometry(p_raw, "permits")
    srs, sr_null = drop_invalid_geometry(sr_raw, "service requests")
    permits = sanitize_columns(permits).to_crs(crs)
    srs = sanitize_columns(srs).to_crs(crs)

    LOG.info("[3/5] Snapping %d permits to subblock centerlines", len(permits))
    permits = match_to_subblocks(permits, subblocks, tolerance, per_ft, snap=True)
    srs = match_to_subblocks(srs, subblocks, tolerance, per_ft, snap=False)
    n_snapped = int(permits["SNAPPED"].sum()) if len(permits) else 0
    n_sr_matched = int(srs[UID].notna().sum()) if len(srs) else 0
    LOG.info("  permits snapped: %d / %d; service requests matched: %d / %d", n_snapped, len(permits), n_sr_matched, len(srs))

    LOG.info("[4/5] Enriching subblocks, aggregating blocks, building QA layers and insights")
    enriched = enrich_subblocks(subblocks, permits, srs)
    n_conflict = int(enriched["FLAG_BOTH_PERMIT_AND_SR"].sum())
    blocks = aggregate_blocks(enriched, per_ft)
    n_block_conflict = int(blocks["FLAG_BOTH_PERMIT_AND_SR"].sum())
    permits_orig = original_points(permits)
    qa_permit = connector_lines(permits, subblocks, ["PermitNumber", UID, "NEAR_DIST_FT"], per_ft, ("ORIG_X", "ORIG_Y"))
    qa_sr = connector_lines(srs, subblocks, ["CSRNUMBER", "DESCRIPTION", UID, "NEAR_DIST_FT"], per_ft)
    insights = {
        TABLE_TOP_CONFLICTS: top_conflicts(enriched),
        TABLE_WARD_SUMMARY: ward_summary(enriched),
        TABLE_ACTIVITY_SUMMARY: activity_summary(enriched, per_ft),
    }
    snap_d = qa_permit["LENGTH_FT"]
    LOG.info("  dual-conflict subblocks: %d; blocks: %d (dual-conflict %d)", n_conflict, len(blocks), n_block_conflict)

    finished = datetime.now(timezone.utc)
    history = {
        "run_id": str(uuid.uuid4()),
        "run_started_utc": started.isoformat(timespec="seconds"),
        "run_finished_utc": finished.isoformat(timespec="seconds"),
        "duration_s": round(time.monotonic() - t0, 1),
        "script_version": __version__,
        "target_crs": crs.to_string(),
        "snap_tolerance_ft": float(opts.tolerance_ft),
        "subblocks_fetched": len(sb_raw),
        "subblocks_written": len(enriched),
        "permits_fetched": len(p_raw),
        "permits_null_geometry": p_null,
        "permits_valid": len(permits),
        "permits_snapped": n_snapped,
        "permits_unmatched": len(permits) - n_snapped,
        "srs_fetched": len(sr_raw),
        "srs_null_geometry": sr_null,
        "srs_valid": len(srs),
        "srs_matched": n_sr_matched,
        "srs_unmatched": len(srs) - n_sr_matched,
        "subblocks_with_permits": int((enriched["PERMIT_COUNT"] > 0).sum()),
        "subblocks_with_srs": int((enriched["SR_COUNT"] > 0).sum()),
        "dual_conflict_subblocks": n_conflict,
        "subblocks_without_blockid": int(enriched["BLOCKID"].isna().sum()) if "BLOCKID" in enriched.columns else len(enriched),
        "blocks_written": len(blocks),
        "dual_conflict_blocks": n_block_conflict,
        "permit_snap_median_ft": float(snap_d.median()) if len(snap_d) else 0.0,
        "permit_snap_p95_ft": float(snap_d.quantile(0.95)) if len(snap_d) else 0.0,
        "permit_snap_max_ft": float(snap_d.max()) if len(snap_d) else 0.0,
        "subblock_url": SUBBLOCKS_URL,
        "permit_url": PERMITS_URL,
        "sr_url": CITYWORKS_URL,
        "subblock_where": where["subblock"],
        "permit_where": where["permit"],
        "sr_where": where["sr"],
    }

    gpkg = opts.out_dir / "data" / GPKG_NAME
    LOG.info("[5/5] Writing %s", gpkg.relative_to(opts.out_dir).as_posix())
    write_geopackage(
        gpkg,
        {
            LAYER_SUBBLOCKS: (enriched, "MultiLineString"),
            LAYER_PERMITS: (permits, _ESRI_GEOMETRY_TO_OGR.get(p_info.get("geometryType"), "Point")),
            LAYER_SERVICE_REQUESTS: (srs, _ESRI_GEOMETRY_TO_OGR.get(sr_info.get("geometryType"), "Point")),
            LAYER_BLOCKS: (blocks, "MultiLineString"),
            LAYER_PERMITS_ORIGINAL: (permits_orig, "Point"),
            LAYER_QA_PERMIT_SNAP: (qa_permit, "LineString"),
            LAYER_QA_SR_ASSIGN: (qa_sr, "LineString"),
        },
        history,
        tables=insights,
    )
    report = opts.out_dir / REPORT_NAME
    report.write_text(build_summary_report(enriched, history, insights), encoding="utf-8")
    LOG.info("Wrote %s", report.name)
    LOG.info("Run %s complete in %.1f s", history["run_id"], history["duration_s"])
    return history


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {s!r}") from exc


def _positive(s: str) -> float:
    v = float(s)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return v


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    d = Filters()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip(), formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent,
                    help="project folder to write data/, logs/ and the report into (default: this script's folder)")
    ap.add_argument("--crs", default=DEFAULT_CRS, help=f"projected working CRS (default {DEFAULT_CRS})")
    ap.add_argument("--tolerance-ft", type=_positive, default=DEFAULT_TOLERANCE_FT,
                    help=f"snap / match tolerance in feet (default {DEFAULT_TOLERANCE_FT:g})")
    ap.add_argument("--permit-min-expiration", type=_parse_date, default=d.permit_min_expiration,
                    help=f"minimum permit expiration date (default {d.permit_min_expiration})")
    ap.add_argument("--sr-min-initiated", type=_parse_date, default=d.sr_min_initiated,
                    help=f"minimum service request initiation date (default {d.sr_min_initiated})")
    ap.add_argument("--timeout", type=_positive, default=60.0, help="HTTP timeout per request in seconds")
    ap.add_argument("--retries", type=int, default=5, help="HTTP retries for transient errors")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir.resolve()
    configure_logging(out_dir / "logs" / LOG_NAME, args.verbose)
    opts = RunOptions(
        out_dir=out_dir,
        target_crs=args.crs,
        tolerance_ft=args.tolerance_ft,
        filters=Filters(permit_min_expiration=args.permit_min_expiration, sr_min_initiated=args.sr_min_initiated),
        timeout=args.timeout,
        retries=args.retries,
    )
    try:
        history = run(opts)
    except (ArcGISError, ValueError) as exc:
        LOG.error("Pipeline failed: %s", exc)
        return 1
    except Exception:
        LOG.exception("Pipeline failed with an unexpected error")
        return 1
    print(json.dumps({k: history[k] for k in ("run_id", "subblocks_written", "permits_snapped", "srs_matched", "dual_conflict_subblocks")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
