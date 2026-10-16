# 自动测评机

需要从较大候选名单自动组合、补足地图人数并生成跨地图总榜时，使用 [多 AI、多地图测评](league.md)。本工具继续支持显式固定名单；两者复用执行器，配置和报告口径分别定义。

`scripts/tournament.py` 为每种人数的一组固定 AI 名单安排换位、多种子比赛和统计。它使用正式 runner、C ABI 与串行 worker；每队比赛第 1 回合 250ms、之后每回合 50ms，重启不重新获得首回合额度。比赛之间默认串行执行；`run --jobs N` 可用于并行自测，正式评测固定 `--jobs 1`。

## 使用

先编译所有参赛库及裁判，再编辑 [示例配置](../../config/tournament.example.json)：

```sh
cargo build --release --workspace
python3 scripts/tournament.py plan --config config/tournament.example.json --out runs/tournament-new
python3 scripts/tournament.py run runs/tournament-new
```

`plan` 只复制输入、生成固定赛程并列出场数，不执行 AI。输出目录必须不存在。示例是一个基准 AI 对若干独立贪心 AI 副本，覆盖 2–8 人、正式模式、每种人数 5 个重复块，共 990 场。可将库路径改为自己的 `.so`。

先做小规模筛选：

```sh
python3 scripts/tournament.py plan --config config/tournament.example.json --out runs/quick-new --mode quick --repeats 1
python3 scripts/tournament.py run runs/quick-new

# 仅生成配置中 ID 为 8p 的名单，正式模式一个块为 56 场。
python3 scripts/tournament.py plan --config config/tournament.example.json --out runs/8p-new --only 8p --repeats 1
python3 scripts/tournament.py run runs/8p-new
```

完成后查看输出目录的 `report.md`、`standings.csv` 或 `results.json`。JSON 包含逐场结果、各出生位成绩、混战中的两两比较、调用状态/耗时直方图及赛程覆盖情况。完整比赛和 ASCII 保存在 `matches/<场次>/attempt-000/match/`，报告附相对目录索引；用 `viewer/export.py` 导出所需比赛，不批量复制 HTML。

## 配置格式

```json
{
  "version": 1,
  "runner": "../target/release/fff-runner",
  "mode": "balanced",
  "repeats": 5,
  "ais": [
    {"id": "alpha", "name": "我的 AI", "library": "../target/release/libalpha.so"},
    {"id": "baseline", "name": "基准", "library": "../target/release/libfff_bot_baseline.so"}
  ],
  "lineups": [
    {"id": "duel", "players": 2, "map": "../maps/arena_2p.ron", "ais": ["alpha", "baseline"]}
  ]
}
```

- 配置内相对路径从**配置文件所在目录**解析；命令行路径从当前目录解析。runner 旁必须有 `fff-ai-worker`。复制配置到别处时需相应调整路径。
- `ais` 定义唯一参赛 ID、显示名和库。ID 使用 1–64 个 ASCII 字母、数字、下划线或连字符，首字符为字母或数字。
- `lineups` 定义唯一名单 ID、2–8 的人数、地图和恰好 N 个不同参赛 ID。可以为同种人数提供多个不同名单或地图，结果分别统计。地图合法性与地图人数由正式 runner 在执行时校验。
- 同一个库可以定义多个不同 ID，例如 `baseline_1` 到 `baseline_7`；每个副本是独立队伍，有独立 AI seed，不在统计中合并。同一名单不能重复引用同一个 ID。
- 测评机不从大型 AI 池自动选参赛子集，也不自动补足人数。
- `mode` 默认 `balanced`，`repeats` 默认 5；CLI 的 `--mode`、`--repeats`、`--only` 在计划创建时覆盖或筛选配置。

## 为什么不需要全排列

正式模式采用经过计数校验的置换集合，让每队各出生位次数相同，并让任意两队在所有不同的有序出生位组合中次数相同。它不要求地图对称，出生位按地图 team_id 编号。

