# 实况数据

`docs/live.contract.json` 是公开接入单。本机实况读取 `dist/live.snapshot.json`，其中不含私人路径或凭据。

现有每日小蛇工作流在生成两套 SVG 时顺带写 `dist/live.snapshot.json`，与 SVG 一起发布到 `output` 分支。没有新增任务。

本机按需更新（只读已发布 SVG，不生成动画、不需要密钥）：

```powershell
python -B -X utf8 scripts/generate_snake.py --refresh-live --output-dir dist --live-output dist/live.snapshot.json
```

读取同一个 output 提交的亮暗 SVG；贡献天数只数一套日格，连续天数遇零或日期中断即断开。贡献日数不等于贡献次数。
源时刻 `at` 是已发布 output 的提交时间，`scope` 写图上真实截止日和覆盖日期；不是本机取数时刻。主页数据时刻是 README/配图最后一次提交时间。
快照读取失败时贡献相关值、时刻为空，说明失败原因，不拿本地旧图替代。文件未变不刷新源时刻，规模内容未变不刷新规模时刻。

PCConfig 的项目夜检运行同一条取数命令，读取远端 `output` 的固定提交，并刷新本机 SVG 和小快照。改了主页内容后也可以按需取数。
实况产物是主页和最新贡献图，后者有本地 `dist` 文件存在检查。现在主页直接显示小蛇、贡献统计和公开仓库语言三种图，均从 `output` 分支读取亮暗版本。
