from fastapi.testclient import TestClient

from app.web.server import app

client = TestClient(app)


def test_page_and_assets_are_served():
    assert "ELV Value Recovery Planner" in client.get("/").text
    for f in ("app.js", "styles.css"):
        assert client.get(f"/static/{f}").status_code == 200


def test_month_matches_the_agent_tool():
    m = client.get("/api/month").json()
    assert len(m["vehicles"]) == 12 and m["month"]["blocked_before_dismantling"] == ["V04", "V07"]


def test_vehicle_pack():
    p = client.get("/api/vehicles/v5").json()
    assert p["vehicle_id"] == "V05" and p["value"]["offer"] == 41984
    assert any("STR-03" in i for i in p["open_items"])


def test_unknown_vehicle_is_404():
    assert client.get("/api/vehicles/V99").status_code == 404


def test_what_if_validates_input():
    assert client.get("/api/what-if", params={"capacity_minutes": 620}).json()["minutes_used"] <= 620
    assert client.get("/api/what-if", params={"capacity_minutes": -5}).status_code == 422


def test_api_is_read_only():
    for path in ("/api/month", "/api/vehicles/V05", "/api/review-queue"):
        assert client.post(path).status_code == 405
