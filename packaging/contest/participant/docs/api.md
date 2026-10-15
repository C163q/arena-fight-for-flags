# C ABI v1：完整接入说明

声明以 [include/ctf_ai.h](../include/ctf_ai.h) 为准。Linux x86_64 GNU 环境、普通 C 对齐，不使用 packed。结构体字段必须按头文件顺序，下面表格也按声明顺序列出；分组行的字段均使用该行类型。队伍 ID 从 0 开始，队内棋子 ID 为 0、1、2；其他标识以输入数据为准。

## 导出与生命周期

动态库必须导出以下四个符号：

```c
uint32_t ctf_abi_version(void);
int32_t ctf_create(const CtfInit *init, void **context_out);
int32_t ctf_decide(void *context, const CtfObservation *observation,
                   CtfTeamAction *output);
void ctf_destroy(void *context);
```

`ctf_abi_version` 返回 1。`ctf_create` 返回 0 为成功，必须填写 `*context_out`；无状态 AI 可写空指针。正常回合之间 context 保留，由 AI 自行分配和销毁。`ctf_decide` 返回 0 为成功，必须完整填写输出；非零忽略整队结果。正常退出调用 `ctf_destroy`，超时或进程崩溃不保证调用。

init、observation 和 output 均由裁判分配，只在本次调用期间有效。输入只读，不得释放、修改或保留其指针；需要记忆的数据应自行复制到 context。输出缓冲区由 AI 填写，不应释放。不得让 panic/异常跨越 C ABI。

Rust 按头文件自行声明等价类型：所有跨接口结构体（含嵌套类型）使用 `#[repr(C)]`，指针用 `*const T`/`*mut T`，`void*` 用 `*mut core::ffi::c_void`，固定宽度整数保持对应位宽，固定数组保留长度。不能用 Rust bool、Vec、String、引用或未指定布局的枚举代替接口字段。导出函数使用 `extern "C"` 和准确符号名，编译为 `cdylib`；Rust 2024 使用 `#[unsafe(no_mangle)]`。这些函数由你的 AI **实现并导出**，不是从裁判链接导入。

## 常量与布局

`CTF_ABI_VERSION=1`，`CTF_TEAM_SIZE=3`，`CTF_MAX_HP=3`，`CTF_SHOT_DAMAGE=1`，`CTF_SHOT_RANGE_MANHATTAN=5`。

| 结构体 | sizeof | alignof |
| --- | --- | --- |
| CtfInit | 80 | 8 |
| CtfAction | 20 | 4 |
| CtfTeamAction | 68 | 4 |
| CtfUnit | 40 | 8 |
| CtfFlag | 32 | 8 |
| CtfHome | 20 | 4 |
| CtfSite | 12 | 4 |
| CtfObservation | 96 | 8 |

这是目标平台的尺寸，自己实现绑定时应核对。`struct_size` 填相应结构体实际大小，ABI 版本填 1。坐标为 int32_t，左上原点，x 向右、y 向下。

## CtfInit

每次初始化传入；重启时会再次调用 create。

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| abi_version, struct_size | uint32_t | ABI 版本、CtfInit 大小 |
| team_id, team_count | uint32_t | 己方 ID、队伍数 2–8 |
| width, height | uint32_t | 地图宽高 |
| max_turns, target_score | uint32_t | 本场最大回合与目标分 |
| flag_respawn_min_turns, flag_respawn_max_turns | uint32_t | 本场旗帜生成等待参数的下限、上限 |
| first_turn, restart_count | uint32_t | 本次初始化要服务的首轮、此前重启次数 |
| seed | uint64_t | 己方独立 AI 种子，可以用于随机策略；不代表引擎随机状态 |
| decision_budget_us | uint32_t | 决策总预算，微秒 |
| initial_flag_count | uint32_t | 本场开局立即生成的旗帜数量 |
| max_hp, shot_damage, shot_range | uint32_t | 满血、命中伤害、曼哈顿射程 |
| respawn_absent_turns | uint32_t | 死亡后完整缺席的回合数 |

## CtfObservation

