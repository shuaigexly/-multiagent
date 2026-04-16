from pydantic_settings import BaseSettings, SettingsConfigDict


_OVERRIDABLE_FIELDS = {
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "llm_provider",
    "feishu_app_id",
    "feishu_app_secret",
    "feishu_region",
    "feishu_bot_verification_token",
    "feishu_bot_encrypt_key",
}
_db_overrides: dict[str, str | None] = {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # provider: openai_compatible | feishu_aily
    # openai_compatible = 任何兼容 OpenAI /chat/completions 接口的服务商
    # feishu_aily = 通过飞书 Aily 会话 API 调用（需企业开通飞书 AI）
    llm_provider: str = "openai_compatible"

    # Feishu / Lark
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_chat_id: str = ""          # 默认推送群
    # region: cn = 飞书中国版（open.feishu.cn，SDK: lark_oapi）
    #         intl = Lark 国际版（open.larksuite.com，SDK: larksuite_oapi）
    feishu_region: str = "cn"
    feishu_bot_verification_token: str = ""  # 飞书事件订阅验证 Token
    feishu_bot_encrypt_key: str = ""         # 飞书事件加密 Key（可选）
    token_encryption_key: str = ""           # OAuth token at-rest encryption key（可选）

    # Database
    database_url: str = "sqlite+aiosqlite:///./data.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MetaGPT
    metagpt_budget: float = 3.0
    metagpt_rounds: int = 5

    # Upload
    upload_dir: str = "./uploads"

    # Security
    api_key: str = ""
    allowed_origins: str = "http://localhost:5173"
    reflection_enabled: bool = True

    def __getattribute__(self, name: str):
        if name in _OVERRIDABLE_FIELDS:
            override = _db_overrides.get(name)
            if override:
                return override
        return super().__getattribute__(name)


settings = Settings()


def apply_db_config(overrides: dict[str, str | None]):
    for key, value in overrides.items():
        if key not in _OVERRIDABLE_FIELDS:
            continue
        normalized = value.strip() if isinstance(value, str) else value
        _db_overrides[key] = normalized or None


def get_llm_api_key() -> str:
    return _db_overrides.get("llm_api_key") or settings.llm_api_key


def get_llm_base_url() -> str:
    return _db_overrides.get("llm_base_url") or settings.llm_base_url


def get_llm_model() -> str:
    return _db_overrides.get("llm_model") or settings.llm_model


def get_llm_provider() -> str:
    return _db_overrides.get("llm_provider") or settings.llm_provider


def get_feishu_app_id() -> str:
    return _db_overrides.get("feishu_app_id") or settings.feishu_app_id


def get_feishu_app_secret() -> str:
    return _db_overrides.get("feishu_app_secret") or settings.feishu_app_secret


def get_feishu_region() -> str:
    return _db_overrides.get("feishu_region") or settings.feishu_region


def get_feishu_bot_verification_token() -> str:
    return _db_overrides.get("feishu_bot_verification_token") or settings.feishu_bot_verification_token


def get_feishu_bot_encrypt_key() -> str:
    return _db_overrides.get("feishu_bot_encrypt_key") or settings.feishu_bot_encrypt_key
