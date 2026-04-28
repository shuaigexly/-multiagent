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
    write_evidence_records,
    write_agent_outputs,
    write_ceo_report,
    write_review_record,
    _derive_evidence_grade,
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
# v8.6.20-r7（审计 #3）：本地锁按 (app_token, task_tid) 分键，避免 Redis 不可用降级时
# 不同 base 的 cycle 互相阻塞（之前用全局单 Lock，B 必须等 A 整轮 LLM 全跑完）。
_LOCAL_CYCLE_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
import threading as _threading
_LOCAL_CYCLE_LOCKS_INIT = _threading.Lock()


def _get_local_cycle_lock(app_token: str, task_tid: str) -> asyncio.Lock:
    key = (app_token, task_tid)
    lock = _LOCAL_CYCLE_LOCKS.get(key)
    if lock is None:
        with _LOCAL_CYCLE_LOCKS_INIT:
            lock = _LOCAL_CYCLE_LOCKS.get(key)
            if lock is None:
                lock = asyncio.Lock()
                _LOCAL_CYCLE_LOCKS[key] = lock
    return lock
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
    # v8.1：双检锁懒初始化；v8.6.20-r7（审计 #3）：按 (app_token, task_tid) 分键，
    # 不再用全局单 Lock 阻塞跨 base 的并发 cycle。
    local_lock = _get_local_cycle_lock(app_token, task_tid)
    await local_lock.acquire()
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
            local_lock.release()
            await client.aclose()
            return None, None
        return client, owner
    except Exception as exc:
        env = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
        if env in {"prod", "production"} and not _ALLOW_LOCAL_WORKFLOW_LOCK:
            local_lock.release()
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
        # 按 (app_token, task_tid) 取自己的锁释放，不再操作全局
        local_lock = _LOCAL_CYCLE_LOCKS.get((app_token, task_tid))
        if local_lock is not None and local_lock.locked():
            local_lock.release()


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
            # v8.6.20-r8（审计 #4）：状态 SingleSelect 在某些 list_records/搜索路径
            # 会返回富文本数组 / dict，str-vs-list 比较 _unmet_dependencies 永远
            # 当成"未完成"，依赖检查会无脑挡住后续任务。统一拍平。
            status_raw = f.get("状态")
            if isinstance(status_raw, list):
                status_raw = "".join(seg.get("text", "") for seg in status_raw if isinstance(seg, dict))
            elif isinstance(status_raw, dict):
                status_raw = status_raw.get("text") or status_raw.get("name") or ""
            index[normalized] = str(status_raw or "")
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


def _section_excerpt_by_keywords(result: AgentResult, keywords: tuple[str, ...], limit: int = 600) -> str:
    for section in result.sections or []:
        title = getattr(section, "title", "") or ""
        if any(keyword in title for keyword in keywords):
            content = getattr(section, "content", "") or ""
            if content.strip():
                return truncate_with_marker(content.strip(), limit, "\n...[已截断]")
    return ""


