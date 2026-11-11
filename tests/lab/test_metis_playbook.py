"""Metis starts discovery from the research sprint's playbook (D-144)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.context import AppContext
from backend.lab import families, playbook
from backend.metis import agenda, trial


def _entry(works_in: list[str]) -> dict:
    f = families.BY_KEY["sma_cross"]
    return {
        "key": "sma_cross:IN:1d",
        "family": "sma_cross",
        "name": f.name,
        "why": f.why,
        "style": f.style,
        "market": "IN",
        "timeframe": "1d",
        "settings": {"fast": 20, "slow": 100},
        "definition": f.definition("IN", "1d", ["RELIANCE", "INFY", "TCS"]),
        "tested_on": ["RELIANCE", "INFY", "TCS"],
        "sprint": "t1",
        "study": {"trades": 60},
        "exam": {"trades": 25},
        "vault": {"trades": 8},
        "regimes": {r: {"trades": 20, "avg_return_pct": 0.4} for r in works_in},
        "works_in": works_in,
        "avoid_in": [],
    }


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "playbook.json"
    monkeypatch.setattr(playbook, "PATH", path)
    return path


def test_discovery_starts_from_the_playbook(
    client: TestClient,
    stocked: AppContext,
    book: Path,
) -> None:
    regime = agenda.market_regime(stocked, "IN")
    playbook.save([_entry([regime] if regime else [])])
    seeds = agenda.discover_seeds(stocked, ["IN"], limit=5)
    first = seeds[0]
    assert first["playbook"] == "sma_cross:IN:1d" and first["title"].startswith("Playbook:")
    if regime:
        assert "suits today's market" in first["why"]
    assert any(s.get("template") for s in seeds[1:])  # textbook strategies follow

    out = trial.try_new(
        stocked,
        first,
        trial.fingerprint_of(first, {}),
        provider=None,
        model="",
        num_ctx=0,
        markets=["IN"],
    )
    assert out.status in ("held_up", "rejected"), out.verdict
    assert out.rules["playbook"] == "sma_cross:IN:1d" and out.rules["definition"]


def test_an_empty_playbook_changes_nothing(
    client: TestClient,
    stocked: AppContext,
    book: Path,
) -> None:
    seeds = agenda.discover_seeds(stocked, ["IN"], limit=3)
    assert seeds and all(s.get("template") for s in seeds)


def test_a_waiting_playbook_gets_every_third_round(
    client: TestClient,
    stocked: AppContext,
    book: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-149: discovery's old record would almost never win the draw against the scanner, so
    while a playbook entry waits to be tested, discover gets at least every third round."""
    from backend.metis import notebook

    monkeypatch.setattr(agenda, "strategy_count", lambda _c: 3)
    monkeypatch.setattr(agenda, "in_use", lambda _c: [])
    monkeypatch.setattr(agenda, "scan_worth_it", lambda _c: True)

    def done(direction: str) -> None:
        rid = notebook.start_round(stocked, "auto", "", "m", direction)
        notebook.update_round(stocked, rid, status="done")

    done("opportunities")
    done("opportunities")
    playbook.save([])
    assert not agenda.playbook_waiting(stocked)
    regime = agenda.market_regime(stocked, "IN")
    playbook.save([_entry([regime] if regime else [])])
    assert agenda.playbook_waiting(stocked)
    c = agenda.choose(stocked, round_no=1)
    assert c.direction == "discover" and "playbook" in c.why
    done("discover")
    assert "playbook" not in agenda.choose(stocked, round_no=1).why  # not every round


def test_playbook_entries_are_tested_before_the_models_own_ideas(
    stocked: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-150: with the AI ready, a discovery round still tests up to two playbook entries first,
    exactly as the sprint found them, then fills the rest with the model's ideas."""
    from types import SimpleNamespace

    from backend.metis import researcher, think

    seeds = [
        {"kind": "new_strategy", "playbook": f"p{k}", "title": f"Playbook: {k}", "market": "US"}
        for k in range(3)
    ] + [{"kind": "new_strategy", "template": "t", "title": "Textbook", "market": "US"}]
    own = [{"kind": "new_strategy", "title": f"Own {k}", "market": "US"} for k in range(3)]
    monkeypatch.setattr(
        think, "think", lambda *a, **k: SimpleNamespace(ideas=own, noticed="n", thinking="t")
    )
    monkeypatch.setattr(trial, "fingerprint_of", lambda i, _b: i["title"])
    metis = stocked.services["metis"]
    b = SimpleNamespace(seeds=seeds, baselines={}, text="brief")
    ideas, _n, _t = metis._ideas(b, {"model": "m", "num_ctx": 16384}, True, "")
    titles = [i["title"] for i in ideas]
    assert titles[: researcher.SPRINT_PER_ROUND] == ["Playbook: 0", "Playbook: 1"]
    assert titles[researcher.SPRINT_PER_ROUND :] == ["Own 0"]
    assert len(ideas) == think.MAX_IDEAS


def test_a_playbook_entry_is_judged_against_the_playbook_not_every_idea(
    client: TestClient,
    stocked: AppContext,
    book: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-151: the luck check counts a playbook entry against the market's playbook (the sprint
    already counted its family's grid), not against every strategy the model ever invented."""
    from backend.metis import notebook

    regime = agenda.market_regime(stocked, "IN")
    playbook.save([_entry([regime] if regime else [])])
    monkeypatch.setattr(notebook, "tries", lambda *_a, **_k: 1300)  # the model's long history
    assert trial.playbook_tries(stocked, "IN") == 1
    assert trial.playbook_tries(stocked, "US") == 1  # never zero
    seen: list[int] = []
    real = trial.luck
    monkeypatch.setattr(trial, "luck", lambda r, n: seen.append(n) or real(r, n))
    first = agenda.discover_seeds(stocked, ["IN"], limit=1)[0]
    trial.try_new(
        stocked,
        first,
        trial.fingerprint_of(first, {}),
        provider=None,
        model="",
        num_ctx=0,
        markets=["IN"],
    )
    assert seen == [1]


def test_slots_spent_on_repeats_go_to_untested_suggestions(
    stocked: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-157: the model kept proposing fixes already tested; those slots now go to the first
    look's untested suggestions instead of being skipped."""
    from types import SimpleNamespace

    from backend.metis import notebook, researcher, think

    seeds = [{"kind": "tweak", "title": f"Suggestion {k}", "strategy_id": 1} for k in range(3)]
    own = [{"kind": "tweak", "title": t, "strategy_id": 1} for t in ("Old A", "New B", "Old C")]
    monkeypatch.setattr(
        think, "think", lambda *a, **k: SimpleNamespace(ideas=own, noticed="", thinking="t")
    )
    monkeypatch.setattr(trial, "fingerprint_of", lambda i, _b: i["title"])
    monkeypatch.setattr(notebook, "seen", lambda _c, fp: fp.startswith("Old"))
    metis = stocked.services["metis"]
    b = SimpleNamespace(seeds=seeds, baselines={}, text="brief")
    ideas, noticed, _t = metis._ideas(b, {"model": "m", "num_ctx": 16384}, True, "")
    assert [i["title"] for i in ideas] == ["New B", "Suggestion 0", "Suggestion 1"]
    assert "untested suggestions" in noticed
    assert len(ideas) <= think.MAX_IDEAS and researcher.SPRINT_PER_ROUND == 2
