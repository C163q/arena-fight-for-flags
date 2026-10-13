# 自动测评机 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 提供 2–8 队固定名单的均衡赛程、串行执行、可靠续跑和逐名单统计。

**Architecture:** Python 标准库工具通过现有 runner 执行比赛；赛程、文件与进程管理、统计分别放入小模块。计划阶段冻结输入；执行与报告阶段验证原始比赛，不依赖可修改的统计缓存。

**Tech Stack:** Python 3.10+、现有 Rust release runner/worker、JSON/CSV/Markdown。

**Spec:** `docs/superpowers/specs/2026-10-13-tournament-design.md`。用户已确认按人数指定名单及推荐方案，延续本会话逐项实现方式。

## Global Constraints

- 不改变规则、C ABI、地图与 50ms 时限；比赛串行。
- 正式每块 2/6/12/20/60/42/56 场；快速每块 N 场；默认 5 块。
- AI 种子独立于引擎种子，随参赛 ID 移动；统计只采用完整块。
- 保存原始比赛，执行与续跑都校验实际输入和回放；基础设施错误不判选手负。
- 同库不同 ID 不合并；分人数、地图、名单报告，不自动枚举参赛子集。

## Review Focus

- 崩溃在 runner 完成与检查点写入之间：识别并验证已有完整比赛，不重打一遍。
- 中断半场与损坏完整比赛：前者保留并重试，后者停止且不静默掩盖。
- 统计缓存或计划被修改：通过输入/计划指纹与原始记录校验，不信任旧排名。
- 多进程同时操作输出：文件锁覆盖执行和报告，避免同场重复执行或报告读到部分结果。
- 含特殊字符的显示名与路径：无 shell 拼接，Markdown/CSV 正确转义；配置 ID 限定安全字符。

### Task 1: 赛程、配置与输入冻结

**Files:** `scripts/tournament_lib/schedule.py`、`storage.py`、`__init__.py`；`tests/test_tournament.py`。

**Interfaces:** `permutations_for(n, mode) -> list[tuple[int,...]]` 返回 AI 索引到出生位的置换；`create_plan(config_path, out, mode=None, repeats=None, only=None) -> dict` 保存含 groups/blocks/matches 的版本化计划；`load_plan(root) -> dict` 校验冻结输入和计划 SHA。

- [x] 写测试：七种人数置换合法、单位置与两两位置完全均衡，6 队 60 场；快速模式位置均衡；配置拒绝重复 ID/名单/越界；AI seed 随 ID 轮换；输入变化拒绝加载。
- [x] 运行 `python3 -m unittest discover -s tests -p 'test_tournament.py' -v`，预期新增接口缺失失败。
- [x] 实现有限域/射影置换、独立种子来源、配置解析、原子 JSON、输入拷贝、文件锁与计划 SHA。
- [x] 同一命令预期全部通过；提交任务代码及测试。

### Task 2: 真实执行与恢复

**Files:** `scripts/tournament_lib/execution.py`；扩展同一测试文件。

**Interfaces:** `run(root, max_matches=None) -> dict` 按固定赛程执行，`collect(root, plan) -> list[dict]` 重新检查完整比赛并归属到计划场次；比赛行含 match_id/group/block/slots/summary/call_stats/directory。

- [x] 写测试：用可执行测试裁判模拟真实文件及故障，覆盖半场重试、完整场恢复、输入/manifest/种子/结果拒绝、并发锁、runner 故障停止与退出状态。
- [x] 同一 unittest 命令预期新增接口缺失失败。
- [x] 实现日志、attempt 状态、顺序 runner/verify 调用、恢复扫描、原子检查点、SIGINT/SIGTERM 子进程退出。基础设施故障保留错误并停止。
- [x] 同一命令预期通过；提交。

### Task 3: 统计、报告与 CLI

**Files:** `scripts/tournament_lib/reporting.py`、`scripts/tournament.py`、`config/tournament.example.json`；扩展测试。

**Interfaces:** `build_results(plan, rows) -> dict` 按完整块计算名次分/平分/位置/两两/块 bootstrap；`write_reports(root, plan, rows) -> dict` 原子输出 JSON/CSV/Markdown。CLI 提供 plan/run/report；run 的 `--max-matches` 只用于有意分段执行，部分块不排名。

- [x] 写手工结果测试：全平、并列第一、名次及分差、故障归属、同库副本、少于五块不显示区间、不完整块排除、稳定并列排序、CSV/Markdown 转义。
- [x] 同一 unittest 命令预期新增统计接口缺失失败。
- [x] 实现统计和 CLI；完整重复块作为 bootstrap 单位，固定统计 RNG，2000 次。
- [x] 同一命令预期通过；验证 CLI help 和示例 plan，总场数 990；提交。

### Task 4: 实战验收、文档与最终审查

**Files:** `tests/tournament_integration.py`、`docs/tournament.md`、README、benchmark/architecture/AGENTS 相关说明；计划与设计状态。

- [x] 先写实战验收脚本：2–8 队快速 35 场与 8 队正式 56 场；恢复不增打、完整块才排名、损坏/不匹配拒绝、半场重试保留原目录。
- [x] 通过正式 release runner 执行验收，预期 91 场通过逐场 verify，报告记实际耗时、存储量；不将这次功能验收称为策略强度定论。
- [x] 运行全部 Python 单测、Rust workspace 测试、fmt/clippy；预期全通过。
- [x] 更新用法、真实结果与限制，提交。

## 完成流程

- [x] 按 executing-plans 做一次新功能独立审查，重要发现一次修复并补回归测试。
- [x] 合并 main，合并后相关验证，正常清理本次工作区。

## 实施证据

91 场真实验收通过，数据见 `runs/tournament-v1/acceptance/acceptance.json`：35 场快速轮换、56 场八人正式赛程，622.97 秒、1,422,664,611 字节，无 AI 故障和非法动作。另用基准对贪心跑了 5 个完整双人块共 10 场，验证不同库、排名和按块区间，输出在 `runs/tournament-v1/demo/`；仅描述这个样本，不作普遍胜率承诺。

Python 19 个工具测试及 8 个回放测试通过。Rust 全套首次在受限沙箱被 Unix socket 权限拒绝，升级到具备进程/通信权限的环境验证；fmt/clippy 均通过。

独立审查及修复见 [审查记录](../../tournament-review-2026-10-13.md)。修复后 Python 测试为 21+8，Rust 42；额外真实 SIGKILL 恢复对局 2 场，既有 101 场全部重新 verify。

交付：实现与审查修复已合并 main（`8c2e948`），合并后 42 个 Rust 测试、29 个 Python 测试及 fmt/clippy 通过；默认配置从主目录生成 990 场计划成功。main 上额外执行真实 SIGKILL 清理/续跑 2 场并全部 verify，总完成对局 105 场。本次功能工作区与分支已正常清理，所有对局留在根目录 `runs/tournament-v1/`。
