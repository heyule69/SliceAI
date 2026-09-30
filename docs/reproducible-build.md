# 可复现模型准备与构建

仓库包含经过适配的 BandIt 推理代码和固定资产清单，不包含模型权重、运行环境、已生成的 worker 或安装包。新机器不需要旧电脑的用户目录或测试素材。

## 固定资产

| 资产 | 固定来源/版本 | 校验方式 |
| --- | --- | --- |
| SenseVoice Small INT8 | sherpa-onnx `2024-07-17` 中文/英文/日语/韩语/粤语导出 | 解包后的 `model.int8.onnx`、`tokens.txt` 精确字节数与 SHA256 |
| Silero VAD | sherpa-onnx `asr-models/silero_vad.onnx`，643854 字节 | SHA256 `9e2449e1…`，以完整清单为准 |
| BandIt Plus DnR SDR 11.47 | MSST `v.1.0.3/model_bandit_plus_dnr_sdr_11.47.chpt`，148891175 字节 | SHA256 `c4828477…`；固定推理配置另行校验 |

完整 SHA256 位于 `scripts/model-assets/sensevoice.json` 和 `bandit-plus.json`，沿用已认可资产的校验值。公开 release 名称不是完整性保证；下载内容变化会被逐文件校验拒绝。ASR 压缩包不执行任意解包，只读取清单指定的普通文件，拒绝链接；许可证来自固定上游 commit，随仓库保存。BandIt 配置按原认可文件的 CRLF 字节重建，仍为 UTF-8 无 BOM，避免 Git 换行转换使 checksum 改变。

上游来源：[sherpa-onnx ASR release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models)、[SenseVoiceSmall](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)、[BandIt Plus weights release](https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/tag/v.1.0.3)。许可证和准确下载链接也写入固定清单。

## 准备资产

准备脚本仅使用 Python 标准库，不需 PyYAML，也不下载或替换推理源码。无参数时校验已经准备的资产；缺失时给出准备命令，不隐式联网。

```powershell
python -X utf8 scripts/prepare-asr-model.py --download --dry-run
python -X utf8 scripts/prepare-audio-model.py --download --dry-run
python -X utf8 scripts/prepare-asr-model.py --download
python -X utf8 scripts/prepare-audio-model.py --download
```

离线机器从显式目录导入；ASR 目录需含三份清单指定文件，BandIt 目录需含 `bandit-plus.chpt`。固定配置和许可证从仓库恢复，不依赖导入目录中的旧 manifest。

```powershell
python -X utf8 scripts/prepare-asr-model.py --source-dir D:/offline/SenseVoice
python -X utf8 scripts/prepare-audio-model.py --source-dir D:/offline/BandItPlus
python -X utf8 scripts/prepare-asr-model.py --verify-only
python -X utf8 scripts/prepare-audio-model.py --verify-only
```

目标默认为仓库下 `asr-model/SenseVoice` 和 `audio-model/BandItPlus`。`--destination` 可显式指定其他准备目录；应用构建仍使用上述默认目录。旧的 `scripts/vendor-bandit.py` 现在是声音资产准备的兼容入口，不再覆盖 `backend/bandit/`。

已有本地 ASR 资产如仍使用旧的许可证链接/换行，可以显式运行 `python -X utf8 scripts/prepare-asr-model.py --source-dir asr-model/SenseVoice`，从本地同一权重重建固定元数据和许可证，不需要再次下载模型。

脚本先在新建的隔离临时目录下载/导入并校验所有文件，再发布；错误下载不会覆盖旧资产。目标目录中不执行递归删除，模型权重保持 Git 忽略。验证下载器使用小型 mocked fixture，不会下载大模型：

```powershell
python -X utf8 -m unittest discover -s scripts -p test_model_assets.py -v
```

## 开发与完整构建

