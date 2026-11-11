"""The AI's reading size (D-141): Automatic, stepping down when the card is full, and a
Metis brief that fits instead of losing its start."""

from __future__ import annotations

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.ai import reading
from backend.config import Paths, database_url
from backend.context import AppContext
from backend.db.engine import Database
from backend.db.migrate import _alembic_config
from backend.db.models import SettingRow
from backend.fakes.ai_provider import FakeAIProvider
from backend.metis import brief
from backend.settings_store import read_all, update
from tests.metis.test_metis import _strategy


def ai(ctx: AppContext) -> FakeAIProvider:
    assert isinstance(ctx.ai, FakeAIProvider)
    return ctx.ai


def test_sizes_and_budget() -> None:
    assert reading.reading_size({"ai.num_ctx": 0, "ai.ctx_fit": 24576}) == 24576
    assert reading.reading_size({"ai.num_ctx": 8192, "ai.ctx_fit": 24576}) == 8192
    assert reading.reading_size({}) == reading.AUTO_START == 32768
    assert reading.step_down(32768) == 24576
    assert reading.step_down(12288) == 8192
    assert reading.step_down(8192) is None  # never below the floor
    assert reading.prompt_budget(32768) == 32768 - 6144 - 1536
    assert reading.prompt_budget(32768, thinking=False) == 32768 - 1536
    assert reading.tokens("abc" * 100) == 100


def test_automatic_by_default_and_steps_down_when_the_card_is_full(
    client: TestClient, ctx: AppContext
) -> None:
    st = client.get("/api/ai/status?fresh=true").json()
    assert st["auto_ctx"] is True and st["num_ctx"] == 32768
    # the model is wholly on the card: nothing changes
    ai(ctx).loaded = {"qwen3.5:4b": (4_500_000_000, 4_500_000_000)}
    assert ctx.ai_service.check_fit() is None
    # partly on the processor: one step down, remembered
    ai(ctx).loaded = {"qwen3.5:4b": (5_500_000_000, 4_000_000_000)}
    assert ctx.ai_service.check_fit() == 24576
    assert client.get("/api/ai/status?fresh=true").json()["num_ctx"] == 24576
    # wholly on the processor means the card is off (power mode), not a size problem
    ai(ctx).loaded = {"qwen3.5:4b": (4_500_000_000, 0)}
    assert ctx.ai_service.check_fit() is None
    # a size the user chose is never changed
    with ctx.db.session() as s:
        update(s, {"ai.num_ctx": 49152}, ctx.clock)
    ai(ctx).loaded = {"qwen3.5:4b": (6_000_000_000, 4_000_000_000)}
    assert ctx.ai_service.check_fit() is None
    st = client.get("/api/ai/status?fresh=true").json()
    assert st["num_ctx"] == 49152 and st["auto_ctx"] is False


def test_settings_accept_the_new_sizes(client: TestClient) -> None:
    assert client.put("/api/settings", json={"ai.num_ctx": 65536}).status_code == 200
    assert client.put("/api/settings", json={"ai.num_ctx": 0}).status_code == 200
    assert client.put("/api/settings", json={"ai.num_ctx": 5000}).status_code == 422


def test_a_brief_too_big_for_the_reading_size_leaves_out_the_least_needed(
    client: TestClient, ctx: AppContext
) -> None:
    sid, _vid = _strategy(client)
    full = brief.build(ctx, "", ["IN"])
    assert full.trimmed == [] and f"STRATEGY #{sid}" in full.text
    need = reading.tokens(full.text)
    small = brief.build(ctx, "", ["IN"], budget=need - 50)
    assert reading.tokens(small.text) < need
    assert small.trimmed and small.trimmed[0] in ("the web excerpts", "the library")
    # the strategy itself, its numbers and the indicator list are what's kept to the end
    assert f"STRATEGY #{sid}" in small.text and sid in small.baselines
    assert "Indicators you may use" in small.text
    roomy = brief.build(ctx, "", ["IN"], budget=10 * need)
    assert roomy.text == full.text


def test_upgrade_resets_a_small_reading_size_to_automatic(paths: Paths) -> None:
    """The user asked to make the AI read more (2026-11-03): a size below 16,384 he chose
    earlier becomes Automatic; bigger ones stay."""
    url = database_url(paths)
    cfg = _alembic_config(url)
    command.upgrade(cfg, "0011")
    db = Database(url)
    with db.session() as s:
        s.add(SettingRow(key="ai.num_ctx", value="4096", updated_at=0))
    command.upgrade(cfg, "head")
    with db.session() as s:
        assert (
            s.scalars(select(SettingRow.value).where(SettingRow.key == "ai.num_ctx")).one() == "0"
        )
        assert reading.reading_size(read_all(s)) == 32768
    db.engine.dispose()
