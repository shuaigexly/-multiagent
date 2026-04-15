from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
