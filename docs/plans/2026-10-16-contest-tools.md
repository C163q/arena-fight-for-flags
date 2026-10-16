# 参赛开发工具实施计划

> **For agentic workers:** 使用 superpowers:executing-plans，在当前会话逐项实施，最后一次全新上下文独立审查。用户已阅设计并要求执行。

**Goal:** 交付预检、默认两场自测、固定对手版本比较、续跑、公开指标摘要和非破坏归档恢复，并装入新题包。
**Architecture:** selftest CLI 组合小模块，复用固定名单赛程和进程执行器。种子与原子发布在存储层提供，实验/预检/摘要/归档各自独立。
**Tech Stack:** Python 3.10+ 标准库、Linux x86_64 release 裁判、现有回放格式。
**Spec:** `docs/design/specs/2026-10-16-contest-tools-design.md`，用户已批准。

## Global Constraints

- 每队首回合 250ms、后续 50ms；不修改 ABI、规则或默认地图。
- run 默认 2p / quick / repeats=1 / jobs=1，恰两场；版本分别对同一对手；正式同场使用 league。
- 引擎 u64 种子列表、AI 与赛程各独立 u256 根种子；固定版本之间逻辑角色和安排一致。
- 所有新输出不存在；原子发布；不覆盖/删除输入；恢复默认 1000000 文件、64GiB，清单最多 256MiB。
- 摘要单 JSON 16MiB、单场 JSON 512MiB、最多 25000 帧；先正式 verify，无未来信息输出。
- 延续千分制显示及精确排序；保留并行来源与旧计划兼容；不重跑正式 1010 场。
- 题包仍为 release 实现二进制、纯 C 头文件与独立参赛说明，不发策略/内部文档/league；只读查询计时器。

## Review Focus

1. 突变的来源文件/并发输出创建：不发布半成品或覆盖数据（任务1/2/5）。
2. 根控制器 SIGKILL 后锁：所有在途 runner/worker 清理，活动内层计划锁覆盖清理期，归档/续跑检查内层锁（任务2/6）。
3. EPERM 与候选 ABI/运行失败：预检分阶段，不更改正常比赛故障统计（任务3）。
4. 同轮死亡掉旗、过量伤害与取消移动：不误记独占击杀/非法，坏记录不算零（任务4）。
5. 归档的路径穿越/重复项/链接/超量/源文件突变：不写出目标新目录外，失败不发布（任务5）。

### Task 1: 可复用种子与原子计划发布

**Files:** 新增 `scripts/tournament_lib/seeds.py`、`tests/test_seed_spec.py`；修改 `storage.py`、`scripts/tournament.py`。
**Interfaces:** `make_seed_spec(maps: list[dict], repeats: int) -> dict`；`validate_seed_spec(spec, groups, repeats) -> dict`；`create_plan(..., seed_spec=None)`；`publish_path(source, target)`；`staged_directory(out)` 上下文。

- [ ] RED：同 map hash/角色复用种子使 matches 的 slots/engine_seed/ai_seeds 完全相同；候选库不同 SHA、旧计划可 load；bool/u64/u256/重复/哈希/长度错误不发布；已存在目标和创建竞态保护。
- [ ] GREEN：严格 JSON v1 种子约束，maps 项 `{sha256, players, engine_seeds}`；可选 CLI `--seed-file`。stage 内构造计划后原子发布，默认随机流不变；显式引擎种子来源写入元数据。
- [ ] 验证：`python3 -m unittest discover -s tests -p 'test_seed_spec.py' -v` 和全 Python 单测；提交。

### Task 2: 自测实验、版本比较与续跑

**Files:** 新增 `scripts/selftest.py`、`scripts/contest_lib/{__init__,common,experiment}.py`、`tests/test_selftest.py`。
**Interfaces:** `prepare_suite(versions, maps, opponent, runner, out, mode='quick', repeats=1, seed_spec=None)`；`resume_suite(root, jobs=1, max_matches=None)`；`load_suite(root)`；`suite_rows(root)`；`resolve_runner(path=None)`、`inspect_map(runner,path)`。

- [ ] RED：默认一候选一地图两场；两版本均对 opponent，四场且对应条件相同；修改源库后续跑仍用快照；坏 ID/输出已存在/地图变化失败；最大场数跨版本计数；并行来源不能清除。
- [ ] GREEN：用正式 inspect-map 校验冻结地图，默认 bin/ 或 target/release/ 的 runner/基准。私有 stage 冻结共享 inputs，再为每版本创建独立 v1 计划，发布前修正来源元数据并重新写计划指纹。实验元数据 `fff-selftest` v1 + SHA sidecar，versions 的 plan 为相对路径；不含动态统计权威缓存。
- [ ] GREEN：run/compare/resume CLI，扩展参数重复 map/opponent/mode/repeats/jobs/seed-file/max-matches；总计划默认最多10000场，显式 match-limit 可提高。外层 `.lock` + 每个 plan `.lock`，复用执行器的在途生命周期；恢复/归档必须检查内层锁，不能只信外层锁。
- [ ] 验证：新单测 + 全套；提交。

