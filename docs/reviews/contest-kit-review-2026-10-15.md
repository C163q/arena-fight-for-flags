# 参赛题包独立审查与修复

独立审查一次，范围为 `efb04fb..8b2e41a`，覆盖打包器、专用材料、白名单、源码分发边界及独立验收。审查正常完成；没有 Critical/Minor，发现一个 Important。未启动或干预计时器。

## 外部 Cargo 参数覆盖 release 约束

原打包器只删除通用 RUSTFLAGS/CARGO_ENCODED_RUSTFLAGS/CARGO_BUILD_RUSTFLAGS，目标平台专用的环境变量和 Cargo 配置仍可传入 `-C debuginfo=2 -C strip=none -C opt-level=0`。这些参数排在 profile 参数之后，使 release 名义下的实际 ELF 含调试信息、保留符号且取消优化，而 manifest 仍宣称已关闭调试并去符号。

审查者在独立 Cargo 工程复现；执行者新增真实 Cargo/rustc 回归 `test_target_rustflags_cannot_reenable_debug_or_disable_stripping`，同时注入目标环境变量和 `.cargo/config.toml`，修复前明确发现 `.debug_info`，RED。

修复为设置受控的最高优先级 `CARGO_ENCODED_RUSTFLAGS`，固定优化级别 3、debug=0、strip=symbols 和关闭 debug assertions，覆盖目标环境/配置中的 rustflags。正常入口构建后再检查五份 ELF：拒绝 `.debug_*`、`.zdebug_*` 和 `.symtab`，并验证基准库动态符号表保留四个 C ABI 函数。

三个新增回归均先失败后通过：环境污染无法重开调试；带调试节的真实 C ELF 被拒绝；缺失基准 ABI 导出被拒绝。最终题包单测 11 项全部通过。

## 审查证据与边界

审查者独立运行首版 8 项题包单测，检查 31 个压缩包文件及 9 个内部链接，并直接验证发布阶段遇到已存在目录时拒绝替换、保留原文件。白名单、相对路径、完整接口、LLM 60/70 分钟要求与只读计时边界无其他发现。

原始回放、Python/JS 辅助源码与运行参数仍可被参赛者观察，符合用户确认的“精简题面、允许探索”方案；未把“不附源码”描述为无法逆向二进制。场外人员负责结束会话，不新增计时控制功能。

没有搁置或未修复的审查发现；按计划不进行第二轮独立审查。修复后的最终真实题包与合并验收见 [题包验收记录](../reports/contest-kit-2026-10-15.md)。
