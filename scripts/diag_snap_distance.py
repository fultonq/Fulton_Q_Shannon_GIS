"""Diagnostic: distance from filtered permits / SRs to the nearest filtered subblock (no limit).
Used to choose SNAP_TOL_M in 02_process.py."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env as Q
Q.start()
import processing
R = Q.RAW_GPKG
sb = processing.run("native:extractbyexpression", {"INPUT": f"{R}|layername=roadway_subblock_raw",
     "EXPRESSION": "\"ROADTYPE\" IN ('1','2','3')", "OUTPUT": "TEMPORARY_OUTPUT"})["OUTPUT"]
sball = f"{R}|layername=roadway_subblock_raw"
pf = processing.run("native:extractbyexpression", {"INPUT": f"{R}|layername=permits_raw",
     "EXPRESSION": "\"ExpirationDate\" >= to_datetime('2025-10-01 00:00:00') AND \"RenewalDescription\"='Renewal' AND \"StatusDescription\"='Issued' AND (\"IsExcavation\"=1 OR \"IsPaving\"=1)",
     "OUTPUT": "TEMPORARY_OUTPUT"})["OUTPUT"]
sr = processing.run("native:extractbyexpression", {"INPUT": f"{R}|layername=cityworks_sr_raw",
     "EXPRESSION": "\"STATUS\" NOT IN ('CLOSED','CANCEL','COMPLETE') AND \"DESCRIPTION\" IN ('ROADWAY REPAIR','POTHOLES','STREET REPAVING','STREET REPAIR','STREET PAVING SCHEDU')",
     "OUTPUT": "TEMPORARY_OUTPUT"})["OUTPUT"]
def dist(lyr, ref, label):
    j = processing.run("native:joinbynearest", {"INPUT": lyr, "INPUT_2": ref, "FIELDS_TO_COPY": ["ROADTYPE"],
        "DISCARD_NONMATCHING": False, "PREFIX": "SB_", "NEIGHBORS": 1, "MAX_DISTANCE": None, "OUTPUT": "TEMPORARY_OUTPUT"})["OUTPUT"]
    d = sorted(f["distance"] for f in j.getFeatures())
    n = len(d); q = lambda p: round(d[min(n-1, int(p*n))], 2)
    print(f"{label}: rows={n} input={lyr.featureCount()} | <0.01m {sum(x<0.01 for x in d)} | <=5 {sum(x<=5 for x in d)} | <=15 {sum(x<=15 for x in d)} | <=30 {sum(x<=30 for x in d)} | <=50 {sum(x<=50 for x in d)} | <=100 {sum(x<=100 for x in d)} | p50 {q(.5)} p90 {q(.9)} p99 {q(.99)} max {d[-1]:.1f}")
    if ref is sball:
        from collections import Counter
        print("   nearest ROADTYPE (all road types):", Counter(f["SB_ROADTYPE"] for f in j.getFeatures()))
dist(pf, sb, "permits -> street/svc/ramp")
dist(pf, sball, "permits -> ALL subblocks")
dist(sr, sb, "SRs -> street/svc/ramp")
