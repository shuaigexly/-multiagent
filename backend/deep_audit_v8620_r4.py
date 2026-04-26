"""v8.6.20-r4 第三轮深度审计：探查更多隐蔽 bug。

聚焦：
  1. 任务表「完成时间」「完成日期」类型一致性（datetime ms vs str）
  2. 完成时间是 str 还是 datetime ms？飞书 Date 字段（type=5）应是 ms 时间戳
  3. 综合报告 字段长度边界（核心结论/重要机会/重要风险/CEO决策事项/管理摘要）
  4. 数据源「字段说明」是否详尽
  5. 数字员工效能「岗位」(SingleSelect) vs「角色」(Text) 一致性
  6. 任务表 主字段「任务标题」格式（📌 标识、富文本）
  7. 是否有 record 缺主字段（UI 显示「未命名」）
"""
import asyncio, io, sys, json
from collections import Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

APP = 'PR41b365raO4RlsznRUc8CVtnRh'
TIDS = {'task':'tblklteip8UDz8f9','output':'tblXSqm1fcd6S6sW','report':'tblfaAH4i93R8hCB','perf':'tblurvu1hlgGZKdU','ds':'tbl37pTXUU1mD18k'}


async def main():
    from app.bitable_workflow import bitable_ops
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    import httpx

    bugs = []
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()

    async with httpx.AsyncClient(timeout=30) as h:
        # === 1. 任务表 完成时间 vs 完成日期 类型审计 ===
        print("## 1. 完成时间 vs 完成日期 类型审计")
        rfields = await h.get(f"{base}/open-apis/bitable/v1/apps/{APP}/tables/{TIDS['task']}/fields", headers={"Authorization": f"Bearer {token}"})
        task_field_types = {f.get("field_name"): (f.get("type"), f.get("ui_type")) for f in (rfields.json().get("data") or {}).get("items") or []}
        print(f"  完成时间: type={task_field_types.get('完成时间')}")
        print(f"  完成日期: type={task_field_types.get('完成日期')}")
        # 完成时间 应是 Text(1) 或 DateTime(5)；完成日期 应是 DateTime(5)
        if task_field_types.get("完成日期") and task_field_types["完成日期"][0] != 5:
            bugs.append(f"完成日期 type={task_field_types['完成日期']} 应是 DateTime(5)")

        tasks = await bitable_ops.list_records(APP, TIDS['task'], max_records=50)
        for r in tasks[:3]:
            f = r.get('fields') or {}
            ct = f.get('完成时间')
            cd = f.get('完成日期')
            print(f"  完成时间值: {ct!r:40s} 完成日期值: {cd!r}")
            if cd and not (isinstance(cd, (int, float)) and cd > 1e12):
                bugs.append(f"完成日期 不是 ms 时间戳: {cd!r}")

        # === 2. 综合报告 字段长度分布 ===
        print("\n## 2. 综合报告 字段长度分布")
        reps = await bitable_ops.list_records(APP, TIDS['report'], max_records=20)
        for r in reps:
            f = r.get('fields') or {}
            t = f.get('报告标题')
            if isinstance(t, list): t = ''.join(x.get('text','') for x in t if isinstance(x,dict))
            t = str(t)[:25]
            lens = {}
            for k in ['核心结论','重要机会','重要风险','CEO决策事项','管理摘要']:
                v = f.get(k)
                if isinstance(v, list): v = ''.join(x.get('text','') for x in v if isinstance(x,dict))
                lens[k] = len(str(v or ''))
            short = [k for k, ll in lens.items() if ll < 40]
            warn = ' ⚠️ 短: ' + ','.join(short) if short else ''
            print(f"  {t:25s} {lens}{warn}")
            for k in short:
                if lens[k] < 20:
                    bugs.append(f"报告[{t}].{k} 仅 {lens[k]} 字符（疑似空/截断）")

        # === 3. 综合报告 主字段为空检查 ===
        print("\n## 3. 综合报告 主字段「报告标题」缺失检查")
        rfields_rep = await h.get(f"{base}/open-apis/bitable/v1/apps/{APP}/tables/{TIDS['report']}/fields", headers={"Authorization": f"Bearer {token}"})
        primary = next((ff for ff in (rfields_rep.json().get("data") or {}).get("items") or [] if ff.get("is_primary")), None)
        print(f"  主字段: {primary.get('field_name') if primary else '?'} type={primary.get('type') if primary else '?'}")
        empty_pri = sum(1 for r in reps if not (r.get('fields') or {}).get(primary.get('field_name')))
        print(f"  主字段为空: {empty_pri}/{len(reps)}")
        if empty_pri:
            bugs.append(f"综合报告 主字段为空: {empty_pri}/{len(reps)}")

        # === 4. 数据源 字段说明 长度（应详尽，便于 agent 理解列含义） ===
        print("\n## 4. 数据源 字段说明 长度")
        ds_rows = await bitable_ops.list_records(APP, TIDS['ds'], max_records=20)
        for r in ds_rows:
            f = r.get('fields') or {}
            n = f.get('数据集名称')
            if isinstance(n, list): n = ''.join(x.get('text','') for x in n if isinstance(x,dict))
            doc = f.get('字段说明')
            if isinstance(doc, list): doc = ''.join(x.get('text','') for x in doc if isinstance(x,dict))
            l = len(str(doc or ''))
            print(f"  {str(n)[:25]:25s} 字段说明={l}c")
            if l < 30:
                bugs.append(f"数据源[{n}] 字段说明仅 {l} 字符（agent 难理解列含义）")

        # === 5. 数字员工效能 岗位(SingleSelect) vs 角色(Text) 一致性 ===
        print("\n## 5. 效能表 岗位 vs 角色 一致性")
        perf = await bitable_ops.list_records(APP, TIDS['perf'], max_records=20)
        for r in perf:
            f = r.get('fields') or {}
            n = f.get('员工姓名')
            if isinstance(n, list): n = ''.join(x.get('text','') for x in n if isinstance(x,dict))
            post = f.get('岗位')
            if isinstance(post, list): post = ''.join(x.get('text','') for x in post if isinstance(x,dict))
            role = f.get('角色')
            if isinstance(role, list): role = ''.join(x.get('text','') for x in role if isinstance(x,dict))
            print(f"  {str(n)[:14]:14s} 岗位={post!r:18s} 角色={role!r}")
            if not post:
                bugs.append(f"效能[{n}] 岗位字段为空")
            if not role:
                bugs.append(f"效能[{n}] 角色字段为空")

        # === 6. 岗位分析 岗位角色 vs 效能 角色 映射 ===
        print("\n## 6. 岗位分析 岗位角色 ↔ 效能 角色 映射")
        outs = await bitable_ops.list_records(APP, TIDS['output'], max_records=200)
        out_role_count = Counter()
        for r in outs:
            f = r.get('fields') or {}
            role = f.get('岗位角色')
            if isinstance(role, list): role = ''.join(x.get('text','') for x in role if isinstance(x,dict))
            out_role_count[str(role or '?')] += 1
        print(f"  岗位分析 岗位角色 分布: {dict(out_role_count)}")
        # 效能 处理任务数 应等于 岗位分析 中按 agent_name 分组的计数
        for r in perf:
            f = r.get('fields') or {}
            n = f.get('员工姓名')
            if isinstance(n, list): n = ''.join(x.get('text','') for x in n if isinstance(x,dict))
            count = f.get('处理任务数')
            actual = out_role_count.get(str(n or ''), 0)
            ok = '✓' if int(count or 0) == actual else f'✗ 实际={actual}'
            print(f"  {str(n)[:14]:14s} 处理={count} actual_by_name={actual} {ok}")
            if int(count or 0) != actual:
                bugs.append(f"效能[{n}] 处理任务数={count} 但岗位分析按姓名={actual}")

        # === 7. 任务表 主字段格式（📌引导 vs 真实任务）===
        print("\n## 7. 任务表 主字段「任务标题」")
        for r in tasks:
            f = r.get('fields') or {}
            t = f.get('任务标题')
            if isinstance(t, list): t = ''.join(x.get('text','') for x in t if isinstance(x,dict))
            t = str(t or '?')
            tno = f.get('任务编号')
            print(f"  T{tno:3} {t[:50]}")
            if not t.strip():
                bugs.append(f"任务编号={tno} 主字段为空")

        # === 8. 任务的「数据源」字段长度分布（embedded markdown + CSV） ===
        print("\n## 8. 任务表 数据源 字段长度（看是否含完整 markdown + csv）")
        for r in tasks:
            f = r.get('fields') or {}
            t = f.get('任务标题')
            if isinstance(t, list): t = ''.join(x.get('text','') for x in t if isinstance(x,dict))
            if str(t or '').startswith('📌'): continue
            ds = f.get('数据源')
            if isinstance(ds, list): ds = ''.join(x.get('text','') for x in ds if isinstance(x,dict))
            ds = str(ds or '')
            has_md = '|' in ds and '---' in ds
            has_csv = '```csv' in ds or 'csv\n' in ds
            tno = f.get('任务编号')
            print(f"  T{tno:3} {str(t)[:25]:25s} {len(ds)}c md={has_md} csv={has_csv}")
            if not has_md:
                bugs.append(f"任务[{t}] 数据源缺 markdown 表格")
            if not has_csv:
                bugs.append(f"任务[{t}] 数据源缺原始 CSV")

    print(f"\n\n## ===== BUG 盘点 ({len(bugs)} 项) =====")
    for b in bugs:
        print(f"  - {b}")


asyncio.run(main())
