"""The vault: the most recent stretch of history that research never sees (D-143).

Why: Metis's exam years are shown as verdicts round after round, and a research sprint tries
hundreds of variants, so both slowly learn the history they are judged on. The vault is
history nobody looks at while choosing: the sprint picks its finalists on the years before
it, then opens the vault **once** for those finalists. A strategy that only worked on the
years it was chosen on fails there.

The vault is measured back from the sprint's start, per timeframe, so it fits the history
Yahoo keeps (daily: decades; hourly: 2 years; 5- and 15-minute: 60 days; 1-minute: what
Agora has saved).
"""

from __future__ import annotations

DAY_MS = 86_400_000
VAULT_DAYS = {"1d": 365, "1h": 120, "15m": 12, "5m": 12, "1m": 4}


def start(timeframe: str, now_ms: int) -> int:
    """Where the vault begins: research may use candles before this, never after."""
    return now_ms - VAULT_DAYS.get(timeframe, 365) * DAY_MS
