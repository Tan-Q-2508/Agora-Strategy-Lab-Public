# Everything CI would run, for Windows:  powershell -ExecutionPolicy Bypass -File scripts\check.ps1
# Fails if any check fails, or if frontend\dist is out of date with the source (D-12).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Step($name, [scriptblock]$cmd) {
    Write-Host "`n== $name"
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$name failed" }
}

Step "Python: lint (ruff)" { uv run ruff check backend tests scripts }
Step "Python: format (ruff)" { uv run ruff format --check backend tests scripts }
Step "Python: types (mypy --strict)" { uv run mypy }
Step "Python: tests (pytest)" { uv run pytest }

Push-Location frontend
try {
    if (-not (Test-Path node_modules)) { Step "Frontend: install" { npm ci } }
    Step "Frontend: lint (eslint)" { npx eslint . }
    Step "Frontend: types (tsc)" { npx tsc -b }
    Step "Frontend: tests (vitest)" { npx vitest run }
    Step "Frontend: build" { npx vite build }
} finally {
    Pop-Location
}

# Compares the fresh build with what is committed or staged (git add) for commit.
git diff --quiet -- frontend/dist
$dirty = $LASTEXITCODE -ne 0
$untracked = git ls-files --others --exclude-standard -- frontend/dist
if ($dirty -or $untracked) {
    git status --short -- frontend/dist
    throw "frontend/dist changed after building: add and commit the rebuilt files."
}
Write-Host "`nAll checks passed."
