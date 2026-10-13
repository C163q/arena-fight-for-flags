# Fight for Flags

Rust 回合制夺旗 AI 竞技场。每队三个棋子，AI 通过 C ABI 一次提交全队动作，每队每回合有 50ms 墙钟预算。各队串行决策、共享同一回合开始快照，裁判随后统一射击、移动、拾旗/生成和得分。

首版已提供 Linux 64 位裁判、独立 AI worker、三种参考 AI、2–8 队 RON 地图、逐轮 JSON/ASCII 记录、规则重放验证器和可离线打开的 HTML 播放器。

## 构建和比赛

需要 Rust 2024 工具链、Linux 64 位环境；导出播放器需要 Python 3.10+。运行测试还需要 C 编译器；浏览器检查额外使用 Playwright 与 Chromium。普通比赛和观看回放不依赖浏览器自动化包。

```sh
cargo build --release --workspace

target/release/fff-runner \
  --map maps/arena_2p.ron \
  --ai target/release/libfff_bot_baseline.so \
  --ai target/release/libfff_bot_greedy.so \
  --seed 41 \
  --out runs/my-match

target/release/fff-runner verify runs/my-match
python3 viewer/export.py runs/my-match
```

默认生成 `runs/my-match/replay.html` 和 `replay.json`。用浏览器打开 [通用播放器](viewer/index.html)，将 `replay.json` 拖入或点击“打开回放”；同一个页面可以反复查看不同比赛。也可以直接打开自包含的 `replay.html`，便于分享。两种方式都不需网络或服务器，已有比赛重新导出即可。

播放器支持播放/暂停、速度、前后单步、指定回合、START/END、射击路径和携旗标记。受伤棋子头顶显示三格血条，满血隐藏；点击棋子查看状态。棋盘支持滚轮/按钮缩放、拖拽平移、适配和全屏；比分紧凑显示，事件/棋子/AI 明细在侧栏标签中独立滚动。仅需数据文件时运行 `python3 viewer/export.py runs/my-match --format json`。

`--ai` 按队伍 ID 顺序重复提供，数量必须与地图的 `players` 一致；同一个库可以用于多支队伍。`--out` 必须不存在，避免覆盖比赛。裁判最终在 stdout 输出一行 JSON 摘要，错误写 stderr 并返回非零退出码。

`--seed` 只固定引擎随机流。默认各队 AI 种子来自独立 OS 随机源并写入 manifest；需要重现随机策略时，按队伍顺序重复传 `--ai-seed N`（全部队伍都提供）。AI 种子不从引擎种子派生。

目标分与最大回合数由 RON 的 `match_limits` 决定，CLI 不覆盖。旗帜等待范围可通过 `--flag-min-turns`、`--flag-max-turns` 调整，默认 5–15（两端包含、整数均匀随机），实际配置完整记录。

## 编写 AI

公开 Rust 类型在 `crates/ai-abi/`，C 头文件在 [include/ctf_ai.h](include/ctf_ai.h)。导出四个函数：`ctf_abi_version`、`ctf_create`、`ctf_decide`、`ctf_destroy`。参考 [等待 AI](bots/wait/src/lib.rs)、[贪心 AI](bots/greedy/src/lib.rs) 和 [基准 AI SDK](crates/ai-sdk/src/lib.rs)。

Rust AI 使用 `cdylib`，依赖 `fff-ai-abi`，可以用 `export_ai!(strategy)` 包装无状态策略。需要跨轮记忆的 AI 自行实现生命周期和私有 context。库只借用当前调用的输入/输出缓冲区，不保留其指针。

```sh
cargo build --release -p fff-bot-baseline
```

AI 可见全图、所有棋子位置/血量/携旗、当前旗帜、比分和复活信息；看不到其他队伍本轮动作、未来具体刷新时刻和引擎 RNG。50ms 包含恢复、IPC 和完整响应校验，排队不计时，初始化另有限额。超时终止该进程组，本轮整队等待，下一轮重启并丢失 context。

## 规则与地图

