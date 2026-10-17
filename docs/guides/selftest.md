# 参赛开发自测工具

`python3 scripts/selftest.py` 提供预检、小规模自测、固定对手版本比较、公开事件摘要与回放备份。它用于开发自测；正式多 AI 同场排名使用 [league](league.md)，旧固定名单接口见 [tournament](tournament.md)。在题包中使用相同命令，runner、worker、基准和默认地图自动从题包查找；仓库中默认查找 `target/release/`。

## 从两场开始

将 release 库放到 `submission/libteam.so`，先运行：

```sh
python3 scripts/selftest.py check --out runs/preflight
python3 scripts/selftest.py run --out runs/quick
```

`check` 先用基准检查运行环境，再让候选在私有两回合地图中通过真实 worker 调用。它保留诊断和原始错误，不在 Python 中加载候选库。成功返回0，已完成的失败诊断返回1，输入/准备错误返回2；Ctrl+C 返回130。控制阶段失败时不会继续候选阶段。ABI、加载、崩溃、超时、通信和候选返回错误分别诊断；权限错误由场外人员检查环境。预检不是强度测试，也不保证复杂局面不会超时。正常比赛仍将 AI 超时/崩溃计入故障，预检不改变计分。

`run` 默认双人地图、一个候选、基准对手、quick、一块、串行，**恰好两场，交换出生位**。开始执行前打印总场数，默认最多接受10000场；扩大限制必须显式 `--match-limit N`。不会估计未测量的实际运行秒数。新输出目录必须不存在。

```sh
python3 scripts/selftest.py run --ai submission/libteam.so \
  --map maps/arena_3p.ron --map maps/arena_8p.ron \
  --mode quick --repeats 1 --out runs/selected
```

此例为3+8=11场，多余位置均由指定对手的独立副本填充。`--opponent FILE` 更换固定对手；`--runner FILE` 指定裁判，其同目录必须有 worker。quick 每图每块N场，balanced 为N(N−1)场（2p仍两场），所有版本场数相加。全图 balanced 一块198场、五块990场，可能耗时数小时并占用大量磁盘。先小样本估算，给编码和提交留足时间。

## 冻结与版本对照

```sh
python3 scripts/selftest.py compare \
  --ai old=submission/libold.so --ai new=submission/libnew.so \
  --opponent submission/libopponent.so --out runs/compare
python3 scripts/selftest.py resume runs/compare --max-matches 2
```

每个版本**分别面对同一固定对手**，彼此不同场。对应比赛使用相同的地图、出生位、引擎种子、逻辑角色 AI 种子和赛程安排；策略变化仍会改变后续局面和随机事件的消费。它控制输入条件，不是因果收益证明。默认两版共四场。

`seeds.json` 保存显式种子条件，可用 `--seed-file runs/compare/seeds.json` 在新实验中复用；地图 ID、人数、字节哈希及重复数必须相符。引擎u64种子、AI和赛程各自u256根种子相互独立。改变地图或重复数需重新生成种子清单。

创建时冻结候选、对手和地图，记录 SHA-256；之后修改源文件不影响续跑。测试新代码必须创建新实验。`--max-matches N` 限制本次新增场数，跨版本合计。Ctrl+C 保留现场，`resume` 验证快照与完整回放，不重复已采纳比赛。不要移动活动实验或替换 runner/worker；恢复备份也不会转换绝对工具路径。

每版 `versions/<id>/` 是独立的旧版兼容计划；外层 `report.md`、`results.json` 汇总。积分为千分制，实际排序仍按未取整值，只有完整、验证通过的换位块有成绩。版本实验明确标记开发自测，不生成正式跨选手总榜。建议保留风格不同的历史实现作对手，基准优势不等于最终优势。

跨场 `--jobs N` 默认1，可先试2；资源争抢可能增加超时并影响结果，不减少记录总空间。每场队伍调用始终串行，正式评测固定1。并行来源会保留，串行续跑无法清除。输出锁覆盖在途进程清理；控制器意外死亡后，内层计划仍活动时禁止续跑和归档。

## 摘要与空间

```sh
python3 scripts/selftest.py summary runs/compare --out runs/analysis
python3 scripts/selftest.py summary runs/single-match \
  --out runs/single-analysis --estimate-matches 198
```

输入为一场完整原始回放或一个自测实验。摘要先通过真实裁判 `verify`，再读取公开动作/事件，输出新目录中的 JSON、Markdown 与校验日志。单 JSON最多16MiB、单场JSON总量512MiB、最多25000帧；坏记录不会按零计入。摘要不启动AI，不输出 RNG 或未来刷新时刻。

提供地面/生成拾旗、交旗、携旗阵亡、射击命中/空射/遮挡/非法、友伤、实际血量损失、移动争格/占格或闭环/死亡取消/非法，以及调用状态与延迟。射击命中率分母为合法射击，移动成功率分母为移动事件；死亡单位等待单独计数。过量集火的名义伤害与实际扣血分别统计，不归属独占击杀。每类最多保留三个可定位示例，输出列出指标定义。

实验按实际候选角色、版本和地图汇总；不完整块也可分析行为，但没有排名积分。磁盘统计包含源目录实际文件，并按同图样本估算场均/轮均与计划规模；少于两场标记样本不足，无样本地图不作预测。估算不是空间上界，不跨图套用；`--estimate-matches` 仅适用于单图。

## 非破坏归档与恢复

```sh
python3 scripts/selftest.py archive runs/compare --out runs/compare.tar.gz
python3 scripts/selftest.py restore runs/compare.tar.gz --out runs/restored
```

支持完整单场或全部完成的自测实验；活动锁、进行中比赛和未完实验均拒绝。归档只含明确的原始比赛、冻结输入和实验元数据，不含锁、缓存、临时尝试或导出网页。每个文件有路径、大小、权限和 SHA-256 清单，源文件变化则拒绝发布。

恢复手动提取到私有临时目录，拒绝路径穿越、重复项、链接、特殊文件、错误哈希和超额输入；每场重新 `verify` 后才原子发布。默认最多1000000文件、64GiB解压数据，清单最多256MiB，扩展元数据最多64KiB、只接受单个局部路径字段，不接受全局/大小覆盖/GNU扩展；可用 `--max-files`、`--max-bytes` 降低或提高配额。恢复应使用组织者信任的裁判，归档哈希用于完整性检查，不证明来源可信。

原始输入不会删除或覆盖；输出已存在则失败。恢复用途是离线查看、导出和审计，**不是可迁移续跑包**，不会重写历史绝对路径或补齐旧工具。恢复后可对单场目录导出播放器。压缩暂时需要额外空间，成功后是否删除原始记录由使用者自行决定；工具没有清理入口。
