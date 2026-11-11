"""Run a research batch at low priority, so the laptop stays cool and Agora stays quick (D-164).

python scripts/research/run_low.py FILE --note "why"
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BELOW_NORMAL = 0x4000
IDLE = 0x40


def main() -> int:
    if sys.platform == "win32":
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL)
    from backend.metis.claude import main as run

    return run(["run", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