棋子 3 血，不自动回血，命中减 1。射程是曼哈顿距离 ≤5，弹道是直线，只有指定格受伤；途中棋子不伤、不挡弹，障碍边角接触也挡弹。存在友伤，射击自身格非法。

携旗不能射击或移入地上旗格，回到己方 3×3 出生区得分。死亡原格掉旗，完整缺席随后十轮，t+11 开始复活。到期生成发生在移动后：未携旗者占格即时携旗，已携旗者占格失败并重新等待。旗只在交回得分时消失，来源旗点随后等待重刷。

七张地图外圈全封墙，运行时 RON 加载并校验可达性。默认终局如下：

| 地图人数 | 尺寸 | 目标分 | 最大回合 |
| --- | --- | --- | --- |
| 2 | 25×25 | 20 | 400 |
| 3 | 29×29 | 20 | 500 |
| 4 | 31×31 | 20 | 600 |
| 5 | 33×33 | 20 | 700 |
| 6 | 35×35 | 20 | 800 |
| 7 | 37×37 | 20 | 900 |
| 8 | 41×41 | 20 | 1000 |

地图已调整为菱形出生环与稀疏障碍，所有出生位到最近旗点等距；仍有实战位置偏好，比较 AI 时轮换位置并跑多个种子。详见 [地图标定报告](docs/map-balance-2026-10-13.md) 和 [地图概览](docs/assets/maps-v2.svg)。独立进程提供超时/崩溃隔离，不是执行恶意本地库的完整安全沙箱。

## 自动测评

为每种人数指定一组 AI，测评机自动安排位置均衡、多种子对抗，串行执行并验证每场回放，支持中断续跑，输出 Markdown/CSV/JSON 报告。正式 8 人赛程每种子 56 场，均衡每个 AI 的出生位及任意两个 AI 的相对位置；快速模式每种子 8 场。

```sh
# 编辑示例中的 AI 库和各人数名单；plan 不启动 AI。
python3 scripts/tournament.py plan --config config/tournament.example.json --out runs/tournament-new
python3 scripts/tournament.py run runs/tournament-new
```

示例覆盖 2–8 人、每种人数 5 个种子，共 990 场；可用 `--mode quick --repeats 1` 先跑 35 场，或 `--only 8p` 只选择 8 人名单。查看输出目录 `report.md`；排名只使用完整换位组，不合并不同人数/名单。详见 [测评机说明](docs/tournament.md)。

## 文档与检查

| 文档 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 编码代理协作约定 |
| [规则](docs/rules.md) | 权威玩法与阶段顺序 |
| [地图](docs/maps.md) | RON schema、七图与校验 |
| [架构](docs/architecture.md) | 模块与进程生命周期 |
| [API](docs/api.md) | 已实现 C ABI v1 的字段与所有权 |
| [回放](docs/replay.md) | 实际文件格式和重放/导出约定 |
| [基准 AI](docs/benchmark-ai.md) | 策略、评测方法与限制 |
| [自动测评机](docs/tournament.md) | 固定名单、均衡赛程、续跑与统计 |
| [决策](docs/decisions.md) | 已接受设计与用户确认记录 |
| [路线图](docs/roadmap.md) | 首版交付与后续工作 |

```sh
cargo fmt --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
python3 -m unittest discover -s viewer -p 'test_*.py' -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/generate_maps.py --check
python3 tests/integration.py --out runs/smoke-new
python3 tests/browser.py runs/smoke-new/2p/replay.html
python3 tests/viewer_usability.py runs/smoke-new/8p/replay.html runs/smoke-new/8p/replay.json
python3 tests/parent_cleanup.py
python3 scripts/evaluate.py --out runs/evaluation-new --report docs/evaluation-new.md
```

进程测试必须允许创建独立进程组、发送停止/恢复/终止信号；受限沙箱可能拒绝这些操作。Python 导出器验证结构，完整规则与 ASCII 一致性通过 `fff-runner verify` 检查；可读取未完成比赛的完整前缀。导出器当前最多 25000 帧、总输入 512MiB。
