# 细剪改造：失败基线、开源研究与当前实现

研究及更新日期：2026-09-30。本文保留改造前的真实产物复核和开源研究依据，并记录当前源码及同段素材重跑状态。V3 的真实界面预览、导出和机械检查已完成，逐句听辨、字幕质量及金标验收尚未通过；已有安装包未替换。

## 结论

当前源码已接入字词时间轴、候选删点、完整故事复核和确定性区间执行。继续复用现有 SenseVoice / Silero 转写资产，由独立 Qwen3-ForcedAligner 环境提供候选窗口的字词起止；未验证的边界保留原声。对齐能提供定位，不能证明重复表达没有语义功能，真实素材仍需要检查误剪和字幕。

当前流程：

```mermaid
flowchart LR
    A[完整事件及原始音频] --> B[转写、语音活动与发射锚点]
    B --> C[有来源引用的故事骨架]
    B --> D[局部字词对齐与候选证据]
    C --> E[AI 判断候选是否安全]
    D --> E
    E --> F[已选语义删点对齐与切口校验]
    F --> G[完整故事复核与执行清单]
    G --> H[预览与导出共用时间轴]
    H --> I[检查真实接缝、字幕和故事覆盖]
```

## 改造前历史基线

改造前的源码开发客户端实际走完向导、预览、播放和导出。429.398 秒事件仍保留一个完整区间，实际删除零秒；三个计划和三个复核的删除列表均为空。首个摘要提到删除重复，结构却没有删点，因此摘要必须从执行结果生成。

当时五十八条细转写中三十八条因粗细转写差异被禁止删除，四十六条字幕待核对；四处规范化文字完全相同，仍因重新分句后的时间覆盖不足而被保护。当时应用只保存 VAD 段落起止，五个段落达到十九至二十四秒，无法从中独立定位小段重说。当前已保存发射锚点，并另外接入可靠字词起止校验。

混音轨的 `-45 dB / 2 秒` 低能量检测结果为空。原始细转写的相邻段落间却有十一处大于两秒的间隙，合计 43.512 秒。这只是**转写/VAD 间隙候选**，可能包含背景音乐、歌词和未识别的笑哭声，不能直接全部删除，也不能据此承诺缩短四十三秒。

### 已验证的低成本起点

