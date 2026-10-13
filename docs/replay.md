# 比赛记录与播放器草案

目的：每场比赛留下一个无需 AI 二进制即可检查的文件夹，同时服务 LLM 分析、规则验证和人类观看。文件格式版本与 AI ABI 版本独立。

用户已明确需要记录射击、血量与携旗。这里选择 **JSON 保存完整状态与事件，逐回合 TXT 保存 ASCII 棋盘和固定字段文字明细**。JSON 是唯一的数据来源，TXT 与 HTML 都由其生成，避免分别维护三套记录。下面的字段和排版是设计契约草案，尚无实际记录器。

## 候选目录

```text
match-<id>/
  manifest.json
  map.ron
  map.json
  initial.json
  initial.txt
  frames/
    000001.json
    000001.txt
    000002.json
    000002.txt
    ...
  summary.json
  replay.html          # 导出器生成；不是裁判运行的必要产物
```

所有文本 UTF-8、换行 LF；ASCII 棋盘和固定字段仅使用 ASCII 字符。相对路径禁止向目录外跳转；回放导出器不执行目录内脚本或加载 AI 库。

`initial` 是编号 0 的初始状态。每个正式回合文件同时描述开始状态、实际采用动作、事件与结束状态；`.txt` 中主要棋盘为结束状态，随后附完整 START 状态。最大 500 回合的推荐配置下，逐帧完整快照比依赖增量链更易检查和定位故障。

## 结构化记录

| 文件 | 必需内容 |
| --- | --- |
| `manifest.json` | 格式版本、比赛 ID、引擎版本、规则版本、完整配置、队伍与 AI 名称、库产物摘要、种子、RNG 算法版本、串行调用政策/每队独立计时边界、环境信息、记录状态、实际最后完整回合 |
| `map.ron` | 运行时读取的原始地图文件，供审阅和保留资产来源 |
| `map.json` | 宽高、地形、出生区、旗点，足够独立重建地图 |
| `initial.json` | 初始完整状态、开局随机选中的立即生成旗点/旗帜、其余旗点的首次调度、比分及所有棋子 |
| `frames/NNNNNN.json` | 回合号、开始状态、实际 AI 调用顺序及每队独立耗时/响应状态、收到的有效提交、归一化后动作、事件序列、结束状态 |
| `summary.json` | 是否完整结束、终局原因、胜者/平局、比分、总回合、各队超时/崩溃/非法动作次数 |

每队响应状态区分 `ok`、`timeout`、`crash`、`load_error`、`protocol_error`、`ai_error`。记录耗时微秒和降级原因；未完整收到的原始数据不作为有效提交，必要时只保存有界诊断文本。棋子动作另记如 `out_of_bounds`、`carrying_cannot_shoot` 等校验结果。

完整内部状态应保存棋子、旗帜及未来刷新/复活调度，供引擎验证；供 AI 的 observation 不包含未来刷新或 RNG 内部信息。导出器只读取记录，不让 AI 接触记录写入目录。

每个旗点还记录关联的存活旗 ID，或交回消失后安排的下一次刷新回合；关联旗可能在原格、被携带或掉落在其他格，不能仅从旗点当前图符推断其能否重刷。首次生成调度与正常交回后的调度分别标注，数据中没有旗帜 TTL 或自动消失事件。

开局记录数量公式 `max(1,(N+1)/3)`、整数除法约定、实际选中数量及旗点 ID 列表。t=0 选中旗点的旗写入 initial.json/initial.txt，未选中旗点记录各自 5–15 回合的首次调度；不能遗漏立即生成的旗，也不能给它们伪造交回消失事件。具体未来调度仅在完整回放内部数据中保存。

manifest 保存本场 `flag_respawn_min_turns`、`flag_respawn_max_turns` 和分布，当前默认分别为 5、15 与整数均匀随机。每次调度事件记录实际抽取的 d 与下一刷新回合；读取旧回放使用其中的配置，不使用将来版本可能调整后的默认值。

