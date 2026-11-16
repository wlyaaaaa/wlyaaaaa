# 实况数据

`live.contract.json` 是公开接入单，`live.snapshot.json` 是公开小快照，不含私人路径或凭据。

现有每日小蛇工作流在生成两套 SVG 时顺带写 `dist/live.snapshot.json`，与 SVG 一起发布到 `output` 分支。没有新增任务。

本机按需更新（只读已发布 SVG，不生成动画、不需要密钥）：

```powershell
python -B -X utf8 scripts/generate_snake.py --refresh-live --output-dir dist --live-output docs/live.snapshot.json
python -B -X utf8 -m unittest discover -s tests -v
```

读取同一个 output 提交的亮暗 SVG；贡献天数只数一套日格，连续天数遇零或日期中断即断开。贡献日数不等于贡献次数。
源时刻 `at` 是已发布 output 的提交时间，`scope` 写图上真实截止日和覆盖日期；不是本机取数时刻。主页数据时刻是 README/配图最后一次提交时间。
快照读取失败时贡献相关值、时刻为空，说明失败原因，不拿本地旧图替代。文件未变不刷新源时刻，规模内容未变不刷新规模时刻。

本机通用读取器只读登记的小 JSON；远端每日发布已接，远端到本机的自动镜像须由持有人接入现有采样/按需更新链。本次手工运行不代表本机已自动接好。主页内容更新后也需重取。
产物只有主页和最新贡献图；图链接必须同时有本地 `dist` 对应文件的 exists 登记。完整公开图片仍在 assets，未另列十四张亮暗图片。
