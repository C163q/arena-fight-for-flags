# 三份参赛提交统一评测

日期：2026-10-16。状态：已完成准备与 65 场验证，按用户要求交接到宿主终端续跑；本文件尚不包含最终成绩。本轮使用既有 [league](../guides/league.md)，不修改候选代码、默认地图或评测算法。

## 输入与适用范围

| 候选 ID | 来源 | 原题包提交 | 最终库 SHA-256 |
| --- | --- | --- | --- |
| `contest_v1` | `~/Program/workspace/contest/fff-contest-v1/submission/libteam.so` | `fc8f9a7` | `e9ec50297f1e429c52b36716028e7a978460d8655e5b20740b65c46a62af3713` |
| `contest_v3` | `~/Program/workspace/contest/fff-contest-v3/submission/libteam.so` | `ae2997a` | `bd224802d328d3c5465715fe20876c8bbfb1e2bfb4071ea99d02c8b44966b6ff` |
| `codex_selftrial` | 本项目 `dist/contest-selftrial-20261016/fff-contest/submission/libteam.so` | `ba51e7d` | `14e7aeae8a94ab7d8b4f07f09bd7d55190eadea3b4c6a5c2ad90a7bf59da8d3a` |

用户确认 v3 使用规范提交入口 `libteam.so`，而不是目录中另一个哈希不同的 `libteam_final.so`。只读检查两位选手原目录，不重编译、不修复或改写其提交；实际对战使用 league 冻结副本。

统一裁判/worker/基准来自 `ba51e7d` 最新题包，地图采用当前仓库七张原始地图 v3。C ABI v1；每队首轮 250ms、其后 50ms；单场队伍串行，跨场固定 `jobs=1`。旧题包选手曾面对不同地图或预算，此结果衡量三份既有库在当前环境的表现，不能用于隔离模型能力、开发时长或题包版本的影响。

## 赛程与结果入口

候选固定为上表三份库。2 人图从三候选中组合参赛，人数较多时三者同场并使用当前基准的独立副本补齐；填充队不入榜。用户确认完成每地图五个完整重复块，增加种子样本；赛程保证候选出场、出生位、两两同场及有序位置对精确均衡。

| 地图人数 | 每块场数 | 五块场数 |
| --- | --- | --- |
| 2 | 6 | 30 |
| 3 | 6 | 30 |
| 4 | 12 | 60 |
| 5 | 20 | 100 |
| 6 | 60 | 300 |
| 7 | 42 | 210 |
| 8 | 56 | 280 |
| 合计 | 202 | 1010 |

每候选五块共出场 1000 次。各地图分别排名，总榜各地图等权；仅同一重复序号下七图全部完成并通过验证后才计入总榜。五块的配对 bootstrap 区间只作描述，不是普适显著性保证。

本地证据保留在忽略目录 `runs/submissions-20261016/`：

- `config.json`：本次配置，`provenance.json`：来源及程序哈希。
- `handoff.json`：交接时 65 场的状态快照，不随续跑自动更新。
- `league/plan.json` 与 `league/inputs/`：完整冻结赛程、地图和候选库。
- `league/report.md`、`standings.csv`、`results.json`：测评工具生成的结果。
- `league/matches/`：原始对局、调用明细和验证日志。

续跑命令为 `python3 scripts/league.py run runs/submissions-20261016/league --jobs 1`；重建报告为 `python3 scripts/league.py report runs/submissions-20261016/league`。不移动计划目录或替换冻结输入。

## 交接检查点

截至 2026-10-16 09:27 UTC 的交接快照：65/1010 场完成并验证；三份候选均零故障、零超时、零非法动作。2/3/4/5 人图各完成第一个完整块，6 人图有 21/60 场但块未完成，7/8 人图尚未开始。没有完整全图重复组，总榜仍为空，不能据此宣布最终名次。

本次父进程收到 SIGINT 后以 130 退出，保留在途尝试；随后成功重新验证原始记录并重建 65 场报告。用户在项目根目录执行上述 run 命令即可继续，工具会跳过已完成且验证有效的场次，并为中断场次创建新尝试。五块全部完成后再补充最终结果。

小人数阶段实测单场约 4–7 秒；后续人数、局长、背景负载与复验都会影响总耗时。已告知用户整轮约两小时的粗估并确认继续五块；该估算不是耗时承诺。

## 后续整理

完成后补充总榜、每地图成绩、故障/超时/非法动作及出生位表现；只讨论证据支持的差异。题包使用体验见 [参赛体验报告](contest-kit-selftrial-2026-10-16.md)，功能候选及验收边界见 [改进准备清单](../design/contest-kit-improvements.md)。
