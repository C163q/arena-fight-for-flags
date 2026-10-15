# AI C ABI v1

已实现于 [Rust 类型](../../crates/ai-abi/src/lib.rs) 和 [C 头文件](../../include/ctf_ai.h)，首版支持 Linux 64 位。ABI v1 的结构布局以这两份文件为准，不兼容变更提升版本。进程内 ABI 与 worker JSON 通信是不同边界，裸指针不会离开 worker。

## 导出与生命周期

```c
uint32_t ctf_abi_version(void);
int32_t ctf_create(const CtfInit *init, void **context_out);
int32_t ctf_decide(void *context, const CtfObservation *observation,
                   CtfTeamAction *output);
void ctf_destroy(void *context);
```

每队独立 worker，正常跨回合保留 context。`ctf_create` 返回 0 表示成功，无状态实现允许空 context；非零为失败。`ctf_decide` 每队每回合调用一次，输出己方三个棋子操作；返回非零忽略整份输出。正常退出调用 destroy；强制终止不保证析构。Rust 不得让 panic unwind 穿过 ABI，宏包装会捕获普通 unwind 并返回 2，abort 由进程隔离处理。

输入/输出缓冲区归 worker，输入只读且只在当前调用期间有效。AI 可复制数据，不能保存输入指针或跨 allocator 释放内存。context 由 AI 创建并自行销毁，不依赖其他队伍的库实例。

## CtfInit

| 字段 | 含义 |
| --- | --- |
| `abi_version`, `struct_size` | 版本 1、实际结构大小 |
| `team_id`, `team_count` | 己方 0 起始 ID、2–8 队 |
| `width`, `height` | 地图运行时尺寸，9–128 |
| `max_turns`, `target_score` | RON `match_limits`，不是 CLI 覆盖值 |
| `flag_respawn_min_turns`, `flag_respawn_max_turns` | 本场生成等待范围，默认 5、15，两端包含、整数均匀随机 |
| `first_turn`, `restart_count` | 本次初始化将服务的回合、此前启动失败/重启次数 |
| `seed` | 己方独立 64 位种子，默认来自 OS 随机源；由 `--ai-seed` 可显式指定，不从引擎种子派生 |
| `decision_budget_us` | 50000 |
| `initial_flag_count` | `max(1,(N+1)/3)`，整数除法 |
| `max_hp`, `shot_damage`, `shot_range` | 3、1、5；射程度量固定为曼哈顿 |
| `respawn_absent_turns` | 10，死亡 t 后在 t+11 开始复活 |

固定玩法还包括无自然回血、友伤开启、自射禁止、仅目标格受伤、途中棋子不挡弹、携旗不能射击或移入地上旗格。这些不由 AI 改写。

## CtfObservation

顶层含版本/大小、turn、team_id、width/height、team_count 及各数组元素数量。所有数组均为借用的只读指针，字段类型和顺序见头文件。

| 数组 | 内容 |
| --- | --- |
| `cells` | `cell_count=width*height`，行主序 `y*width+x`；0 地面、1 障碍 |
| `units` | `unit_count=team_count*3`，按 team_id/unit_id 排序；含 alive、hp、x/y、carrying、flag_id、respawn_at_turn |
| `flags` | 所有当前旗；state=0 为地上、1 为携带；含 id、site_id、位置/携带者 |
| `homes` | 每队一条 3×3 出生区，长度 team_count |
| `sites` | 静态旗点 ID 与坐标，长度 site_count |
| `scores` | 每队当前得分，长度 team_count |

死亡棋子 alive=0、hp=0、x=y=-1、无携旗；复活时刻为绝对回合号。未携旗时 flag_id=0，仍应以 carrying 判断。地上旗的 carrier_team/carrier_unit 为 UINT32_MAX；携带旗的位置随携带者报告。旗列表可能为空，数量为 0 时不读取指针。

全图、所有队伍位置/血量/携旗、比分与当前旗帜公开；未来刷新时刻、引擎 RNG、其他 AI 内存和其他队伍本轮提交不公开。本回合移动后的新旗与即时携旗只进入结束状态及下一轮观测。

## CtfTeamAction

顶层版本/大小加固定三个槽位，槽位 unit_id 必须依次 0、1、2。每槽含 `unit_id,kind,direction,target_x,target_y`，死亡者也写 Wait。

| 类型 | 编码 | 使用字段 |
| --- | --- | --- |
| 等待 | kind=0 | unit_id |
| 移动 | kind=1 | direction：0 上、1 下、2 左、3 右 |
| 射击 | kind=2 | target_x/target_y，必须在图内、非自身格、曼哈顿距离 1–5 |

建议未使用字段置零；它们不改变对应动作语义。worker 在调用前将版本和槽位设为无效哨兵，AI 必须完整填写。版本/大小/槽位错误或非零返回导致整队 Wait；正常外层结果中的单个未知动作、非法方向或目标仅使对应棋子等待并记录原因。

射击/移动的最终合法性归引擎。射击后死亡取消移动，记录 `killed_before_move`，不把合法提交算成非法动作。射击掉旗可能使携旗者的目标格变为非法，记录 `carrying_cannot_enter_flag`；这种动态结果不能仅凭 AI 开始观测预先判定。

## 50ms 与执行隔离

队伍依次调用，各自窗口从恢复/派发到完整响应校验，包含 IPC、调度与 JSON 编解码；等待其他队伍不扣预算。初始化/重启限 1000ms，退出限 100ms，worker 地址空间限 256MiB。调用窗口外暂停进程组，上一队故障清理完成才切换。

超时强制终止对应组，本轮整队等待，下一轮冷启动；context 丢失，restart_count 增加。后台计算不得延续到函数返回之后。此机制提供运行隔离，不是恶意本地代码沙箱；系统其他进程仍可能影响墙钟结果。

## Rust 作者入口

```rust
use fff_ai_abi::{CtfTeamAction, ObservationView};
fn strategy(_view: &ObservationView<'_>) -> CtfTeamAction {
    CtfTeamAction::waits()
}
fff_ai_abi::export_ai!(strategy);
```

以 [bots/wait](../../bots/wait/src/lib.rs) 的 Cargo 设置建立 cdylib，依赖公开 `fff-ai-abi`。公共 `fff-ai-sdk` 包含 BFS/参考策略，仅依赖 ABI，不连接引擎私有状态。需要私有记忆时自行实现四个导出函数，遵守相同布局与生命周期。
