from datetime import date

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
import shapely
from pyproj import CRS
from shapely.geometry import LineString, Point

CRS_FT = "EPSG:2248"


def _subblocks(process):
    raw = gpd.GeoDataFrame(
        {
            "OBJECTID": [1, 2, 3],
            "SUBBLOCKKEY": ["A", "B", None],
            "ROADTYPE": ["1", "3", "2"],
            "SHAPE.LEN": [1.0, 2.0, 3.0],
        },
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(0, 500), (1000, 500)]),
            LineString([(5000, 0), (5000, 1000)]),
        ],
        crs=CRS_FT,
    )
    return process.prepare_subblocks(raw, CRS_FT)


def _points(rows, date_col, crs=CRS_FT):
    return gpd.GeoDataFrame(
        {"ID": [r[0] for r in rows], date_col: pd.to_datetime([r[1] for r in rows], utc=True)},
        geometry=[Point(r[2]) for r in rows],
        crs=crs,
    )


# --- SQL ---------------------------------------------------------------------
def test_sql_literal_escapes_quotes(process):
    assert process.sql_literal("O'Neil") == "'O''Neil'"
    with pytest.raises(ValueError):
        process.sql_list([])


def test_default_where_clauses_match_spec(process):
    f = process.Filters()
    assert process.subblock_where(f) == "ROADTYPE IN ('1', '2', '3')"
    assert process.permit_where(f) == (
        "ExpirationDate >= timestamp '2025-10-01 00:00:00' AND Renewal = 2"
        " AND StatusDescription IN ('Issued') AND (IsExcavation = 1 OR IsPaving = 1)"
    )
    assert process.service_request_where(f) == (
        "STATUS NOT IN ('CLOSED', 'CANCEL', 'COMPLETE') AND DESCRIPTION IN ('ROADWAY REPAIR', 'POTHOLES',"
        " 'STREET REPAVING', 'STREET REPAIR', 'STREET PAVING SCHEDU')"
        " AND INITIATEDDATE >= timestamp '2025-10-01 00:00:00'"
    )
    custom = process.Filters(sr_min_initiated=date(2026, 1, 2))
    assert "timestamp '2026-01-02 00:00:00'" in process.service_request_where(custom)


# --- CRS / prep ----------------------------------------------------------------
def test_units_per_foot(process):
    assert process.crs_units_per_foot(CRS("EPSG:2248")) == pytest.approx(0.999998, rel=1e-5)
    assert process.crs_units_per_foot(CRS("EPSG:26985")) == pytest.approx(0.3048)
    with pytest.raises(ValueError):
        process.crs_units_per_foot(CRS("EPSG:4326"))


def test_prepare_subblocks(process):
    sb = _subblocks(process)
    assert list(sb.index) == [0, 1, 2]
    assert list(sb["SUBBLOCK_UID"]) == ["A", "B", "OID-3"]
    assert list(sb["ROADWAY_TYPE"]) == ["STREET", "RAMP", "SERVICE LANE"]
    assert "SHAPE_LEN" in sb.columns and "SHAPE.LEN" not in sb.columns


def test_sanitize_rejects_case_collisions(process):
    gdf = gpd.GeoDataFrame({"Ward": [1], "WARD": [2]}, geometry=[Point(0, 0)], crs=CRS_FT)
    with pytest.raises(ValueError, match="case-insensitively"):
        process.sanitize_columns(gdf)


def test_drop_invalid_geometry(process):
    gdf = gpd.GeoDataFrame({"a": [1, 2, 3]}, geometry=[Point(0, 0), None, Point()], crs=CRS_FT)
    out, n = process.drop_invalid_geometry(gdf, "x")
    assert n == 2 and len(out) == 1


