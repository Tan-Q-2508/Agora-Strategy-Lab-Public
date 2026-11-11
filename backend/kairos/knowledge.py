"""Kairos's knowledge pack: a curated trading playbook, retrieved by relevance (KAIROS §1).

The small local model can't hold a textbook in its head, so the textbook lives here as
short sections (``knowledge/*.md``: a ``## Title``, a ``tags:`` line, a paragraph or two)
and the few sections that match the user's question go into the prompt. Ranking is BM25
over the section text, with the title and tags counted three times: fast, offline and
predictable.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DIR = Path(__file__).parent / "knowledge"
_WORD = re.compile(r"[a-z0-9%&+]+(?:[-'][a-z0-9]+)*")
STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "it",
    "this",
    "that",
    "with",
    "as",
    "at",
    "by",
    "be",
    "what",
    "how",
    "why",
    "does",
    "do",
    "i",
    "me",
    "my",
    "you",
    "your",
    "can",
    "should",
    "would",
    "about",
    "tell",
    "explain",
    "please",
    "kairos",
    "when",
}


def words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP]


@dataclass(frozen=True)
class Section:
    doc: str
    title: str
    tags: tuple[str, ...]
    body: str

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"


class Pack:
    """A folder of ``*.md`` sections, searchable by BM25 (Kairos's playbook, Metis's library)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._sections: tuple[Section, ...] | None = None
        self._idx: tuple[list[Counter[str]], dict[str, float], float] | None = None

    def sections(self) -> tuple[Section, ...]:
        if self._sections is None:
            out: list[Section] = []
            for path in sorted(self.folder.glob("*.md")):
                doc = path.stem
                for chunk in path.read_text(encoding="utf-8").split("\n## ")[1:]:
                    title, _, rest = chunk.partition("\n")
                    tags: tuple[str, ...] = ()
                    lines = rest.strip().splitlines()
                    if lines and lines[0].startswith("tags:"):
                        tags = tuple(lines[0][5:].split())
                        lines = lines[1:]
                    out.append(Section(doc, title.strip(), tags, "\n".join(lines).strip()))
            self._sections = tuple(out)
        return self._sections

    def _index(self) -> tuple[list[Counter[str]], dict[str, float], float]:
        if self._idx is None:
            docs = []
            for s in self.sections():
                terms = Counter(words(s.body))
                for w in words(s.title) + [t.lower() for t in s.tags]:
                    terms[w] += 3
                docs.append(terms)
            n = len(docs)
            df: Counter[str] = Counter()
            for d in docs:
                df.update(d.keys())
            idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
            avg = sum(sum(d.values()) for d in docs) / max(n, 1)
            self._idx = (docs, idf, avg)
        return self._idx

    def search(self, query: str, k: int = 3, min_score: float = 2.0) -> list[Section]:
        """The ``k`` best sections for ``query`` (BM25, k1 = 1.4, b = 0.7)."""
        docs, idf, avg = self._index()
        q = words(query)
        scored: list[tuple[float, int]] = []
        for i, d in enumerate(docs):
            length = sum(d.values())
            score = 0.0
            for w in q:
                f = d.get(w, 0)
                if f:
                    score += idf[w] * f * 2.4 / (f + 1.4 * (0.3 + 0.7 * length / avg))
            if score >= min_score:
                scored.append((score, i))
        scored.sort(reverse=True)
        all_sections = self.sections()
        return [all_sections[i] for _, i in scored[:k]]

    def for_prompt(self, query: str, budget_chars: int = 2600, k: int = 4) -> str:
        """Relevant sections as prompt text, within a character budget."""
        out: list[str] = []
        used = 0
        for s in self.search(query, k=k):
            block = f"### {s.title}\n{s.body}"
            if used + len(block) > budget_chars:
                break
            out.append(block)
            used += len(block)
        return "\n\n".join(out)


PLAYBOOK = Pack(DIR)


def sections() -> tuple[Section, ...]:
    return PLAYBOOK.sections()


def search(query: str, k: int = 3, min_score: float = 2.0) -> list[Section]:
    """The ``k`` best sections of Kairos's playbook for ``query``."""
    return PLAYBOOK.search(query, k, min_score)


def for_prompt(query: str, budget_chars: int = 2600) -> str:
    """Relevant playbook sections as prompt text, within a character budget."""
    return PLAYBOOK.for_prompt(query, budget_chars)
