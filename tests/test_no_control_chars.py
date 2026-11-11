"""No source file holds a stray control character (D-194: two regexes had a backspace where a
word boundary was meant, written through a shell that turned "\b" into one)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_backspace_or_bell_characters_in_source() -> None:
    bad = []
    for folder in ("backend", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(ch in text for ch in ("\x08", "\x07", "\x0b", "\x0c")):
                bad.append(str(path.relative_to(ROOT)))
    assert bad == []