# --- snapping ------------------------------------------------------------------
def test_snap_moves_point_onto_nearest_line(process):
    sb = _subblocks(process)
    pts = _points([("p1", "2026-01-01", (250, 40)), ("p2", "2026-01-01", (700, 480)),
                   ("far", "2026-01-01", (3000, 3000))], "ExpirationDate")
    out = process.match_to_subblocks(pts, sb, tolerance=150, units_per_foot=1.0, snap=True)

    assert list(out["SUBBLOCK_UID"].astype(object).where(out["SUBBLOCK_UID"].notna(), None)) == ["A", "B", None]
    assert list(out["SNAPPED"]) == [1, 1, 0]
    assert out.geometry.iloc[0].equals(Point(250, 0))
    assert out.geometry.iloc[1].equals(Point(700, 500))
    assert out.geometry.iloc[2].equals(Point(3000, 3000))  # unmatched keeps original location
    assert list(out["ORIG_X"]) == [250, 700, 3000]
    assert out["NEAR_DIST_FT"].iloc[0] == pytest.approx(40)
    assert pd.isna(out["NEAR_DIST_FT"].iloc[2])
    # every snapped point lies on its assigned line
    for geom, idx in zip(out.geometry[:2], out[process.SUBBLOCK_IDX][:2]):
        assert shapely.distance(geom, sb.geometry.iloc[int(idx)]) < 1e-9


def test_tie_does_not_duplicate_points(process):
    sb = _subblocks(process)
    pts = _points([("mid", "2026-01-01", (500, 250))], "ExpirationDate")  # equidistant from A and B
    out = process.match_to_subblocks(pts, sb, tolerance=300, units_per_foot=1.0, snap=True)
    assert len(out) == 1 and out["SUBBLOCK_UID"].iloc[0] in {"A", "B"}


def test_match_without_snap_keeps_geometry(process):
    sb = _subblocks(process)
    pts = _points([("s", "2026-01-01", (100, 30))], "INITIATEDDATE")
    out = process.match_to_subblocks(pts, sb, tolerance=150, units_per_foot=1.0, snap=False)
    assert out.geometry.iloc[0].equals(Point(100, 30))
    assert out["SUBBLOCK_UID"].iloc[0] == "A"
    assert "SNAPPED" not in out.columns


def test_match_handles_empty_points(process):
    sb = _subblocks(process)
    empty = _points([], "ExpirationDate")
    out = process.match_to_subblocks(empty, sb, tolerance=150, units_per_foot=1.0, snap=True)
    assert out.empty and {"SUBBLOCK_UID", "SNAPPED", "NEAR_DIST_FT"} <= set(out.columns)


def test_match_rejects_crs_mismatch(process):
    sb = _subblocks(process)
    pts = _points([("p", "2026-01-01", (0, 0))], "ExpirationDate", crs="EPSG:26985")
    with pytest.raises(ValueError, match="CRS mismatch"):
        process.match_to_subblocks(pts, sb, tolerance=150, units_per_foot=1.0, snap=True)


# --- enrichment ----------------------------------------------------------------
def test_enrich_counts_dates_and_flags(process):
    sb = _subblocks(process)
    permits = process.match_to_subblocks(
        _points([("p1", "2026-01-01", (100, 10)), ("p2", "2026-06-30", (900, 10)),
                 ("p3", "2026-03-01", (100, 490))], "ExpirationDate"),
        sb, 150, 1.0, snap=True)
    srs = process.match_to_subblocks(
        _points([("s1", "2025-11-01", (500, 20)), ("s2", "2025-12-15", (5010, 500)),
                 ("s3", "2025-10-05", (9000, 9000))], "INITIATEDDATE"),
        sb, 150, 1.0, snap=False)
    out = process.enrich_subblocks(sb, permits, srs).set_index("SUBBLOCK_UID")

    assert out.loc["A", "PERMIT_COUNT"] == 2 and out.loc["A", "SR_COUNT"] == 1
    assert out.loc["A", "MAX_PERMIT_EXP_DATE"] == pd.Timestamp("2026-06-30", tz="UTC")
    assert out.loc["A", "FLAG_BOTH_PERMIT_AND_SR"] == 1
    assert out.loc["A", "ACTIVITY_CLASS"] == "Permit + SR"
    assert out.loc["B", "ACTIVITY_CLASS"] == "Permit only" and out.loc["B", "FLAG_BOTH_PERMIT_AND_SR"] == 0
    assert out.loc["OID-3", "ACTIVITY_CLASS"] == "SR only"
    assert out.loc["OID-3", "MAX_SR_INIT_DATE"] == pd.Timestamp("2025-12-15", tz="UTC")
    assert pd.isna(out.loc["B", "MAX_SR_INIT_DATE"])
    assert out["PERMIT_COUNT"].sum() == 3 and out["SR_COUNT"].sum() == 2  # unmatched SR not counted


