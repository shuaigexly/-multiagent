from fastapi import Header, HTTPException

from app.core.settings import settings


async def require_api_key(x_api_key: str = Header("", alias="X-API-Key")):
    """Simple API-key guard. Set API_KEY env var to enable; empty = dev mode (no auth)."""
    expected = settings.api_key
    if expected and x_api_key != expected:
        raise HTTPException(401, "Invalid API key")