事件类型至少包括刷新、复活/出生阻塞、射击、命中、死亡、移动成功/失败、拾旗、掉旗、得分与 AI 失败。事件包含阶段和稳定对象 ID，按阶段及明确顺序记录，不能靠日志产生先后来解释同时行动。

## 射击、血量与携旗事件

每个事件有 `event_id`、`phase` 和 `type`；棋子引用始终是 `(team_id,unit_id)`，文字符号只是显示别名。建议同类对象按稳定 ID 排序，事件 ID 作为同帧内关联键，不暗示动作先后。

| 事件 | 必需信息 |
| --- | --- |
| `shot` | 射手、射击开始位置、指定目标坐标、曼哈顿距离、合法性结果、实际执行结果、命中对象/伤害或遮挡物坐标 |
| `hp_change` | 棋子、旧血量、新血量、总伤害、来源射击事件 ID；复活恢复另记原因 |
| `death` | 棋子、死亡位置、引发死亡的血量变化事件 ID、计划复活回合 |
| `move` | 棋子、原位置、目标坐标、合法性/成败原因、最终位置；因携旗移入旗格失败时附携带旗 ID 与目标格地上旗 ID 列表 |
| `carry_change` | 棋子、旧旗 ID/无旗、新旗 ID/无旗、原因、旗帜当前位置/携带者及关联事件 |
| `score` | 队伍、得分前后值、交回的旗 ID、交旗棋子 |
| `flag_removed` | 交回消失的旗 ID、来源旗点、交旗棋子、得分事件 ID；当前原因只能是 `home_return` |
| `flag_respawn_scheduled` | 来源旗点、调度原因 `initial/after_return/retry`、原始任务来源、触发事件 ID、当前回合、抽取延迟与下一尝试回合；首次任务没有上一面消失旗，相关字段为空 |
| `flag_spawned` | 新旗 ID、来源旗点、生成坐标、对应调度事件 ID；开局立即生成标记 `initial_immediate`，调度引用为空 |
| `flag_spawn_failed` | 旗点、尝试坐标、移动后占格棋子与携带旗 ID、原因 `occupied_by_carrier`、本次调度引用；不分配新旗 ID |

`shot.validation` 建议区分 `ok`、`out_of_bounds`、`out_of_range`、`self_target`、`carrying_cannot_shoot`、`dead_unit` 等；`shot.result` 区分 `not_executed`、`blocked`、`miss`、`hit`。合法但被墙挡住不是非法动作；落空不是命中；非法射击保留原始目标和原因，采用动作另记为 Wait。故障时没有收到完整提交，不编造射击事件。

友军命中按普通 `hit` 记录实际 `hit_unit`、1 点伤害及血量变化；射手和受害者可以同队，但不能是同一棋子。目标等于射手自身坐标时记录 `validation=self_target, result=not_executed, hit_unit=null, damage=0`，采用动作是 Wait，不生成有效弹道或血量变化。TXT 明确显示受害者队伍，播放器应标注友伤，不能把同队命中隐藏。

对于每次合法射击，记录用于遮挡检查的格序列 `line_cells` 和首个遮挡物 `blocked_by`，便于解释斜线遮挡；序列仅在规则固定后由引擎给出，渲染器不自行猜测。棋子不挡弹，`blocked_by` 只能表示障碍或无障碍，不能引用途中棋子。仅 `hit_unit` 可能受到该发伤害，它必须位于指定目标格；轨迹途经棋子不会产生伤害事件。

携旗者死亡时，用 `carry_change(reason=death_drop)` 记录解除携旗、原旗 ID 与死亡格的地上旗状态。若另一携旗者试图移入该格，其 `move` 事件记录 `validation=carrying_cannot_enter_flag, result=not_executed`，原位置与最终位置相同，并关联目标格旗 ID。该校验在射击及掉旗之后发生，不能因 AI 的 START 观测里尚未出现这面地上旗就漏记原因。

JSON 保留原始移动提交，最终采用动作按校验变成 Wait；TXT 将这类移动与同格争抢失败分开说明，播放器显示失败目标格及旗帜标记。新掉旗始终使用原 flag ID，不另造一面旗，防止回放出现重复旗帜。

