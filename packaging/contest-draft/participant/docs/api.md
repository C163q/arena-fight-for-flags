# AI 接口：函数、数据与运行限制

本页说明如何让比赛程序调用你的 AI。你需要编写一个动态库，实现四个指定函数；比赛程序会加载这个库，把数据传给函数，再读取返回的动作。动态库不需要自己启动比赛。

双方通过 **C ABI v1** 交换数据。ABI 规定函数怎样调用、结构体如何在内存中排列；“v1”表示本题当前使用版本 1。即使不用 C 语言，也必须遵守相同的排列和调用约定。声明以 [C 头文件](../include/ctf_ai.h) 为准。

本文保留了编写接口所需的技术细节，可以先了解调用顺序，再在实现具体字段时查表。`uint32_t`、`uint64_t` 是 32 位、64 位无符号整数，`int32_t` 是 32 位有符号整数；`T*` 表示指向 T 类型数据的指针，`const T*` 表示只能读取该数据。队伍编号从 0 开始，队内棋子编号为 0、1、2；旗帜和旗点的编号应读取输入，不要根据数组下标猜测。

## 1. 实现四个函数

动态库必须导出以下四个函数。“导出”意味着编译后的库中能按这些准确名称找到它们，不能只在源码内部定义：

```c
uint32_t ctf_abi_version(void);
int32_t ctf_create(const CtfInit *init, void **context_out);
int32_t ctf_decide(void *context, const CtfObservation *observation,
                   CtfTeamAction *output);
void ctf_destroy(void *context);
```

| 函数 | 什么时候调用、你需要做什么 |
| --- | --- |
| `ctf_abi_version` | 加载时检查接口版本，必须返回 `1` |
| `ctf_create` | 初始化时调用；读取本场参数，填写 `*context_out`，成功返回 `0` |
| `ctf_decide` | 每回合调用一次；读取当前局面，完整填写三个棋子的动作，成功返回 `0` |
| `ctf_destroy` | 正常结束时调用；释放自己创建的记忆数据。超时或崩溃时不保证调用 |

`context` 是你自己管理的记忆数据。需要跨回合记忆时，在 `ctf_create` 中分配数据，将其指针写入 `*context_out`；之后每次 `ctf_decide` 会收到这个指针。正常结束时由 `ctf_destroy` 释放。如果不需要记忆，仍须填写 `*context_out`，可以写空指针，并让其他函数能够接受它。

`ctf_create` 返回非零表示初始化失败；`ctf_decide` 返回非零表示本次调用失败，整队输出都不会采用。注意：`ctf_decide` 的整数返回值用于表示成功或失败，棋子的动作要写入 `output` 指向的结构体。

`init`、`observation` 和 `output` 指向的数据均由比赛程序提供，只在本次函数调用期间有效。输入只读，不得修改或释放，也不能保存这些指针留到以后使用；需要记忆的数据应复制到自己管理的内存。输出内存由你填写，不由你释放。Rust panic 或 C++ 异常必须在自己的函数内部处理，不能传到比赛程序中。

Rust 按头文件自行声明等价类型：所有跨接口结构体（含嵌套类型）使用 `#[repr(C)]`，指针用 `*const T`/`*mut T`，`void*` 用 `*mut core::ffi::c_void`，固定宽度整数保持对应位宽，固定数组保留长度。不能用 Rust bool、Vec、String、引用或未指定布局的枚举代替接口字段。导出函数使用 `extern "C"` 和准确符号名，编译为 `cdylib`；Rust 2024 使用 `#[unsafe(no_mangle)]`。这些函数由你的 AI **实现并导出**，不是从裁判链接导入。

## 2. 数据类型与内存排列

目标平台是 Linux x86_64 GNU。所有结构体使用平台的普通 C 对齐，不使用 `packed`，也不要调整字段顺序。下面的字段表按头文件中的声明顺序列出；同一行列出的多个字段都使用该行的类型。

