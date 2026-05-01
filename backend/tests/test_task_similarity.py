"""v8.6.20-r40: 跨任务相似度检索回归。

锁定契约：
1. _tokenize 处理中英混合 + CJK 逐字 + 停用词过滤 + ASCII 单词整体
2. _jaccard 边界（空集 / 完全相同 / 完全不交）
3. score_similarity 加权：title × 2 + dimension × 0.5 + background × 0.3
4. find_similar_completed_tasks 返回 top_k 排序 + min_score 过滤
5. /similar 端点：base 未 setup 返 409；正常返 matches 列表
6. 富文本数组 [{text:"..."}] 拍平后正确参与匹配
"""
from __future__ import annotations

from types import ModuleType
import sys

import pytest


def _ensure_sse_stub(monkeypatch):
    sse_pkg = ModuleType("sse_starlette")
    sse_mod = ModuleType("sse_starlette.sse")
    sse_mod.EventSourceResponse = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sse_starlette", sse_pkg)
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_mod)


# ---------- 单元：分词 ----------


def test_tokenize_handles_mixed_chinese_and_english():
    from app.bitable_workflow.task_similarity import _tokenize
    tokens = _tokenize("Q3 经营复盘 GMV 下滑 12%")
    assert "q3" in tokens
    assert "gmv" in tokens
    assert "经" in tokens and "营" in tokens
    assert "12" in tokens


def test_tokenize_filters_stopwords():
    from app.bitable_workflow.task_similarity import _tokenize
    tokens = _tokenize("我们 the of 数据 分析")
    assert "我" not in tokens  # 中文停用词
    assert "the" not in tokens
    assert "of" not in tokens
    assert "数" in tokens and "据" in tokens


def test_tokenize_returns_empty_for_blank_input():
    from app.bitable_workflow.task_similarity import _tokenize
    assert _tokenize("") == set()
    assert _tokenize("   ") == set()
    assert _tokenize("。。。") == set()


# ---------- 单元：jaccard ----------


def test_jaccard_identical_returns_one():
    from app.bitable_workflow.task_similarity import _jaccard
    s = {"a", "b", "c"}
    assert _jaccard(s, s) == 1.0


def test_jaccard_disjoint_returns_zero():
    from app.bitable_workflow.task_similarity import _jaccard
    assert _jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial_overlap():
    from app.bitable_workflow.task_similarity import _jaccard
    # |交集|=1, |并集|=3, score = 1/3
    assert abs(_jaccard({"a", "b"}, {"b", "c"}) - 1/3) < 1e-9


def test_jaccard_empty_inputs_return_zero():
    from app.bitable_workflow.task_similarity import _jaccard
    assert _jaccard(set(), {"a"}) == 0.0
    assert _jaccard({"a"}, set()) == 0.0


# ---------- 单元：score_similarity 加权 ----------


def test_score_same_title_dimension_higher_than_only_dimension():
    from app.bitable_workflow.task_similarity import score_similarity
    same = score_similarity(
        query_title="Q3 经营复盘", query_dimension="数据复盘", query_background="GMV 下滑",
        candidate_title="Q3 经营复盘", candidate_dimension="数据复盘", candidate_background="GMV 下滑",
    )
    only_dim = score_similarity(
        query_title="Q3 经营复盘", query_dimension="数据复盘", query_background="",
        candidate_title="完全不同的产品复盘", candidate_dimension="数据复盘", candidate_background="",
    )
    assert same > only_dim
    assert same > 1.0  # 至少超过 dimension 权重


def test_score_zero_when_completely_unrelated():
    from app.bitable_workflow.task_similarity import score_similarity
    score = score_similarity(
        query_title="Q3 GMV", query_dimension="数据", query_background="",
        candidate_title="春节促销活动", candidate_dimension="内容", candidate_background="",
    )
    # 无字符重叠，dimension 也不同 → 接近 0
    assert score < 0.2


def test_score_dimension_exact_match_bonus():
    """同 dimension 给固定 0.5；不同 dimension 走 jaccard 后乘 0.5。"""
    from app.bitable_workflow.task_similarity import score_similarity
    exact = score_similarity(
        query_title="X", query_dimension="数据复盘", query_background="",
        candidate_title="Y", candidate_dimension="数据复盘", candidate_background="",
    )
    different = score_similarity(
        query_title="X", query_dimension="数据复盘", query_background="",
        candidate_title="Y", candidate_dimension="内容增长", candidate_background="",
    )
    assert exact > different


# ---------- 集成：find_similar_completed_tasks ----------


