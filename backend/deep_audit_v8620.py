"""v8.6.20-r3 深度审计：扫所有表所有字段所有 record，找内容/类型/截断/格式异常。"""
import asyncio, io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

APP = 'PR41b365raO4RlsznRUc8CVtnRh'
TIDS = {'task':'tblklteip8UDz8f9','output':'tblXSqm1fcd6S6sW','report':'tblfaAH4i93R8hCB','perf':'tblurvu1hlgGZKdU','ds':'tbl37pTXUU1mD18k'}


async def main():
    from app.bitable_workflow import bitable_ops
    bugs = []

    # 1. 综合报告 7 条 — 看具体字段内容
    print("## 1. 综合报告字段健全性")
    reps = await bitable_ops.list_records(APP, TIDS['report'], max_records=20)
    expected = ['报告标题','综合健康度','核心结论','重要机会','重要风险','CEO决策事项','管理摘要','参与岗位数','决策紧急度']
    for i, r in enumerate(reps):
        f = r.get('fields') or {}
        title = f.get('报告标题')
        if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(x,dict))
        title = str(title)[:25]
        miss = [k for k in expected if not f.get(k)]
        truncated = [k for k, v in f.items() if isinstance(v, str) and "...[已截断]" in v]
        urgency = f.get('决策紧急度')
        health = f.get('综合健康度')
        # 健康 vs 紧急度 一致性
        warn = ''
        if health == '🟢 健康' and urgency and int(float(urgency)) >= 5:
            warn = ' ⚠️ 健康但紧急度=5 矛盾'
            bugs.append(f"综合报告[{title}] 健康但紧急度={urgency}")
        if isinstance(health, list):
            bugs.append(f"综合报告[{title}] 综合健康度返回 list (富文本未拍平)")
        print(f"  [{i}] {title:25s} 健康={health!r:14s} 紧急={urgency} 缺={miss} 截断={truncated[:3]}{warn}")

    # 2. 数据源库 7 条 — 查每条字段
    print("\n## 2. 数据源库 字段健全性")
    ds_rows = await bitable_ops.list_records(APP, TIDS['ds'], max_records=20)
    for r in ds_rows:
        f = r.get('fields') or {}
        name = f.get('数据集名称')
        if isinstance(name, list): name = ''.join(x.get('text','') for x in name if isinstance(x,dict))
        cs = len(str(f.get('原始 CSV') or ''))
        md = len(str(f.get('渲染表格') or ''))
        rows = f.get('数据行数')
        att = f.get('原始数据文件')
        print(f"  {name!r:30s} CSV={cs}c MD={md}c 行数={rows} 附件={'有' if att else '无'}")
        if cs == 0:
            bugs.append(f"数据源[{name}] 缺原始 CSV")

    # 3. 任务表 — task_image / 负责人 / 数据源 哪些任务缺
    print("\n## 3. 任务表 可选字段填充")
    tasks = await bitable_ops.list_records(APP, TIDS['task'], max_records=20)
    for r in tasks:
        f = r.get('fields') or {}
        title = f.get('任务标题')
        if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(title,list) for x in title if isinstance(x,dict)) if isinstance(title, list) else title
        title = str(title or '?')[:25]
        if title.startswith('📌'): continue
        img = '有' if f.get('任务图像') else '无'
        ds = f.get('数据源')
        ds_len = len(str(ds)) if ds else 0
        owner = f.get('负责人')
        score = f.get('综合评分')
        print(f"  T{f.get('任务编号','?'):3} {title:25s} 数据源={ds_len}c 任务图像={img} 负责人={'有' if owner else '无'} 综合评分={score}")

    # 4. 岗位分析 — 看每条「分析摘要」「行动项」「分析思路」截断/缺失情况
    print("\n## 4. 岗位分析 内容健全性（前 6 条）")
    outs = await bitable_ops.list_records(APP, TIDS['output'], max_records=100)
    truncated_summary = 0
    truncated_action = 0
    truncated_thinking = 0
    chart_data_invalid = 0
    for r in outs:
        f = r.get('fields') or {}
        s = str(f.get('分析摘要') or '')
        a = str(f.get('行动项') or '')
        t = str(f.get('分析思路') or '')
        cd = str(f.get('图表数据') or '')
        if "...[已截断]" in s: truncated_summary += 1
        if "...[已截断]" in a: truncated_action += 1
        if "...[已截断]" in t: truncated_thinking += 1
        if cd:
            try:
                json.loads(cd.replace("...[已截断]", ""))
            except Exception:
                chart_data_invalid += 1
    print(f"  分析摘要被截断: {truncated_summary}/{len(outs)}")
    print(f"  行动项被截断: {truncated_action}/{len(outs)}")
    print(f"  分析思路被截断: {truncated_thinking}/{len(outs)}")
    print(f"  图表数据 JSON 损坏: {chart_data_invalid}/{len(outs)}")

    # 5. 数字员工效能「处理任务数」「活跃度」分布
    print("\n## 5. 数字员工效能")
    perf = await bitable_ops.list_records(APP, TIDS['perf'], max_records=20)
    for r in perf:
        f = r.get('fields') or {}
        n = f.get('员工姓名')
        if isinstance(n, list): n = ''.join(x.get('text','') for x in n if isinstance(x,dict))
        c = f.get('处理任务数')
        a = f.get('活跃度')
        role = f.get('角色')
        if isinstance(role, list): role = ''.join(x.get('text','') for x in role if isinstance(x,dict))
        print(f"  {n!r:18s} role={role!r:20s} 处理={c} 活跃={a}")

    # 6. 跟进任务（应不存在 — cycle 关闭了 followup）
    print("\n## 6. 跟进任务")
    followup = sum(1 for r in tasks if str((r.get('fields') or {}).get('任务标题','')).startswith('[跟进]'))
    print(f"  共 {followup} 条")

    # 7. 综合报告「综合健康度」分布
    print("\n## 7. 综合健康度分布")
    from collections import Counter
    health_dist = Counter((r.get('fields') or {}).get('综合健康度') for r in reps)
    print(f"  {dict(health_dist)}")

    # === BUG 总结 ===
    print(f"\n\n## ===== BUG 盘点 ({len(bugs)} 项) =====")
    for b in bugs:
        print(f"  - {b}")


asyncio.run(main())