`CTF_ABI_VERSION=1`，`CTF_TEAM_SIZE=3`，`CTF_MAX_HP=3`，`CTF_SHOT_DAMAGE=1`，`CTF_SHOT_RANGE_MANHATTAN=5`。

| 结构体 | 大小 sizeof（字节） | 对齐 alignof（字节） |
| --- | --- | --- |
| CtfInit | 80 | 8 |
| CtfAction | 20 | 4 |
| CtfTeamAction | 68 | 4 |
| CtfUnit | 40 | 8 |
| CtfFlag | 32 | 8 |
| CtfHome | 20 | 4 |
| CtfSite | 12 | 4 |
| CtfObservation | 96 | 8 |

大小表示结构体占用多少字节，对齐表示其起始地址的排列要求。自己为其他语言声明等价类型时，必须核对这两项；布局不一致会导致双方读到错误的字段。`struct_size` 表示相应结构体的实际大小，输出中的 ABI 版本填 1。坐标为 `int32_t`，左上原点，x 向右、y 向下。

## 3. 初始化参数 CtfInit

`ctf_create` 收到的参数。它包含本场地图尺寸、队伍编号、计算时间限制等信息；故障后重新启动 AI 时，也会再次收到。

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| abi_version, struct_size | uint32_t | ABI 版本、CtfInit 大小 |
| team_id, team_count | uint32_t | 己方 ID、队伍数 2–8 |
| width, height | uint32_t | 地图宽高 |
| max_turns, target_score | uint32_t | 本场最大回合与目标分 |
| flag_respawn_min_turns, flag_respawn_max_turns | uint32_t | 本场旗帜生成等待参数的下限、上限 |
| first_turn, restart_count | uint32_t | 本次启动后将处理的第一个比赛回合号、此前重启次数 |
| seed | uint64_t | 己方独立 AI 种子，可以用于随机策略；不代表引擎随机状态 |
| decision_budget_us | uint32_t | 常规回合的计算时间限制，单位为微秒（µs）。第 1 回合的特殊限制见下文 |
| initial_flag_count | uint32_t | 本场开局立即生成的旗帜数量 |
| max_hp, shot_damage, shot_range | uint32_t | 满血、命中伤害、曼哈顿射程 |
| respawn_absent_turns | uint32_t | 死亡后完整缺席的回合数，当前为 10 |

`decision_budget_us` 当前始终传入 `50000`（50ms），只记录常规回合的限制，不会逐回合更新。判断当前回合能计算多久，应读取 `CtfObservation.turn`：等于 `1` 时，本队这次调用的时间限制为 250ms；大于 `1` 时为 50ms。

## 4. 每回合局面 CtfObservation

`ctf_decide` 收到的局面是本回合开始时的状态。各队看到同一局面，自己的 `team_id` 不同。你看不到其他队伍为本回合选择的操作，也不知道旗帜未来会在哪一回合生成。比赛程序内部的随机状态也不在输入中。

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| abi_version, struct_size | uint32_t | 版本、CtfObservation 大小 |
| turn, team_id | uint32_t | 当前比赛回合号（从 1 开始）、己方 ID |
| width, height | uint32_t | 地图宽高 |
| team_count | uint32_t | 队伍数，也是 homes/scores 的长度 |
| unit_count, flag_count, site_count, cell_count | uint32_t | 对应数组长度 |
| reserved | uint32_t | 保留字段，当前为 0 |
| cells | const uint8_t* | 长度 cell_count=width×height，逐行存储；坐标 (x,y) 对应 cells[y×width+x]，0 地面、1 墙 |
| units | const CtfUnit* | 长度 unit_count=team_count×3，按 team_id、unit_id 排序 |
| flags | const CtfFlag* | 长度 flag_count，当前全部地上和携带的旗帜 |
| homes | const CtfHome* | 长度 team_count，每队一项 |
| sites | const CtfSite* | 长度 site_count，静态旗点 |
| scores | const uint32_t* | 长度 team_count，下标为队伍 ID |

数组字段是指向第一个元素的指针，长度由相应计数字段给出；不要把指针本身当成完整数组。所有数组只在本次调用期间有效。长度为 0 时不要通过指针读数据，也不能假定这个指针一定非空。

