"""
Step 6 - Zip the project folder as <Name>_GIS.zip and verify the zipped project opens.

Usage: python-qgis.bat 06_package.py [FirstName_M_LastName] [verify_dir]   (default name: Fulton_Q_Shannon)
"""
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env as Q  # noqa: E402

NAME = (sys.argv[1] if len(sys.argv) > 1 else "Fulton_Q_Shannon") + "_GIS"
ROOT = Q.ROOT
OUT_DIR = os.path.join(ROOT, "submission")
ZIP = os.path.join(OUT_DIR, NAME + ".zip")

SKIP_DIRS = {"submission", "__pycache__", ".venv", ".git"}


def include(rel):
    parts = rel.replace("\\", "/").split("/")
    if parts[0] in SKIP_DIRS or "__pycache__" in parts:
        return False
    # cached REST pages (raw JSON) are re-creatable; the merged raw GeoPackage is kept
    if rel.replace("\\", "/").startswith("data/raw/") and rel.endswith(".json") and len(parts) > 3:
        return False
    if rel.endswith((".gpkg-wal", ".gpkg-shm", ".lock", ".pdf")):
        return False
    return True


os.makedirs(OUT_DIR, exist_ok=True)
if os.path.exists(ZIP):
    os.remove(ZIP)
n = 0
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            full = os.path.join(d, f)
            rel = os.path.relpath(full, ROOT)
            if include(rel):
                z.write(full, os.path.join(NAME, rel))
                n += 1
print(f"zipped {n} files -> {ZIP} ({os.path.getsize(ZIP) / 1e6:.1f} MB)")

# ---- verify: unzip elsewhere and open the project from there ----
verify = sys.argv[2] if len(sys.argv) > 2 else os.path.join(OUT_DIR, "_verify")
shutil.rmtree(verify, ignore_errors=True)
with zipfile.ZipFile(ZIP) as z:
    z.extractall(verify)
Q.start()
from qgis.core import QgsProject  # noqa: E402

p = QgsProject.instance()
assert p.read(os.path.join(verify, NAME, "CS12_Roadway_Enrichment.qgz"))
bad = []
for lyr in p.mapLayers().values():
    src = lyr.source()
    local = lyr.providerType() == "ogr"
    ok = lyr.isValid() and (not local or os.path.normcase(verify) in os.path.normcase(src))
    print(f"  {'OK ' if ok else 'BAD'} {lyr.providerType():20s} {lyr.name()}")
    if not ok:
        bad.append(lyr.name())
p.clear()
print("VERIFY:", "all layers valid and resolved inside the unzipped copy" if not bad else f"problems: {bad}")
