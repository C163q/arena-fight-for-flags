# 文档导航

构建、运行比赛和编写 AI 从 [项目 README](../README.md) 开始。日常使用查阅使用指南；玩法和数据契约查阅参考规范。设计稿、实施计划、审查和实测报告保留过程与证据，阅读时注意其日期、版本和适用范围。

## 使用指南 `guides/`

| 文档 | 用途 |
| --- | --- |
| [自动测评机](guides/tournament.md) | 配置参赛名单、生成赛程、运行与续跑、查看排名 |
| [多 AI、多地图测评](guides/league.md) | 候选自动组合、填充空位与跨地图总榜 |
| [参赛题包](guides/contest-kit.md) | 一键生成、分发边界、专用文档与场外操作 |
| [计时器](guides/timer.md) | 人类启动终端计时器，LLM 只读查询总用时 |

比赛命令见 [项目 README](../README.md#构建和比赛)；观看与导出回放见 [回放说明](reference/replay.md)。

## 参考规范 `reference/`

| 文档 | 用途 |
| --- | --- |
| [游戏规则](reference/rules.md) | 权威玩法、动作合法性和回合结算顺序 |
| [AI 接口](reference/api.md) | C ABI v1、字段、所有权与计算预算 |
| [地图格式](reference/maps.md) | RON schema、默认七图与加载校验 |
| [回放格式与播放](reference/replay.md) | 记录文件、验证、导出和离线播放器 |
| [基准 AI](reference/benchmark-ai.md) | 公开参考策略、评估方法和已知限制 |

## 架构与设计 `design/`

| 文档 | 用途 |
| --- | --- |
| [系统架构](design/architecture.md) | 当前模块边界、进程管理与数据流 |
| [设计决策](design/decisions.md) | 已接受的方案及用户确认来源 |
| [交付状态与路线图](design/roadmap.md) | 交付情况和后续方向 |
| [参赛题包改进准备](design/contest-kit-improvements.md) | 基于体验与对抗的候选改进、验收边界；尚未实施 |

已完成功能的设计稿保存在 `design/specs/`，当前使用方式和实际边界以指南、参考规范为准：

- [参赛开发工具改进设计](design/specs/2026-10-16-contest-tools-design.md)：预检、小规模自测、固定条件版本比较、摘要与归档；待审阅、尚未实施。
- [千分制显示设计](design/specs/2026-10-16-score-presentation.md)
- [多 AI、多地图测评设计](design/specs/2026-10-16-league-design.md)
- [本机并发容量测量](design/specs/2026-10-15-jobs-capacity-design.md)
- [测评机并行自测](design/specs/2026-10-15-tournament-jobs-design.md)
- [计时查询 PID 命名空间兼容](design/specs/2026-10-15-timer-pidns-design.md)
- [首回合预算与地图 v3](design/specs/2026-10-15-arena-v3-design.md)：首回合预算、旗点运输距离与标定。
- [参赛题包](design/specs/2026-10-15-contest-kit-design.md)：外层组织者材料、内层参赛内容、LLM 时限与披露边界。
- [播放器改进](design/specs/2026-10-13-viewer-usability-design.md)
- [地图与数值标定](design/specs/2026-10-13-map-balance-design.md)
- [自动测评机](design/specs/2026-10-13-tournament-design.md)
- [总用时计时器](design/specs/2026-10-13-session-timer-design.md)

## 实施计划 `plans/`

计划记录任务拆分、验收要求和实施证据；进度以各文件为准：

- [千分制显示](plans/2026-10-16-score-presentation.md)
- [多 AI、多地图测评](plans/2026-10-16-league.md)
- [本机并发容量测量](plans/2026-10-15-jobs-capacity.md)
- [测评机并行自测](plans/2026-10-15-tournament-jobs.md)

- [计时查询 PID 命名空间兼容](plans/2026-10-15-timer-pidns.md)
- [首回合预算与地图 v3](plans/2026-10-15-arena-v3.md)

- [首个可运行版本](plans/2026-10-13-playable-v1.md)
- [播放器改进](plans/2026-10-13-viewer-usability.md)
- [地图与数值调整](plans/2026-10-13-map-balance.md)
- [自动测评机](plans/2026-10-13-tournament.md)
- [总用时计时器](plans/2026-10-14-session-timer.md)

- [参赛题包](plans/2026-10-15-contest-kit.md)

## 审查记录 `reviews/`

记录独立审查发现、修复、回归证据与审查范围：

- [千分制显示审查](reviews/score-presentation-2026-10-16.md)
- [多 AI、多地图测评审查](reviews/league-review-2026-10-16.md)
- [本机并发容量审查](reviews/jobs-capacity-review-2026-10-15.md)
- [测评机并行自测审查](reviews/tournament-jobs-review-2026-10-15.md)
- [计时查询 PID 命名空间审查](reviews/timer-pidns-review-2026-10-15.md)
- [首回合预算与地图 v3 审查](reviews/arena-v3-review-2026-10-15.md)
- [参赛题包审查](reviews/contest-kit-review-2026-10-15.md)
- [首版独立审查](reviews/review-2026-10-13.md)
- [自动测评机审查](reviews/tournament-review-2026-10-13.md)
- [计时器审查](reviews/timer-review-2026-10-14.md)

## 实测报告 `reports/`

报告结论仅适用于记录中的地图、AI、配置和样本；原始对局数据保留在本地 `runs/`，不随文档迁移。

- [地图竞技位置表现复核](reports/map-competition-2026-10-16.md)：既有三策略结果中的出生位差异，不修改地图。
- [千分制显示验收](reports/score-presentation-2026-10-16.md)：兼容字段、原记录重建与新题包。
- [三份参赛提交统一评测](reports/submissions-2026-10-16.md)：三份冻结提交、当前地图与串行均衡对抗。
- [参赛题包独立实现体验](reports/contest-kit-selftrial-2026-10-16.md)：限时开发、接入与迭代体验，明确已有知识的影响。
- [多 AI、多地图测评实测](reports/league-2026-10-16.md)：测评工具自身的兼容性、真实执行与交付验收。
- [本机并发容量实测](reports/jobs-capacity-2026-10-15.md)：512场、建议8并发与实测边界。
- [测评机并行自测实测](reports/tournament-jobs-2026-10-15.md)：并发、清理、91 场完整验收与新题包。
- [基准 AI 首版实测](reports/evaluation-2026-10-13.md)：旧地图上的对照结果。
- [地图 v2 与 20 分终局标定](reports/map-balance-2026-10-13.md)：历史地图的标定与位置偏好。
- [首回合预算与地图 v3 实测](reports/arena-v3-2026-10-15.md)：当前默认地图、49 场自战和位置偏好。
- [计时查询 PID 命名空间修复实测](reports/timer-pidns-2026-10-15.md)：真实沙箱、旧计时器兼容和完整进程验收。
- [参赛题包验收](reports/contest-kit-2026-10-15.md)：独立编译、对战、自测与回放验收。
- [地图 v3 概览](assets/maps-v3.svg)：当前默认七图。
- [地图 v2 概览](assets/maps-v2.svg)：历史布局。

## 文档维护

新增使用说明放入 `guides/`，规则和接口契约放入 `reference/`；架构、决策和设计稿放入 `design/`；执行计划、审查记录、实测报告分别放入 `plans/`、`reviews/`、`reports/`。共享图片放入 `assets/`。

指南和规范随实现更新，历史记录保留日期、版本、结论及限制。新增文档同步补充本索引；移动文档同步更新 Markdown 链接、命令示例、脚本输出路径和 [协作约定](../AGENTS.md)。
