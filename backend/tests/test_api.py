from fastapi.testclient import TestClient

from app.main import app


def test_health_and_project_creation() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        response = client.post(
            "/api/v1/projects",
            json={"name": "Launch film", "width": 1280, "height": 720, "fps": 24},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["name"] == "Launch film"
        assert payload["clips"] == []


def test_project_validation_is_exposed_as_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/projects",
            json={"name": "", "width": 100, "height": 100, "fps": 100},
        )
        assert response.status_code == 422


def test_project_can_be_renamed_and_deleted() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "Working title", "description": "First draft", "width": 1280, "height": 720, "fps": 24},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        updated = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "Summer launch", "description": "Approved campaign"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Summer launch"
        assert updated.json()["description"] == "Approved campaign"

        listed = client.get("/api/v1/projects")
        assert listed.status_code == 200
        assert any(item["id"] == project_id and item["name"] == "Summer launch" for item in listed.json())

        deleted = client.delete(f"/api/v1/projects/{project_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 404


def test_project_update_rejects_an_empty_payload() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "Validation target", "width": 1280, "height": 720, "fps": 24},
        )
        project_id = created.json()["id"]
        assert client.patch(f"/api/v1/projects/{project_id}", json={}).status_code == 422
        assert client.delete(f"/api/v1/projects/{project_id}").status_code == 204

