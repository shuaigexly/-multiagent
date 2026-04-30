"""v8.6.20-r29: workflow API per-app_token 状态隔离回归。

历史问题（Round-12 audit Blocker #1）：`workflow._state` 是单进程字典，多个用户
同时调 `/setup` + `/start` 不同 base 会互相覆盖 — 第二个 caller 的 native_assets
直接抹掉第一个的，前端显示完全错的状态。

本文件验证 r29 起的隔离契约：
1. `_set_state(token_a, ...)` 不污染 `_get_state(token_b)`
2. GET endpoint 带 `?app_token=` 拿到自己 base 的 snapshot，不带就 fallback 到
   最近活跃 base（保留 r28 之前的旧前端契约）
3. 切换活跃 base 后，老 base 的 bucket 仍可被显式 token 拿回
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_workflow_state():
    """每个 test 前后把 workflow 模块的所有运行时状态清干净，避免相互污染。"""
    from app.api import workflow

    workflow._state.clear()
    workflow._state_by_token.clear()
    workflow._active_token = ""
    yield
    workflow._state.clear()
    workflow._state_by_token.clear()
    workflow._active_token = ""


def test_set_state_isolates_buckets_per_app_token():
    from app.api import workflow

    workflow._set_state("app_a", app_token="app_a", url="https://a", native_assets={"flag": "A"})
    workflow._set_state("app_b", app_token="app_b", url="https://b", native_assets={"flag": "B"})

    snap_a = workflow._get_state("app_a")
    snap_b = workflow._get_state("app_b")

    assert snap_a["app_token"] == "app_a"
    assert snap_a["url"] == "https://a"
    assert snap_a["native_assets"] == {"flag": "A"}
    assert snap_b["app_token"] == "app_b"
    assert snap_b["url"] == "https://b"
    assert snap_b["native_assets"] == {"flag": "B"}


def test_get_state_default_returns_active_bucket():
    from app.api import workflow

    workflow._set_state("first", app_token="first", url="https://first")
    workflow._set_state("second", app_token="second", url="https://second")

    # 默认 = _active_token，刚刚最后写的是 second
    default_snap = workflow._get_state()
    assert default_snap["app_token"] == "second"

    # 显式拿 first 仍能获取
    first_snap = workflow._get_state("first")
    assert first_snap["app_token"] == "first"
    assert first_snap["url"] == "https://first"


def test_replace_state_overwrites_only_target_bucket():
    from app.api import workflow

    workflow._set_state("alpha", app_token="alpha", native_assets={"v": 1})
    workflow._set_state("beta", app_token="beta", native_assets={"v": 2})

    workflow._replace_state("alpha", {"app_token": "alpha", "url": "https://new-alpha"})

    snap_a = workflow._get_state("alpha")
    snap_b = workflow._get_state("beta")
    assert "native_assets" not in snap_a  # alpha 整体被替换，旧字段被清
    assert snap_a["url"] == "https://new-alpha"
    assert snap_b["native_assets"] == {"v": 2}  # beta 不受影响


def test_legacy_state_dict_mirrors_active_bucket_for_backward_compat():
    from app.api import workflow

    workflow._set_state("alpha", app_token="alpha", url="https://alpha", native_manifest={"v": 1})
    # 旧路径直接读 workflow._state 仍能拿到当前活跃 base 的内容
    assert workflow._state["app_token"] == "alpha"
    assert workflow._state["native_manifest"] == {"v": 1}

    # 切到 beta：legacy _state 反映 beta
    workflow._set_state("beta", app_token="beta", url="https://beta")
    assert workflow._state["app_token"] == "beta"
    assert workflow._state.get("native_manifest") is None


def test_legacy_state_writes_inherited_into_new_bucket():
    """pytest fixture 大量直接写 `workflow._state.update({...})` 灌种子；
    后续调用 `_set_state(token, ...)` 时这些字段必须被继承进新 bucket，不丢。"""
    from app.api import workflow

    workflow._state.update(
        {
            "app_token": "legacy_token",
            "url": "https://legacy",
            "table_ids": {"task": "tbl_t"},
            "native_assets": {"status": "blueprint_ready"},
        }
    )

    # 第一次 _set_state 同 token：应该把 legacy fixture 内容继承进来
    workflow._set_state("legacy_token", app_token="legacy_token", table_ids={"task": "tbl_t2"})

    bucket = workflow._get_state("legacy_token")
    assert bucket["url"] == "https://legacy"
    assert bucket["native_assets"] == {"status": "blueprint_ready"}  # 继承自 legacy
    assert bucket["table_ids"] == {"task": "tbl_t2"}  # 新写覆盖


@pytest.mark.asyncio
async def test_workflow_status_with_explicit_token_targets_specific_base(monkeypatch):
    from app.api import workflow

    monkeypatch.setattr("app.api.workflow.runner.is_running", lambda: False)
    monkeypatch.setattr("app.api.workflow._refresh_native_state_artifacts", lambda *_a, **_k: None)

    workflow._set_state("base_x", app_token="base_x", url="https://x", native_assets={"flag": "X"})
    workflow._set_state("base_y", app_token="base_y", url="https://y", native_assets={"flag": "Y"})

    # 默认看活跃（base_y）
    default = await workflow.workflow_status(app_token=None)
    assert default["state"]["app_token"] == "base_y"

    # 显式查 base_x
    explicit = await workflow.workflow_status(app_token="base_x")
    assert explicit["state"]["app_token"] == "base_x"
    assert explicit["state"]["native_assets"] == {"flag": "X"}


@pytest.mark.asyncio
async def test_workflow_native_manifest_targets_specific_app_token(monkeypatch):
    from app.api import workflow

    monkeypatch.setattr("app.api.workflow._refresh_native_state_artifacts", lambda *_a, **_k: None)

    workflow._set_state("base_p", app_token="base_p", url="https://p", native_manifest={"v": "P"})
    workflow._set_state("base_q", app_token="base_q", url="https://q", native_manifest={"v": "Q"})

    p_resp = await workflow.workflow_native_manifest(app_token="base_p")
    q_resp = await workflow.workflow_native_manifest(app_token="base_q")

    assert p_resp["app_token"] == "base_p"
    assert p_resp["native_manifest"] == {"v": "P"}
    assert q_resp["app_token"] == "base_q"
    assert q_resp["native_manifest"] == {"v": "Q"}


def test_concurrent_setup_simulation_does_not_cross_contaminate():
    """模拟两个用户「先后」调 /setup 不同 base — r28 之前会让第二次抹掉第一次的
    native_assets；r29 起每个 token 独享 bucket，互不影响。"""
    from app.api import workflow

    # 第 1 个用户 setup base A
    workflow._replace_state("user_a_base", {
        "app_token": "user_a_base",
        "url": "https://feishu.cn/base/user_a_base",
        "table_ids": {"task": "tbl_a_task", "report": "tbl_a_report"},
        "native_assets": {"customer": "A", "automation_templates": ["a1", "a2"]},
    })

    # 第 2 个用户 setup base B（覆盖 _active_token）
    workflow._replace_state("user_b_base", {
        "app_token": "user_b_base",
        "url": "https://feishu.cn/base/user_b_base",
        "table_ids": {"task": "tbl_b_task", "report": "tbl_b_report"},
        "native_assets": {"customer": "B", "automation_templates": ["b1"]},
    })

    # 用户 A 用 ?app_token=user_a_base 拉自己的状态 — 必须看见 customer=A
    snap_a = workflow._get_state("user_a_base")
    assert snap_a["app_token"] == "user_a_base"
    assert snap_a["native_assets"]["customer"] == "A"
    assert snap_a["native_assets"]["automation_templates"] == ["a1", "a2"]

    # 用户 B 同理拿到自己的
    snap_b = workflow._get_state("user_b_base")
    assert snap_b["native_assets"]["customer"] == "B"


@pytest.mark.asyncio
async def test_concurrent_set_state_under_asyncio_gather_holds_isolation():
    """v8.6.20-r31：把 5 个 _set_state 用 asyncio.gather 并发跑，每 base 独享 bucket。

    这是 multi-tenant 隔离的硬验收：判定 r29 改造在真正 race 下也成立。
    旧版（_state 单字典）此场景下 native_assets 会因 task switch 互相覆盖。
    """
    import asyncio
    from app.api import workflow

    async def setup_one(token: str, customer: str, n_templates: int) -> None:
        # 模拟 setup_workflow 内的多步 _set_state（每步 await 让出控制权）
        workflow._set_state(token, app_token=token)
        await asyncio.sleep(0)
        workflow._set_state(token, url=f"https://feishu.cn/base/{token}")
        await asyncio.sleep(0)
        workflow._set_state(
            token,
            table_ids={"task": f"tbl_{customer}_task"},
            native_assets={
                "customer": customer,
                "automation_templates": [f"{customer.lower()}{i}" for i in range(n_templates)],
            },
        )

    tokens = [
        ("base_alpha", "Alpha", 3),
        ("base_beta", "Beta", 2),
        ("base_gamma", "Gamma", 5),
        ("base_delta", "Delta", 1),
        ("base_epsilon", "Epsilon", 4),
    ]
    await asyncio.gather(*(setup_one(t, c, n) for t, c, n in tokens))

    # 每个 token 自己的快照都正确，没有任何字段串到别的 base
    for token, customer, n_templates in tokens:
        snap = workflow._get_state(token)
        assert snap["app_token"] == token, f"{token} 的 app_token 字段被污染：{snap}"
        assert snap["url"] == f"https://feishu.cn/base/{token}"
        assert snap["table_ids"] == {"task": f"tbl_{customer}_task"}
        assert snap["native_assets"]["customer"] == customer, (
            f"{token} customer 字段串台 — 期望 {customer} 实际 {snap['native_assets']['customer']}"
        )
        assert len(snap["native_assets"]["automation_templates"]) == n_templates
        # 抽样检查模板内容里没有别 base 的前缀
        for tpl in snap["native_assets"]["automation_templates"]:
            assert tpl.startswith(customer.lower()), (
                f"{token} 模板列表里发现别 base 的内容：{tpl}"
            )

    # 5 个 bucket 都注册成功
    assert len(workflow._state_by_token) == 5
    # _active_token 是最后写的某一个（gather 的完成顺序非确定），但必须是 5 个之一
    assert workflow._active_token in {t for t, *_ in tokens}


@pytest.mark.asyncio
async def test_get_state_during_concurrent_writes_returns_consistent_snapshot():
    """v8.6.20-r31：写入 base A 的过程中，读 base B 必须拿到 B 自己的字段，
    不会因为 _active_token 切换而读到错的 bucket。
    """
    import asyncio
    from app.api import workflow

    workflow._replace_state("base_x", {
        "app_token": "base_x",
        "url": "https://x",
        "native_assets": {"flag": "X"},
    })
    workflow._replace_state("base_y", {
        "app_token": "base_y",
        "url": "https://y",
        "native_assets": {"flag": "Y"},
    })

    read_results: list[tuple[str, str]] = []

    async def write_to_x():
        for i in range(20):
            workflow._set_state("base_x", url=f"https://x/v{i}")
            await asyncio.sleep(0)

    async def read_y_repeatedly():
        for _ in range(20):
            snap = workflow._get_state("base_y")
            read_results.append((snap.get("app_token", ""), snap.get("native_assets", {}).get("flag", "")))
            await asyncio.sleep(0)

    await asyncio.gather(write_to_x(), read_y_repeatedly())

    # 所有对 base_y 的读取必须始终拿到 base_y 自己的字段，从不被 base_x 污染
    assert read_results, "至少应有读取记录"
    for app_token, flag in read_results:
        assert app_token == "base_y", f"读 base_y 拿到了 app_token={app_token}"
        assert flag == "Y", f"读 base_y 拿到了 flag={flag}"
