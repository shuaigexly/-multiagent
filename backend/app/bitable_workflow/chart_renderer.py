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


def _draw_bar_group(ax, names: list[str], values: list[float], units: list[str], title: str) -> None:
    """绘一组柱状图到 ax 上，含单位标注。"""
    bars = ax.bar(names, values, color="#5B8DEF")
    ax.set_title(title, fontsize=11, pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", labelrotation=20, labelsize=9)
    for bar, val, unit in zip(bars, values, units):
        label = f"{val:g}{unit}" if unit else f"{val:g}"
        ax.annotate(
            label,
            xy=(bar.get_x() + bar.get_width() / 2, val),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center", va="bottom",
            fontsize=8,
        )


def render_chart_to_png(chart_data: list[dict], title: str = "") -> Optional[bytes]:
    """把 chart_data 数组渲染为 PNG bytes。

    chart_data 结构兼容：
      [{"name": "MAU", "value": 10, "unit": "万"}, ...]   → 柱状图
      [{"name": "...", "value": ..., "unit": "..."}, ...] (>=2 项 + value 全数值)

    matplotlib 缺失时返回 None。
    """
    if not chart_data or not isinstance(chart_data, list):
        return None
    fig = None
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless backend
        import matplotlib.pyplot as plt
    except ImportError:
        logger.debug("matplotlib not installed, skipping chart render")
        return None

    # v8.6.3 修复中文字体缺失：DejaVu Sans 不支持中文（之前柱状图标签被替换成豆腐方框）。
    # 优先使用系统真实可用的中文字体，按 Windows / macOS / Linux 常见字体顺序探测。
    # matplotlib 找不到字体也不会抛错（warning 后用 fallback），所以排序从最常见到最少见。
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",       # Windows 默认
        "SimHei",                 # Windows 黑体
        "PingFang SC",           # macOS 默认
        "Hiragino Sans GB",      # macOS 备用
        "Noto Sans CJK SC",      # Linux 默认
        "WenQuanYi Micro Hei",   # Linux 文泉驿
        "Source Han Sans CN",    # 思源黑体
        "Arial Unicode MS",      # 通用 Unicode
        "DejaVu Sans",           # 最后兜底
    ]
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

    # v8.6.3 修量纲混杂：MAU=11.2万、留存=38%、LTV=212元 用同一 Y 轴 → 大值一柱独大
    # v8.6.9 修单柱独占：之前 2-4 组不同 unit 时拆成多子图，但每组 <2 项时
    # 子图就是"一根柱占满整宽"，丑且信息量低（数据分析师/财务顾问 都中招）。
    # 现在改逻辑：
    #   · 所有数据点同 unit  → 单图（最常见，最好看）
    #   · 多 unit 但每组都 ≥ 2 项 → 子图（每组本身有比较意义）
    #   · 否则                → 单图 + 组内归一化（柱高 = 组内占比%，标签保留原值）
    from collections import defaultdict
    groups: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for n, v, u in zip(names, values, units):
        groups[u or "无单位"].append((n, v, u))

    multi_subplot_ok = (
        2 <= len(groups) <= 4
        and all(len(items) >= 2 for items in groups.values())
    )

    try:
        if len(groups) <= 1:
            # 单一量纲：单子图
            fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
            _draw_bar_group(ax, names, values, units, title or "关键指标")
        elif multi_subplot_ok:
            # 2-4 组量纲且每组都 ≥ 2 项：纵向多子图（每子图本身有横向对比）
            fig, axes = plt.subplots(
                len(groups), 1,
                figsize=(8, 2.4 * len(groups)),
                dpi=110,
                squeeze=False,
            )
            fig.suptitle(title or "关键指标", fontsize=12)
            for ax, (unit_key, items) in zip(axes.flatten(), groups.items()):
                ns = [it[0] for it in items]
                vs = [it[1] for it in items]
                us = [it[2] for it in items]
                _draw_bar_group(ax, ns, vs, us, f"按 {unit_key} 分组")
        else:
            # 多 unit 但有 group 只有 1 项 — 单图 + 组内归一化
            normalized = []
            for n, v, u in zip(names, values, units):
                grp_max = max(it[1] for it in groups[u or "无单位"]) or 1
                normalized.append((n, v / grp_max * 100, f"{v:g}{u}"))
            fig, ax = plt.subplots(figsize=(9, 4.8), dpi=110)
            ax.bar([x[0] for x in normalized], [x[1] for x in normalized], color="#5B8DEF")
            ax.set_title((title or "关键指标") + "（组内归一化 %，柱标签为原值）")
            ax.set_ylabel("组内相对值 %")
            ax.set_ylim(0, 115)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.tick_params(axis="x", labelrotation=20, labelsize=9)
            for i, (n, v_norm, lbl) in enumerate(normalized):
                ax.annotate(lbl, xy=(i, v_norm), xytext=(0, 3), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        logger.warning("chart render failed: %s", exc)
        return None
    finally:
        if fig is not None:
            plt.close(fig)


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
