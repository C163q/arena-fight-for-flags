# Session Timer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 实现人类终端正向计时器与 LLM 一次性只读查询器。

**Architecture:** 新 Rust 包 `crates/session-timer` 构建 `fff-timer` 与 `fff-timer-query`；共享纯时间换算、Linux 锁与记录读取、终端渲染模块。计时只记录单调起点，查询独立计算经过时间，不向计时器发请求。

**Tech Stack:** Rust 2024、标准库、workspace 已有 libc；真实 PTY/进程验收用 Python 标准库。

**Spec:** `docs/superpowers/specs/2026-10-13-session-timer-design.md`，用户已明确批准实现。延续本会话 inline 执行和本地 Git 管理。

## Global Constraints

- Linux，共享 `/tmp/fff-session-timer-v1` 单例，不暴露路径、起点、暂停/继续/重置参数。
- `CLOCK_BOOTTIME`，休眠计入、向下取整，上限 359999 秒，保持运行。
- 查询只读文件和 `F_GETLK`，成功只输出一行时间，不存在退出 1、其他错误非零。
- 状态文件不删除、不 rename；真实锁判断活性，初始化锁区间避免旧起点。
- 非 TTY 静默；大字完整放不下则基本时间；关闭显示后继续计时；正常信号退出收尾。
- 不影响人类已启动的计时器，验收仅停止自身进程。

## Review Focus

- POSIX 锁在同进程关闭同 inode 的任何描述符时释放：计时器只能持有一个状态描述符，不在自身调用查询。
- 初始化、退出/重启与残留 PID：查询要检查就绪范围、前后锁所有者和记录一致性。
- 全局路径存在符号链接/FIFO/硬链接/未知内容：拒绝且不覆盖，不因 open 阻塞。
- PTY 堵塞或关闭：输出不能阻塞信号退出，不能停止计时；不改变调用者共享的输出描述符标志。
- 重启与测试竞争：真实验收先排除既有计时器，不杀他人实例，不在 CLI 暴露测试命名空间。

### Task 1: 单调计时、单例状态与只读查询

**Files:** Cargo.toml/Cargo.lock；`crates/session-timer/Cargo.toml`、`src/lib.rs`、`src/clock.rs`、`src/state.rs`。

**Interfaces:** `clock::now_ns() -> Result<u64, Error>`、`clock::format_elapsed(start_ns, now_ns) -> Result<String, Error>`；`state::Session::acquire(path) -> Result<Session, Error>`、`Session::publish()`；`state::query_record(path) -> Result<Record, Error>`，Record 含 pid/start_ns。

- [x] 写测试并观察失败：计时边界、饱和；独立子进程持锁、重复启动拒绝、就绪/旧状态、只读不创建/不修改、退出/强杀释放、不覆盖未知格式/符号链接/FIFO/硬链接。
- [x] 实现 Linux 时钟、固定记录协议、文件安全打开/权限、POSIX 两段记录锁，查询前后校验。
- [x] `cargo test --offline -p fff-session-timer --lib` 全通过；提交。

### Task 2: 大字终端与两个程序

**Files:** `src/display.rs`、`src/bin/timer.rs`、`src/bin/query.rs`、`src/lib.rs`。

**Interfaces:** `display::frame(text, size, ansi) -> String` 纯布局；`Terminal::new/update/finish` 使用独立非阻塞终端描述符；公开 `timer_main()`、`query_main()` 供 bin 调用。

- [x] 先写渲染测试观察失败：大字完整、尺寸受限、小终端/未知尺寸/dumb 回退、缩放；实战验收脚本先写对两个 CLI 的行为要求。
- [x] 实现块状字形/居中/resize、非阻塞输出和信号退出，非终端静默，查询严格一行、拒绝控制参数。
- [x] `cargo test --offline -p fff-session-timer` 通过，release 构建两个程序；提交。

### Task 3: 真实验收与文档

**Files:** `tests/timer_integration.py`、`docs/timer.md`、README、AGENTS、architecture 与设计状态。

- [x] 真实 release 程序验证：不同目录竞争、时间前进、读取不改文件、退出/重启/强杀、拒绝参数、大/小/resize PTY、非 TTY 静默、关闭与堵塞显示、自然终端收尾。拒绝干扰既有计时器。
- [x] 全 workspace Rust 测试、fmt/clippy、Python 单测通过；保存实际验收结果。
- [x] 更新文档与状态并提交，记录测试证据。

## 完成流程

- [x] 对本次新增功能做一次独立审查，重要发现一次修复，补 RED→GREEN 回归，不重新审查。
- [ ] 合并 main 并复验，正常清理本次工作区，确保没有遗留测试计时器。

## 实施证据

53 个 Rust workspace 测试（计时器 11 个）、29 个既有 Python 单测、fmt/clippy 通过。真实 release 验收 14 项通过，数据保存在根目录 `runs/timer-v1/acceptance-complete/acceptance.json`，耗时 4.51 秒；没有遗留运行中的计时器。大字抓取见该目录 ANSI 文件，纯文本预览为 `runs/timer-v1/preview.txt`。全局状态文件保留，查询返回未运行。

独立审查正常完成；唯一 Important 已 RED→GREEN 修复，见 [审查记录](../../timer-review-2026-10-14.md)。修复后 Rust 54、Python 29、fmt/clippy 通过，14 项最终 release 验收通过。
