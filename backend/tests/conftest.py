"""共享测试夹具（Fixtures）"""
import pytest
from app.agents.base_agent import AgentResult, ResultSection


@pytest.fixture
def ok_result():
    return AgentResult(
        agent_id="data_analyst",
        agent_name="数据分析师",
        sections=[
            ResultSection(title="核心结论", content="增长趋势良好，MAU 环比+15%"),
            ResultSection(title="风险提示", content="获客成本上升需关注"),
        ],
        action_items=["加强用户留存分析", "控制广告投放 ROI", "优化付费转化路径"],
        raw_output="## 核心结论\n增长趋势良好\n## 风险提示\n获客成本上升",
    )


@pytest.fixture
def failed_result():
    return AgentResult(
        agent_id="finance_advisor",
        agent_name="财务顾问",
        sections=[ResultSection(title="错误", content="分析失败：连接超时")],
        action_items=[],
        raw_output="FAILED: Connection timeout",
    )


@pytest.fixture
def ceo_result():
    return AgentResult(
        agent_id="ceo_assistant",
        agent_name="CEO 助理",
        sections=[
            ResultSection(title="核心结论", content="整体经营状况稳健，建议加大内容投入"),
            ResultSection(title="重要机会", content="短视频赛道用户需求旺盛"),
            ResultSection(title="重要风险", content="竞争对手加速布局，需提前防守"),
            ResultSection(title="CEO 需决策", content="1. 追加内容预算 2. 加速产品迭代"),
            ResultSection(title="管理摘要", content="本轮分析由7岗联合完成，建议优先落实行动项"),
        ],
        action_items=["追加内容预算50万", "加速产品迭代排期", "建立竞品监控机制"],
        raw_output="## 核心结论\n整体经营状况稳健",
    )
