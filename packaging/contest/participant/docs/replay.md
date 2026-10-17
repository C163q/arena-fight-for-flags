# 回放与分析

比赛目录包含 `manifest.json`、地图与初始状态、`frames/` 内每轮 JSON/TXT，以及结束摘要。TXT 有 ASCII 棋盘、棋子/比分表、实际操作、射击者与目标、射击结果、血量和携旗变化，适合程序员或 LLM 直接阅读。完整记录可能包含题面未展开的机制，可通过实验分析。

先验证原始记录，再导出：

```sh
bin/fff-runner verify runs/my-match
python3 viewer/export.py runs/my-match
```

默认在比赛目录生成 `replay.html` 与 `replay.json`。直接用浏览器打开 `replay.html`，或打开 [通用播放器](../viewer/index.html) 并拖入 `replay.json`。不需要服务器或网络。同一个页面可以反复打开不同比赛。

```sh
# 只导出通用播放器需要的数据文件
python3 viewer/export.py runs/my-match --format json
```

播放器支持自动播放、调速、前后单步、滑块与指定回合，以及 START/END 状态。棋盘支持缩放、平移、适配与全屏；受伤棋子头顶显示三格血条，满血隐藏。侧栏显示比分及事件/棋子/AI 调用明细，点击棋子可查看状态。

图例：`#` 为墙、`.` 为地面、`0`–`7` 为出生区、`o` 为旗点、`*` 为地上旗、`A`–`X` 为棋子。棋子字符覆盖下层物体，完整明细仍保留。

`verify` 重新执行已记录的实际动作并核对规则与 ASCII，不重新运行 AI。导出器只验证格式结构；不要以导出成功代替完整验证。未完成比赛可查看完整前缀。导出最多 25000 帧，单个源文件 16MiB、总输入 512MiB；超限会报错。

## 行为摘要与备份

`python3 scripts/selftest.py summary 比赛目录 --out runs/analysis` 先验证记录，再生成公开事件指标和磁盘估算，不运行 AI。`archive` 和 `restore` 用于完整记录的非破坏备份，恢复后对其中单场目录重新导出播放器。命令和限制见 [自主评测](testing.md)。
