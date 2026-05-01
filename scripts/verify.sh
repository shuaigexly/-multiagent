#!/usr/bin/env bash
# v8.6.20-r50 一键验收脚本（POSIX 版） — 跑完 8 步把所有核心可验证项过一遍。
# 用法：bash scripts/verify.sh [--with-randomly] [--with-frontend]
#
# 步骤：
#   1. git 状态
#   2. backend pytest（标准顺序）
#   3. 多种子 random-order 稳定性 (--with-randomly)
#   4. backend compileall
#   5. frontend pytest + tsc + build (--with-frontend)
#   6. OpenAPI spec 重新导出
#   7. CLI 烟雾测试（--help）
#   8. 提交清单 checklist
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON_BIN:-python}"
WITH_RANDOMLY=0
WITH_FRONTEND=0
for arg in "$@"; do
  case "$arg" in
    --with-randomly) WITH_RANDOMLY=1 ;;
    --with-frontend) WITH_FRONTEND=1 ;;
    -h|--help)
      echo "Usage: bash scripts/verify.sh [--with-randomly] [--with-frontend]"
      exit 0 ;;
  esac
done

step=1
section() {
  echo ""
  echo "=========================================================="
  echo " 第 ${step} 步 · $1"
  echo "=========================================================="
  step=$((step + 1))
}

failures=0
mark_fail() { failures=$((failures + 1)); echo "❌ FAIL: $1"; }
mark_ok()  { echo "✓ $1"; }

# ---- 1. git status ----
section "Git 状态 + HEAD"
git log --oneline -3 || mark_fail "git log"
git status --short | head -10
mark_ok "Git readable"

# ---- 2. backend pytest（标准顺序）----
section "Backend pytest（标准顺序）"
if "$PY" -m pytest backend/tests -q --no-header 2>&1 | tail -3; then
  mark_ok "pytest 标准顺序"
else
  mark_fail "pytest 标准顺序"
fi

# ---- 3. 多种子 random-order 稳定性 ----
if [ "$WITH_RANDOMLY" -eq 1 ]; then
  section "Backend pytest --randomly × 4 seeds"
  for seed in 1 42 20260501 99999; do
    echo "  --- seed=$seed ---"
    if "$PY" -m pytest backend/tests -q -p randomly --randomly-seed=$seed --no-header 2>&1 | tail -2; then
      mark_ok "seed=$seed"
    else
      mark_fail "seed=$seed"
    fi
  done
else
  section "Backend pytest --randomly（跳过；加 --with-randomly 启用）"
fi

# ---- 4. compileall ----
section "Backend compileall（语法 + import 完整性）"
if "$PY" -m compileall -q backend/app backend/tests; then
  mark_ok "compileall"
else
  mark_fail "compileall"
fi

# ---- 5. frontend ----
if [ "$WITH_FRONTEND" -eq 1 ]; then
  section "Frontend vitest + tsc + build"
  pushd frontend > /dev/null
  if npx vitest run 2>&1 | tail -5; then mark_ok "vitest"; else mark_fail "vitest"; fi
  if npx tsc --noEmit 2>&1 | tail -5; then mark_ok "tsc"; else mark_fail "tsc"; fi
  if npm run build 2>&1 | tail -5; then mark_ok "vite build"; else mark_fail "vite build"; fi
  popd > /dev/null
else
  section "Frontend（跳过；加 --with-frontend 启用）"
fi

# ---- 6. OpenAPI spec 导出 ----
section "OpenAPI spec 一键导出"
pushd backend > /dev/null
if "$PY" -m scripts.export_openapi --pretty --out ../docs/openapi.json 2>&1 | tail -5; then
  mark_ok "OpenAPI 导出"
else
  mark_fail "OpenAPI 导出"
fi
popd > /dev/null

# ---- 7. CLI smoke (run from backend/ — app/ package lives there) ----
section "CLI 烟雾测试 (--help)"
pushd backend > /dev/null
if "$PY" -m app.cli --help 2>&1 | head -20; then
  mark_ok "CLI --help"
else
  mark_fail "CLI --help"
fi
popd > /dev/null

# ---- 8. 提交清单 ----
section "提交清单"
declare -a CHECK_FILES=(
  "docs/COMPETITION_SUBMISSION_DRAFT.md"
  "docs/COMPETITION_SELF_AUDIT.md"
  "docs/openapi.json"
  "backend/app/cli.py"
  "backend/scripts/export_openapi.py"
  "frontend/src/components/TaskActionsToolbar.tsx"
  "README.md"
)
for f in "${CHECK_FILES[@]}"; do
  if [ -f "$f" ]; then
    size=$(wc -c < "$f")
    mark_ok "$f ($size bytes)"
  else
    mark_fail "$f 缺失"
  fi
done

# ---- 总结 ----
echo ""
echo "=========================================================="
if [ $failures -eq 0 ]; then
  echo "✅ 全部步骤通过"
  exit 0
else
  echo "❌ $failures 个步骤失败 — 见上述 FAIL 行"
  exit 1
fi