# --- GeoPackage output ---------------------------------------------------------
def test_write_geopackage_atomic_and_history_appends(process, tmp_path):
    sb = _subblocks(process)
    permits = process.match_to_subblocks(
        _points([("p1", "2026-01-01", (100, 10))], "ExpirationDate"), sb, 150, 1.0, snap=True)
    srs = process.match_to_subblocks(_points([], "INITIATEDDATE"), sb, 150, 1.0, snap=False)
    enriched = process.enrich_subblocks(sb, permits, srs)
    gpkg = tmp_path / "data" / "out.gpkg"
    layers = {
        "roadway_subblock_enriched": (enriched, "MultiLineString"),
        "permits_snapped": (permits, "Point"),
        "service_requests_filtered": (srs, "Point"),
    }
    process.write_geopackage(gpkg, layers, {"run_id": "r1", "n": 1})
    process.write_geopackage(gpkg, layers, {"run_id": "r2", "n": 2})

    names = dict(pyogrio.list_layers(gpkg))
    assert names["roadway_subblock_enriched"] == "MultiLineString"
    assert names["service_requests_filtered"] == "Point"  # empty layer still typed
    assert names["geoprocessing_history"] is None
    hist = pyogrio.read_dataframe(gpkg, layer="geoprocessing_history", read_geometry=False)
    assert list(hist["run_id"]) == ["r1", "r2"]
    written = pyogrio.read_dataframe(gpkg, layer="permits_snapped")
    assert process.SUBBLOCK_IDX not in written.columns
    assert [p.name for p in gpkg.parent.iterdir()] == ["out.gpkg"]  # no temp leftovers


def test_summary_report_renders(process):
    sb = _subblocks(process)
    permits = process.match_to_subblocks(
        _points([("p1", "2026-01-01", (100, 10))], "ExpirationDate"), sb, 150, 1.0, snap=True)
    srs = process.match_to_subblocks(
        _points([("s1", "2025-11-01", (500, 20))], "INITIATEDDATE"), sb, 150, 1.0, snap=False)
    enriched = process.enrich_subblocks(sb, permits, srs)
    history = {k: 0 for k in (
        "subblocks_written", "permits_fetched", "permits_snapped", "permits_valid", "srs_fetched",
        "srs_matched", "srs_valid", "subblocks_with_permits", "subblocks_with_srs",
        "dual_conflict_subblocks", "permits_unmatched", "srs_unmatched", "permits_null_geometry",
        "srs_null_geometry")}
    history.update(run_id="x", run_finished_utc="now", script_version="t", snap_tolerance_ft=150.0,
                   subblock_where="w1", permit_where="w2", sr_where="w3")
    md = process.build_summary_report(enriched, history)
    assert "| A | STREET |" in md
    assert "n/a" in md  # zero-denominator percentages handled


