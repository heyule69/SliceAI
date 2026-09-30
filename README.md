# SliceAI 0.2

Windows 录播切片客户端：先发现完整事件，再通过固定问答选择细剪要求。当前为开发验收版。

## 使用

下述新增行为以当前源码构建为准。本轮更新没有重新打包或替换 `release/` 中的客户端；已有客户端需在后续构建发布后才包含这些修复。

运行 `release/SliceAI-0.2.0/SliceAI.exe`，保留旁边的 `worker` 文件夹。安装包为 `release/SliceAI_0.2.0_x64-setup.exe`。支持 Windows 10 / 11 x64，需要 WebView2；不需要用户安装 Python 或 FFmpeg。

1. 左下角「设置」填写自己的 AI API 地址、模型和 Key。内容判断通过 API；转写在本地进行。SenseVoice INT8 转写模型及 Silero VAD 随软件内置，无需首次下载。
2. 导入录播，可选附加 UTF-8 的 SRT/VTT 转写及 XML/JSON 弹幕。多音轨素材可选择要分析的音轨，默认第一音轨；转写、声音处理、预览和导出使用同一选择。选择内容偏好和来源过滤，开始查找事件。
3. 结果默认先列出，按需预览、选择并导出。粗剪保持连续原区间、原构图和原声音，不新增字幕。使用 H.264/AAC 转码精确截取。
4. 进入「细剪」，通过五步选择确定剪辑要求。点击开始后自动制定方案、复核并生成预览。修改内容区间需要重新确认。
5. 字幕可改字、拆分合并、调整时间；默认烧录，可关闭并选择另存 SRT。修改字幕后先保存草稿，再预览、切换版本或导出。改变保留区间后需检查切点附近字幕并重新确认；字幕核对标记提示原声和转写存在分歧。预览和正式导出使用同一方案。
6. 降低背景音乐可直接应用，20 秒原声/处理后试听为可选步骤。启用时先处理完整事件音频，再转写对照、判断删减并复用处理音频合成；默认强度为 100%，可调低或恢复原声。

窗口默认 1090 × 720，记忆用户调整的大小；最小 960 × 640。列表和选择面板各自滚动。每个事件拥有独立剪辑要求、方案、字幕与版本记录，粗剪结果保留。

## 背景音乐处理

使用 **BandIt Plus（DnR SDR 11.47）**，仅使用 `speech` 输出。CPU float32，44.1 kHz、6 秒窗口、75% 重叠；反射补齐、Hann 重叠衔接后恢复到 48 kHz，并保持原始采样数。100% 强度与用户认可的 04 试听处理一致，不混入 effects 音轨。

模型和独立运行环境随完整包提供，无首次模型联网下载。分块读取并通过临时文件中转，声音进程完成即退出。改变强度复用同一来源、音轨、事件范围和模型的人声 stem，仅重新混音。音频缓存采用 16 GiB 软预算和 LRU 清理；版本、试听及持久路径引用会保护所需文件，受保护内容可使缓存超过预算。分离前估算临时文件空间，不足时先报预计/可用空间。旧模型缓存不会复用；旧方案如开启了声音处理，需要重新应用声音处理，已有预览和导出文件保留。

本机 25 秒真实笑声样本：源码运行约 124 秒，进程树峰值工作集约 955 MB；输出与认可的 04 浮点 WAV 逐采样一致。这是该样本和本机的实测，不代表所有录播的分离质量或处理速度。打包回归记录保存在 `test-results/v0.2/audio-comparison/笑声/`。

## 数据与当前验收范围

- 使用 SliceAI 独立 SQLite 数据目录；Key 用 Windows DPAPI 加密。与 BilibiliLive 无数据、配置或密钥共享。
- API 接收转写、可选弹幕；来源复核还会发送候选画面。声音处理完全本地，不调用 AI API。
- 粗剪按完整事件识别，跨窗口接续并复核边界，无默认 12 段数量截断。来源不确定的结果单列；原素材未讲完的事件保留未完标记。
- 后台耗时任务串行执行，支持取消；失败保留草稿和已完成结果。异常重启会恢复可操作状态，重新执行前保留已完成成片。视频原文件不修改，重复导出使用新文件名。
- 媒体时间零点以首视频轨的 `start_time` 为基准；晚起音频补静音，PTS 空隙按媒体时间保留。导入字幕、弹幕仍应使用相对录播的时间。
- 已通过字幕映射、重排确认、版本恢复、API 失败、取消、来源复核等自动回归；声音已获得用户对聊天和笑声样本的认可。
- 长录播实际结果的重复事件合并、完整桌面交互及资源验收仍在进行，不能把本次声音模块验收视为整个 0.2 计划完成。

