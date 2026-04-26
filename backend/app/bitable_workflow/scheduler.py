"""
状态驱动调度器（七岗多智能体版）

轮询「分析任务」表中的待处理记录，对每条任务调用完整的七岗 DAG 分析流水线：
  待分析 → [Wave1: 5个并行Agent] → [Wave2: 财务顾问] → [Wave3: CEO助理] → 已完成

崩溃恢复：ANALYZING 状态为上次崩溃遗留，重置回待分析重新处理。
反馈闭环：任务完成后，CEO 助理行动项自动写回「分析任务」表形成新的待分析任务。
飞书通知：任务完成后向配置的飞书群推送摘要卡片消息。
"""
import asyncio
import logging
import os
import re
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.schema import Status
from app.bitable_workflow.workflow_agents import (
    cleanup_prior_task_output_ids,
    collect_prior_task_output_ids,
    run_task_pipeline,
    update_performance,
    write_agent_outputs,
    write_ceo_report,
)
from app.agents.base_agent import AgentResult
from app.core.observability import clear_task_context, set_task_context
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)

# v8.6.19 — feature flags（默认开启 + 自动 fallback；不依赖人工关 flag）
USE_RECORDS_SEARCH = os.getenv("WORKFLOW_USE_RECORDS_SEARCH", "1") == "1"
USE_BATCH_RECORDS = os.getenv("WORKFLOW_USE_BATCH_RECORDS", "1") == "1"


def _flatten_text_value(value):
    """v8.6.19 修：飞书 search_records / get_record 把 text/title 字段返回为
    `[{"text": "...", "type": "text"}]` 富文本数组。直接当 string 用 / 写回飞书都会
    炸（写回报 1254060 TextFieldConvFail）。这里把富文本数组拍平成纯 string。

    其他类型（int/float/None/dict 含 file_token 等）原样返回。
    """
    if isinstance(value, list) and value and isinstance(value[0], dict) and "text" in value[0]:
        return "".join(str(seg.get("text", "")) for seg in value if isinstance(seg, dict))
    return value


def _flatten_record_fields(fields: dict) -> dict:
    """对 record fields 字典应用 _flatten_text_value 规范化所有富文本字段。"""
    if not isinstance(fields, dict):
        return fields
    return {k: _flatten_text_value(v) for k, v in fields.items()}

# 单轮最多处理任务数（每条任务触发 7 次 LLM 调用）
_MAX_PER_CYCLE = 3
_LOCAL_CYCLE_LOCK: asyncio.Lock | None = None
import threading as _threading
_LOCAL_CYCLE_LOCK_INIT = _threading.Lock()
_LOCK_TTL_SECONDS = int(os.getenv("WORKFLOW_CYCLE_LOCK_TTL_SECONDS", "900"))
_RECOVER_STALE_MINUTES = int(os.getenv("WORKFLOW_RECOVER_STALE_MINUTES", "30"))
_ALLOW_LOCAL_WORKFLOW_LOCK = os.getenv("WORKFLOW_ALLOW_LOCAL_LOCK", "").lower() in {
    "1",
    "true",
    "yes",
}


def _owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


def _cycle_lock_key(app_token: str, task_tid: str) -> str:
    return f"workflow:cycle-lock:{app_token}:{task_tid}"


async def _acquire_cycle_lock(app_token: str, task_tid: str) -> tuple[object | None, str | None]:
    # v8.1 修复：双检锁懒初始化，防止并发 cycle 启动各自创建独立 Lock 实例 → 本地互斥失效
    global _LOCAL_CYCLE_LOCK
    if _LOCAL_CYCLE_LOCK is None:
        with _LOCAL_CYCLE_LOCK_INIT:
            if _LOCAL_CYCLE_LOCK is None:
                _LOCAL_CYCLE_LOCK = asyncio.Lock()
    await _LOCAL_CYCLE_LOCK.acquire()
    owner = _owner_id()
    try:
        import redis.asyncio as aioredis
        from app.core.settings import settings

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        ok = await client.set(
            _cycle_lock_key(app_token, task_tid),
            owner,
            nx=True,
            ex=_LOCK_TTL_SECONDS,
        )
        if not ok:
            _LOCAL_CYCLE_LOCK.release()
            await client.aclose()
            return None, None
        return client, owner
    except Exception as exc:
        env = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
        if env in {"prod", "production"} and not _ALLOW_LOCAL_WORKFLOW_LOCK:
            _LOCAL_CYCLE_LOCK.release()
            raise RuntimeError("Redis workflow lock is required in production") from exc
        logger.warning("Redis workflow lock unavailable; using in-process lock only: %s", exc)
        return None, owner


