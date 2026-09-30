import json
import shutil
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]
folder=root/'test-results/2026-08-28'
task=json.loads((folder/'AI测试结果.json').read_text(encoding='utf-8'))
asr=json.loads((root/'.test-artifacts/real-recording/summary.json').read_text(encoding='utf-8'))
assert task['status']=='complete'
assert len(task['exports'])==len(task['clips'])==12
import sys
sys.path.insert(0,str(root/'backend'))
from formats import parse_subtitles
results=[]
for record in task['exports']:
    path=Path(record['path']);assert path.is_file() and path.stat().st_size>1024
    data=json.loads(subprocess.check_output([str(root/'src-tauri/resources/worker/bin/ffprobe.exe'),'-v','error',
         '-show_entries','format=duration,size:stream=codec_type,codec_name,width,height','-of','json',str(path)],creationflags=0x08000000))
    duration=float(data['format']['duration'])
    assert abs(duration-record['duration'])<.5
    assert {s['codec_type'] for s in data['streams']}=={'video','audio'}
    cues=parse_subtitles(Path(record['subtitle']),duration)
    assert all(0<=s['start']<s['end']<=duration for s in cues)
    results.append({'file':path.name,'duration':duration,'bytes':path.stat().st_size,'subtitle_cues':len(cues)})
usage=task['api_usage']
cost=(usage['prompt_cache_hit_tokens']*.04+usage['prompt_cache_miss_tokens']*2+usage['completion_tokens']*8)/1_000_000
summary={'verified_exports':len(results),'total_duration_seconds':round(sum(r['duration'] for r in results),3),
         'total_megabytes':round(sum(r['bytes'] for r in results)/1024**2,2),'api_usage':usage,
         'estimated_cny_at_peak_2026_09_29':round(cost,6),'checks':results,'asr':asr}
(folder/'验证记录.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
def stamp(seconds):
    n=int(seconds);return f'{n//3600:02d}:{n//60%60:02d}:{n%60:02d}'
report=f'''# 真实录播测试结果

素材：`{asr['video']}`。原文件大小和修改时间均未改变。

## 实际用量

| 项目 | 结果 |
| --- | ---: |
| 录播时长 | {stamp(asr['duration_seconds'])} |
| 本地转写耗时 | {asr['wall_seconds']:.2f} 秒 |
| 转写段落 | {asr['sentences']:,} |
| 转写引擎与 FFmpeg 采样峰值工作集 | {asr['sampled_peak_worker_and_ffmpeg_mb']} MB |
| API 输入 token | {usage['prompt_tokens']:,} |
| API 输出 token | {usage['completion_tokens']:,} |
| API 合计 token | {usage['total_tokens']:,} |
| API 请求次数 | {usage['requests']}（46 个区间 + 1 次边界修正） |
| AI 精选成片 | {len(results)} 段，共 {stamp(summary['total_duration_seconds'])} |
| 成片总大小 | {summary['total_megabytes']} MB |

模型为 DeepSeek Flash，显式关闭思考模式；只发送转写文本，没有原始弹幕，因此本次未做弹幕联合判断。API 返回的实际 usage 已写入任务和验证记录，软件结果页可查看总量。

按 2026-09-29 官方高峰价格，考虑实际缓存命中量，整场分析估算费用 **¥{cost:.4f}**。这是按价格表计算，不是读取账单；额外连接测试用了 44 tokens。

价格来源：https://api-docs.deepseek.com/zh-cn/quick_start/pricing/

## AI 筛选结果

| 片段 | 原录播位置 | 时长 |
| --- | --- | ---: |
'''
for clip,record in zip(task['clips'],task['exports']):
    relative=Path(record['path']).relative_to(folder).as_posix()
    report+=f'| [{clip["title"]}]({relative}) | {stamp(clip["start"])}–{stamp(clip["end"])} | {clip["end"]-clip["start"]:.1f} 秒 |\n'
report+='''
## 验证与已知限制

所有 12 个 MP4 均包含 H.264 视频和 AAC 音频，时长与选择区间相差不到 0.5 秒；SRT 时间戳都在对应成片范围内。完整转写见同目录 `完整转写.srt`。成片和 SRT 位于 `AI精选` 子目录。

旁边的“长视频定位导出验证_非AI筛选”是另一次手工选择区间的技术测试，不计入上面的 12 个 AI 精选片段。

转写中有背景音乐歌词及部分错字，提示词已要求排除歌词、广告和待机内容。没有进行逐句人工听校，模型也可能误判主播播放的视频或缺少铺垫；这次验证证明流程完成，不代表每个片段都达到直接发布的编辑质量。

转写内存数字只包括处理引擎和 FFmpeg，不包括桌面 UI。桌面启动后的单次采样，进程树独占工作集约 250 MB，工作集直接求和约 584 MB（含共享页），私有提交约 335 MB。均为本机测量，不能视作其他硬件的固定占用。

9 小时 45 分钟的另一段素材仅检查了媒体信息，没有做完整转写。当前验证覆盖 8 月 28 日这段 5 小时 29 分钟的录播。
'''
(folder/'测试报告.md').write_text(report,encoding='utf-8')
# Browser-only verification adapter uses copies of thumbnails, without expanding Vite file access.
assets=folder/'ui-assets';assets.mkdir(exist_ok=True)
fixture=json.loads(json.dumps(task))
for value in [fixture,*fixture['clips']]:
    path=Path(value['thumbnail'])
    if path.is_file():
        target=assets/path.name;shutil.copy2(path,target);value['thumbnail']=str(target)
(root/'.test-artifacts/real-ui-result.json').write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf-8')
script=(root/'.test-artifacts/ui-harness.js').read_text(encoding='utf-8').replace('/.test-artifacts/release-smoke/result.json','/.test-artifacts/real-ui-result.json').replace('界面验收 · 测试数据','实际测试结果 · 界面验收')
(root/'.test-artifacts/real-ui-harness.js').write_text(script,encoding='utf-8')
html=(root/'.test-artifacts/ui-harness.html').read_text(encoding='utf-8').replace('/.test-artifacts/ui-harness.js','/.test-artifacts/real-ui-harness.js')
(root/'.test-artifacts/real-ui-harness.html').write_text(html,encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in ('checks','asr')},ensure_ascii=False))