# --- V2: blocks, QA layers, insights -----------------------------------------
def _v2_fixture(process):
    raw = gpd.GeoDataFrame(
        {
            "OBJECTID": [1, 2, 3],
            "SUBBLOCKKEY": ["A", "B", "C"],
            "BLOCKID": ["BLK1", "BLK1", None],
            "ROADTYPE": ["1", "1", "3"],
            "ROUTENAME": ["K ST NW", "K ST NW", "RAMP X"],
            "WARD_ID": ["2", "2", "6"],
        },
        geometry=[
            LineString([(0, 0), (500, 0)]),
            LineString([(500, 0), (1000, 0)]),
            LineString([(5000, 0), (5000, 1000)]),
        ],
        crs=CRS_FT,
    )
    sb = process.prepare_subblocks(raw, CRS_FT)
    permits = process.match_to_subblocks(
        _points([("P1", "2026-01-01", (100, 40)), ("P2", "2026-05-01", (900, -30)),
                 ("FAR", "2026-01-01", (3000, 3000))], "ExpirationDate").rename(columns={"ID": "PermitNumber"}),
        sb, 150, 1.0, snap=True)
    srs = process.match_to_subblocks(
        _points([("S1", "2025-11-01", (700, 20)), ("S2", "2025-12-01", (5030, 500))],
                "INITIATEDDATE").rename(columns={"ID": "REQUESTID"}),
        sb, 150, 1.0, snap=False)
    return sb, permits, srs, process.enrich_subblocks(sb, permits, srs)


def test_aggregate_blocks(process):
    sb, permits, srs, enriched = _v2_fixture(process)
    blocks = process.aggregate_blocks(enriched, 1.0).set_index("BLOCK_UID")

    assert list(blocks.index) == ["BLK1", "SB:C"]  # null BLOCKID kept as its own block
    b = blocks.loc["BLK1"]
    assert (b.SUBBLOCK_COUNT, b.PERMIT_COUNT, b.SR_COUNT) == (2, 2, 1)
    # A has a permit only, B has a permit and an SR
    assert b.FLAG_BOTH_PERMIT_AND_SR == 1 and b.SUBBLOCKS_WITH_BOTH == 1
    assert b.MAX_PERMIT_EXP_DATE == pd.Timestamp("2026-05-01", tz="UTC")
    assert b.geometry.geom_type == "LineString" and b.LENGTH_FT == pytest.approx(1000)  # merged
    assert blocks.loc["SB:C", "ACTIVITY_CLASS"] == "SR only"
    assert blocks["PERMIT_COUNT"].sum() == enriched["PERMIT_COUNT"].sum()
    assert blocks["SR_COUNT"].sum() == enriched["SR_COUNT"].sum()


def test_original_points_restore_source_location(process):
    _, permits, _, _ = _v2_fixture(process)
    orig = process.original_points(permits)
    assert orig.geometry.iloc[0].equals(Point(100, 40))
    assert permits.geometry.iloc[0].equals(Point(100, 0))
    assert "ORIG_X" not in orig.columns and len(orig) == len(permits)


def test_connector_lines(process):
    sb, permits, srs, _ = _v2_fixture(process)
    qa_p = process.connector_lines(permits, sb, ["PermitNumber", "SUBBLOCK_UID", "NEAR_DIST_FT"], 1.0,
                                   ("ORIG_X", "ORIG_Y"))
    assert list(qa_p["PermitNumber"]) == ["P1", "P2"]  # unmatched permit has no line
    assert list(qa_p.geometry.iloc[0].coords) == [(100, 40), (100, 0)]
    assert list(qa_p["LENGTH_FT"]) == list(qa_p["NEAR_DIST_FT"])

    qa_s = process.connector_lines(srs, sb, ["REQUESTID"], 1.0)
    assert list(qa_s.geometry.iloc[1].coords) == [(5030, 500), (5000, 500)]

    empty = process.connector_lines(srs.iloc[0:0], sb, ["REQUESTID"], 1.0)
    assert empty.empty and "LENGTH_FT" in empty.columns


