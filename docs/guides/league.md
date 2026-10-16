# 多 AI、多地图测评

`scripts/league.py` 自动从候选 AI 池组队、按地图容量补位，生成每地图排行榜与各地图等权总榜。原 [固定名单工具](tournament.md) 继续保留，新旧工具复用执行器。

## 使用

```sh
cargo build --release --workspace
# 编辑 participants、maps 和 filler；路径相对配置文件。
python3 scripts/league.py plan --config config/league.example.json --out runs/league-new
# plan 只校验、冻结输入并显示场数，不运行 AI；检查规模后再执行。
python3 scripts/league.py run runs/league-new
```

配置 version=2，包含 runner、非空 participants（id/name/library）、非空 maps（id/map）、可选 filler（name/library），repeats 默认 1。完整格式见 [示例配置](../../config/league.example.json)。候选 ID、地图条目 ID 分别唯一，为 1–64 个 ASCII 字母/数字/下划线/连字符，首字符为字母或数字。name 可省略，同库可定义不同候选 ID 并分别统计。

plan 调用 `fff-runner inspect-map PATH` 完整校验冻结后的 RON 并读取人数，不重复填写容量；旧 runner 不支持该命令时重新构建。人数不足时所有候选同场，剩余席位使用 filler 库的独立副本，各有独立 AI seed；人数等于容量时全员同场；超额时每场选容量个不同候选，不填充。所有选定地图均不需填充时可省略 filler。

## 赛程与规模

每地图的完整重复块严格保证候选出场次数、各出生位次数、每对候选同场次数及各不同有序出生位对次数相同。生成后遍历实际赛程重新计数，不用近似随机抽样替代。优先采用有限域仿射/射影置换、几何/循环组合；通用兜底为完整子集加换位。不承诺最少场数、三方以上组合均衡或地图公平。

重点优化 1–16 候选；更大名单仅在可构造且场数允许时接受，不保证紧凑。下面为每地图、每重复块的场数；多个地图与 repeats 要相加。示例三候选的 2/4/8 人图共 74 场。16 候选在 8 人图每块 240 场，每队出场 120 次、每位置 15 次，每对同场 56 次、每有序位置对 1 次。

| 候选数 | 2 人图 | 3 人图 | 4 人图 | 5 人图 | 6 人图 | 7 人图 | 8 人图 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2 | 6 | 12 | 20 | 60 | 42 | 56 |
| 2 | 2 | 6 | 12 | 20 | 60 | 42 | 56 |
| 3 | 6 | 6 | 12 | 20 | 60 | 42 | 56 |
| 4 | 12 | 12 | 12 | 20 | 60 | 42 | 56 |
| 5 | 20 | 20 | 20 | 20 | 60 | 42 | 56 |
| 6 | 30 | 60 | 60 | 60 | 60 | 42 | 56 |
| 7 | 42 | 42 | 42 | 42 | 42 | 42 | 56 |
| 8 | 56 | 56 | 56 | 56 | 56 | 56 | 56 |
| 9 | 72 | 72 | 72 | 72 | 72 | 72 | 72 |
| 10 | 90 | 360 | 360 | 360 | 360 | 360 | 360 |
| 11 | 110 | 110 | 110 | 110 | 110 | 110 | 110 |
| 12 | 132 | 660 | 660 | 660 | 660 | 660 | 660 |
| 13 | 156 | 156 | 156 | 156 | 156 | 156 | 156 |
| 14 | 182 | 1092 | 1092 | 1092 | 1092 | 1092 | 1092 |
| 15 | 210 | 210 | 1260 | 1260 | 2100 | 630 | 840 |
| 16 | 240 | 240 | 240 | 240 | 240 | 240 | 240 |