本项目固定 `sherpa-onnx==1.12.40` 和已有 SenseVoice INT8 权重能返回 `tokens` 与 `timestamps`。改造前 `backend/asr.py` 未保存它们，当前源码已保留原始锚点和来源信息。固定上游实现可见 [SenseVoice 转换](https://github.com/k2-fsa/sherpa-onnx/blob/v1.12.40/sherpa-onnx/csrc/offline-recognizer-sense-voice-impl.h) 和 [CTC 贪心解码器](https://github.com/k2-fsa/sherpa-onnx/blob/v1.12.40/sherpa-onnx/csrc/offline-ctc-greedy-search-decoder.cc)。

用同一真实录播的二十秒窗口，本机现有 CPU、双线程、已有模型得到六十八个 token 锚点；模型载入约 1.215 秒，单次推理约 0.388 秒，证明句内锚点可以保留。这只是一次小窗口探针，不代表整场速度、识别准确度或安全切口已通过。

这些是 **CTC 发射时点，既不是词尾，也不是给定文本的强制对齐**。输出的 `durations`、`words`、声学分数为空。不能把下个 token 的时点当作当前 token 的真实结束，不能按字符数平均分配音频时间。标点、数字转换和字幕改字后的显示文本也不能直接逐字套 token 时间。

私人源路径、转写和本机探针只放在被忽略的 `.test-artifacts/`，不纳入公共仓库。

## 开源项目实际采用的方法

| 项目 | 已核对的机制 | 对本项目的价值与限制 |
| --- | --- | --- |
| [FastCut](https://github.com/bluebluegrass/FastCut) | 中文文字剪辑；默认 Qwen3 ASR 加 ForcedAligner，保存文字及起止。删除文字生成区间，再用 FFmpeg 同一路径预览和导出；结合 Silero 搜索切口。 | 最贴近中文句内剪辑的表示方式。作者对模型的优劣评价属于其项目经验，不能替代本素材实测。未发现声明的代码许可证，只研究方法。 |
| [transcriptcut](https://github.com/amide-init/transcriptcut) | 明确语气词先规则生成候选，含歧义的词结合局部上下文交给模型分类；模型返回既有 ID。停顿依据词时间间隙单独检测。 | 学习“候选先行、模型只判用途、工具执行”。现有语气词规则主要面向英文，需要中文专门验证。代码 MIT。 |
| [cobanov/autocut](https://github.com/cobanov/autocut) / [Silero VAD](https://github.com/snakers4/silero-vad) | 本地语音概率、启停迟滞、最小片段、边距与区间合并；缓存概率后调参数无需重复推理。 | 为混音中的无人说话间隔提供候选，优于只要求音轨低能量。VAD 仍可能把歌声当语音或漏掉笑哭，不能直接当作主播分离器。Silero MIT；autocut 未发现代码许可证。 |
| [Auto-Editor](https://github.com/WyattBlue/auto-editor) / [jumpcutter](https://github.com/carykh/jumpcutter) | 音量阈值生成活动时间轴，配合边距、最小保留/删除长度或加速静段。 | 学习稳定区间合并和边界处理。持续背景音乐仍可能使全段保留，不适合作为本项目唯一检测器。前者 Unlicense，后者 MIT。 |
| [mli/autocut](https://github.com/mli/autocut) | VAD、识别、Markdown 勾选字幕、按保留句子裁切。 | 识别与编辑决定分离；语义删什么由人确认，不能作为“自动理解直播故事”已解决的证据。Apache-2.0。 |
| [WhisperX](https://github.com/m-bain/whisperX) | 识别后由独立语言声学模型强制对齐，中文按字处理，允许 CPU。 | 可对现有转写的小窗口精对齐，但额外声学模型和 torch 等依赖较重，错转写、未知字符和重叠语音仍有失败边界。 |

直接源码证据：[FastCut 后端](https://github.com/bluebluegrass/FastCut/blob/main/main.py)、[transcriptcut 候选分类](https://github.com/amide-init/transcriptcut/blob/main/server/src/lib/ai/filler-words.ts)、[transcriptcut 词间隙](https://github.com/amide-init/transcriptcut/blob/main/client/src/lib/timeline/silence.ts)、[autocut VAD](https://github.com/cobanov/autocut/blob/main/src-tauri/src/vad.rs)、[autocut 区间](https://github.com/cobanov/autocut/blob/main/src-tauri/src/cutlist.rs)、[Auto-Editor 音频](https://github.com/WyattBlue/auto-editor/blob/master/src/analyze/audio.nim)、[WhisperX 对齐](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py)。

## 对齐器选择

现有 token 发射锚点与 VAD 边界作为轻量基础，保留转写中的重复和口头语，并检查时间信息完整性。锚点可帮助定位候选窗口，连续讲话中的字词删除仍需要可靠起止和切口复核。

当前接入 [Qwen3-ForcedAligner 独立接口](https://github.com/QwenLM/Qwen3-ASR#forcedaligner-usage)：输入音频、给定转写和语言，返回中文字符或英文词的开始/结束。只对候选相关窗口运行，保留 SenseVoice 转写，**未同时引入 Qwen ASR**。官方标称最长五分钟，本项目限制单次窗口最多三十二秒；全窗口无效时尝试候选附近更短的局部窗口。权重约 1.84 GB，源码及模型卡为 Apache-2.0。[实现](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_forced_aligner.py)、[权重](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B/tree/main)。

官方示例主要展示 GPU。本机 Windows/CPU 已完成源码中的局部窗口运行，采用 CPU bfloat16 和 safetensors 0.8.0 的 `pread` 读取；此前默认 mmap / float32 路径在本机测试中出现加载异常，未采用。依赖通过独立 `.alignment-venv` 隔离，接口、权重和校验值固定，运行时只加载已准备的本地模型。短窗口运行成功不等于全部字词边界合格，零时长、文字不对应或覆盖不完整的结果仍被拒绝。

FunASR 最新 SenseVoice Python 也有 CTC 对齐，返回 `words + timestamp`；必须按原始对齐单位配对。[官方说明](https://github.com/modelscope/FunASR/blob/main/docs/python_api.md#consuming-sensevoice-alignment)。此路径需要对应的 PyTorch 权重和运行环境，不能把该参数直接加到本项目的 sherpa ONNX API。

强制对齐只把给定文本放到声音上，**不能证明文本正确**。可疑错字要使用音频重新识别和核对，不能让语言模型根据故事润色台词后再伪装成原话。

## 已接入的模块边界

1. **统一原始时间轴**：`backend/asr.py` 保存原始 token、发射锚点、VAD、模型身份及分段来源。显示字幕另存，旧段落转写继续可读；缓存身份包含格式和模型版本。
2. **局部声音保护**：`fine_auto.reconcile_audio` 区分相同音频重分句、识别差异及分离后的局部丢声风险。识别分歧显示字幕核对提示；局部声音风险阻止相应删点，笑哭和音乐反应保留。
3. **候选及证据**：原有语音段生成语义候选，可靠字词窗口生成短重说、语气词候选；间隙还需要原始音频证据。每个候选保存唯一 ID、原文引用、源时间、类别和证据。模型只判断既有候选，不能创造时间或台词；连续重复仍可能有语义功能。
4. **完整故事复核**：`analysis_budget.grounded_outline` 生成有原文引用的事件节点，AI 判断候选及局部上下文后，再复核合并删点对完整故事的影响。关键节点保护和最终复核恢复内容后，整句删点会重新检查与保留语音的重叠，直到状态稳定。
5. **字词边界与执行**：需要字词起止的删点调用独立局部对齐器。缺少可靠结束、零时长、文字不对应或边界覆盖不完整时被阻止；一个完整局部窗口可独立使用，不把远处失败的字词伪装成已对齐。切口使用实测字词间隙内的边距，音频从连续 PCM 按源时间裁切并加短淡入淡出，再统一编码；预览、字幕和导出使用同一保留方案。
6. **真实统计与恢复**：界面展示候选、被阻止、实际应用及源时长到成片时长，按实际删除区间合并统计，零删减显示“未产生有效精简”及原因。每个已应用删点可查看源相对时间、原文和理由；恢复会建立新版本、重算删点账本并从源字幕重新映射，确认后再生成预览。手动改区间同样重算实际应用情况，历史版本保留。

时间轴区分发射锚点和强制对齐起止，记录方法及来源。不具备可靠边界时保留空值，不按字符平均分配；情绪模型标签只作参考，不作为确定事实。

## 实施情况

上述实现已经接入当前源码，开发客户端已通过真实界面重跑同一个 429.398 秒事件。此处记录执行事实，不将削减时长作为质量合格的判断依据。

| 阶段 | 实际应用删点 | 实际删除 | 方案时长 | 状态 |
| --- | ---: | ---: | ---: | --- |
| 改造前基线 | 0 | 0 秒 | 429.398 秒 | 当时完成预览和导出；精简未达标 |
| 新实现 V2 | 7 | 2.09 秒 | — | 人工发现一个误判的重说删点 |
| 恢复后 V3 | 6 | 1.77 秒 | 427.628 秒 | 通过界面恢复生成；预览、导出和机械检查完成 |

V3 共记录 82 个候选、16 个被阻止、6 个实际应用。恢复、预览生成、播放器播放及 MP4 + SRT 正式导出均已通过真实界面执行。导出媒体时长 427.632683 秒，与计划相差约 4.7 ms；全片解码零错误，视频为 1280 × 720 H.264，音频为 AAC、48 kHz、双声道、192 kbit/s。6 个删点均覆盖完整对齐字，源区间及字幕边界检查通过。成片测得真峰值 -1.43 dBTP、响度 -16.43 LUFS。

成片有 63 项字幕，其中 14 项仍待核对。上述检查证明当前方案能够生成、恢复和导出，并验证了编码和区间边界；逐句接缝听辨、字幕正确性、故事覆盖和独立金标验收尚未通过。本轮自动回归通过 206 项：后端 168 项、前端 17 项、构建脚本 21 项。

局部强制对齐是独立的可选离线环境，使用 `.alignment-venv` 与 `alignment_worker.py`，只处理候选相关的短窗口。Windows 源码探针使用 CPU bfloat16 和 safetensors 0.8.0 的 `pread` 读取方式，避开本机默认 mmap / float32 的加载异常；这项运行方式不等于精确边界已全部通过。模型和依赖采用固定版本；准备脚本允许显式下载或离线导入，运行时禁用下载并校验本地权重。模型、子进程缺失或对齐失败时保留原声，相关删点标为被阻止，基础转写和粗剪仍可使用。

构建接入 `scripts/build-alignment.py`：冻结目标为 `worker/alignment/sliceai-alignment.exe` 和相邻 `model/`，携带固定模型清单、完整校验清单、许可证和必要语言资源；发布脚本在复制前后检查本地资产，`--require-alignment` 阻止漏装字词对齐子进程。构建和发布入口的 `--dry-run` 不写文件，`--verify-only` 明确报告缺少冻结资源。本轮未构建新的冻结 runtime 或 NSIS 安装包，也没有替换已有 `release/` 客户端。

独立对齐环境、候选判断、整体复核、恢复及同素材预览导出已运行，真实细剪质量尚未完成验收。完整事件资源测量、冻结后离线运行、逐句接缝和字幕听辨仍须分别验证；下方数值继续作为拟定目标，不是已实现成绩。

## 验收标准

先复用本次完整事件，另外选带音乐、无音乐、重说、笑哭、混语小集，建立人工听辨确认的文字和可删范围。逐句听辨尚未完成，当前只是待建立的金标集。

建议目标：已确认的关键故事节点全部保留；不截断字尾、漏掉笑哭或改变原话；词/字边界误差以人工金标衡量，初始目标 95% 不超过 150 ms；人工确认的可删范围命中率初始目标至少 80%。这些是拟定的验收目标，不是已经测得的能力。

每个真实接缝都对比原声与成片，分别记录漏剪、误剪、字幕字错、边界误差和主观听感。报告区分候选与实际删除；不把强制缩短百分比当质量指标。V3 预览、导出及机械检查已完成，逐句主观听辨和金标验收仍未通过；单元测试通过不能替代真实素材验收。
