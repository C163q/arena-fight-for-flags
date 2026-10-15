# 参赛题包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，沿用用户确认的当前会话逐项实现与一次独立最终审查。

**Goal:** 一键交付场外计时器与独立、可自测的参赛 tarball。

**Architecture:** Python 标准库打包器运行隔离的 release 构建，按显式白名单组装，验证后原子发布。参赛文档独立维护，仅 C 头文件作为语言接入材料。

**Tech Stack:** Python 3.10+、Cargo release、Linux x86_64 GNU、现有测评/回放工具。

**Spec:** [参赛题包设计](../design/specs/2026-10-15-contest-kit-design.md)。用户已确认开始实现。

## Global Constraints

- 外层只有 README.md、fff-timer、participant.tar.gz；内层无 fff-timer、Rust 源码/rlib、策略 SDK、内部文档。
- C ABI 字段完整，玩法精简且不误导；原始回放不删改。
- LLM 60 分钟完成、70 分钟强制收取编译结果，无结果弃权；仅场外人员控制计时。
- 无既有输出覆盖，不扫描复制整个仓库；生成产物放在忽略的 dist/。

## Review Focus

1. 源文件符号链接/缓存/额外源码混入：白名单与拒绝符号链接测试。
2. 输出位置位于源码或祖先目录：拒绝覆盖及失败后只清理暂存目录测试。
3. release 构建受外部 Cargo 配置影响：显式目标/产物路径、实际 ELF 验证及动态库符号验收。
4. 脱离仓库运行时相对路径或模块缺失：仓库外真实编译/对战/评测/导出。
5. 不同平台和字段定义漂移：平台限制、接口全部类型字段说明人工核对，C 与 Rust 独立接入验收。

### Task 1: 打包与专用材料

**Files:** 创建 `scripts/package_contest.py`、`packaging/contest/`、`tests/test_contest_package.py`；修改 `.gitignore`。
**Interfaces:** `assemble(root: Path, artifacts: Path, output: Path, build_info: dict) -> Path` 负责已构建产物的白名单组装；`main()` 唯一正式入口始终执行 release 构建。

- [x] 写文件集/哈希/权限/独立配置、重复输出拒绝、缺失产物/链接拒绝与失败清理测试；首次运行证明缺失打包器失败。
- [x] 实现打包器、独立文档、模板和配置；关闭调试信息，去除可移除符号，记录平台与构建信息。
- [x] 单测与既有 Python 单测通过；提交。

### Task 2: 独立真实验收与维护文档

**Files:** 创建 `tests/contest_package_integration.py`、`docs/guides/contest-kit.md`；更新 README/AGENTS/导航/设计状态。
**Interfaces:** 消费 Task 1 的外层目录，从 tarball 在 /tmp 解压，使用 `bin/`、`include/`、`config/` 和 `viewer/`。

- [x] 创建真实验收脚本：只用头文件构建候选库；2–8 人生成赛程；双人完整换位块运行、恢复报告和回放验证/导出；只读查询，不启动计时。
- [x] 运行正式打包与独立验收，排除硬编码仓库路径；手工核对完整 API、LLM 时限和竞争要求。
- [x] 文档记录生成、维护、披露规则和实际验收；相关单测、地图一致性、链接、fmt/clippy 检查通过；提交。

### Task 3: 独立审查与交付

**Files:** 审查记录和计划状态。

- [x] 派发一次新上下文独立审查，关注完整工作分支及 Review Focus。
- [x] 若有重要问题，RED→GREEN 修复并重跑相应检查，保留审查证据。
- [ ] 合并本地 main；在 main 生成最终忽略题包，复验；提交最终文档并清理工作区。
