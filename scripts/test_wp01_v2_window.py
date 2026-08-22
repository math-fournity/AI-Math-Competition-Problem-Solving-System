#!/usr/bin/env python3
"""WP-01 独立v2管线跨窗口绝对Round定位测试。"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.v2_pipeline import _next_archived_round


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assert _next_archived_round(root) == 1
        (root / "rounds" / "round1").mkdir(parents=True)
        (root / "rounds" / "round2").mkdir()
        assert _next_archived_round(root) == 3
        (root / "rounds" / "round10").mkdir()
        (root / "rounds" / "round_bad").mkdir()
        assert _next_archived_round(root) == 11
    print("PASS v2 absolute round resumes from archived max+1")


if __name__ == "__main__":
    main()
