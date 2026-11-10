import json, urllib.request, urllib.parse
P="https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/DDOT_TOPS/MapServer/23"
S="https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/162"
C="https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/Cityworks/MapServer/1"
def get(url, **p):
    p["f"]="json"
    data=urllib.parse.urlencode(p).encode()
    with urllib.request.urlopen(url, data=data, timeout=300) as r: return json.load(r)
def grp(url, fields, where="1=1"):
    stats=json.dumps([{"statisticType":"count","onStatisticField":"OBJECTID","outStatisticFieldName":"n"}])
    r=get(url+"/query", where=where, groupByFieldsForStatistics=fields, outStatistics=stats)
    if "error" in r: print(r); return
    rows=sorted(r["features"], key=lambda f:-(f["attributes"].get("n") or f["attributes"].get("N") or 0))
    for f in rows[:40]: print("   ", f["attributes"])
    print("   rows:",len(rows))
print("== permits domains"); m=get(P)
for f in m["fields"]:
    if f.get("domain"): print(f["name"], f["domain"].get("codedValues"))
print("== permits status/renewal/permittype (exp>=2025-10-01)")
grp(P,"StatusDescription,RenewalDescription,Renewal,PermitTypeDescription,PermitType","ExpirationDate >= timestamp '2025-10-01 00:00:00'")
print("== permits excav/paving flags, renewal issued exp>=")
grp(P,"IsExcavation,IsPaving,StatusDescription","ExpirationDate >= timestamp '2025-10-01 00:00:00' AND RenewalDescription='Renewal'")
print("== subblock ROADTYPE domain"); m=get(S)
for f in m["fields"]:
    if f["name"]=="ROADTYPE": print(f["domain"])
grp(S,"ROADTYPE")
print("== cityworks domains"); m=get(C)
for f in m["fields"]:
    if f["name"] in("STATUS","DESCRIPTION","REQUESTCATEGORY"): print(f["name"], [c["code"] for c in f["domain"]["codedValues"]])
print("== cityworks status x inspcomplete (date + desc)")
W="DESCRIPTION IN ('ROADWAY REPAIR','POTHOLES','STREET REPAVING','STREET REPAIR','STREET PAVING SCHEDU') AND INITIATEDDATE >= timestamp '2025-10-01 00:00:00'"
grp(C,"STATUS,INSPECTIONCOMPLETE",W)
print("== cityworks desc (date)")
grp(C,"DESCRIPTION,REQUESTCATEGORY","INITIATEDDATE >= timestamp '2025-10-01 00:00:00' AND REQUESTCATEGORY LIKE '%ROAD%'")
