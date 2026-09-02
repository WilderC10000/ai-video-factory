IDEA = "He converted an enormous concrete pipe into a hidden luxury home."


def test_create_and_fetch_project(client):
    resp = client.post("/projects", json={"idea_text": IDEA})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "IDEA"
    project_id = body["id"]

    resp = client.get(f"/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["idea_text"] == IDEA


def test_create_rejects_empty_idea(client):
    resp = client.post("/projects", json={"idea_text": "   "})
    assert resp.status_code == 422


def test_full_pipeline_via_api(client):
    project_id = client.post("/projects", json={"idea_text": IDEA}).json()["id"]

    resp = client.post(f"/projects/{project_id}/concept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CONCEPT_APPROVED"

    resp = client.post(f"/projects/{project_id}/script")
    assert resp.status_code == 200
    assert resp.json()["status"] == "SCRIPT_READY"

    resp = client.post(f"/projects/{project_id}/storyboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "STORYBOARD_READY"
    assert len(body["shots"]) >= 10
    assert body["total_cost_usd"] == 0.0


def test_out_of_order_transition_returns_conflict(client):
    project_id = client.post("/projects", json={"idea_text": IDEA}).json()["id"]

    resp = client.post(f"/projects/{project_id}/script")
    assert resp.status_code == 409


def test_unknown_project_returns_404(client):
    resp = client.get("/projects/does-not-exist")
    assert resp.status_code == 404


def test_list_projects(client):
    client.post("/projects", json={"idea_text": IDEA})
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
