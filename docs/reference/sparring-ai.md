# 陪练 AI

`fff-bot-sparring` 是独立的强化陪练 AI，用于给新策略提供更有压力的对手。它与普通参赛库使用相同的 C ABI、观测和计算时间限制。现有基准保持原样；陪练也不会自动加入参赛题包。

## 构建与使用

在仓库根目录运行：

```sh
cargo build --release --workspace
```

陪练库为 `target/release/libfff_bot_sparring.so`。将它作为自测对手：

```sh
python3 scripts/selftest.py run --ai submission/libteam.so \
  --opponent target/release/libfff_bot_sparring.so \
  --out runs/against-sparring
```

默认双人地图、交换出生位，共两场。测试自己的新版本需要使用新的输出目录。扩大到多人地图时，可重复提供 `--map`；其他位置由陪练的独立副本填充，各副本之间不共享记忆。

也可直接对战：

```sh
target/release/fff-runner --map maps/arena_2p.ron \
  --ai submission/libteam.so \
  --ai target/release/libfff_bot_sparring.so \
  --out runs/sparring-match
target/release/fff-runner verify runs/sparring-match
python3 viewer/export.py runs/sparring-match
```

在 league 配置中，将同一路径填入候选的 `library` 可比较它的名次；填入 `filler.library` 则将它作为补位队，不参与候选排名。正式评测仍使用 `--jobs 1`。

## 策略与边界

策略源码在 `bots/sparring/`，生产依赖只有 `fff-ai-abi`。测试额外使用引擎交叉检查几何和移动结果，不把引擎或其私有状态链接进陪练库。

- 地图缓存：正交最短路、出生区距离和射击视线。射线擦障碍边角也视为遮挡；途中棋子不遮挡。距离和射线均按需计算，缓存最多 96 个目标的距离表，避免为最大地图分配平方规模矩阵。临时预测坐标没有缓存时使用曼哈顿距离作为估计。
- 任务分配：三个棋子一起选择取旗或等待目标，考虑到达、返程、其他队伍争抢与重复分工。根据已公开的旗帜出现、携带、消失情况估计旗点等待，读取本场公开的等待范围，不读取实际未来生成时间。
- 联合动作：枚举等待、正交移动和可命中敌人的射击组合，减少过量集火与队内争格；携旗者不能射击，返程使用带风险代价的路径。
- 短期预测：预测其他队伍的射击与移动，模拟同时伤害、掉旗、移动冲突、拾旗和交旗，对一部分较好的动作组合继续预测。射击者即使本轮被击杀，其合法射击仍参与结算。生成旗帜和复活不在短期预测中模拟，下一轮以新观测修正。
- 合法性保护：携旗路径避开当前地上旗，以及其他携旗棋子可能被致命射击后掉旗的格子，避免把对敌方射击目标的猜测当作保证。

地图和任务历史保存在 AI context 内；超时重启后可以从当前观测重新工作。策略不访问比赛文件、其他进程、引擎随机状态或其他队伍的本轮动作，不运行后台计算。它采用确定性的破平顺序，没有在线训练阶段。

这是一种有界启发式搜索。敌方实际选择可能不同于预测；任务分配、较深的交战、守点与地图结构仍可能被专门策略利用。“强化陪练”不代表已证明优于所有参赛 AI。具体样本和计时见 [实测报告](../reports/sparring-ai-2026-10-19.md)。建议保留基准和风格不同的历史对手共同测试。

## 维护检查

除 workspace 测试外，可检查最大地图和常规回合故障恢复：

```sh
python3 tests/sparring_integration.py --out runs/sparring-check
```

该检查需要 C 编译器和正常的 worker 进程通信。测试转发库只在测试自己创建的 worker 中故意退出，随后检查新 worker 是否在 50ms 限制内完成冷启动；原始错误和验证结果保存在输出目录。可用 `--bin-dir` 指定已有 release 程序目录，`--library` 指定陪练库。繁忙机器可能出现额外超时，应保留日志检查负载。
