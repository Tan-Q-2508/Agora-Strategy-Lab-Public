"""Regenerate the synthetic test fixtures in tests/fixtures/market/.

Run with:  uv run python scripts/make_fixtures.py
The output is deterministic; tests/unit/test_fixtures.py fails if the committed files
ever differ from what this script produces.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.fakes.synthetic import write_fixtures  # noqa: E402

if __name__ == "__main__":
    out = ROOT / "tests" / "fixtures" / "market"
    paths = write_fixtures(out)
    size = sum(p.stat().st_size for p in paths)
    print(f"Wrote {len(paths)} files ({size / 1024:.0f} KB) to {out}")