交回时记录解除携旗、得分、`flag_removed(reason=home_return)` 与来源旗点的下一次调度，使用事件 ID 关联。拾取和掉落不能产生 `flag_removed` 或新的刷新调度；一面旗无论在地上停留多少轮都保留同一 ID。TXT 附 `FLAG_LIFECYCLE` 明细，播放器区分空旗点仍关联在外旗帜与正在等待生成的旗点。

正式回合的 `flag_spawned`、`flag_spawn_failed` 及对应即时拾取事件都标记为移动后的 `flag_spawn` 阶段。旗点空闲时新旗落地；未携旗者占据时记录生成，再记录同阶段 `carry_change(reason=spawn_pickup)` 关联新旗与生成事件。此类新旗可能没有作为地上旗出现在最终快照，事件仍必须完整保留。

携旗者占格则记录 `flag_spawn_failed`，随后 `flag_respawn_scheduled(reason=retry)` 关联失败事件，重新抽取 5–15 回合；下一尝试位于失败回合 t+d 的移动后阶段。保留初始生成或交回后生成的原始任务来源，不伪造得分或旗帜消失。TXT 显示尝试回合、占格者/携旗状态、失败原因、重试延迟与新回合，HTML 同样展示。

以下是独立排版片段，分别位于第 25、34 回合 TXT，不是对后文第 13 回合示例的完整续写：

```text
TURN 25 PHASE FLAG_SPAWN
t25.spawn_failed.0 point=site0 pos=(3,4) occupant=team1.unit0 carry=flag8 result=failed reason=occupied_by_carrier
t25.retry.0 point=site0 reason=retry source=t25.spawn_failed.0 delay=9 next_attempt_turn=34 next_attempt_phase=flag_spawn
TURN 34 PHASE FLAG_SPAWN
t34.spawn.0 point=site0 pos=(3,4) flag=flag12 schedule=t25.retry.0 result=success
t34.carry.0 unit=team0.unit0 carry=none->flag12 reason=spawn_pickup source=t34.spawn.0
```

所有射击先记录命中和各发伤害，再记录每个受伤棋子唯一的累计 `hp_change`，不伪装成依次扣血。完整 START/END 状态仍列出每个棋子的血量和携旗，包含没有变化的棋子；事件用于解释变化，不能替代状态快照。

下面是接续后文第 12 回合状态的第 13 回合**事件片段**：D、E 同时瞄准携旗的 B，B 本回合等待，从 2 血被两发打到 0，旗帜按已确认规则掉在死亡格。`line_cells`、完整状态和其他动作省略，不能将此片段当成完整回放帧。

```json
{
  "turn": 13,
  "events": [
    {
      "event_id": "t13.shot.0", "phase": "shoot", "type": "shot",
      "shooter": {"team_id": 1, "unit_id": 0},
      "from": {"x": 3, "y": 6}, "target": {"x": 4, "y": 3},
      "range_distance": 4, "validation": "ok", "result": "hit",
      "hit_unit": {"team_id": 0, "unit_id": 1}, "damage": 1,
      "blocked_by": null
    },
    {
      "event_id": "t13.shot.1", "phase": "shoot", "type": "shot",
      "shooter": {"team_id": 1, "unit_id": 1},
      "from": {"x": 6, "y": 6}, "target": {"x": 4, "y": 3},
      "range_distance": 5, "validation": "ok", "result": "hit",
      "hit_unit": {"team_id": 0, "unit_id": 1}, "damage": 1,
      "blocked_by": null
    },
    {
      "event_id": "t13.hp.0", "phase": "shoot", "type": "hp_change",
      "unit": {"team_id": 0, "unit_id": 1},
      "before": 2, "damage": 2, "after": 0,
      "sources": ["t13.shot.0", "t13.shot.1"]
    },
    {
      "event_id": "t13.death.0", "phase": "shoot", "type": "death",
      "unit": {"team_id": 0, "unit_id": 1},
      "position": {"x": 4, "y": 3}, "source": "t13.hp.0",
      "respawn_at_turn": 24
    },
    {
      "event_id": "t13.carry.0", "phase": "shoot", "type": "carry_change",
      "unit": {"team_id": 0, "unit_id": 1},
      "before": 7, "after": null, "reason": "death_drop",
      "flag_id": 7, "ground": {"x": 4, "y": 3},
      "source": "t13.death.0"
    }
  ]
}
```

