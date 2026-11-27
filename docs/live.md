# 实况数据

`docs/live.contract.json` 是公开接入单。本机实况读取 `dist/live.snapshot.json`，其中不含私人路径或凭据。

现有每日小蛇工作流在生成两套 SVG 时顺带写 `dist/live.snapshot.json`，与 SVG 一起发布到 `output` 分支。没有新增任务。

本机按需更新（读取已发布文件和 GitHub 置顶，沿用本机 GitHub CLI 登录，不生成动画）：

```powershell
python -B -X utf8 scripts/generate_snake.py --refresh-live --output-dir dist --live-output dist/live.snapshot.json
```

用 Git 读取远端 output 分支指向的固定提交，再从该提交取快照、亮暗 SVG 及 README 引用的配图大小。贡献天数只数一套日格，连续天数遇零或日期中断即断开。亮暗配图分别计文件，置顶只计 GitHub 返回的公开仓库。
源时刻 `at` 取该提交内快照记录的生成时间，`mirror_at` 是本机本次成功取回的时间。覆盖日期取图上最早和最晚的日格，正文最后变动取 README 的最近提交，`pins_at` 是本次取得置顶的时间。
读失败的来源留空，已读到的其它来源照常保留，规模内容未变保留原规模时刻。

PCConfig 的项目夜检运行同一条取数命令，读取远端 `output` 的固定提交，并刷新本机 SVG 和小快照。改了主页内容后也可以按需取数。
实况产物是主页和最新贡献图，后者有本地 `dist` 文件存在检查。现在主页直接显示小蛇、贡献统计和公开仓库语言三种图，均从 `output` 分支读取亮暗版本。
