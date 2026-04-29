from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client_without_api_key(monkeypatch) -> TestClient:
    from app.api import feishu_context, feishu_oauth
    from app.core.settings import settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(settings, "api_key", "")

    app = FastAPI()
    app.include_router(feishu_context.router)
    app.include_router(feishu_oauth.router)
    return TestClient(app)


def test_feishu_context_path_and_query_ids_are_bounded(monkeypatch):
    client = _client_without_api_key(monkeypatch)
    long_id = "x" * 200

    assert client.get(f"/api/v1/feishu/wiki/nodes/{long_id}").status_code == 422
    assert client.get(f"/api/v1/feishu/chats/{long_id}/messages").status_code == 422
    assert client.get(f"/api/v1/feishu/doc/{long_id}/content").status_code == 422
    assert client.get("/api/v1/feishu/calendar", params={"start": "1" * 100}).status_code == 422


def test_feishu_oauth_query_ids_are_bounded(monkeypatch):
    client = _client_without_api_key(monkeypatch)
    long_id = "x" * 300

    assert client.get("/api/v1/feishu/oauth/url", params={"frontend_origin": "https://" + long_id}).status_code == 422
    assert client.get("/api/v1/feishu/oauth/list-bases", params={"folder_token": long_id}).status_code == 422
    assert client.get("/api/v1/feishu/oauth/list-tables", params={"app_token": long_id}).status_code == 422
    assert client.get("/api/v1/feishu/oauth/list-dashboards", params={"app_token": long_id}).status_code == 422
    assert client.post("/api/v1/feishu/oauth/apply-view-config", params={"app_token": long_id}).status_code == 422


def _task_and_stream_client_without_api_key(monkeypatch) -> TestClient:
    from app.api import events, feishu, results, tasks, workflow
    from app.core.settings import settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(settings, "api_key", "")

    app = FastAPI()
    app.include_router(tasks.router)
    app.include_router(events.router)
    app.include_router(results.router)
    app.include_router(feishu.router)
    app.include_router(workflow.router)
    return TestClient(app)


def test_task_and_stream_path_and_query_ids_are_bounded(monkeypatch):
    client = _task_and_stream_client_without_api_key(monkeypatch)
    long_id = "x" * 200
    long_token = "t" * 5000

    assert client.post(
        f"/api/v1/tasks/{long_id}/confirm",
        json={"selected_modules": ["data_analyst"]},
    ).status_code == 422
    assert client.get(f"/api/v1/tasks/{long_id}/status").status_code == 422
    assert client.delete(f"/api/v1/tasks/{long_id}").status_code == 422
    assert client.get(f"/api/v1/tasks/{long_id}/results").status_code == 422
    assert client.post(
        f"/api/v1/tasks/{long_id}/publish",
        json={"asset_types": ["doc"]},
    ).status_code == 422
    assert client.post(f"/api/v1/tasks/{long_id}/events-token").status_code == 422
    assert client.get(f"/api/v1/tasks/{long_id}/events").status_code == 422
    assert client.post(f"/api/v1/workflow/stream-token/{long_id}").status_code == 422
    assert client.get(f"/api/v1/workflow/stream/{long_id}").status_code == 422

    assert client.get("/api/v1/tasks", params={"search": "s" * 300}).status_code == 422
    assert client.get("/api/v1/tasks", params={"status": "s" * 80}).status_code == 422
    assert client.delete("/api/v1/tasks/task-id", params={"action": "x" * 40}).status_code == 422
    assert client.get("/api/v1/tasks/task-id/events", params={"token": long_token}).status_code == 422
    assert client.get("/api/v1/workflow/stream/task-id", params={"token": long_token}).status_code == 422
    assert client.post("/api/v1/feishu/tasks", json={"summary": "s" * 600}).status_code == 422
    assert client.post(
        "/api/v1/feishu/tasks",
        json={"summary": "ok", "source_task_id": long_id},
    ).status_code == 422


def test_config_request_values_are_bounded(monkeypatch):
    from app.api import config
    from app.core.settings import settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(settings, "api_key", "")

    app = FastAPI()
    app.include_router(config.router)
    client = TestClient(app)

    long_value = "x" * 5000
    too_many_configs = [{"key": "llm_model", "value": "model"} for _ in range(40)]

    assert client.post("/api/v1/config", json={"key": "llm_model", "value": long_value}).status_code == 422
    assert client.post("/api/v1/config", json={"configs": too_many_configs}).status_code == 422
    assert client.post("/api/v1/config/test-llm", json={"api_key": long_value}).status_code == 422
    assert client.post("/api/v1/config/test-llm", json={"base_url": "https://" + long_value}).status_code == 422
    assert client.post("/api/v1/config/test-llm", json={"model": "m" * 300}).status_code == 422
    assert client.post("/api/v1/config/test-feishu", json={"app_id": "a" * 200}).status_code == 422
    assert client.post("/api/v1/config/test-feishu", json={"app_secret": "s" * 600}).status_code == 422
