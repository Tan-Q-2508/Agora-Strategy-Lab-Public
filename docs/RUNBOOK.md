# RUNBOOK: launching, setup and troubleshooting

## 1. Launchers (built in Phase 0.4)

Two files at the repo root, double-clickable:

**`Start Agora.bat` (Windows, primary)**
1. Opens a small console window titled "Agora: keep this window open".
2. If `uv` is not found: install it using Astral's official PowerShell installer, then
   refresh PATH for this window.
3. `uv sync --frozen --no-dev` (installs Python 3.12 automatically if missing, plus
   dependencies).
4. `uv run --frozen --no-dev python -m backend.launch`, which does steps 5–8 (D-19):
5. If port 8765 is busy: check whether it's already Agora (`/api/health`); if yes, just
   open the browser; if not, show a plain message and exit.
6. Back up `data/agora.db` if a migration is pending, run `alembic upgrade head`, and seed
   reference data (`backend/db/migrate.py`; also runnable alone with
   `uv run python -m backend.db.migrate`). Then start uvicorn in-process on 127.0.0.1:8765.
7. When `/api/health` responds, open `http://localhost:8765` in the default browser.
8. Print in plain words: "Agora is running. Close this window to stop Agora."
9. Closing the window stops the server cleanly (paper sessions marked stopped/paused).

**Since 2026-10-25 (D-124) steps 4–9 run without a terminal window:** once dependencies are in
place the .bat starts `.venv\Scripts\pythonw.exe -m backend.desktop.tray` and closes. The tray
icon (by the clock) starts the server as a windowless child process (`backend/desktop/supervisor.py`,
output in `data/logs/server.log`), opens Agora in its own window (Chrome or Edge `--app`, no tabs or
address bar; `backend/desktop/window.py`) unless an open window reconnects within 12 s (D-111), and
offers **Open Agora** (also a double-click), **Restart Agora**, **Open the log folder** and **Stop
Agora**. Stop and Restart ask the server to shut down cleanly (`POST /api/system/quit`, local only)
and force it only after 30 s. If the server stops on its own the tray starts it again (at most 3
times an hour). A second double-click while the tray runs just opens a window (the tray holds port
8766). On first run the tray puts an **Agora** shortcut with the logo on the Desktop (the real one,
often in OneDrive), which starts the .bat minimised; deleting it is harmless. Without
`pythonw.exe` the .bat falls back to the old console way.

**`Start Agora.command` (macOS)**: same steps with the shell installer and `open`; since D-124
it starts the tray (an icon in the menu bar) in the background and the Terminal window can be
closed.

