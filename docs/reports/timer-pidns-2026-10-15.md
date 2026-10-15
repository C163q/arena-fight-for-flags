# 计时查询 PID 命名空间修复实测

## 根因与实际修改

用户报告沙箱内查询失败。独立临时锁检查证明共享 inode 与 `F_GETLK` 本身正常：宿主报告持有者 PID，工具沙箱因 PID 隔离报告 0。旧查询器把文件中的宿主 PID 与该值比较，误报“尚未就绪”。反方向查询时同一进程还会映射为不同的正数 PID，单独放行 0 不足以完整修复。

修复移除跨来源 PID 相等要求。三字段 `FFF_TIMER_V1 pid start_ns` 格式、固定 `/tmp` 路径、POSIX 单例及初始化锁保留；记录 PID 仅供诊断。查询仍只读打开、按锁类型判断是否有活锁、前后校验锁持有者与初始化状态，并两次读取完整记录检查一致性和格式。没有启动、停止、暂停、重置、改路径或信号入口。

## RED → GREEN

新增三个回归在旧实现全部失败（NotReady）：

- 子 PID 命名空间查询宿主活锁：锁可见，持有者 PID 为 0。
- 宿主查询子命名空间活锁：锁持有者映射为另一正数 PID。
- 稳定发布记录中的诊断 PID 不与查询方锁 PID 比较。

修复后计时器 16 项 Rust 测试通过，包括两个真实命名空间方向，**未跳过**。原有初始化、残留记录、重启、单例、特殊文件与只读用例均保留。完整 workspace 60 项通过，fmt 与 clippy 通过。

## 正式程序与实际工具沙箱

`tests/timer_integration.py --pid-namespace` 使用 release 二进制并强制执行真实 `unshare` 查询，共 15 项检查通过，用时 4.757 秒。包含非 TTY 静默、时钟推进、单例竞争、只读、SIGINT/SIGTERM/SIGKILL 后释放、从零重启、PTY 字体/resize/终端恢复与输出关闭/堵塞。若环境不支持命名空间，强制选项失败而不静默跳过；普通 Rust 用例会明确报告 SKIP，不能据此宣称已覆盖。

实际工具沙箱也完成独立对照：先确认无人运行计时器，再由测试在宿主启动自己的旧版 `dist/contest-kit-v3/fff-timer` 实例。沙箱内 `F_GETLK` 确认活锁 PID 为 0；旧题包查询器返回 2（尚未就绪），新查询器返回 0，stdout 为 `00:00:05`。双方 PID 命名空间不同、时间命名空间相同；查询前后文件内容和 mtime 不变，旧计时器继续运行且单例锁保留。测试只终止自己的实例，结束没有测试计时器残留。

这同时证明新查询器能查询旧版未重启的计时器，不需要改状态文件或让人类重开计时。没有修改外部参赛目录或替换其二进制。

原始证据保留在 `runs/timer-pidns/timer-acceptance/acceptance.json` 与 `runs/timer-pidns/codex-sandbox/acceptance.json`；后者同目录保留本次专用 host/query 脚本与旧查询器，便于复查。测试源提交基线为 `99d2d39`，修复提交为 `dcc9759`。

## 支持边界

沙箱与宿主仍需共享同一状态 inode 和 `CLOCK_BOOTTIME` 时间基准。独立 `/tmp`、被禁止的文件读取/锁查询或偏移后的时间命名空间不由本修复打通；不能承诺任意沙箱均可查询。当前协议不是防同 UID 恶意篡改的认证机制。查询器保持只读，不自动改变运行环境或提权。

## 重现

```sh
cargo build --release -p fff-session-timer
cargo test -p fff-session-timer -- --nocapture
python3 tests/timer_integration.py --out runs/timer-check-new --pid-namespace
```

真实测试需要进程信号/PTY/命名空间权限；已有人工实例时验收拒绝启动。源码检查和运行验收按各自实际范围报告。
