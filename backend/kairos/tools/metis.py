"""Kairos's tool for Metis, its AI researcher (METIS §8): what it found, switch it on or off,
give it a focus, research now."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from backend.kairos.tools.base import Args, Env, Result, Tool
from backend.metis import notebook
from backend.settings_store import update

WORDS = {
    "held_up": "held up",
    "saved": "held up and saved",
    "rejected": "didn't hold up",
    "untestable": "couldn't be tested",
}


class MetisArgs(Args):
    action: Literal["status", "on", "off", "now"] = Field(
        "status",
        description="status: what Metis has found; on/off: switch it; now: start a round now.",
    )
    focus: str | None = Field(
        None, description="Optional: what Metis should look into, in the user's words."
    )


def metis(env: Env, a: MetisArgs) -> Result:
    ctx = env.ctx
    m = ctx.services["metis"]
    changes: dict[str, object] = {}
    if a.action in ("on", "off"):
        changes["metis.enabled"] = a.action == "on"
    if a.focus is not None:
        changes["metis.focus"] = a.focus.strip()[:500]
    if changes:
        with ctx.db.session() as s:
            update(s, changes, ctx.clock)
        m.poke()
    lines: list[str] = []
    ready, why = m.ai_ready()
    st = m.status()
    if a.action == "now":
        if not ready:
            lines.append(why)
        elif m.working:
            lines.append("Metis is already researching.")
        else:
            ctx.jobs.submit("metis_round", "Metis is researching", lambda jc: m.round("user"))
            lines.append("Metis started a round of research; its notebook fills in as it goes.")
    lines.append(
        f"Metis is {'on' if st['on'] else 'off'}"
        + (
            f", researching every {st['every_minutes']} minutes while Agora is open"
            if st["on"]
            else ""
        )
        + "."
    )
    if st["focus"]:
        lines.append(f"Its focus: {st['focus']}")
    if not ready:
        lines.append(why)
    t = st["totals"]
    lines.append(
        f"So far it has tested {t['tested']} ideas; {t['held_up']} held up on years it hadn't "
        f"seen and {t['saved']} were saved to your strategies."
    )
    for i in notebook.ideas(ctx, limit=5):
        lines.append(
            f"- {i['title']} ({i['kind']}): {WORDS.get(i['status'], i['status'])}. {i['verdict']}"
        )
    card = {
        "type": "list",
        "title": "Metis, the AI researcher",
        "items": [{"label": x, "sub": "", "link": None} for x in lines[:5]],
        "link": "/metis",
    }
    label = {
        "on": "Switched Metis on",
        "off": "Switched Metis off",
        "now": "Asked Metis to research",
    }.get(a.action, "Checked Metis's notebook")
    return Result(True, "\n".join(lines), label, "", card, {"navigate": "/metis"})


TOOLS = [
    Tool(
        "metis",
        "Metis is Kairos's AI researcher: while Agora is open it thinks up ideas to improve the "
        "user's strategies, tests each one on years it never saw, and keeps only what holds up. "
        "Use this to say what Metis found, switch it on or off, give it a focus, or start a "
        "round now.",
        MetisArgs,
        metis,
        lambda a: "Checking with Metis…",
        group="metis",
    ),
]
