# 千分制评测显示实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans；按用户此前选择在当前会话实施，最后一次独立审查。

**Goal:** 将当前两套测评报告统一改为千分制，保持现有计算与排序。
**Architecture:** 在共用 reporting 中提供纯显示换算；两套统计结果增加兼容字段，导出器使用新字段。真实比赛记录保持不变。
**Tech Stack:** Python 标准库、Markdown、现有 release 题包构建器。
**Spec:** `docs/design/specs/2026-10-16-score-presentation.md`。

## Global Constraints

0–1000，半分向上；保留 0–1 原始字段；不修改精确排序、执行器、ABI、计划格式与白名单；正式评测不重跑。

## Review Focus

整数取整边界；同显示分但未取整值不相等；置信区间尺度与缺失值；CSV/JSON 兼容；包内外文档与旧记录重建。

### Task 1: 千分制显示、报告与交付

**Files:** `scripts/tournament_lib/{reporting,league_reporting}.py`；`tests/test_score_presentation.py`；使用指南、参赛模板、导航、设计决策及实测报告。
**Interfaces:** `display_score(value) -> int`；`score_fields(value, ci) -> dict`，由两套 reporting 共用。原统计字段和排序键保持语义。

- [ ] 添加整数边界、同整数非并列、两套真实导出及原始字段兼容的回归；运行并确认 RED。
- [ ] 实现纯显示换算及新字段，Markdown/CSV 使用千分制；全 Python 与 viewer 单测 GREEN。
- [ ] 同步文档和模板；读取原始记录重建 1010 场报告，核对原始分、排名、置信区间及比赛文件保持不变。
- [ ] 用既有真实比赛验证 league/旧 tournament 的报告重建；执行器未变，不重跑大规模执行验收。生成新 release 题包并执行仓库外题包验收；一次独立审查。
- [ ] 记录证据、本地提交、集成并清理本次工作区。不推送。
