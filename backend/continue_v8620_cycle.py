"""把 v8.6.20-r5 e2e base 的剩余 cycle 跑完。

VG9zbTkwRardU0sVx8tc0jQZn9g：T2 已完成、T3 分析中（被中断）、T4-T8 待分析、
T9-T11 [跟进]待分析。Phase 0 应自动恢复 T3，Phase 1 拉新待分析。
"""
import asyncio, io, sys, os, time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")

APP = "VG9zbTkwRardU0sVx8tc0jQZn9g"


async def main():
    from app.bitable_workflow.scheduler import run_one_cycle
    from app.bitable_workflow import bitable_ops
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    import httpx

    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    async with httpx.AsyncClient(timeout=20) as h:
        r = await h.get(f"{base}/open-apis/bitable/v1/apps/{APP}/tables", headers={"Authorization": f"Bearer {token}"})
        TIDS = {t["name"]: t["table_id"] for t in (r.json().get("data") or {}).get("items") or []}

    table_ids = {
        "task": TIDS["分析任务"],
        "output": TIDS["岗位分析"],
        "report": TIDS["综合报告"],
        "performance": TIDS["数字员工效能"],
    }

    for round_n in range(1, 8):
        t0 = time.monotonic()
        print(f"\n========== Round {round_n} ==========")
        try:
            n = await run_one_cycle(APP, table_ids)
        except Exception as exc:
            print(f"Round {round_n} 抛错: {exc}")
            break
        print(f"Round {round_n}: processed={n} 耗时={time.monotonic()-t0:.0f}s")

        tasks = await bitable_ops.list_records(APP, table_ids["task"], max_records=50)
        from collections import Counter
        states = Counter()
        for t in tasks:
            s = (t.get("fields") or {}).get("状态")
            if isinstance(s, list): s = ''.join(x.get('text','') for x in s if isinstance(x,dict))
            states[str(s)] += 1
        print(f"  state: {dict(states)}")
        if states.get("待分析", 0) == 0 and states.get("分析中", 0) == 0:
            print("  → 全部完成，停止")
            break

    print("\n========== 终态 ==========")
    tasks = await bitable_ops.list_records(APP, table_ids["task"], max_records=50)
    for t in tasks:
        f = t.get("fields") or {}
        title = f.get("任务标题")
        if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(x,dict))
        s = f.get("状态")
        if isinstance(s, list): s = ''.join(x.get('text','') for x in s if isinstance(x,dict))
        score = f.get("综合评分")
        print(f"  T{f.get('任务编号','?'):3} {str(title)[:30]:30s} {s!r:10s} 评分={score}")


if __name__ == "__main__":
    asyncio.run(main())
