"""Agora's heartbeat: a stop that nobody saw can't stay unnoticed (D-218).

On 6 Nov Agora vanished for 40 minutes with no crash and no line in any log: Windows ended the
tray and the server together, so nothing inside Agora could say so. Something that is killed can't
report its own death, so the record is made by the *next* start: every 30 seconds the running app
writes ``data/heartbeat.json``, a clean stop marks it clean, and a start that finds no clean mark
writes down how long Agora was gone. A long gap between two beats of a running app is recorded too
(the laptop slept, or Agora froze). The record is ``data/logs/outages.jsonl``, shown on Home.

No process of its own: nothing runs while Agora is closed (CLAUDE §4).
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend import actions
from backend.logging_setup import get_logger

log = get_logger("uptime")

BEAT_S = 30.0
GAP_S = 180.0  # a beat this late means the laptop slept or Agora froze


class Uptime:
    def __init__(self, data_dir: Path, clock_s: Callable[[], float] = time.time) -> None:
        self.file = data_dir / "heartbeat.json"
        self.record = data_dir / "logs" / "outages.jsonl"
        self.clock = clock_s
        self.started_at = 0.0
        self.last_beat = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ the beat

    def _write(self, clean: bool) -> None:
        tmp = self.file.with_suffix(".tmp")
        body = {
            "pid": os.getpid(),
            "started_at": self.started_at,
            "last_beat": self.last_beat,
            "clean": clean,
        }
        tmp.write_text(json.dumps(body), encoding="utf-8")
        tmp.replace(self.file)

    def beat(self) -> None:
        now = self.clock()
        if self.last_beat and now - self.last_beat >= GAP_S:
            self._note("gap", self.last_beat, now)
        self.last_beat = now
        try:
            self._write(clean=False)
        except OSError:  # a full disk mustn't stop Agora; the diagnosis checks the disk
            log.warning("Couldn't write the heartbeat", exc_info=True)

    def _note(self, kind: str, start: float, end: float) -> dict[str, Any]:
        entry = {"kind": kind, "from": int(start * 1000), "to": int(end * 1000)}
        with contextlib.suppress(OSError):
            self.record.parent.mkdir(parents=True, exist_ok=True)
            with self.record.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        log.warning("Agora was away (%s) for %d minutes", kind, (end - start) / 60)
        actions.note(
            "outage",
            "Stopped with nobody seeing it" if kind == "stopped_unseen" else "A long gap",
            f"{(end - start) / 60:.0f} minutes",
            status="failed",
            away_from=entry["from"],
            away_to=entry["to"],
        )
        return entry

    # ------------------------------------------------------------ start and stop

    def start(self) -> None:
        now = self.clock()
        try:
            prev = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = None
        if prev and not prev.get("clean") and prev.get("last_beat"):
            self._note("stopped_unseen", float(prev["last_beat"]), now)
        self.started_at = now
        self.last_beat = 0.0
        self.beat()
        self._thread = threading.Thread(target=self._loop, name="agora-heartbeat", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(BEAT_S):
            self.beat()

    def shutdown(self) -> None:
        self._stop.set()
        self.last_beat = self.clock()
        with contextlib.suppress(OSError):
            self._write(clean=True)

    # ------------------------------------------------------------ reading

    def outages(self, days: float = 7.0) -> list[dict[str, Any]]:
        """Newest first; ``minutes`` rounded for reading."""
        since = (self.clock() - days * 86_400) * 1000
        try:
            lines = self.record.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            with contextlib.suppress(ValueError, KeyError):
                e = json.loads(line)
                if e["to"] >= since:
                    out.append({**e, "minutes": round((e["to"] - e["from"]) / 60_000)})
        return out[::-1]
