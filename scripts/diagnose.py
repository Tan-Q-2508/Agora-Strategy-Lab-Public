"""The repeatable diagnosis (WEEKEND_BRIEF §3): is Agora right, not just running?

    python scripts/diagnose.py                  checks on the live data; writes a dated report
    python scripts/diagnose.py --journeys       also runs the failure journeys (needs dev tools)

Read-only against the running app and its database; safe while desks trade. The report goes to
`data/logs/diagnosis-YYYY-MM-DD-HHMM.md`. See `docs/DIAGNOSIS.md` for what each part covers.
Exit code 0 when every check passed, 1 otherwise.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db.engine import Database  # noqa: E402
from backend.diagnosis import market_data, opportunities, reconcile  # noqa: E402
from backend.diagnosis.charges import charges_match_model  # noqa: E402

DB = ROOT / "data" / "agora.db"
API = "http://127.0.0.1:8765/api"


def ask(path: str) -> dict:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=30) as r:
            return json.load(r)
    except OSError as exc:
        return {"unreachable": str(exc)}


def actions_part(lines: list[str]) -> int:
    file = ROOT / "data" / "actions.db"
    if not file.exists():
        lines.append("- **FAIL** no action log yet")
        return 1
    c = sqlite3.connect(f"file:{file.as_posix()}?mode=ro", uri=True, timeout=10)
    since = int((time.time() - 86_400) * 1000)
    rows = c.execute(
        """select kind, count(*), sum(status='failed'), sum(status='cut_off'),
                  sum(status='running'), cast(avg(ms) as int), max(ms)
           from actions where started_at >= ? group by 1 order by 2 desc""",
        (since,),
    ).fetchall()
    lines.append("\n## What Agora did in the last day\n")
    lines.append("| Work | Times | Failed | Cut off | Running | Avg ms | Longest ms |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    expected = {"autopilot_round", "news_read", "metis_round", "data_fetch"}
    missing = sorted(expected - {r[0] for r in rows})
    if missing:
        lines.append(f"\n**Silent:** nothing logged today from {', '.join(missing)}")
    return 1 if missing else 0


def main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    lines = [f"# Agora diagnosis, {stamp}\n"]
    bad = 0
    health = ask("/health")
    lines.append("## Running\n")
    if "unreachable" in health:
        lines.append(f"- **FAIL** Agora isn't answering: {health['unreachable']}")
        bad += 1
    else:
        lines.append(f"- Agora answers, database ok: {health.get('db_ok')}")
        down = [s["source"] for s in health.get("data_sources", []) if s["state"] != "ok"]
        lines.append(f"- Sources not ok: {', '.join(down) or 'none'}")
    alarms = ask("/alarms").get("alarms", [])
    lines.append(f"- Alarms: {len(alarms)}")
    lines += [f"  - {a['level']}: {a['what']}" for a in alarms]
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=60)
    for title, checks in (
        ("The books", reconcile.CHECKS),
        ("The data", market_data.CHECKS),
    ):
        lines.append(f"\n## {title}\n")
        for check in checks:
            chk = check(c)
            word = "ok" if chk.ok else ("WARN" if chk.severity == "warning" else "**FAIL**")
            lines.append(f"- {word} {chk.question} ({chk.checked} checked) {chk.note}")
            lines += [f"  - {x}" for x in chk.faults[:12]]
            if not chk.ok and chk.severity == "error":
                bad += 1
    chk = charges_match_model(Database())
    word = "ok" if chk.ok else "**FAIL**"
    lines.append("\n## Charges\n")
    lines.append(f"- {word} {chk.question} ({chk.checked} checked)")
    lines += [f"  - {x}" for x in chk.faults[:12]]
    bad += int(not chk.ok)
    rep = opportunities.measure(c, 28)
    lines.append("\n## Big up-days of the last 28 days, and what stopped each\n")
    for market in ("IN", "US"):
        lines.append(f"**{market}**\n")
        lines += [f"- {n}: {why} (average +{pct:.1f}%)" for why, n, pct in rep.table(market)]
    bad += actions_part(lines)
    if "--journeys" in sys.argv:
        lines.append("\n## Journeys\n")
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/journeys", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        lines.append(f"- {'ok' if out.returncode == 0 else '**FAIL**'}: {out.stdout[-300:]}")
        bad += int(out.returncode != 0)
    lines.insert(1, f"**{'All checks passed' if bad == 0 else f'{bad} checks failed'}**\n")
    report = ROOT / "data" / "logs" / f"diagnosis-{stamp}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print("\n".join(lines))
    print(f"\nSaved to {report}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
