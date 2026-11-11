# Agora: a local stock-strategy lab

Agora lets you design, backtest and paper-trade stock strategies on your own computer,
with an optional local AI assistant (Ollama) that explains results and proposes ideas.
It is a full-stack portfolio project: Python backend, React frontend, one shared trading engine.

> **Not a trading tool.** There is no broker connection, no API keys and no order execution
> code. Paper trading uses a simulated account. Nothing here is financial advice.

## What it demonstrates

- **One engine, two clocks.** Backtests and live paper trading run the same strategy and
  fill code. Only the clock and the data feed differ (see `docs/DECISIONS.md`, D-04).
- **No look-ahead by construction.** A strategy only ever sees bars that have closed.
- **Ports and adapters.** Market data, the clock and the AI sit behind interfaces with real
  and fake implementations, so the whole test suite runs offline on seeded synthetic data.
- **Hand-calculated golden tests** for the engine, fill model, cost model and indicators.
- **Honest costs.** Brokerage, taxes and slippage are modelled in `Decimal` (`docs/COST_MODEL.md`).
- **AI that never trades.** The local LLM explains and drafts; orders come only from
  deterministic strategy code. Its numbers are checked against the data before display.
- **Research discipline.** Overfitting guards, out-of-sample checks, strategy lineage and a
  self-audit (`docs/AUDIT_2026-11.md`).
- **Plain-English UX** with a premium, motion-rich interface (`docs/DESIGN_BRIEF.md`).

## Stack

Python 3.12 (uv) · FastAPI · SQLAlchemy 2 + Alembic (SQLite) · pandas · RestrictedPython sandbox ·
React 19 + Vite + TypeScript + Tailwind v4 + shadcn/ui + Framer Motion ·
TradingView Lightweight Charts + Apache ECharts + Monaco · pytest, Vitest, Playwright.

## Where to look

| Path | What is there |
|---|---|
| `backend/engine`, `backend/backtest`, `backend/costs` | The shared engine, fills and cost model |
| `backend/strategy`, `backend/indicators` | Strategy runtime, sandbox, indicators |
| `backend/kairos`, `backend/metis` | The AI agent and AI researcher |
| `backend/portfolio`, `backend/paper` | Portfolio allocation and paper trading |
| `backend/data`, `backend/fakes` | Real and fake data sources |
| `frontend/src` | React app (the built app is in `frontend/dist`) |
| `tests/` | Unit, golden, journey and fixture-based tests |
| `SPEC.md`, `docs/` | Product spec, design decisions (`DECISIONS.md`), data model, API contract |

## Running it

Windows: double-click `Start Agora.bat`. macOS: `Start Agora.command`.
Or, with [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync
uv run pytest
uv run uvicorn --factory backend.main:create_app --port 8765
```

Then open http://localhost:8765. Market data comes from Yahoo Finance and other public
sources; Ollama is optional.

## Note on this repository

This is a public snapshot of a private working repository. Day-to-day planning logs and
personal notes were left out, so a few comments or docs refer to files not included here.
