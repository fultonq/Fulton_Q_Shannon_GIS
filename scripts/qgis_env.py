"""Shared bootstrap: start headless QGIS + Processing and log every processing.run call."""
import datetime as _dt
import json
import os
import sys

from qgis.core import QgsApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_GPKG = os.path.join(ROOT, "data", "raw", "raw_downloads.gpkg")
OUT_GPKG = os.path.join(ROOT, "data", "output", "CS12_Roadway_Enrichment.gpkg")
SHP_DIR = os.path.join(ROOT, "data", "output", "shapefiles")
DOCS = os.path.join(ROOT, "docs")
HISTORY_JSON = os.path.join(DOCS, "geoprocessing_history.json")

_qgs = None
HISTORY = []


def start():
    global _qgs
    prefix = os.environ.get("QGIS_PREFIX_PATH", r"X:/QGIS/apps/qgis")
    QgsApplication.setPrefixPath(prefix, True)
    _qgs = QgsApplication([], False)
    _qgs.initQgis()
    sys.path.append(os.path.join(prefix, "python", "plugins"))
    from processing.core.Processing import Processing  # noqa: E402
    Processing.initialize()
    from qgis.analysis import QgsNativeAlgorithms
    reg = QgsApplication.processingRegistry()
    if not reg.providerById("native"):
        reg.addProvider(QgsNativeAlgorithms())
    return _qgs


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    try:
        from qgis.core import QgsVectorLayer
        if isinstance(v, QgsVectorLayer):
            return v.source()
    except Exception:  # noqa: BLE001
        pass
    return str(v)


def run(step, alg, params, note=""):
    """processing.run wrapper that records a geoprocessing-history entry."""
    import processing
    t0 = _dt.datetime.now()
    print(f"\n>> [{step}] {alg}  {note}", flush=True)
    res = processing.run(alg, params)
    t1 = _dt.datetime.now()
    entry = {
        "step": step,
        "algorithm": alg,
        "note": note,
        "started": t0.isoformat(timespec="seconds"),
        "seconds": round((t1 - t0).total_seconds(), 1),
        "parameters": _jsonable(params),
        "results": _jsonable(res),
        "python_command": f"processing.run({alg!r}, {json.dumps(_jsonable(params))})",
    }
    HISTORY.append(entry)
    print(f"   done in {entry['seconds']} s -> {entry['results']}", flush=True)
    return res


def save_history():
    os.makedirs(DOCS, exist_ok=True)
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(HISTORY, f, indent=2)
