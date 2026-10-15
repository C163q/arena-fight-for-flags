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
  replay.html       # Python 导出器生成的自包含播放器
  replay.json       # Python 导出器生成的单个数据文件
```

文件 UTF-8、LF；ASCII 棋盘和字段名为 ASCII。地图 ID、队伍 ID、棋子 ID、旗 ID 全程稳定。帧号为正式回合号，初始状态为 0。

## 实际 JSON 结构

具体 Rust 类型见 [replay/src/lib.rs](../../crates/replay/src/lib.rs) 和 [engine/src/model.rs](../../crates/engine/src/model.rs)。

| 文件 | 内容 |
| --- | --- |
| manifest | format_version=1、match_id、engine/rules/RNG 版本、seed、config、map_id、teams、status、last_complete_turn、time_policy、platform、build_profile |
| map.json | 规范化 MapDefinition，含 RON 的 match_limits；map.ron 保留原始来源文本 |
| initial.json | `{format_version:1,state:Snapshot}` |
| 每轮 JSON | `{format_version:1,frame:Frame,calls:[CallReport],call_order:[team_id...]}` |
| summary | complete、turns、scores、outcome、ai_failures、illegal_actions |

`Frame` 含 turn、start、requested、applied、events、end。start 是复活后供 AI 决策的状态；end 包含射击、移动、已有旗拾取、移动后生成与得分结果。requested 保留引擎收到的原始操作；applied 为校验/取消后的操作。同格争抢等合法但失败的移动仍由事件说明，不能仅靠 applied 判断是否真的移动。

`Snapshot` 含 turn、scores、units、flags、sites、rng_state、next_flag_id、outcome。每个 Unit 含 id、position 或 null、hp、carrying 或 null、respawn_at_turn 或 null。旗的位置为 `location:{state:"ground",position:{x,y}}` 或 `location:{state:"carried",unit:{team_id,unit_id}}`。

sites 保留 active_flag_id 或 next_attempt_turn、origin、scheduled_by，用于追踪来源旗和重试任务。完整内部调度及 RNG 用于校验；不会原样传给 AI。teams 中记录每队 ai_seed（旧记录允许缺省），用于重现随机策略；它独立于引擎 seed。每队调用记录包含 status、elapsed_us、init_elapsed_us、restart_count、实际 actions、raw_output 和有界 error。状态区分 ok、timeout、crash、load_error、protocol_error、ai_error。

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

验证器校验版本、路径/大小、地图与原始 RON、初始种子、逐轮调用与动作；成功调用必须有合法原始 ABI 输出，解码结果与提交动作一致；重新执行规则引擎，比对完整状态、事件、JSON/TXT 和最终统计。它不加载原 AI，不要求超时再次发生。缺帧、篡改、目录逃逸和文本不一致均报错。

## 导出与播放

```sh
python3 viewer/export.py runs/my-match
# 只导出单个数据文件，供通用页面载入
python3 viewer/export.py runs/my-match --format json
# 指定另一位置；默认同时生成 my-replay.html 与 my-replay.json
python3 viewer/export.py runs/my-match --out /tmp/my-replay.html
# 仅生成自包含 HTML
python3 viewer/export.py runs/my-match --format html
```

直接用浏览器打开 [通用播放器](../../viewer/index.html)，将 `replay.json` 拖入页面，或点击“打开回放”。同一页面可反复打开不同比赛，不需要服务器、网络或 AI 库。通用页面与同目录的 `player.css`、`player.js` 配套使用；分享单个文件时用自包含 `replay.html`，它也支持再载入其他比赛。已有比赛目录重新导出即可，无需重新运行比赛。

数据包顶层为 `{bundle_format:"fff-replay",bundle_version:1,manifest,map,initial,records,summary}`，其中 initial 是初始 Snapshot，records 是按回合升序的完整 JSON 记录，summary 在未完成比赛中为 null。它是播放交换格式，不改变比赛目录原有 format_version=1，也不取代逐轮 ASCII 和 Rust 校验所需的原始文件。64 位 seed、AI seed、rng_state 以十进制字符串保存，避免 JavaScript 精度损失；JSON 不包含页面代码。

导出器仅依赖 Python 标准库，校验地图标记、状态中的棋子/旗/旗点来源/终局、调用元数据与播放器消费的事件字段；错误包含文件和字段路径。页面在切换比赛前再次检查数据包版本、地图、帧与嵌套状态/事件。损坏文件显示错误并保留已有比赛，异步选择只采用最后一次请求。完整规则一致性仍由 Rust 验证器负责。名称/事件通过文本渲染，HTML 嵌入 JSON 转义 script 结束字符。

支持播放/暂停、速度、前后、滑块、指定回合、START/END、比分/携旗、射击路径和可展开事件。桌面棋盘和侧栏限制在视口内，比分两列紧凑排列，事件/棋子/AI 信息通过标签页切换并独立滚动。受伤的存活棋子头顶显示三格血条，满血时隐藏；悬停或点击棋子查看完整状态。死亡棋子的复活信息保留在“棋子”标签中。

棋盘支持缩放按钮、滚轮缩放、拖动平移、“适配”和全屏。缩放范围 100%–1200%，切换回合/阶段保留视野，加载新比赛重置视野和播放进度；移动端用按钮缩放、单指拖动，布局改为上下排列。射击线使用记录中的移动前坐标，生成事件显示在结束局面中。支持 2–8 队和不完整记录提示。

当前导出上限为 25000 帧、单个源文件 16MiB、总输入 512MiB；浏览器数据包限制 512MiB。超限明确报错。浏览器检查命令见 README。
