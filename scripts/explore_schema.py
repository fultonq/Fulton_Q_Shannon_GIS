import json, urllib.request, urllib.parse, sys
URLS = {
 "permits": "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/DDOT_TOPS/MapServer/23",
 "subblock": "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/162",
 "cityworks": "https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/Cityworks/MapServer/1",
}
def get(url, **p):
    p["f"]="json"
    with urllib.request.urlopen(url+"?"+urllib.parse.urlencode(p), timeout=120) as r:
        return json.load(r)
for k,u in URLS.items():
    m=get(u)
    print("=====",k,m.get("name"),m.get("geometryType"),"maxRec",m.get("maxRecordCount"),"sr",m.get("extent",{}).get("spatialReference"))
    print("  count:", get(u+"/query", where="1=1", returnCountOnly="true"))
    for f in m["fields"]:
        print("   ",f["name"],f["type"],f.get("length",""), "domain" if f.get("domain") else "")
