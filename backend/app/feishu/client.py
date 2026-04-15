"""飞书/Lark 客户端封装，支持国内版（lark_oapi）和国际版（larksuite_oapi）"""
import logging
from app.core.settings import settings

logger = logging.getLogger(__name__)

_client = None


def get_feishu_client():
    """
    根据 FEISHU_REGION 返回对应 SDK 客户端。
    cn  → lark_oapi.Client（飞书国内版，open.feishu.cn）
    intl → larksuite_oapi.Client（Lark 国际版，open.larksuite.com）
    """
    global _client
    if _client is not None:
        return _client

    region = settings.feishu_region.strip().lower()

    if region == "intl":
        try:
            import larksuite_oapi as lark_intl
            _client = (
                lark_intl.Client.builder()
                .app_id(settings.feishu_app_id)
                .app_secret(settings.feishu_app_secret)
                .log_level(lark_intl.LogLevel.WARNING)
                .build()
            )
            logger.info("Using Lark international SDK (open.larksuite.com)")
        except ImportError:
            raise RuntimeError(
                "FEISHU_REGION=intl 需要安装国际版 SDK：pip install larksuite-oapi"
            )
    else:
        # 默认 cn：飞书中国版
        import lark_oapi as lark
        _client = (
            lark.Client.builder()
            .app_id(settings.feishu_app_id)
            .app_secret(settings.feishu_app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        logger.info("Using Feishu China SDK (open.feishu.cn)")

    return _client


def reset_feishu_client():
    """测试用：重置客户端单例"""
    global _client
    _client = None


def get_feishu_base_url() -> str:
    """返回飞书/Lark 开放平台 URL 前缀（用于生成文档、知识库等链接）"""
    region = settings.feishu_region.strip().lower()
    return "https://open.larksuite.com" if region == "intl" else "https://open.feishu.cn"


def get_applink_base_url() -> str:
    """返回 AppLink URL 前缀（用于生成任务等 App 内跳转链接）"""
    region = settings.feishu_region.strip().lower()
    return "https://applink.larksuite.com" if region == "intl" else "https://applink.feishu.cn"