```sh
# 仅选配置中的指定地图；三个完整重复块。
python3 scripts/league.py plan --config config/league.example.json --out runs/league-three --only 8p --repeats 3
# 默认限制 10000 场；可以显式提高，绝不截断均衡块。
python3 scripts/league.py plan --config config/league.example.json --out runs/league-large --match-limit 20000
```

每块独立随机重标记候选和出生位、打乱场次，块内共用引擎 seed，AI seed 随独立队伍身份移动。引擎/AI/赛程三条种子流独立来自 OS。同引擎 seed 不保证行动不同的对局经历相同刷新轨迹。

## 执行与续跑

```sh
python3 scripts/league.py run runs/league-new --max-matches 2
python3 scripts/league.py run runs/league-new
python3 scripts/league.py report runs/league-new
# 并行仅供自测，默认与正式评测固定 1。
python3 scripts/league.py run runs/league-new --jobs 2
```

分段上限限制新启动的场数。不完整块保留明细但不入正式排名。Ctrl+C/SIGTERM 保留现场，续跑重新验证原始回放，不信任统计缓存。地图/AI 主库复制冻结，runner/worker 路径与指纹固定；期间勿替换程序、移动计划或修改冻结输入。其他动态依赖和外部数据未完全冻结，独立进程不等于恶意代码沙箱。记录损坏、输入不符、裁判错误会停止；AI 故障和非法动作按游戏规则计入比赛。

单场各队仍串行，跨场共用旧工具的锁、中断与父进程死亡清理。并行争抢 CPU/内存/磁盘，可能增加墙钟超时、改变成绩，不保证线性加速，也不减少总回放空间。含并行场次（包括未完整块）的报告一直标为自测，串行续跑不清除。正式比较另建低背景负载的串行计划。

先跑两场估算耗时和磁盘量再开始大赛程，repeats=1 也可能数百至数千场。league 面向场外评测，当前未加入参赛题包；选手仍使用题包内固定名单自测器，开发时间包含自测，及时查询计时器。

## 排名与结果

每地图只采用完整且验证通过的块，按实际出场计算 `名次分=(低于自己的对手数+0.5×同分对手数)/(地图人数−1)`。填充对手参与场内比较但不入榜。同主分按平均游戏分、独胜率排序，完全相同并列。两两混战成绩只采用双方同场比赛并附样本量，不能解释为独立 1v1 胜率。

积分采用千分制：未取整名次分乘 1000，四舍五入到整数（半分向上）。报告主积分、出生位积分与 95% 区间统一使用这一尺度；平均夺旗分和各项比率不缩放。排序继续使用未取整值，显示积分相同不代表并列。JSON 顶层 `score_scale=1000`，条目新增 `score`、`score_ci95`，总榜新增 `by_map_score`；原有 `rank_score`、`rank_score_ci95`、`by_map` 保持 0–1，CSV 同时保留 `score` 和 `rank_score`。

总榜各指定地图名次分等权平均，不按场数加权。仅采用同一重复序号下所有指定地图均完整的全图重复组；单图榜可能使用更多完整块。总榜同主分并列，不跨图用原始游戏分破同分；无完整统计单位时显示暂无正式排名。至少五个完整地图块/全图重复组才按该单位配对 bootstrap（2000 次、固定 seed）给描述性 95% 区间，五个仍不保证普适显著性。

输出 report.md、standings.csv、results.json，包含总榜、单图榜、同场胜平负、出生位成绩、调用耗时/故障/超时/非法动作、均衡检查与重复组进度。比赛在 `matches/<场次>/attempt-000/match/`，后续尝试使用递增 attempt；用 `python3 viewer/export.py 比赛目录` 导出回放。

```sh
python3 -m unittest discover -s tests -p 'test_league*.py' -v
python3 tests/league_integration.py --out runs/league-check-new
```

短局验收仅修改私有测试地图，不改变正式资产或用于策略强度结论。依据见 [设计稿](../design/specs/2026-10-16-league-design.md) 与 [实施计划](../plans/2026-10-16-league.md)。