每队每回合一份开始快照；各队观察同一局面，自己的 team_id 不同。输入只包含当前公开信息，不包含其他队伍本轮动作、未来具体生成时间或引擎 RNG。

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| abi_version, struct_size | uint32_t | 版本、CtfObservation 大小 |
| turn, team_id | uint32_t | 当前绝对回合号、己方 ID |
| width, height | uint32_t | 地图宽高 |
| team_count | uint32_t | 队伍数，也是 homes/scores 的长度 |
| unit_count, flag_count, site_count, cell_count | uint32_t | 对应数组长度 |
| reserved | uint32_t | 保留字段，当前为 0 |
| cells | const uint8_t* | 长度 cell_count=width×height，行主序 cells[y×width+x]，0 地面、1 墙 |
| units | const CtfUnit* | 长度 unit_count=team_count×3，按 team_id、unit_id 排序 |
| flags | const CtfFlag* | 长度 flag_count，当前全部地上和携带的旗帜 |
| homes | const CtfHome* | 长度 team_count，每队一项 |
| sites | const CtfSite* | 长度 site_count，静态旗点 |
| scores | const uint32_t* | 长度 team_count，下标为队伍 ID |

所有数组只在调用期间有效；数量为 0 时不解引用指针、不据此假设非空。

### CtfUnit

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| team_id, unit_id | uint32_t | 所属队伍、队内 ID（0、1、2） |
| alive, hp | uint32_t | alive 为 0/1；当前 HP |
| x, y | int32_t | 坐标；死亡时均为 -1 |
| carrying, respawn_at_turn | uint32_t | carrying 为 0/1；死亡时预定复活的绝对回合号，存活时为 0 |
| flag_id | uint64_t | 携带旗 ID；未携带时为 0，仍应以 carrying 判断 |

死亡时 hp=0、carrying=0，不占格；复活预定时间可能因占格而延后。ID 在死亡/复活后不变。

### CtfFlag

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| id | uint64_t | 旗帜 ID |
| site_id, state | uint32_t | 来源旗点 ID；state=0 地上、1 携带 |
| x, y | int32_t | 当前坐标；携带时为携带者位置 |
| carrier_team, carrier_unit | uint32_t | 携带者 ID；地上时均为 UINT32_MAX |

### CtfHome 与 CtfSite

| 结构体 | 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- | --- |
| CtfHome | team_id | uint32_t | 所属队伍 |
| CtfHome | x, y | int32_t | 出生矩形左上角 |
| CtfHome | width, height | uint32_t | 矩形宽高 |
| CtfSite | id | uint32_t | 旗点 ID |
| CtfSite | x, y | int32_t | 旗点坐标 |

出生区包括 `[x,x+width)`、`[y,y+height)` 的格子。旗点是地形信息，不代表该格当前一定有旗。

## 输出 CtfTeamAction 与 CtfAction

| 结构体 | 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- | --- |
| CtfTeamAction | abi_version, struct_size | uint32_t | 必须填 1 和 sizeof(CtfTeamAction) |
| CtfTeamAction | actions | CtfAction[3] | 固定三个槽，unit_id 依次 0、1、2 |
| CtfAction | unit_id, kind, direction | uint32_t | 棋子 ID、动作、移动方向 |
| CtfAction | target_x, target_y | int32_t | 射击目标 |

| 动作 | kind 常量/值 | 使用字段 |
| --- | --- | --- |
| 等待 | CTF_WAIT=0 | unit_id |
| 移动 | CTF_MOVE=1 | unit_id、direction：CTF_UP=0、CTF_DOWN=1、CTF_LEFT=2、CTF_RIGHT=3 |
| 射击 | CTF_SHOOT=2 | unit_id、target_x/target_y：图内、非射手自身格、曼哈顿距离 1–5 |

输出不会自动初始化为合法结果，必须填写版本、大小、全部槽位及使用的字段；未使用字段建议置零，死亡棋子填等待。版本/大小/槽位错误、非零返回、崩溃/超时导致整队等待。外层结果合法时，单个非法游戏动作只让对应棋子不执行，并记录原因。

## 预算与故障

每队决策 50000µs 墙钟预算，包含恢复、通信与完整结果校验，排队等待不计入。初始化/重启另限 1000ms，正常退出限 100ms；每队进程地址空间限 256MiB。不要在函数返回后后台计算。

超时终止本队进程组，本轮全部等待，后续回合重启并丢失 context，restart_count 增加。正常响应只保留自己的记忆，不应依赖其他队伍内存。输出的动作仍由裁判按实际结算状态校验；开始快照中看似可行的动作可能因同轮射击、掉旗或占格而失效，回放会给出结果。
