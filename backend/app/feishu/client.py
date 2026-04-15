"""飞书 lark-oapi 客户端封装"""
import logging
import lark_oapi as lark
from lark_oapi.api.auth.v3 import *
from app.core.settings import settings

logger = logging.getLogger(__name__)

_client: lark.Client | None = None


def get_feishu_client() -> lark.Client:
    global _client
    if _client is None:
        _client = (
            lark.Client.builder()
            .app_id(settings.feishu_app_id)
            .app_secret(settings.feishu_app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
    return _client