def test_insight_tables(process):
    _, _, _, enriched = _v2_fixture(process)
    top = process.top_conflicts(enriched)
    assert list(top["SUBBLOCK_UID"]) == ["B"] and top["ACTIVITY_SCORE"].iloc[0] == 2

    ward = process.ward_summary(enriched).set_index("WARD")
    assert ward.loc["2", "PERMIT_LOCATIONS"] == 2 and ward.loc["6", "OPEN_SRS"] == 1
    assert ward.loc["2", "DISTINCT_PERMITS"] == 2

    act = process.activity_summary(enriched, 1.0)
    assert list(act["ACTIVITY_CLASS"]) == ["Permit + SR", "Permit only", "SR only"]
    assert act["SUBBLOCKS"].sum() == 3


def test_top_conflicts_ranking(process):
    sb, _, _, enriched = _v2_fixture(process)
    e = enriched.copy()
    e["PERMIT_COUNT"] = [9, 1, 1]  # A: many address rows, but only 3 distinct permits
    e["DISTINCT_PERMIT_COUNT"] = [3, 1, 1]
    e["SR_COUNT"] = [1, 3, 1]
    e["DISTINCT_SR_LOCATIONS"] = [1, 3, 1]
    e["FLAG_BOTH_PERMIT_AND_SR"] = 1
    top = process.top_conflicts(e)
    assert list(top["SUBBLOCK_UID"]) == ["B", "A", "C"]  # tie on score broken by SR_COUNT
    assert list(top["RANK"]) == [1, 2, 3]


def test_multi_address_permits_counted_once(process):
    """TOPS stores one row per work-location address; distinct counts must collapse them."""
    sb, _, srs, _ = _v2_fixture(process)
    # M1 has three addresses: two on subblock A, one on subblock B (same block BLK1).
    rows = [("M1", "2026-01-01", (100, 10)), ("M1", "2026-01-01", (200, 10)),
            ("M1", "2026-01-01", (700, 10)), ("P9", "2026-02-01", (800, 10))]
    permits = process.match_to_subblocks(
        _points(rows, "ExpirationDate").rename(columns={"ID": "PermitNumber"}), sb, 150, 1.0, snap=True)
    enriched = process.enrich_subblocks(sb, permits, srs)
    e = enriched.set_index("SUBBLOCK_UID")
    assert (e.loc["A", "PERMIT_COUNT"], e.loc["A", "DISTINCT_PERMIT_COUNT"]) == (2, 1)
    assert (e.loc["B", "PERMIT_COUNT"], e.loc["B", "DISTINCT_PERMIT_COUNT"]) == (2, 2)
    assert e.loc["C", "DISTINCT_PERMIT_COUNT"] == 0

    blocks = process.aggregate_blocks(enriched, 1.0, permits).set_index("BLOCK_UID")
    assert blocks.loc["BLK1", "PERMIT_COUNT"] == 4
    assert blocks.loc["BLK1", "DISTINCT_PERMIT_COUNT"] == 2  # M1 spans A and B but counts once
    assert blocks.loc["SB:C", "DISTINCT_PERMIT_COUNT"] == 0
    # Without the permit rows the block falls back to the subblock sum (upper bound).
    assert process.aggregate_blocks(enriched, 1.0).set_index("BLOCK_UID").loc["BLK1", "DISTINCT_PERMIT_COUNT"] == 3

    ward = process.ward_summary(enriched, permits).set_index("WARD")
    assert (ward.loc["2", "PERMIT_LOCATIONS"], ward.loc["2", "DISTINCT_PERMITS"]) == (4, 2)

    top = process.top_conflicts(enriched)
    assert list(top["SUBBLOCK_UID"]) == ["B"]
    assert top["ACTIVITY_SCORE"].iloc[0] == 3  # 2 distinct permits + 1 SR


def test_distinct_falls_back_to_rows_without_permit_id(process):
    sb, permits, srs, _ = _v2_fixture(process)
    e = process.enrich_subblocks(sb, permits.drop(columns="PermitNumber"), srs)
    assert (e["DISTINCT_PERMIT_COUNT"] == e["PERMIT_COUNT"]).all()


