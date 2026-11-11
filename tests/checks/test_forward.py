"""Forward checks (D-90): what Kairos and Metis saved, and portfolio sleeves, re-tested on the
candles formed after they were saved; undone when they stopped holding up."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.checks import forward, store
from backend.context import AppContext
from backend.db.models import KairosMemory, Portfolio, PortfolioSleeve, StrategyVersion
from backend.portfolio import service as portfolios
from backend.settings_store import update
from backend.strategy import revisions
from backend.strategy import service as strategies
from backend.strategy.templates import template_definition

DAY = 86_400_000


def _strategy(client: TestClient) -> int:
    d = template_definition("ma_crossover", "IN", ["RELIANCE", "TCS", "INFY"])
    r = client.post(
        "/api/strategies", json={"name": "Crossing", "definition": d.model_dump(mode="json")}
    )
    assert r.status_code == 201, r.json()
    return int(r.json()["strategy"]["id"])


def _metis_revision(ctx: AppContext, sid: int, days_ago: int) -> tuple[int, int]:
    """A Metis revision of the strategy saved ``days_ago`` days ago: (its id, its parent's)."""
    with ctx.db.session() as s:
        v1 = strategies.latest_version(s, sid)
        assert v1 is not None
        d = v1.definition.model_copy(deep=True)
        d.parameters[0].default = d.parameters[0].default + 5  # a tweak of the fast average
        saved = revisions.revise(
            s, sid, d, ctx.clock.now_ms(), author="metis", note="Metis: a slower fast line"
        )
        row = s.get(StrategyVersion, saved.version_id)
        assert row is not None
        row.created_at = ctx.clock.now_ms() - days_ago * DAY
        return saved.version_id, v1.id


def _set(ctx: AppContext, **values: Any) -> None:
    with ctx.db.session() as s:
        update(s, values, ctx.clock)


def test_a_revision_is_checked_on_the_candles_since(client: TestClient, ctx: AppContext) -> None:
    sid = _strategy(client)
    vid, parent = _metis_revision(ctx, sid, 300)
    subs = [x for x in forward.subjects(ctx) if x.kind == "revision"]
    assert [(x.version_id, x.baseline_version_id) for x in subs] == [(vid, parent)]
    assert forward.is_due(ctx, subs[0])
    c = forward.run_one(ctx, subs[0])
    assert c["verdict"] in ("holding", "slipping", "failed"), c
    r = c["result"]
    assert r["sessions"] > 150 and r["subject"] == "revision"
    assert r["numbers"][0]["label"] == "Version 2 made"
    assert r["can_undo"] == (c["verdict"] == "failed")
    assert not forward.is_due(ctx, subs[0])  # once a day
    assert forward.run_due(ctx) == []


def test_too_few_new_candles_waits(client: TestClient, ctx: AppContext) -> None:
    sid = _strategy(client)
    _metis_revision(ctx, sid, 10)
    (subj,) = forward.subjects(ctx)
    assert not forward.is_due(ctx, subj)
    item = forward.overview(ctx)[0]
    assert item["check"] is None and item["days_since"] == 10


def test_your_own_newer_version_ends_the_check(client: TestClient, ctx: AppContext) -> None:
    sid = _strategy(client)
    _metis_revision(ctx, sid, 300)
    with ctx.db.session() as s:
        latest = strategies.latest_version(s, sid)
        assert latest is not None
        d = latest.definition.model_copy(deep=True)
        d.sizing.value = 25.0
        revisions.revise(s, sid, d, ctx.clock.now_ms(), author="user", note="mine")
    assert forward.subjects(ctx) == []


def _failed(ctx: AppContext, subj: forward.Subject) -> dict[str, Any]:
    return {
        "verdict": "failed",
        "title": "Version 2 stopped holding up.",
        "text": "It made less.",
        "subject": subj.kind,
        "name": subj.name,
        "since": subj.since,
        "sessions": 60,
        "trades": 12,
        "numbers": [],
        "raw": {"new_net": -100.0, "old_net": 900.0},
        "can_undo": True,
        "undo_label": "Put version 1 back",
    }


def test_a_failed_revision_is_put_back_on_its_own(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _strategy(client)
    _vid, parent = _metis_revision(ctx, sid, 300)
    monkeypatch.setattr(forward, "check_revision", _failed)
    c = forward.run_one(ctx, forward.subjects(ctx)[0])
    assert c["action"].startswith("Version 1's rules were put back on its own as version 3")
    with ctx.db.session() as s:
        latest = strategies.latest_version(s, sid)
        v1 = strategies.get_version(s, parent)
        assert latest is not None and v1 is not None
        assert latest.version == 3 and latest.content_hash == v1.content_hash
        assert latest.created_by == "metis" and latest.source == f"forward-undo:{c['id']}"
        assert latest.note.startswith("Undid version 2")
        lessons = [m.text for m in s.query(KairosMemory).all()]
    assert any(t.startswith("Forward check: Crossing version 2 stopped") for t in lessons)
    # the put-back version isn't itself forward-checked, and acting twice changes nothing
    assert forward.subjects(ctx) == []
    assert forward.undo(ctx, c["id"])["action"] == c["action"]
    assert any(i["check"]["id"] == c["id"] for i in forward.overview(ctx))


def test_with_auto_undo_off_the_button_does_it(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _strategy(client)
    _metis_revision(ctx, sid, 300)
    _set(ctx, **{"revisions.auto_undo": False})
    monkeypatch.setattr(forward, "check_revision", _failed)
    c = forward.run_one(ctx, forward.subjects(ctx)[0])
    assert c["action"] == "" and c["result"]["can_undo"]
    r = client.post(f"/api/checks/{c['id']}/undo").json()
    assert r["check"]["action"].startswith("Version 1's rules were put back by you")
    with ctx.db.session() as s:
        latest = strategies.latest_version(s, sid)
        assert latest is not None and latest.created_by == "user"


def _sleeve(ctx: AppContext, sid: int, days_ago: int) -> tuple[int, int]:
    p = portfolios.create(ctx, market="IN", budget=200_000)
    with ctx.db.session() as s:
        v = strategies.latest_version(s, sid)
        assert v is not None
        row = PortfolioSleeve(
            portfolio_id=p["id"],
            strategy_id=sid,
            version_id=v.id,
            symbols=json.dumps(["RELIANCE", "TCS", "INFY"]),
            overrides="{}",
            size_pct=19.0,
            weight=0.5,
            capital=100_000.0,
            status="planned",
            reasons="[]",
            added_at=ctx.clock.now_ms() - days_ago * DAY,
        )
        s.add(row)
        s.flush()
        return int(p["id"]), int(row.id)


def test_a_sleeve_is_checked_against_its_exam_years(client: TestClient, ctx: AppContext) -> None:
    sid = _strategy(client)
    pid, slid = _sleeve(ctx, sid, 300)
    (subj,) = forward.subjects(ctx)
    assert subj.kind == "sleeve" and subj.sleeve_id == slid and subj.portfolio_id == pid
    c = forward.run_one(ctx, subj)
    assert c["verdict"] in ("holding", "slipping", "failed"), c
    labels = [n["label"] for n in c["result"]["numbers"]]
    assert labels[0] == "Made since it was added" and "Average exam-year day" in labels


def test_a_failed_draft_sleeve_leaves_the_plan(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _strategy(client)
    pid, slid = _sleeve(ctx, sid, 300)
    monkeypatch.setattr(forward, "check_sleeve", _failed)
    c = forward.run_one(ctx, forward.subjects(ctx)[0])
    assert c["action"] == ""  # a draft portfolio doesn't manage itself
    done = forward.undo(ctx, c["id"])
    assert done["action"].startswith("Taken out of the plan by you")
    with ctx.db.session() as s:
        row = s.get(PortfolioSleeve, slid)
        p = s.get(Portfolio, pid)
        assert row is not None and row.status == "retired" and p is not None


def test_the_api(client: TestClient, ctx: AppContext) -> None:
    sid = _strategy(client)
    _metis_revision(ctx, sid, 300)
    body = client.get("/api/checks/forward").json()
    assert body["auto_undo"] is True and body["items"][0]["check"] is None
    job = client.post("/api/checks/forward/run").json()["job_id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        j = client.get(f"/api/jobs/{job}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["checked"] == 1, j
    item = client.get("/api/checks/forward").json()["items"][0]
    assert item["check"]["verdict"] in ("holding", "slipping", "failed")
    with ctx.db.session() as s:
        listed = store.for_strategy(s, sid, "forward")
    assert listed[0]["id"] == item["check"]["id"]
    if item["check"]["verdict"] != "failed":
        r = client.post(f"/api/checks/{item['check']['id']}/undo")
        assert r.status_code == 400 and r.json()["error"]["code"] == "NOTHING_TO_UNDO"
    assert client.post("/api/checks/99999/undo").status_code == 404
