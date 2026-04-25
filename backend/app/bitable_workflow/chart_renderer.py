"""Chart 自动渲染 — chart_data JSON → matplotlib PNG → 飞书云空间 → Bitable 附件字段。

调用链：
  workflow_agents.write_agent_outputs
    → render_chart_to_png(chart_data) [matplotlib bar/line]
    → upload_to_drive(png_bytes) [飞书云空间 / temp file]
    → 返回 file_token
    → record fields 写 {"图表": [{"file_token": ...}]}

降级：matplotlib 不可用 / 上传失败 → 返回 None，调用方继续以文本字段写 chart_data JSON。
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
from typing import Any, Optional

import httpx

from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token

logger = logging.getLogger(__name__)


def _safe_label(s: Any) -> str:
    return str(s) if s is not None else ""


def render_chart_to_png(chart_data: list[dict], title: str = "") -> Optional[bytes]:
    """把 chart_data 数组渲染为 PNG bytes。

    chart_data 结构兼容：
      [{"name": "MAU", "value": 10, "unit": "万"}, ...]   → 柱状图
      [{"name": "...", "value": ..., "unit": "..."}, ...] (>=2 项 + value 全数值)

    matplotlib 缺失时返回 None。
    """
    if not chart_data or not isinstance(chart_data, list):
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless backend
        import matplotlib.pyplot as plt
    except ImportError:
        logger.debug("matplotlib not installed, skipping chart render")
        return None

    # 用 DejaVu Sans 兜底中文（matplotlib 默认无中文，会出豆腐）
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial Unicode MS", "Microsoft YaHei", "SimHei"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    names: list[str] = []
    values: list[float] = []
    units: list[str] = []
    for item in chart_data[:12]:  # 最多 12 列，避免过宽
        if not isinstance(item, dict):
            continue
        try:
            v = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        names.append(_safe_label(item.get("name"))[:18])
        values.append(v)
        units.append(_safe_label(item.get("unit")))

    if len(names) < 2:
        return None  # 1 个数据点不画图

    try:
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
        bars = ax.bar(names, values, color="#5B8DEF")
        ax.set_title(title or "Agent Metrics", fontsize=12, pad=10)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(axis="x", labelrotation=20)
        # 在柱子顶部标注单位
        for bar, val, unit in zip(bars, values, units):
            label = f"{val:g}{unit}" if unit else f"{val:g}"
            ax.annotate(
                label,
                xy=(bar.get_x() + bar.get_width() / 2, val),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center", va="bottom",
                fontsize=9,
            )
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        logger.warning("chart render failed: %s", exc)
        return None


async def upload_chart_to_bitable(
    app_token: str,
    table_id: str,
    png_bytes: bytes,
    file_name: str = "chart.png",
) -> Optional[str]:
    """把 PNG 上传为 Bitable 附件，返回 file_token；失败返回 None。

    使用飞书 `drive/v1/medias/upload_all` 接口（multipart/form-data，parent_type=bitable_image）。
    """
    if not png_bytes:
        return None
    try:
        token = await get_tenant_access_token()
    except Exception as exc:
        logger.warning("chart upload skipped: feishu auth failed: %s", exc)
        return None

    base = get_feishu_open_base_url()
    url = f"{base}/open-apis/drive/v1/medias/upload_all"

    # 写入临时文件以便 multipart 上传
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf:
            tf.write(png_bytes)
            tmp_path = tf.name

        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(tmp_path, "rb") as fh:
                files = {"file": (file_name, fh, "image/png")}
                data = {
                    "file_name": file_name,
                    "parent_type": "bitable_image",
                    "parent_node": app_token,
                    "size": str(len(png_bytes)),
                    "extra": f'{{"bitablePerm":{{"tableId":"{table_id}","attachmentFieldId":""}}}}',
                }
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    files=files,
                    data=data,
                )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 0:
            logger.warning("chart upload non-zero: code=%s msg=%s", body.get("code"), body.get("msg"))
            return None
        return body.get("data", {}).get("file_token")
    except Exception as exc:
        logger.warning("chart upload exception: %s", exc)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