| 人数 | 正式模式每块场数 | 每队每位置次数 | 每对队伍每位置对次数 | 快速模式每块场数 |
| --- | --- | --- | --- | --- |
| 2 | 2 | 1 | 1 | 2 |
| 3 | 6 | 2 | 1 | 3 |
| 4 | 12 | 3 | 1 | 4 |
| 5 | 20 | 4 | 1 | 5 |
| 6 | 60 | 10 | 2 | 6 |
| 7 | 42 | 6 | 1 | 7 |
| 8 | 56 | 7 | 1 | 8 |

8 人 balanced 模式 1 块为 56 场、5 块为 280 场；2–8 人各一组，1 块也有 **198 场**、5 块为 **990 场**。快速模式分别为 40 场和 175 场。快速模式每块随机打乱名单后循环轮换，只保证单队位置均衡，不保证两两位置均衡。

每个重复块独立随机重标记参赛 ID 与出生位、打乱执行顺序；同块共用引擎种子，AI seed 跟随参赛 ID 而非出生位。引擎、AI 和赛程随机化分别从独立 OS 随机源初始化，实际种子和完整赛程保存到 `plan.json`。同种子不意味着行动不同的两局会经历完全相同的后续刷新轨迹。

两两均衡不能消除三方以上的组合效应，不等价于全排列，也不保证地图本身公平。结果只适用于指定名单、地图和测试条件。

## 续跑、失败和输入冻结

```sh
# 有意分段执行，只启动至多 10 场新比赛。
python3 scripts/tournament.py run runs/tournament-new --max-matches 10

# 再次执行同一命令即可续跑，不重复已完成比赛。
python3 scripts/tournament.py run runs/tournament-new

# 不运行 AI，重新验证原始记录并生成报告。
python3 scripts/tournament.py report runs/tournament-new
```

Ctrl+C/SIGTERM 中断时终止所有在途 runner/校验进程，保留半场；下次为同一计划场次新建 attempt，使用原种子重打。已经完成但检查点未写完的比赛，验证后直接采用。`checkpoint.json` 只是进度辅助，原始回放才是结果依据。独立启动助手在 exec 前设置 Linux 父进程死亡信号并检查启动竞态：测评机被 SIGKILL 后先终止 runner，再触发既有 worker 父进程清理；恢复时扫描原始目录。

只有全部场次完成并通过 `fff-runner verify` 的重复块进入正式排名；部分块保留逐场结果但不参与排名，报告明确列出进度。`--max-matches` 不会把未完整块冒充为均衡结果。

AI 超时/崩溃和非法动作按游戏规则计入比赛，并分别统计。runner 非零退出、损坏的完整记录、输入不匹配或回放验证失败会停止测评，保留日志，不自动给 AI 判负或换种子重赛；需排查错误并使用新输出目录，不应删改原始比赛来绕过校验。

计划复制地图和 AI 库到 `inputs/`，记录 SHA-256；原库随后变化不会影响冻结副本。runner/worker 使用生成计划时的绝对路径并锁定指纹，执行每场前重新检查，续跑期间不要替换它们或移动输出目录。主库以外的动态依赖、外部数据与系统环境未被完整冻结。独立进程隔离不等于恶意代码沙箱。

输出目录通过 Linux 文件锁排除同时执行/报告，锁描述符继承到 runner/验证进程，直到子进程退出才释放；另一进程或清理中的子进程仍持锁时，`report`/`run` 会提示锁冲突，可待退出后重试。主线程独占检查点与进度输出，每场结束原子更新检查点；正常分段停止或全部完成时生成报告。中断后可执行 `report` 查看已完成块。

## 并行自测与时间成本

