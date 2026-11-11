"""Silence is a failure: what should have happened and didn't (WEEKEND_BRIEF §3, D-222).

A log shows what happened; nothing logs what never happened. These checks are fast enough for Home
to ask every minute. Each alarm says what is wrong and what will happen next, in plain words.
"""

from __future__ import annotations

import shutil
from typing import Any

from backend import actions

# how long each kind of work may run before it counts as stuck
STUCK_MS = {
    "autopilot_round": 3_600_000,
    "metis_round": 2 * 3_600_000,
    "metis_idea": 3_600_000,
    "kairos_train": 3 * 3_600_000,
    "news_read": 1_800_000,
    "ai_call": 1_800_000,
}
# how often each kind of work should happen while Agora is open
EXPECTED_EVERY_MS = {
    "autopilot_round": 3 * 3_600_000,
    "news_read": 3 * 3_600_000,
}
MIN_FREE_GB = 5.0
OUTAGE_HOURS = 48


def _alarm(level: str, what: str, next_step: str, key: str) -> dict[str, str]:
    return {"level": level, "what": what, "next": next_step, "key": key}


def outages(ctx: Any) -> list[dict[str, str]]:
    uptime = ctx.services.get("uptime")
    if uptime is None:
        return []
    out = []
    for e in uptime.outages(days=OUTAGE_HOURS / 24):
        if e["kind"] == "stopped_unseen":
            out.append(
                _alarm(
                    "warn",
                    f"Agora stopped with nobody seeing it, for {e['minutes']} minutes.",
                    "Desks checked their stops on the missed candles when it came back.",
                    f"outage-{e['from']}",
                )
            )
        elif e["minutes"] >= 15:
            out.append(
                _alarm(
                    "info",
                    f"Agora froze or the laptop slept for {e['minutes']} minutes.",
                    "Nothing to do; it carried on by itself.",
                    f"gap-{e['from']}",
                )
            )
    return out


def desks(ctx: Any) -> list[dict[str, str]]:
    out = []
    for d in ctx.desk.desks():
        fresh = d.get("freshness") or {}
        if d.get("state") == "stopped":
            continue
        if fresh.get("level") == "red":
            out.append(
                _alarm(
                    "error",
                    f"{d['name']} has no fresh prices: {fresh.get('text', '')}",
                    "Open trades are kept. Agora keeps trying.",
                    f"desk-{d['id']}",
                )
            )
        elif d.get("state") == "paused_data":
            out.append(
                _alarm(
                    "warn",
                    f"{d['name']} is waiting for prices.",
                    "New trades are paused until prices return.",
                    f"desk-{d['id']}",
                )
            )
    return out


def stuck_work(ctx: Any) -> list[dict[str, str]]:
    store = actions.current()
    if store is None:
        return []
    now = ctx.clock.now_ms()
    out = []
    for row in store.search(status="running", since_ms=now - 2 * 86_400_000, limit=200):
        limit = STUCK_MS.get(row["kind"])
        if limit is not None and now - row["started_at"] > limit:
            mins = (now - row["started_at"]) // 60_000
            out.append(
                _alarm(
                    "warn",
                    f"{row['what']} has been running for {mins} minutes without finishing.",
                    "If it doesn't finish, restarting Agora ends it safely.",
                    f"stuck-{row['id']}",
                )
            )
    return out


def silent_work(ctx: Any) -> list[dict[str, str]]:
    store = actions.current()
    if store is None:
        return []
    now = ctx.clock.now_ms()
    uptime = ctx.services.get("uptime")
    up_since = int(uptime.started_at * 1000) if uptime is not None else 0
    last = {r["kind"]: r["last_at"] for r in store.summary(now - 7 * 86_400_000)}
    out = []
    for kind, every in EXPECTED_EVERY_MS.items():
        seen = max(last.get(kind) or 0, up_since)
        if up_since and now - seen > every:
            hours = (now - seen) / 3_600_000
            out.append(
                _alarm(
                    "warn",
                    f"Nothing from {kind.replace('_', ' ')} for {hours:.0f} hours.",
                    "It should run on its own; restart Agora if this stays.",
                    f"silent-{kind}",
                )
            )
    return out


def disk(ctx: Any) -> list[dict[str, str]]:
    free = shutil.disk_usage(ctx.paths.data_dir).free / 1e9
    if free < MIN_FREE_GB:
        return [
            _alarm(
                "error",
                f"Only {free:.1f} GB of disk left.",
                "Free some space; Agora can't save prices on a full disk.",
                "disk",
            )
        ]
    return []


def current(ctx: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for check in (outages, desks, stuck_work, silent_work, disk):
        try:
            out += check(ctx)
        except Exception as exc:  # an alarm check must never break Home
            out.append(_alarm("warn", f"A health check failed: {exc!r}", "See the log.", "check"))
    order = {"error": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda a: order.get(a["level"], 3))
