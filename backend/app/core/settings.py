from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Feishu
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_chat_id: str = ""          # 默认推送群

    # Database
    database_url: str = "sqlite+aiosqlite:///./data.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MetaGPT
    metagpt_budget: float = 3.0
    metagpt_rounds: int = 5

    # Upload
    upload_dir: str = "./uploads"


settings = Settings()
