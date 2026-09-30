from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
p=root/'index.html';s=p.read_text(encoding='utf-8')
s=s.replace('</head>','  <link rel="stylesheet" href="/src/fine.css">\n</head>')
s=re.sub(r'\s*<fieldset><legend>片段时长</legend>.*?</fieldset>','',s)
s=re.sub(r'\s*<fieldset><legend>导出形式</legend>.*?</fieldset>','',s)
s=s.replace('<label class="check-row"><input id="autoExport" type="checkbox" checked>完成后自动导出</label>','')
s=s.replace('添加字幕','已有转写').replace('<h2>切片选项</h2>','<h2>查找事件</h2>').replace('开始切片</button>','查找完整事件</button>')
s=s.replace('<section id="exportsPage"','<section id="finePage" class="page" hidden></section>\n        <section id="exportsPage"')
s=s.replace('v0.1.2','v0.2.0');p.write_text(s,encoding='utf-8')
p=root/'src/main.ts';s=p.read_text(encoding='utf-8')
s="import { FineWorkspace } from './fine';\n"+s
s=s.replace('type Clip = {','type Clip = { unfinished?: boolean;')
s=s.replace("let duration = 'smart', topics = ['自动判断'], output = 'separate',", "let topics = ['自动判断'],")
s=s.replace('const modal =',"const fine = new FineWorkspace(navigate,toast,refresh);\nconst modal =")
s=s.replace('  currentPage = page;',"  document.querySelectorAll<HTMLVideoElement>('video').forEach(v=>v.pause());\n  currentPage = page;")
s=s.replace("['processing','results'].includes(page)","['processing','results','fine'].includes(page)")
s=s.replace("results:'精彩片段'","results:'完整事件',fine:'对话细剪'")
s=s.replace("prefs:{duration,topics,output,auto_export:$<HTMLInputElement>('autoExport').checked,exclude_playback:","prefs:{topics,exclude_playback:")
s=s.replace("<small>${esc(c.category)}</small>","<small>${c.unfinished?'结尾未完 · ':''}${esc(c.reason||c.category)}</small>")
s=s.replace('<span title="AI 推荐程度，不是准确率">评分</span><span></span>','<span title="AI 推荐程度，不是准确率">评分</span><span></span><span></span>')
s=s.replace("${task.clips.map(c=>`<article", "${[...task.clips].sort((a,b)=>b.score-a.score).map(c=>`<article")
s=s.replace("${time(c.end-c.start).slice(3)}","${c.end-c.start>=3600?time(c.end-c.start):time(c.end-c.start).slice(3)}")
s=s.replace('<button class="row-preview" data-preview="${c.id}">预览</button></article>','<button class="row-preview" data-preview="${c.id}">预览</button><button class="fine-link" data-fine="${c.id}">细剪</button></article>')
s=s.replace(' 个片段</span><span id="selectionCount">',' 个事件</span><span id="selectionCount">')
start=s.index('function exportModal(');end=s.index('function settingsTab(',start)
s=s[:start]+'''function exportModal(id: string) {
 const ids=[...(selected.get(id)||[])];if(!ids.length){toast('请至少选择一个事件');return;}
 showModal(`<h2 class="modal-title">导出原片段</h2><p class="modal-description">${ids.length} 个独立视频 · 原画面、原声音</p><div class="modal-footer"><button class="secondary-button" data-action="close">取消</button><button class="primary-button" id="confirmExport">开始导出</button></div>`);
 $('confirmExport').onclick=()=>void guarded(async()=>{if(pending.has(id))return;await queue('export',id,{clip_ids:ids,mode:'separate',subtitle:'none'});closeModal();toast('已加入导出队列');});
}
'''+s[end:]
s=re.sub(r'<div class="modal-field"><label for="maxClips">.*?</div>','',s)
s=s.replace("['asr_threads','max_clips','chat_offset']","['asr_threads','chat_offset']")
s=s.replace('视频导出为 MP4，字幕单独保存为 SRT。','原片段导出为 MP4；字幕在细剪方案中设置。')
s=s.replace(" if(d.preview)"," if(d.fine)void guarded(()=>fine.load(currentTask,Number(d.fine)));\n if(d.preview)")
s=re.sub(r"for\(const group of \['durationChoices','outputChoices'\]\).*?;\n",'',s)
s=s.replace("'添加字幕':'添加弹幕'","'已有转写':'添加弹幕'")
s=s.replace('选择时长与内容偏好后开始。','选择内容偏好后开始。')
s=s.replace('查看预览，导出独立片段或合集。字幕单独保存为 SRT。','导出原片段，或进入细剪，与 AI 确定方向后确认方案、预览和导出。')
s=s.replace('每个候选发送 6 张缩略画面','分段发送少量缩略画面')
s=s.replace("  const e=event.payload;","  const e=event.payload;\n  if(e.cmd?.startsWith('edit_'))return;")
p.write_text(s,encoding='utf-8')
