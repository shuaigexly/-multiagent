from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_upload_path_resolution_is_scoped_to_upload_dir(tmp_path, monkeypatch):
    from app.api.tasks import _resolve_upload_file_path
    from app.core.settings import settings

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    inside_file = upload_dir / "inside.txt"
    outside_file = tmp_path / "outside.txt"
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

    assert _resolve_upload_file_path(str(inside_file)) == inside_file.resolve()
    assert _resolve_upload_file_path(str(outside_file)) is None
    assert _resolve_upload_file_path(str(upload_dir)) is None


@pytest.mark.asyncio
async def test_uploaded_file_is_removed_when_feishu_context_json_is_invalid(tmp_path, monkeypatch):
    from app.api import tasks
    from app.core.settings import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    class FakeUpload:
        filename = "data.csv"

        def __init__(self):
            self._chunks = [b"a,b\n1,2\n", b""]

        async def read(self, _size: int):
            return self._chunks.pop(0)

    request = SimpleNamespace(client=SimpleNamespace(host="upload-cleanup-test"))

    with pytest.raises(HTTPException) as exc:
        await tasks.create_task(
            request=request,
            input_text="analyze this",
            feishu_context="{bad json",
            file=FakeUpload(),
            db=SimpleNamespace(),
        )

    assert exc.value.status_code == 422
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_cleanup_refuses_paths_outside_upload_dir(tmp_path, monkeypatch):
    from app.api.tasks import _remove_upload_file
    from app.core.settings import settings

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    inside_file = upload_dir / "inside.txt"
    outside_file.write_text("keep", encoding="utf-8")
    inside_file.write_text("remove", encoding="utf-8")
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

    await _remove_upload_file(str(outside_file))
    await _remove_upload_file(str(inside_file))

    assert outside_file.exists()
    assert not inside_file.exists()
