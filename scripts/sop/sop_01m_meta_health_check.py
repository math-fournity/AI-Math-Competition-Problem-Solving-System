"""sop_01m_meta_health_check.py — 元检查：SOP_01健康检查的合理性

检查 sop_01_health_check 的 SOP 文档和脚本本身是否还合理。
不是重做健康检查，而是反思健康检查这一步的设计是否需要调整。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_meta_base import run_meta_check

if __name__ == "__main__":
    run_meta_check("01m")
