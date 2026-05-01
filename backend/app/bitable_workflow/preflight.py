"""部署前置体检 — 在用户调 /setup 之前先把"配置正确性"摸一遍（v8.6.20-r37）。

为什么需要这个
==============
真实部署排错的痛点：用户配错 FEISHU_APP_ID 或 LLM_API_KEY，但是 /setup 流程要先
建 12 张表 + 视图 + 配置原生资产 + LLM 确认任务模板，跑到 LLM 这步才挂 — 中间
已经污染了一个空 base，要手动删掉重来。

preflight 在 30 秒内做四件事，给 ✅/❌ 列表：
  1. Feishu tenant_access_token 拿一次，确认 app_id/secret 配置生效
  2. LLM 用最便宜的 fast 档调一次最短 prompt，确认 base_url + key 能通
  3. Redis 探针（如果配了）— 确保分布式锁不会跑到一半假死
  4. 国内模型校验 — 拒绝 base_url 指向 openai/anthropic（竞赛一票否决项）

设计原则
========
- 每个 check 30s 超时，整体最多 30s 不超
- 任意 check 失败不影响其他 check 继续执行
- 永远返回 200（payload 里说 ok=True/False），让前端直接拿来渲染
- 不调用昂贵的 LLM 路径（fast 档 + 1 token 极简 prompt）
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from app.core.redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


# 竞赛一票否决项：禁止使用境外大模型
_FORBIDDEN_LLM_HOSTS = (
    "api.openai.com",
    "api.anthropic.com",
    "claude.ai",
    "openrouter.ai",  # 也算转发境外
)


@dataclass
class PreflightCheck:
    name: str
    label: str          # 中文展示用
    ok: bool = False
    detail: str = ""    # 简短失败原因 / 成功摘要
    elapsed_ms: int = 0
    advisory: str = ""  # 失败时给用户的建议（"去 .env 配 X"）


@dataclass
class PreflightReport:
    ok: bool = False                # 全部 check 都通过
    checks: list[PreflightCheck] = field(default_factory=list)
    started_at: str = ""
    elapsed_ms: int = 0


async def _check_feishu_token() -> PreflightCheck:
    import time

    chk = PreflightCheck(name="feishu_token", label="飞书 tenant_access_token")
    start = time.monotonic()
    try:
        from app.feishu.aily import get_tenant_access_token

        token = await asyncio.wait_for(get_tenant_access_token(), timeout=20)
        chk.ok = bool(token)
        chk.detail = "已成功获取 token（前 8 位：" + redact_sensitive_text(
            token[:8] if token else "", max_chars=20
        ) + "...）"
    except asyncio.TimeoutError:
        chk.detail = "20s 超时；检查网络或 Feishu API 域名可达性"
        chk.advisory = "确认 FEISHU_APP_ID / FEISHU_APP_SECRET 配置；境内网络一般 < 2s"
    except Exception as exc:
        chk.detail = redact_sensitive_text(str(exc)[:300])
        chk.advisory = "去 .env 配 FEISHU_APP_ID 与 FEISHU_APP_SECRET（飞书开放平台应用凭证）"
    chk.elapsed_ms = int((time.monotonic() - start) * 1000)
    return chk


async def _check_llm_reachability() -> PreflightCheck:
    import time

    chk = PreflightCheck(name="llm", label="LLM 可达性 + 配额")
    start = time.monotonic()
    try:
        from app.core.llm_client import call_llm

        out = await asyncio.wait_for(
            call_llm(
                system_prompt="只回 1。",
                user_prompt="1",
                temperature=0,
                max_tokens=4,
                tier="fast",
            ),
            timeout=25,
        )
        chk.ok = bool(out and out.strip())
        chk.detail = f"LLM 返回 {len(out or '')} 字符；通路正常"
    except asyncio.TimeoutError:
        chk.detail = "25s 超时；模型响应慢或网络问题"
        chk.advisory = "切到 fast 档（DeepSeek-Chat / 智谱 GLM-Flash 等低延迟模型）"
    except Exception as exc:
        chk.detail = redact_sensitive_text(str(exc)[:300])
        chk.advisory = "确认 LLM_BASE_URL / LLM_API_KEY；竞赛要求用国内模型，例如 https://api.deepseek.com/v1"
    chk.elapsed_ms = int((time.monotonic() - start) * 1000)
    return chk


async def _check_llm_base_url_compliance() -> PreflightCheck:
    import time

    chk = PreflightCheck(name="llm_compliance", label="国内模型合规性")
    start = time.monotonic()
    try:
        from app.core.settings import get_llm_base_url

        url = (get_llm_base_url() or "").lower()
        forbidden = next((host for host in _FORBIDDEN_LLM_HOSTS if host in url), None)
        if forbidden:
            chk.detail = f"检测到 LLM_BASE_URL 指向境外服务：{forbidden}"
            chk.advisory = "竞赛禁用境外大模型；切到 deepseek-chat / 智谱 GLM / 火山引擎 / 通义千问 / 豆包 / MiniMax / 飞书 Aily"
        else:
            chk.ok = True
            chk.detail = f"base_url 不在境外黑名单（当前指向：{redact_sensitive_text(url[:60])}...）"
    except Exception as exc:
        chk.detail = redact_sensitive_text(str(exc)[:300])
        chk.advisory = "settings 模块加载失败，检查 backend/app/core/settings.py"
    chk.elapsed_ms = int((time.monotonic() - start) * 1000)
    return chk


async def _check_redis() -> PreflightCheck:
    import time

    chk = PreflightCheck(name="redis", label="Redis 分布式锁")
    start = time.monotonic()
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        chk.ok = True  # 单实例本地锁也算合规
        chk.detail = "未配置 REDIS_URL — 单实例部署使用进程内锁（生产多实例必须挂 Redis）"
        chk.advisory = ""
        chk.elapsed_ms = int((time.monotonic() - start) * 1000)
        return chk
    try:
        from app.core.budget import _get_redis  # 复用同一连接 + 60s 重试节流

        client = await asyncio.wait_for(_get_redis(), timeout=5)
        if client is None:
            chk.detail = "Redis 客户端不可用（_get_redis 返回 None；可能在 retry 冷却期）"
            chk.advisory = "等 60s 让 retry 窗口过期，或直接重启进程"
        else:
            await asyncio.wait_for(client.ping(), timeout=3)
            chk.ok = True
            chk.detail = "ping 成功；分布式锁可用"
    except asyncio.TimeoutError:
        chk.detail = "Redis 超时（PING > 3s）"
        chk.advisory = "检查 REDIS_URL 主机可达性 / 网络延迟"
    except Exception as exc:
        chk.detail = redact_sensitive_text(str(exc)[:300])
        chk.advisory = "REDIS_URL 配错 / Redis 实例未启动；多实例部署必须修复"
    chk.elapsed_ms = int((time.monotonic() - start) * 1000)
    return chk


async def run_preflight() -> PreflightReport:
    """并发跑所有 check，30s 内出结果。任一 check 抛错被 gather 兜住，不影响其他。"""
    import time
    from datetime import datetime, timezone

    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()

    coros = [
        _check_feishu_token(),
        _check_llm_reachability(),
        _check_llm_base_url_compliance(),
        _check_redis(),
    ]
    # gather 把每个 coro 的异常封进 result（return_exceptions=True），便于把
    # 单个 check 失败映射成统一 PreflightCheck.ok=False。
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    checks: list[PreflightCheck] = []
    for raw in raw_results:
        if isinstance(raw, BaseException):
            checks.append(
                PreflightCheck(
                    name="unknown",
                    label="未知 check",
                    ok=False,
                    detail=redact_sensitive_text(str(raw)[:300]),
                )
            )
        else:
            checks.append(raw)

    report = PreflightReport(
        ok=all(c.ok for c in checks),
        checks=checks,
        started_at=started_at,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    return report


def report_to_dict(report: PreflightReport) -> dict:
    return {
        "ok": report.ok,
        "started_at": report.started_at,
        "elapsed_ms": report.elapsed_ms,
        "checks": [
            {
                "name": c.name,
                "label": c.label,
                "ok": c.ok,
                "detail": c.detail,
                "advisory": c.advisory,
                "elapsed_ms": c.elapsed_ms,
            }
            for c in report.checks
        ],
    }
