from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_plan_flow_returns_bundle():
    create = client.post("/runs", json={
        "title": "Run M1.2b",
        "requirement_title": "As a user, I can see health",
        "requirement_description": "Expose /health returning {status: ok}",
        "constraints": [],
        "priority": "Should",
        "non_functionals": []
    })
    assert create.status_code == 200
    run_id = create.json()["run_id"]

    # Plan
    resp = client.post(f"/runs/{run_id}/plan")
    assert resp.status_code == 200
    body = resp.json()

    # shape checks
    assert "product_vision" in body and "technical_solution" in body
    assert len(body["epics"]) >= 1
    assert len(body["stories"]) >= 1

    # fetch persisted version via GET
    get_resp = client.get(f"/runs/{run_id}/plan")
    assert get_resp.status_code == 200
    body2 = get_resp.json()
    assert len(body2["epics"]) >= 1
    assert len(body2["stories"]) >= 1
    # every story has some AC (coerced to list)
    assert all(isinstance(s.get("acceptance", []), list) for s in body2["stories"])
