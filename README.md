# SliceAI 0.2

Windows 录播切片客户端：先发现完整事件，再通过固定问答选择细剪要求。当前为开发验收版。

## 使用

正式交付使用安装版：运行 `release/SliceAI_0.2.0_x64-setup.exe`，按安装向导安装后使用。2026-09-30 已更新此安装包，包含字词细剪改造、导出目录修复及三个离线工作进程。

测试阶段使用免安装程序：当前构建可直接运行 `src-tauri/target/release/sliceai.exe`，保留旁边的整个 `worker` 文件夹。使用 `npm run build:portable` 更新测试程序，跳过安装包压缩；确认测试结果后再通过 `npm run bundle` 生成正式安装包。完整打包脚本另外收集的 `release/SliceAI-0.2.0/` 用于免安装测试，只有重新收集后才代表当前源码。

支持 Windows 10 / 11 x64，需要 WebView2；两种方式都不需要用户安装 Python 或 FFmpeg。

1. 左下角「设置」填写自己的 AI API 地址、模型和 Key。内容判断通过 API；转写在本地进行。SenseVoice INT8 转写模型及 Silero VAD 随软件内置，无需首次下载。
2. 导入录播，可选附加 UTF-8 的 SRT/VTT 转写及 XML/JSON 弹幕。多音轨素材可选择要分析的音轨，默认第一音轨；转写、声音处理、预览和导出使用同一选择。选择内容偏好和来源过滤，开始查找事件。
3. 结果默认先列出，按需预览、选择并导出。粗剪保持连续原区间、原构图和原声音，不新增字幕。使用 H.264/AAC 转码精确截取。
4. 进入「细剪」，通过五步选择确定剪辑要求。点击开始后生成有原文证据的候选，判断删减并复核完整故事，再生成预览。界面显示候选、被阻止和实际应用数量，以及原片到成片的真实时长；可查看删点的源相对时间、原文和理由。恢复已应用删点会创建新版本，重新映射字幕，需要确认后生成新预览。修改内容区间也需要重新确认。
5. 字幕可改字、拆分合并、调整时间；默认烧录，可关闭并选择另存 SRT。修改字幕后先保存草稿，再预览、切换版本或导出。改变保留区间后需检查切点附近字幕并重新确认；字幕核对标记提示原声和转写存在分歧。预览和正式导出使用同一方案。点击「导出成片」先选择保存文件夹，核对位置并选择是否另存字幕后开始导出；视频和字幕直接写入所选文件夹，完成后显示实际保存路径，可打开保存文件夹。取消目录选择不会导出。
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

2026-09-30 改造前软件实测：一个 429.398 秒事件走完标准细剪与导出后仍删除零秒，58 条字幕中 46 条待核对。媒体导出正常，精简和字幕质量未达标。此记录保留为历史基线。

同一事件在当前源码的真实界面重跑中，V2 应用 7 个删点、删除 2.09 秒；人工发现一个误判的重说删点，并通过界面恢复为 V3。V3 记录 82 个候选、16 个被阻止、6 个实际应用，计划时长 427.628 秒，实际删除 1.77 秒。真实界面预览、播放及 MP4 + SRT 导出已完成；成片时长 427.632683 秒，完整解码零错误，6 个删点均覆盖完整对齐字，源区间和字幕边界检查通过。63 项字幕中仍有 14 项待核对；逐句主观听辨、字幕质量及金标验收尚未通过，尚未认定整体细剪效果合格。实现、开源依据和未验证边界见 [细剪改造记录](docs/fine-editing-redesign.md)。

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

字词对齐是独立的可选离线环境；句内删点需要它提供可靠的字词起止。本次环境使用 Python 3.12、CPU 版 PyTorch 的 bfloat16 推理、固定的 Qwen3-ForcedAligner 权重和 safetensors 0.8.0 的 `pread` 读取方式。它只对候选相关窗口对齐，不引入 Qwen ASR，不替换 SenseVoice 转写。开发环境单独安装以下依赖；权重约 1.84 GB，仅下面显式准备命令会下载，应用运行时校验本地资产并禁用下载。若模型或子进程缺失、校验失败或对齐不完整，原始转写和粗剪仍可用，需要可靠字词边界的候选会被阻止并说明原因。全窗口对齐不完整时可以使用独立验证完整的局部窗口；无法完整覆盖目标字词或与保留语音重叠的切口会被阻止。

