# v8.6.20-r50 one-shot acceptance script (PowerShell). Run all core checks.
# Usage: powershell -File scripts\verify.ps1 [-WithRandomly] [-WithFrontend]
# (ASCII-only labels to avoid Win PS 5.1 codepage breakage on UTF-8 .ps1 files)
param(
    [switch]$WithRandomly,
    [switch]$WithFrontend
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$step = 1
$failures = 0

function Section($title) {
    Write-Host ""
    Write-Host "=========================================================="
    Write-Host (" Step {0} - {1}" -f $script:step, $title)
    Write-Host "=========================================================="
    $script:step++
}

function MarkOk($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function MarkFail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; $script:failures++ }

# 1. git
Section "Git status + HEAD"
git log --oneline -3
git status --short | Select-Object -First 10
MarkOk "Git readable"

# 2. backend pytest standard order
Section "Backend pytest (default order)"
& $python -m pytest backend/tests -q --no-header 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -eq 0) { MarkOk "pytest default" } else { MarkFail "pytest default" }

# 3. random-order seeds
if ($WithRandomly) {
    Section "Backend pytest --randomly x 4 seeds"
    foreach ($seed in @(1, 42, 20260501, 99999)) {
        Write-Host "  --- seed=$seed ---"
        & $python -m pytest backend/tests -q -p randomly --randomly-seed=$seed --no-header 2>&1 | Select-Object -Last 2
        if ($LASTEXITCODE -eq 0) { MarkOk "seed=$seed" } else { MarkFail "seed=$seed" }
    }
} else {
    Section "Backend pytest --randomly (skipped; pass -WithRandomly to run)"
}

# 4. compileall
Section "Backend compileall (syntax + import sanity)"
& $python -m compileall -q backend/app backend/tests
if ($LASTEXITCODE -eq 0) { MarkOk "compileall" } else { MarkFail "compileall" }

# 5. frontend
if ($WithFrontend) {
    Section "Frontend vitest + tsc + build"
    Push-Location frontend
    npx vitest run 2>&1 | Select-Object -Last 5
    if ($LASTEXITCODE -eq 0) { MarkOk "vitest" } else { MarkFail "vitest" }
    npx tsc --noEmit 2>&1 | Select-Object -Last 5
    if ($LASTEXITCODE -eq 0) { MarkOk "tsc" } else { MarkFail "tsc" }
    npm run build 2>&1 | Select-Object -Last 5
    if ($LASTEXITCODE -eq 0) { MarkOk "vite build" } else { MarkFail "vite build" }
    Pop-Location
} else {
    Section "Frontend (skipped; pass -WithFrontend to run)"
}

# 6. OpenAPI export
Section "OpenAPI spec export"
Push-Location backend
& $python -m scripts.export_openapi --pretty --out ../docs/openapi.json 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -eq 0) { MarkOk "OpenAPI export" } else { MarkFail "OpenAPI export" }
Pop-Location

# 7. CLI smoke (must run from backend/ where app/ package lives)
# Don't pipe through Select-Object — early pipeline close makes Python report
# non-zero on Windows. Capture all output, then trim for display.
Section "CLI smoke test (--help)"
Push-Location backend
$cliOut = & $python -m app.cli --help 2>&1
$cliRc = $LASTEXITCODE
$cliOut | Select-Object -First 8
if ($cliRc -eq 0 -and ($cliOut -match "preflight")) { MarkOk "CLI help" } else { MarkFail "CLI help (rc=$cliRc)" }
Pop-Location

# 8. checklist
Section "Submission checklist files"
$checkFiles = @(
    "docs/COMPETITION_SUBMISSION_DRAFT.md",
    "docs/COMPETITION_SELF_AUDIT.md",
    "docs/openapi.json",
    "backend/app/cli.py",
    "backend/scripts/export_openapi.py",
    "frontend/src/components/TaskActionsToolbar.tsx",
    "README.md"
)
foreach ($f in $checkFiles) {
    if (Test-Path $f) {
        $size = (Get-Item $f).Length
        MarkOk "$f ($size bytes)"
    } else {
        MarkFail "$f missing"
    }
}

Write-Host ""
Write-Host "=========================================================="
if ($failures -eq 0) {
    Write-Host "[PASS] all steps OK" -ForegroundColor Green
    exit 0
} else {
    Write-Host ("[FAIL] {0} steps failed - see [FAIL] lines above" -f $failures) -ForegroundColor Red
    exit 1
}