async def _release_cycle_lock(lock_client: object | None, owner: str | None, app_token: str, task_tid: str) -> None:
    try:
        if lock_client is not None and owner:
            key = _cycle_lock_key(app_token, task_tid)
            current = await lock_client.get(key)
            if current == owner:
                await lock_client.delete(key)
            await lock_client.aclose()
    finally:
        if _LOCAL_CYCLE_LOCK is not None and _LOCAL_CYCLE_LOCK.locked():
            _LOCAL_CYCLE_LOCK.release()


async def _renew_cycle_lock(lock_client: object, owner: str, app_token: str, task_tid: str) -> None:
    """Keep the distributed workflow lock alive while a long analysis cycle runs."""
    key = _cycle_lock_key(app_token, task_tid)
    interval = max(5, min(60, _LOCK_TTL_SECONDS // 3))
    while True:
        await asyncio.sleep(interval)
        current = await lock_client.get(key)
        if current != owner:
            raise RuntimeError("Lost Redis workflow lock ownership")
        await lock_client.expire(key, _LOCK_TTL_SECONDS)


def _parse_feishu_time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


_DEP_NUM_RE = re.compile(r"^[Tt]?0*(\d+)$")


def _normalize_task_number(raw: str) -> str:
    """规范化任务编号：'T0001' / '0001' / '1' / 'T100' 都归一为 '1' / '100' 等纯数字字符串。

    旧实现用 lstrip('T0').lstrip('0') 是 char-set 剥离，对 '100' 会变成空字符串 → 100 号任务永远查不到。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    m = _DEP_NUM_RE.match(s)
    if m:
        return m.group(1) or "0"
    return s  # 异常格式原样返回，由调用方判定为"未知"


async def _build_dep_index(app_token: str, task_tid: str) -> dict[str, str]:
    """构建 任务编号 → 状态 索引，供依赖检查使用。

    任务编号 字段类型为 AutoNumber，飞书会以序列号字符串返回（如 '1', '2', '3'）。
    若该字段缺失或返回结构异常，统一以空字符串兜底，让依赖检查降级为通过。
    """
    index: dict[str, str] = {}
    try:
        rows = await bitable_ops.list_records(app_token, task_tid, max_records=200)
    except Exception as exc:
        logger.debug("dep index list_records failed (skip dep check): %s", exc)
        return index
    for r in rows:
        f = r.get("fields") or {}
        num = f.get("任务编号")
        # AutoNumber 在 SDK 中可能返回 dict {"value": [{"text": "1"}]} 或 直接字符串
        raw_num = ""
        if isinstance(num, str):
            raw_num = num
        elif isinstance(num, dict):
            value = num.get("value")
            if isinstance(value, list) and value:
                first = value[0]
                raw_num = (first.get("text") if isinstance(first, dict) else str(first)) or ""
        elif isinstance(num, (int, float)):
            raw_num = str(int(num))
        normalized = _normalize_task_number(raw_num)
        if normalized:
            index[normalized] = f.get("状态") or ""
    return index


def _unmet_dependencies(dep_field: object, dep_index: dict[str, str]) -> list[str]:
    """解析依赖任务编号字段，返回未完成的依赖列表。

    格式宽松：
      - "1, 3"  / "T0001, T0003" / "1；3" / "1\n3" 都识别
      - 缺省 / 空白 / 解析失败 → 视为无依赖
    """
    if not dep_field:
        return []
    raw = str(dep_field) if not isinstance(dep_field, str) else dep_field
    parts = [_normalize_task_number(p) for p in re.split(r"[,，;；\n\s]+", raw) if p.strip()]
    unmet: list[str] = []
    for num in parts:
        if not num:
            continue
        status = dep_index.get(num)
        if status is None:
            # 引用了不存在的任务编号 — 容错：视为未完成（用户应改正字段）
            unmet.append(f"T{num}(未知)")
        elif status != Status.COMPLETED:
            unmet.append(f"T{num}({status or '空状态'})")
    return unmet


def _is_stale_analyzing(fields: dict) -> bool:
    updated_at = _parse_feishu_time(fields.get("最近更新"))
    if updated_at is None:
        return False
    return datetime.now(timezone.utc) - updated_at > timedelta(minutes=_RECOVER_STALE_MINUTES)


async def _claim_pending_record(
    app_token: str,
    task_tid: str,
    record_id: str,
    owner: str,
) -> Optional[dict]:
    """v8.6.19：claim 成功返回回读后的完整 record (`get_record` 结果)，失败返回 None。

    旧版返回 bool，调用方还要再 get_record 一次拿全字段；现在合二为一，避免重复 IO，
    且让上层直接拿到 fields（含 分析维度/背景说明/数据源/任务图像）给 pipeline。
    """
    claim_stage = f"🔒 已领取：{owner}"
    await bitable_ops.update_record(
        app_token,
        task_tid,
        record_id,
        {"状态": Status.ANALYZING, "当前阶段": claim_stage, "进度": 0.01},
    )
    claimed = await bitable_ops.get_record(app_token, task_tid, record_id)
    # v8.6.19：飞书 get_record 把 text/title 返回为富文本数组 [{"text":...,"type":"text"}]
    # 必须拍平成 string，否则上层写回会触发 1254060 TextFieldConvFail
    raw_fields = claimed.get("fields") or {}
    fields = _flatten_record_fields(raw_fields)
    claimed["fields"] = fields  # 同步覆盖，保证调用方拿到的是 flat
    if fields.get("状态") == Status.ANALYZING and fields.get("当前阶段") == claim_stage:
        return claimed
    return None


_HEALTH_TO_HEADER_COLOR = {
    "🟢": "green", "🟡": "yellow", "🔴": "red", "⚪": "grey",
}


def _ceo_health_header_color(ceo_result: AgentResult) -> str:
    """从 CEO 输出推断 header 颜色：🟢 健康→green / 🟡 关注→yellow / 🔴 预警→red / 其他→blue"""
    try:
        from app.bitable_workflow.workflow_agents import _extract_health
        health = _extract_health(ceo_result) or ""
    except Exception:
        health = ""
    for marker, color in _HEALTH_TO_HEADER_COLOR.items():
        if marker in health:
            return color
    return "blue"


def _ceo_section_first_paragraph(ceo_result: AgentResult, keyword: str) -> str:
    """从 ceo_result.sections 中找标题含 keyword 的 section，返回 content 首段（200 字截断）"""
    for s in (ceo_result.sections or []):
        title = getattr(s, "title", None) or (s.get("title") if isinstance(s, dict) else "")
        if keyword in (title or ""):
            content = getattr(s, "content", None) or (s.get("content") if isinstance(s, dict) else "")
            content = (content or "").strip()
            if not content:
                continue
            # 取首段（双换行截断 / 200 字截断）
            first = content.split("\n\n", 1)[0].strip()
            return truncate_with_marker(first, 200, "...")
    return ""


async def _send_completion_message(
    app_token: str,
    task_tid: str,
    rid: str,
    task_title: str,
    ceo_result: AgentResult,
) -> None:
    """v8.6.19：任务完成后发飞书富文本卡片，含跳转按钮 + 健康度颜色 + 机会/风险字段。

    URL 用 get_feishu_base_url()（用户侧 feishu.cn）；base/table 级链接为硬验收，
    record 参数为 best-effort（飞书 deeplink 实测可能因版本变化）。
    """
    try:
        from app.feishu.im import send_card_message
        from app.feishu.client import get_feishu_base_url
        feishu_base = get_feishu_base_url()
        url = f"{feishu_base}/base/{app_token}?table={task_tid}&record={rid}"
        summary = truncate_with_marker(ceo_result.raw_output or "七岗多智能体分析已完成", 1200)
        opportunity = _ceo_section_first_paragraph(ceo_result, "机会")
        risk = _ceo_section_first_paragraph(ceo_result, "风险")
        fields = []
        if opportunity:
            fields.append(("重要机会", opportunity))
        if risk:
            fields.append(("重要风险", risk))
        await send_card_message(
            title=f"分析完成：{task_title}",
            content=summary,
            header_color=_ceo_health_header_color(ceo_result),
            action_url=url,
            fields=fields,
        )
        logger.info("Feishu card sent for task [%s] url=%s", task_title, url)
    except ValueError:
        logger.debug("feishu_chat_id not configured, skipping notification for task [%s]", task_title)
    except Exception as exc:
        logger.warning("Feishu notification failed for task [%s]: %s", task_title, exc)


async def _create_followup_tasks(
    app_token: str,
    task_tid: str,
    task_title: str,
    ceo_result: AgentResult,
    parent_task_number: str | None = None,
) -> None:
    """将 CEO 助理行动项转化为新的「待分析」任务，实现业务闭环（再流转）。

    同时尝试通过飞书任务 API 创建待办事项，方便在飞书中直接跟进。
    只取前 3 条非空行动项；跟进任务本身不再生成二级跟进，避免无限循环。

    parent_task_number: 原任务的「任务编号」（AutoNumber 字段值），自动写入
      跟进任务的「依赖任务编号」字段，构建任务依赖图（v8.6.7 新增）。
    """
    if task_title.startswith("[跟进]"):
        return

    # v8.6.4 修复：CEO 助理把"管理摘要"文本以 "[摘要] ..." 形式插入 action_items[0]
    # （便于飞书消息推送）。如果直接拿来当跟进任务标题，会得到 "[跟进] [摘要] 当前公司面临..."
    # 这种语义混乱的二级任务 — 用户在表里看到一堆"[跟进] [摘要]"开头的废任务。
    # 这里显式过滤掉 [摘要] 前缀的元素。
    action_items = [
        item.strip() for item in (ceo_result.action_items or [])
        if item.strip() and not item.strip().startswith("[摘要]")
    ][:3]
    if not action_items:
        logger.debug("No action items for follow-up from task [%s]", task_title)
        return

    # 1. 写入飞书任务 API（待办事项），便于在飞书客户端直接追踪
    try:
        from app.feishu.task import batch_create_tasks
        await batch_create_tasks(action_items)
        logger.info("Created %d Feishu tasks for [%s]", len(action_items), task_title)
    except Exception as exc:
        logger.warning("Feishu task API failed for [%s]: %s", task_title, exc)

    # 2. 在「分析任务」表中生成后续待分析记录（再流转闭环）
    from app.bitable_workflow import schema as _schema
    for item in action_items:
        record_fields: dict = {
            "任务标题": f"[跟进] {truncate_with_marker(item, 50, '...[截断]')}",
            "分析维度": "综合分析",
            "优先级": "P2 中",
            "状态": Status.PENDING,
            "进度": 0,
            "背景说明": f"由任务「{task_title}」的CEO助理决策建议自动生成",
            # v8.6.20：跟进任务也填综合评分（由 priority_score 算出）
            "综合评分": _schema.priority_score("P2 中"),
        }
        # v8.6.7：跟进任务自动指向原任务，构建依赖图
        if parent_task_number:
            record_fields["依赖任务编号"] = str(parent_task_number)
        try:
            # v8.6.20：综合评分老 base 没有 → optional fallback
            await bitable_ops.create_record_optional_fields(
                app_token, task_tid, record_fields, optional_keys=["综合评分"],
            )
            logger.info(
                "Follow-up task created from [%s]: %s",
                task_title,
                truncate_with_marker(item, 50, "...[截断]"),
            )
        except Exception as exc:
            logger.warning("Failed to create follow-up task from [%s]: %s", task_title, exc)


async def run_one_cycle(app_token: str, table_ids: dict) -> int:
    task_tid = table_ids["task"]
    lock_client, lock_owner = await _acquire_cycle_lock(app_token, task_tid)
    if lock_owner is None:
        logger.info("Workflow cycle skipped because another instance holds the lock")
        return 0
    renew_task: asyncio.Task | None = None
    if lock_client is not None and lock_owner:
        renew_task = asyncio.create_task(
            _renew_cycle_lock(lock_client, lock_owner, app_token, task_tid)
        )
    cycle_task: asyncio.Task | None = None
    try:
        cycle_task = asyncio.create_task(_run_one_cycle_locked(app_token, table_ids))
        if renew_task is None:
            return await cycle_task
        done, _pending = await asyncio.wait(
            {cycle_task, renew_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        if renew_task in done:
            renew_exc = renew_task.exception()
            if renew_exc is not None:
                cycle_task.cancel()
                try:
                    await cycle_task
                except asyncio.CancelledError:
                    pass
                raise RuntimeError("Workflow lock renewal failed; cycle aborted") from renew_exc
        return await cycle_task
    finally:
        if cycle_task is not None and not cycle_task.done():
            cycle_task.cancel()
            try:
                await cycle_task
            except asyncio.CancelledError:
                pass
        if renew_task is not None:
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Workflow lock renewal stopped with error: %s", exc)
        await _release_cycle_lock(lock_client, lock_owner, app_token, task_tid)


async def _run_one_cycle_locked(app_token: str, table_ids: dict) -> int:
    """
    执行一轮完整的多智能体分析处理：
      0. 恢复崩溃遗留的 ANALYZING 记录 → 重置为待分析
      1. 领取「待分析」任务，逐条执行七岗 DAG 流水线
      2. 将各岗分析输出写入「岗位分析」表（含关联字段）
      3. 将 CEO 助理综合报告写入「综合报告」表（含关联字段）
      4. 更新「数字员工效能」表
      5. 发送飞书消息通知
      6. CEO 行动项生成新的「待分析」任务（再流转闭环）

    返回本轮成功完成的任务数。
    """
    task_tid = table_ids["task"]
    output_tid = table_ids.get("output")
    report_tid = table_ids["report"]
    performance_tid = table_ids.get("performance")
    processed = 0

    # Phase 0: 恢复 ANALYZING 悬挂记录（上次崩溃遗留）
    # v8.6.19：优先 search_records（必须 automatic_fields=True，因为 stale 判断依赖
    # 「最近更新」是 ModifiedTime 自动字段）+ batch_update_records 一次恢复多条；
    # 任一失败回退老路径（list + 逐条 update）
    stuck: list[dict] = []
    if USE_RECORDS_SEARCH:
        try:
            stuck = await bitable_ops.search_records(
                app_token, task_tid,
                filter_conditions=[{"field_name": "状态", "operator": "is", "value": [Status.ANALYZING]}],
                field_names=["任务标题", "最近更新", "状态"],
                automatic_fields=True,  # 「最近更新」是 ModifiedTime
            )
        except Exception as exc:
            logger.warning("Phase0 search failed, fallback to list_records: %s", exc)
            stuck = []
    if not stuck:
        stuck = await bitable_ops.list_records(
            app_token, task_tid,
            filter_expr=f'CurrentValue.[状态]="{Status.ANALYZING}"',
        )

    stale_to_recover: list[dict] = []
    for record in stuck:
        rid = record.get("record_id")
        if not rid:
            logger.warning("Stuck record missing record_id, skipping: %s", record)
            continue
        fields = record.get("fields", {})
        if not _is_stale_analyzing(fields):
            logger.info("Skipping active ANALYZING record=%s; not stale enough for recovery", rid)
            continue
        stale_to_recover.append({"record_id": rid, "fields": {"状态": Status.PENDING}})

    if stale_to_recover:
        if USE_BATCH_RECORDS:
            try:
                n = await bitable_ops.batch_update_records(app_token, task_tid, stale_to_recover)
                logger.warning("Recovered %d stuck ANALYZING records → 待分析 (batch)", n)
            except Exception as exc:
                logger.warning("batch_update recovery failed, fallback to serial: %s", exc)
                for entry in stale_to_recover:
                    try:
                        await bitable_ops.update_record(app_token, task_tid, entry["record_id"], entry["fields"])
                        logger.warning("Recovered stuck ANALYZING record=%s (serial)", entry["record_id"])
                    except Exception as inner:
                        logger.error("Failed to recover ANALYZING record=%s: %s", entry["record_id"], inner)
        else:
            for entry in stale_to_recover:
                try:
                    await bitable_ops.update_record(app_token, task_tid, entry["record_id"], entry["fields"])
                    logger.warning("Recovered stuck ANALYZING record=%s (serial, flag off)", entry["record_id"])
                except Exception as exc:
                    logger.error("Failed to recover ANALYZING record=%s: %s", entry["record_id"], exc)

    # Phase 1: 领取待分析任务（v8.6.19：search + 综合评分 server sort，三层降级）
    pending_pool_size = int(os.getenv("WORKFLOW_PENDING_POOL_SIZE", "200"))

    def _prio_key(record: dict) -> int:
        raw = (record.get("fields") or {}).get("优先级", "") or ""
        s = str(raw).upper().strip()
        if "P0" in s or "紧急" in s:
            return 0
        if "P1" in s or "高" in s:
            return 1
        if "P2" in s or "中" in s:
            return 2
        if "P3" in s or "低" in s:
            return 3
        return 99

    candidates: Optional[list[dict]] = None
    sorted_by_search = False
    # 第一层：search + 综合评分 server-side sort（仅当字段存在）
    if USE_RECORDS_SEARCH:
        if await bitable_ops.field_exists(app_token, task_tid, "综合评分"):
            try:
                candidates = await bitable_ops.search_records(
                    app_token, task_tid,
                    filter_conditions=[{"field_name": "状态", "operator": "is", "value": [Status.PENDING]}],
                    sort=[{"field_name": "综合评分", "desc": True}],
                    field_names=["任务标题", "状态", "优先级", "任务编号", "依赖任务编号"],
                    max_records=pending_pool_size,
                )
                sorted_by_search = True
            except Exception as exc:
                logger.warning("Phase1 search+sort failed, falling back: %s", exc)
                candidates = None
        # 第二层：search 仅 filter（综合评分缺失或 sort 失败）
        if candidates is None:
            try:
                candidates = await bitable_ops.search_records(
                    app_token, task_tid,
                    filter_conditions=[{"field_name": "状态", "operator": "is", "value": [Status.PENDING]}],
                    field_names=["任务标题", "状态", "优先级", "任务编号", "依赖任务编号"],
                    max_records=pending_pool_size,
                )
            except Exception as exc:
                logger.warning("Phase1 search filter failed, falling back to list: %s", exc)
                candidates = None
    # 第三层：list + filter_expr（兜底老路径）
    if candidates is None:
        candidates = await bitable_ops.list_records(
            app_token, task_tid,
            filter_expr=f'CurrentValue.[状态]="{Status.PENDING}"',
            page_size=min(100, pending_pool_size),
            max_records=pending_pool_size,
        )
    if not sorted_by_search:
        candidates.sort(key=_prio_key)

    if candidates:
        prio_summary = [(r.get("fields") or {}).get("优先级", "?") for r in candidates[:5]]
        logger.info("Phase 1 candidates=%d top5_prio=%s sorted_by_search=%s",
                    len(candidates), prio_summary, sorted_by_search)

    # 任务依赖图：构建 任务编号 → status 的全表索引（便于检查依赖）
    dep_index = await _build_dep_index(app_token, task_tid)

    # v8.6.19：遍历候选，依赖 + claim 都满足才计入本轮（不先截断），直到达 _MAX_PER_CYCLE
    for record in candidates:
        if processed >= _MAX_PER_CYCLE:
            break
        rid = record.get("record_id", "?")
        # v8.6.19：search_records 返回的 text 字段是富文本数组，先拍平
        fields = _flatten_record_fields(record.get("fields", {}))
        task_title = fields.get("任务标题", f"任务_{rid[:8]}")

        # 绑定 task_id 上下文 — 此后所有 logger.* 调用自动带上 task_id，便于聚合查询
        set_task_context(task_id=rid)

        # 任务依赖检查：「依赖任务编号」中的所有任务必须 已完成 才能启动
        unmet_deps = _unmet_dependencies(fields.get("依赖任务编号"), dep_index)
        if unmet_deps:
            stage_msg = f"⏸ 等待依赖任务：{', '.join(unmet_deps[:3])}"
            try:
                await bitable_ops.update_record(
                    app_token, task_tid, rid, {"当前阶段": stage_msg}
                )
            except Exception as upd_exc:
                logger.debug("dep wait stage update failed: %s", upd_exc)
            logger.info("Task [%s] blocked by deps: %s", task_title, unmet_deps)
            clear_task_context(task_id=True, agent_id=True)
            continue

        try:
            # v8.6.19：claim 返回 dict|None — 成功的 record 含完整 fields（含
            # 分析维度 / 背景说明 / 数据源 / 任务图像），避免 search 字段子集不够而
            # 必须再 get_record。
            claim_owner = _owner_id()
            claimed_record = await _claim_pending_record(app_token, task_tid, rid, claim_owner)
            if claimed_record is None:
                logger.warning("Workflow claim lost for record=%s owner=%s", rid, claim_owner)
                continue
            # 用 claim 回读到的完整 fields 替换 search 拿到的字段子集
            fields = claimed_record.get("fields") or fields

            await bitable_ops.update_record(
                app_token, task_tid, rid,
                {"当前阶段": "▶ Wave1 启动：五岗并行分析中…", "进度": 0.1}
            )

            from app.bitable_workflow import progress_broker
            await progress_broker.publish(
                rid, "task.started",
                {"title": task_title, "stage": "Wave1 启动：五岗并行分析中…", "progress": 0.1},
            )

            # 每个 Wave 完成后更新「当前阶段」+「进度」字段，让用户在多维表格实时看到进展
            _wave_progress = iter([0.45, 0.75, 0.95])

            async def _on_wave(stage: str) -> None:
                progress = next(_wave_progress, 0.95)
                try:
                    await bitable_ops.update_record(
                        app_token, task_tid, rid, {"当前阶段": stage, "进度": progress}
                    )
                except Exception as stage_exc:
                    logger.debug("当前阶段 update skipped: %s", stage_exc)
                await progress_broker.publish(
                    rid, "wave.completed", {"stage": stage, "progress": progress},
                )

            # 执行七岗 DAG 分析流水线（Wave1→Wave2→Wave3）
            # 传入 rid 作为 task_id，启用 Redis 缓存：崩溃重试会跳过已完成的 agent
            all_results, ceo_result = await run_task_pipeline(
                fields, progress_callback=_on_wave, task_id=rid
            )

            # 先记录历史输出 ID；新输出和报告全部写入成功后再清理旧记录，避免重试失败丢失上次好结果。
            prior_output_ids = await collect_prior_task_output_ids(
                app_token, task_title, output_tid, report_tid
            )

            # 写入各岗分析输出（含关联字段；写入不完整会使整条任务重试）
            if output_tid:
                output_written = await write_agent_outputs(
                    app_token, output_tid, task_title, all_results, task_record_id=rid
                )
                if output_written != len(all_results):
                    raise RuntimeError(f"岗位分析写入不完整: {output_written}/{len(all_results)}")

            # 写入 CEO 综合报告（含关联字段；核心交付物，失败直接抛出）
            await write_ceo_report(
                app_token,
                report_tid,
                task_title,
                ceo_result,
                participant_count=len(all_results) + 1,  # +1 for ceo_assistant
                task_record_id=rid,
            )

            # 更新员工效能（含 CEO 助理本身）
            if performance_tid:
                await update_performance(
                    app_token, performance_tid, all_results + [ceo_result]
                )

            try:
                await cleanup_prior_task_output_ids(
                    app_token, output_tid, report_tid, prior_output_ids
                )
            except Exception as cleanup_exc:
                logger.warning(
                    "Prior output cleanup failed after successful replacement for task=%s: %s",
                    task_title,
                    cleanup_exc,
                )

            # 标记为已完成，进度置为 100%
            # v8.6.19 — 双字段过渡：完成时间（旧 TEXT 总是写）+ 完成日期（新 DateTime 毫秒戳）
            # 老 base 缺「完成日期」时 update_record_optional_fields 自动 fallback 仅写完成时间
            await bitable_ops.update_record_optional_fields(
                app_token,
                task_tid,
                rid,
                {
                    "状态": Status.COMPLETED,
                    "当前阶段": "✅ 七岗分析全部完成",
                    "进度": 1.0,
                    "完成时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "完成日期": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
                },
                optional_keys=["完成日期"],
            )
            processed += 1
            logger.info("Task [%s] completed by 7-agent pipeline", task_title)

            # 任务成功完成 → 清除 Redis 缓存 + 广播 SSE task.done
            try:
                from app.bitable_workflow.agent_cache import invalidate_task_cache
                await invalidate_task_cache(rid)
            except Exception as cache_exc:
                logger.debug("cache invalidate failed: %s", cache_exc)
            await progress_broker.publish(
                rid, "task.done",
                {"title": task_title, "progress": 1.0, "participant_count": len(all_results) + 1},
            )

            # 飞书消息通知（v8.6.19 升级：含跳转 url + 健康度颜色 + 机会/风险字段）
            await _send_completion_message(app_token, task_tid, rid, task_title, ceo_result)

            # 反馈再流转：CEO 行动项 → 新的待分析任务（自动 set 依赖任务编号 = 原任务编号）
            parent_num_raw = fields.get("任务编号")
            parent_num: str | None = None
            if isinstance(parent_num_raw, str):
                parent_num = parent_num_raw
            elif isinstance(parent_num_raw, dict):
                v = parent_num_raw.get("value")
                if isinstance(v, list) and v:
                    first = v[0]
                    parent_num = (first.get("text") if isinstance(first, dict) else str(first)) or None
            elif isinstance(parent_num_raw, (int, float)):
                parent_num = str(int(parent_num_raw))
            await _create_followup_tasks(
                app_token, task_tid, task_title, ceo_result,
                parent_task_number=parent_num,
            )

        except Exception as exc:
            logger.error("Pipeline failed for task=%s record=%s: %s", task_title, rid, exc)
            try:
                await bitable_ops.update_record(
                    app_token, task_tid, rid,
                    {"状态": Status.PENDING, "当前阶段": f"❌ 执行失败，将重试：{truncate_with_marker(exc, 100, '...[截断]')}"}
                )
            except Exception as reset_exc:
                logger.error(
                    "Failed to reset task=%s back to PENDING: %s — task may remain stuck in ANALYZING",
                    task_title, reset_exc,
                )
            # 不清除缓存 — 下次重试可复用已完成的 agent 结果
            try:
                from app.bitable_workflow import progress_broker
                await progress_broker.publish(
                    rid, "task.error", {"reason": truncate_with_marker(exc, 200, "...[截断]")},
                )
            except Exception:
                pass
        finally:
            clear_task_context(task_id=True, agent_id=True)

    return processed
