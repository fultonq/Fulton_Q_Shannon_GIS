"""Step 5 - Render PNG previews of the project (whole District + a zoomed block)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env as Q
Q.start()
from qgis.core import (QgsProject, QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle,
                       QgsCoordinateTransform, QgsCoordinateReferenceSystem)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor
proj = QgsProject.instance()
proj.read(os.path.join(Q.ROOT, "CS12_Roadway_Enrichment.qgz"))
vis = [n.layer() for n in proj.layerTreeRoot().findLayers() if n.isVisible() and n.layer().isSpatial()]
enr = next(l for l in vis if "ENRICHED" in l.name())
def render(extent, fn, size=(1600, 1600)):
    ms = QgsMapSettings(); ms.setLayers(vis); ms.setDestinationCrs(proj.crs())
    ms.setOutputSize(QSize(*size)); ms.setBackgroundColor(QColor("white"))
    ms.setExtent(extent)
    job = QgsMapRendererParallelJob(ms); job.start(); job.waitForFinished()
    job.renderedImage().save(fn); print("wrote", fn)
xf = QgsCoordinateTransform(enr.crs(), proj.crs(), proj)
render(xf.transformBoundingBox(enr.extent()), os.path.join(Q.DOCS, "map_preview_district.png"))
both = next(l for l in proj.mapLayers().values() if "BOTH_FLAG" in l.name())
f = max(both.getFeatures(), key=lambda f: f["PRMT_CNT"])
bb = f.geometry().boundingBox(); bb.grow(120)
render(xf.transformBoundingBox(bb), os.path.join(Q.DOCS, "map_preview_block.png"), (1400, 1000))
