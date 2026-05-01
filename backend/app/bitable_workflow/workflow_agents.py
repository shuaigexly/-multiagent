"""
内容运营虚拟组织 — 七岗多智能体协作流水线

复用 app.agents 注册的七个 BaseAgent，按 AGENT_DEPENDENCIES DAG 组织执行：

  Wave 1（并行，无上游依赖）
    DataAnalystAgent      数据分析师  — 指标分析、趋势洞察
    ContentManagerAgent   内容负责人  — 内容资产盘点、创作策略
    SEOAdvisorAgent       SEO增长顾问 — 关键词机会、流量增长
    ProductManagerAgent   产品经理    — 需求分析、路线图规划
    OperationsManagerAgent 运营负责人 — 执行规划、任务拆解

  Wave 2（依赖数据分析师输出）
    FinanceAdvisorAgent   财务顾问    — 收支诊断、现金流分析

  Wave 3（汇总所有上游）
    CEOAssistantAgent     CEO 助理    — 综合管理决策摘要
"""
import asyncio
import hashlib
import json as _json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from app.agents.base_agent import AgentResult, ResultSection
from app.agents.ceo_assistant import ceo_assistant_agent
from app.agents.content_manager import content_manager_agent
from app.agents.data_analyst import data_analyst_agent
from app.agents.finance_advisor import finance_advisor_agent
from app.agents.operations_manager import operations_manager_agent
from app.agents.product_manager import product_manager_agent
from app.agents.seo_advisor import seo_advisor_agent
from app.bitable_workflow import bitable_ops
from app.core.redaction import redact_sensitive_text
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)

# Wave 1: no upstream dependency — run in parallel
_WAVE1_AGENTS = [
    data_analyst_agent,
    content_manager_agent,
    seo_advisor_agent,
    product_manager_agent,
    operations_manager_agent,
]

# Wave 2: finance_advisor needs data_analyst output
_WAVE2_AGENTS = [finance_advisor_agent]

# Wave 3: synthesizes all upstream results
_WAVE3_AGENT = ceo_assistant_agent


async def _enrich_with_vision(task_description: str, fields: dict) -> str:
    """如果任务带「任务图像」附件，用 vision LLM 把图片转成文字描述并附加到 task_description。

    飞书 Bitable 附件字段值是 list[{"file_token": "..."}]；通过 file_token 拼出可访问 URL。
    每张图最多分析前 3 张，避免无限放大 token 成本。
    LLM_VISION_MODEL 未配置时直接返回原 task_description。
    """
    images = fields.get("任务图像") or []
    if not images or not isinstance(images, list):
        return task_description

    import os

    if not os.getenv("LLM_VISION_MODEL", "").strip():
        return task_description

    import base64
    import httpx

    from app.core.vision import analyze_image
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token

    base = get_feishu_open_base_url()
    try:
        token = await get_tenant_access_token()
    except Exception as exc:
        logger.warning("vision skipped: feishu token failed: %s", redact_sensitive_text(exc, max_chars=500))
        return task_description

    descriptions: list[str] = []
    # 关键修复：Vision LLM 不能直接访问飞书带鉴权的 URL（永远 401），
    # 必须由后端先下载字节，再 base64 → data URI 喂给 vision API。
    # v7.8 再修：大图必须降采样压缩，否则 5MB → base64 7MB → ~1.7M tokens 直接爆 context。
    MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 4MB 原始上限（兜底）
    MAX_AFTER_RESIZE = 600 * 1024       # 压缩后 600KB 目标（合理 vision 输入）

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as http:
        for idx, item in enumerate(images[:3], 1):
            if not isinstance(item, dict):
                continue
            file_token = item.get("file_token") or ""
            if not file_token:
                continue
            try:
                resp = await http.get(
                    f"{base}/open-apis/drive/v1/medias/{file_token}/download",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                img_bytes = resp.content
            except Exception as exc:
                logger.warning("vision: download attachment failed idx=%s err=%s", idx, exc)
                continue

            if len(img_bytes) > MAX_IMAGE_BYTES:
                logger.warning("vision: image %s too large (%d bytes), skipping", idx, len(img_bytes))
                continue

            # 大图压缩：若 PIL 可用且图片 > 600KB，按长边 1280 缩放 + JPEG 75 质量
            mime = resp.headers.get("content-type", "image/png").split(";", 1)[0].strip() or "image/png"
            if len(img_bytes) > MAX_AFTER_RESIZE:
                try:
                    from io import BytesIO

                    from PIL import Image

                    img = Image.open(BytesIO(img_bytes))
                    # JPEG 仅支持 RGB / L / CMYK；其他模式（RGBA/P/1/I/F/PA/...）必须先转 RGB
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    # v8.1 修复：Pillow ≥10 弃用 Image.LANCZOS，改用 Image.Resampling.LANCZOS。
                    # 双路径兼容旧版本（< 10）和新版本（≥ 10）。
                    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None) \
                        or getattr(Image, "LANCZOS", None)
                    img.thumbnail((1280, 1280), resample) if resample else img.thumbnail((1280, 1280))
                    out = BytesIO()
                    img.save(out, format="JPEG", quality=75, optimize=True)
                    img_bytes = out.getvalue()
                    mime = "image/jpeg"
                    logger.info("vision: image %s resized to %d bytes", idx, len(img_bytes))
                except ImportError:
                    logger.warning("vision: PIL unavailable, large image %d bytes may exceed context", len(img_bytes))
                except Exception as exc:
                    logger.warning("vision: resize failed idx=%s err=%s — using original", idx, exc)

            data_uri = f"data:{mime};base64,{base64.b64encode(img_bytes).decode('ascii')}"
            try:
                text = await analyze_image(data_uri)
            except Exception as exc:
                logger.warning("vision analyze failed idx=%s err=%s", idx, exc)
                text = None
            if text:
                descriptions.append(f"【图像 {idx} 描述】\n{text}")

    if not descriptions:
        return task_description

    enriched = (
        f"{task_description}\n\n"
        f"=== 用户附上 {len(descriptions)} 张图像，vision LLM 已转译如下 ===\n"
        + "\n\n".join(descriptions)
    )
    logger.info("Pipeline enriched with %d image descriptions", len(descriptions))
    return enriched


def _build_task_description(fields: dict) -> str:
    title = fields.get("任务标题", "未命名任务")
    dimension = fields.get("分析维度", "综合分析")
    background = fields.get("背景说明", "")
    desc = f"任务：{title}\n分析维度：{dimension}"
    if background:
        desc += f"\n背景说明：{background}"
    target = (fields.get("目标对象") or "").strip()
    if target:
        desc += f"\n目标对象：{target}"
    purpose = (fields.get("输出目的") or "").strip()
    if purpose:
        desc += f"\n输出目的：{purpose}"
    success = (fields.get("成功标准") or "").strip()
    if success:
        desc += f"\n成功标准：{success}"
    constraints = (fields.get("约束条件") or "").strip()
    if constraints:
        desc += f"\n约束条件：{constraints}"
    stage = (fields.get("业务阶段") or "").strip()
    if stage:
        desc += f"\n业务阶段：{stage}"
    dataset = (fields.get("引用数据集") or "").strip()
    if dataset:
        desc += f"\n引用数据集：{dataset}"
    return desc


