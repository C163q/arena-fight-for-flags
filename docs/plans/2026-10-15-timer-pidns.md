# 计时查询 PID 命名空间修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，按已授权的当前会话逐项实现、一次独立审查执行。

**Goal:** 宿主计时器可由沙箱内只读查询器正确查询。

**Architecture:** 原状态发布协议和锁不变，以稳定锁/内容确认会话，PID 仅诊断。真实命名空间测试加现有进程/PTY 验收。

**Tech Stack:** Rust/libc、Python 标准库、Linux PID namespaces。

**Spec:** [修复设计](../design/specs/2026-10-15-timer-pidns-design.md)。

## Global Constraints

- 固定 `/tmp/fff-session-timer-v1`，状态三字段格式不变，新查询器兼容旧计时器。
- 查询不获取/释放锁、不写状态、不发控制信号、不加入任何控制或路径入口。
- 不影响人类已有实例；测试只清理自己启动的进程；新产物放入忽略的 runs/dist。

## Review Focus

- `l_pid==0` 仍是活锁，不能等同无锁；真实 PID namespace 测试覆盖。
- 正数 PID 重映射不能被错误拒绝；稳定异 PID 记录测试覆盖。
- 初始化或残留记录不得误作当前起点；保留原锁/内容校验与现有回归。
- 查询不得干扰单例或改 inode/mtime；真实进程验收覆盖。
- 共享 `/tmp` 不代表时钟一定共享；明确支持边界，不做错误的通用沙箱承诺。

### Task 1: 修复查询与回归验证

**Files:** `crates/session-timer/src/state.rs`、计时器说明及命名空间验收工具。

**Interfaces:** `query_record(path: &Path) -> Result<Record, Error>` 保持；`Record.pid` 只作诊断。

- [x] 写稳定异 PID 记录回归与真实命名空间查询测试，观察旧 PID 比较导致失败。
- [x] 移除无效相等假设，保留锁/初始化/双读/格式校验；测试 GREEN。
- [x] 完整 Rust、fmt、clippy、`tests/timer_integration.py` 和实际沙箱只读查询验收；同步文档并提交。

### Task 2: 题包与独立审查交付

**Files:** 专用参赛/组织者模板、指南、导航、报告、审查记录。

**Interfaces:** 原白名单打包入口、新 release 输出目录和仓库外验收。

- [x] 同步共享 inode/时钟边界，生成新题包并进行仓库外完整验收。
- [x] 完整 Rust/Python 检查、一次 fresh-context 独立审查，修复 Critical/Important 并保留证据。
- [x] 记录实际检查与兼容限制，本地提交合并，清理自己隔离工作区；生成最终题包。

完成证据：[实测报告](../reports/timer-pidns-2026-10-15.md)、[独立审查与修复](../reviews/timer-pidns-review-2026-10-15.md)。main 已合并，最终 release 题包及其实际沙箱查询通过。
