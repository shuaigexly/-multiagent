"""一键导出 OpenAPI 3.x JSON spec（v8.6.20-r47）。

用法：
    cd backend && python -m scripts.export_openapi > openapi.json
    cd backend && python -m scripts.export_openapi --pretty --out ../docs/openapi.json

加 --pretty 输出人类可读 JSON（缩进 2）；--out 指定输出路径。

为什么需要：评审 / 第三方集成方拿到 spec 就能在 Swagger UI / Postman / curl 自助
探查全部 15 端点的入参 / 出参契约 — 不再需要翻 README 表格猜接口形态。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 把 backend/ 加到 path，让 app 模块可导入
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# v8.6.20-r47：spec dump 不该启动后台 lifespan / Redis / Bitable 真连接。临时
# 关掉这些副作用环境，让 import app 安全。
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:8000")
os.environ.setdefault("API_KEY", "spec-export-only")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI 3.x JSON spec")
    parser.add_argument("--out", help="输出文件路径；不传则写 stdout", default=None)
    parser.add_argument("--pretty", action="store_true", help="缩进 2 输出，便于人读")
    args = parser.parse_args()

    from app.main import app  # noqa: WPS433 (delayed import after env setup)

    spec = app.openapi()
    # 清理一些容易被误读的运行时字段
    for path_obj in spec.get("paths", {}).values():
        for method_obj in path_obj.values():
            if isinstance(method_obj, dict) and "operationId" in method_obj:
                # FastAPI 自动 operationId 含函数名，对外暴露给评审无害但偶尔过长，保留
                pass

    if args.pretty:
        text = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        text = json.dumps(spec, ensure_ascii=False)

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        endpoints = sum(len(p) for p in spec.get("paths", {}).values())
        sys.stderr.write(
            f"✓ Wrote OpenAPI spec to {out_path}\n"
            f"  paths: {len(spec.get('paths', {}))}\n"
            f"  operations: {endpoints}\n"
        )
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
