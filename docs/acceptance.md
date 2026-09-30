# 质量与性能验收基线

合成回归检查剪辑执行、媒体格式和时间映射。真实内容精选、笑声/情绪是否误删、BGM 分离质量需要独立人工标注与真实 AI 结果；未执行的环节必须报告 `not_measured`。历史 25 秒用户认可样本和短合成测试不能代表整场录播。

## 合成渲染

```powershell
python -X utf8 scripts/benchmark.py synthetic
```

脚本新建隔离 profile，生成固定 24 秒、320×180、25 fps 的测试图案/440 Hz 纯音，固定保留 `[1,4]`、`[9,12]`、`[18,22]`，运行真实细剪预览和正式导出。总成片预期 10 秒，时长容差 0.3 秒；检查三条字幕的元数据时间映射。测试不调用 AI、ASR 或重型声音模型，不读取应用用户数据库。保留成片与 `report.json`，默认输出在 Git 忽略的 `test-results/bench/<随机ID>/`。`--output-dir` 要求空目录，工具不会删除或覆盖以前的运行记录。

性能用 100 ms 采样记录 wall time、进程树 RSS/工作集、累计 CPU seconds、进程 I/O、输出目录峰值和结束占用。`average_cpu_percent_one_core_basis=100` 表示平均占用一个逻辑核心，可能超过 100。短命进程或两次采样之间的峰值可能遗漏；I/O 是进程逻辑计数，包含程序/DLL 读取和系统缓存，不能当作物理磁盘吞吐。目录占用只统计该输出目录。无 psutil 或进程已退出时指标为 null/未测，不填零。CI 机器速度变化较大，仅强制正确性指标，性能报告用作同环境比较。

字幕元数据一致不等于声画/口型同步或烧录文字正确。报告把声学对齐、OCR、语义精选明确列为未测。

## 真实长录播的显式测量

`measure` 接受 JSON 参数数组，直接启动程序，不使用 shell 字符串，不自行联网或创建 AI 任务。需要你显式准备模型、字幕/弹幕和运行命令；应在独立验收 profile 运行，记录 Git commit、音轨编号、输入媒体版本、模型 hash、API 模型及选项。不要把 API Key 写入提交的 JSON。

例：将以下内容保存为 UTF-8 无 BOM 的本地 `asr-command.json`，把路径替换为待测素材和实际环境。输出路径应位于本次测量目录；`--audio-track` 是从 0 开始的音频轨序号。

```json
["D:/SliceAI/.venv/Scripts/python.exe", "-X", "utf8", "D:/SliceAI/backend/asr.py", "--video", "D:/recordings/long.mkv", "--audio-track", "0", "--model", "D:/SliceAI/asr-model/SenseVoice", "--output", "D:/SliceAI/test-results/bench/real-asr/transcript.jsonl", "--ffmpeg", "ffmpeg", "--ffprobe", "ffprobe", "--threads", "2"]
```

```powershell
python -X utf8 scripts/benchmark.py measure --command-json asr-command.json --video D:/recordings/long.mkv --output-dir test-results/bench/real-asr
```

它保存资源数据和 `wall_seconds_per_source_second`。进程返回非零时 benchmark 返回失败并保留原始输出字节 `process-output.bin`。此命令只是 ASR 示例；测量完整粗剪/细剪时提供对应程序参数数组并使用独立目录。完整链路质量仍需下面的标注评分。

## 标注评分

格式示例是 `bench/annotations.example.json`、`bench/results.example.json`。示例中的区间和文字是人为 fixture，不是已验收的录播数据。

- `events`：人工穷尽标注值得独立保留的事件，时间相对原视频；结果 `clips` 用同一原视频时间。
- `protected`：不可误删的原视频区间，如铺垫、因果、笑声、低声评论和后续回应；结果 `ranges` 是最终实际保留区间，按播放顺序列出。
- `captions`：人工按最终成片音频对齐的字幕，时间在成片轴上。人工/结果使用一致且唯一的 `id`，可选 `text` 用于比较文字。

```powershell
python -X utf8 scripts/benchmark.py evaluate --annotations D:/qa/annotations.json --results D:/qa/results.json --report test-results/bench/quality.json
```

事件按区间 IoU（默认 ≥0.5，可配置 `--iou-threshold`）匹配，报告漏掉的标注事件、无匹配的误选片段及同一事件的重复输出数量。误删统计 `protected` 减去保留区间并集的秒数；重复源内容统计保留区间总长减去并集长度。字幕报告缺失/多余 cue、文字不一致数、边界绝对误差的 median/p95/max。跨边界分段、不同字幕分句需要先人工统一 ID，不能把分句差异当成同步精度。

标注不全时不能解释为召回率/误选率；脚本输出计数，不自动宣布产品质量通过。缺少某类标注或结果时对应指标报告未测。评价供应的结果文件，不自动重新执行模型，必须记住结果对应的 commit 和配置。

## 发布前真实验收

覆盖至少一场长录播及多音轨、音频晚起/PTS 空隙、跨窗口长故事、重复讲述、外部播放、安静笑声、BGM 较重、字幕切点、取消/崩溃恢复、移动原素材等案例。按事件记录漏剪/误选，按细剪记录误删/字幕同步，按完整运行记录耗时、CPU、峰值工作集和磁盘峰值。声音缓存 16 GiB 是软预算；版本和试听引用保护文件，可能超过预算。磁盘预检与短合成通过也不能代替实盘不足/取消和长期缓存验收。

分批模型请求用于控制上下文/输出容量，不表示把连续长故事拆成多个成片。最终长故事完整性以及长时间处理的实际速度、分离质量尚需真实标注测量；不要仅凭单元测试或实现说明承诺结果。
