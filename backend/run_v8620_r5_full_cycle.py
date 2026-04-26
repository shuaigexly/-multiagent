"""v8.6.20-r5 端到端验收：建新 base → 跑 1 轮 cycle → 审计 → 不删（留 URL 给用户看）。

验收点：
  1. setup_workflow 一气呵成（rollback 不触发）
  2. 综合评分 字段 type=2 (Number)，SEED 任务写入 75（priority_score("P1 高")）
  3. 健康度数值 字段 type=2 (Number)，cycle 完后按 health_score 回填
  4. 决策紧急度 受健康度 cap：🟢→≤3 / 🟡→≤4
  5. verify on this base = issues=0
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")


async def main():
    from app.bitable_workflow import bitable_ops
    from app.bitable_workflow.runner import setup_workflow
    from app.bitable_workflow.scheduler import run_one_cycle
    from app.bitable_workflow.schema import priority_score, health_score
    from app.bitable_workflow.verify import audit_bitable, _print_report

    print("===== Step 1: setup_workflow =====")
    t0 = time.monotonic()
    setup_result = await setup_workflow(name=f"v8.6.20-r5 e2e {int(t0)}")
    app_token = setup_result["app_token"]
    tids = setup_result["table_ids"]
    print(f"  app_token = {app_token}")
    print(f"  url       = {setup_result['url']}")
    print(f"  耗时       = {time.monotonic() - t0:.1f}s")

    print("\n===== Step 2: 验证 schema 字段类型 =====")
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    import httpx
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    async with httpx.AsyncClient(timeout=30) as h:
        # 任务表 综合评分
        r = await h.get(
            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tids['task']}/fields",
            headers={"Authorization": f"Bearer {token}"},
        )
        task_fields = (r.json().get("data") or {}).get("items") or []
        score_field = next((f for f in task_fields if f.get("field_name") == "综合评分"), None)
        print(f"  分析任务.综合评分 type={score_field.get('type') if score_field else '?'} (期望 2/Number)")
        assert score_field and score_field.get("type") == 2, "综合评分 不是 Number(2)！"

        # 岗位分析表 健康度数值
        r2 = await h.get(
            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tids['output']}/fields",
            headers={"Authorization": f"Bearer {token}"},
        )
        out_fields = (r2.json().get("data") or {}).get("items") or []
        health_field = next((f for f in out_fields if f.get("field_name") == "健康度数值"), None)
        print(f"  岗位分析.健康度数值 type={health_field.get('type') if health_field else '?'} (期望 2/Number)")
        assert health_field and health_field.get("type") == 2, "健康度数值 不是 Number(2)！"

    print("\n===== Step 3: 验证 SEED 任务 综合评分=75 =====")
    tasks = await bitable_ops.list_records(app_token, tids["task"], max_records=20)
    seed_score_ok = 0
    seed_total = 0
    for r in tasks:
        f = r.get("fields") or {}
        title = f.get("任务标题")
        if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(x,dict))
        if str(title or '').startswith('📌'): continue
        seed_total += 1
        score = f.get("综合评分")
        try:
            score_n = int(float(score)) if score is not None else None
        except Exception:
            score_n = None
        prio = f.get("优先级")
        if isinstance(prio, list): prio = ''.join(x.get('text','') for x in prio if isinstance(x,dict))
        expected = priority_score(str(prio or ''))
        ok = '✓' if score_n == expected else f'✗ 期望{expected}'
        print(f"  {str(title)[:25]:25s} 优先级={prio!r:10s} 综合评分={score!r}->{score_n} {ok}")
        if score_n == expected:
            seed_score_ok += 1
    print(f"  → SEED 综合评分通过: {seed_score_ok}/{seed_total}")

    print("\n===== Step 4: 跑 1 轮 cycle =====")
    t1 = time.monotonic()
    cycle_result = await run_one_cycle(app_token, tids)
    print(f"  cycle: processed={cycle_result} 耗时={time.monotonic()-t1:.1f}s")

    print("\n===== Step 5: 验证 健康度数值 ← health_score =====")
    outs = await bitable_ops.list_records(app_token, tids["output"], max_records=200)
    h_match = 0
    h_total = 0
    for r in outs:
        f = r.get("fields") or {}
        h = f.get("健康度评级")
        if isinstance(h, list): h = ''.join(x.get('text','') for x in h if isinstance(x,dict))
        v = f.get("健康度数值")
        if v is None: continue
        try:
            v_n = int(float(v))
        except Exception:
            v_n = None
        h_total += 1
        expected = health_score(str(h or ''))
        if v_n == expected:
            h_match += 1
        else:
            print(f"  ✗ {f.get('岗位角色')!r} {f.get('任务标题')!r}: 健康度评级={h!r} 数值={v!r}->{v_n} 期望={expected}")
    print(f"  → 健康度数值 一致: {h_match}/{h_total}")

    print("\n===== Step 6: 验证 决策紧急度 受健康度 cap (r3) =====")
    reps = await bitable_ops.list_records(app_token, tids["report"], max_records=20)
    cap_ok = 0
    cap_violations = []
    for r in reps:
        f = r.get("fields") or {}
        title = f.get("报告标题")
        if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(x,dict))
        h = f.get("综合健康度")
        urg = f.get("决策紧急度")
        try:
            urg_n = int(float(urg)) if urg is not None else 0
        except: urg_n = 0
        cap = 3 if '🟢' in str(h) else (4 if '🟡' in str(h) else 5)
        if urg_n <= cap:
            cap_ok += 1
        else:
            cap_violations.append((title, h, urg_n, cap))
        print(f"  {str(title)[:25]:25s} 健康={h!r:12s} 紧急={urg_n} cap={cap} {'✓' if urg_n<=cap else '✗'}")
    print(f"  → 紧急度 cap 通过: {cap_ok}/{len(reps)}")

    print("\n===== Step 7: verify audit (整体) =====")
    expected_tables = ["分析任务", "岗位分析", "综合报告", "数字员工效能"]
    report = await audit_bitable(app_token, expected_table_names=expected_tables)
    issues = _print_report(report)
    print(f"\n  → 总 issues: {issues}（期望 0）")

    print("\n\n===== 端到端验收总结 =====")
    print(f"  app_token   = {app_token}")
    print(f"  URL         = {setup_result['url']}")
    print(f"  字段类型    : 综合评分=Number ✓, 健康度数值=Number ✓")
    print(f"  SEED 评分   : {seed_score_ok}/7 通过")
    print(f"  健康度数值  : {h_match}/{h_total} 一致")
    print(f"  紧急度 cap  : {cap_ok}/{len(reps)} 不超 cap")
    if cap_violations:
        print(f"  ⚠️ 违规:")
        for v in cap_violations:
            print(f"    {v}")
    print(f"  verify     : {issues} issues")

    return {
        "ok": (seed_score_ok >= 1 and h_match == h_total and cap_ok == len(reps) and issues == 0),
        "app_token": app_token,
        "url": setup_result["url"],
        "score_ok": seed_score_ok,
        "health_ok": h_match,
        "cap_ok": cap_ok,
        "issues": issues,
    }


if __name__ == "__main__":
    res = asyncio.run(main())
    print(f"\n→ FINAL: {res}")
    sys.exit(0 if res.get("ok") else 1)