```sh
# 最多四场同时运行，默认值为 1。
python3 scripts/tournament.py run runs/quick-new --jobs 4
# 最多启动两场新比赛，不因并发而超出分段上限。
python3 scripts/tournament.py run runs/quick-new --jobs 4 --max-matches 2
# 正式评测固定使用 1，另建正式计划，勿复用并行自测的成绩。
python3 scripts/tournament.py run runs/formal-new --jobs 1
```

`--jobs` 是同时在途的整场比赛上限（包括该场回放校验），接受正整数，默认 **1**。编排线程启动独立裁判进程，单场内各队 AI 仍串行；赛程、换位和种子不变。并发可缩短总等待，但会争抢 **CPU、内存和磁盘**，不保证按并发数线性加速；回放空间总量也不会因并行而减少。尤其墙钟预算不变，CPU 争抢会增加 AI 超时，改变决策、比分和排名。建议从 2 个并发开始，按可用资源调整，避免直接使用逻辑 CPU 总数。

**正式评测使用 `--jobs 1`。** 并行结果只用于自测筛选；性能余量与正式成绩请在低负载串行环境复核。即使 jobs=1，其他系统任务仍可能干扰计时。每场 attempt 和 JSON 记录配置并发上限，Markdown/CSV/JSON 报告列出已采用场次的配置；只要曾采用 jobs>1 的场次，即使后续串行续跑也标为并行自测。旧串行记录按 jobs=1 兼容；标记不是防篡改认证，也不证明所有场次同时运行。

不要将 `repeats=1` 理解为一场比赛：全人数 balanced 仍有 198 场。总时间取决于参赛 AI 和机器，应先跑单场或 `--only 2p --mode quick --repeats 1` 的 **2 场**；按实测每场耗时估算剩余赛程，再选择人数、模式和分段上限。全人数 quick 一块为 35 场。LLM 的 60 分钟包含自测时间，应经常查询 `fff-timer-query`，保留已编译结果，不在截止前启动未经估算的大赛程。Ctrl+C 后可续跑，基础设施错误则停止所有在途任务，保留现场。

### 选择并发数量

自测建议先从 `--jobs 2` 开始，可尝试不超过可用 CPU 核数一半的并发，并根据超时情况调整。已有其他任务或 AI 接近决策时限时，应降低并发；默认及正式评测仍使用 `--jobs 1`。维护者的测量方法、环境与完整数据保留在 [容量实测](../reports/jobs-capacity-2026-10-15.md)。

## 排名口径

每个人数、地图、名单独立排名。主指标为平均归一化名次分：

`(低于自己的对手数 + 0.5 × 与自己同分的对手数) / (N−1)`

得分为 0–1，越大越好；同值依次比较平均得分、独胜率，完全相同保留并列。平均名次对同分取中间名次。独胜和并列第一分别统计，第一积分是并列 k 队各记 1/k 的场均值，不改变游戏结算。

同时报告平均得分、与最高对手分差、各出生位成绩、混战中的两两成绩、AI 故障/超时/非法动作和裁判侧完整调用耗时 P50/P95/P99。超时属于故障的子集；故障和超时率按调用次数计，非法动作率分母为调用次数乘三。

同一重复块内各局相互关联，不作为独立样本。至少五个完整块才计算按块 bootstrap 的描述性 95% 区间：固定统计种子、2000 次重采样，主指标为名次分。少于五块不显示区间。五块仍然较少，区间不能保证普遍显著性，也不会自动判定某个 AI 已可靠优于另一个。

## 验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tests/tournament_integration.py --out runs/tournament-check-new
python3 tests/tournament_parent_cleanup.py --out runs/tournament-kill-check-new
```

实战验收使用正式 release runner，覆盖 2–8 队快速模式共 35 场、8 队正式模式 56 场，验证真实中断与恢复、复用已完成场次、记录损坏/输入变化拒绝和每场回放。验收同库自战证明工具流程，不用于断言 AI 强度排名。

历史验收结果、独立审查及修复证据见 [测评机审查记录](../reviews/tournament-review-2026-10-13.md)。
