"""The research service (D-129): Kairos's ``web_research`` tool and Metis's briefs use it."""

from __future__ import annotations

from typing import Any

from backend.logging_setup import get_logger
from backend.research.web import FakeWeb, Findings, HttpWeb, Researcher
from backend.settings_store import read_setting

log = get_logger("research")


class ResearchService:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        web = FakeWeb() if ctx.data_mode == "fake" else HttpWeb()
        self.researcher = Researcher(web, ctx.clock.now_ms)

    def enabled(self) -> bool:
        return bool(read_setting(self.ctx.db, "research.enabled"))

    def research(self, question: str, pages: int = 3) -> Findings:
        if not self.enabled():
            return Findings(question, note="Web research is switched off in Settings → Kairos.")
        try:
            return self.researcher.research(question, pages)
        except Exception:  # the web must never break a round or a chat
            log.exception("Web research failed for %r", question)
            return Findings(question, note="Agora couldn't read the web just now.")
