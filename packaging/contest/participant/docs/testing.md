# 自主评测

以下命令均在解压后的 `fff-contest/` 运行。先将自己的 release 动态库保存为 `submission/libteam.so`。

## 先预检，再做两场自测

```sh
python3 scripts/selftest.py check --out runs/preflight
python3 scripts/selftest.py run --out runs/quick
```

默认从 `submission/libteam.so` 加载候选。预检先以基准检查环境，再以候选运行私有两回合真实 worker；查看 `diagnostics.json` 和 `report.md`。成功返回0、诊断失败返回1、输入错误返回2；权限问题交场外人员处理。预检不是强度成绩，也不保证其他局面不会超时。正常比赛的 AI 故障仍按规则计入。

`run` 默认双人、基准对手、quick、一块、串行，**仅两场，交换出生位**。开始前打印总场数。可重复 `--map maps/arena_3p.ron` 等选择地图，用 `--opponent FILE` 更换固定对手、`--repeats N` 增加样本、`--mode balanced` 增加轮换；多人图其余位置都是固定对手的独立副本。默认总场数上限10000，可显式提高 `--match-limit`。

## 比较自己的版本

```sh
python3 scripts/selftest.py compare \
  --ai old=submission/libold.so --ai new=submission/libnew.so \
  --opponent submission/libopponent.so --out runs/compare
python3 scripts/selftest.py resume runs/compare --max-matches 2
```

两版分别面对固定对手，彼此不同场，默认共四场。对应比赛共享地图、种子、逻辑角色和出生位；不同策略会产生不同后续局面。`--seed-file runs/compare/seeds.json` 可在新实验复用条件，要求地图字节、ID、人数和重复数一致。

创建时冻结所有库与地图，**改代码后新建实验**，续跑只使用旧快照。Ctrl+C 保留现场，`resume` 校验已完成回放后继续；`--max-matches N` 限制本次新增场数（跨版本合计）。不要移动活动实验或替换裁判/worker。输出 `report.md`、`results.json` 仅是开发自测；只有完整换位块有积分。保留不同风格的历史版本作为对手，避免只针对基准优化。

`--jobs N` 默认1，可先尝试2；竞争资源可能增加超时并改变结果，串行续跑仍保留并行标记。**正式评测固定1**。新输出必须不存在。每版内层计划也可用下面旧测评器查看。

## 指标、空间与备份

```sh
python3 scripts/selftest.py summary runs/compare --out runs/analysis
python3 scripts/selftest.py archive runs/compare --out runs/compare.tar.gz
python3 scripts/selftest.py restore runs/compare.tar.gz --out runs/restored
```

摘要先经裁判验证，按候选角色汇总各图拾旗、交旗、携旗阵亡、射击结果、友伤、实际扣血、移动结果和调用时间；坏记录会失败。名义射击伤害包含过量集火，实际扣血单列，不声称独占击杀。命中率以合法射击为分母，移动成功率以移动事件为分母。代表事件数量有界，可回原始记录定位；不完整块可以看行为，但不排名。

支持单场完整回放或自测实验；单图可加 `--estimate-matches N` 估计扩展规模。实际字节和同图样本估算列在摘要中，无样本不估计，少于两场标记不足；不是空间上界。默认两场也应结合本机实际耗时、磁盘安排后续测试。

归档只接受完整、无活动进程的记录，保留原始输入；恢复逐文件校验并逐场通过裁判后写入新目录，不覆盖已有文件。默认最多1000000文件、64GiB解压数据，使用 `--max-files`、`--max-bytes` 调整；拒绝链接、穿越、重复项、错误哈希和超量输入。仅离线备份，**不能迁移续跑**，不重写历史工具路径；工具不自动删除任何原始记录。恢复后可导出其中单场的回放。摘要输入最多25000帧、单JSON16MiB、单场JSON512MiB。

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

扩大自测可换成 `--mode balanced --repeats 5`，或通过 `--only 3p 8p` 选择名单。不指定 `--only` 会涵盖 2–8 队；**balanced 即使 `--repeats 1` 也有 198 场**，默认 5 个重复块共 **990 场**，可能消耗数小时和大量磁盘。先跑上面的 2 场，按本机耗时估算；全人数 quick 一块也有 35 场。不要在 60 分钟开发时限内贸然启动完整赛程，经常查询 `bin/fff-timer-query` 并保留可提交库。快速模式每块 N 场，只均衡每队出生位；正式模式还均衡任意两队的相对位置，8 队每块 56 场。两者均无法完全消除多人组合效应。

单场各队调用始终串行；跨场默认串行，可指定并发上限：

```sh
python3 scripts/tournament.py run runs/check-new --jobs 2
# 正式评测由场外人员运行，固定并发为 1。
python3 scripts/tournament.py run runs/formal-new --jobs 1
```

`--jobs N` 接受正整数，默认 **1**，表示至多 N 场（含回放校验）同时运行。并行争抢 CPU、内存与磁盘，墙钟决策预算不变，可能增加 AI 超时、改变行为和排名；不保证线性加速，也不会减少总回放空间。建议先从 `--jobs 2` 开始，可尝试不超过可用 CPU 核数一半的并发，并根据超时情况调整；已有其他任务或 AI 接近决策时限时，应降低并发。**正式评测使用 `--jobs 1`**；并行自测供快速筛选，最终在低负载串行环境检查超时和性能。报告会记录每场并发设置，并将含并行场次的结果标记为自测；改为串行续跑不会清除标记，正式对比须另建计划。

Ctrl+C 会终止所有在途比赛并保留记录，重新运行同一 `run` 命令可续跑；`run ... --max-matches 2` 可分段执行。查看输出目录 `report.md`、`standings.csv` 或 `results.json`。只有完整并通过回放验证的换位块参与排名；基础设施错误会停止执行，AI 超时/崩溃则计入比赛和故障统计。

计划冻结候选库与地图，**修改 AI 后必须创建新的输出目录和计划**，不能用旧计划测试新版本。续跑期间不要移动计划目录或替换裁判/worker。只重建报告：

```sh
python3 scripts/tournament.py report runs/check-new
```

主排名指标为平均归一化名次分（高于对手记 1，同分记 0.5，低于记 0）。报告采用千分制：名次分乘 1000 后四舍五入到整数，满分 1000，置信区间也采用千分制。排名仍按未取整值，同值再比较平均夺旗分和独胜率；显示整数相同不一定并列。平均夺旗分不缩放。JSON/CSV 的 `score` 是千分制积分，原有 `rank_score` 保留 0–1。不同人数/名单分别排名。报告另含各出生位成绩、非法动作、故障和调用耗时；置信区间只作描述，不代表必然优于所有对手。

原始比赛在 `matches/<场次>/attempt-*/match/`，使用 [回放工具](replay.md) 检查失误。基准只是对照，对手可能强得多，请尝试自己的假设、分析失败并持续改善策略。
