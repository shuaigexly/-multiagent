"""v8.6.20-r3 深度审计：探查更多隐蔽 bug。"""
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
        # === 1. 字段类型审计：是否还有 Formula 残留 ===
        print("## 1. 字段类型 — 找 Formula 残留 / 类型不一致")
        for tname, tid in TIDS.items():
            r = await h.get(
                f"{base}/open-apis/bitable/v1/apps/{APP}/tables/{tid}/fields",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = r.json()
            for f in (data.get("data") or {}).get("items") or []:
                t = f.get("type")
                ui = f.get("ui_type")
                name = f.get("field_name")
                if t == 20:  # Formula
                    bugs.append(f"{tname}.{name} 还是 Formula(20) — 应已改为 Number")
                    print(f"  ⚠️ {tname:8s} {name!r:20s} type={t} (Formula) ui={ui}")
                elif name in ("综合评分", "健康度数值") and t != 2:
                    bugs.append(f"{tname}.{name} type={t} 期望 Number(2)")
                    print(f"  ⚠️ {tname:8s} {name!r:20s} type={t} ui={ui}")

        # === 2. 综合评分实际分布 ===
        print("\n## 2. 综合评分分布（应反映优先级 P0=100/P1=75/P2=50/P3=25）")
        tasks = await bitable_ops.list_records(APP, TIDS['task'], max_records=50)
        score_dist = Counter()
        prio_score_pairs = []
        for r in tasks:
            f = r.get('fields') or {}
            title = f.get('任务标题')
            if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(x,dict))
            title = str(title or '?')[:25]
            if title.startswith('📌'): continue
            prio = f.get('优先级')
            if isinstance(prio, list): prio = ''.join(x.get('text','') for x in prio if isinstance(x,dict))
            score = f.get('综合评分')
            score_dist[score] += 1
            prio_score_pairs.append((str(prio or ''), score, title))
        print(f"  分布: {dict(score_dist)}")
        for prio, score, title in prio_score_pairs:
            from app.bitable_workflow.schema import priority_score
            expected = priority_score(prio)
            ok = '✓' if score == expected else f'✗ 期望{expected}'
            print(f"  T{title:25s} 优先级={prio!r:10s} 综合评分={score} {ok}")
            if score != expected:
                bugs.append(f"任务[{title}] 综合评分={score} 应={expected}（优先级={prio}）")

        # === 3. 健康度数值（output 表）分布 ===
        print("\n## 3. 健康度数值（output）分布 — 应反映健康度评级")
        outs = await bitable_ops.list_records(APP, TIDS['output'], max_records=200)
        from app.bitable_workflow.schema import health_score
        h_dist = Counter()
        mismatch = 0
        for r in outs:
            f = r.get('fields') or {}
            health = f.get('健康度评级')
            if isinstance(health, list):
                health = ''.join(x.get('text','') for x in health if isinstance(x,dict))
            v = f.get('健康度数值')
            h_dist[v] += 1
            expected = health_score(str(health or ''))
            if v != expected:
                mismatch += 1
        print(f"  健康度数值分布: {dict(h_dist)}")
        print(f"  与健康度评级不一致: {mismatch}/{len(outs)}")
        if mismatch > 0:
            bugs.append(f"岗位分析 健康度数值 与 健康度评级 不一致：{mismatch}/{len(outs)}")

        # === 4. 综合报告 紧急度 vs 健康度 联动审计（v8.6.20-r3）===
        print("\n## 4. 综合报告 紧急度 vs 健康度 联动（应：🟢→≤3, 🟡→≤4, 🔴→≤5）")
        reps = await bitable_ops.list_records(APP, TIDS['report'], max_records=20)
        cap_violations = 0
        for r in reps:
            f = r.get('fields') or {}
            t = f.get('报告标题')
            if isinstance(t, list): t = ''.join(x.get('text','') for x in t if isinstance(x,dict))
            t = str(t)[:25]
            health = f.get('综合健康度')
            urg = f.get('决策紧急度')
            try:
                urg_n = int(float(urg)) if urg is not None else 0
            except: urg_n = 0
            cap = 3 if '🟢' in str(health) else (4 if '🟡' in str(health) else 5)
            ok = '✓' if urg_n <= cap else f'✗ 超 cap {cap}'
            print(f"  {t:25s} 健康={health!r:12s} 紧急={urg_n} cap={cap} {ok}")
            if urg_n > cap:
                cap_violations += 1
        if cap_violations:
            bugs.append(f"综合报告 紧急度未按健康度 cap：{cap_violations}/{len(reps)}（旧数据，需重跑或回填）")

        # === 5. 数字员工效能 处理任务数 vs 实际写入量 ===
        print("\n## 5. 数字员工效能 vs 实际岗位分析量")
        actual_count = Counter()
        for r in outs:
            f = r.get('fields') or {}
            role = f.get('角色')
            if isinstance(role, list):
                role = ''.join(x.get('text','') for x in role if isinstance(x,dict))
            actual_count[str(role or '?')] += 1
        perf = await bitable_ops.list_records(APP, TIDS['perf'], max_records=20)
        print(f"  实际写入: {dict(actual_count)}")
        for r in perf:
            f = r.get('fields') or {}
            n = f.get('员工姓名')
            if isinstance(n, list): n = ''.join(x.get('text','') for x in n if isinstance(x,dict))
            count = f.get('处理任务数')
            role = f.get('角色')
            if isinstance(role, list): role = ''.join(x.get('text','') for x in role if isinstance(x,dict))
            actual = actual_count.get(str(role or ''), 0)
            ok = '✓' if int(count or 0) == actual else f'✗ 实际={actual}'
            print(f"  {n!r:18s} role={role!r:20s} 处理={count} actual={actual} {ok}")
            if int(count or 0) != actual:
                bugs.append(f"效能[{n}] 处理任务数={count} 实际={actual}")

        # === 6. 综合报告：参与岗位数 / CEO决策事项 / 管理摘要 健全性 ===
        print("\n## 6. 综合报告内容 — 参与岗位数、决策事项")
        for i, r in enumerate(reps):
            f = r.get('fields') or {}
            t = f.get('报告标题')
            if isinstance(t, list): t = ''.join(x.get('text','') for x in t if isinstance(x,dict))
            t = str(t)[:25]
            participants = f.get('参与岗位数')
            decisions = f.get('CEO决策事项')
            if isinstance(decisions, list): decisions = ''.join(x.get('text','') for x in decisions if isinstance(x,dict))
            summary = f.get('管理摘要')
            if isinstance(summary, list): summary = ''.join(x.get('text','') for x in summary if isinstance(x,dict))
            d_len = len(str(decisions or ''))
            s_len = len(str(summary or ''))
            warn = ''
            if int(float(participants or 0)) != 7:
                warn += f' 参与{participants}≠7'
                bugs.append(f"报告[{t}] 参与岗位数={participants} 应=7")
            if d_len < 50:
                warn += f' 决策仅{d_len}c'
            print(f"  [{i}] {t:25s} 参与={participants} 决策={d_len}c 摘要={s_len}c{warn}")

        # === 7. 任务表完成时间/完成日期 双写检查 ===
        print("\n## 7. 任务完成时间 vs 完成日期 双写")
        time_only = 0
        date_only = 0
        both = 0
        for r in tasks:
            f = r.get('fields') or {}
            status = f.get('状态')
            if isinstance(status, list): status = ''.join(x.get('text','') for x in status if isinstance(x,dict))
            if '已完成' not in str(status or '') and '✅' not in str(status or ''):
                continue
            ct = f.get('完成时间')
            cd = f.get('完成日期')
            if isinstance(ct, list): ct = ''.join(x.get('text','') for x in ct if isinstance(x,dict))
            if ct and cd: both += 1
            elif ct: time_only += 1
            elif cd: date_only += 1
        print(f"  双写: {both}, 仅完成时间: {time_only}, 仅完成日期: {date_only}")
        if time_only > 0 and both == 0:
            bugs.append(f"完成日期 未被写入（{time_only} 个 completed 任务都缺）")

        # === 8. 综合报告主字段（报告标题）富文本 vs 字符串 ===
        print("\n## 8. 主字段类型一致性")
        for r in reps[:1]:
            f = r.get('fields') or {}
            t = f.get('报告标题')
            print(f"  报告标题 type={type(t).__name__}, 值={str(t)[:60]}")
            if isinstance(t, list):
                bugs.append(f"报告标题 仍返回 list（应已被 _flatten 拍平）")

        # === 9. 视图过滤命中率（重点：🟡 关注岗位）===
        print("\n## 9. 视图 filter 命中（健康度评级='🟡 关注'）")
        try:
            view_hit = await bitable_ops.list_records(
                APP, TIDS['output'],
                filter_expr='CurrentValue.[健康度评级]="🟡 关注"',
                max_records=200,
            )
        except Exception as e:
            view_hit = []
            print(f"  filter 失败: {e}")
        actual_hit = sum(1 for r in outs if (
            ((r.get('fields') or {}).get('健康度评级') == '🟡 关注') or
            (isinstance((r.get('fields') or {}).get('健康度评级'), list) and
             '🟡 关注' in ''.join(x.get('text','') for x in (r.get('fields') or {}).get('健康度评级') or [] if isinstance(x, dict)))
        ))
        print(f"  filter 命中: {len(view_hit)}, 实际值=🟡: {actual_hit}")
        if len(view_hit) != actual_hit:
            bugs.append(f"健康度=🟡 视图命中 {len(view_hit)} ≠ 实际 {actual_hit}（option_id 漂移残留）")

    # === BUG 总结 ===
    print(f"\n\n## ===== BUG 盘点 ({len(bugs)} 项) =====")
    for b in bugs:
        print(f"  - {b}")


asyncio.run(main())
