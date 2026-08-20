"""sop_05m_meta_report_worklog.py — 元检查：SOP_05 报告+WORKLOG的合理性"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_meta_base import run_meta_check

if __name__ == "__main__":
    run_meta_check("05m")