`respawn_at_turn=24` 使用已确认的 D09 边界：第 13 回合死亡，完整缺席第 14–23 回合，第 24 回合开始复活。若出生区满员，如何处理仍见 D09 补充。同一事件片段在 TXT 中生成以下明细，保留 ID 以便 LLM 对照 JSON：

```text
SHOTS
t13.shot.0 shooter=team1.unit0(D) from=(3,6) target=(4,3) distance=4 validation=ok result=hit victim=team0.unit1(B) damage=1
t13.shot.1 shooter=team1.unit1(E) from=(6,6) target=(4,3) distance=5 validation=ok result=hit victim=team0.unit1(B) damage=1
HP_CHANGES
t13.hp.0 unit=team0.unit1(B) hp=2->0 damage=2 sources=t13.shot.0,t13.shot.1
DEATHS
t13.death.0 unit=team0.unit1(B) position=(4,3) respawn_at_turn=24
CARRY_CHANGES
t13.carry.0 unit=team0.unit1(B) carry=flag7->none reason=death_drop ground=(4,3)
```

TXT 各节使用稳定字段，空节写 `none`，每回合自带图例和对象标识；LLM 可只读取所需回合，或按 `shooter=`、`target=`、`hp=`、`carry=` 搜索。时间、位置、血量等不用自然语言猜测，较复杂的原因再附简短说明。

## ASCII 输出

ASCII 与同文件的文字明细必须能独立阅读：每帧包含比赛/回合编号、阶段、坐标方向、图例、比分、完整棋盘、所有棋子信息、当前旗帜清单、原始/采用动作、AI 状态与关键事件。每格一个字符，棋盘含行列编号；宽度超过个位数时保持列对齐。不把血量、携旗和射击目标硬塞进一个棋盘字符。

建议符号：`#` 障碍，`.` 地面，`0`–`7` 出生区所属队伍，`o` 空旗点，`*` 地上旗；棋子符号为 `A`–`X`，索引为 `team_id*3+unit_id`，覆盖最多 24 个棋子。例如队伍 0 为 A/B/C，队伍 1 为 D/E/F，队伍 7 为 V/W/X。渲染优先级：棋子 > 地上旗 > 出生区/旗点 > 地面。被覆盖的地形、旗帜与携旗状态必须出现在下方明细中，不能仅靠一个字符表达全部状态。

以下为 9×9 格式示例，**不是首版正式地图或金标准规则用例**：

```text
MATCH example FORMAT 1
TURN 12 PHASE END
COORD x=right y=down ORIGIN top-left
SCORE team0=1 team1=0
LEGEND #=wall .=floor 0/1=home o=flag-site *=ground-flag
       A/B/C=team0.unit0/1/2 D/E/F=team1.unit0/1/2

    012345678
  0 #########
  1 #000o#..#
  2 #0A0.#..#
  3 #000B...#
  4 #..o*...#
  5 #....111#
  6 #..D.1E1#
  7 #....111#
  8 #########

UNITS
team0 unit0 A alive pos=(2,2) hp=3 carry=none
team0 unit1 B alive pos=(4,3) hp=2 carry=flag7
team0 unit2 C dead pos=none hp=0 respawn_at_turn=17
team1 unit0 D alive pos=(3,6) hp=3 carry=none
team1 unit1 E alive pos=(6,6) hp=1 carry=none
team1 unit2 F dead pos=none hp=0 respawn_at_turn=19
FLAG_SITES site0=(3,4) site1=(4,1)
FLAGS
flag7 source=site0 carried_by=team0.unit1
flag8 source=site1 ground=(4,4)
```

正式 ASCII 还应包含本回合提交、归一化动作、AI 状态及事件；示例只展示状态块形状。不能遗漏死亡棋子，携旗情况也必须有文字字段。空旗点列表与被覆盖地形从静态地图读取。超过 9 列时使用多行列号或固定宽度编号，不能将 10 写成两格。

