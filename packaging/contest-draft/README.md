# 参赛文档审阅存档

这组文档在 2026-10-17 从 `packaging/contest/` 复制后，经用户审阅和修改，现已定稿并同步回正式模板。本目录保留本次审阅结束时的副本，**不参与打包，后续维护以 `packaging/contest/` 为准**。本次未覆盖已有分发题包。

下表可查阅正式模板与本次定稿副本。审阅前的原文保存在 Git 历史中，例如 `git show f195039:packaging/contest/participant/docs/testing.md`。

| 文档 | 正式模板 | 本次定稿副本 |
| --- | --- | --- |
| 自测说明 | [正式模板](../contest/participant/docs/testing.md) | [定稿副本](participant/docs/testing.md) |
| 参赛入口 | [正式模板](../contest/participant/README.md) | [定稿副本](participant/README.md) |
| 基本规则 | [正式模板](../contest/participant/docs/rules.md) | [定稿副本](participant/docs/rules.md) |
| 回放说明 | [正式模板](../contest/participant/docs/replay.md) | [定稿副本](participant/docs/replay.md) |
| 接口说明 | [正式模板](../contest/participant/docs/api.md) | [定稿副本](participant/docs/api.md) |
| 场外操作 | [正式模板](../contest/organizer/README.md) | [定稿副本](organizer/README.md) |

这里仅存放文档。文内命令及头文件、播放器链接按最终题包的目录结构编写，不能直接在本审阅目录运行。审阅时可另看仓库中的 [C 头文件](../../include/ctf_ai.h) 和 [播放器](../../viewer/index.html)。

## 本次采用的写法

面向会写基础代码、但未必熟悉动态库和进程管理的读者。入口先说明要交什么、由谁调用，再引导读规则、接接口、跑少量比赛。用命令的实际作用解释工具，不要求参赛者先理解内部架构。

- “候选”在操作说明中改为“你的 AI”或“正在测试的版本”；报告中确实出现的 `candidate` 解释一次，保留原字段名便于查找。
- “私有两回合真实 worker”改为“通过正常比赛程序加载你的 AI，进行两回合检查”，说明目的和通过检查的含义。
- `worker` 仅在题包文件说明中对应准确文件名，并说明自动启动；不作为学习自测的前提。
- “冻结输入”“快照”改为“保存创建测试时的库和地图副本”，直接解释为什么改代码后必须新建测试。
- 计算时限、指针有效期、数据布局等直接影响正确运行的内容保留，补充解释；旗帜精确刷新、复杂移动依赖、基准策略等仍不展开。
- 运行失败先给下一步操作和报告位置；隔离环境配置放在场外说明中。

自测说明后半部分保留按需查阅的并行、备份、单场和名单配置。本次已通过用户逐项审阅，未另行进行新手用户实测。

核对依据、检查记录和后续反馈处理见 [处理记录](../../docs/reviews/contest-documents-2026-10-17.md)。
