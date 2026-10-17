# 参赛开发工具独立审查

日期：2026-10-17。一次全新上下文、只读独立审查，范围 `bb44291..8548fe5`，依据 [已批准设计](../design/specs/2026-10-16-contest-tools-design.md) 与 [计划](../plans/2026-10-16-contest-tools.md)。实现与验收见 [报告](../reports/contest-tools-2026-10-17.md)。

## 发现与处理

无Critical。两项Important进入一次修复，另有一项Minor保留。

1. **全局PAX大小覆盖绕过配额**：`archive.py` 原先只限制扩展头本身，tarfile仍可用原始大尺寸跳过隐藏数据。独立审查用8MiB隐藏数据复现，在6776字节有效载荷配额下仍恢复成功。现在只接受本工具写入格式需要的一个局部PAX路径字段；拒绝全局头、大小覆盖、任意其他字段、GNU长名/稀疏及扩展链。保留64KiB扩展头和4096字符路径上限。
2. **验证到归档快照的时间窗口**：原代码丢弃正式验证前后的记录指纹，再从稍后状态建立归档快照。审查以真实两回合记录复现：验证返回后改比分，归档成功但恢复失败。现在单场保留验证指纹直到发布；实验在collect之前捕获全部完整记录的指纹，验证后及发布前检查，最后再校验冻结输入。不能将稍后的变更当成新的可信快照。

回归先观察失败，再修复通过：`test_global_pax_cannot_hide_raw_data_outside_payload_quota`、`test_only_one_local_path_extension_is_allowed`、`test_change_after_verification_before_snapshot_is_not_published`、`test_experiment_change_after_collect_is_not_published`。额外兼容性用例验证64字符版本ID产生的正常PAX长路径仍可归档/恢复。归档专项15项通过。

**保留的Minor**：实验摘要 `summary.md` 的候选段落插在表头和数据行之间，Markdown表格渲染不完整；单场摘要及实验JSON/指标不受影响。按本轮执行流程保留到后续显示修订，没有将它描述为已修复。

独立审查的 `Declined to judge` 为空；两项Important均接受，不需第二次审查。修复以回归、完整Python套件和重新打包后的仓库外验收证明，未再派发审查者。

## 执行裁定

- 沿用用户明确批准的实施授权及“当前会话实施、最终独立审查”，不重复询问；若理解错误，代价是需要调整流程安排。
- 续跑、归档同时检查内层计划锁，避免外层控制器死亡时绕过子进程清理；代价是清理期间暂不可操作。
- 在种子模块引入时就同步旧题包白名单，保证tournament可独立导入；代价是增加一个公开辅助模块。
- 最终审查、集成和清理放在实现验收任务之后，遵循inline执行阶段；代价仅为进度里程碑顺序，审查没有省略。