```powershell
py -3.12 -m venv .alignment-venv
.alignment-venv/Scripts/python.exe -m pip install -r backend/requirements-alignment-lock.txt
python -X utf8 scripts/prepare-alignment-model.py --download --dry-run
python -X utf8 scripts/prepare-alignment-model.py --download
# 离线导入可改用 --source-dir <已准备的权重目录>
.alignment-venv/Scripts/python.exe -X utf8 scripts/prepare-alignment-model.py --verify-only
```

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
.alignment-venv/Scripts/python.exe -X utf8 scripts/build-alignment.py
.alignment-venv/Scripts/python.exe -X utf8 scripts/build-alignment.py --verify-only
npm run bundle
.venv/Scripts/python.exe -X utf8 scripts/package-release.py --verify-only --require-alignment
.venv/Scripts/python.exe -X utf8 scripts/package-release.py --require-alignment
```

构建需要 Rust MSVC 工具链、Visual Studio C++ Build Tools，FFmpeg / FFprobe 在 PATH 中；音频、ASR 和字词对齐分别使用独立 Python 环境。先构建各子进程，测试时执行 `npm run build:portable`，正式打包执行 `npm run bundle`。测试程序依赖相邻的完整 `worker` 目录；后台源码或模型变化后，需要先更新对应的冻结工作进程。对齐构建的 `--dry-run` 仅显示计划，`--verify-only` 检查已有冻结资源并明确报告未构建；发布预检校验本地模型、对齐运行文件及许可证。发布脚本不会下载模型，完整字词细剪包使用 `--require-alignment` 阻止漏包；已有发布目录会保留为 `build/release-previous-*` 备份。`npm run dev` 只预览界面，桌面本地操作使用 `npm run desktop`。

BandIt 原项目采用 Apache-2.0，MSST 推理实现采用 MIT；本地适配说明和许可证保存在 `backend/bandit/`，完整包包含在 `worker/audio/licenses/`。独立对齐包的构建目标为 `worker/alignment/`，携带模型清单、逐文件校验清单、Qwen 的 Apache-2.0 许可证全文和安装 wheel 的第三方许可；模型卡声明 Apache-2.0，全文从 Qwen 软件 wheel 复制并标注来源。其他第三方组件见各 worker 的 `THIRD-PARTY-NOTICES.txt`。安装包未作代码签名。2026-09-30 已完成三个工作进程的冻结构建和离线运行检查，并在原路径更新 NSIS 安装包；真实剪辑质量与整场素材验收仍需继续。

## 回归与质量性能基线

GitHub Actions 分开运行前端构建/交互回归、Windows Python/DPAPI/FFmpeg 回归，以及独立音频环境的合成分块/重采样/缓存测试；CI 不下载大型模型、不调用真实 AI。

现有自动回归覆盖后端 176 项、前端 26 项、构建脚本 23 项；其中主环境跳过的五项声音测试由独立音频环境验证。免安装工作进程收集新增两项回归，构建脚本 23 项已完整复跑。上述真实素材的预览、导出和机械检查另行记录，自动回归通过不代表主观剪辑质量或字幕已经合格。

`python -X utf8 scripts/benchmark.py synthetic` 用固定 24 秒测试图案/纯音素材跑细剪预览和导出，保存时长、字幕元数据以及 CPU、进程树工作集、I/O 和输出目录占用。真实长录播可通过显式命令测量，再用独立标注和结果 JSON 计算漏剪、误选、重复、受保护内容误删及字幕时间误差。缺少 AI 结果或人工标注时记录“未测”，合成素材通过不代表实际内容识别质量。指标定义、命令与验收范围见 [验收基线](docs/acceptance.md)。

## 交互修复（2026-09-29）

进入细剪时优先打开已有片段，否则直接播放原录播的对应区间，播放器从 00:00 开始；查看不生成预览、不占用后台队列。只有不能直接播放的格式，才按需生成兼容副本。正式成片仍从原录播生成。降低背景音乐直接按所选要求处理，试听可选。任务列表支持删除任务，默认保留本地文件；勾选后删除本任务生成的缓存和导出文件，保留原录播、导入字幕、弹幕及其他任务引用的文件。运行中的任务须先停止。设置保存成功自动关闭，失败保留输入。

本轮整改与验证：[全面复核整改记录](docs/review-2026-09-30.md)。
