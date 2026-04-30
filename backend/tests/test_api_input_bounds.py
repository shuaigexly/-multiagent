from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


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
    assert client.post("/api/v1/tasks/%20%20/events-token").status_code == 400
    assert client.get("/api/v1/tasks/%20%20/events", params={"token": "token"}).status_code == 400
    assert client.post("/api/v1/workflow/stream-token/%20%20").status_code == 400
    assert client.get("/api/v1/workflow/stream/%20%20", params={"token": "token"}).status_code == 400

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


def test_task_confirm_payloads_are_bounded():
    from pydantic import ValidationError
    from app.models.schemas import PublishRequest, TaskConfirm, TaskCreate

    with pytest.raises(ValidationError):
        TaskConfirm(selected_modules=["data_analyst"] * 20)

    with pytest.raises(ValidationError):
        TaskConfirm(selected_modules=["data_analyst"], user_instructions="x" * 2001)

    with pytest.raises(ValidationError):
        TaskCreate(input_text="x" * 5001)

    with pytest.raises(ValidationError):
        PublishRequest(asset_types=["doc"] * 20)

    with pytest.raises(ValidationError):
        PublishRequest(asset_types=["doc"], chat_id="c" * 129)


def test_workflow_control_payloads_are_bounded():
    from pydantic import ValidationError
    from app.api.workflow import ApplyNativeRequest, ConfirmRequest, SeedRequest, SetupRequest, StartRequest

    with pytest.raises(ValidationError):
        SetupRequest(name=" " * 8)

    with pytest.raises(ValidationError):
        SetupRequest(name="x" * 121)

    with pytest.raises(ValidationError):
        StartRequest(
            app_token="app",
            table_ids={"task": "task", "report": "report", "performance": "perf"},
            interval=86401,
        )

    with pytest.raises(ValidationError):
        ApplyNativeRequest(surfaces=["workflow"] * 20)

    with pytest.raises(ValidationError):
        SeedRequest(app_token="abc", table_id="def", title="   ")

    with pytest.raises(ValidationError):
        StartRequest(
            app_token="app",
            table_ids={" task ": "   ", "report": "report", "performance": "perf"},
        )

    with pytest.raises(ValidationError):
        StartRequest(
            app_token="app",
            table_ids={" task ": "tbl_a", "task": "tbl_b", "report": "report", "performance": "perf"},
        )

    seed = SeedRequest(app_token=" app ", table_id=" tbl ", title=" 增长诊断 ")
    assert seed.app_token == "app"
    assert seed.table_id == "tbl"
    assert seed.title == "增长诊断"

    seed_with_optional_fields = SeedRequest(
        app_token="app",
        table_id="tbl",
        title="增长诊断",
        dimension=" 综合分析 ",
        background=" 背景 ",
        template=" 模板A ",
    )
    assert seed_with_optional_fields.dimension == "综合分析"
    assert seed_with_optional_fields.background == "背景"
    assert seed_with_optional_fields.template == "模板A"
    assert seed_with_optional_fields.template_name == "模板A"

    start = StartRequest(
        app_token=" app ",
        table_ids={" task ": " tbl_task ", "report": " tbl_report ", "performance": " tbl_perf "},
    )
    assert start.app_token == "app"
    assert start.table_ids == {"task": "tbl_task", "report": "tbl_report", "performance": "tbl_perf"}

    confirm = ConfirmRequest(app_token=" app ", table_id=" tbl ", record_id=" rec ", action=" approve ", actor=" CEO ")
    assert confirm.app_token == "app"
    assert confirm.table_id == "tbl"
    assert confirm.record_id == "rec"
    assert confirm.action == "approve"
    assert confirm.actor == "CEO"


@pytest.mark.asyncio
async def test_workflow_records_trims_query_values(monkeypatch):
    from app.api import workflow

    captured = {}

    async def fake_list_records(app_token, table_id, filter_expr=None):
        captured["app_token"] = app_token
        captured["table_id"] = table_id
        captured["filter_expr"] = filter_expr
        return [{"record_id": "rec_1"}]

    monkeypatch.setattr(workflow.bitable_ops, "list_records", fake_list_records)

    result = await workflow.workflow_records(" app ", " tbl ", " 待分析 ")

    assert result == {"count": 1, "records": [{"record_id": "rec_1"}]}
    assert captured["app_token"] == "app"
    assert captured["table_id"] == "tbl"
    assert "待分析" in captured["filter_expr"]


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
