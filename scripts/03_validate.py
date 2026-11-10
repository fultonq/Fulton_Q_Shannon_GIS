"""Step 3 - Validate outputs and write docs/validation_summary.txt."""
import os
from osgeo import ogr
ogr.UseExceptions()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = os.path.join(ROOT, "data", "output", "CS12_Roadway_Enrichment.gpkg")
ds = ogr.Open(G)
out = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)
def q(sql):
    r = ds.ExecuteSQL(sql); rows = [[f.GetField(i) for i in range(f.GetFieldCount())] for f in r]
    ds.ReleaseResultSet(r); return rows
p("== Layers in", G)
for i in range(ds.GetLayerCount()):
    l = ds.GetLayer(i); p(f"  {l.GetName():35s} {l.GetFeatureCount():>7,}  {ogr.GeometryTypeToName(l.GetGeomType())}")
d = ds.GetLayerByName("roadway_subblock_enriched").GetLayerDefn()
p("== Enrichment fields:", [(d.GetFieldDefn(j).GetName(), d.GetFieldDefn(j).GetTypeName()) for j in range(d.GetFieldCount())
                          if d.GetFieldDefn(j).GetName() in ("SUBBLOCKKEY","PRMT_CNT","PRMT_MAXEX","SR_CNT","SR_MAXINIT","HAS_PRMT","HAS_SR","BOTH_FLAG","FLAG_CAT")])
p("== Subblocks by ROADTYPE:", q("SELECT ROADTYPE, count(*) FROM roadway_subblock_enriched GROUP BY 1"))
p("== FLAG_CAT:", q("SELECT FLAG_CAT, count(*), sum(PRMT_CNT), sum(SR_CNT) FROM roadway_subblock_enriched GROUP BY 1 ORDER BY 2"))
p("== Totals (blocks w/ permits, permits counted, blocks w/ SR, SRs counted, both):",
  q("SELECT sum(HAS_PRMT), sum(PRMT_CNT), sum(HAS_SR), sum(SR_CNT), sum(BOTH_FLAG) FROM roadway_subblock_enriched"))
p("== Max dates overall:", q("SELECT max(PRMT_MAXEX), min(PRMT_MAXEX), max(SR_MAXINIT), min(SR_MAXINIT) FROM roadway_subblock_enriched"))
p("== Permit snap status:", q("SELECT SNAP_STAT, COUNTED, count(*), round(avg(SNAP_DIST),3), round(max(SNAP_DIST),3) FROM permits_filtered_snapped GROUP BY 1,2"))
p("== Permit counted check (sum PRMT_CNT == COUNTED permits):",
  q("SELECT (SELECT sum(PRMT_CNT) FROM roadway_subblock_enriched), (SELECT count(*) FROM permits_filtered_snapped WHERE COUNTED=1)"))
p("== SR status:", q("SELECT STATUS, DESCRIPTION, count(*), sum(SB_SUBBLOCKKEY IS NULL) AS unassigned FROM cityworks_sr_filtered GROUP BY 1,2"))
p("== SR counted check:", q("SELECT (SELECT sum(SR_CNT) FROM roadway_subblock_enriched), (SELECT count(*) FROM cityworks_sr_filtered WHERE SB_SUBBLOCKKEY IS NOT NULL)"))
p("== Duplicate permits in snapped layer:", q("SELECT count(*) - count(DISTINCT OBJECTID) FROM permits_filtered_snapped"))
# geometric check: snapped points really lie on their subblock
r = q("""SELECT count(*), sum(ST_Distance(p.geom, s.geom) < 0.01)
         FROM permits_filtered_snapped p JOIN roadway_subblock_enriched s ON s.SUBBLOCKKEY = p.SB_SUBBLOCKKEY""")
p("== Snapped permits lying on their street/svc/ramp subblock (n, within 1 cm):", r)
p("== Top 10 blocks with permits AND SRs:")
for row in q("""SELECT SUBBLOCKKEY, ROUTENAME, FROMSTREET, TOSTREET, PRMT_CNT, PRMT_MAXEX, SR_CNT, SR_MAXINIT
                FROM roadway_subblock_enriched WHERE BOTH_FLAG=1 ORDER BY PRMT_CNT + SR_CNT DESC LIMIT 10"""):
    p("   ", row)
open(os.path.join(ROOT, "docs", "validation_summary.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