def _normalize_source_type(value: str) -> str:
    s = (value or "").strip().lower()
    return s if s in {"real_data", "benchmark", "upstream", "judgment"} else "judgment"


def _normalize_usage(value: str) -> str:
    s = (value or "").strip().lower()
    return s if s in {"insight", "opportunity", "risk", "decision"} else "insight"


def _normalize_confidence_text(value: str) -> str:
    s = (value or "").strip().lower()
    if s in {"high", "medium", "low"}:
        return s
    return "medium"


def _derive_evidence_grade(item: dict) -> str:
    source_type = _normalize_source_type(str(item.get("source_type", "")))
    confidence = _normalize_confidence_text(str(item.get("confidence", "")))
    cite = str(item.get("cite", "") or "").strip()
    if source_type == "real_data" and confidence in {"high", "medium"}:
        return "硬证据"
    if source_type in {"benchmark", "upstream"} and confidence == "high" and cite:
        return "硬证据"
    if confidence == "low":
        return "待验证"
    if source_type == "judgment" and not cite:
        return "待验证"
    return "推断"


def _first_nonempty_paragraph(text: str, limit: int = 220) -> str:
    if not text:
        return ""
    for chunk in text.split("\n\n"):
        line = chunk.strip()
        if line:
            return truncate_with_marker(line, limit, "...")
    return truncate_with_marker(text.strip(), limit, "...")


def _build_exec_brief(ceo_result: AgentResult, decision_buckets: dict[str, list[str]]) -> dict[str, str]:
    one_liner = (
        _first_nonempty_paragraph(_section_excerpt(ceo_result, "核心结论"), 160)
        or _first_nonempty_paragraph(_section_excerpt(ceo_result, "管理摘要"), 160)
        or truncate_with_marker(ceo_result.raw_output or "", 160, "...")
    )
    management_summary = (
        _section_excerpt(ceo_result, "管理摘要")
        or _section_excerpt(ceo_result, "一段话")
        or _section_excerpt(ceo_result, "核心结论")
    )
    top_action = (
        decision_buckets["execute_now"][:1]
        or decision_buckets["ceo_decision"][:1]
        or decision_buckets["delegated"][:1]
    )
    report_risk = (
        _first_nonempty_paragraph(_section_excerpt(ceo_result, "重要风险"), 220)
        or _first_nonempty_paragraph(_section_excerpt(ceo_result, "需补数"), 220)
    )
    needs = decision_buckets["need_data"][:2]
    brief = (
        f"一句话结论：{one_liner or '待补充'}\n\n"
        f"管理摘要：{truncate_with_marker(management_summary or '待补充', 500, '...[截断]')}\n\n"
        f"首要动作：{top_action[0] if top_action else '待补充'}\n\n"
        f"汇报风险：{report_risk or '当前无明确汇报阻塞'}\n\n"
        f"需补数：{'; '.join(needs) if needs else '无'}"
    )
    return {
        "one_liner": one_liner,
        "top_action": top_action[0] if top_action else "",
        "report_risk": report_risk,
        "brief": truncate_with_marker(brief, 1800, "\n...[已截断]"),
    }


def _evidence_summary(result: AgentResult, limit: int = 3) -> str:
    evidence = result.structured_evidence[:limit]
    if evidence:
        lines = []
        for item in evidence:
            claim = truncate_with_marker(item.get("claim", ""), 80, "...[截断]")
            source_type = _normalize_source_type(str(item.get("source_type", "")))
            lines.append(f"- [{source_type}] {claim}")
        return "\n".join(lines)
    if result.sections:
        section = result.sections[0]
        return f"- [judgment] {truncate_with_marker(section.title + '：' + section.content, 180, '...[截断]')}"
    return ""


def _derive_decision_buckets(ceo_result: AgentResult) -> dict[str, list[str]]:
    buckets = {
        "ceo_decision": [],
        "delegated": [],
        "need_data": [],
        "execute_now": [],
    }
    for item in ceo_result.decision_items:
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        kind = str(item.get("type") or "").strip().lower()
        if kind not in buckets:
            kind = "delegated"
        buckets[kind].append(summary)
    return buckets


def _section_excerpt(result: AgentResult, keyword: str, fallback: str = "") -> str:
    for section in result.sections:
        if keyword in section.title:
            return truncate_with_marker(section.content or "", 1000, "\n...[已截断]")
    return fallback


def _error_result(agent_id: str, agent_name: str, exc: Exception) -> AgentResult:
    return AgentResult(
        agent_id=agent_id,
        agent_name=agent_name,
        sections=[ResultSection(title="错误", content=f"分析失败：{exc}")],
        action_items=[],
        raw_output=f"FAILED: {exc}",
        chart_data=[],
    )


def _is_failed_result(result: AgentResult) -> bool:
    """硬失败（不含 FALLBACK 兜底）— FALLBACK 是有内容的降级，不算失败。"""
    return (result.raw_output or "").startswith("FAILED:")


def _is_fallback_result(result: AgentResult) -> bool:
    return (result.raw_output or "").startswith("FALLBACK:")


def _raise_if_failed(results: list[AgentResult], stage: str) -> None:
    failed = [r for r in results if _is_failed_result(r)]
    if failed:
        names = ", ".join(r.agent_name for r in failed)
        raise RuntimeError(f"{stage} failed agents: {names}")


def _cache_input_hash(task_description: str, data_summary, upstream: Optional[list[AgentResult]]) -> str:
    data_payload = data_summary.model_dump() if hasattr(data_summary, "model_dump") else None
    upstream_payload = [
        {
            "agent_id": r.agent_id,
            "raw_output": r.raw_output,
            "actions": r.action_items,
        }
        for r in (upstream or [])
    ]
    payload = {
        "task_description": task_description,
        "data_summary": data_payload,
        "upstream": upstream_payload,
    }
    encoded = _json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