def test_repeat_sr_reports_at_one_location_counted_once(process):
    """Block-range SR addresses geocode to one point; the ranking must not reward repeats."""
    sb, permits, _, _ = _v2_fixture(process)
    rows = [(f"S{i}", "2026-04-08", (700, 20)) for i in range(4)]  # four reports, same point on B
    rows += [("T1", "2026-05-01", (100, 20)), ("T2", "2026-05-02", (300, 20))]  # two places on A
    srs = process.match_to_subblocks(
        _points(rows, "INITIATEDDATE").rename(columns={"ID": "REQUESTID"}), sb, 150, 1.0, snap=False)
    enriched = process.enrich_subblocks(sb, permits, srs)
    e = enriched.set_index("SUBBLOCK_UID")
    assert (e.loc["B", "SR_COUNT"], e.loc["B", "DISTINCT_SR_LOCATIONS"]) == (4, 1)
    assert (e.loc["A", "SR_COUNT"], e.loc["A", "DISTINCT_SR_LOCATIONS"]) == (2, 2)

    top = process.top_conflicts(enriched)
    assert list(top["SUBBLOCK_UID"]) == ["A", "B"]  # 1 permit + 2 places beats 1 permit + 4 repeats
    assert list(top["ACTIVITY_SCORE"]) == [3, 2]

    blocks = process.aggregate_blocks(enriched, 1.0, permits).set_index("BLOCK_UID")
    assert (blocks.loc["BLK1", "SR_COUNT"], blocks.loc["BLK1", "DISTINCT_SR_LOCATIONS"]) == (6, 3)
    ward = process.ward_summary(enriched, permits).set_index("WARD")
    assert (ward.loc["2", "OPEN_SRS"], ward.loc["2", "DISTINCT_SR_LOCATIONS"]) == (6, 3)


def test_enrich_date_windows(process):
    """Earliest permit start / latest permit end, and oldest / newest open SR, per subblock and block."""
    sb, _, _, _ = _v2_fixture(process)
    raw = _points([("P1", "2026-06-30", (100, 10)), ("P2", "2026-03-31", (200, 10))], "ExpirationDate")
    raw["EffectiveDate"] = pd.to_datetime(["2026-02-01", "2026-01-15"], utc=True)
    permits = process.match_to_subblocks(raw.rename(columns={"ID": "PermitNumber"}), sb, 150, 1.0, snap=True)
    srs = process.match_to_subblocks(
        _points([("S1", "2025-11-01", (300, 20)), ("S2", "2026-04-01", (400, 20)),
                 ("S3", "2025-12-01", (700, 20))], "INITIATEDDATE").rename(columns={"ID": "REQUESTID"}),
        sb, 150, 1.0, snap=False)
    enriched = process.enrich_subblocks(sb, permits, srs)
    a = enriched.set_index("SUBBLOCK_UID").loc["A"]
    assert a.MIN_PERMIT_EFF_DATE == pd.Timestamp("2026-01-15", tz="UTC")
    assert a.MAX_PERMIT_EXP_DATE == pd.Timestamp("2026-06-30", tz="UTC")
    assert a.MIN_SR_INIT_DATE == pd.Timestamp("2025-11-01", tz="UTC")
    assert a.MAX_SR_INIT_DATE == pd.Timestamp("2026-04-01", tz="UTC")
    assert pd.isna(enriched.set_index("SUBBLOCK_UID").loc["B", "MIN_PERMIT_EFF_DATE"])

    blk = process.aggregate_blocks(enriched, 1.0, permits).set_index("BLOCK_UID").loc["BLK1"]
    assert blk.MIN_SR_INIT_DATE == pd.Timestamp("2025-11-01", tz="UTC")
    assert blk.MIN_PERMIT_EFF_DATE == pd.Timestamp("2026-01-15", tz="UTC")

    top = process.top_conflicts(enriched)
    assert {"MIN_PERMIT_EFF_DATE", "MIN_SR_INIT_DATE"} <= set(top.columns)
