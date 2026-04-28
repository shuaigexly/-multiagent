"""飞书 OAuth token 的静态加密/解密。"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import settings

logger = logging.getLogger(__name__)
# v8.6.20-r11（审计 #5）：缓存同时记住 key 字串，settings.token_encryption_key 在
# 运行时被改写时自动失效旧 Fernet 实例，避免「旧 key 加密、新 key 解密 → 全失败」。
# (Fernet | None, key_str) 元组；初值用 _UNSET 哨兵区分 "从未初始化" 与 "已知 None"
_UNSET = object()
_fernet_cache: tuple[object, str] = (_UNSET, "")


def _requires_token_encryption() -> bool:
    if os.getenv("TOKEN_ENCRYPTION_ALLOW_PLAINTEXT", "").lower() in {"1", "true", "yes"}:
        return False
    return True


def _get_fernet() -> Fernet | None:
    global _fernet_cache
    key = settings.token_encryption_key.strip()
    cached_obj, cached_key = _fernet_cache
    if cached_obj is not _UNSET and cached_key == key:
        return cached_obj  # type: ignore[return-value]

    if not key:
        if _requires_token_encryption():
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required to store OAuth tokens")
        _fernet_cache = (None, key)
        return None
    try:
        instance = Fernet(key.encode())
        _fernet_cache = (instance, key)
        return instance
    except Exception as exc:
        if _requires_token_encryption():
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is invalid") from exc
        logger.warning("TOKEN_ENCRYPTION_KEY 无效，已按显式配置回退为明文 token")
        _fernet_cache = (None, key)
        return None


def reset_fernet_cache() -> None:
    """Force re-read settings.token_encryption_key on next encrypt/decrypt call."""
    global _fernet_cache
    _fernet_cache = (_UNSET, "")


def encrypt_token(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    fernet = _get_fernet()
    if fernet is None:
        return plaintext
    try:
        return fernet.encrypt(plaintext.encode()).decode()
    except Exception as exc:
        if _requires_token_encryption():
            raise RuntimeError("Token encryption failed") from exc
        logger.warning("Token 加密失败，已按显式配置回退为原样存储")
        return plaintext


def decrypt_token(stored: str) -> str:
    if not stored:
        return stored
    fernet = _get_fernet()
    if fernet is None:
        return stored
    try:
        return fernet.decrypt(stored.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as exc:
        if _requires_token_encryption():
            raise RuntimeError("Token decryption failed") from exc
        logger.warning("Token 解密失败，已按显式配置回退为原样使用")
        return stored
    except Exception as exc:
        if _requires_token_encryption():
            raise RuntimeError("Token decryption failed") from exc
        logger.warning("Token 解密异常，已按显式配置回退为原样使用")
        return stored