### CtfUnit

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| team_id, unit_id | uint32_t | 所属队伍、队内 ID（0、1、2） |
| alive, hp | uint32_t | alive：0 死亡、1 存活；hp 为当前血量 |
| x, y | int32_t | 坐标；死亡时均为 -1 |
| carrying, respawn_at_turn | uint32_t | carrying：0 未携旗、1 携旗；死亡时预定复活的比赛回合号，存活时为 0 |
| flag_id | uint64_t | 携带旗 ID；未携带时为 0，仍应以 carrying 判断 |

死亡时 hp=0、carrying=0，不占格；复活预定时间可能因占格而延后。ID 在死亡/复活后不变。

### CtfFlag

| 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- |
| id | uint64_t | 旗帜 ID |
| site_id, state | uint32_t | 来源旗点 ID；state=0 地上、1 携带 |
| x, y | int32_t | 当前坐标；携带时为携带者位置 |
| carrier_team, carrier_unit | uint32_t | 携带者的队伍与棋子 ID；地上时均为 UINT32_MAX（4294967295，表示无携带者） |

### CtfHome 与 CtfSite

| 结构体 | 字段（按顺序） | C 类型 | 含义 |
| --- | --- | --- | --- |
| CtfHome | team_id | uint32_t | 所属队伍 |
| CtfHome | x, y | int32_t | 出生矩形左上角 |
| CtfHome | width, height | uint32_t | 矩形宽高 |
| CtfSite | id | uint32_t | 旗点 ID |
| CtfSite | x, y | int32_t | 旗点坐标 |

出生区包括横坐标从 `x` 到 `x+width-1`、纵坐标从 `y` 到 `y+height-1` 的格子。旗点是可能产旗的位置，不代表该格当前一定有旗；实际旗帜看 `flags` 数组。

## 5. 填写动作 CtfTeamAction 与 CtfAction

把整队结果写入 `output` 指向的 `CtfTeamAction`。其中 `actions` 固定有三个元素，依次对应己方 0、1、2 号棋子；死亡棋子也必须有对应项，并填写等待。

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

不要依赖输出内存原有的值。必须填写版本、大小、三个动作的 `unit_id`、`kind` 及该动作需要的字段；未使用字段建议置零。

注意两种错误的区别：

- 接口结果错误：例如整队结构体的版本、大小、棋子编号不符合要求，或函数返回非零、崩溃、超时，会让三个棋子全部等待。
- 单个游戏操作非法：整队结果格式正确，但某个棋子试图走入墙、使用未知动作编号或射击超出范围等，只取消该棋子的操作，并在记录中注明原因。

## 6. 计算时间限制、内存限制与故障处理

比赛第 1 回合的计算时间限制为 250000µs（250ms），之后每回合为 50000µs（50ms）。这是本队三个棋子合计的一次调用的限制，按实际经过的总时间计算，不是只统计 CPU 执行你的代码的时间。恢复 AI 运行、数据通信和检查完整结果的开销也计算在内；等待其他队伍计算的时间不计入。

只有比赛第 1 回合允许 250ms，根据 `CtfObservation.turn == 1` 判断。`CtfInit.first_turn` 表示本次启动后将处理的第一个比赛回合号，不能据此再次使用 250ms。例如在第 20 回合重启，`first_turn` 为 `20`，该回合仍只允许 50ms。

初始化或重启另外限时 1000ms，正常退出限时 100ms。每队 AI 进程的地址空间上限为 256MiB；地址空间还包含程序和库映射，不只计算你主动分配的数据。不要在函数返回后继续后台计算。

超时时，本队 AI 会被强制结束，当回合三个棋子全部等待。后续回合重新启动，原 `context` 中的记忆丢失，`restart_count` 增加。各队独立运行，不应依赖其他队伍的内存。

返回的操作最终仍由比赛程序根据结算时的状态判断。回合开始时看似可行的操作，可能因同回合射击、掉旗或位置冲突而失效；可以通过回放查看结果。
