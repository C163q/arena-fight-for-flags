# 参赛题包的生成与维护

本说明供维护项目和制作题包的人阅读；不放入参赛压缩包。参赛者可以是人类程序员或 LLM，交付目标是独立实现符合 C ABI 的动态库。

## 一键生成

在仓库根目录运行：

```sh
python3 scripts/package_contest.py
# 或生成到新的目录
python3 scripts/package_contest.py --out dist/contest-kit-new
```

需要 Linux x86_64 GNU/glibc、Rust/Cargo 工具链和 GNU readelf。默认输出 `dist/contest-kit/`，目录已存在时拒绝覆盖。正常入口总是执行 `cargo build --locked --release`，选择裁判、worker、基准 AI、计时器这四个包，显式使用 GNU x86_64 目标、优化级别 3、关闭调试信息及 debug assertions、去除可移除符号。

编译设置使用受控的最高优先级 rustflags，覆盖外部目标平台参数；构建后检查实际 ELF 不含调试节/普通符号表，基准库保留四个 ABI 导出。

构建缓存独立位于 `target/contest-build/`，不从现有普通 `target/release/` 拿旧文件。打包失败只清理本次暂存文件，不删除既有输出。默认的 `dist/` 与构建缓存由 Git 忽略；自定义输出建议仍放在 `dist/` 下，或仓库外，避免误提交二进制。

```text
contest-kit/
  README.md             场外组织者说明，含题包与计时器哈希
  fff-timer             仅由场外人员手动操作
  participant.tar.gz    分发给参赛者的材料
```

只把 tarball 提供给参赛者，解压后在 `fff-contest/` 工作。外层计时器不进入 tarball；工作目录不能替代工具权限隔离，agent 若可读取外层目录仍能找到计时器。

## 固定文件范围

压缩包包含 `bin/` 下的 runner、worker、timer-query；`lib/` 下的基准 AI；C 头文件、七张 RON 地图、专门的参赛 README/docs、测评脚本及其所需模块、示例配置、回放导出器和离线播放器资源。路径与具体文件白名单在 `scripts/package_contest.py` 中显式列出，不递归复制工具目录。

内层 `manifest.json` 记录格式/ABI 版本、源码提交与是否有工作区修改、工具链、平台、所需最低 glibc、文件 SHA-256 和权限。同样的文件与构建信息生成相同 tarball 字节；不保证不同工具链或环境下重编译产生相同 ELF。题包不捆绑 glibc/libgcc，需要在目标比赛环境验证兼容性。

不分发引擎、裁判、基准 AI、SDK 或接口库源码，不包含 `.rs`、`.rlib`、测试夹具、内部设计/审查/报告、历史对局或缓存。只提供 C 头文件和接口文档作为绑定依据。Python/JS 辅助工具是明确允许公开的内容。去除符号不等于二进制不可逆向。

## 专用文档与披露边界

模板在 `packaging/contest/organizer/` 和 `packaging/contest/participant/`。不要直接把项目 `docs/` 复制进题包。

- API 必须完整，包括所有字段、类型、顺序、数组长度、尺寸/对齐、哨兵值、坐标、生命周期、返回码与预算。Rust 参赛者自行照头文件声明 `repr(C)` 类型和 C ABI 导出函数，无需与裁判使用相同版本的 Rust。
- 玩法说明覆盖基础行动、战斗、携旗、得分和基本冲突规则，旗点只概述为随机产旗。省略精确刷新生命周期、调度与失败重试、复杂移动依赖、随机算法和基准策略。
- ABI 已公开的运行参数仍如实说明，不删减头文件，不伪造数值。原始回放及辅助工具保持原样，参赛者可以通过实验推断题面未展开的规则。
- 不提供完整 AI 示例或策略 SDK，不把超过基准等同于最终胜出。参赛 README 明确要求持续测试与改进，提醒其他 LLM/程序员的 AI 可能显著强于基准。

当前题包的预算为比赛第 1 回合 250ms、其余 50ms，重启不重置首回合额度；`CtfInit.decision_budget_us` 仍为常规 50000µs。默认地图 v3 最近取旗距离为 6–8 步，目标分仍为 20。已有题包不会自动更新，应生成新目录；已冻结的旧测评计划继续使用旧输入，新版本另建赛程，不能混合续跑。

修改 ABI、地图、命令或播放器时，检查专用文档和白名单是否同步。精简文档应省略细节，不能编造不同规则。若未来需要连运行参数或回放数据也隐藏，须单独设计协议与记录变更。

## LLM 计时与场外操作

外层和内层 README 均须说明：LLM 的设计、编码、编译、自测时限为 **60 分钟**；**70 分钟**由场外人员强制终止会话并收取当时已有编译结果，无结果视作弃权，不等待补编译。LLM 必须时常执行 `bin/fff-timer-query`，只读查询总时间。人类程序员的时间安排另行约定。

场外人员启动与退出 `fff-timer`，维护计时与 agent 的文件权限，收取 `submission/libteam.so`、依赖说明和哈希，再安排正式名单、多次完整换位块对抗。计时器不自动结束会话，题包脚本也不控制 agent。共享 `/tmp` 的全局单例计时器要求有关场次依次计时。

## 检查

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s viewer -p 'test_*.py' -v
python3 scripts/generate_maps.py --check
python3 tests/contest_package_integration.py \
  --kit dist/contest-kit --out /tmp/fff-contest-check-new
```

独立验收输出目录必须是仓库外的全新目录；脚本保留解压题包、日志和真实对局。它先检查文件哈希、内部链接和禁止文件，再复制测试专用的 C/Rust 绑定（这些源码不在题包中），独立编译动态库，生成 2–8 人赛程，执行双人完整换位块并恢复/重建报告，执行 C/Rust 互战与八人对战，验证回放并导出 HTML/JSON。

验收只运行查询器，不启动、停止或接管计时器。真实对战需要 Unix socket 与子进程信号权限；普通 Python 单测使用真实组装逻辑与 ELF 文件，完整 ABI 行为由独立真实验收覆盖。