def _count_bullets(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    return len([line for line in text.splitlines() if line.strip().lstrip("-•*").strip()])


def _extract_task_number(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw = value.get("value")
        if isinstance(raw, list) and raw:
            first = raw[0]
            return (first.get("text") if isinstance(first, dict) else str(first)) or ""
    if isinstance(value, (int, float)):
        return str(int(value))
    return ""


def _derive_archive_status(route: str) -> str:
    if route == "等待拍板":
        return "待拍板"
    if route == "直接执行":
        return "待执行"
    if route in {"补数复核", "重新分析"}:
        return "待复核"
    return "待汇报"


def _derive_execution_owner(task_fields: dict, route: str) -> str:
    existing = str(task_fields.get("执行负责人") or "").strip()
    if existing:
        return existing
    if route == "直接执行":
        return "待指派"
    return ""


def _derive_review_owner(task_fields: dict, route: str) -> str:
    existing = str(task_fields.get("复核负责人") or "").strip()
    if existing:
        return existing
    if route in {"补数复核", "重新分析"}:
        return "待指派"
    return ""


def _derive_approval_owner(task_fields: dict, route: str) -> str:
    existing = str(task_fields.get("拍板负责人") or "").strip()
    if existing:
        return existing
    fallback = str(task_fields.get("汇报对象") or task_fields.get("目标对象") or "").strip()
    if fallback:
        return fallback
    if route == "等待拍板":
        return "待指派"
    return ""


def _derive_retrospective_owner(task_fields: dict, route: str) -> str:
    existing = str(task_fields.get("复盘负责人") or "").strip()
    if existing:
        return existing
    review_owner = str(task_fields.get("复核负责人") or "").strip()
    if review_owner:
        return review_owner
    execution_owner = str(task_fields.get("执行负责人") or "").strip()
    if execution_owner:
        return execution_owner
    if route in {"直接执行", "补数复核", "重新分析"}:
        return "待指派"
    return ""


def _safe_int_field(value: object) -> int:
    """v8.6.20-r6：审计 #6/#7 — int(...) 对富文本 list / 含单位的字符串会 ValueError，
    把整条 cycle 拖死。统一一个兜底：list 拍平 + 提数字 + 失败返 0。"""
    if isinstance(value, list):
        value = "".join(seg.get("text", "") for seg in value if isinstance(seg, dict))
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0
        try:
            return int(float(s))
        except (TypeError, ValueError):
            import re as _re
            m = _re.match(r"-?\d+", s)
            return int(m.group(0)) if m else 0
    return 0


def _derive_review_sla_hours(task_fields: dict, route: str) -> int:
    current = _safe_int_field(task_fields.get("复核SLA小时"))
    if current > 0:
        return current
    if route == "补数复核":
        return 24
    if route == "重新分析":
        return 4
    return 0


def _derive_business_owner(task_fields: dict) -> str:
    existing = str(task_fields.get("业务归属") or "").strip()
    if existing:
        return existing
    dimension = str(task_fields.get("分析维度") or "").strip()
    purpose = str(task_fields.get("输出目的") or "").strip()
    if dimension == "产品规划":
        return "产品"
    if dimension == "增长优化":
        return "增长"
    if dimension == "内容战略":
        return "内容"
    if dimension == "运营诊断":
        return "运营"
    if purpose == "执行跟进":
        return "运营"
    if purpose == "管理决策":
        return "综合经营"
    return "综合经营"


def _derive_audience_level(task_fields: dict, route: str) -> str:
    existing = str(task_fields.get("汇报对象级别") or "").strip()
    if existing:
        return existing
    audience = str(task_fields.get("汇报对象") or task_fields.get("目标对象") or "").strip()
    if route == "等待拍板":
        return "CEO / CXO"
    audience_upper = audience.upper()
    if any(token in audience_upper for token in ("CEO", "CXO", "CFO", "COO", "CTO", "CMO")):
        return "CEO / CXO"
    if any(token in audience for token in ("管理层", "经营会", "委员会", "总办会")):
        return "部门管理层"
    return "负责人"


def _render_template_text(template: str, context: dict[str, str]) -> str:
    rendered = str(template or "")
    for key, value in context.items():
        rendered = rendered.replace(f"{{{key}}}", str(value or ""))
    return rendered


def _is_unassigned_owner(value: object) -> bool:
    owner = str(value or "").strip()
    if not owner:
        return True
    lowered = owner.lower()
    return any(marker in lowered for marker in ("待指派", "未指定", "待补充", "未分配"))


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _hours_from_now(value: object, now: datetime | None = None) -> int:
    dt = _parse_feishu_time(value)
    if dt is None:
        return 0
    current = now or datetime.now(tz=timezone.utc)
    return max(0, int((current - dt).total_seconds() // 3600))


def _hours_overdue(value: object, now: datetime | None = None) -> int:
    dt = _parse_feishu_time(value)
    if dt is None:
        return 0
    current = now or datetime.now(tz=timezone.utc)
    if dt >= current:
        return 0
    return max(0, int((current - dt).total_seconds() // 3600))


def _derive_native_bitable_contract(task_fields: dict | None, workflow_fields: dict | None = None) -> dict[str, object]:
    fields = dict(task_fields or {})
    if workflow_fields:
        fields.update(workflow_fields)
    route = str(fields.get("工作流路由") or "").strip()
    status = str(fields.get("状态") or "").strip()
    pending_report = _boolish(fields.get("待发送汇报"))
    pending_approval = _boolish(fields.get("待拍板确认"))
    pending_execution = _boolish(fields.get("待执行确认"))
    pending_review = _boolish(fields.get("待安排复核"))
    pending_retro = _boolish(fields.get("待复盘确认"))
    in_retro = _boolish(fields.get("是否进入复盘"))
    archived = status == Status.ARCHIVED or str(fields.get("归档状态") or "").strip() == "已归档"

    if archived:
        current_role = "已归档"
        current_owner = "归档库"
        current_action = "归档沉淀"
    elif pending_approval:
        current_role = "拍板人"
        current_owner = _derive_approval_owner(fields, route) or "待指派"
        current_action = "管理拍板"
    elif pending_execution:
        current_role = "执行人"
        current_owner = _derive_execution_owner(fields, route) or "待指派"
        current_action = "执行落地"
    elif pending_review:
        current_role = "复核人"
        current_owner = _derive_review_owner(fields, route) or "待指派"
        current_action = "安排复核"
    elif pending_retro or in_retro:
        current_role = "复盘负责人"
        current_owner = _derive_retrospective_owner(fields, route) or "待指派"
        current_action = "进入复盘" if pending_retro else "归档沉淀"
    elif pending_report or route == "直接汇报" or (route == "等待拍板" and not pending_approval):
        current_role = "汇报对象"
        current_owner = str(fields.get("汇报对象") or fields.get("目标对象") or "").strip() or "待指派"
        current_action = "发送汇报"
    else:
        current_role = "系统调度"
        current_owner = "系统"
        current_action = "等待分析完成" if status != Status.COMPLETED else "归档沉淀"

    exception_status = "正常"
    exception_type = "无"
    exception_note = ""
    now = datetime.now(tz=timezone.utc)

    if pending_approval:
        approval_hours = _hours_from_now(fields.get("完成日期") or fields.get("最近更新"), now)
        if approval_hours >= 24:
            exception_status = "已异常"
            exception_type = "拍板滞留"
            exception_note = f"已等待拍板 {approval_hours} 小时"
    elif pending_execution:
        overdue_hours = _hours_overdue(fields.get("执行截止时间"), now)
        if overdue_hours > 0:
            exception_status = "已异常"
            exception_type = "执行超期"
            exception_note = f"执行已超期 {overdue_hours} 小时"
    elif pending_review:
        overdue_hours = _hours_overdue(fields.get("建议复核时间"), now)
        if overdue_hours > 0:
            exception_status = "已异常"
            exception_type = "复核超时"
            exception_note = f"复核已超时 {overdue_hours} 小时"
    elif pending_retro:
        retro_hours = _hours_from_now(fields.get("执行完成时间") or fields.get("最近更新"), now)
        if retro_hours >= 48:
            exception_status = "已异常"
            exception_type = "复盘滞留"
            exception_note = f"执行完成后 {retro_hours} 小时仍未进入复盘"

    if exception_type == "无" and current_role in {"汇报对象", "拍板人", "执行人", "复核人", "复盘负责人"}:
        if _is_unassigned_owner(current_owner):
            exception_status = "需关注"
            exception_type = "责任人待指派"
            exception_note = f"{current_role}尚未明确责任人"

    if status == Status.PENDING:
        automation_status = "未触发"
    elif status == Status.ANALYZING:
        automation_status = "执行中"
    elif archived or in_retro:
        automation_status = "已完成"
    elif exception_status == "已异常":
        automation_status = "失败"
    else:
        automation_status = "执行中"

    return {
        "业务归属": _derive_business_owner(fields),
        "汇报对象级别": _derive_audience_level(fields, route),
        "拍板负责人": _derive_approval_owner(fields, route),
        "复盘负责人": _derive_retrospective_owner(fields, route),
        "当前责任角色": current_role,
        "当前责任人": current_owner,
        "当前原生动作": current_action,
        "异常状态": exception_status,
        "异常类型": exception_type,
        "异常说明": exception_note,
        "自动化执行状态": automation_status,
    }


async def _resolve_template_defaults(
    app_token: str,
    template_tid: str | None,
    purpose: str = "",
    template_name: str = "",
) -> dict[str, object]:
    if not template_tid:
        return {}
    try:
        templates = await bitable_ops.list_records(app_token, template_tid, max_records=200)
    except Exception as exc:
        logger.warning("template defaults lookup failed app=%s: %s", app_token, exc)
        return {}

    normalized_name = template_name.strip()
    normalized_purpose = purpose.strip()
    exact_match: dict | None = None
    purpose_match: dict | None = None
    fallback_match: dict | None = None
    for row in templates:
        # v8.6.20-r10（审计 #1）：模板表 模板名称/适用输出目的 是 Text 字段，list_records
        # 偶尔返回富文本数组 [{"text":"...","type":"text"}]。直接 str(...)拿到字面量
        # "[{'text':'X',...}]"，跟 "X" 永不相等 → 模板永远不命中，整个模板中心功能
        # 在飞书返回 list 形态时静默失效。先拍平再比对。
        fields = _flatten_record_fields(row.get("fields") or {})
        if not bool(fields.get("启用")):
            continue
        row_name = str(fields.get("模板名称") or "").strip()
        row_purpose = str(fields.get("适用输出目的") or "").strip()
        if normalized_name and row_name == normalized_name:
            exact_match = fields
            break
        if normalized_purpose and row_purpose == normalized_purpose and purpose_match is None:
            purpose_match = fields
        if not row_purpose and fallback_match is None:
            fallback_match = fields
    selected = exact_match or purpose_match or fallback_match
    if not selected:
        return {}
    return {
        "template_name": str(selected.get("模板名称") or "").strip(),
        "report_audience": str(selected.get("默认汇报对象") or "").strip(),
        "report_audience_open_id": str(selected.get("默认汇报对象OpenID") or "").strip(),
        "approval_owner": str(selected.get("默认拍板负责人") or "").strip(),
        "approval_owner_open_id": str(selected.get("默认拍板负责人OpenID") or "").strip(),
        "execution_owner": str(selected.get("默认执行负责人") or "").strip(),
        "execution_owner_open_id": str(selected.get("默认执行负责人OpenID") or "").strip(),
        "review_owner": str(selected.get("默认复核负责人") or "").strip(),
        "review_owner_open_id": str(selected.get("默认复核负责人OpenID") or "").strip(),
        "retrospective_owner": str(selected.get("默认复盘负责人") or "").strip(),
        "retrospective_owner_open_id": str(selected.get("默认复盘负责人OpenID") or "").strip(),
        "review_sla_hours": _safe_int_field(selected.get("默认复核SLA小时")),
    }


def _template_context(
    task_title: str,
    task_fields: dict,
    route: str,
    review_fields: dict | None,
    ceo_result: AgentResult,
    decision_buckets: dict[str, list[str]],
) -> dict[str, str]:
    one_liner = _section_excerpt_by_keywords(ceo_result, ("核心结论", "管理摘要", "一段话"), 180)
    management_summary = _section_excerpt_by_keywords(ceo_result, ("管理摘要", "核心结论", "一段话"), 600)
    risk = _section_excerpt_by_keywords(ceo_result, ("重要风险",), 260)
    audience = str(task_fields.get("汇报对象") or task_fields.get("目标对象") or "").strip()
    execution_owner = _derive_execution_owner(task_fields, route)
    review_owner = _derive_review_owner(task_fields, route)
    return {
        "task_title": task_title,
        "route": route,
        "review_action": str((review_fields or {}).get("推荐动作") or "").strip(),
        "one_liner": one_liner,
        "management_summary": management_summary,
        "risk": risk,
        "audience": audience or "未指定",
        "execution_owner": execution_owner or "未指定",
        "review_owner": review_owner or "未指定",
        "execute_items": "；".join(decision_buckets["execute_now"][:3] or decision_buckets["delegated"][:3]) or "无",
        "decision_items": "；".join(decision_buckets["ceo_decision"][:3]) or "无",
        "need_data_items": "；".join(decision_buckets["need_data"][:3]) or "无",
    }


def _derive_workflow_route(
    review_fields: dict | None,
    ceo_result: AgentResult,
) -> tuple[str, dict[str, list[str]]]:
    decision_buckets = {
        "ceo_decision": [],
        "delegated": [],
        "need_data": [],
        "execute_now": [],
    }
    for item in ceo_result.decision_items:
        summary = str(item.get("summary") or "").strip()
        item_type = str(item.get("type") or "").strip().lower()
        if summary and item_type in decision_buckets:
            decision_buckets[item_type].append(summary)

    recommend = str((review_fields or {}).get("推荐动作") or "").strip()
    if recommend == "补数后复核":
        return "补数复核", decision_buckets
    if recommend == "建议重跑":
        return "重新分析", decision_buckets
    if decision_buckets["ceo_decision"]:
        return "等待拍板", decision_buckets
    if decision_buckets["execute_now"] or decision_buckets["delegated"]:
        return "直接执行", decision_buckets
    return "直接汇报", decision_buckets


def _base_route_transition_fields() -> dict[str, object]:
    return {
        "待发送汇报": False,
        "待创建执行任务": False,
        "待安排复核": False,
        "待拍板确认": False,
        "待执行确认": False,
        "待复盘确认": False,
        "建议复核时间": None,
        "执行截止时间": None,
    }


def _build_route_transition_fields(route: str, has_execution_items: bool, task_fields: dict | None = None) -> dict[str, object]:
    """构造路由切换后的互斥待办标记和时限字段。

    任何一次重新分析结果落回主流程时，都必须显式清理上一条路由遗留的
    `待安排复核 / 建议复核时间 / 待执行确认 / 执行截止时间` 等互斥状态，
    否则同一条任务会同时命中多个责任面视图。
    """
    task_fields = task_fields or {}
    now = datetime.now(tz=timezone.utc)
    review_at_ms: int | None = None
    execution_due_at_ms: int | None = None
    if route == "补数复核":
        review_at_ms = int((now + timedelta(hours=24)).timestamp() * 1000)
    elif route == "重新分析":
        review_at_ms = int((now + timedelta(hours=4)).timestamp() * 1000)
    elif route == "直接执行":
        execution_due_at_ms = task_fields.get("执行截止时间") or int((now + timedelta(hours=72)).timestamp() * 1000)

    transition = _base_route_transition_fields()
    transition.update(
        {
            "待发送汇报": route in {"直接汇报", "等待拍板"},
            "待创建执行任务": route == "直接执行" and has_execution_items,
            "待安排复核": route in {"补数复核", "重新分析"},
            "待拍板确认": route == "等待拍板",
            "待执行确认": route == "直接执行",
            "建议复核时间": review_at_ms,
            "执行截止时间": execution_due_at_ms,
        }
    )
    return transition


def _build_workflow_payload(
    task_title: str,
    task_fields: dict | None,
    review_fields: dict | None,
    ceo_result: AgentResult,
) -> dict:
    route, decision_buckets = _derive_workflow_route(review_fields, ceo_result)
    task_fields = task_fields or {}
    summary = _section_excerpt_by_keywords(ceo_result, ("管理摘要", "核心结论", "一段话"), 300)
    risk = _section_excerpt_by_keywords(ceo_result, ("重要风险",), 220)
    top_execute = decision_buckets["execute_now"][:2] or decision_buckets["delegated"][:2]
    top_decision = decision_buckets["ceo_decision"][:2]
    top_need_data = decision_buckets["need_data"][:2]
    recommend = str((review_fields or {}).get("推荐动作") or "").strip()

    message_lines = [
        f"任务：{task_title}",
        f"工作流路由：{route}",
        f"评审动作：{recommend or '未生成'}",
        f"管理摘要：{summary or '待补充'}",
    ]
    if top_decision:
        message_lines.append("需拍板：" + "；".join(top_decision))
    if top_execute:
        message_lines.append("建议执行：" + "；".join(top_execute))
    if top_need_data:
        message_lines.append("需补数：" + "；".join(top_need_data))
    if risk:
        message_lines.append(f"汇报风险：{risk}")

    execution_lines = [f"路由：{route}"]
    if top_decision:
        execution_lines.append("拍板项：\n" + "\n".join(f"- {item}" for item in top_decision))
    if top_execute:
        execution_lines.append("执行项：\n" + "\n".join(f"- {item}" for item in top_execute))
    if top_need_data:
        execution_lines.append("补数项：\n" + "\n".join(f"- {item}" for item in top_need_data))

    route_fields = _build_route_transition_fields(route, bool(top_execute), task_fields)
    payload = {
        "工作流路由": route,
        "工作流消息包": truncate_with_marker("\n".join(message_lines), 1800, "\n...[已截断]"),
        "工作流执行包": truncate_with_marker("\n\n".join(execution_lines), 1800, "\n...[已截断]"),
        **route_fields,
        "汇报对象": str(task_fields.get("汇报对象") or task_fields.get("目标对象") or "").strip(),
        "拍板负责人": _derive_approval_owner(task_fields, route),
        "执行负责人": _derive_execution_owner(task_fields, route),
        "复核负责人": _derive_review_owner(task_fields, route),
        "复盘负责人": _derive_retrospective_owner(task_fields, route),
        "复核SLA小时": _derive_review_sla_hours(task_fields, route),
    }
    payload.update(_derive_native_bitable_contract(task_fields, payload))
    return payload


async def _apply_template_config(
    app_token: str,
    template_tid: str | None,
    task_title: str,
    task_fields: dict,
    review_fields: dict | None,
    ceo_result: AgentResult,
    payload: dict,
) -> dict:
    if not template_tid:
        return payload
    try:
        templates = await bitable_ops.list_records(app_token, template_tid, max_records=200)
    except Exception as exc:
        logger.warning("template center lookup failed task=%s: %s", task_title, exc)
        return payload
    route = str(payload.get("工作流路由") or "").strip()
    purpose = str(task_fields.get("输出目的") or "").strip()
    selected_template_name = str(task_fields.get("套用模板") or "").strip()
    exact_match: dict | None = None
    matched: dict | None = None
    fallback: dict | None = None
    for row in templates:
        # v8.6.20-r10（审计 #1）：拍平避免富文本字面量误判
        fields = _flatten_record_fields(row.get("fields") or {})
        if not bool(fields.get("启用")):
            continue
        template_name = str(fields.get("模板名称") or "").strip()
        if selected_template_name and template_name == selected_template_name:
            exact_match = fields
            break
    if exact_match is not None:
        selected = exact_match
    else:
        for row in templates:
            fields = _flatten_record_fields(row.get("fields") or {})
            if not bool(fields.get("启用")):
                continue
            template_route = str(fields.get("适用工作流路由") or "").strip()
            template_purpose = str(fields.get("适用输出目的") or "").strip()
            if template_route != route:
                continue
            if template_purpose and template_purpose == purpose:
                matched = fields
                break
            if not template_purpose and fallback is None:
                fallback = fields
        selected = matched or fallback
    if not selected:
        return payload
    merged = dict(payload)
    merged["套用模板"] = str(selected.get("模板名称") or selected_template_name or "").strip()
    if not str(merged.get("汇报对象") or "").strip():
        merged["汇报对象"] = str(selected.get("默认汇报对象") or "").strip()
    if not str(merged.get("汇报对象OpenID") or "").strip():
        merged["汇报对象OpenID"] = str(selected.get("默认汇报对象OpenID") or "").strip()
    if not str(merged.get("拍板负责人") or "").strip():
        merged["拍板负责人"] = str(selected.get("默认拍板负责人") or "").strip()
    if not str(merged.get("拍板负责人OpenID") or "").strip():
        merged["拍板负责人OpenID"] = str(selected.get("默认拍板负责人OpenID") or "").strip()
    if not str(merged.get("执行负责人") or "").strip():
        merged["执行负责人"] = str(selected.get("默认执行负责人") or "").strip()
    if not str(merged.get("执行负责人OpenID") or "").strip():
        merged["执行负责人OpenID"] = str(selected.get("默认执行负责人OpenID") or "").strip()
    if not str(merged.get("复核负责人") or "").strip():
        merged["复核负责人"] = str(selected.get("默认复核负责人") or "").strip()
    if not str(merged.get("复核负责人OpenID") or "").strip():
        merged["复核负责人OpenID"] = str(selected.get("默认复核负责人OpenID") or "").strip()
    if not str(merged.get("复盘负责人") or "").strip():
        merged["复盘负责人"] = str(selected.get("默认复盘负责人") or "").strip()
    if not str(merged.get("复盘负责人OpenID") or "").strip():
        merged["复盘负责人OpenID"] = str(selected.get("默认复盘负责人OpenID") or "").strip()
    # v8.6.20-r9（审计 #7）：int(...) 对富文本/带单位字符串炸；统一用 _safe_int_field
    if _safe_int_field(merged.get("复核SLA小时")) <= 0:
        merged["复核SLA小时"] = _safe_int_field(selected.get("默认复核SLA小时"))
    route_buckets = _derive_workflow_route(review_fields, ceo_result)[1]
    template_task_fields = dict(task_fields)
    template_task_fields.update(
        {
            "汇报对象": merged.get("汇报对象") or task_fields.get("汇报对象"),
            "拍板负责人": merged.get("拍板负责人") or task_fields.get("拍板负责人"),
            "执行负责人": merged.get("执行负责人") or task_fields.get("执行负责人"),
            "复核负责人": merged.get("复核负责人") or task_fields.get("复核负责人"),
            "复盘负责人": merged.get("复盘负责人") or task_fields.get("复盘负责人"),
            "复核SLA小时": merged.get("复核SLA小时") or task_fields.get("复核SLA小时"),
        }
    )
    context = _template_context(task_title, template_task_fields, route, review_fields, ceo_result, route_buckets)
    report_template = str(selected.get("汇报模板") or "").strip()
    execute_template = str(selected.get("执行模板") or "").strip()
    if report_template:
        merged["工作流消息包"] = truncate_with_marker(_render_template_text(report_template, context), 1800, "\n...[已截断]")
    if execute_template:
        merged["工作流执行包"] = truncate_with_marker(_render_template_text(execute_template, context), 1800, "\n...[已截断]")
    merged.update(_derive_native_bitable_contract(task_fields, merged))
    return merged


def _build_task_delivery_snapshot(
    task_title: str,
    task_fields: dict | None,
    all_results: list[AgentResult],
    ceo_result: AgentResult,
    review_fields: dict | None,
    evidence_written: int,
) -> dict:
    all_with_ceo = all_results + [ceo_result]
    evidence_items = [
        item
        for result in all_with_ceo
        for item in (result.structured_evidence or [])
    ]
    high_confidence = sum(
        1
        for item in evidence_items
        if str(item.get("confidence") or "").strip().lower() == "high"
    )
    hard_evidence = sum(1 for item in evidence_items if _derive_evidence_grade(item) == "硬证据")
    pending_verify = sum(1 for item in evidence_items if _derive_evidence_grade(item) == "待验证")
    ceo_linked = sum(
        1
        for item in evidence_items
        if str(item.get("usage") or "").strip().lower() in {"opportunity", "risk", "decision"}
    )
    decision_count = len([item for item in ceo_result.decision_items if str(item.get("summary") or "").strip()])
    review_summary = ""
    review_action = ""
    readiness = 0
    need_data_count = 0
    if review_fields:
        review_summary = str(review_fields.get("评审摘要") or review_fields.get("评审结论") or "").strip()
        review_action = str(review_fields.get("推荐动作") or "").strip()
        # v8.6.20-r9（审计 #7）：Rating 字段在某些 sdk 路径下返回 dict {"value": 4}；
        # 用 _safe_int_field 兼容 dict/list/str/int。
        readiness_values = [
            _safe_int_field(review_fields.get("真实性")),
            _safe_int_field(review_fields.get("决策性")),
            _safe_int_field(review_fields.get("可执行性")),
            _safe_int_field(review_fields.get("闭环准备度")),
        ]
        readiness = round(sum(readiness_values) / len(readiness_values)) if all(readiness_values) else 0
        need_data_count = _count_bullets(review_fields.get("需补数事项"))

    management_summary = (
        _section_excerpt_by_keywords(ceo_result, ("管理摘要", "一段话"), 800)
        or _section_excerpt_by_keywords(ceo_result, ("核心结论",), 800)
        or truncate_with_marker(ceo_result.raw_output or "", 800, "\n...[已截断]")
    )
    workflow_payload = _build_workflow_payload(task_title, task_fields, review_fields, ceo_result)

    return {
        "最新评审动作": review_action,
        "最新评审摘要": truncate_with_marker(review_summary, 1500, "\n...[已截断]"),
        "最新管理摘要": truncate_with_marker(management_summary, 1500, "\n...[已截断]"),
        "汇报就绪度": readiness,
        "证据条数": evidence_written or len(evidence_items),
        "高置信证据数": high_confidence,
        "硬证据数": hard_evidence,
        "待验证证据数": pending_verify,
        "进入CEO汇总证据数": ceo_linked,
        "决策事项数": decision_count,
        "需补数条数": need_data_count,
        **workflow_payload,
    }


async def _sync_native_workflow_contracts(app_token: str, task_tid: str) -> None:
    """周期性刷新已完成/已归档任务的原生责任与异常契约字段。"""
    synced = 0
    for status in (Status.COMPLETED, Status.ARCHIVED):
        try:
            rows = await bitable_ops.list_records(
                app_token,
                task_tid,
                filter_expr=f'CurrentValue.[状态]="{status}"',
                page_size=100,
                max_records=200,
            )
        except Exception as exc:
            logger.warning("native contract sync lookup failed status=%s: %s", status, exc)
            continue
        for row in rows:
            record_id = row.get("record_id")
            if not record_id:
                continue
            fields = _flatten_record_fields(row.get("fields") or {})
            contract = _derive_native_bitable_contract(fields)
            changed = {
                key: value
                for key, value in contract.items()
                if str(fields.get(key) or "") != str(value or "")
            }
            if not changed:
                continue
            try:
                await bitable_ops.update_record_optional_fields(
                    app_token,
                    task_tid,
                    record_id,
                    changed,
                    optional_keys=list(contract.keys()),
                )
                synced += 1
            except Exception as exc:
                logger.warning("native contract sync failed record=%s: %s", record_id, exc)
    if synced:
        logger.info("Native Bitable contracts synced count=%d", synced)


async def _hydrate_task_dataset_reference(
    app_token: str,
    datasource_tid: str | None,
    fields: dict,
) -> dict:
    """若任务未直接提供「数据源」但填写了「引用数据集」，从数据源库回填原始 CSV。

    保持兼容：查不到时仅保留原字段，不抛异常。
    """
    if not datasource_tid:
        return fields
    if (fields.get("数据源") or "").strip():
        return fields
    dataset_name = str(fields.get("引用数据集") or "").strip()
    if not dataset_name:
        return fields
    try:
        filter_expr = f"CurrentValue.[数据集名称]={bitable_ops.quote_filter_value(dataset_name)}"
        rows = await bitable_ops.list_records(app_token, datasource_tid, filter_expr=filter_expr, max_records=1)
        if not rows:
            logger.info("Referenced dataset not found: %s", dataset_name)
            return fields
        ds_fields = rows[0].get("fields") or {}
        raw_csv = str(ds_fields.get("原始 CSV") or "").strip()
        field_doc = str(ds_fields.get("字段说明") or "").strip()
        source = str(ds_fields.get("数据来源") or "").strip()
        trust = str(ds_fields.get("可信等级") or "").strip()
        rendered = raw_csv
        if field_doc:
            rendered = f"字段说明：{field_doc}\n\n{rendered}"
        if source or trust:
            rendered = (
                f"数据资产：{dataset_name}\n"
                f"来源：{source or '未标注'}\n"
                f"可信等级：{trust or '未标注'}\n\n"
                f"{rendered}"
            )
        merged = dict(fields)
        if rendered:
            merged["数据源"] = rendered
        return merged
    except Exception as exc:
        logger.warning("hydrate dataset reference failed dataset=%s: %s", dataset_name, exc)
        return fields


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


async def _write_action_record(
    app_token: str,
    action_tid: str | None,
    task_title: str,
    action_type: str,
    action_status: str,
    route: str = "",
    content: str = "",
    result_text: str = "",
    record_id: str = "",
) -> None:
    if not action_tid:
        return
    fields = {
        "动作标题": f"{task_title} · {action_type}",
        "任务标题": task_title,
        "动作类型": action_type,
        "动作状态": action_status,
        "工作流路由": route,
        "动作内容": truncate_with_marker(content, 1800, "\n...[已截断]"),
        "执行结果": truncate_with_marker(result_text, 1800, "\n...[已截断]"),
        "关联记录ID": record_id,
    }
    try:
        await bitable_ops.create_record_optional_fields(
            app_token,
            action_tid,
            fields,
            optional_keys=["工作流路由", "执行结果", "关联记录ID"],
        )
    except Exception as exc:
        logger.warning("write action record failed task=%s type=%s: %s", task_title, action_type, exc)


async def _write_automation_log(
    app_token: str,
    automation_log_tid: str | None,
    task_title: str,
    node_name: str,
    status: str,
    route: str = "",
    trigger: str = "",
    summary: str = "",
    detail: str = "",
    record_id: str = "",
) -> None:
    if not automation_log_tid:
        return
    fields = {
        "日志标题": f"{task_title} · {node_name}",
        "任务标题": task_title,
        "节点名称": node_name,
        "触发来源": trigger,
        "执行状态": status,
        "工作流路由": route,
        "日志摘要": truncate_with_marker(summary, 1800, "\n...[已截断]"),
        "详细结果": truncate_with_marker(detail, 1800, "\n...[已截断]"),
        "关联记录ID": record_id,
    }
    try:
        await bitable_ops.create_record_optional_fields(
            app_token,
            automation_log_tid,
            fields,
            optional_keys=["工作流路由", "触发来源", "详细结果", "关联记录ID"],
        )
    except Exception as exc:
        logger.warning("write automation log failed task=%s node=%s: %s", task_title, node_name, exc)


async def _list_related_rows(
    app_token: str,
    table_id: str | None,
    *,
    task_title: str,
    record_id: str = "",
    max_records: int = 100,
) -> list[dict]:
    if not table_id:
        return []
    if record_id:
        safe_record_id = bitable_ops.quote_filter_value(record_id)
        return await bitable_ops.list_records(
            app_token,
            table_id,
            filter_expr=f"CurrentValue.[关联记录ID]={safe_record_id}",
            max_records=max_records,
        )
    safe_title = bitable_ops.quote_filter_value(task_title)
    return await bitable_ops.list_records(
        app_token,
        table_id,
        filter_expr=f"CurrentValue.[任务标题]={safe_title}",
        max_records=max_records,
    )


async def _write_review_history_record(
    app_token: str,
    review_history_tid: str | None,
    task_title: str,
    task_number: str,
    review_fields: dict | None,
    route: str = "",
    record_id: str = "",
) -> dict | None:
    if not review_history_tid or not review_fields:
        return None
    try:
        existing_rows = await _list_related_rows(
            app_token,
            review_history_tid,
            task_title=task_title,
            record_id=record_id,
            max_records=100,
        )
    except Exception as exc:
        logger.warning("review history lookup failed task=%s: %s", task_title, exc)
        existing_rows = []
    round_no = len(existing_rows) + 1
    prev_action = ""
    if existing_rows:
        latest = max(existing_rows, key=lambda row: str((row.get("fields") or {}).get("生成时间") or ""))
        prev_action = str((latest.get("fields") or {}).get("推荐动作") or "").strip()
    current_action = str(review_fields.get("推荐动作") or "").strip()
    if prev_action and prev_action != current_action:
        diff_summary = f"前次推荐动作：{prev_action}；本次推荐动作：{current_action}"
    elif prev_action:
        diff_summary = f"与前次一致：{current_action}"
    else:
        diff_summary = "首轮评审，无前次复核结果"
    fields = {
        "复核标题": f"{task_title} · 第{round_no}轮复核",
        "任务标题": task_title,
        "任务编号": task_number,
        "复核轮次": float(round_no),
        "推荐动作": current_action,
        "工作流路由": route,
        "触发原因": str(review_fields.get("评审摘要") or review_fields.get("评审结论") or "").strip(),
        "复核结论": str(review_fields.get("评审结论") or "").strip(),
        "前次评审动作": prev_action,
        "新旧结论差异": diff_summary,
        "需补数事项": str(review_fields.get("需补数事项") or "").strip(),
        "关联记录ID": record_id,
    }
    new_record_id = await bitable_ops.create_record_optional_fields(
        app_token,
        review_history_tid,
        fields,
        optional_keys=["任务编号", "工作流路由", "前次评审动作", "需补数事项", "关联记录ID"],
    )
    return {"record_id": new_record_id, "round": round_no, "fields": fields}


async def _write_delivery_archive_record(
    app_token: str,
    archive_tid: str | None,
    task_title: str,
    task_number: str,
    task_fields: dict,
    delivery_snapshot: dict,
    ceo_result: AgentResult,
    route: str,
    record_id: str = "",
) -> dict | None:
    if not archive_tid:
        return None
    try:
        existing_rows = await _list_related_rows(
            app_token,
            archive_tid,
            task_title=task_title,
            record_id=record_id,
            max_records=100,
        )
    except Exception as exc:
        logger.warning("delivery archive lookup failed task=%s: %s", task_title, exc)
        existing_rows = []
    version_no = len(existing_rows) + 1
    version = f"v{version_no}"
    archive_status = _derive_archive_status(route)
    fields = {
        "归档标题": f"{task_title} · {version}",
        "任务标题": task_title,
        "任务编号": task_number,
        "汇报版本号": version,
        "工作流路由": route,
        "归档状态": archive_status,
        "最新评审动作": str(delivery_snapshot.get("最新评审动作") or "").strip(),
        "一句话结论": truncate_with_marker(
            _section_excerpt_by_keywords(ceo_result, ("核心结论", "管理摘要", "一段话"), 240)
            or str(delivery_snapshot.get("最新管理摘要") or ""),
            500,
            "\n...[已截断]",
        ),
        "管理摘要": truncate_with_marker(str(delivery_snapshot.get("最新管理摘要") or ""), 1500, "\n...[已截断]"),
        "首要动作": truncate_with_marker(
            _section_excerpt_by_keywords(ceo_result, ("首要动作",), 240)
            or (ceo_result.action_items[0] if ceo_result.action_items else ""),
            500,
            "\n...[已截断]",
        ),
        "汇报就绪度": float(delivery_snapshot.get("汇报就绪度") or 0),
        "工作流消息包": truncate_with_marker(str(delivery_snapshot.get("工作流消息包") or ""), 1500, "\n...[已截断]"),
        "汇报对象": str(task_fields.get("汇报对象") or task_fields.get("目标对象") or "").strip(),
        "执行负责人": str(task_fields.get("执行负责人") or "").strip(),
        "复核负责人": str(task_fields.get("复核负责人") or "").strip(),
        "关联记录ID": record_id,
    }
    archive_record_id = await bitable_ops.create_record_optional_fields(
        app_token,
        archive_tid,
        fields,
        optional_keys=[
            "任务编号",
            "汇报版本号",
            "工作流路由",
            "归档状态",
            "最新评审动作",
            "一句话结论",
            "首要动作",
            "汇报对象",
            "执行负责人",
            "复核负责人",
            "关联记录ID",
        ],
    )
    return {
        "record_id": archive_record_id,
        "version": version,
        "archive_status": archive_status,
        "fields": fields,
    }


async def _send_completion_message(
    app_token: str,
    task_tid: str,
    rid: str,
    task_title: str,
    ceo_result: AgentResult,
    action_tid: str | None = None,
    automation_log_tid: str | None = None,
    route: str = "",
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
        await _write_action_record(
            app_token,
            action_tid,
            task_title,
            "发送汇报",
            "已完成",
            route=route,
            content=summary,
            result_text=f"已发送飞书卡片消息，跳转 {url}",
            record_id=rid,
        )
        await _write_automation_log(
            app_token,
            automation_log_tid,
            task_title,
            "飞书消息通知",
            "已完成",
            route=route,
            trigger="任务完成",
            summary="已发送飞书卡片消息",
            detail=url,
            record_id=rid,
        )
        logger.info("Feishu card sent for task [%s] url=%s", task_title, url)
    except ValueError:
        await _write_action_record(
            app_token,
            action_tid,
            task_title,
            "发送汇报",
            "已跳过",
            route=route,
            content="未配置飞书群 ID，跳过消息发送",
            record_id=rid,
        )
        await _write_automation_log(
            app_token,
            automation_log_tid,
            task_title,
            "飞书消息通知",
            "已跳过",
            route=route,
            trigger="任务完成",
            summary="未配置飞书群 ID，跳过发送",
            record_id=rid,
        )
        logger.debug("feishu_chat_id not configured, skipping notification for task [%s]", task_title)
    except Exception as exc:
        await _write_action_record(
            app_token,
            action_tid,
            task_title,
            "发送汇报",
            "执行失败",
            route=route,
            content="飞书卡片消息发送失败",
            result_text=str(exc),
            record_id=rid,
        )
        await _write_automation_log(
            app_token,
            automation_log_tid,
            task_title,
            "飞书消息通知",
            "执行失败",
            route=route,
            trigger="任务完成",
            summary="飞书卡片消息发送失败",
            detail=str(exc),
            record_id=rid,
        )
        logger.warning("Feishu notification failed for task [%s]: %s", task_title, exc)


async def _create_followup_tasks(
    app_token: str,
    task_tid: str,
    task_title: str,
    ceo_result: AgentResult,
    template_tid: str | None = None,
    parent_task_number: str | None = None,
    action_tid: str | None = None,
    automation_log_tid: str | None = None,
    route: str = "",
) -> None:
    """将 CEO 助理行动项转化为新的「待分析」任务，实现业务闭环（再流转）。

    同时尝试通过飞书任务 API 创建待办事项，方便在飞书中直接跟进。
    只取前 3 条非空行动项；跟进任务本身不再生成二级跟进，避免无限循环。

    parent_task_number: 原任务的「任务编号」（AutoNumber 字段值），自动写入
      跟进任务的「依赖任务编号」字段，构建任务依赖图（v8.6.7 新增）。
    """
    if task_title.startswith("[跟进]"):
        return

    def _classify_followup(summary: str, explicit_type: str = "") -> str:
        t = (explicit_type or "").strip().lower()
        if t in {"need_data", "ceo_decision", "execute_now", "delegated"}:
            return t
        s = summary.lower()
        if any(key in s for key in ["补数", "补齐", "核验", "确认数据", "拉取数据", "验证口径"]):
            return "need_data"
        if any(key in s for key in ["拍板", "审批", "预算", "定价", "资源投入", "是否批准"]):
            return "ceo_decision"
        if any(key in s for key in ["本周启动", "立即执行", "发布", "上线", "通知", "推进"]):
            return "execute_now"
        return "delegated"

    followups: list[tuple[str, str]] = []
    if ceo_result.decision_items:
        for item in ceo_result.decision_items:
            summary = str(item.get("summary") or "").strip()
            if not summary:
                continue
            followups.append((summary, _classify_followup(summary, str(item.get("type") or ""))))
    else:
        # v8.6.4 修复：CEO 助理把"管理摘要"文本以 "[摘要] ..." 形式插入 action_items[0]
        # （便于飞书消息推送）。如果直接拿来当跟进任务标题，会得到 "[跟进] [摘要] 当前公司面临..."
        # 这种语义混乱的二级任务 — 用户在表里看到一堆"[跟进] [摘要]"开头的废任务。
        # 这里显式过滤掉 [摘要] 前缀的元素。
        for item in ceo_result.action_items or []:
            summary = item.strip()
            if not summary or summary.startswith("[摘要]"):
                continue
            followups.append((summary, _classify_followup(summary)))

    followups = followups[:3]
    if not followups:
        logger.debug("No action items for follow-up from task [%s]", task_title)
        return

    execution_items = [summary for summary, kind in followups if kind in {"execute_now", "delegated"}]
    analysis_items = [
        (summary, kind) for summary, kind in followups
        if kind in {"need_data", "ceo_decision", "delegated"}
    ]
    should_create_execution_tasks = route == "直接执行" and bool(execution_items)

    # 1. 写入飞书任务 API（待办事项），便于在飞书客户端直接追踪
    try:
        from app.feishu.task import batch_create_tasks
        if should_create_execution_tasks:
            await batch_create_tasks(execution_items)
            await _write_action_record(
                app_token,
                action_tid,
                task_title,
                "创建执行任务",
                "已完成",
                route=route,
                content="\n".join(f"- {item}" for item in execution_items),
                result_text=f"已创建 {len(execution_items)} 条飞书任务",
            )
            await _write_automation_log(
                app_token,
                automation_log_tid,
                task_title,
                "执行任务创建",
                "已完成",
                route=route,
                trigger="工作流执行包",
                summary=f"已创建 {len(execution_items)} 条飞书任务",
                detail="\n".join(execution_items),
            )
            logger.info("Created %d Feishu tasks for [%s]", len(execution_items), task_title)
        elif execution_items:
            logger.info(
                "Skip Feishu task creation for [%s]: route=%s execution_items=%d",
                task_title,
                route or "未指定",
                len(execution_items),
            )
    except Exception as exc:
        await _write_action_record(
            app_token,
            action_tid,
            task_title,
            "创建执行任务",
            "执行失败",
            route=route,
            content="\n".join(f"- {item}" for item in execution_items),
            result_text=str(exc),
        )
        await _write_automation_log(
            app_token,
            automation_log_tid,
            task_title,
            "执行任务创建",
            "执行失败",
            route=route,
            trigger="工作流执行包",
            summary="创建飞书任务失败",
            detail=str(exc),
        )
        logger.warning("Feishu task API failed for [%s]: %s", task_title, exc)

    # 2. 在「分析任务」表中只为需要继续分析/补数/决策的事项生成后续记录
    from app.bitable_workflow import schema as _schema
    import hashlib as _hashlib
    for item, kind in analysis_items:
        purpose = "补数核验" if kind == "need_data" else "管理决策"
        # v8.6.20-r10（审计 #8）：之前 truncate_with_marker(item, 50) 让两个前 42
        # 字符相同的 decision_items 崩塌成同一 followup_title — dedupe lookup 把
        # 第二条当成"重复"silently 丢弃，造成数据丢失。给标题尾部加 #6 位 sha1
        # 摘要确保唯一性，dedupe 仍能精确命中真重复（同 item 必同 hash）。
        item_hash = _hashlib.sha1(str(item).encode("utf-8")).hexdigest()[:6]
        title_body = truncate_with_marker(item, 42, "...")
        followup_title = f"[跟进] {title_body} #{item_hash}"
        try:
            safe_title = bitable_ops.quote_filter_value(followup_title)
            existing_rows = await bitable_ops.list_records(
                app_token,
                task_tid,
                filter_expr=f"CurrentValue.[任务标题]={safe_title}",
                max_records=20,
            )
            # v8.6.20-r6：审计 #13 — 状态 SingleSelect 在某些 search_records 路径
            # 会返回 dict/list，直接 in 比对会漏掉，导致 dedupe 失效。先拍平再比。
            def _row_status(row: dict) -> str:
                raw = (row.get("fields") or {}).get("状态")
                if isinstance(raw, dict):
                    raw = raw.get("text") or raw.get("name") or ""
                return _flatten_text_value(raw) if not isinstance(raw, str) else raw

            duplicate_row = next(
                (row for row in existing_rows if _row_status(row) in {Status.PENDING, Status.ANALYZING}),
                None,
            )
            if duplicate_row:
                logger.info(
                    "Skip duplicate follow-up task for [%s], existing record=%s status=%s",
                    task_title,
                    duplicate_row.get("record_id"),
                    (duplicate_row.get("fields") or {}).get("状态"),
                )
                await _write_action_record(
                    app_token,
                    action_tid,
                    task_title,
                    "自动跟进任务",
                    "已跳过",
                    route=route,
                    content=f"已存在未关闭跟进任务：{followup_title}",
                    record_id=duplicate_row.get("record_id") or "",
                )
                await _write_automation_log(
                    app_token,
                    automation_log_tid,
                    task_title,
                    "跟进任务创建",
                    "已跳过",
                    route=route,
                    trigger="CEO 助理行动项",
                    summary=f"已存在未关闭跟进任务：{followup_title}",
                    record_id=duplicate_row.get("record_id") or "",
                )
                continue
        except Exception as exc:
            logger.warning("Follow-up dedupe lookup failed for [%s]: %s", task_title, exc)
        record_fields: dict = {
            "任务标题": followup_title,
            "分析维度": "综合分析",
            "优先级": "P2 中",
            "输出目的": purpose,
            "任务来源": "跟进任务",
            "业务归属": "综合经营",
            "汇报对象级别": "负责人",
            "状态": Status.PENDING,
            "进度": 0,
            "背景说明": f"由任务「{task_title}」的CEO助理决策建议自动生成（类型：{kind}）",
            "自动化执行状态": "未触发",
            # v8.6.20：跟进任务也填综合评分（由 priority_score 算出）
            "综合评分": _schema.priority_score("P2 中"),
        }
        template_defaults = await _resolve_template_defaults(
            app_token,
            template_tid,
            purpose=purpose,
        )
        if template_defaults.get("template_name"):
            record_fields["套用模板"] = str(template_defaults["template_name"])
        if template_defaults.get("report_audience"):
            record_fields["汇报对象"] = str(template_defaults["report_audience"])
        if template_defaults.get("report_audience_open_id"):
            record_fields["汇报对象OpenID"] = str(template_defaults["report_audience_open_id"])
        if template_defaults.get("approval_owner"):
            record_fields["拍板负责人"] = str(template_defaults["approval_owner"])
        if template_defaults.get("approval_owner_open_id"):
            record_fields["拍板负责人OpenID"] = str(template_defaults["approval_owner_open_id"])
        if template_defaults.get("execution_owner"):
            record_fields["执行负责人"] = str(template_defaults["execution_owner"])
        if template_defaults.get("execution_owner_open_id"):
            record_fields["执行负责人OpenID"] = str(template_defaults["execution_owner_open_id"])
        if template_defaults.get("review_owner"):
            record_fields["复核负责人"] = str(template_defaults["review_owner"])
        if template_defaults.get("review_owner_open_id"):
            record_fields["复核负责人OpenID"] = str(template_defaults["review_owner_open_id"])
        if template_defaults.get("retrospective_owner"):
            record_fields["复盘负责人"] = str(template_defaults["retrospective_owner"])
        if template_defaults.get("retrospective_owner_open_id"):
            record_fields["复盘负责人OpenID"] = str(template_defaults["retrospective_owner_open_id"])
        # v8.6.20-r9（审计 #7）：用 _safe_int_field 防 list/带单位字符串
        if _safe_int_field(template_defaults.get("review_sla_hours")) > 0:
            record_fields["复核SLA小时"] = _safe_int_field(template_defaults.get("review_sla_hours"))
        # v8.6.7：跟进任务自动指向原任务，构建依赖图
        if parent_task_number:
            record_fields["依赖任务编号"] = str(parent_task_number)
        try:
            # v8.6.20：综合评分老 base 没有 → optional fallback
            new_record_id = await bitable_ops.create_record_optional_fields(
                app_token,
                task_tid,
                record_fields,
                optional_keys=[
                    "综合评分",
                    "任务来源",
                    "业务归属",
                    "汇报对象级别",
                    "自动化执行状态",
                    "套用模板",
                    "汇报对象",
                    "汇报对象OpenID",
                    "拍板负责人",
                    "拍板负责人OpenID",
                    "执行负责人",
                    "执行负责人OpenID",
                    "复核负责人",
                    "复核负责人OpenID",
                    "复盘负责人",
                    "复盘负责人OpenID",
                    "复核SLA小时",
                ],
            )
            await _write_action_record(
                app_token,
                action_tid,
                task_title,
                "自动跟进任务",
                "已完成",
                route=route,
                content=item,
                result_text=f"已创建后续分析任务：{record_fields['任务标题']}",
                record_id=new_record_id,
            )
            logger.info(
                "Follow-up task created from [%s]: %s",
                task_title,
                truncate_with_marker(item, 50, "...[截断]"),
            )
        except Exception as exc:
            await _write_action_record(
                app_token,
                action_tid,
                task_title,
                "自动跟进任务",
                "执行失败",
                route=route,
                content=item,
                result_text=str(exc),
            )
            logger.warning("Failed to create follow-up task from [%s]: %s", task_title, exc)


async def _create_review_recheck_task(
    app_token: str,
    task_tid: str,
    task_title: str,
    review_fields: dict | None,
    template_tid: str | None = None,
    parent_task_number: str | None = None,
    action_tid: str | None = None,
    automation_log_tid: str | None = None,
    route: str = "",
) -> None:
    """当 reviewer 判定需要补数/重跑时，生成单条复核任务。"""
    if not review_fields:
        return
    recommend = str(review_fields.get("推荐动作") or "").strip()
    if recommend not in {"补数后复核", "建议重跑"}:
        return
    need_data = str(review_fields.get("需补数事项") or "").strip()
    summary = (
        f"根据自动评审结果对任务《{task_title}》进行"
        + ("补数复核" if recommend == "补数后复核" else "重新分析")
    )
    recheck_title = f"[复核] {truncate_with_marker(task_title, 40, '...[截断]')}"
    try:
        safe_title = bitable_ops.quote_filter_value(recheck_title)
        existing_rows = await bitable_ops.list_records(
            app_token,
            task_tid,
            filter_expr=f"CurrentValue.[任务标题]={safe_title}",
            max_records=20,
        )
        for row in existing_rows:
            fields = row.get("fields") or {}
            if fields.get("状态") in {Status.PENDING, Status.ANALYZING}:
                logger.info(
                    "Skip duplicate review recheck task for [%s], existing record=%s status=%s",
                    task_title,
                    row.get("record_id"),
                    fields.get("状态"),
                )
                await _write_action_record(
                    app_token,
                    action_tid,
                    task_title,
                    "创建复核任务",
                    "已跳过",
                    route=route,
                    content=f"已存在未关闭复核任务：{recheck_title}",
                    record_id=row.get("record_id") or "",
                )
                await _write_automation_log(
                    app_token,
                    automation_log_tid,
                    task_title,
                    "复核任务创建",
                    "已跳过",
                    route=route,
                    trigger="评审推荐动作",
                    summary=f"已存在未关闭复核任务：{recheck_title}",
                    record_id=row.get("record_id") or "",
                )
                return
    except Exception as exc:
        logger.warning("Review recheck dedupe lookup failed for [%s]: %s", task_title, exc)
    background = truncate_with_marker(
        summary + (f"\n\n重点补充：\n{need_data}" if need_data else ""),
        1800,
        "\n...[已截断]",
    )
    from app.bitable_workflow import schema as _schema
    fields = {
        "任务标题": recheck_title,
        "分析维度": "综合分析",
        "优先级": "P1 高" if recommend == "补数后复核" else "P0 紧急",
        "输出目的": "补数核验" if recommend == "补数后复核" else "管理决策",
        "任务来源": "复核任务",
        "业务归属": "综合经营",
        "汇报对象级别": "负责人",
        "状态": Status.PENDING,
        "进度": 0,
        "背景说明": background,
        "成功标准": "补齐关键缺失证据并给出可直接采用的结论",
        "自动化执行状态": "未触发",
        "综合评分": _schema.priority_score("P1 高" if recommend == "补数后复核" else "P0 紧急"),
    }
    template_defaults = await _resolve_template_defaults(
        app_token,
        template_tid,
        purpose=str(fields.get("输出目的") or ""),
    )
    if template_defaults.get("template_name"):
        fields["套用模板"] = str(template_defaults["template_name"])
    if template_defaults.get("report_audience"):
        fields["汇报对象"] = str(template_defaults["report_audience"])
    if template_defaults.get("report_audience_open_id"):
        fields["汇报对象OpenID"] = str(template_defaults["report_audience_open_id"])
    if template_defaults.get("approval_owner"):
        fields["拍板负责人"] = str(template_defaults["approval_owner"])
    if template_defaults.get("approval_owner_open_id"):
        fields["拍板负责人OpenID"] = str(template_defaults["approval_owner_open_id"])
    if template_defaults.get("execution_owner"):
        fields["执行负责人"] = str(template_defaults["execution_owner"])
    if template_defaults.get("execution_owner_open_id"):
        fields["执行负责人OpenID"] = str(template_defaults["execution_owner_open_id"])
    if template_defaults.get("review_owner"):
        fields["复核负责人"] = str(template_defaults["review_owner"])
    if template_defaults.get("review_owner_open_id"):
        fields["复核负责人OpenID"] = str(template_defaults["review_owner_open_id"])
    if template_defaults.get("retrospective_owner"):
        fields["复盘负责人"] = str(template_defaults["retrospective_owner"])
    if template_defaults.get("retrospective_owner_open_id"):
        fields["复盘负责人OpenID"] = str(template_defaults["retrospective_owner_open_id"])
    # v8.6.20-r9（审计 #7）
    if _safe_int_field(template_defaults.get("review_sla_hours")) > 0:
        fields["复核SLA小时"] = _safe_int_field(template_defaults.get("review_sla_hours"))
    if parent_task_number:
        fields["依赖任务编号"] = str(parent_task_number)
    fields.update(_derive_native_bitable_contract(fields))
    try:
        new_record_id = await bitable_ops.create_record_optional_fields(
            app_token,
            task_tid,
            fields,
            optional_keys=[
                "任务来源",
                "业务归属",
                "汇报对象级别",
                "输出目的",
                "成功标准",
                "自动化执行状态",
                "综合评分",
                "套用模板",
                "汇报对象",
                "汇报对象OpenID",
                "拍板负责人",
                "拍板负责人OpenID",
                "执行负责人",
                "执行负责人OpenID",
                "复核负责人",
                "复核负责人OpenID",
                "复盘负责人",
                "复盘负责人OpenID",
                "复核SLA小时",
                "当前责任角色",
                "当前责任人",
                "当前原生动作",
                "异常状态",
                "异常类型",
                "异常说明",
            ],
        )
        await _write_action_record(
            app_token,
            action_tid,
            task_title,
            "创建复核任务",
            "已完成",
            route=route,
            content=background,
            result_text=f"已创建复核任务：{fields['任务标题']}",
            record_id=new_record_id,
        )
        await _write_automation_log(
            app_token,
            automation_log_tid,
            task_title,
            "复核任务创建",
            "已完成",
            route=route,
            trigger="评审推荐动作",
            summary=f"已创建复核任务：{fields['任务标题']}",
            detail=background,
            record_id=new_record_id,
        )
        logger.info("Review recheck task created for [%s] recommend=%s", task_title, recommend)
    except Exception as exc:
        await _write_action_record(
            app_token,
            action_tid,
            task_title,
            "创建复核任务",
            "执行失败",
            route=route,
            content=background,
            result_text=str(exc),
        )
        await _write_automation_log(
            app_token,
            automation_log_tid,
            task_title,
            "复核任务创建",
            "执行失败",
            route=route,
            trigger="评审推荐动作",
            summary="创建复核任务失败",
            detail=str(exc),
        )
        logger.warning("Failed to create review recheck task for [%s]: %s", task_title, exc)


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
        # v8.6.20-r8 BLOCKER 修复：之前用 FIRST_EXCEPTION，但 _renew_cycle_lock 是
        # while True 永远不会主动 done，FIRST_EXCEPTION 在 cycle 干净完成（无异常）时
        # 会等到 ALL_COMPLETED — 导致每次成功 cycle 后整个 loop 永远 hang，没有第二轮。
        # 改为 FIRST_COMPLETED：cycle 一完就返回，下面的 if renew_task in done 仍能
        # 捕获 renew 早死场景（renew 异常也会让它进 done）。
        done, _pending = await asyncio.wait(
            {cycle_task, renew_task},
            return_when=asyncio.FIRST_COMPLETED,
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
    datasource_tid = table_ids.get("datasource")
    evidence_tid = table_ids.get("evidence")
    review_tid = table_ids.get("review")
    action_tid = table_ids.get("action")
    review_history_tid = table_ids.get("review_history")
    archive_tid = table_ids.get("archive")
    automation_log_tid = table_ids.get("automation_log")
    template_tid = table_ids.get("template")
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

    # Phase 0.5: 同步已完成任务的原生责任/异常字段，让多维表格视图和自动化直接消费主表
    await _sync_native_workflow_contracts(app_token, task_tid)

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
            fields = await _hydrate_task_dataset_reference(app_token, datasource_tid, fields)

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

            evidence_written = 0
            if evidence_tid:
                evidence_written = await write_evidence_records(
                    app_token, evidence_tid, task_title, all_results + [ceo_result]
                )
                if evidence_written <= 0:
                    logger.warning("No evidence rows were written for task=%s", task_title)

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
            review_payload: dict | None = None
            if performance_tid:
                await update_performance(
                    app_token, performance_tid, all_results + [ceo_result]
                )
            if review_tid:
                review_payload = await write_review_record(
                    app_token, review_tid, task_title, all_results, ceo_result,
                )

            delivery_snapshot = _build_task_delivery_snapshot(
                task_title,
                fields,
                all_results,
                ceo_result,
                (review_payload or {}).get("fields"),
                evidence_written,
            )
            delivery_snapshot = await _apply_template_config(
                app_token,
                template_tid,
                task_title,
                fields,
                (review_payload or {}).get("fields"),
                ceo_result,
                delivery_snapshot,
            )
            workflow_route = str(delivery_snapshot.get("工作流路由") or "").strip()

            task_number = _extract_task_number(fields.get("任务编号"))
            review_history_payload = await _write_review_history_record(
                app_token,
                review_history_tid,
                task_title,
                task_number,
                (review_payload or {}).get("fields"),
                route=workflow_route,
                record_id=rid,
            )
            if review_history_payload:
                await _write_automation_log(
                    app_token,
                    automation_log_tid,
                    task_title,
                    "复核历史沉淀",
                    "已完成",
                    route=workflow_route,
                    trigger="评审结果",
                    summary=f"已写入第 {review_history_payload['round']} 轮复核历史",
                    record_id=review_history_payload["record_id"],
                )
            archive_payload = await _write_delivery_archive_record(
                app_token,
                archive_tid,
                task_title,
                task_number,
                fields,
                delivery_snapshot,
                ceo_result,
                workflow_route,
                record_id=rid,
            )
            if archive_payload:
                await _write_automation_log(
                    app_token,
                    automation_log_tid,
                    task_title,
                    "交付归档沉淀",
                    "已完成",
                    route=workflow_route,
                    trigger="任务完成",
                    summary=f"已写入交付归档版本 {archive_payload['version']}",
                    record_id=archive_payload["record_id"],
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
            # v8.6.20-r10（审计 #4）：完成时间(Text) 和 完成日期(DateTime ms) 必须
            # 来自同一时刻，且文本字段用北京时间（用户阅读）。之前完成时间用 naive
            # datetime.now() 跟着服务器 tz 走，UTC 部署下两字段相差 8 小时。
            _complete_now_utc = datetime.now(tz=timezone.utc)
            try:
                from zoneinfo import ZoneInfo as _Zone
                _complete_now_local = _complete_now_utc.astimezone(_Zone("Asia/Shanghai"))
            except Exception:
                _complete_now_local = _complete_now_utc.astimezone(timezone(timedelta(hours=8)))
            # 老 base 缺「完成日期」时 update_record_optional_fields 自动 fallback 仅写完成时间
            await bitable_ops.update_record_optional_fields(
                app_token,
                task_tid,
                rid,
                {
                    "状态": Status.COMPLETED,
                    "当前阶段": "✅ 七岗分析全部完成",
                    "进度": 1.0,
                    "完成时间": _complete_now_local.strftime("%Y-%m-%d %H:%M"),
                    "完成日期": int(_complete_now_utc.timestamp() * 1000),
                    "汇报版本号": (archive_payload or {}).get("version") or "v1",
                    "归档状态": (archive_payload or {}).get("archive_status") or _derive_archive_status(workflow_route),
                    **delivery_snapshot,
                },
                optional_keys=[
                    "完成日期",
                    "最新评审动作",
                    "最新评审摘要",
                    "最新管理摘要",
                    "汇报就绪度",
                    "证据条数",
                    "高置信证据数",
                    "硬证据数",
                    "待验证证据数",
                    "进入CEO汇总证据数",
                    "决策事项数",
                    "需补数条数",
                    "工作流路由",
                    "套用模板",
                    "工作流消息包",
                    "工作流执行包",
                    "待发送汇报",
                    "待创建执行任务",
                    "待安排复核",
                    "待拍板确认",
                    "待执行确认",
                    "待复盘确认",
                    "建议复核时间",
                    "业务归属",
                    "汇报对象",
                    "汇报对象级别",
                    "拍板负责人",
                    "执行负责人",
                    "执行截止时间",
                    "复核负责人",
                    "复盘负责人",
                    "复核SLA小时",
                    "当前责任角色",
                    "当前责任人",
                    "当前原生动作",
                    "异常状态",
                    "异常类型",
                    "异常说明",
                    "自动化执行状态",
                    "汇报版本号",
                    "归档状态",
                ],
            )
            processed += 1
            logger.info("Task [%s] completed by 7-agent pipeline", task_title)

            await _write_action_record(
                app_token,
                action_tid,
                task_title,
                "工作流记录",
                "已完成",
                route=workflow_route,
                content=truncate_with_marker(
                    "\n".join(
                        [
                            f"工作流路由：{workflow_route or '未生成'}",
                            f"证据条数：{delivery_snapshot.get('证据条数') or 0}",
                            f"高置信证据数：{delivery_snapshot.get('高置信证据数') or 0}",
                            f"硬证据数：{delivery_snapshot.get('硬证据数') or 0}",
                            f"待验证证据数：{delivery_snapshot.get('待验证证据数') or 0}",
                            f"决策事项数：{delivery_snapshot.get('决策事项数') or 0}",
                            f"需补数条数：{delivery_snapshot.get('需补数条数') or 0}",
                        ]
                    ),
                    1800,
                    "\n...[已截断]",
                ),
                result_text=delivery_snapshot.get("工作流消息包") or "",
                record_id=rid,
            )

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
            await _send_completion_message(
                app_token,
                task_tid,
                rid,
                task_title,
                ceo_result,
                action_tid=action_tid,
                automation_log_tid=automation_log_tid,
                route=workflow_route,
            )

            # 反馈再流转：CEO 行动项 → 新的待分析任务（自动 set 依赖任务编号 = 原任务编号）
            parent_num = task_number or None
            await _create_followup_tasks(
                app_token, task_tid, task_title, ceo_result,
                template_tid=template_tid,
                parent_task_number=parent_num,
                action_tid=action_tid,
                automation_log_tid=automation_log_tid,
                route=workflow_route,
            )
            await _create_review_recheck_task(
                app_token,
                task_tid,
                task_title,
                (review_payload or {}).get("fields"),
                template_tid=template_tid,
                parent_task_number=parent_num,
                action_tid=action_tid,
                automation_log_tid=automation_log_tid,
                route=workflow_route,
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
