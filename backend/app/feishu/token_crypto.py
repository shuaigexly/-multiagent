"""飞书 OAuth token 的静态加密/解密。"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import settings

logger = logging.getLogger(__name__)
_fernet_cache: Fernet | None | bool = False


def _requires_token_encryption() -> bool:
    if os.getenv("TOKEN_ENCRYPTION_ALLOW_PLAINTEXT", "").lower() in {"1", "true", "yes"}:
        return False
    return True


def _get_fernet() -> Fernet | None:
    global _fernet_cache
    if _fernet_cache is not False:
        return _fernet_cache

    key = settings.token_encryption_key.strip()
    if not key:
        if _requires_token_encryption():
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required to store OAuth tokens")
        _fernet_cache = None
        return None
    try:
        _fernet_cache = Fernet(key.encode())
        return _fernet_cache
    except Exception as exc:
        if _requires_token_encryption():
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is invalid") from exc
        logger.warning("TOKEN_ENCRYPTION_KEY 无效，已按显式配置回退为明文 token")
        _fernet_cache = None
        return None


def reset_fernet_cache() -> None:
    """Call this after TOKEN_ENCRYPTION_KEY is changed at runtime."""
    global _fernet_cache
    _fernet_cache = False


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