2026-09-30 当前源码软件实测：一个 429.398 秒事件走完标准细剪与导出后仍删除零秒，58 条字幕中 46 条待核对。媒体导出正常，但精简和字幕质量未达标。已核查开源文字剪辑与对齐实现，并用现有模型验证字/token 锚点可以返回；改造方向和未验证边界见 [细剪核心改造提案](docs/fine-editing-redesign.md)，提案尚未实现。

## 开发和构建

技术：Tauri 2 / Rust、Vite / TypeScript、按需 Python 工作进程、SQLite、sherpa-onnx、FFmpeg、BandIt Plus。源文件均为 UTF-8 无 BOM。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
python -m venv .audio-venv
.audio-venv/Scripts/python.exe -m pip install -r backend/requirements-audio.txt
npm ci
npm run desktop
```

Git 仓库不包含权重、虚拟环境或旧客户端资源。固定模型版本、字节数、SHA256、公开来源、推理配置及许可证位于 `scripts/model-assets/`。准备入口不读取 `LOCALAPPDATA` 或 `.test-artifacts`，也不覆盖已适配的 `backend/bandit/`。先用 `--dry-run` 查看计划；联网准备需要显式 `--download`，也可用 `--source-dir` 导入相同 SHA256 的离线资产。

```powershell
python -X utf8 scripts/prepare-asr-model.py --download --dry-run
python -X utf8 scripts/prepare-audio-model.py --download --dry-run
python -X utf8 scripts/prepare-asr-model.py --download
python -X utf8 scripts/prepare-audio-model.py --download
```

ASR 资产写入 `asr-model/SenseVoice`，声音资产写入 `audio-model/BandItPlus`；构建入口在运行 PyInstaller 前按仓库固定清单校验。详见 [可复现构建](docs/reproducible-build.md)。应用运行时只加载随完整包提供的离线模型。

```powershell
npm run build
npm run test:frontend
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
.venv/Scripts/python.exe -X utf8 -m unittest discover -s scripts -p "test_*.py" -v
.audio-venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_audio_streaming.py -v
.audio-venv/Scripts/python.exe -X utf8 scripts/prepare-audio-model.py
.audio-venv/Scripts/python.exe -X utf8 scripts/build-audio.py
.venv/Scripts/python.exe -X utf8 scripts/prepare-asr-model.py
.venv/Scripts/python.exe -X utf8 scripts/build-worker.py
npm run bundle
.venv/Scripts/python.exe -X utf8 scripts/package-release.py
```

构建需要 Rust MSVC 工具链、Visual Studio C++ Build Tools，FFmpeg / FFprobe 在 PATH 中；音频和 ASR 使用不同 Python 环境。`npm run dev` 只预览界面，桌面本地操作使用 `npm run desktop`。

BandIt 原项目采用 Apache-2.0，MSST 推理实现采用 MIT；本地适配说明和许可证保存在 `backend/bandit/`，完整包包含在 `worker/audio/licenses/`。其他第三方组件见 `worker/THIRD-PARTY-NOTICES.txt` 与 `worker/audio/THIRD-PARTY-NOTICES.txt`。安装包未作代码签名。

## 回归与质量性能基线

GitHub Actions 分开运行前端构建/交互回归、Windows Python/DPAPI/FFmpeg 回归，以及独立音频环境的合成分块/重采样/缓存测试；CI 不下载大型模型、不调用真实 AI。

`python -X utf8 scripts/benchmark.py synthetic` 用固定 24 秒测试图案/纯音素材跑细剪预览和导出，保存时长、字幕元数据以及 CPU、进程树工作集、I/O 和输出目录占用。真实长录播可通过显式命令测量，再用独立标注和结果 JSON 计算漏剪、误选、重复、受保护内容误删及字幕时间误差。缺少 AI 结果或人工标注时记录“未测”，合成素材通过不代表实际内容识别质量。指标定义、命令与验收范围见 [验收基线](docs/acceptance.md)。

## 交互修复（2026-09-29）

进入细剪时优先打开已有片段，否则直接播放原录播的对应区间，播放器从 00:00 开始；查看不生成预览、不占用后台队列。只有不能直接播放的格式，才按需生成兼容副本。正式成片仍从原录播生成。降低背景音乐直接按所选要求处理，试听可选。任务列表支持删除任务，默认保留本地文件；勾选后删除本任务生成的缓存和导出文件，保留原录播、导入字幕、弹幕及其他任务引用的文件。运行中的任务须先停止。设置保存成功自动关闭，失败保留输入。

本轮整改与验证：[全面复核整改记录](docs/review-2026-09-30.md)。
