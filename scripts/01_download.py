"""
Step 1 - Download the three DC GIS REST layers to a local GeoPackage (raw copies).

* Paging uses objectIds (returnIdsOnly, then POST in chunks), so the 2,000-record
  maxRecordCount limit never truncates the data.
* Geometry is requested in EPSG:26985 (NAD83 / Maryland State Plane, metres). That is
  the District's standard projected CRS, so snap and join distances are true metres.
* Server-side WHERE clauses only make the download smaller (Cityworks has about 1.5 M
  rows). All business filters are applied later in QGIS Processing, so they appear in
  the geoprocessing history.

Run with QGIS's Python:  X:\\QGIS\\bin\\python-qgis.bat 01_download.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from osgeo import gdal, ogr

gdal.UseExceptions()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
RAW_GPKG = os.path.join(RAW_DIR, "raw_downloads.gpkg")
OUT_SR = 26985
CHUNK = 1000

SOURCES = {
    # layer name : (REST url, server-side pre-filter)
    "permits_raw": (
        "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/DDOT_TOPS/MapServer/23",
        "1=1",
    ),
    "roadway_subblock_raw": (
        "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/162",
        "1=1",
    ),
    "cityworks_sr_raw": (
        "https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/Cityworks/MapServer/1",
        "INITIATEDDATE >= timestamp '2025-10-01 00:00:00'",
    ),
}


def post(url, params, tries=5):
    params = dict(params, f="json")
    data = urllib.parse.urlencode(params).encode()
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, data=data, timeout=300) as r:
                js = json.load(r)
            if "error" in js:
                raise RuntimeError(js["error"])
            return js
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            print(f"    retry {i + 1}/{tries}: {e}", flush=True)
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"failed: {url}")


def download(name, url, where, log):
    page_dir = os.path.join(RAW_DIR, name)
    os.makedirs(page_dir, exist_ok=True)
    ids = post(url + "/query", {"where": where, "returnIdsOnly": "true"})
    oids = sorted(ids.get("objectIds") or [])
    print(f"[{name}] {len(oids):,} features match: {where}", flush=True)
    pages = []
    for n, i in enumerate(range(0, len(oids), CHUNK)):
        fn = os.path.join(page_dir, f"page_{n:04d}.json")
        if not os.path.exists(fn):
            js = post(url + "/query", {
                "objectIds": ",".join(map(str, oids[i:i + CHUNK])),
                "outFields": "*",
                "outSR": OUT_SR,
                "returnGeometry": "true",
            })
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(js, f)
        pages.append(fn)
        if n % 10 == 0:
            print(f"    page {n + 1}/{-(-len(oids) // CHUNK)}", flush=True)

    # Merge the pages into one GeoPackage layer (OGR ESRIJSON driver keeps date types).
    for k, fn in enumerate(pages):
        gdal.VectorTranslate(
            RAW_GPKG, fn,
            options=gdal.VectorTranslateOptions(
                format="GPKG",
                layerName=name,
                # first page: create the layer inside the existing GeoPackage ("update")
                # without recreating the file; later pages append to it.
                accessMode=("append" if k > 0
                            else ("update" if os.path.exists(RAW_GPKG) else None)),
                dstSRS=f"EPSG:{OUT_SR}",
                layerCreationOptions=["SPATIAL_INDEX=YES"],
            ),
        )
    ds = ogr.Open(RAW_GPKG)
    cnt = ds.GetLayerByName(name).GetFeatureCount()
    print(f"[{name}] written {cnt:,} features to {RAW_GPKG}", flush=True)
    log.append({"layer": name, "url": url, "server_where": where,
                "expected": len(oids), "written": cnt,
                "downloaded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})


def existing_layers():
    if not os.path.exists(RAW_GPKG):
        return set()
    ds = ogr.Open(RAW_GPKG)
    return {ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())}


if __name__ == "__main__":
    os.makedirs(RAW_DIR, exist_ok=True)
    only = sys.argv[1:] or list(SOURCES)
    log = []
    for nm in only:
        if nm in existing_layers():
            ogr.Open(RAW_GPKG, update=1).DeleteLayer(nm)
        download(nm, *SOURCES[nm], log)
    with open(os.path.join(RAW_DIR, "download_log.json"), "a", encoding="utf-8") as f:
        for row in log:
            f.write(json.dumps(row) + "\n")
