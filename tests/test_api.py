from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_health() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("backend.api.routes.run_pipeline")
def test_create_job_returns_queued_job(mock_run_pipeline) -> None:
    client = _client()
    response = client.post("/jobs", json={"topic": "Why EVs are popular"})

    assert response.status_code == 200
    body = response.json()
    assert body["topic"] == "Why EVs are popular"
    assert body["status"] == "queued"
    assert body["id"]


def test_create_job_rejects_empty_topic() -> None:
    client = _client()
    response = client.post("/jobs", json={"topic": "   "})
    assert response.status_code == 422


@patch("backend.api.routes.run_pipeline")
def test_get_job_roundtrip(mock_run_pipeline) -> None:
    client = _client()
    created = client.post("/jobs", json={"topic": "topic"}).json()

    fetched = client.get(f"/jobs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_get_missing_job_returns_404() -> None:
    client = _client()
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


def test_get_result_before_completion_returns_409() -> None:
    with patch("backend.api.routes.run_pipeline"):
        client = _client()
        created = client.post("/jobs", json={"topic": "topic"}).json()

    response = client.get(f"/jobs/{created['id']}/result")
    assert response.status_code == 409