Both scripts:
- Write progress to the console in plain English ("Setting up Agora for the first time.
  This takes a few minutes…").
- Log setup output to `data/logs/launcher.log`; the app itself logs to `data/logs/agora.log`
  (rotating, 5 × 2 MB); the tray icon to `data/logs/tray.log` (D-158).
- On any failure print one plain-English line + "Details are in data/logs/launcher.log".

## 2. First run
1. Launcher sets up Python and dependencies (a few minutes).
2. Browser opens to onboarding: pick markets → download daily history (progress bar) →
   run a template backtest.
3. Optional: Settings → AI helper → install Ollama and download the model.

## 3. Updating
User pulls in GitHub Desktop, then double-clicks the launcher. The launcher's `uv sync`
and `alembic upgrade head` apply new dependencies and database changes automatically.
Migrations must never delete user data; destructive changes need a backup step first
(copy `agora.db` to `data/backups/agora-YYYYMMDD-HHMM.db`).

## 4. Folder layout (on the laptop)
```
Agora/
  Start Agora.bat / Start Agora.command
  backend/  frontend/  tests/  scripts/  docs/
  data/            ← created at runtime, never committed
    agora.db
    logs/
    backups/
```

## 5. Troubleshooting (plain-English table also shown in Settings → Diagnostics)

| Symptom | Likely cause | What Agora tells the user |
|---|---|---|
| Browser says "can't connect" | Server not started or crashed | "Agora isn't running. Double-click Start Agora again." |
| "Yahoo is limiting requests" | Rate limit | "Using saved data; will retry automatically." |
| Data stops updating in paper trading | Yahoo outage / laptop slept | Banner + freshness badge turns red; resumes automatically |
| AI helper unavailable | Ollama not installed/running/model missing | Setup card with the exact next step |
| AI answers slowly; Task Manager shows the graphics card idle | Ollama started at sign-in before the NVIDIA card woke, so it found only the processor (its `server.log`: `inference compute … library=cpu`) | Agora restarts Ollama by itself (D-101). By hand: right-click the Ollama icon → Quit Ollama, start it again. Check: `curl localhost:11434/api/ps` shows `size_vram` equal to `size` |
| Pages stay blank after an update | The open window still runs the screens from before the update and asks for page files the new build replaced | Agora reloads itself once when that happens (D-137); in a window opened before D-137, press Ctrl+R once |
| Port already in use | Another app on 8765 | "Another program is using Agora's port. Restart your computer or close that program." |
| Data library broken after Yahoo change | `yfinance` outdated | Diagnostics: "Update data library" button (`uv add yfinance@latest` then restart) |

## 6. Support bundle
Settings → Diagnostics → "Create support bundle" zips `data/logs/`, the settings table,
recent `app_events` and `data_fetch_log`, and version info, then opens the folder. The user
can attach it in a Claude Code session to get a fix.

## 7. For Claude Code sessions
- Run `bash scripts/check.sh` (or `scripts\check.ps1`) before every commit. It runs ruff,
  mypy, pytest, eslint, tsc, vitest, rebuilds `frontend/dist`, and fails if the rebuilt
  `dist` differs from what is committed or staged.
- Regenerate fixtures with `uv run python scripts/make_fixtures.py` (deterministic).
- After changing `backend/db/models.py`, create a migration with
  `uv run alembic revision --autogenerate -m "..."` and review it; a test fails if models and
  migrations disagree.
- Never assume the cloud session can reach Yahoo/NSE/Stooq/Ollama.
- If a change needs the user to test on the laptop, say exactly what to click.

## 7a. A research sprint (Claude, in a laptop session; D-143)
Run from the Agora folder while Agora is open or closed; it reads saved prices only.
1. `uv run python -m backend.lab families` (the 32 families and their variants).
2. `uv run python -m backend.lab run --sprint 2026-11` (every family, both markets; add
   `--families a,b`, `--markets IN`, `--timeframes 1d`, `--stocks 40` to narrow or widen).
3. `uv run python -m backend.lab report --sprint 2026-11` (study and exam numbers only).
4. `uv run python -m backend.lab pick --sprint 2026-11` (finalists by the fixed rules).
5. `uv run python -m backend.lab vault --sprint 2026-11` (once; it refuses a second time).
6. `uv run python -m backend.lab promote --sprint 2026-11`, then run the tests and commit
   `backend/seed_data/playbook.json`. Never hand-edit finalists or numbers.
7. Write new families (with a reason) for the next sprint from what the report shows; a new
   sprint name gets a fresh vault start.

## 8. Starting without a terminal window (suggestions 2026-10-24; options 1 and 2 built 2026-10-25, D-124)

The user asked whether Agora can start without the black terminal window, or as a single program.
Options offered (nothing built until he picks one, PROGRESS 19.8):
1. **Tray app (recommended):** `Start Agora` runs with `pythonw` (no window) and puts a small Agora
   icon by the clock with *Open*, *Restart*, *Stop* and *Open the log*. Closing the browser tab no
   longer matters; Stop is in the tray.
2. **Its own window (app mode):** open Agora in Edge/Chrome `--app=http://localhost:8765`, a window
   with no tabs or address bar, plus the tray icon. Looks like a desktop program; still the same app.
3. **A real desktop program (pywebview or Tauri):** one `Agora.exe` with its own window. Most native,
   but a big build step, and every update means rebuilding the program.
4. **Start with Windows:** any of the above can also start when the laptop signs in.

## Logs and diagnosis (Phase 27)

- **Logs page:** everything Agora did. `scripts/actions.py` reads the same log from a terminal.
- **Home:** alarms appear only when something needs a look.
- **`data/logs/outages.jsonl`:** every stop nobody saw and every long gap (D-218).
- **From a tool:** restart with `scripts/restart_agora.ps1`; never start Agora directly from a tool.