async def _safe_analyze(
    agent,
    task_description: str,
    upstream: Optional[list[AgentResult]] = None,
    data_summary=None,
    task_id: Optional[str] = None,
    dimension: Optional[str] = None,
) -> AgentResult:
    """Run one agent with error isolation + multi-level Redis cache.

    Cache lookup order：
      1. task-specific (task_id, agent_id, input_hash) — 同任务重试复用
      2. shared (dimension, agent_id, input_hash) — 跨任务 DAG 共享（同维度 + 同输入）
    """
    input_hash = _cache_input_hash(task_description, data_summary, upstream)
    # Layer 1: task-specific cache
    if task_id:
        try:
            from app.bitable_workflow.agent_cache import get_cached_result

            cached = await get_cached_result(task_id, agent.agent_id, input_hash)
            if cached:
                logger.info("[cache-hit:task] %s/%s", task_id, agent.agent_id)
                return cached
        except Exception as cache_exc:
            logger.debug("task cache read skipped: %s", cache_exc)

    # Layer 2: cross-task shared cache (DAG sharing — same dimension + same input)
    if dimension:
        try:
            from app.bitable_workflow.agent_cache import get_shared_result

            shared = await get_shared_result(dimension, agent.agent_id, input_hash)
            if shared:
                logger.info("[cache-hit:shared] dim=%s/%s", dimension, agent.agent_id)
                # 复制后写入 task cache 加速本任务后续重试
                if task_id:
                    try:
                        from app.bitable_workflow.agent_cache import set_cached_result

                        await set_cached_result(task_id, agent.agent_id, input_hash, shared)
                    except Exception:
                        pass
                return shared
        except Exception as cache_exc:
            logger.debug("shared cache read skipped: %s", cache_exc)

    # v8.6.20-r43：每个 agent 入口先检查取消信号 — 用户在 /cancel 端点点了取消
    # 后，本任务后续的 agent 调用立即终止，避免浪费 LLM tokens。
    if task_id:
        from app.bitable_workflow import cancellation

        cancellation.raise_if_cancelled(task_id)

    # v8.6.20-r41：熔断器先于 LLM 调用 — 若该 agent 已被标记 OPEN，跳过 LLM
    # 直接走 fallback，避免每条任务都被 broken pipe 拖 1-3 分钟超时。
    from app.agents import circuit_breaker

    if circuit_breaker.is_open(agent.agent_id):
        logger.warning("[%s] circuit breaker OPEN — short-circuit to fallback", agent.agent_id)
        try:
            from app.agents.fallback import build_fallback_result

            return build_fallback_result(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                task_description=task_description,
                upstream=upstream,
                error_reason="circuit_breaker_open",
            )
        except Exception as fb_exc:
            logger.warning("[%s] fallback build failed during CB short-circuit: %s", agent.agent_id, fb_exc)

    try:
        result = await agent.analyze(
            task_description=task_description,
            data_summary=data_summary,
            upstream_results=upstream or [],
        )
        circuit_breaker.record_success(agent.agent_id)
    except Exception as exc:
        circuit_breaker.record_failure(agent.agent_id)
        logger.error("[%s] analyze failed: %s", agent.agent_id, exc)
        # 规则引擎降级：返回基于 persona + upstream 的骨架报告，避免任务全空
        try:
            from app.agents.fallback import build_fallback_result

            return build_fallback_result(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                task_description=task_description,
                upstream=upstream,
                error_reason=str(exc)[:200],
            )
        except Exception as fb_exc:
            logger.warning("[%s] fallback build failed: %s", agent.agent_id, fb_exc)
            return _error_result(agent.agent_id, agent.agent_name, exc)

    # Cache the successful result.
    # 关键：FALLBACK 兜底结果不能写 shared cache（会污染同维度其他任务）；
    #      task cache 也只在 confidence>=3 才写，避免低质量重试时把 1 分输出锁定下来。
    is_fallback = _is_fallback_result(result)
    is_failed = _is_failed_result(result)
    if not is_failed:
        try:
            from app.bitable_workflow.agent_cache import set_cached_result, set_shared_result

            if task_id and not is_fallback:
                await set_cached_result(task_id, agent.agent_id, input_hash, result)
            if dimension and not is_fallback and (result.confidence_hint or 5) >= 3:
                await set_shared_result(dimension, agent.agent_id, input_hash, result)
        except Exception as cache_exc:
            logger.debug("agent cache write skipped: %s", cache_exc)

    return result


