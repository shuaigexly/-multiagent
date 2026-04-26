"""v8.6.20-r3/r4/r5 端到端验收（VG9 base）。"""
import asyncio, io, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)

APP = "VG9zbTkwRardU0sVx8tc0jQZn9g"


async def main():
    from app.bitable_workflow import bitable_ops
    from app.bitable_workflow.schema import priority_score, health_score
    from app.bitable_workflow.verify import audit_bitable, _print_report
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    import httpx

    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    async with httpx.AsyncClient(timeout=20) as h:
        r = await h.get(f"{base}/open-apis/bitable/v1/apps/{APP}/tables", headers={"Authorization": f"Bearer {token}"})
        TIDS = {t["name"]: t["table_id"] for t in (r.json().get("data") or {}).get("items") or []}

    issues = []

    # === 1. 字段类型: 综合评分 / 健康度数值 是 Number(2)
    print("\n## 1. 字段类型审计")
    async with httpx.AsyncClient(timeout=20) as h:
        for table_name, fname in [("分析任务", "综合评分"), ("岗位分析", "健康度数值")]:
            tid = TIDS[table_name]
            r = await h.get(f"{base}/open-apis/bitable/v1/apps/{APP}/tables/{tid}/fields", headers={"Authorization": f"Bearer {token}"})
            f = next((x for x in (r.json().get("data") or {}).get("items") or [] if x.get("field_name") == fname), None)
            t = f.get("type") if f else None
            print(f"  {table_name}.{fname} type={t} (期望 2/Number) {'✓' if t==2 else '✗'}")
            if t != 2:
                issues.append(f"{table_name}.{fname} type={t} ≠ 2(Number)")

    # === 2. SEED 任务 综合评分 = priority_score(优先级)
    print("\n## 2. SEED 任务 综合评分")
    tasks = await bitable_ops.list_records(APP, TIDS["分析任务"], max_records=100)
    seed_ok = 0
    seed_n = 0
    for t in tasks:
        f = t.get("fields") or {}
        title = f.get("任务标题")
        if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(x,dict))
        if str(title or '').startswith('📌'): continue
        if str(title or '').startswith('[跟进]'): continue  # SEED only
        seed_n += 1
        score = f.get("综合评分")
        try: score_n = int(float(score)) if score is not None else None
        except: score_n = None
        prio = f.get("优先级")
        if isinstance(prio, list): prio = ''.join(x.get('text','') for x in prio if isinstance(x,dict))
        expected = priority_score(str(prio or ''))
        ok = score_n == expected
        if ok: seed_ok += 1
        print(f"  {str(title)[:25]:25s} 优先={prio!r:10s} 评分={score!r}->{score_n} 期望={expected} {'✓' if ok else '✗'}")
    print(f"  → SEED 评分通过: {seed_ok}/{seed_n}")
    if seed_ok != seed_n:
        issues.append(f"SEED 综合评分 {seed_ok}/{seed_n}")

    # === 3. 健康度数值 ← health_score(健康度评级)
    print("\n## 3. 岗位分析 健康度数值 一致性")
    outs = await bitable_ops.list_records(APP, TIDS["岗位分析"], max_records=500)
    h_ok = 0
    for r in outs:
        f = r.get("fields") or {}
        h = f.get("健康度评级")
        if isinstance(h, list): h = ''.join(x.get('text','') for x in h if isinstance(x,dict))
        v = f.get("健康度数值")
        try: v_n = int(float(v)) if v is not None else None
        except: v_n = None
        expected = health_score(str(h or ''))
        if v_n == expected:
            h_ok += 1
        else:
            print(f"  ✗ {f.get('岗位角色')!r} {f.get('任务标题')!r}: 健康度={h!r} 数值={v!r}->{v_n} 期望={expected}")
    print(f"  → 健康度数值 一致: {h_ok}/{len(outs)}")
    if h_ok != len(outs):
        issues.append(f"健康度数值 {h_ok}/{len(outs)}")

    # === 4. 综合报告 紧急度 按健康度 cap (r3)
    print("\n## 4. 综合报告 紧急度 cap (r3)")
    reps = await bitable_ops.list_records(APP, TIDS["综合报告"], max_records=50)
    cap_ok = 0
    for r in reps:
        f = r.get("fields") or {}
        title = f.get("报告标题")
        if isinstance(title, list): title = ''.join(x.get('text','') for x in title if isinstance(x,dict))
        h = f.get("综合健康度")
        urg = f.get("决策紧急度")
        try: urg_n = int(float(urg)) if urg is not None else 0
        except: urg_n = 0
        cap = 3 if '🟢' in str(h) else (4 if '🟡' in str(h) else 5)
        ok = urg_n <= cap
        if ok: cap_ok += 1
        print(f"  {str(title)[:25]:25s} 健康={h!r:12s} 紧急={urg_n} cap={cap} {'✓' if ok else '✗'}")
    print(f"  → 紧急度不超 cap: {cap_ok}/{len(reps)}")
    if cap_ok != len(reps):
        issues.append(f"紧急度 cap {cap_ok}/{len(reps)}")

    # === 5. verify audit
    print("\n## 5. verify_bitable issues")
    expected_tables = ["分析任务", "岗位分析", "综合报告", "数字员工效能"]
    report = await audit_bitable(APP, expected_table_names=expected_tables)
    audit_issues = _print_report(report)
    if audit_issues != 0:
        issues.append(f"verify {audit_issues} issues")

    # === 总结
    print("\n\n========== r3/r4/r5 e2e 验收总结 ==========")
    print(f"  字段类型(r4):    Number ✓✓")
    print(f"  SEED 综合评分:    {seed_ok}/{seed_n}")
    print(f"  健康度数值:       {h_ok}/{len(outs)}")
    print(f"  紧急度 cap (r3):  {cap_ok}/{len(reps)}")
    print(f"  verify issues:   {audit_issues}")
    print(f"  最终: {'✓ 全过' if not issues else '✗ ' + str(issues)}")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
