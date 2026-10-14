import pytest


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    """Emulates an ArcGIS layer with ``n`` point features."""

    def __init__(self, n=5, max_records=2, drop_one=False, error=None):
        self.n, self.max_records, self.drop_one, self.error = n, max_records, drop_one, error
        self.calls = []

    def post(self, url, data, timeout):
        self.calls.append((url, dict(data)))
        if self.error:
            return FakeResponse({"error": {"code": 400, "message": self.error}})
        if not url.endswith("/query"):
            return FakeResponse({
                "name": "Fake", "geometryType": "esriGeometryPoint", "maxRecordCount": self.max_records,
                "fields": [
                    {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                    {"name": "ExpirationDate", "type": "esriFieldTypeDate"},
                    {"name": "Shape", "type": "esriFieldTypeGeometry"},
                ],
            })
        if data.get("returnIdsOnly") == "true":
            return FakeResponse({"objectIdFieldName": "OBJECTID", "objectIds": list(range(self.n, 0, -1))})
        ids = [int(i) for i in data["objectIds"].split(",")]
        if self.drop_one:
            ids = ids[:-1]
        return FakeResponse({
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": i,
                 "geometry": {"type": "Point", "coordinates": [-77.0 + i / 1000, 38.9]},
                 "properties": {"OBJECTID": i, "ExpirationDate": 1767225600000 if i % 2 else None}}
                for i in ids
            ],
        })


def test_fetch_batches_by_object_id_and_converts_dates(process):
    session = FakeSession(n=5, max_records=2)
    client = process.ArcGISClient(chunk_size=1000, session=session)
    gdf, info = client.fetch("https://x/MapServer/1", "1=1")

    batches = [c[1]["objectIds"] for c in session.calls if "objectIds" in c[1]]
    assert batches == ["1,2", "3,4", "5"]  # sorted, capped by maxRecordCount
    assert len(gdf) == 5 and gdf.crs.to_epsg() == 4326
    assert str(gdf["ExpirationDate"].dtype).startswith("datetime64") and "UTC" in str(gdf["ExpirationDate"].dtype)
    assert gdf["ExpirationDate"].isna().sum() == 2
    assert gdf.attrs["geometry_type"] == "Point"


def test_fetch_detects_short_batches(process):
    client = process.ArcGISClient(session=FakeSession(n=3, drop_one=True))
    with pytest.raises(process.ArcGISError, match="received"):
        client.fetch("https://x/MapServer/1", "1=1")


def test_server_error_payload_raises(process):
    client = process.ArcGISClient(session=FakeSession(error="Invalid query"))
    with pytest.raises(process.ArcGISError, match="Invalid query"):
        client.fetch("https://x/MapServer/1", "bad")


def test_empty_result_has_schema(process):
    client = process.ArcGISClient(session=FakeSession(n=0))
    gdf, _ = client.fetch("https://x/MapServer/1", "1=0")
    assert gdf.empty and {"OBJECTID", "ExpirationDate"} <= set(gdf.columns)


@pytest.mark.network
def test_live_services_respond_to_definition_queries(process):
    client = process.ArcGISClient(timeout=60, retries=2)
    f = process.Filters()
    for url, where in ((process.SUBBLOCKS_URL, process.subblock_where(f)),
                       (process.PERMITS_URL, process.permit_where(f)),
                       (process.CITYWORKS_URL, process.service_request_where(f))):
        assert client.object_ids(url, where), f"no features for {url}"
