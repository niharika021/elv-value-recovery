import pytest
from fastapi.testclient import TestClient

from app.elv_agent import tools
from app.web.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_decision_log():
    tools.STORE.path.unlink(missing_ok=True)
    yield
    tools.STORE.path.unlink(missing_ok=True)


def test_page_and_assets_are_served():
    page = client.get("/").text
    assert '<span class="brand-name">CoreYield</span>' in page and "<title>CoreYield" in page
    assert "ELV Value Recovery Planner" in page and "DEMO DATA" in page
    for view in ("overview", "inbox", "rules"):                 # three tabs; Ask opens from the corner button
        assert f'data-view="{view}"' in page and f'id="view-{view}"' in page
    assert 'data-view="ask"' not in page and 'id="view-ask"' in page and 'id="assistant-open"' in page
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


def test_inbox_lists_reviews_and_signable_vehicles():
    i = client.get("/api/inbox").json()
    assert {("V05", "STR-03"), ("V08", "ALT-08")} <= {(r["vehicle_id"], r["part_no"]) for r in i["reviews"]}
    assert {v["vehicle_id"] for v in i["ready_to_sign"]} == {"V01", "V09"}


def test_a_decision_is_recorded_and_changes_the_inbox():
    body = dict(engineer="Test Engineer", kind="part_review", vehicle_id="v08", action="accept",
                target="ALT-08", reason="spin test quiet after cleaning")
    r = client.post("/api/decisions", json=body)
    assert r.status_code == 201 and r.json()["decision"]["context"]["engine_verdict"] == "reuse"
    assert ("V08", "ALT-08") not in {(x["vehicle_id"], x["part_no"]) for x in client.get("/api/inbox").json()["reviews"]}
    assert client.get("/api/decisions").json()["count"] >= 1


def test_a_refused_decision_is_a_400_with_the_reason():
    r = client.post("/api/decisions", json=dict(engineer="T", kind="sign_off", vehicle_id="V05", action="sign"))
    assert r.status_code == 400 and "open item" in r.json()["detail"]
    r = client.post("/api/decisions", json=dict(engineer="", kind="part_review", vehicle_id="V05",
                                                action="accept", target="STR-03", reason="x"))
    assert r.status_code == 400


def test_health_is_served_at_both_paths():
    assert client.get("/health").json() == {"ok": True} and client.get("/api/health").json() == {"ok": True}


def test_firebase_hosting_config_serves_the_page_and_forwards_the_api():
    import json
    from pathlib import Path
    h = json.loads(Path("firebase.json").read_text())["hosting"]
    assert h["public"] == "app/web" and "**/*.py" in h["ignore"]                     # no server code published
    runs = {r["source"]: r["run"] for r in h["rewrites"] if "run" in r}
    assert runs["/api/**"] == {"serviceId": "coreyield", "region": "asia-south1"} and "/health" in runs
    assert {"source": "/", "destination": "/static/index.html"} in h["rewrites"]
    assert Path("app/web/static/index.html").exists()
    assert json.loads(Path(".firebaserc").read_text())["projects"]["default"] == "elv-value-recovery-2026"


def test_how_it_works_and_the_assistant_are_on_the_page():
    page = client.get("/").text
    assert 'class="how"' in page and "Engineer approves" in page and 'id="how-start"' in page
    assert 'id="assistant-open"' in page and 'id="assistant"' in page and 'id="drawer-slot"' in page
    assert page.count('id="chat-box"') == 1          # one conversation, shared by the Ask tab and the side panel
