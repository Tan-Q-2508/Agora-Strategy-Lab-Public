"""Build higher-timeframe candles from lower ones (e.g. 15m from 5m).

Used when Yahoo can't serve a timeframe but Agora already holds a finer one
(DATA_SOURCES §7). Buckets are anchored to the session open, so a 15-minute NSE candle
starts at 09:15, 09:30, … like the exchange's own. Results are marked ``derived``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from backend.core.types import Bar, Timeframe

# ts → (session open ms, session close ms), or None when the bar is outside any session
SessionOf = Callable[[int], tuple[int, int] | None]


def aggregate(
    bars: Sequence[Bar], target: Timeframe, session_of: SessionOf, source_tf: Timeframe
) -> list[Bar]:
    """Combine ``bars`` (one timeframe, oldest first) into ``target`` candles.

    A bucket is only emitted when it is complete: every lower bar it should contain is
    present. A half-built candle would mislead strategies, so it is dropped instead.
    """
    step = target.minutes * 60_000
    sub = source_tf.minutes * 60_000
    buckets: dict[int, list[Bar]] = {}
    ends: dict[int, int] = {}
    for b in bars:
        sess = session_of(b.ts)
        if sess is None:
            continue
        open_ms, close_ms = sess
        start = open_ms + ((b.ts - open_ms) // step) * step
        buckets.setdefault(start, []).append(b)
        ends[start] = min(start + step, close_ms)
    out: list[Bar] = []
    for start in sorted(buckets):
        group = buckets[start]
        expected = -(-(ends[start] - start) // sub)  # ceil
        if len(group) < expected:
            continue
        out.append(
            Bar(
                ts=start,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
                source="derived",
                split_factor=group[-1].split_factor,
            )
        )
    return out
