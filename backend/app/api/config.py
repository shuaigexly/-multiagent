"""运行时配置 API"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from fastapi import APIRouter, Depends
from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.redaction import redact_sensitive_text
from app.core.settings import (
    apply_db_config,
    get_feishu_app_id,
    get_feishu_app_secret,
    get_feishu_bot_encrypt_key,
    get_feishu_bot_verification_token,
    get_feishu_region,
    get_llm_api_key,
    get_llm_base_url,
    get_llm_model,
    get_llm_provider,
)
from app.feishu.client import reset_feishu_client
from app.models.database import UserConfig, get_db

router = APIRouter(prefix="/api/v1/config", tags=["config"])

CONFIG_KEYS = (
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "llm_provider",
    "feishu_app_id",
    "feishu_app_secret",
    "feishu_region",
    "feishu_bot_verification_token",
    "feishu_bot_encrypt_key",
)
SECRET_KEYS = {
    "llm_api_key",
    "feishu_app_secret",
    "feishu_bot_verification_token",
    "feishu_bot_encrypt_key",
}
FEISHU_RUNTIME_KEYS = {"feishu_app_id", "feishu_app_secret", "feishu_region"}
CONFIG_GETTERS = {
    "llm_api_key": get_llm_api_key,
    "llm_base_url": get_llm_base_url,
    "llm_model": get_llm_model,
    "llm_provider": get_llm_provider,
    "feishu_app_id": get_feishu_app_id,
    "feishu_app_secret": get_feishu_app_secret,
    "feishu_region": get_feishu_region,
    "feishu_bot_verification_token": get_feishu_bot_verification_token,
    "feishu_bot_encrypt_key": get_feishu_bot_encrypt_key,
}


def _normalize_key(value: str) -> str:
    if value not in CONFIG_KEYS:
        raise ValueError(f"不支持的配置项: {value}")
    return value


def _normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-3:]}"


class ConfigStatus(BaseModel):
    set: bool
    value: str | None


class ConfigItem(BaseModel):
    key: str
    value: str | None = None

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _normalize_key(value)


class SaveConfigRequest(BaseModel):
    key: str | None = None
    value: str | None = None
    configs: list[ConfigItem] | None = None

    @field_validator("key")
    @classmethod
    def validate_optional_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_key(value)

    @model_validator(mode="after")
    def validate_payload(self):
        if self.configs:
            if self.key is not None or self.value is not None:
                raise ValueError("single 与 batch 保存方式不能同时使用")
            return self
        if self.key is None:
            raise ValueError("缺少 key 或 configs")
        return self

    def items(self) -> list[ConfigItem]:
        if self.configs:
            return self.configs
        return [ConfigItem(key=self.key or "", value=self.value)]


class LLMTestRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class FeishuTestRequest(BaseModel):
    app_id: str | None = None
    app_secret: str | None = None
    region: Literal["cn", "intl"] | None = None


async def _upsert_configs(db: AsyncSession, items: Iterable[ConfigItem]) -> dict[str, str | None]:
    normalized_map = {item.key: _normalize_value(item.value) for item in items}
    normalized_items = list(normalized_map.items())
    if not normalized_items:
        return {}
    keys = [key for key, _ in normalized_items]
    existing_rows = await db.execute(select(UserConfig).where(UserConfig.key.in_(keys)))
    existing = {row.key: row for row in existing_rows.scalars().all()}

    applied: dict[str, str | None] = {}
    for key, value in normalized_items:
        row = existing.get(key)
        if row is None:
            db.add(UserConfig(key=key, value=value))
        else:
            row.value = value
        applied[key] = value

    await db.commit()
    return applied


async def _test_feishu_credentials(app_id: str, app_secret: str, region: str):
    region = region.strip().lower()
    if region == "intl":
        try:
            import larksuite_oapi as lark
            from larksuite_oapi.api.auth.v3 import (
                InternalTenantAccessTokenRequest,
                InternalTenantAccessTokenRequestBody,
            )
        except ImportError as exc:
            raise RuntimeError(
                "FEISHU_REGION=intl 需要安装国际版 SDK：pip install larksuite-oapi"
            ) from exc
    else:
        import lark_oapi as lark
        from lark_oapi.api.auth.v3 import (
            InternalTenantAccessTokenRequest,
            InternalTenantAccessTokenRequestBody,
        )

    client = (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )
    request = (
        InternalTenantAccessTokenRequest.builder()
        .request_body(
            InternalTenantAccessTokenRequestBody.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )
        .build()
    )
    response = await client.auth.v3.tenant_access_token.ainternal(request)
    if response.code != 0:
        raise RuntimeError(response.msg or "获取 tenant_access_token 失败")


@router.get("", response_model=dict[str, ConfigStatus], dependencies=[Depends(require_api_key)])
async def get_config_status():
    payload: dict[str, ConfigStatus] = {}
    for key in CONFIG_KEYS:
        value = CONFIG_GETTERS[key]()
        display_value = _mask_secret(value) if key in SECRET_KEYS else (value or None)
        payload[key] = ConfigStatus(set=bool(value), value=display_value)
    return payload


@router.post("", dependencies=[Depends(require_api_key)])
async def save_config(
    body: SaveConfigRequest,
    db: AsyncSession = Depends(get_db),
):
    applied = await _upsert_configs(db, body.items())
    apply_db_config(applied)
    if any(key in FEISHU_RUNTIME_KEYS for key in applied):
        reset_feishu_client()
    return {"ok": True, "saved": list(applied.keys())}


@router.post("/test-llm", dependencies=[Depends(require_api_key)])
async def test_llm(body: LLMTestRequest):
    requested_base_url = _normalize_value(body.base_url)
    requested_api_key = _normalize_value(body.api_key)
    if requested_base_url and not requested_api_key:
        stored_base = get_llm_base_url()
        if requested_base_url != stored_base:
            return {"ok": False, "message": "自定义 base_url 时必须同时提供 api_key"}

    api_key = requested_api_key or get_llm_api_key()
    base_url = requested_base_url or get_llm_base_url()
    model = _normalize_value(body.model) or get_llm_model()

    if not api_key:
        return {"ok": False, "message": "缺少 LLM API Key"}
    if not base_url:
        return {"ok": False, "message": "缺少 LLM Base URL"}
    if not model:
        return {"ok": False, "message": "缺少 LLM Model"}

    client = None
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "reply with: ok"}],
            temperature=0,
            max_tokens=16,
        )
        content = (response.choices[0].message.content or "").strip()
        if "ok" not in content.lower():
            return {"ok": False, "message": f"模型返回异常: {content or '[空响应]'}"}
        return {"ok": True, "message": "连接成功"}
    except Exception as exc:
        return {"ok": False, "message": redact_sensitive_text(exc, max_chars=500)}
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass


@router.post("/test-feishu", dependencies=[Depends(require_api_key)])
async def test_feishu(body: FeishuTestRequest):
    app_id = _normalize_value(body.app_id) or get_feishu_app_id()
    app_secret = _normalize_value(body.app_secret) or get_feishu_app_secret()
    region = (_normalize_value(body.region) or get_feishu_region() or "cn").lower()

    if not app_id:
        return {"ok": False, "message": "缺少飞书 App ID"}
    if not app_secret:
        return {"ok": False, "message": "缺少飞书 App Secret"}

    try:
        await _test_feishu_credentials(app_id, app_secret, region)
        return {"ok": True, "message": "飞书连接成功"}
    except Exception as exc:
        return {"ok": False, "message": redact_sensitive_text(exc, max_chars=500)}


@router.post("/test-bot", dependencies=[Depends(require_api_key)])
async def test_bot():
    try:
        verification_token = get_feishu_bot_verification_token()
        encrypt_key = get_feishu_bot_encrypt_key()

        if encrypt_key:
            from lark_oapi.core.utils import AESCipher

            AESCipher(encrypt_key)

        config_summary: list[str] = []
        if verification_token:
            config_summary.append("Verification Token ✓")
        else:
            config_summary.append("Verification Token 未设置（开发模式）")
        if encrypt_key:
            config_summary.append("Encrypt Key ✓")
        else:
            config_summary.append("Encrypt Key 未设置（明文模式）")

        return {
            "ok": True,
            "message": "Bot 配置正常：" + "，".join(config_summary),
        }
    except Exception as exc:
        return {"ok": False, "message": f"Bot 配置异常: {redact_sensitive_text(exc, max_chars=200)}"}