同一回合 `.txt` 还应附上开始阶段复活列表、供 AI 决策的 `PHASE START` 棋盘和对象明细，以及移动后的 `FLAG_SPAWN` 生成/失败/重试明细。AI 的开始状态不包含本回合稍后才生成的旗；结束状态包含生成与即时携旗结果，不能将这些变化提前放进 START。

## 写入完整性

先写临时文件，再原子替换对应 JSON/TXT 成品；只有一对文件都就绪后才更新 manifest 的最后完整回合。初始 manifest 标为 `in_progress`，正常结束写 summary 并标为 `complete`。中断的目录仍可播放连续的完整前缀，UI 必须标明记录未完成。

读取器校验版本、地图尺寸、回合连续性、对象 ID、必要字段和安全的大小上限。缺失帧、损坏 JSON、JSON/TXT 不一致应报出具体文件与原因，不悄悄猜测局面。

## 人类播放器提案（D13）

额外工具使用 Python 标准库读取目录，将数据安全嵌入 HTML 模板，生成一个可离线打开的 `replay.html`。无需后端、联网、AI 库或编译 Rust 即可观看；这是本地回放导出，不要求部署站点。

最低功能：

- 播放/暂停、上一回合/下一回合、回合滑块和输入框跳转；允许观看初始状态 0。
- 速度选择，播放到最后自动停止；跳转后正确更新全部信息。
- 棋盘上的障碍、出生区、旗点、棋子队伍、血量和携旗标记。
- 2–8 队的独立颜色及文字/符号标识；按实际地图尺寸缩放，不硬编码双人布局。
- 比分、回合号、棋子明细、死亡复活状态和本回合事件。
- 切换本回合 START/END，默认 END；事件标记帮助看懂先射击后移动。
- 射击阶段叠加从射手位置到指定格的直线与目标标记；区分非法未执行、遮挡、落空和命中。途经棋子不播放受伤效果，也不截断射击线。
- 展示每个受伤棋子的血量前后值、命中来源，以及拾旗/掉旗/交旗后的携旗变化；同阶段射击以同时结算呈现，不让动画顺序改变含义。
- 在移动动画之后展示到期旗点生成：未携旗者即时拿旗，携旗者占格则失败并显示重试安排；开局立即生成作为初始状态显示。
- AI 超时/崩溃提示、终局结果或未完成回放提示。

把 AI 名称、事件文本等作为文本渲染，不能作为 HTML 执行。嵌入 JSON 时处理闭合 script 等特殊内容，避免名称把数据块变成脚本。未来若回放很大，再评估本地服务和按需加载。

## 验证模式

规则验证器读取 initial、各回合实际采用动作以及完整配置，重新执行引擎，比较开始状态、事件和结束状态。来自原始提交的非法射击诊断另外按动作校验重建，不能在动作归一化为 Wait 后丢失原始目标。独立检查 ASCII 与文字事件明细是否对应同一 JSON 数据。验证不重新调用 AI，也不要求墙钟超时再次发生。

检查每发伤害只能关联指定格的目标、所有血量变化与来源伤害总和一致、血量不为负、携旗变更与地上旗/携带者状态不重复；同时验证 JSON 和 TXT 中的射手/目标坐标一致。射击层从记录的 from/target/line_cells 渲染，不从结束位置推算射手位置。

旗帜验证还需检查：每旗点最多一面未消失关联旗；新交回任务必须关联此前的交回消失事件，失败重试必须关联前次失败事件并保留任务来源；拾取/掉落不开始刷新计时；不存在自动过期；旗生成于来源旗点，而不是死亡格。除 t=0 初始化外，尝试必须在移动后发生；未携旗占格立即携旗、已携旗占格不创建旗并重试。随机延迟与下一尝试回合符合本场配置。

记录中的实际故障导致的等待必须作为输入保留。重放相同动作得出相同状态是引擎确定性保证；重新运行同一 AI 是否赶上 50ms 是另一项运行实验。
