"""飞书 OAuth token 的静态加密/解密。"""
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet | None:
    key = settings.token_encryption_key.strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        logger.warning("TOKEN_ENCRYPTION_KEY 无效，已禁用 token 加密")
        return None


def encrypt_token(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    fernet = _get_fernet()
    if fernet is None:
        return plaintext
    try:
        return fernet.encrypt(plaintext.encode()).decode()
    except Exception:
        logger.warning("Token 加密失败，已回退为原样存储")
        return plaintext


def decrypt_token(stored: str) -> str:
    if not stored:
        return stored
    fernet = _get_fernet()
    if fernet is None:
        return stored
    try:
        return fernet.decrypt(stored.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        logger.warning("Token 解密失败，已回退为原样使用")
        return stored
    except Exception:
        logger.warning("Token 解密异常，已回退为原样使用")
        return stored
