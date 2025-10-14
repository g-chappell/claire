# apps/backend/tests/test_plan_get_post.py
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_plan_then_get():
    r = c.post("/runs", json={
        "title":"Plan E2E","requirement_title":"As a user, I can see health",
        "requirement_description":"Expose /health returning {status: ok}"
    })
    run_id = r.json()["run_id"]

    p1 = c.post(f"/runs/{run_id}/plan")
    assert p1.status_code == 200
    p2 = c.get(f"/runs/{run_id}/plan")
    assert p2.status_code == 200
    assert p1.json()["stories"] and p2.json()["stories"]
