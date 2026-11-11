#!/usr/bin/env bash
# Everything CI would run. Run before every commit:  bash scripts/check.sh
# Fails if any check fails, or if frontend/dist is out of date with the source (D-12).
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

step "Python: lint (ruff)"
uv run ruff check backend tests scripts
uv run ruff format --check backend tests scripts

step "Python: types (mypy --strict)"
uv run mypy

step "Python: tests (pytest)"
uv run pytest

cd frontend
if [ ! -d node_modules ]; then
  step "Frontend: install"
  npm ci
fi

step "Frontend: lint (eslint)"
npx eslint .

step "Frontend: types (tsc)"
npx tsc -b

step "Frontend: tests (vitest)"
npx vitest run

step "Frontend: build"
npx vite build

step "End-to-end: smoke test (Playwright, practice data)"
npx playwright test
cd ..

step "Frontend: committed build is up to date"
# Compares the fresh build with what is committed or staged (git add) for commit.
if ! git diff --quiet -- frontend/dist || [ -n "$(git ls-files --others --exclude-standard -- frontend/dist)" ]; then
  git status --short -- frontend/dist
  echo "frontend/dist changed after building: add and commit the rebuilt files." >&2
  exit 1
fi

printf '\nAll checks passed.\n'
