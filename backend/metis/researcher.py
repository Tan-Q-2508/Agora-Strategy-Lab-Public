"""Metis researches on its own while Agora is open (METIS §6, §13, §14, D-77, D-81, D-83).

A background thread checks every 30 seconds whether a round is due. A round is due when
Metis is switched on (``metis.enabled``) and ``metis.every_minutes`` have passed since the last
one (the first comes a minute after Agora opens, or at the next check after the switch is
turned on). It waits, and says why, while:

- a backtest, research, training, improvement, scan or portfolio job is running,
- the user talked to Kairos in the last minute (the graphics card answers the user first).

Each round first picks a direction (``agenda.py``): improve what's in use, improve the others,
discover new strategies, or look for opportunities (the scanner, code only). Then it builds the
brief (study years only, with a senior quant's first look and the library), lets the model think
up to three ideas, tests each in the shared engine, keeps what held up (``metis.apply``, through
the revision gateway), and writes it all in the notebook. Without the AI helper it runs a
**playbook round**: the first experiments from the expert's first look and the textbook
strategies the user doesn't have. Nothing here places an order (D-56). The thread lives and
dies with the app (D-06).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from backend import actions
from backend.ai import reading
from backend.ai.ollama import AIUnavailable
from backend.core.heavy import background_turn
from backend.logging_setup import get_logger
from backend.metis import agenda, apply, brief, notebook, think, trial
from backend.settings_store import read_all

log = get_logger("metis")
# playbook entries tested first in each discovery round, before the AI's own ideas (D-150)
SPRINT_PER_ROUND = 2
TICK_S = 30.0
FIRST_WAIT_MS = 60_000
SWITCH_ON_WAIT_MS = 0
USER_QUIET_MS = 60_000
BUSY_KINDS = (
    "backtest",
    "kairos_research",
    "kairos_train",
    "kairos_improve",
    "kairos_learn",
    "opportunity_scan",
    "portfolio_plan",
    "portfolio_backtest",
)


class Metis:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.started_at = ctx.clock.now_ms()
        self.last_round_at: int | None = None
        self.next_round_at: int | None = None
        self.working = False
        self.doing = ""  # what Metis is doing right now, in plain words
        self.direction: str | None = None  # this round's direction (D-83)
        self.waiting = ""  # why it is waiting, in plain words
        self._was_on = False

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """App start. Practice-data sessions (tests, the cloud) don't run the thread unless
        asked (``AGORA_METIS=1``); the laptop always does, and it only works when switched on."""
        if self.ctx.data_mode != "real" and not os.environ.get("AGORA_METIS"):
            return
        notebook.close_unfinished(self.ctx)  # rounds cut off when Agora last closed
        self._thread = threading.Thread(target=self._loop, name="metis", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def poke(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(TICK_S)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                if self.due():
                    with background_turn("Metis"):
                        self.round("auto")
            except Exception:  # a bad round must never take the app down
                log.exception("Metis's round failed")

    # ------------------------------------------------------------ when

    def settings(self) -> dict[str, Any]:
        with self.ctx.db.session() as s:
            st = read_all(s)
        return {
            "enabled": bool(st["metis.enabled"]),
            "every_minutes": int(st["metis.every_minutes"]),
            "apply": bool(st["metis.apply"]),
            "focus": str(st["metis.focus"]),
            "model": str(st["ai.model"]),
            "num_ctx": reading.reading_size(st),
            "ai_enabled": bool(st["ai.enabled"]),
            "own_ideas": bool(st["metis.own_ideas"]),
            "markets": list(st["markets"]),
        }

    def ai_ready(self) -> tuple[bool, str]:
        st = self.settings()
        if not st["ai_enabled"]:
            return False, "The AI helper is switched off in Settings → AI helper."
        if not st["own_ideas"]:
            # D-166: Claude writes Metis's ideas for a while (the user, 2026-11-05)
            return False, "Metis's own ideas are switched off in Settings → Metis."
        status = self.ctx.ai_service.status()
        if status.get("state") != "ready":
            return False, (
                "Metis needs the AI helper (Ollama) to think. Open Settings → AI helper to set "
                "it up; Metis starts by itself once it's ready."
            )
        return True, ""

    def busy(self) -> str:
        if any(
            j.status in ("queued", "running") and j.kind in BUSY_KINDS for j in self.ctx.jobs.list()
        ):
            return "Waiting for a backtest or study job to finish."
        agent = self.ctx.services.get("kairos")
        last = getattr(agent, "last_active_ms", None)
        if getattr(agent, "active", 0) or (
            last is not None and self.ctx.clock.now_ms() - last < USER_QUIET_MS
        ):
            return "Waiting while you talk to Kairos."
        return ""

    def due(self) -> bool:
        """Is a round due now? Also keeps ``next_round_at`` and ``waiting`` up to date."""
        st = self.settings()
        now = self.ctx.clock.now_ms()
        if not st["enabled"]:
            self._was_on, self.next_round_at, self.waiting = False, None, ""
            return False
        if not self._was_on:
            self._was_on = True
            first = self.started_at + FIRST_WAIT_MS
            self.next_round_at = (
                max(now + SWITCH_ON_WAIT_MS, first) if self.last_round_at is None else now
            )
        if self.next_round_at is None:
            self.next_round_at = (self.last_round_at or now) + st["every_minutes"] * 60_000
        if now < self.next_round_at:
            self.waiting = ""
            return False
        # Without the AI helper Metis still runs playbook rounds (D-81); it only waits for
        # running jobs and for the user's chats with Kairos.
        self.waiting = self.busy()
        return not self.waiting

    # ------------------------------------------------------------ status

    def status(self) -> dict[str, Any]:
        st = self.settings()
        ready, why = self.ai_ready()
        if self.working:
            state = "working"
        elif not st["enabled"]:
            state = "off"
        elif self.waiting:
            state = "waiting"
        elif not ready:
            state = "playbook"
        else:
            state = "scheduled"
        last = notebook.rounds(self.ctx, limit=1)
        return {
            "on": st["enabled"],
            "state": state,
            "doing": self.doing if self.working else "",
            "waiting": self.waiting,
            "ai_note": "" if ready else why,
            "direction": self.direction
            if self.working
            else (last[0]["direction"] if last else None),
            "ai_ready": ready,
            "thread": self._thread is not None and self._thread.is_alive(),
            "last_round_at": self.last_round_at,
            "next_round_at": self.next_round_at if st["enabled"] else None,
            "every_minutes": st["every_minutes"],
            "apply": st["apply"],
            "focus": st["focus"],
            "totals": notebook.totals(self.ctx),
        }

    # ------------------------------------------------------------ one round

    def _say(self, text: str) -> None:
        self.doing = text
        log.info("Metis: %s", text)

    def round(self, trigger: str = "user") -> dict[str, Any]:
        """One round of research. ``trigger``: ``auto`` (the thread) or ``user`` (Research now)."""
        if not self._lock.acquire(blocking=False):
            return {"status": "skipped", "note": "Metis is already researching."}
        act = actions.track("metis_round", "Metis research round", who="metis", why=trigger)
        try:
            out = self._round(trigger)
            done = str(out.get("note") or out.get("status") or "")
            if out.get("status") == "failed":
                act.failed(done, round_id=out.get("round_id"))
            else:
                act.done(
                    done,
                    round_id=out.get("round_id"),
                    ideas=out.get("ideas"),
                    kept=out.get("kept"),
                    direction=out.get("direction"),
                )
            try:
                from backend.metis import lists

                made = lists.refresh(self.ctx, self.settings()["markets"])
                if made:
                    out["lists"] = made
            except Exception:  # lists are a bonus
                log.exception("Metis's watchlists failed")
            return out
        except Exception as exc:
            act.failed(repr(exc))
            raise
        finally:
            self.working = False
            self.doing = ""
            self._lock.release()

    def _round(self, trigger: str) -> dict[str, Any]:
        st = self.settings()
        ready, why = self.ai_ready()
        self.working = True
        choice = agenda.choose(self.ctx, st["focus"])
        self.direction = choice.direction
        model = st["model"] if ready else "playbook"
        rid = notebook.start_round(self.ctx, trigger, st["focus"], model, choice.direction)
        now = self.ctx.clock.now_ms()
        self.last_round_at = now
        self.next_round_at = now + st["every_minutes"] * 60_000
        kept = tried = 0
        try:
            if choice.direction == "opportunities":
                return self._scan_round(rid, st, choice)
            self._say(f"This round: {agenda.WORDS[choice.direction]} ({choice.why}).")
            seeds = (
                agenda.discover_seeds(self.ctx, st["markets"])
                if choice.direction == "discover"
                else []
            )
            self._say("Reading the evidence and its senior quant's first look…")
            b = brief.build(
                self.ctx,
                st["focus"],
                st["markets"],
                direction=choice.direction,
                in_use=agenda.in_use(self.ctx),
                discover_seeds=seeds,
                budget=reading.prompt_budget(st["num_ctx"]) - reading.tokens(think.PERSONA),
            )
            notebook.update_round(self.ctx, rid, brief=b.text)
            ideas, noticed, thinking = self._ideas(b, st, ready, why)
            notebook.update_round(self.ctx, rid, noticed=noticed, thinking=thinking)
            for n, idea in enumerate(ideas, start=1):
                self._say(f"Testing idea {n} of {len(ideas)}: {idea['title']}…")
                outcome = self._test(idea, b, st)
                if outcome is None:
                    continue
                tried += 1
                iid = notebook.add_idea(
                    self.ctx,
                    rid,
                    kind=idea["kind"],
                    title=idea["title"],
                    why=idea["why"],
                    market_code=outcome.market,
                    strategy_id=outcome.strategy_id,
                    strategy_version_id=outcome.version_id,
                    spec=json.dumps(outcome.rules),
                    fingerprint=outcome.fingerprint,
                    status=outcome.status,
                    verdict=outcome.verdict,
                    result=json.dumps(outcome.result),
                    origin=idea.get("origin", "ai"),
                )
                if outcome.status == "held_up":
                    kept += 1
                    if st["apply"]:
                        self._say(f"Saving “{idea['title']}”…")
                        try:
                            apply.save(self.ctx, iid, auto=True)
                        except Exception as exc:
                            log.warning("Metis couldn't save idea %s: %s", iid, exc)
            note = _round_note(len(ideas), tried, kept, st["apply"])
            if not ready:
                note += f" (Playbook round: {why})"
            notebook.update_round(
                self.ctx,
                rid,
                status="done",
                finished_at=self.ctx.clock.now_ms(),
                note=note,
                ideas=tried,
                kept=kept,
            )
            return {
                "status": "done",
                "round_id": rid,
                "note": note,
                "ideas": tried,
                "kept": kept,
                "direction": choice.direction,
            }
        except think.GaveWay:
            note = (
                "Paused so Kairos could answer you first; Metis picks up again a minute after "
                "your chat."
            )
            notebook.update_round(
                self.ctx,
                rid,
                status="done",
                finished_at=self.ctx.clock.now_ms(),
                note=note,
                ideas=tried,
                kept=kept,
            )
            return {"status": "done", "round_id": rid, "note": note, "ideas": tried, "kept": kept}
        except AIUnavailable as exc:
            note = f"The AI helper stopped answering ({exc}). Metis will try again next round."
        except Exception as exc:
            log.exception("Metis's round %s failed", rid)
            note = f"Something went wrong in this round ({type(exc).__name__}); see the log file."
        notebook.update_round(
            self.ctx,
            rid,
            status="failed",
            finished_at=self.ctx.clock.now_ms(),
            note=note,
            ideas=tried,
            kept=kept,
        )
        return {"status": "failed", "round_id": rid, "note": note}

    def _ideas(
        self, b: brief.Brief, st: dict[str, Any], ready: bool, why: str
    ) -> tuple[list[dict[str, Any]], str, str]:
        """(ideas to test, what was noticed, the model's thinking). The research sprint's
        playbook entries first, exactly as the sprint found them (D-144, D-150: the small model
        is weak at inventing and was ignoring them), then the AI's ideas when it can think and
        they can be used; otherwise the playbook's first experiments."""
        playbook = [
            i for i in b.seeds if not notebook.seen(self.ctx, trial.fingerprint_of(i, b.baselines))
        ]
        sprint = [i for i in playbook if i.get("playbook")][:SPRINT_PER_ROUND]
        if not ready:
            noticed = (
                "Working from the playbook: the AI helper isn't available "
                f"({why}) Testing a senior quant's first experiments."
            )
            return playbook[: think.MAX_IDEAS], noticed, ""
        self._say("Thinking up ideas…")
        kairos = self.ctx.services.get("kairos")
        thought = think.think(
            self.ctx.ai,
            b.text,
            model=st["model"],
            num_ctx=st["num_ctx"],
            give_way=lambda: bool(getattr(kairos, "active", 0)),
        )
        try:
            self.ctx.ai_service.check_fit()
        except Exception:  # the size check must never spoil a round
            log.exception("Reading size check failed")
        fresh = [
            i
            for i in thought.ideas
            if not notebook.seen(self.ctx, trial.fingerprint_of(i, b.baselines))
        ]
        if fresh:
            room = max(0, think.MAX_IDEAS - len(sprint))
            own = fresh[:room]
            # slots the model spent on repeats go to the first look's untested ideas (D-157):
            # the small model kept proposing fixes already tested, and the round lost them
            spare = [i for i in playbook if i not in sprint][: room - len(own)]
            noticed = thought.noticed
            if spare and len(own) < len(thought.ideas[:room]):
                noticed = (noticed + " " if noticed else "") + (
                    "Some of its own ideas were repeats, so Metis also tested its senior quant's "
                    "untested suggestions."
                )
            return sprint + own + spare, noticed, thought.thinking
        noticed = thought.noticed
        if playbook:
            noticed = (noticed + " " if noticed else "") + (
                "Its own ideas couldn't be used or were repeats, so Metis tested its playbook's "
                "first experiments instead."
            )
        return playbook[: think.MAX_IDEAS], noticed, thought.thinking

    def _scan_round(self, rid: int, st: dict[str, Any], choice: agenda.Choice) -> dict[str, Any]:
        from backend.portfolio import scan

        self._say("Looking for new stocks for strategies that work…")
        notes, found = [], 0
        for m in st["markets"]:
            out = scan.scan(self.ctx, m, progress=lambda _p, msg: self._say(msg))
            notes.append(out["note"])
            found += len(out["found"])
        note = "Opportunities: " + " ".join(notes)
        notebook.update_round(
            self.ctx,
            rid,
            status="done",
            finished_at=self.ctx.clock.now_ms(),
            note=note,
            noticed=f"This round: {agenda.WORDS['opportunities']} ({choice.why}).",
            brief="The opportunity scanner (code only): every strategy on every stock of the "
            "market, stocks chosen on the study years and judged on the exam years.",
            ideas=0,
            kept=found,
        )
        return {
            "status": "done",
            "round_id": rid,
            "note": note,
            "ideas": 0,
            "kept": found,
            "direction": "opportunities",
        }

    def _test(self, idea: dict[str, Any], b: brief.Brief, st: dict[str, Any]) -> Any:
        """One idea through the tests, with a log entry that says what became of it (D-220)."""
        with actions.track(
            "metis_idea",
            str(idea.get("title") or idea.get("kind") or "An idea"),
            who="metis",
            why=str(idea.get("why") or idea.get("rationale") or "")[:300],
            idea_kind=idea.get("kind"),
        ) as act:
            out = self._try(idea, b, st)
            if out is None:
                act.skipped("Tested before: a repeat teaches nothing.")
            else:
                act.done(f"{out.status}: {out.verdict}", market=out.market)
            return out

    def _try(self, idea: dict[str, Any], b: brief.Brief, st: dict[str, Any]) -> Any:
        fp = trial.fingerprint_of(idea, b.baselines)
        if notebook.seen(self.ctx, fp):
            return None  # tested before: a repeat teaches nothing
        if idea["kind"] == "new_strategy":
            ready, _why = self.ai_ready()
            return trial.try_new(
                self.ctx,
                idea,
                fp,
                provider=self.ctx.ai if ready else None,
                model=st["model"],
                num_ctx=st["num_ctx"],
                markets=b.markets,
            )
        base = b.baselines.get(idea["strategy_id"] or -1)
        if base is None and len(b.baselines) == 1:
            # one strategy was shown: a wrong or missing number can only mean that one
            base = next(iter(b.baselines.values()))
            idea["strategy_id"] = base.strategy_id
            fp = trial.fingerprint_of(idea, b.baselines)
            if notebook.seen(self.ctx, fp):
                return None
        if base is None:
            return trial.Outcome(
                "untestable",
                f"Metis named a strategy it wasn't shown (#{idea['strategy_id']}).",
                trial.rules_of(idea),
                fp,
            )
        return trial.try_change(self.ctx, idea, base, fp)


def _round_note(proposed: int, tried: int, kept: int, applied: bool) -> str:
    if proposed == 0:
        return "Metis didn't come up with a usable idea this round."
    repeats = proposed - tried
    bits = [f"Tested {tried} idea{'s' if tried != 1 else ''}"]
    if repeats:
        bits.append(f"skipped {repeats} it had tried before")
    if kept:
        held = f"{kept} held up"
        bits.append(
            held + (" and was saved" if kept == 1 else " and were saved") if applied else held
        )
    else:
        bits.append("none held up")
    return "; ".join(bits) + "."
