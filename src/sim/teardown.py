"""teardown.py — sim清场

清理一个sim批次的全部痕迹：
  1. tmux：杀掉所有含batch_id的session（名字由run_key派生，天然含batch_id）
  2. Redis：删除P27_REDIS_PREFIX前缀下的全部键（sim前缀独立，不影响生产）
  3. DB：默认保留（post-mortem用），--purge-db时删除sim库
  4. 文件：默认保留work_dir/trajectory（post-mortem用），--purge-files时删除

安全护栏与setup相同：非隔离环境拒绝执行。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PROD_DB = "xishujuzhen_math_glm52"


def guard_sim_env():
    problems = []
    if os.environ.get("ARANGO_DB", PROD_DB) == PROD_DB:
        problems.append(f"ARANGO_DB == 生产库({PROD_DB})")
    prefix = os.environ.get("P27_REDIS_PREFIX", "p27:")
    if prefix == "p27:":
        problems.append("P27_REDIS_PREFIX是生产前缀(p27:)")
    # ⚠️ 2026-08-20事故教训：漏检文件根导致rmtree误删生产p27-continuation
    # 目录。文件根必须与setup相同的三重检查——SOLVER_BASE/TRAJECTORY_BASE
    # 任一指向/Volumes/data即拒绝。
    for var in ("SOLVER_BASE", "TRAJECTORY_BASE"):
        if os.environ.get(var, "/Volumes/data/").startswith("/Volumes/data"):
            problems.append(f"{var}指向生产文件根(/Volumes/data)或未设置")
    if problems:
        raise SystemExit("❌ 拒绝非隔离环境清场：\n  - " + "\n  - ".join(problems))


def teardown(batch_id, purge_db=False, purge_files=False):
    guard_sim_env()

    # 1. tmux——杀sim session。匹配规则：所有sim题目id强制sim_前缀（setup约定），
    # session名尾部含完整pid（pid<40字符不被截断），所以"sim_"in名字即sim session。
    # （017首日教训：用batch_id子串匹配会因run_key[-40:]截断而失配漏杀——
    # stall剧本的两个fake sleep session就是这样残留的。）
    try:
        out = subprocess.run(["tmux", "ls"], capture_output=True, text=True, timeout=5)
        killed = 0
        for line in out.stdout.splitlines():
            name = line.split(":")[0]
            if "sim_" in name:
                subprocess.run(["tmux", "kill-session", "-t", name],
                               capture_output=True, timeout=5)
                killed += 1
        print(f"  [teardown] tmux清理: 杀{killed}个sim session")
    except Exception as e:
        print(f"  [teardown] tmux清理跳过: {e}")

    # 2. Redis——删sim前缀全部键
    from src.continuation_redis_queue import get_redis
    r = get_redis()
    prefix = os.environ.get("P27_REDIS_PREFIX", "p27:")
    deleted = 0
    for key in r.scan_iter(match=prefix + "*", count=100):
        r.delete(key)
        deleted += 1
    print(f"  [teardown] Redis清理: 删{deleted}个键（前缀{prefix}）")

    # 3. DB——默认保留现场
    if purge_db:
        import arango
        from src.continuation_config import (
            ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD)
        client = arango.ArangoClient(hosts=ARANGO_HOST)
        sysdb = client.db("_system", username=ARANGO_USER, password=ARANGO_PASSWORD)
        if sysdb.has_database(ARANGO_DB):
            sysdb.delete_database(ARANGO_DB)
            print(f"  [teardown] DB已删除: {ARANGO_DB}")
        client.close()
    else:
        print(f"  [teardown] DB保留（post-mortem用，--purge-db可删）")

    # 4. 文件——默认保留现场
    if purge_files:
        from src.continuation_config import (
            CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE)
        for base in (CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE):
            if base.exists():
                shutil.rmtree(base, ignore_errors=True)
                print(f"  [teardown] 文件已删除: {base}")
    else:
        print(f"  [teardown] 文件保留（post-mortem用，--purge-files可删）")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="sim清场（一般经run_sim调用）")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--purge-db", action="store_true")
    ap.add_argument("--purge-files", action="store_true")
    args = ap.parse_args()
    teardown(args.batch_id, args.purge_db, args.purge_files)