async def run_task_pipeline(
    task_fields: dict,
    progress_callback=None,
    agent_event_callback=None,
    task_id: Optional[str] = None,
) -> tuple[list[AgentResult], AgentResult]:
    """
    对单条任务执行完整的七岗多智能体分析流水线。

    波次执行顺序遵循 AGENT_DEPENDENCIES DAG：
      Wave 1 → Wave 2（财务顾问，需要数据分析师输出）→ Wave 3（CEO 助理，汇总全部）

    progress_callback: 可选的异步函数 async(stage: str)，在每个 Wave 完成后调用，
                       用于向主任务表写入「当前阶段」进度。
    agent_event_callback: 可选的异步函数 async(event: dict)，在每个 Agent
                          started/completed/failed 时调用，用于嵌入式 workflow UI
                          精确点亮七岗节点。
    task_id: 任务唯一 ID（通常传 Bitable record_id），用于 Redis 缓存 agent 输出；
             崩溃恢复时已完成的 agent 会直接从缓存读取，避免重跑昂贵的 LLM 调用。

    返回：(wave1+wave2 共六个 AgentResult, CEO 助理综合 AgentResult)
    """
    task_description = _build_task_description(task_fields)
    dimension = (task_fields.get("分析维度") or "").strip() or None
    logger.info("Pipeline started for task: %s (dim=%s)", task_fields.get("任务标题", "?"), dimension)

    # Vision: 用户上传任务图像 → vision LLM 转文字 → 注入 task_description
    task_description = await _enrich_with_vision(task_description, task_fields)

    # 解析用户粘贴的数据源（CSV / markdown / 文本），注入到每个 agent 的 data_summary
    # v8.0 修复：parse_content 用了 pandas（同步 + 重 import），大 CSV (> 1万行) 解析
    # 会阻塞事件循环数百毫秒。放进线程池避免拖延 SSE 推送 / 健康检查 / 其他并行任务。
    data_summary = None
    data_source_text = (task_fields.get("数据源") or "").strip()
    # v8.6.16：数据源字段为「markdown 表格 + 原始 CSV」组合格式（飞书 UI 友好渲染）。
    # 优先抽出 ```...``` 围栏内的纯 CSV（机器解析），找不到再回退给 parse_content
    # 自识别（它能直接消化 markdown 表格 / CSV / JSON 各种形态）。
    if data_source_text:
        import re as _re
        m = _re.search(r"```(?:csv)?\s*\n?([\s\S]+?)\n?```", data_source_text)
        if m:
            data_source_text = m.group(1).strip()
    if data_source_text:
        try:
            from app.core.data_parser import parse_content

            data_summary = await asyncio.to_thread(parse_content, data_source_text)
            logger.info(
                "Data source parsed: type=%s rows=%d cols=%d",
                data_summary.content_type, data_summary.row_count, len(data_summary.columns),
            )
        except Exception as exc:
            logger.warning("Data source parse failed, falling back to no data: %s", exc)

    async def _emit_agent_event(
        event_type: str,
        agent,
        *,
        wave: str,
        dependency: str,
        result: AgentResult | None = None,
        error: Exception | str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        if not agent_event_callback:
            return
        duration_ms = None
        if started_at:
            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        payload = {
            "event_type": event_type,
            "agent_id": agent.agent_id,
            "agent_name": agent.agent_name,
            "wave": wave,
            "dependency": dependency,
            "duration_ms": duration_ms,
        }
        if result is not None:
            payload.update(
                {
                    "confidence": result.confidence_hint or 0,
                    "fallback": _is_fallback_result(result),
                    "failed": _is_failed_result(result),
                    "summary": _first_nonempty_paragraph(result.raw_output or "", 180),
                    "evidence_count": len(result.structured_evidence or []),
                    "action_count": len(result.action_items or []),
                }
            )
        if error is not None:
            payload["reason"] = redact_sensitive_text(error, max_chars=220)
        try:
            await agent_event_callback(payload)
        except Exception as cb_exc:
            logger.debug("agent_event_callback failed: %s", cb_exc)

    async def _run_agent(agent, *, wave: str, dependency: str, upstream=None) -> AgentResult:
        started_at = datetime.now(timezone.utc)
        await _emit_agent_event("agent.started", agent, wave=wave, dependency=dependency, started_at=started_at)
        try:
            result = await _safe_analyze(
                agent,
                task_description,
                upstream=upstream,
                data_summary=data_summary,
                task_id=task_id,
                dimension=dimension,
            )
        except Exception as exc:
            await _emit_agent_event("agent.failed", agent, wave=wave, dependency=dependency, error=exc, started_at=started_at)
            raise
        await _emit_agent_event(
            "agent.failed" if _is_failed_result(result) else "agent.completed",
            agent,
            wave=wave,
            dependency=dependency,
            result=result,
            started_at=started_at,
        )
        return result

    # Wave 1: parallel execution of 5 independent agents
    wave1_coros = [
        _run_agent(agent, wave="Wave 1", dependency="无上游依赖")
        for agent in _WAVE1_AGENTS
    ]
    wave1_results: list[AgentResult] = list(await asyncio.gather(*wave1_coros))
    _raise_if_failed(wave1_results, "Wave1")
    logger.info("Wave 1 complete: %d agents", len(wave1_results))
    if progress_callback:
        try:
            await progress_callback("Wave1 完成：数据分析 / 内容 / SEO / 产品 / 运营 五岗并行分析就绪")
        except Exception as cb_exc:
            logger.debug("progress_callback Wave1 failed: %s", cb_exc)

    # Wave 2: finance_advisor uses data_analyst output as upstream.
    # Look up by agent_id, not by list index, so reordering _WAVE1_AGENTS never silently
    # passes the wrong result to finance_advisor.
    wave1_by_id = {r.agent_id: r for r in wave1_results}
    da_result = wave1_by_id.get("data_analyst") or wave1_results[0]
    fa_result = await _run_agent(
        finance_advisor_agent,
        wave="Wave 2",
        dependency="依赖数据分析师输出",
        upstream=[da_result],
    )
    wave2_results = [fa_result]
    _raise_if_failed(wave2_results, "Wave2")
    logger.info("Wave 2 complete: finance_advisor")
    if progress_callback:
        try:
            await progress_callback("Wave2 完成：财务顾问分析就绪，正在生成 CEO 综合报告…")
        except Exception as cb_exc:
            logger.debug("progress_callback Wave2 failed: %s", cb_exc)

    # Wave 3: ceo_assistant synthesizes all upstream conclusions
    all_upstream = wave1_results + wave2_results
    if all(_is_failed_result(result) for result in all_upstream):
        raise RuntimeError("所有上游 Agent 均执行失败，任务无可用结果")

    # 把 wave1+wave2 注入 ContextVar，供 ask_peer 工具在 CEO LLM 调用中使用
    from app.agents.peer_qa import clear_peer_pool, set_peer_pool
    peer_token = set_peer_pool(all_upstream)
    try:
        ceo_result = await _run_agent(
            _WAVE3_AGENT,
            wave="Wave 3",
            dependency="汇总全部上游结论",
            upstream=all_upstream,
        )
    finally:
        clear_peer_pool(peer_token)
    if _is_failed_result(ceo_result):
        raise RuntimeError(f"CEO 助理汇总失败: {ceo_result.raw_output}")
    logger.info("Wave 3 complete: ceo_assistant")
    if progress_callback:
        try:
            await progress_callback("Wave3 完成：CEO 助理综合报告生成完毕")
        except Exception as cb_exc:
            logger.debug("progress_callback Wave3 failed: %s", cb_exc)

    return all_upstream, ceo_result


async def cleanup_prior_task_outputs(
    app_token: str,
    task_title: str,
    output_table_id: Optional[str],
    report_table_id: Optional[str],
) -> None:
    """Deprecated unsafe cleanup path.

    Deleting old rows before replacement writes succeed can lose the last good
    results. Use collect_prior_task_output_ids() before writing, then
    cleanup_prior_task_output_ids() after all replacement writes succeed.
    """
    raise RuntimeError(
        "cleanup_prior_task_outputs is unsafe; use collect_prior_task_output_ids "
        "before writes and cleanup_prior_task_output_ids after successful writes"
    )


async def collect_prior_task_output_ids(
    app_token: str,
    task_title: str,
    output_table_id: Optional[str],
    report_table_id: Optional[str],
) -> dict[str, list[str]]:
    """Collect existing output/report record IDs so cleanup can happen after new writes succeed."""
    safe_title = bitable_ops.quote_filter_value(task_title)
    filter_expr = f"CurrentValue.[任务标题]={safe_title}"
    report_filter = f"CurrentValue.[报告标题]={safe_title}"
    prior = {"output": [], "report": []}
    if output_table_id:
        records = await bitable_ops.list_records(
            app_token,
            output_table_id,
            filter_expr=filter_expr,
            max_records=500,
        )
        prior["output"] = [r["record_id"] for r in records if r.get("record_id")]
    if report_table_id:
        records = await bitable_ops.list_records(
            app_token,
            report_table_id,
            filter_expr=report_filter,
            max_records=500,
        )
        prior["report"] = [r["record_id"] for r in records if r.get("record_id")]
    return prior


async def cleanup_prior_task_output_ids(
    app_token: str,
    output_table_id: Optional[str],
    report_table_id: Optional[str],
    prior_ids: dict[str, list[str]],
) -> None:
    """Best-effort cleanup of old rows collected before the successful replacement write."""
    cleanup_errors: list[str] = []
    for table_id, record_ids, label in [
        (output_table_id, prior_ids.get("output", []), "岗位分析"),
        (report_table_id, prior_ids.get("report", []), "综合报告"),
    ]:
        if not table_id:
            continue
        for record_id in record_ids:
            try:
                await bitable_ops.delete_record(app_token, table_id, record_id)
            except Exception as exc:
                logger.warning("Cleanup prior %s record=%s failed: %s", label, record_id, exc)
                cleanup_errors.append(f"{label}:{record_id}: {exc}")
    if cleanup_errors:
        raise RuntimeError("清理历史输出失败: " + "；".join(cleanup_errors[:3]))


_AGENT_ROLE_EMOJI_MAP = {
    "数据分析师": "📊 数据分析师",
    "内容负责人": "📝 内容负责人",
    "SEO/增长顾问": "🔍 SEO/增长顾问",
    "SEO 增长顾问": "🔍 SEO/增长顾问",
    "产品经理": "📱 产品经理",
    "运营负责人": "⚙️ 运营负责人",
    "财务顾问": "💰 财务顾问",
    "CEO 助理": "👔 CEO 助理",
    "CEO助理": "👔 CEO 助理",
}


def _role_with_emoji(agent_name: str) -> str:
    """Map bare agent name to the emoji-prefixed SingleSelect option label."""
    return _AGENT_ROLE_EMOJI_MAP.get(agent_name, agent_name)


_HEALTH_MAP = {
    "🟢": "🟢 健康",
    "🟡": "🟡 关注",
    "🔴": "🔴 预警",
    "⚪": "⚪ 数据不足",
}


def _extract_health(result: AgentResult) -> str:
    """健康度评级判定（按可信度逐级降级）：
      1. LLM metadata.health（最高可信）
      2. "总体/整体/综合 评级/健康度" 行附近的 emoji（LLM 在正文显式自报）
      3. 严重优先级扫描（兜底，可能高估风险）

    v8.6.4 修复：之前 step 2 缺失，"🟡需关注" 的财务顾问报告因正文风险段含 🔴
    被误判为"🔴 预警"。现在先按"总体评级"显式取 LLM 真意。
    """
    # v8.2 清理：删除未使用的 `emoji` 局部变量（旧实现遗留）
    if result.health_hint:
        for key, label in _HEALTH_MAP.items():
            if key in result.health_hint:
                return label

    text_blobs = [s.content or "" for s in result.sections]
    text_blobs.append(result.raw_output or "")
    combined = "\n".join(text_blobs)[:5000]

    import re as _re
    rating_match = _re.search(
        r"(?:总体|整体|综合|核心|本期)\s*(?:评级|健康度|健康|状态|评估)[：:]\s*\**\s*(.{0,20})",
        combined,
    )
    if rating_match:
        rating_window = rating_match.group(1)
        for key, label in _HEALTH_MAP.items():
            if key in rating_window:
                return label

    if "🔴" in combined:
        return "🔴 预警"
    if "🟡" in combined:
        return "🟡 关注"
    if "🟢" in combined:
        return "🟢 健康"
    return "⚪ 数据不足"


# v8.6.20 — 防御：飞书 SingleSelect 字段写入时若 value 含 invisible 字符（zero-width
# space U+200B、NBSP U+00A0 等）或空白漂移，飞书会"看似匹配实则新建 option"，
# 导致 filter 视图命中数对不上（实测 base #3 bug：32 条 🟡 关注 filter 仅命中 20）。
# normalize 函数严格只允许 schema 中的 4 个 label，超界返回兜底 ⚪ 数据不足。
_HEALTH_LABELS_ALLOWED = {"🟢 健康", "🟡 关注", "🔴 预警", "⚪ 数据不足"}
_AGENT_ROLE_LABELS_ALLOWED = {opt["name"] for opt in __import__("app.bitable_workflow.schema", fromlist=["AGENT_ROLE_OPTIONS"]).AGENT_ROLE_OPTIONS}


def _normalize_singleselect(value: str, allowed: set[str], fallback: str) -> str:
    """SingleSelect 字段写入前严格校验：必须 ∈ allowed；含不可见字符或空白漂移会被
    飞书当成新 option 创建（schema 外 hidden option_id），filter 视图命中漂移。

    v8.6.20-r7（审计 #9）：补 NFC 归一化 + emoji variation selector U+FE0E/U+FE0F +
    全角空格 U+3000，应对从 HTML/Word/中文输入法粘贴的 LLM/用户输入。"""
    if not value:
        return fallback
    s = unicodedata.normalize("NFC", str(value)).strip()
    # 移除 zero-width 字符 + emoji variation selectors
    for ch in ("​", "‌", "‍", "﻿", "︎", "️"):
        s = s.replace(ch, "")
    # NBSP -> 普通 space + 全角空格 U+3000 -> 普通 space
    s = s.replace(" ", " ").replace("　", " ")
    if s in allowed:
        return s
    return fallback


def _estimate_confidence(result: AgentResult) -> int:
    """置信度：优先 LLM 自报（metadata.confidence），否则启发式估算。"""
    if 1 <= result.confidence_hint <= 5:
        return result.confidence_hint
    raw = result.raw_output or ""
    if not raw or "FAILED" in raw[:50]:
        return 1
    section_count = len(result.sections)
    action_count = len(result.action_items)
    has_chart = bool(result.chart_data)
    has_thinking = bool(result.thinking_process)
    score = 2
    if section_count >= 4:
        score += 1
    if action_count >= 3:
        score += 1
    if has_chart:
        score += 1
    if has_thinking and len(raw) > 1500:
        score += 1
    return min(5, max(1, score))


def _estimate_urgency(ceo_result: AgentResult) -> int:
    """决策紧急度（v8.6.20-r3 修：与健康度联动，避免 🟢 健康 + 紧急度=5 的矛盾）：
      1. 优先 CEO 的 metadata.structured_actions 最高 P 级
      2. emoji 启发式（旧逻辑）
      3. **按健康度设上限**：🟢→cap 3，🟡→cap 4，🔴→可 5（避免逻辑悖论）
    """
    raw_score = 3  # default
    if ceo_result.structured_actions:
        priority_score = {"P0": 5, "P1": 4, "P2": 3, "P3": 2}
        max_score = max(
            (priority_score.get((a.get("priority") or "").upper(), 0) for a in ceo_result.structured_actions),
            default=0,
        )
        if max_score:
            raw_score = max_score
    else:
        combined = (ceo_result.raw_output or "").lower()
        if "🔴" in ceo_result.raw_output or "紧急" in combined or "p0" in combined:
            raw_score = 5
        elif "🟡" in ceo_result.raw_output or "重要" in combined:
            raw_score = 4
        elif "🟢" in ceo_result.raw_output:
            raw_score = 2

    # v8.6.20-r3：按健康度 cap 紧急度上限，避免「🟢 健康 + 紧急度=5」逻辑矛盾
    # v8.6.20-r7（审计 #5）：⚪ 数据不足 不再返回 raw_score（之前默认 raw=3 会给出
    # 「数据不足但紧急度=3 火」的误导信号），改为强制 1。
    health = _extract_health(ceo_result)
    if "⚪" in health or "数据不足" in health:
        return 1
    if "🟢" in health:
        return min(raw_score, 3)
    if "🟡" in health:
        return min(raw_score, 4)
    return raw_score  # 🔴 预警 → 不 cap，原值（最高 5）


def _format_sections(result: AgentResult, max_chars: int = 2000) -> str:
    """Concatenate all sections into one markdown block, truncated to max_chars.

    Builds incrementally and stops as soon as the limit is reached, avoiding
    serialising the full output when only the first few sections fit.
    """
    if not result.sections:
        return truncate_with_marker(result.raw_output, max_chars, "\n...[已截断]")
    parts: list[str] = []
    total = 0
    for s in result.sections:
        chunk = f"## {s.title}\n{s.content or ''}"
        if total + len(chunk) + 2 > max_chars:
            remaining = max_chars - total - 20
            if remaining > 0 and parts:
                parts.append(truncate_with_marker(chunk, remaining + len("\n...[已截断]"), "\n...[已截断]"))
            elif remaining > 0:
                parts.append(truncate_with_marker(chunk, remaining + len("\n...[已截断]"), "\n...[已截断]"))
            break
        parts.append(chunk)
        total += len(chunk) + 2  # +2 for "\n\n" separator
    return "\n\n".join(parts)


async def write_agent_outputs(
    app_token: str,
    output_table_id: str,
    task_title: str,
    results: list[AgentResult],
    task_record_id: Optional[str] = None,
) -> int:
    """将各岗 AgentResult 写入「岗位分析」表。每个 Agent 写一条记录。

    task_record_id: 分析任务表中对应记录的 record_id，用于填写关联字段。
    返回成功写入的记录数。调用方必须校验是否等于结果数量。

    生成时间字段为 CreatedTime 类型，由飞书自动填充，无需手动写入。
    """
    from app.bitable_workflow.chart_renderer import render_chart_to_png, upload_chart_to_bitable

    written = 0
    for result in results:
        summary = _format_sections(result, max_chars=5000)
        action_text = (
            "\n".join(f"- {a}" for a in result.action_items[:15])
            if result.action_items
            else ""
        )
        # 自动渲染 chart_data → PNG → 上传 Bitable 附件字段
        chart_attachment_token: Optional[str] = None
        if result.chart_data:
            try:
                png = render_chart_to_png(
                    result.chart_data,
                    title=f"{result.agent_name} · 关键指标",
                )
                if png:
                    chart_attachment_token = await upload_chart_to_bitable(
                        app_token,
                        output_table_id,
                        png,
                        file_name=f"{result.agent_id}_chart.png",
                    )
            except Exception as render_exc:
                logger.warning("chart render/upload failed for %s: %s", result.agent_id, render_exc)

        from app.bitable_workflow import schema as _schema
        # v8.6.20 — 防御 SingleSelect option_id 漂移（实测 #3 bug 根因）：
        # 严格 normalize，含 invisible 字符或不在 allowed 集合的值统一兜底
        health_label = _normalize_singleselect(
            _extract_health(result), _HEALTH_LABELS_ALLOWED, "⚪ 数据不足",
        )
        role_label = _normalize_singleselect(
            _role_with_emoji(result.agent_name), _AGENT_ROLE_LABELS_ALLOWED,
            _role_with_emoji(result.agent_name),  # 角色 normalize 失败仍写原值（兜底）
        )
        fields: dict = {
            "任务标题": task_title,
            "岗位角色": role_label,
            "健康度评级": health_label,
            # v8.6.20：健康度数值由 health_score() 算（替代飞书公式不生效）
            "健康度数值": _schema.health_score(health_label),
            "分析摘要": summary,
            "证据摘要": truncate_with_marker(_evidence_summary(result), 1000, "\n...[已截断]"),
            "行动项": truncate_with_marker(action_text, 2000, "\n...[已截断]"),
            "行动项数": len(result.action_items),
            "置信度": _estimate_confidence(result),
            "分析思路": truncate_with_marker(result.thinking_process, 3000, "\n...[已截断]") if result.thinking_process else "",
            "图表数据": truncate_with_marker(_json.dumps(result.chart_data, ensure_ascii=False), 3000, "\n...[已截断]") if result.chart_data else "",
        }
        if chart_attachment_token:
            fields["图表"] = [{"file_token": chart_attachment_token}]
        # v8.6.1 实测确认：飞书 POST/PUT/batch_create 三个 records 写接口**全部**
        # 不接受 LinkedRecord(type=18) 字段写入（code=1254067 LinkFieldConvFail）。
        # 这是飞书 Bitable 平台限制 — LinkedRecord 字段只能通过 UI 手动建立或在
        # 业务侧靠 任务标题/任务编号 文本字段做"逻辑关联"。
        # 因此从一开始就不写关联字段，避免无意义的 4xx + 重试浪费。
        try:
            # v8.6.20：「健康度数值」是新加 Number 字段，老 base 没有 → optional fallback
            await bitable_ops.create_record_optional_fields(
                app_token, output_table_id, fields,
                optional_keys=["健康度数值", "证据摘要"],
            )
            written += 1
        except Exception as exc:
            logger.error("Failed to write output for agent=%s: %s", result.agent_name, exc)
    return written


async def write_ceo_report(
    app_token: str,
    report_table_id: str,
    task_title: str,
    ceo_result: AgentResult,
    participant_count: int,
    task_record_id: Optional[str] = None,
) -> str:
    """将 CEO 助理综合报告写入「综合报告」表，返回 record_id。

    task_record_id: 分析任务表中对应记录的 record_id，用于填写关联字段。
    CEO 报告是核心交付物；写入失败直接抛出，由调用方决定是否失败整条任务。
    生成时间字段为 CreatedTime 类型，由飞书自动填充。
    """
    decision_buckets = _derive_decision_buckets(ceo_result)
    evidence_count = len(ceo_result.structured_evidence)
    exec_brief = _build_exec_brief(ceo_result, decision_buckets)
    record_fields: dict = {
        "报告标题": task_title,
        "综合健康度": _extract_health(ceo_result),
        "一句话结论": exec_brief["one_liner"],
        "核心结论": _section_excerpt(ceo_result, "核心结论"),
        "重要机会": _section_excerpt(ceo_result, "重要机会"),
        "重要风险": _section_excerpt(ceo_result, "重要风险"),
        "CEO决策事项": _section_excerpt(ceo_result, "CEO 需拍板") or _section_excerpt(ceo_result, "决策"),
        "管理摘要": _section_excerpt(ceo_result, "管理摘要") or _section_excerpt(ceo_result, "一段话"),
        "首要动作": exec_brief["top_action"],
        "汇报风险": exec_brief["report_risk"],
        "高管一页纸": exec_brief["brief"],
        "参与岗位数": float(participant_count),
        "决策紧急度": _estimate_urgency(ceo_result),
        "必须拍板事项": truncate_with_marker("\n".join(f"- {x}" for x in decision_buckets["ceo_decision"]), 1500, "\n...[已截断]"),
        "可授权事项": truncate_with_marker("\n".join(f"- {x}" for x in decision_buckets["delegated"]), 1500, "\n...[已截断]"),
        "需补数事项": truncate_with_marker("\n".join(f"- {x}" for x in decision_buckets["need_data"]), 1500, "\n...[已截断]"),
        "立即执行事项": truncate_with_marker("\n".join(f"- {x}" for x in decision_buckets["execute_now"]), 1500, "\n...[已截断]"),
        "证据充分度": min(5, max(1, evidence_count or 1)),
    }
    # v8.6.1 同上：飞书所有 records 写接口都不支持 LinkedRecord，从源头不写关联字段
    return await bitable_ops.create_record_optional_fields(
        app_token,
        report_table_id,
        record_fields,
        optional_keys=[
            "一句话结论",
            "首要动作",
            "汇报风险",
            "高管一页纸",
            "必须拍板事项",
            "可授权事项",
            "需补数事项",
            "立即执行事项",
            "证据充分度",
        ],
    )


async def write_evidence_records(
    app_token: str,
    evidence_table_id: str,
    task_title: str,
    results: list[AgentResult],
) -> int:
    """将各岗结构化证据写入「证据链」表。

    优先使用 metadata.evidence；若缺失，则回退为首段分析的 judgement 摘要，避免整张表为空。
    """
    written = 0
    for result in results:
        evidence_items = result.structured_evidence or [{
            "claim": result.sections[0].title if result.sections else f"{result.agent_name} 分析结论",
            "source_type": "judgment",
            "evidence": result.sections[0].content if result.sections else truncate_with_marker(result.raw_output, 300),
            "confidence": "medium",
            "usage": "insight",
            "cite": "岗位分析正文",
        }]
        role_label = _normalize_singleselect(
            _role_with_emoji(result.agent_name), _AGENT_ROLE_LABELS_ALLOWED, _role_with_emoji(result.agent_name),
        )
        for idx, item in enumerate(evidence_items[:8], 1):
            source_type = _normalize_source_type(str(item.get("source_type", "")))
            usage = _normalize_usage(str(item.get("usage", "")))
            confidence = _normalize_confidence_text(str(item.get("confidence", "")))
            fields = {
                "证据标题": f"{task_title} · {result.agent_name} · 证据{idx}",
                "任务标题": task_title,
                "岗位角色": role_label,
                "结论摘要": truncate_with_marker(str(item.get("claim", "")), 500, "...[截断]"),
                "证据类型": source_type,
                "证据用途": usage,
                "证据内容": truncate_with_marker(str(item.get("evidence", "")), 2000, "\n...[已截断]"),
                "引用来源": truncate_with_marker(str(item.get("cite", "")), 500, "...[截断]"),
                "证据置信度": confidence,
                "证据等级": _derive_evidence_grade({
                    "source_type": source_type,
                    "usage": usage,
                    "confidence": confidence,
                    "cite": item.get("cite", ""),
                }),
                "进入CEO汇总": usage in {"opportunity", "risk", "decision"},
            }
            try:
                await bitable_ops.create_record_optional_fields(
                    app_token,
                    evidence_table_id,
                    fields,
                    optional_keys=["证据等级"],
                )
                written += 1
            except Exception as exc:
                logger.warning("Evidence write failed for %s #%s: %s", result.agent_id, idx, exc)
    return written


def build_auto_review(
    task_title: str,
    all_results: list[AgentResult],
    ceo_result: AgentResult,
) -> dict:
    total_evidence = sum(len(r.structured_evidence or []) for r in all_results + [ceo_result])
    hard_evidence_count = sum(
        1
        for r in all_results + [ceo_result]
        for item in (r.structured_evidence or [])
        if _derive_evidence_grade(item) == "硬证据"
    )
    pending_verify_count = sum(
        1
        for r in all_results + [ceo_result]
        for item in (r.structured_evidence or [])
        if _derive_evidence_grade(item) == "待验证"
    )
    real_data_count = sum(
        1
        for r in all_results + [ceo_result]
        for item in (r.structured_evidence or [])
        if _normalize_source_type(str(item.get("source_type", ""))) == "real_data"
    )
    truth_score = min(5, max(1, hard_evidence_count + (1 if real_data_count else 0) or (2 if total_evidence else 1)))
    if pending_verify_count >= max(2, hard_evidence_count + 1):
        truth_score = max(1, truth_score - 1)
    decision_count = len([x for x in ceo_result.decision_items if str(x.get("type") or "").strip()])
    decision_score = min(5, max(1, decision_count or (2 if ceo_result.sections else 1)))
    exec_score = min(5, max(1, len(ceo_result.structured_actions) or len(ceo_result.action_items) or 1))
    closure_score = min(5, max(1, len([x for x in ceo_result.decision_items if str(x.get("type") or "") in {"need_data", "execute_now", "delegated", "ceo_decision"}]) or 1))
    need_data = [
        str(x.get("summary") or "").strip()
        for x in ceo_result.decision_items
        if str(x.get("type") or "").strip() == "need_data" and str(x.get("summary") or "").strip()
    ]
    avg_score = (truth_score + decision_score + exec_score + closure_score) / 4
    if avg_score >= 4.0:
        recommend = "直接采用"
    elif need_data:
        recommend = "补数后复核"
    else:
        recommend = "建议重跑"
    review_summary = (
        f"任务《{task_title}》自动评审：真实性={truth_score}/5，决策性={decision_score}/5，"
        f"可执行性={exec_score}/5，闭环准备度={closure_score}/5。"
    )
    return {
        "任务标题": task_title,
        "评审结论": review_summary,
        "推荐动作": recommend,
        "真实性": truth_score,
        "决策性": decision_score,
        "可执行性": exec_score,
        "闭环准备度": closure_score,
        "需补数事项": truncate_with_marker("\n".join(f"- {x}" for x in need_data), 1500, "\n...[已截断]"),
        "评审摘要": truncate_with_marker(
            review_summary + (f" 需补数 {len(need_data)} 项。" if need_data else " 当前可直接进入执行/再流转。"),
            1500,
            "\n...[已截断]",
        ),
    }


async def build_review_payload(
    task_title: str,
    all_results: list[AgentResult],
    ceo_result: AgentResult,
) -> dict:
    """优先使用 LLM reviewer 评审，失败时回退启发式评分。"""
    fallback = build_auto_review(task_title, all_results, ceo_result)
    try:
        from app.core.llm_client import call_llm

        agent_summaries = []
        for result in all_results + [ceo_result]:
            section_head = ""
            if result.sections:
                section_head = truncate_with_marker(result.sections[0].content or "", 400, "\n...[已截断]")
            evidence_head = "; ".join(
                truncate_with_marker(str(item.get("claim") or ""), 80, "...[截断]")
                for item in (result.structured_evidence or [])[:3]
            )
            agent_summaries.append(
                f"## {result.agent_name}\n"
                f"首段摘要：{section_head}\n"
                f"行动项数：{len(result.action_items)}\n"
                f"证据数：{len(result.structured_evidence)}\n"
                f"证据示例：{evidence_head}\n"
            )
        reviewer_prompt = (
            f"你是飞书经营分析工作流的严格评审官。请评估任务《{task_title}》的整套产出质量。\n\n"
            "请按以下四个维度打分（1-5）：真实性、决策性、可执行性、闭环准备度。\n"
            "同时给出推荐动作，只能是：直接采用 / 补数后复核 / 建议重跑。\n"
            "若需要补数，明确列出 1-3 条补数事项。\n\n"
            "以下是岗位输出摘要：\n"
            + "\n".join(agent_summaries)
            + "\n请只输出严格 JSON：\n"
            "{\n"
            '  "recommend": "直接采用|补数后复核|建议重跑",\n'
            '  "truth": 1,\n'
            '  "decision": 1,\n'
            '  "execution": 1,\n'
            '  "closure": 1,\n'
            '  "summary": "100字以内评审摘要",\n'
            '  "needs": ["补数项1", "补数项2"]\n'
            "}\n"
        )
        raw = await call_llm(
            system_prompt="你是严格的经营分析结果评审官，只返回 JSON。",
            user_prompt=reviewer_prompt,
            temperature=0,
            max_tokens=500,
            tier="fast",
        )
        match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
        parsed = _json.loads(raw)
        recommend = str(parsed.get("recommend") or "").strip()
        if recommend not in {"直接采用", "补数后复核", "建议重跑"}:
            recommend = fallback["推荐动作"]
        needs_raw = parsed.get("needs") or []
        needs = [str(x).strip() for x in needs_raw if str(x).strip()][:3] if isinstance(needs_raw, list) else []
        return {
            "任务标题": task_title,
            "评审结论": truncate_with_marker(str(parsed.get("summary") or fallback["评审结论"]), 300, "...[截断]"),
            "推荐动作": recommend,
            "真实性": min(5, max(1, int(parsed.get("truth", fallback["真实性"]) or fallback["真实性"]))),
            "决策性": min(5, max(1, int(parsed.get("decision", fallback["决策性"]) or fallback["决策性"]))),
            "可执行性": min(5, max(1, int(parsed.get("execution", fallback["可执行性"]) or fallback["可执行性"]))),
            "闭环准备度": min(5, max(1, int(parsed.get("closure", fallback["闭环准备度"]) or fallback["闭环准备度"]))),
            "需补数事项": truncate_with_marker("\n".join(f"- {x}" for x in needs), 1500, "\n...[已截断]"),
            "评审摘要": truncate_with_marker(
                str(parsed.get("summary") or fallback["评审摘要"]),
                1500,
                "\n...[已截断]",
            ),
        }
    except Exception as exc:
        logger.warning("LLM reviewer fallback to heuristic for task=%s: %s", task_title, exc)
        return fallback


async def write_review_record(
    app_token: str,
    review_table_id: str,
    task_title: str,
    all_results: list[AgentResult],
    ceo_result: AgentResult,
) -> dict:
    fields = await build_review_payload(task_title, all_results, ceo_result)
    record_id = await bitable_ops.create_record_optional_fields(
        app_token,
        review_table_id,
        fields,
        optional_keys=["需补数事项"],
    )
    return {"record_id": record_id, "fields": fields}


async def update_performance(
    app_token: str,
    performance_table_id: str,
    results: list[AgentResult],
) -> None:
    """更新数字员工效能表的处理任务数（滚动累计）。

    批量拉取全表现有记录（性能表最多 7 行），避免每个 Agent 各发一次 list_records。
    最近更新字段为 ModifiedTime 类型，由飞书自动填充。
    """
    try:
        all_rows = await bitable_ops.list_records(
            app_token, performance_table_id, max_records=50
        )
    except Exception as exc:
        logger.warning("Performance: failed to fetch existing rows: %s", exc)
        all_rows = []

    # v8.6.20-r9（审计 #1）：员工姓名 是 Text 字段，飞书 list_records 偶尔返回
    # 富文本数组 [{"text":"产品经理","type":"text"}] —— 直接放进 dict-key 会 raise
    # TypeError: unhashable type: 'list'，让整个 update_performance 被 except 静默
    # 吞掉；或某些 sdk 路径下 stringified key 永远 miss → 每 cycle create 一行 →
    # 效能表无限膨胀。先拍平再做 key。
    from app.bitable_workflow.scheduler import _flatten_record_fields
    perf_by_name: dict[str, dict] = {}
    for row in all_rows:
        flat = _flatten_record_fields(row.get("fields") or {})
        name = flat.get("员工姓名") or ""
        if isinstance(name, str) and name:
            perf_by_name[name] = {**row, "fields": flat}

    for result in results:
        try:
            existing = perf_by_name.get(result.agent_name)
            if existing:
                rid = existing["record_id"]
                prev_raw = (existing.get("fields") or {}).get("处理任务数", 0)
                try:
                    prev = float(prev_raw or 0)
                except (TypeError, ValueError):
                    prev = 0.0
                new_count = prev + 1
                activity = min(5, 1 + int(new_count // 2))  # 1,2,3,4,5 递进
                await bitable_ops.update_record(
                    app_token,
                    performance_table_id,
                    rid,
                    {"处理任务数": new_count, "活跃度": activity},
                )
            else:
                await bitable_ops.create_record(
                    app_token,
                    performance_table_id,
                    {
                        "员工姓名": result.agent_name,
                        "岗位": _role_with_emoji(result.agent_name),
                        "角色": result.agent_id,
                        "处理任务数": 1.0,
                        "活跃度": 1,
                    },
                )
        except Exception as exc:
            logger.warning("Performance update failed for %s: %s", result.agent_name, exc)