建议 Windows x64、Python 3.11、Node 22（至少 22.12）、Rust MSVC 和 Visual Studio C++ Build Tools。Python 依赖按 `backend/requirements*.txt` 的固定版本安装，前端用 `npm ci` 按 lockfile 安装。ASR 与声音依赖使用独立 venv；准备标准库脚本也可先在系统 Python 3.11+ 中运行。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
python -m venv .audio-venv
.audio-venv/Scripts/python.exe -m pip install -r backend/requirements-audio.txt
npm ci
npm run build
npm run test:frontend
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
.venv/Scripts/python.exe -X utf8 -m unittest discover -s scripts -p "test_*.py" -v
.audio-venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p "test_audio*.py" -v
.audio-venv/Scripts/python.exe -X utf8 scripts/build-audio.py
.alignment-venv/Scripts/python.exe -X utf8 scripts/build-alignment.py
.venv/Scripts/python.exe -X utf8 scripts/build-worker.py
npm run bundle
.venv/Scripts/python.exe -X utf8 scripts/package-release.py --require-alignment
```

FFmpeg/FFprobe 需在 PATH 中，至少具有 libx264、AAC 和 libass subtitles filter。CI 使用 [Gyan 固定 7.1.1 essentials release](https://github.com/GyanD/codexffmpeg/releases/tag/7.1.1)，记录版本；本地其他构建可用，但质量性能报告应保存准确版本和 build configuration。`build-worker.py` 会携带 PATH 中的工具，因此版本变更需要重新验收。源码/依赖/模型固定不表示安装包字节级一致，PyInstaller、Rust 工具链、操作系统和构建时间仍会影响产物。

`scripts/verify-bandit-integration.py` 是已有本机用户认可样本的专用工具；其样本不在 Git 中，不列为新机器构建的必需步骤。通用合成与真实标注验收见 [acceptance.md](acceptance.md)。构建脚本会写开发资源目录，执行完整构建前应确保没有运行中的客户端工作进程；本次代码修复不自动打包或替换已有客户端。

## 字词对齐与完整安装包

细剪完整构建还需要 `alignment-model/Qwen3-ForcedAligner-0.6B` 固定资产和独立 `.alignment-venv`。使用 `scripts/prepare-alignment-model.py` 准备资产，按 `backend/requirements-alignment-lock.txt` 创建独立依赖环境，再运行上述 `build-alignment.py`。具体离线模型约定见 [细剪改造](fine-editing-redesign.md)。打包使用 `--require-alignment`，避免把缺少对齐器的版本当作完整版发布。

`src-tauri/nsis-template.nsi` 基于 Tauri CLI 2.12.0 的安装模板，保留原安装、升级和卸载流程，只改为逐文件 LZMA 压缩。完整模型资源约 3.9 GB；默认固实压缩在本机触发 NSIS 大文件映射错误。模板来源和许可证随文件保存，后续更新 CLI 时需核对模板兼容性。原始模型与离线加载方式不变；NSIS 最终可执行文件仍受其大小限制，完整构建必须实际验证，不从便携目录大小推断能否打包。

冻结对齐进程须运行真实短音频探针；开发环境通过不能代替冻结验收。日文模块按实际属性访问延迟加载，冻结 PyTorch 的模块元数据检查不会触发它。识别、声音和对齐进程分别构建、验证后再生成安装包。

## 其他脚本的适用范围

`scripts/` 还保留历史验收和一次性迁移工具，不能把目录内所有脚本当成新机器的默认构建步骤。当前 41 个 Python 脚本按以下范围核验默认路径：

| 范围 | 脚本 | 默认输入与前置条件 |
| --- | --- | --- |
| 正式准备、构建、基线 | `prepare-asr-model.py`、`prepare-audio-model.py`、`vendor-bandit.py`、`model_assets.py`、`build-worker.py`、`build-audio.py`、`package-release.py`、`benchmark.py`、`test_model_assets.py`、`test_benchmark.py`、`build-brand-icons.py` | 模型按上文显式准备；构建消费本轮生成的资源；打包消费 Tauri 构建结果。基线合成输入和新测试 fixture 自行生成，真实验收输入由参数提供。图标重建是可选操作，读取已提交 SVG，额外需要 Pillow。 |
| 浏览器 QA 生成器 | `prepare-desktop-fixes-qa.py`、`prepare-startup-regression.py`、`prepare-fine-wizard-qa.py`、`prepare-ui-harness.py` | 生成到 `.test-artifacts/`；前三者自行构造 mock 状态。`prepare-ui-harness.py` 生成的页面另外读取旧 `release-smoke/result.json`，不属于通用前端回归入口。当前通用入口为 `npm run test:frontend`。 |
| 历史实录与模型对比 | `analyze-real-recording.py`、`recheck-real-recording.py`、`review-existing-events.py`、`test-fine-wizard-real.py`、`test-v02-real.py`、`test-real-recording.py`、`smoke-release.py`、`measure-memory.py`、`check-v02-audio-text.py`、`export-real-sample.py`、`verify-real-results.py`、`report-source-review.py`、`verify-bandit-integration.py`、`check-audio-cancellation.py`、`check-laughter-retention.py`、`find-laughter-sample.py`、`compare-audio-model.py`、`prepare-audio-comparison.py`、`run-audio-comparison.py`、`finish-audio-comparison.py`、`test-v02-audio.py`、`test-laughter-audio.py`、`package-audio-audition.py` | 默认路径仍依赖旧 `LOCALAPPDATA` 数据库/模型、未提交的录播和试听、`.test-artifacts/` 或 `test-results/`；部分对比工具涉及旧 MossFormer 或未固定的第三方模型下载。这些工具不在上述新机器流程或 CI 中，也不能用于证明当前源码的通用质量。新验收使用参数化 `benchmark.py`。 |
| 一次性源码迁移 | `finalize-v02-ui.py`、`upgrade-ui-v02.py`、`version-v02.py` | 会改写已提交源码；已完成的历史迁移，不作为构建或验收入口。 |

模型目录、worker、安装包和测试报告是声明过的输出产物，保持 Git 忽略；“不依赖旧产物”不表示可以跳过模型准备、依赖安装或构建顺序。本轮只静态核验历史工具，没有读取或运行它们对应的用户数据、旧录播或外部模型。
