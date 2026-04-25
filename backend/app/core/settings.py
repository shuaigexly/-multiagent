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
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
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
    token_encryption_key: str = ""           # OAuth token at-rest encryption key（必填，除非显式允许明文）

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
    public_backend_origin: str = "http://localhost:8000"
    allowed_backend_origins: str = ""
    # Reflection（AutoGen 风格）默认关闭：每个 agent 分析会额外追加一次 LLM 评审调用，
    # 对 GLM-4-flash 等免费额度较紧的模型成本翻倍。生产环境默认关闭，必要时手动打开。
    reflection_enabled: bool = False

    # LLM 成本管控（0 表示不限制）
    daily_token_budget: int = 0          # 每个租户每日 token 上限
    per_task_token_budget: int = 0       # 单条任务 token 上限

    # v8.6.6 — 多维表格初始权限（默认 app 建的 base 别人完全打不开）
    feishu_base_owner_email: str = ""    # 用户邮箱，必须在飞书租户内才能反查成 open_id
    feishu_base_owner_mobile: str = ""   # 或手机号（最稳，飞书账号一定绑了手机）
    feishu_base_owner_open_id: str = ""  # 或直接填 open_id（首选，最不易出错）
    feishu_base_public_link_share: bool = False  # 是否开链接分享
    # link_share_entity: tenant_readable=组织内可查看 / anyone_readable=任何人凭链接可查看
    #                    tenant_editable / anyone_editable / closed
    feishu_base_link_share_entity: str = "anyone_readable"
    feishu_base_extra_viewers: str = ""  # 逗号分隔附加只读成员（邮箱/open_id）

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
