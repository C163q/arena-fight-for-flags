# 测评机并行自测实测

实现提交：`bbdbb05`，基线 `4df73f2`。增加 `run --jobs N`，默认 1；单场队伍串行、计时预算与赛程不变。并行场次记录配置上限，JSON/CSV/Markdown 保留并行自测标记，混合串行续跑不清除。正式评测固定 jobs=1，另建正式计划。

## 检查与真实比赛

- 基线 Python 35 项通过；新增并发/分段、取消、参数、旧记录和报告测试先失败，再实现通过。最终 Python 41 项、播放器 8 项全部通过，`git diff --check` 和 151 个本地文档链接检查通过。
- 正式 release runner/worker：`tests/tournament_integration.py --jobs 2`，2–8 人 quick 35 场、8 人 balanced 56 场，共 **91 场**。所有场次经回放校验，AI 故障与非法动作均为 **0**；两场真实 SIGINT 半场保留并恢复，已完成场不重复，完整块排名、损坏记录及输入变化拒绝通过。
- 上述整个验收约 **670.108 秒**，记录共 **1,652,204,679 字节**。包含中断/恢复、重复验证和错误注入，不是比赛吞吐基准；没有同条件串行对照，不能据此声称加速比。
- `tests/tournament_parent_cleanup.py --jobs 2`：两个 runner 与两个已观察 worker 在父测评机 SIGKILL 后退出，锁覆盖清理，两场成功续跑；`--jobs 1` 的单 runner/已观察 worker 清理及两场续跑亦通过。仅清理测试自己的进程。
- 一次独立只读审查正常完成，无 Critical/Important/Minor；审查者另运行测评单测 24 项及私有多 verifier 中断/恢复、高 jobs 分段上限验证。详见 [审查记录](../reviews/tournament-jobs-review-2026-10-15.md)。

最初受限沙箱中的真实 worker 操作被拒绝，产生 EPERM/load_error；这些失败记录保留，不计入通过场次。后续在沙箱外使用全新路径重跑。父进程验收读取 `/proc` 时观察到 ESRCH，测试的存活探针补充处理正常进程消失竞态；生产代码无相应绕过。

原始验收位于 `runs/tournament-jobs/parallel-host/`、`kill-parallel-host-2/`、`kill-serial-host/`，单测/构建日志与过程账本在 `runs/tournament-jobs/verification/`。上述四场父进程恢复比赛和题包四场比赛另计，合计 **99 场成功完整比赛**，不含被中断或沙箱失败的比赛。

## 新参赛题包

产物：`dist/contest-kit-v3-parallel/`；由干净的 `bbdbb05` 构建，后续交付提交仅更新内部文档。压缩包 SHA-256：

```text
e0e20c9711ac4440466be869bd4edec9419f6fed9d79b3264aa640fe056ec8f7
```

Linux x86_64 GNU release，最低 glibc 2.39，另需 libgcc_s；31 个显式白名单文件，无游戏/策略/Rust 实现源码，仍只提供 C 头文件。旧题包不自动更新。

仓库外 `tests/contest_package_integration.py` 在 `/tmp/fff-contest-jobs-check/` 通过：15 个命令、C/Rust 自行声明接口并独立编译、2–8 人赛程、4 场真实比赛、回放验证/导出、并行设置后串行续跑的混合标记，以及只读计时查询。约 7.544 秒，未启动计时器。结果复制到 `runs/tournament-jobs/package-acceptance.json`。

题包两层 README 和自测指南均说明：全人数 balanced 每块 198 场、五块 990 场，先用单场或两场 2p quick 估算耗时；LLM 60 分钟包含自测，应查看查询器并保留已编译产物。

## 实际限制

并行共享 CPU、内存和磁盘，可能增加墙钟超时并改变排名，不保证线性加速；回放总空间不会减少。jobs 表示配置上限，不证明实际始终达到该并发，记录也不提供防篡改认证。正式 jobs=1 仍受外部负载影响。

本次未加入绑核、自动时间截止或恶意代码沙箱；仅在当前 Python 环境实测，没有遍历所有 Python 3.10+ 版本，也未穷尽磁盘耗尽、不可中断 I/O、连续强制信号的故障组合。
