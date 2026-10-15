# 参赛题包验收记录

## 首次完整验收

白名单打包器在 `8776824` 版本生成 release 题包，共 31 个参赛文件，压缩包约 1.28MB，外层计时器约 373KB。目标为 Linux x86_64 GNU，实际 ELF 需要 glibc ≥2.39 和 libgcc_s；不能直接用于较老 glibc 或其他架构。构建信息、精确文件哈希与权限见内层 manifest。

使用 `tests/contest_package_integration.py` 在仓库外 `/tmp/fff-contest-acceptance-v2/` 验收，约 7.30 秒完成 15 个程序调用：

- 解压后核对全部文件哈希、9 个本地文档链接及禁止文件。
- 仅按头文件独立构建 C 与 Rust C ABI 动态库；C/Rust 尺寸与对齐断言通过，动态导出符号齐全，未链接项目 Rust 库。
- 2–8 人快速赛程共 35 场均能生成；实际完成双人正式换位块 2 场、C/Rust 互战 1 场、八人局 1 场，四场均无 AI 故障/非法动作并通过正式验证。
- 双人测评分段执行一场后续跑，并重建报告；八人局导出自包含 HTML 和 JSON。
- 只读时间查询正确提示未运行，验收没有启动或停止计时器。

此次候选为测试专用等待策略，不随题包分发；对局验证独立可用性，不证明策略强度。首次受限沙箱运行因 Unix socket/进程操作权限返回 `Operation not permitted`，全部 AI load_error；在允许对应系统操作的环境重跑后成功，没有放宽任何断言。

本地完整原始数据位于上述 `/tmp/` 目录；摘要另保存在忽略目录 `runs/contest-kit-v1/acceptance-preview.json`。文件数不含验收后复制进去的测试源码和生成数据。

## 项目检查

54 个 Rust workspace 测试、29 个 Python 工具测试（新增题包 8 个）、8 个回放测试通过；fmt、clippy、七图生成一致性和文档链接检查通过。参赛 API 逐字段核对无遗漏；C/Rust 编译测试覆盖头文件布局。回放浏览器验收使用现有 Chromium 检查。

## 分发边界

只提供 C 头文件和接口文档，裁判与基准源码不分发；允许公开的 Python/JS 工具保留。题面省略的机制仍可从实验、接口和回放推断。外层 README 与内层 README 均写明 LLM 60 分钟任务时限、70 分钟强制终止并收取已有编译结果，无结果弃权，以及只读查询要求。

自动终止 agent 会话由场外人员执行，计时器不负责截止控制；只改变工作目录不能限制 agent 读取外层文件，分发时需使用相应文件/工具权限。

## 审查修复及最终交付

独立审查发现的目标 rustflags 覆盖问题已 RED→GREEN 修复，详见 [审查记录](../reviews/contest-kit-review-2026-10-15.md)。新增三项回归后，题包单测共 11 项；最终 main 再次通过 Rust 54 项、Python 工具 32 项和回放 8 项、fmt/clippy。

最终题包由干净的 main 提交 `fc8f9a7` 一键生成，保存在忽略目录 `dist/contest-kit/`。其压缩包 SHA-256：`11ad46439ebd4b39036ba0d00e216be23c4efd81b9d4bac6c92d47373dad9433`。外层 README、计时器与 tarball 共三个文件，tarball 仍为 31 个参赛文件，release ELF 实际调试节/符号与基准导出检查通过。

最终仓库外验收目录 `/tmp/fff-contest-acceptance-final/`，15 个程序调用、4 场真实比赛全部通过，耗时 6.69 秒；2–8 人赛程生成、C/Rust 独立编译、双人分段续跑/报告、八人局与回放导出均通过，无 AI 故障或非法动作。只读查询为未运行，没有启动计时器；摘要保存在 `runs/contest-kit-v1/acceptance-final.json`。

源码、维护模板、验收脚本和记录已提交；生成产物不进入 Git，不推送远端。首版预览与最终验收共 8 场成功真实比赛，另保留最初沙箱权限失败现场，不混作成功证据。
