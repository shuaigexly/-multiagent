from pathlib import Path


def test_get_int_env_falls_back_for_invalid_values(monkeypatch):
    from app.core.env import get_int_env

    monkeypatch.delenv("TEST_INT_ENV", raising=False)
    assert get_int_env("TEST_INT_ENV", 10, minimum=1) == 10

    monkeypatch.setenv("TEST_INT_ENV", "bad")
    assert get_int_env("TEST_INT_ENV", 10, minimum=1) == 10

    monkeypatch.setenv("TEST_INT_ENV", "0")
    assert get_int_env("TEST_INT_ENV", 10, minimum=1) == 10

    monkeypatch.setenv("TEST_INT_ENV", "25")
    assert get_int_env("TEST_INT_ENV", 10, minimum=1, maximum=20) == 10

    monkeypatch.setenv("TEST_INT_ENV", "15")
    assert get_int_env("TEST_INT_ENV", 10, minimum=1, maximum=20) == 15


def test_app_code_uses_safe_integer_env_parser():
    app_root = Path(__file__).resolve().parents[1] / "app"

    offenders = []
    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "int(os.getenv" in text or "float(os.getenv" in text:
            offenders.append(str(path.relative_to(app_root)))

    assert offenders == []