@pytest.mark.asyncio
async def test_find_similar_returns_top_k_sorted_by_score(monkeypatch):
    from app.bitable_workflow import bitable_ops, task_similarity

    async def fake_list(_app, _tid, *, filter_expr=None, max_records=200):
        return [
            {
                "record_id": "rec_a",
                "fields": {
                    "任务标题": "Q3 经营复盘",
                    "分析维度": "数据复盘",
                    "背景说明": "GMV 下滑 12%",
                    "综合健康度": "🔴 预警",
                    "完成时间": "2026-04-01",
                    "决策摘要": "建议本季度暂缓新功能投入",
                },
            },
            {
                "record_id": "rec_b",
                "fields": {
                    "任务标题": "春节促销活动总结",
                    "分析维度": "内容增长",
                    "背景说明": "活动 ROI 评估",
                },
            },
            {
                "record_id": "rec_c",
                "fields": {
                    "任务标题": "Q4 经营复盘",
                    "分析维度": "数据复盘",
                    "背景说明": "用户留存分析",
                },
            },
        ]

    monkeypatch.setattr(bitable_ops, "list_records", fake_list)

    matches = await task_similarity.find_similar_completed_tasks(
        app_token="app",
        table_id="tbl_task",
        query_title="Q3 经营复盘",
        query_dimension="数据复盘",
        query_background="GMV 下滑",
        top_k=2,
    )
    assert len(matches) == 2
    # rec_a 完全匹配 → 第 1 名；rec_c 同维度 + 部分 title overlap → 第 2 名
    assert matches[0].record_id == "rec_a"
    assert matches[0].score > matches[1].score
    # rec_a 富出来的元数据被携带
    assert matches[0].health == "🔴 预警"
    assert "建议本季度" in matches[0].summary


@pytest.mark.asyncio
async def test_find_similar_filters_below_min_score(monkeypatch):
    from app.bitable_workflow import bitable_ops, task_similarity

    async def fake_list(*_a, **_kw):
        return [
            {
                "record_id": "rec_unrelated",
                "fields": {
                    "任务标题": "ABC XYZ DEF",
                    "分析维度": "完全不同",
                    "背景说明": "",
                },
            }
        ]

    monkeypatch.setattr(bitable_ops, "list_records", fake_list)

    matches = await task_similarity.find_similar_completed_tasks(
        app_token="app", table_id="tbl",
        query_title="Q3 经营复盘",
        query_dimension="数据复盘",
        top_k=3,
        min_score=0.3,  # 高一点，过滤掉
    )
    assert matches == []


@pytest.mark.asyncio
async def test_find_similar_handles_richtext_fields(monkeypatch):
    """飞书 search 返富文本数组 [{text:"..."}]，必须能被拍平后参与匹配。"""
    from app.bitable_workflow import bitable_ops, task_similarity

    async def fake_list(*_a, **_kw):
        return [
            {
                "record_id": "rec_rt",
                "fields": {
                    "任务标题": [{"text": "Q3 经营复盘", "type": "text"}],
                    "分析维度": [{"text": "数据复盘", "type": "text"}],
                    "背景说明": [{"text": "GMV 下滑", "type": "text"}],
                },
            }
        ]

    monkeypatch.setattr(bitable_ops, "list_records", fake_list)

    matches = await task_similarity.find_similar_completed_tasks(
        app_token="app", table_id="tbl",
        query_title="Q3 经营复盘",
        query_dimension="数据复盘",
        top_k=3,
    )
    assert len(matches) == 1
    assert matches[0].title == "Q3 经营复盘"
    assert matches[0].score > 1.0  # title 完全匹配应该至少 2.0


@pytest.mark.asyncio
async def test_find_similar_returns_empty_when_query_blank(monkeypatch):
    from app.bitable_workflow import task_similarity

    matches = await task_similarity.find_similar_completed_tasks(
        app_token="app", table_id="tbl", query_title="", query_dimension="数据复盘",
    )
    assert matches == []


@pytest.mark.asyncio
async def test_find_similar_swallows_list_records_failure(monkeypatch):
    from app.bitable_workflow import bitable_ops, task_similarity

    async def fail_list(*_a, **_kw):
        raise RuntimeError("Bitable down")

    monkeypatch.setattr(bitable_ops, "list_records", fail_list)

    # 失败应返空列表（不阻塞 caller）
    matches = await task_similarity.find_similar_completed_tasks(
        app_token="app", table_id="tbl", query_title="Q3 复盘",
    )
    assert matches == []


# ---------- 端点 ----------


@pytest.mark.asyncio
async def test_similar_endpoint_returns_409_when_base_not_setup(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from fastapi import HTTPException

    workflow._state_by_token.clear()
    workflow._active_token = ""
    workflow._state.clear()

    with pytest.raises(HTTPException) as exc:
        await workflow.workflow_similar_tasks(
            title="Q3 复盘", dimension="", background="", app_token=None, limit=3,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_similar_endpoint_returns_matches(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import task_similarity
    from app.bitable_workflow.task_similarity import SimilarTask

    async def fake_find(**kwargs):
        return [
            SimilarTask(
                record_id="rec_old",
                title="Q3 经营复盘",
                dimension="数据复盘",
                score=2.5,
                health="🟡 关注",
                completed_at="2026-03-31",
                summary="过去结论：调整内容投放",
            ),
        ]

    monkeypatch.setattr(task_similarity, "find_similar_completed_tasks", fake_find)

    workflow._state_by_token.clear()
    workflow._active_token = ""
    workflow._state.clear()
    workflow._set_state(
        "app_demo",
        app_token="app_demo",
        table_ids={"task": "tbl_task"},
    )

    resp = await workflow.workflow_similar_tasks(
        title="Q4 经营复盘",
        dimension="数据复盘",
        background="GMV 持续下滑",
        app_token="app_demo",
        limit=3,
    )
    assert resp["count"] == 1
    assert resp["matches"][0]["record_id"] == "rec_old"
    assert resp["matches"][0]["score"] == 2.5
    assert resp["matches"][0]["health"] == "🟡 关注"
