# 真实细剪失败后的开源研究与改造提案

研究日期：2026-09-30。本文是源码阅读、真实产物复核和小样本可行性验证后的提案，尚未实现新的剪辑核心。

## 结论

需要把细剪从“按整条转写保留或删除”改成“字词时间轴、候选删点、全局故事复核、确定性执行”。先复用现有 SenseVoice / Silero 资产，再评估局部强制对齐器；提高静音阈值、强迫压缩比例或反复运行同一识别器不能解决核心问题。

推荐流程：

```mermaid
flowchart LR
    A[完整事件及原始音频] --> B[逐字转写与语音活动]
    B --> C[有来源引用的故事骨架]
    B --> D[停顿、重说和冗余候选]
    C --> E[AI 判断候选是否安全]
    D --> E
    E --> F[候选窗口精对齐与切口校验]
    F --> G[结构化保留及删除清单]
    G --> H[预览与导出共用时间轴]
    H --> I[检查真实接缝、字幕和故事覆盖]
```

## 本项目实测证据

当前源码开发客户端已实际走完向导、预览、播放和导出。429.398 秒事件仍保留一个完整区间，实际删除零秒；三个计划和三个复核的删除列表均为空。首个摘要提到删除重复，结构却没有删点，因此摘要必须从执行结果生成。

细转写五十八条中三十八条因粗细转写差异被禁止删除；四处规范化文字完全相同，仍因重新分句后的时间覆盖不足而被保护。当前识别输出只有 VAD 段落起止，五个段落达到十九至二十四秒，不能从其中独立删除小段重说。

混音轨的 `-45 dB / 2 秒` 低能量检测结果为空。原始细转写的相邻段落间却有十一处大于两秒的间隙，合计 43.512 秒。这只是**转写/VAD 间隙候选**，可能包含背景音乐、歌词和未识别的笑哭声，不能直接全部删除，也不能据此承诺缩短四十三秒。

### 已验证的低成本起点

本项目固定 `sherpa-onnx==1.12.40` 和已有 SenseVoice INT8 权重能返回 `tokens` 与 `timestamps`，当前 `backend/asr.py` 未保存它们。固定上游实现可见 [SenseVoice 转换](https://github.com/k2-fsa/sherpa-onnx/blob/v1.12.40/sherpa-onnx/csrc/offline-recognizer-sense-voice-impl.h) 和 [CTC 贪心解码器](https://github.com/k2-fsa/sherpa-onnx/blob/v1.12.40/sherpa-onnx/csrc/offline-ctc-greedy-search-decoder.cc)。

用同一真实录播的二十秒窗口，本机现有 CPU、双线程、已有模型得到六十八个 token 锚点；模型载入约 1.215 秒，单次推理约 0.388 秒。两个连续“就”的锚点分别是窗口内 11.58 和 12.60 秒，证明句内信息可以保留。这只是一次小窗口探针，不代表整场速度、识别准确度或安全切口已通过。

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

首选低成本准备：接出现有 token 发射锚点与 VAD 边界，保留逐字原文中的重复和口头语，建立时间信息完整性检查。锚点可帮助生成候选，连续讲话中的字词删除还须精对齐和切口复核。

建议实测 [Qwen3-ForcedAligner 独立接口](https://github.com/QwenLM/Qwen3-ASR#forcedaligner-usage)：输入音频、给定转写和语言，返回中文字符或英文词的开始/结束。可只对候选小窗口运行，保留 SenseVoice 粗转写，**不必同时引入 Qwen ASR**。官方标称最长五分钟，七分钟事件需要分段。权重约 1.84 GB，源码及模型卡为 Apache-2.0。[实现](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_forced_aligner.py)、[权重](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B/tree/main)。

其代码随模型 device 运行，CPU float32 可行属于源码推断；官方主要展示 GPU，**本机 Windows/CPU 速度和内存尚未实测**。应用前必须隔离依赖、固定接口版本与模型校验，不能自动下载后默认加入整场流程。

FunASR 最新 SenseVoice Python 也有 CTC 对齐，返回 `words + timestamp`；必须按原始对齐单位配对。[官方说明](https://github.com/modelscope/FunASR/blob/main/docs/python_api.md#consuming-sensevoice-alignment)。此路径需要对应的 PyTorch 权重和运行环境，不能把该参数直接加到本项目的 sherpa ONNX API。

强制对齐只把给定文本放到声音上，**不能证明文本正确**。可疑错字要使用音频重新识别和核对，不能让语言模型根据故事润色台词后再伪装成原话。

## 实施顺序与模块边界

1. **建立统一原始时间轴**：`backend/asr.py` 保存原始 token、发射锚点、VAD、模型身份及分段来源。显示字幕另存；旧段落转写继续可读。缓存身份加入新格式和模型版本，避免旧字幕缓存误充精确时间。
2. **先修局部保护**：`fine_auto.reconcile_audio` 区分相同音频重分句、识别差异、分离后实际丢声。单调文字/时间比较限制在局部；识别不确定作为字幕核对提示，实际丢声证据才阻断相应删点。不能取消所有笑哭及低声保护。
3. **独立生成候选**：本地规则定位短重说、明确重复、长间隙；每个候选保存原文 ID、来源时间、类别、证据。语气词是否表达强调由上下文判断；歌曲、笑哭和情绪沉默单列，不默认删除。
4. **全局故事到局部判断**：复用 `analysis_budget.grounded_outline` 生成有原文引用的事件节点，覆盖铺垫、冲突、因果、回应及结尾。AI 只判断候选及其局部上下文，返回原文 ID，最后复核合并清单对完整故事的影响。
5. **精对齐后执行**：需要句内剪的候选调用可替换的局部对齐器。缺少可靠结束边界、对齐异常或文字不对应音频时列为待确认。对安全切口做边距和短音频淡入淡出，预览、音频、字幕与导出共用源时间轴。
6. **展示真实效果**：`fine_auto.py` 与 `src/fine.ts` 显示候选、被阻止、实际应用及恢复动作；摘要由结构生成。实际零删除明确显示未产生精简和原因，不能仅凭生成了 MP4 宣称精简完成。

建议时间轴至少区分发射锚点和精对齐起止，记录对齐方法和来源。不具备可靠边界时保留空值；不伪造置信度，不把情绪模型标签当作确定事实。

## 验收标准

先复用本次完整事件，另外选带音乐、无音乐、重说、笑哭、混语小集，建立人工听辨确认的文字和可删范围。逐句听辨尚未完成，当前只是待建立的金标集。

建议目标：已确认的关键故事节点全部保留；不截断字尾、漏掉笑哭或改变原话；词/字边界误差以人工金标衡量，初始目标 95% 不超过 150 ms；人工确认的可删范围命中率初始目标至少 80%。这些是拟定的验收目标，不是已经测得的能力。

每个真实接缝都对比原声与成片，分别记录漏剪、误剪、字幕字错、边界误差和主观听感。报告区分候选与实际删除；不把强制缩短百分比当质量指标。导出和软件交互仍须重跑，单元测试通过不能替代真实素材验收。
