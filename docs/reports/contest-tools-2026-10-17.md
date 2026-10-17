# 参赛开发工具验收

日期：2026-10-17；实现方案见 [设计](../design/specs/2026-10-16-contest-tools-design.md)，操作见 [指南](../guides/selftest.md)。本轮不修改规则、ABI、AI预算或地图，不重跑原正式1010场。

## 实际交付

统一 `scripts/selftest.py`：环境/ABI分阶段预检，默认两场换位，自定义地图和固定对手，版本分别对同一对手共享随机输入条件，冻结快照续跑，公开行为摘要、磁盘估算和非破坏归档/恢复。保持旧 tournament 接口和并发来源。专用参赛文档与显式打包白名单同步更新，league不进入题包。

## 验证证据

原始验收保留在仓库忽略的 `runs/contest-tools-20261016/` 与 `runs/contest-tools-20261017/`。

| 检查 | 结果 |
| --- | --- |
| Python全套 | 102项通过，含种子复用、原子发布、预检、实验、摘要和归档攻击输入 |
| viewer | 8项通过 |
| Rust | workspace 61项test、fmt --check、clippy all-targets -D warnings通过 |
| 地图生成一致性 | 七张默认地图 --check通过，资产不修改 |
| 真实预检 | wait/坏ABI/退出/无限循环，8场两回合；类别与退出码符合预期，见20261016/preflight/acceptance.json |
| 真实新自测 | 默认原图2场＋两版本短图4场，共同条件、冻结后源库变更、串行续跑保留并发、无重复、摘要、归档恢复、损坏输入拒绝；见20261017/selftest/acceptance.json |
| 新入口父进程SIGKILL | jobs=2，观察2个runner/4个worker，全部退出、内层锁覆盖清理、活动归档拒绝、恢复2场；见20261017/selftest-cleanup/acceptance.json |
| 旧测评器 | 91场（quick 2–8人35场＋balanced 8人56场），真实中断/续跑、记录损坏和冻结输入拒绝，零AI故障/非法；见20261017/tournament/acceptance.json |
| 旧入口父进程SIGKILL | jobs=2，2个runner/4个worker清理、锁与续跑通过；见20261017/tournament-cleanup/acceptance.json |
| 代表回放摘要 | 已有328轮记录先verify再分析，双方名义伤害93/129、实际承受129/93、携旗阵亡11/4；见20261016/analysis-duel |
| 单场归档往返 | 已有328轮、662文件、5311586原始字节，恢复重新验证；见20261016/duel-records.tar.gz与restored-duel |

上述短图只修改测试私有副本的回合上限，不将短图结果当AI强度证据。预检中的失败是主动构造的候选故障，不是工具失效。并行验收属于开发自测，正式评测仍固定jobs=1。所有计时器操作仅限只读查询，未启动或接管人类计时器。

## 限制

共同种子不保证不同策略的后续世界相同；预检只验证给定两回合局面；空间估算依赖同图小样本，不是上界。归档完整性哈希不认证来源，恢复仅用于离线查看/审计，不迁移续跑；验证使用外部可信裁判。进程隔离不等于恶意代码安全沙箱。

地图证据复核已完成，见 [位置表现](map-competition-2026-10-16.md)。具体布局调整仍需单独设计和标定，本轮没有修改。

## 新题包

输出 `dist/contest-kit-tools-20261017/`，从干净提交 `ef0a435` release构建，39个内层文件。归档SHA-256：`a154a0af090c88a355f253655b9bb28b258c9f21b6636bc7fa22a800dfcec6f6`。最低glibc 2.39；不打包源码实现、计时器控制程序、league或内部文档。

仓库外验收 `/tmp/fff-contest-tools-20261017/acceptance.json` 通过：23个命令，12场真实比赛（其中8场两回合），独立C/Rust编译、全部文件哈希、10个内部链接、旧赛程及新工具全流程。只读查询器返回1，表示计时器不存在，未启动计时器。验收摘要副本保存在 `runs/contest-tools-20261017/package-acceptance.json`。
