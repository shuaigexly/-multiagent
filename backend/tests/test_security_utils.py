import asyncio

import pytest
from cryptography.fernet import Fernet

from app.core.settings import settings
from app.core.text_utils import truncate_with_marker
from app.feishu import token_crypto


def test_truncate_with_marker_marks_truncated_text():
    text = "A" * 50

    result = truncate_with_marker(text, 20, "...cut")

    assert result.endswith("...cut")
    assert len(result) <= 20


def test_token_encryption_requires_key_by_default(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_ALLOW_PLAINTEXT", raising=False)
    monkeypatch.setattr(settings, "token_encryption_key", "")
    token_crypto.reset_fernet_cache()

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        token_crypto.encrypt_token("secret-token")


def test_token_encryption_allows_plaintext_only_when_explicit(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_ALLOW_PLAINTEXT", "1")
    monkeypatch.setattr(settings, "token_encryption_key", "")
    token_crypto.reset_fernet_cache()

    assert token_crypto.encrypt_token("secret-token") == "secret-token"
    assert token_crypto.decrypt_token("secret-token") == "secret-token"


def test_token_encryption_round_trips_with_fernet_key(monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_ALLOW_PLAINTEXT", raising=False)
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode("ascii"))
    token_crypto.reset_fernet_cache()

    encrypted = token_crypto.encrypt_token("secret-token")

    assert encrypted != "secret-token"
    assert token_crypto.decrypt_token(encrypted) == "secret-token"


@pytest.mark.asyncio
async def test_workflow_lock_requires_redis_in_production(monkeypatch):
    import builtins
    from app.bitable_workflow import scheduler

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "redis.asyncio":
            raise RuntimeError("redis unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("WORKFLOW_ALLOW_LOCAL_LOCK", raising=False)
    monkeypatch.setattr(scheduler, "_ALLOW_LOCAL_WORKFLOW_LOCK", False)
    monkeypatch.setattr(scheduler, "_LOCAL_CYCLE_LOCK", None)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="Redis workflow lock is required"):
        await scheduler._acquire_cycle_lock("app", "tbl")

    assert scheduler._LOCAL_CYCLE_LOCK is not None
    assert not scheduler._LOCAL_CYCLE_LOCK.locked()


@pytest.mark.asyncio
async def test_workflow_lock_renewal_extends_owned_lock(monkeypatch):
    from app.bitable_workflow import scheduler

    class FakeRedis:
        def __init__(self):
            self.expired = []

        async def get(self, key):
            return "owner"

        async def expire(self, key, ttl):
            self.expired.append((key, ttl))

    calls = 0

    async def fake_sleep(_seconds):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError()

    client = FakeRedis()
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "_LOCK_TTL_SECONDS", 90)

    with pytest.raises(asyncio.CancelledError):
        await scheduler._renew_cycle_lock(client, "owner", "app", "tbl")

    assert client.expired == [("workflow:cycle-lock:app:tbl", 90)]


@pytest.mark.asyncio
async def test_collect_prior_task_output_ids_uses_existing_records(monkeypatch):
    from app.bitable_workflow import workflow_agents

    calls = []

    async def fake_list_records(app_token, table_id, filter_expr=None, max_records=500, **kwargs):
        calls.append((app_token, table_id, filter_expr, max_records))
        if table_id == "tbl_output":
            return [{"record_id": "out_1"}, {"record_id": ""}, {}]
        if table_id == "tbl_report":
            return [{"record_id": "report_1"}]
        return []

    monkeypatch.setattr(workflow_agents.bitable_ops, "list_records", fake_list_records)

    prior = await workflow_agents.collect_prior_task_output_ids(
        "app_token",
        "Task A",
        "tbl_output",
        "tbl_report",
    )

    assert prior == {"output": ["out_1"], "report": ["report_1"]}
    assert [call[1] for call in calls] == ["tbl_output", "tbl_report"]
    assert all(call[3] == 500 for call in calls)


@pytest.mark.asyncio
async def test_cleanup_prior_task_output_ids_deletes_collected_records(monkeypatch):
    from app.bitable_workflow import workflow_agents

    deleted = []

    async def fake_delete_record(app_token, table_id, record_id):
        deleted.append((app_token, table_id, record_id))

    monkeypatch.setattr(workflow_agents.bitable_ops, "delete_record", fake_delete_record)

    await workflow_agents.cleanup_prior_task_output_ids(
        "app_token",
        "tbl_output",
        "tbl_report",
        {"output": ["out_1", "out_2"], "report": ["report_1"]},
    )

    assert deleted == [
        ("app_token", "tbl_output", "out_1"),
        ("app_token", "tbl_output", "out_2"),
        ("app_token", "tbl_report", "report_1"),
    ]


@pytest.mark.asyncio
async def test_unsafe_prior_output_cleanup_entrypoint_is_disabled():
    from app.bitable_workflow import workflow_agents

    with pytest.raises(RuntimeError, match="unsafe"):
        await workflow_agents.cleanup_prior_task_outputs(
            "app_token",
            "Task A",
            "tbl_output",
            "tbl_report",
        )
