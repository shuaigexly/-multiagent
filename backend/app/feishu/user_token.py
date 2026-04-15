"""飞书用户 Token 内存缓存（user_access_token，用于需要用户级授权的 API）"""

_user_access_token: str | None = None
_user_open_id: str | None = None


def get_user_access_token() -> str | None:
    return _user_access_token


def set_user_access_token(token: str | None) -> None:
    global _user_access_token
    _user_access_token = token


def get_user_open_id() -> str | None:
    return _user_open_id


def set_user_open_id(open_id: str | None) -> None:
    global _user_open_id
    _user_open_id = open_id
