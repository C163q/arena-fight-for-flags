# 自主评测

以下命令均在解压后的 `fff-contest/` 运行。先将自己的 release 动态库保存为 `submission/libteam.so`。

## 单场对战

```sh
bin/fff-runner --map maps/arena_2p.ron \
  --ai submission/libteam.so --ai lib/libfff_bot_baseline.so \
  --seed 41 --out runs/my-match
bin/fff-runner verify runs/my-match
```

`--ai` 的顺序对应地图的队伍 ID，数量必须等于地图人数；同一库可以出现多次。输出目录必须不存在。成功时 stdout 是 JSON 摘要，错误写 stderr 并返回非零。

`--seed` 固定引擎随机流；AI 种子来自独立随机源，如需固定，按队伍顺序重复 `--ai-seed N`，每队都提供。固定随机种子不能保证不同策略面对完全相同的后续局面。

## 轮换与重复比赛

`config/tournament.example.json` 为每种人数提供“我的 AI + 基准副本”的名单。配置内路径相对于配置文件目录，使用不同 ID 表示独立队伍。先跑双人快速检查：

```sh
python3 scripts/tournament.py plan --config config/tournament.example.json \
  --out runs/check-new --only 2p --mode quick --repeats 1
python3 scripts/tournament.py run runs/check-new
```

正式评估可以换成 `--mode balanced --repeats 5`，或通过 `--only 3p 8p` 选择名单。不指定 `--only` 会涵盖 2–8 队；默认正式模式 5 个重复块共 990 场，可能消耗较多时间和磁盘。快速模式每块 N 场，只均衡每队出生位；正式模式还均衡任意两队的相对位置，8 队每块 56 场。两者均无法完全消除多人组合效应。

执行与比赛均串行。Ctrl+C 可中断，重新运行同一 `run` 命令续跑；`run ... --max-matches 2` 可分段执行。查看输出目录 `report.md`、`standings.csv` 或 `results.json`。只有完整并通过回放验证的换位块参与排名；基础设施错误会停止执行，AI 超时/崩溃则计入比赛和故障统计。

计划冻结候选库与地图，**修改 AI 后必须创建新的输出目录和计划**，不能用旧计划测试新版本。续跑期间不要移动计划目录或替换裁判/worker。只重建报告：

```sh
python3 scripts/tournament.py report runs/check-new
```

主排名指标为平均归一化名次分（高于对手记 1，同分记 0.5，低于记 0）；同值再比较平均得分和独胜率。不同人数/名单分别排名。报告另含各出生位成绩、非法动作、故障和调用耗时；置信区间只作描述，不代表必然优于所有对手。

原始比赛在 `matches/<场次>/attempt-*/match/`，使用 [回放工具](replay.md) 检查失误。基准只是对照，对手可能强得多，请尝试自己的假设、分析失败并持续改善策略。
