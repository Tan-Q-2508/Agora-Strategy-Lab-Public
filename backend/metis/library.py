"""Metis's quant library (METIS §11, D-81): what a senior quant researcher knows, retrieved by
relevance like Kairos's playbook. The sections live in ``library/*.md``; each ends, where it
can, with how to test the idea in Agora."""

from __future__ import annotations

from pathlib import Path

from backend.kairos.knowledge import Pack, Section

LIBRARY = Pack(Path(__file__).parent / "library")


def sections() -> tuple[Section, ...]:
    return LIBRARY.sections()


def search(query: str, k: int = 3, min_score: float = 2.0) -> list[Section]:
    return LIBRARY.search(query, k, min_score)


def for_prompt(query: str, budget_chars: int = 2400, k: int = 4) -> str:
    return LIBRARY.for_prompt(query, budget_chars, k)
