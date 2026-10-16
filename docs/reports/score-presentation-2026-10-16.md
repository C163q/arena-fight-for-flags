# 千分制显示验收

日期：2026-10-16。实现提交 `bd65f59`，依据 [设计](../design/specs/2026-10-16-score-presentation.md)。仅改积分显示和兼容输出，不修改比赛、赛程、精确排序、地图权重或平均夺旗分。

## 输出与兼容

两套工具的 Markdown 主积分、出生位名次积分和 95% 区间使用千分制整数，半分向上。CSV 增加 `score`；JSON 增加 `score_scale=1000`、`score`、`score_ci95`，league 总榜另有 `by_map_score`。原有 `rank_score`、`rank_score_ci95`、`by_map` 仍为 0–1；显示同整数不自动并列。

## 验证

- 改动前 61 项 Python 单测通过；四项新回归先 RED 后 GREEN，覆盖取整边界、两套导出及原字段兼容、缺失区间、同为 833 分但排名不同。
- 改动后 65 项 Python 单测与 8 项 viewer 单测通过；包含题包 11 项单测。
- 独立审查额外运行 28 项相关单测，比较 16 组完整/部分/空结果的旧字段与排序，无问题，见 [审查记录](../reviews/score-presentation-2026-10-16.md)。
- 旧版固定名单的 14 场真实记录通过 report 入口重新验证并导出，无需重新运行 AI。
- 正式 1010 场通过 league report 入口逐场复验并重建。主积分为 803、514、341；区间为 796–809、490–537、315–372。原有字段、排序与归一化区间逐项比较不变，681916 个原始比赛文件的 inode/大小/mtime/ctime 元数据指纹保持一致。没有重跑正式对局。

原报告备份在 `runs/submissions-20261016/before-per-mille/`，重建结果仍在 `runs/submissions-20261016/league/`。核对证据为 `runs/score-presentation-20261016/report-audit.json`；完整成绩见 [三份提交评测](submissions-2026-10-16.md)。

## 新题包

新产物为 `dist/contest-kit-per-mille-20261016/`，从干净实现提交 `bd65f59` release 构建，不覆盖既有题包。压缩包仍为 31 个白名单文件，不增加策略源码、维护者文档或额外工具。

`participant.tar.gz` SHA-256：`ba1f14ce7d3cbf75363dae7d35e2396780923735903f53a937f073b10db4873c`。

仓库外验收位于 `/tmp/fff-per-mille-package-20261016/`：15 条命令、4 场测试比赛、C/Rust 独立绑定、2–8 人计划、续跑与报告重建、回放验证和导出通过。包内 CLI 已输出 0/1000 千分制积分并保留 0/1 原始字段。计时器只查询，没有启动或接管。验收回执副本为 `runs/score-presentation-20261016/package-acceptance.json`。

这是额外的题包接入验收，不是重跑正式测评。旧题包、选手原目录和冻结比赛输入均保留原版本。
