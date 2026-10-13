# 比赛记录与离线播放器 v1

JSON 是记录的数据来源；TXT 从同一 Frame 生成，HTML 导出器读取 JSON。供 LLM 阅读时，每轮 TXT 同时提供 ASCII 棋盘、血量/携旗表、原始/采用动作、调用状态和事件；无需靠一个图符猜测射击目标或伤害。

## 目录

```text
match/
  manifest.json
  map.ron
  map.json
  initial.json
  initial.txt
  frames/
    000001.json
    000001.txt
    ...
  summary.json
  replay.html       # Python 导出器生成
```

文件 UTF-8、LF；ASCII 棋盘和字段名为 ASCII。地图 ID、队伍 ID、棋子 ID、旗 ID 全程稳定。帧号为正式回合号，初始状态为 0。

## 实际 JSON 结构

具体 Rust 类型见 [replay/src/lib.rs](../crates/replay/src/lib.rs) 和 [engine/src/model.rs](../crates/engine/src/model.rs)。

| 文件 | 内容 |
| --- | --- |
| manifest | format_version=1、match_id、engine/rules/RNG 版本、seed、config、map_id、teams、status、last_complete_turn、time_policy、platform、build_profile |
| map.json | 规范化 MapDefinition，含 RON 的 match_limits；map.ron 保留原始来源文本 |
| initial.json | `{format_version:1,state:Snapshot}` |
| 每轮 JSON | `{format_version:1,frame:Frame,calls:[CallReport],call_order:[team_id...]}` |
| summary | complete、turns、scores、outcome、ai_failures、illegal_actions |

`Frame` 含 turn、start、requested、applied、events、end。start 是复活后供 AI 决策的状态；end 包含射击、移动、已有旗拾取、移动后生成与得分结果。requested 保留引擎收到的原始操作；applied 为校验/取消后的操作。同格争抢等合法但失败的移动仍由事件说明，不能仅靠 applied 判断是否真的移动。

`Snapshot` 含 turn、scores、units、flags、sites、rng_state、next_flag_id、outcome。每个 Unit 含 id、position 或 null、hp、carrying 或 null、respawn_at_turn 或 null。旗的位置为 `location:{state:"ground",position:{x,y}}` 或 `location:{state:"carried",unit:{team_id,unit_id}}`。

sites 保留 active_flag_id 或 next_attempt_turn、origin、scheduled_by，用于追踪来源旗和重试任务。完整内部调度及 RNG 用于校验；不会原样传给 AI。每队调用记录包含 status、elapsed_us、init_elapsed_us、restart_count、实际 actions、raw_output 和有界 error。状态区分 ok、timeout、crash、load_error、protocol_error、ai_error。

## 事件与 LLM 明细

每个事件有 event_id、phase、type，其他字段直接展开在事件对象中。阶段包括 start、validation、shoot、move、pickup、flag_spawn、score。阶段内记录顺序用于稳定关联，不赋予同时射击或移动先后优势。

| type | 重要字段 |
| --- | --- |
| shot | shooter、from、target、range_distance、validation、result、hit_unit、damage、blocked_by、line_cells |
| hp_change | unit、before、after、damage、sources（射击事件 ID 列表） |
| death | unit、position、source、respawn_at_turn |
| move | unit、from、target、validation、result、reason、final_position、carrying、target_flags |
| carry_change | unit、before/after、reason、flag_id/source 等上下文 |
| score / flag_removed | 得分前后、交回旗、来源旗点、关联事件；消失原因 home_return |
| flag_spawned | flag_id、site_id、position、schedule、reason |
| flag_spawn_failed | site_id、position、occupant、carrying、reason=occupied_by_carrier、schedule |
| flag_respawn_scheduled | site_id、reason=after_return/retry、origin、source、delay、next_attempt_turn、next_attempt_phase |
| respawn / respawn_blocked | unit、位置/血量或下一重试回合 |

只有目标格可能受到一发伤害，途经棋子不是遮挡物。友伤照常记录实际 hit_unit；自射保留 target、validation=self_target、result=not_executed、damage=0。多发命中先记各发来源，再记一次累计 hp_change，血量下限 0。

射击中死亡导致的移动取消记录 validation=ok、result=cancelled、reason=killed_before_move，保留其原起点和目标；不会计成 AI 提交非法动作。携旗者移入地上旗格属于非法，单独记录 carrying_cannot_enter_flag。

移动后生成失败不创建旗，也不伪造一次旧旗消失。重试调度关联失败事件，保留 initial/after_return 来源，重新抽 5–15 回合。未携旗者占格时，生成与 carry_change(reason=spawn_pickup) 同阶段关联；新旗可能不以地上状态出现在最终快照，事件仍保留。

TXT 排列为 END 棋盘/对象表、AI_CALLS、ACTIONS、EVENTS，最后附完整 START 棋盘/对象表。事件每行包含稳定 ID、phase、type 和紧凑 JSON 字段，适合 LLM 搜索 shooter/target/hp/carrying 或读取某个回合，无需运行程序。

图例：`#` 墙、`.` 地面、`0`–`7` 出生区、`o` 旗点、`*` 地上旗、`A`–`X` 棋子（team_id*3+unit_id）。棋子覆盖地上旗及底层地形，明细保留被遮盖内容。列号用多行十进制位显示，避免 10 占两格。

## 写入与校验

先写临时文件并同步，再原子替换对应 JSON/TXT；一对文件写完才推进 manifest.last_complete_turn。正常写 summary 后 status=complete；中断保持 in_progress，可读取已完整提交前缀，未提交尾文件不算有效帧。

```sh
target/release/fff-runner verify runs/my-match
```

验证器校验版本、路径/大小、地图与原始 RON、初始种子、逐轮调用与动作；重新执行规则引擎，比对完整状态、事件、JSON/TXT 和最终统计。它不加载原 AI，不要求超时再次发生。缺帧、篡改、目录逃逸和文本不一致均报错。

## 导出与播放

```sh
python3 viewer/export.py runs/my-match
# 或指定另一位置
python3 viewer/export.py runs/my-match --out /tmp/my-replay.html
```

导出器仅依赖 Python 标准库，做结构校验并将数据安全嵌入一个 HTML。完整规则一致性由上述 Rust 验证器负责。名称/事件通过文本渲染，嵌入 JSON 转义 script 结束字符；64 位种子与 RNG 元数据保留十进制文本，避免 JavaScript 精度损失。

支持播放/暂停、速度、前后、滑块、指定回合、START/END、比分/血量/携旗、射击路径和可展开事件。射击线使用记录中的移动前坐标，生成事件显示在移动之后的结束局面中。支持 2–8 队和不完整记录提示。

当前导出上限为 25000 帧、单文件 16MiB、总输入 512MiB；超限明确报错。HTML 全部数据内嵌，不需要服务、网络或 AI 库。浏览器检查命令见 README。
