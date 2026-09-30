"""Verify the known playback regression and prepare the real-result UI fixture."""
import json
import shutil
from pathlib import Path

root=Path(__file__).resolve().parents[1]
folder=root/'test-results/2026-08-28'
task=json.loads((folder/'来源复核结果.json').read_text(encoding='utf-8'))
before=json.loads((folder/'来源复核前.json').read_text(encoding='utf-8'))
assert task['status']=='complete'
assert {c['id'] for c in task['rejected_clips']}=={3,4,5}
assert {c['id'] for c in task['clips']}=={1,2,6,7,8,9,10,11,12}
assert len(task['exports'])==len(before['exports'])==12
assert sum(r.get('source_warning',False) for r in task['exports'])==3
assert all(Path(r['path']).is_file() and Path(r['subtitle']).is_file() for r in task['exports'])
assert all(c['source_review']['decision']=='keep' for c in task['clips'])
delta={k:v-before.get('api_usage',{}).get(k,0) for k,v in task['api_usage'].items()}
report=f'''# 播放内容误选修复 · v0.1.1

使用原来同一场 5 小时 29 分钟录播、同一份转写，对已有的 12 个候选进行来源复核。没有重跑 ASR 或全文分析。

结果：保留 **9 段**，排除 **3 段**。原录播与此前 12 个导出文件均保留；应用中已为其中 3 个历史导出标注“本次来源复核未通过”。

## 排除结果

'''
for clip in sorted(task['rejected_clips'],key=lambda c:c['id']):
    report+=f'- **{clip["title"]}**：{clip["source_review"]["reason"]}\n'
report+=f'''
## 判定方式与限制

每个候选在片段的 5%、23%、41%、59%、77%、95% 位置提取 6 张最长宽度 768 像素的 JPEG，连同该候选附近字幕交给用户配置的图片模型。本次使用 DeepSeek Flash，关闭思考模式。视频与音频不上传；会发送少量画面和文字。

排除纯播放、仅零星附和的内容。正常主播聊天需要真实字幕引用与画面证据；观看外部视频时，还要求有明确的实质评论证据。默认保守门槛：引用对应的估算发言时长至少 10 秒、占整段至少 20%。短引用只按所在 ASR 句子的文字占比估算，不能将一句吐槽充当整段主播发言。该估算不等于说话人分离；抽帧也可能漏掉画面变化。短而精彩的反应可能被排除，不能保证所有来源判定准确。

第三段短剧有约 7 秒可核对的主播评论，但整段约 109 秒，因此排除。没有通过“出现播放器就全部删除”来判断，也没有针对该主播的固定画面布局写规则。

API 不支持图片、抽帧失败或网络错误时，任务报告失败，未完成复核的片段不会导出。格式不合格或来源无法确认时暂不纳入。结果按录播文件信息、片段范围、字幕、API 地址与模型、提示版本缓存；重新复核和导出会重新校验缓存证据，避免重复计费。

## API 用量

- 新增请求：{delta['requests']} 次。
- 输入：{delta['prompt_tokens']:,} tokens；输出：{delta['completion_tokens']:,} tokens。
- 新增合计：**{delta['total_tokens']:,} tokens**。
- 含此前全文分析的累计用量：{task['api_usage']['total_tokens']:,} tokens。
- 调整本地贡献门槛后的复核使用缓存，未增加 API 请求。

## 工程验证

自动测试覆盖纯播放、零星附和、实质评论、正常聊天、缺失/杜撰证据、重复引用、缓存失效、候选补位、旧片段导出拦截、API 失败与取消。另有真实 FFmpeg 抽帧、MP4 / SRT 导出以及打包引擎端到端测试。

历史的 `测试报告.md` 与 `AI测试结果.json` 记录的是修复前那次分析；本文件与 `来源复核结果.json` 记录修复后的结果。
'''
(folder/'来源复核报告.md').write_text(report,encoding='utf-8')
fixture=json.loads(json.dumps(task))
assets=folder/'ui-assets';assets.mkdir(exist_ok=True)
for value in [fixture,*fixture['clips']]:
    path=Path(value['thumbnail'])
    if path.is_file():
        target=assets/path.name;shutil.copy2(path,target);value['thumbnail']=str(target)
(root/'.test-artifacts/real-ui-result.json').write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf-8')
html=(root/'index.html').read_text(encoding='utf-8').replace('<script type="module" src="/src/main.ts"></script>',
    '<script type="module" src="/.test-artifacts/real-ui-harness.js"></script>')
assert '/.test-artifacts/real-ui-harness.js' in html
(root/'.test-artifacts/real-ui-harness.html').write_text(html,encoding='utf-8')
print(json.dumps({'kept':len(task['clips']),'excluded':len(task['rejected_clips']),'new_usage':delta},ensure_ascii=False))