### Task 3: 真实控制预检

**Files:** 新增 `scripts/contest_lib/preflight.py`、`tests/test_preflight.py`；扩展 selftest CLI。
**Interfaces:** `check_ai(ai, runner, baseline, map_path, out) -> dict`。

- [ ] RED：控制先失败时不运行候选；normal/permission/load/ABI/crash/timeout 分类与原文保留；游戏非法不等于 ABI 错误；任何输入失败不覆盖旧输出。
- [ ] GREEN：正式 inspect-map 后仅修改私有 map 的 max_turns=2，控制与候选各使用现有 run/collect 的一场真实调用，普通 Python 不加载 .so；JSON/Markdown 诊断各阶段、日志路径、调用状态；退出0/1/2按设计。
- [ ] 验证：单测 + 少量真实 worker 的等待、坏 ABI、崩溃和无限循环 fixture，全部故障保留记录；提交。

### Task 4: 公开事件摘要与磁盘估算

**Files:** 新增 `scripts/contest_lib/summary.py`、`tests/test_contest_summary.py`；扩展 CLI。
**Interfaces:** `summarize_match(path, runner, logdir) -> dict`；`write_summary(source, out, runner=None, estimate_matches=None)`。

- [ ] RED：literal 事件夹具中的 pickup/spawn_pickup/score/death_drop、3发打1HP、友伤、争格/占格/死亡取消/非法分别计算；非法/缺帧/越限/坏 summary 拒绝；代表事件有界；不输出 RNG/刷新数据。
- [ ] GREEN：安全有界读取、正式 verify、按帧流式统计；实验按候选角色汇总同地图指标，调用数和比率分母明确，千分制来自完整块旧报告；未完整块只能显示行为统计。日志与 JSON/Markdown 写在新输出目录，来源记录不变。
- [ ] GREEN：总字节/场均/轮均及同图粗估，样本不足标记；不承诺上界或跨图一致。
- [ ] 验证：单测 + 既有代表回放；提交。

### Task 5: 非破坏归档与验证恢复

**Files:** 新增 `scripts/contest_lib/archive.py`、`tests/test_contest_archive.py`；扩展 CLI。
**Interfaces:** `archive_records(source, out, runner=None, max_files=1000000, max_bytes=68719476736)`；`restore_archive(source, out, runner=None, max_files=1000000, max_bytes=68719476736)`。

- [ ] RED：单场/完整实验 round-trip 字节相同且可 verify；完整清单覆盖每个有效载荷；目标已存在不变；in_progress/未完实验/锁定拒绝；源突变拒绝；穿越/绝对路径/重复/符号与硬链接/特殊文件/漏项/错哈希/超额拒绝且不写出新目标目录。
- [ ] GREEN：`fff-replay-archive` v1，清单含规范相对路径、size/SHA/mode、比赛列表；清单≤256MiB。仅明确比赛文件和实验元数据/冻结输入白名单，排除锁/缓存/源码/临时文件；源变化检测；原子发布文件。
- [ ] GREEN：手动安全提取到 private stage，不用不受控 extractall；输入配额先检查后写入，逐文件校验；逐场 verify 后发布新目录。仅离线备份，不改历史绝对路径以伪造可迁移续跑。
- [ ] 验证：单测 + 真实回放归档/恢复与重验；提交。

### Task 6: 验收、参赛题包与交付

**Files:** `tests/selftest_integration.py`、`tests/selftest_parent_cleanup.py`；包生成器白名单、题包单测/外部验收、模板、新指南、AGENTS、导航、决策、实测与审查记录。

- [ ] 实战验收：默认两场、两版共同条件、freeze/resume、权限和 ABI 故障、摘要与 archive/restore；父进程 SIGKILL、jobs=2 全在途清理，任何内层活动锁禁止归档/重跑。
- [ ] 保持旧 tournament/league Python 与既有接口；存储改动用原 tournament 实战与父进程清理验收。执行器若需要改动，额外按 AGENTS 运行对应实战检查。
- [ ] 同步独立参赛文档及实际白名单；新工具明示 self-test，保留60/70分钟、千分制、串行正式要求；不发送优秀策略源码。
- [ ] 全Python/viewer单测、适用Rust检查、新 release 题包仓库外验收；一次独立审查；修复 Important/Critical 后集成本地 main。原始1010场不重跑，地图不修改。
- [ ] 更新准备清单的实际状态，记录剩余限制和验收路径；自行本地提交，不推送，清理本次工作区。
