"""sim — 全流程模拟（full-flow simulation）包

设计见 dev-docs/017。核心思想：被测系统（launcher/feeder/门闸/注册表/
Redis队列/判定逻辑）100%原代码真跑，唯一被替换的是devin cli命令——
在tmux里跑的换成src/sim/fake_devin.py（剧本演员），它按剧本写真export/
proof/DONE/HANDOVER再退出。世界的全部输出就是文件+进程行为，所以下游
一切判定逻辑面对的都是真文件真session。

组件：
  scenarios.py    剧本库——每个剧本对应launcher的一条真实分支路径
  fake_devin.py   剧本演员——被launch_solve/start_handover在tmux里启动
  setup.py        造批次——fixture题目+截断态seed export+prepared runs
  run_sim.py      编排——setup→真feeder→真launcher→等窗口收场→断言→清场
  assert_final.py 收场断言——DB状态/窗口历史/rounds_log/flow/016不变量
  teardown.py     清场——tmux/Redis/DB/文件（--keep可保留现场）
"""
