"""scenarios.py — 全流程模拟的剧本库

每个剧本（scenario）描述一组题的模拟行为，对应launcher的一条真实分支
路径。剧本在setup时写入每个work_dir的sim_scenario.json，fake_devin读它
决定自己的动作。

剧本结构（写入sim_scenario.json的内容）：
  {
    "name": "solve3",
    "solve":    {"2": "truncate", "3": "complete"},   # round → 动作，"*"=默认
    "handover": "ok"                                    # ok | timeout
  }

solve动作（fake_devin按round查表执行）：
  truncate  写截断态export（rc>1000/msg=0/tc=0/comp≥24000）→ exit 0
  complete  写完成态export（msg>0）+ proof.md（含\\boxed）→ exit 0
  dead      什么都不写 → exit 1（DONE.md记录退出码1，无proof→dead_session判定）
  stall     打印一行后sleep不退出（无DONE.md→pane静止→stall检测）

round编号约定：R1是seed（原始失败尝试，launcher取件时做precheck并补录
rounds_log条目，不启动session）；R2起才是fake_devin出演的续传轮。

已修复的缺陷（017首日实证，详见dev-docs/017 §5）：
  - 截断路径曾不可达（dead分支抢占is_truncated）——修复后截断判定先于dead
  - rounds_log曾因round-1不补录导致R2重跑（实证[2,2,3]）——修复后轮序[1,2,3]
"""

SCENARIOS = {
    # 主干多轮续传：seed截断→R2截断→（预期R3，实际可能重跑R2）→完成
    "solve3": {
        "description": "三次才解出来——多轮续传主干全链",
        "runs": 1,
        "solve": {"2": "truncate", "3": "complete"},
        "handover": "ok",
        "max_rounds": 5,
        "expect_final": "COMPLETED",
    },
    # 第一次续传就解出：R2直接完成
    "first_try": {
        "description": "一次续传即完成——单轮完成+kill_session(completed)",
        "runs": 1,
        "solve": {"2": "complete"},
        "handover": "ok",
        "max_rounds": 5,
        "expect_final": "COMPLETED",
    },
    # 永远截断：走到TRUNCATED_AT_MAX
    "never": {
        "description": "永远截断——TRUNCATED_AT_MAX分支",
        "runs": 1,
        "solve": {"*": "truncate"},
        "handover": "ok",
        "max_rounds": 3,
        "expect_final": "TRUNCATED_AT_MAX",
    },
    # devin退出但无proof无有效export：dead_session判定+清理
    "dead": {
        "description": "session死亡——dead_session判定+清理（铁律例外分支）",
        "runs": 1,
        "solve": {"2": "dead"},
        "handover": "ok",
        "max_rounds": 5,
        "expect_final": None,  # dead_session不是final_status，查status字段
        "expect_status": "dead_session",
    },
    # pane静止不产出：stall检测
    "stall": {
        "description": "光思考不产出——stall检测分支（需--stall-seconds调小）",
        "runs": 1,
        "solve": {"2": "stall"},
        "handover": "ok",
        "max_rounds": 5,
        "expect_final": None,
        "expect_status": "failed_stall",
        "stall_seconds": 20,
    },
    # Pipe A超时：check_handover超时kill→v1回退→R3(v1路径)完成
    "h_timeout": {
        "description": "HANDOVER生成超时——超时kill+v1回退分支",
        "runs": 1,
        "solve": {"2": "truncate", "3": "complete"},
        "handover": "timeout",
        "max_rounds": 5,
        "expect_final": "COMPLETED",
        "handover_timeout_seconds": 15,
    },
    # 016动力学回归：多题并发全部永远截断，断言防抖/NX/单session不变量
    "chaos_016": {
        "description": "016失控循环回归——多题并发截断循环，断言三道P0闸",
        "runs": 4,
        "solve": {"*": "truncate"},
        "handover": "ok",
        "max_rounds": 3,
        "expect_final": "TRUNCATED_AT_MAX",
    },
}


def get(name):
    if name not in SCENARIOS:
        raise SystemExit(f"未知剧本: {name}（可用: {', '.join(SCENARIOS)}）")
    return SCENARIOS[name]


def scenario_file_content(name):
    """生成写入work_dir/sim_scenario.json的内容"""
    sc = get(name)
    return {
        "name": name,
        "solve": sc["solve"],
        "handover": sc["handover"],
    }
