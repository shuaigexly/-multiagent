"""飞书/Lark 客户端封装，支持国内版（lark_oapi）和国际版（larksuite_oapi）"""
import logging

from app.core.settings import (
    get_feishu_app_id,
    get_feishu_app_secret,
    get_feishu_region,
)

logger = logging.getLogger(__name__)

_client = None
_client_credentials = None
import threading as _threading
_client_lock = _threading.Lock()


def get_feishu_client():
    """
    根据 FEISHU_REGION 返回对应 SDK 客户端。
    cn  → lark_oapi.Client（飞书国内版，open.feishu.cn）
    intl → larksuite_oapi.Client（Lark 国际版，open.larksuite.com）

    v8.3 修复：懒初始化 race — 并发首次调用各自创建 lark Client，winner 之外的
    Client 持有的 connection pool 永不被关闭 → 资源泄漏。threading.Lock 双检守护。
    """
    global _client, _client_credentials

    region = get_feishu_region().strip().lower()
    app_id = get_feishu_app_id()
    app_secret = get_feishu_app_secret()
    credentials = (region, app_id, app_secret)

    if _client is not None and _client_credentials == credentials:
        return _client

    with _client_lock:
        # 双检：等锁的并发调用拿到锁后另一个可能已经构造完成
        if _client is not None and _client_credentials == credentials:
            return _client

        if region == "intl":
            try:
                import larksuite_oapi as lark_intl
                _client = (
                    lark_intl.Client.builder()
                    .app_id(app_id)
                    .app_secret(app_secret)
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
                .app_id(app_id)
                .app_secret(app_secret)
                .log_level(lark.LogLevel.WARNING)
                .build()
            )
            logger.info("Using Feishu China SDK (open.feishu.cn)")

        _client_credentials = credentials
        return _client


def reset_feishu_client():
    """测试用：重置客户端单例"""
    global _client, _client_credentials
    _client = None
    _client_credentials = None
    try:
        from app.feishu import aily

        aily._TOKEN_CACHE.clear()
    except Exception:
        pass


def get_feishu_base_url() -> str:
    """返回飞书/Lark 用户侧 URL 前缀（用于生成可被用户直接打开的文档、知识库链接）
    注意：open.feishu.cn 是 API 域名，用户侧访问需用 feishu.cn
    """
    region = get_feishu_region().strip().lower()
    return "https://larksuite.com" if region == "intl" else "https://feishu.cn"


def get_applink_base_url() -> str:
    """返回 AppLink URL 前缀（用于生成任务等 App 内跳转链接）"""
    region = get_feishu_region().strip().lower()
    return "https://applink.larksuite.com" if region == "intl" else "https://applink.feishu.cn"
