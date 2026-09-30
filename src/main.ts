import { SegmentPlayer, type Playback } from './segment-player';
import { FineWorkspace } from './fine';
import { invoke, convertFileSrc, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';
import { open } from '@tauri-apps/plugin-dialog';
import { reconcileTaskRows, patchHTML } from './task-list';
import { bindImportedVideo, sameImportedVideo, globalActivity, type QueueEntry } from './workspace-state';

type Clip = { unfinished?: boolean; source_review?: { decision: string; reason: string }; id: number; title: string; start: number; end: number; category: string; reason: string; score: number; thumbnail: string; preview: string };
type Export = { source_warning?: boolean; id: string; path: string; subtitle: string; duration: number; mode: string; created: string };
type Task = { audio_track?: number; media?: Media; rejected_clips?: Clip[]; source_review_summary?: { checked: number; excluded: number; held: number; unreviewed: number }; id: string; title: string; video: string; duration: number; created: string; status: string; stage: string; progress: number; error: string; thumbnail: string; clips: Clip[]; exports: Export[]; prefs: { output: string; exclude_playback?: boolean }; api_usage?: { requests: number; prompt_tokens: number; completion_tokens: number; total_tokens: number } };
type Settings = { api_base: string; api_model: string; api_json_mode: boolean; key_saved: boolean; output_dir: string; asr_threads: number; max_clips: number; chat_offset: number; asr_model_dir: string; ffmpeg_path: string; ffprobe_path: string };
type State = { edits?: { id:string; task_id:string; title:string; status?:string; exports:Export[] }[]; settings: Settings; tasks: Task[]; model: { ready: boolean; path: string }; data_dir: string; tools: Record<string,string> };
type AudioTrack = { index:number; title?:string; language?:string; channels?:number; default?:boolean };
type Media = { audio_tracks?:AudioTrack[]; path: string; name: string; duration: number; width: number; height: number; size: number; thumbnail: string };
const native = isTauri();
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const icon = (name: string) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const asset = (path: string) => path && native ? convertFileSrc(path) : '';
const filename = (path: string) => path.split(/[\\/]/).pop() || path;
const time = (seconds: number) => { const n = Math.max(0, Math.floor(seconds)); return `${Math.floor(n/3600).toString().padStart(2,'0')}:${Math.floor(n/60)%60}`.replace(/:(\d)$/,':0$1') + `:${(n%60).toString().padStart(2,'0')}`; };
const date = (value: string) => new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const active = new Set(['queued','probing','transcribing','analyzing','rendering','exporting','cancelling']);
let state: State | null = null, media: Media | null = null, subtitle = '', chat = '', currentTask = '', currentPage = 'home', filter = 'all';
let audioTrack=0, queueEntries:QueueEntry[]=[],queueRevision=-1;
let topics = ['自动判断'], importing = false, starting = false;
let modalPlayer:SegmentPlayer|null=null;
let previewToken = 0, toastTimer: ReturnType<typeof setTimeout>;
const pending = new Set<string>(), selected = new Map<string,Set<number>>();
const initialDrop = $('dropzoneContent').innerHTML;
const fine = new FineWorkspace(navigate,toast,refresh,updateActivity);
const modal = $<HTMLDialogElement>('modal');

function toast(message: unknown) { $('toast').textContent = String(message); $('toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('visible'), 6500); }
function nativeOnly() { if (!native) { toast('这是界面预览。请打开 SliceAI 桌面程序使用本地文件和自动切片。'); return false; } return true; }
async function call<T>(cmd: string, values: Record<string,unknown> = {}): Promise<T> { return invoke<T>('call',{ request: {cmd,...values} }); }
async function refresh() { if (native) applySnapshot(await call<State>('state')); }
function applySnapshot(snapshot:State) {
  state=snapshot;
  for(const id of pending)if(!state.tasks.some(t=>t.id===id&&active.has(t.status))&&!queueEntries.some(q=>q.task_id===id))pending.delete(id);
  renderLists();updateStart();
  if(currentTask&&['processing','results'].includes(currentPage)){const task=state.tasks.find(t=>t.id===currentTask);if(task)renderTask(task);}
}
function updateActivity(){
  const edits=[...(state?.edits||[])];
  if(fine.p){const index=edits.findIndex(p=>p.id===fine.p!.id);if(index>=0)edits[index]={...edits[index],status:fine.p.status};else edits.push({id:fine.p.id,task_id:fine.p.task_id,title:fine.p.title,status:fine.p.status,exports:[]});}
  $('appStatus').textContent=globalActivity(state?.tasks||[],edits,queueEntries);
  $('appStatus').title='查看处理队列并定位任务';
}
function applyQueue(snapshot:{queue:QueueEntry[];queue_revision?:number}){
  const revision=snapshot.queue_revision??queueRevision+1;if(revision<queueRevision)return;
  queueRevision=revision;queueEntries=snapshot.queue;updateActivity();fine.updateQueue(queueEntries);
}
function showActivity(){
  const rows=queueEntries.map(q=>{
    const task=state?.tasks.find(t=>t.id===q.task_id),project=state?.edits?.find(p=>p.id===q.project_id);
    const label=project?.title||task?.title||'后台处理';
    return `<div class="queue-row"><span>${q.status==='running'?'处理中':`排队第 ${q.position} 项`} · ${esc(label)}</span>${q.project_id?`<button class="text-button" data-open-project="${esc(q.project_id)}">查看细剪</button>`:q.task_id?`<button class="text-button" data-task="${esc(q.task_id)}" data-action="close">查看任务</button>`:''}</div>`;
  });
  if(!rows.length){for(const task of state?.tasks||[])if(active.has(task.status))rows.push(`<div class="queue-row"><span>${esc(task.stage||statusNames[task.status])} · ${esc(task.title)}</span><button class="text-button" data-task="${esc(task.id)}" data-action="close">查看任务</button></div>`);for(const p of state?.edits||[])if(['busy','queued'].includes(p.status||''))rows.push(`<div class="queue-row"><span>细剪处理中 · ${esc(p.title)}</span><button class="text-button" data-open-project="${esc(p.id)}">查看细剪</button></div>`);}
  showModal(`<h2 class="modal-title">处理队列</h2>${rows.join('')||'<p class="modal-description">暂无处理中的任务。</p>'}`);
}
function updateAttachments(){
  for(const kind of ['subtitle','chat'] as const){const value=kind==='subtitle'?subtitle:chat;$(`${kind}Name`).textContent=value?filename(value):kind==='subtitle'?'已有转写':'添加弹幕';$(`${kind}Button`).title=value|| (kind==='subtitle'?'可选 SRT / VTT 字幕':'可选 XML / JSON 弹幕');$(`${kind}Remove`).hidden=!value;}
}
function removeAttachment(kind:'subtitle'|'chat'){if(starting||importing)return;if(kind==='subtitle')subtitle='';else chat='';updateAttachments();updateStart();}
function trackLabel(track:AudioTrack){return `音轨 ${track.index+1}${track.title?' · '+track.title:''}${track.language?' · '+track.language:''}${track.channels?' · '+track.channels+' 声道':''}`;}
function renderAudioTracks(){
  const tracks=media?.audio_tracks||[];$('audioTrackField').hidden=!tracks.length;
  if(!tracks.some(t=>t.index===audioTrack))audioTrack=tracks[0]?.index||0;
  $<HTMLSelectElement>('audioTrack').innerHTML=tracks.map(t=>`<option value="${t.index}" ${t.index===audioTrack?'selected':''}>${esc(trackLabel(t))}</option>`).join('');
}
function taskTrack(task:Task){const index=task.audio_track||0;const track=task.media?.audio_tracks?.find(t=>t.index===index);return track?trackLabel(track):`音轨 ${index+1}`;}
function showModal(html: string, wide = false) { modalPlayer?.destroy();modalPlayer=null;previewToken++; modal.classList.toggle('preview-dialog',wide); modal.classList.remove('settings-dialog'); $('modalContent').innerHTML = html; if (!modal.open) modal.showModal(); }
function closeModal() { previewToken++; modal.querySelector('video')?.pause(); modal.close(); }
modal.addEventListener('close',() => { modalPlayer?.destroy();modalPlayer=null;previewToken++; modal.querySelector('video')?.pause(); $('modalContent').innerHTML = ''; });
modal.addEventListener('click',event => { if(event.target===modal){const r=modal.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeModal();} });

function navigate(page: string) {
  const leavingFine=currentPage==='fine'&&page!=='fine';
  if(leavingFine)fine.leave();
  document.querySelectorAll<HTMLVideoElement>('video').forEach(v=>v.pause());
  currentPage = page;
  document.querySelectorAll<HTMLElement>('.page').forEach(el => el.hidden = el.id !== `${page}Page`);
  document.querySelectorAll('.sidebar [data-page]').forEach(el => el.classList.toggle('active',el.getAttribute('data-page') === (['processing','results','fine'].includes(page) ? 'tasks' : page)));
  $('pageBreadcrumb').textContent = ({home:'新建切片',tasks:'全部任务',exports:'导出记录',processing:'正在处理',results:'完整事件',fine:'智能细剪'} as Record<string,string>)[page] || '';
  if(page==='exports'||page==='tasks') renderLists();
  if(leavingFine&&page==='results'&&fine.p){currentTask=fine.p.task_id;const task=state?.tasks.find(t=>t.id===currentTask);if(task)renderTask(task);}
  $('pageContent').scrollTop=0;
}
function updateStart() {
  $<HTMLButtonElement>('startButton').disabled = !media || importing || starting || (native && !state);
  $('startHint').textContent = importing ? '读取中…' : !media ? '请选择录播' : !state?.settings.key_saved ? '请先配置 API' : !subtitle && !state?.model.ready ? '请准备本地模型或添加字幕' : '已就绪';
  for(const id of ['subtitleButton','chatButton','subtitleRemove','chatRemove','audioTrack'])($(id) as HTMLButtonElement|HTMLSelectElement).disabled=importing||starting;
}
async function pick(extensions: string[], directory = false): Promise<string|null> {
  if(!nativeOnly()) return null;
  const result = await open({multiple:false,directory,filters:directory?undefined:[{name:'支持的文件',extensions}]});
  return typeof result==='string' ? result : null;
}
async function importVideo(path?: string) {
  if(importing||starting) return;
  const value = path || await pick(['mp4','mkv','flv','mov','webm','avi','m4v','ts']); if(!value) return;
  const previousMedia=media,previousHTML=$('dropzoneContent').innerHTML;
  importing=true; updateStart();
  $('dropzoneContent').innerHTML = `${icon('film')}<h3>正在读取录播…</h3><p>${esc(filename(value))}</p>`;
  try {
    const result = await call<Media>('probe',{path:value});
    const files=bindImportedVideo({video:media?.path||'',subtitle,chat,audioTrack},result.path);
    const removed=!!(subtitle&&!files.subtitle||chat&&!files.chat);subtitle=files.subtitle;chat=files.chat;audioTrack=files.audioTrack;media=result;
    updateAttachments();renderAudioTracks();if(removed)toast('录播已更换，上一录播的字幕和弹幕已移除。');
    $('dropzoneContent').innerHTML = `<div class="imported-media">${result.thumbnail?`<img src="${esc(asset(result.thumbnail))}" alt="录播预览">`:icon('film')}<h3>${esc(result.name)}</h3><p>${time(result.duration)} <i>·</i> ${result.width} × ${result.height} <i>·</i> ${(result.size/1024**3).toFixed(2)} GB</p><span class="text-button blue">点击更换录播</span></div>`;
  } catch(error) { $('dropzoneContent').innerHTML=previousHTML||initialDrop;media=previousMedia;renderAudioTracks();toast(error); }
  finally { importing=false; updateStart(); }
}
async function attachment(kind: 'subtitle'|'chat') {
  if(importing||starting)return;const source=media?.path||'';
  const value=await pick(kind==='subtitle'?['srt','vtt']:['xml','json']);if(!value)return;
  if(!sameImportedVideo(source,media?.path||'')||importing){toast('录播已变化，请重新选择附件。');return;}
  if(kind==='subtitle')subtitle=value;else chat=value;
  updateAttachments();updateStart();
}
async function startTask() {
  if(!nativeOnly()||!media||starting)return;
  const input={video:media.path,subtitle,chat,audio_track:audioTrack,prefs:{topics:[...topics],exclude_playback:$<HTMLInputElement>('excludePlayback').checked}};
  starting=true;updateStart();
  try {
   // A startup event or another window may leave the displayed status stale.
   // Check current saved prerequisites before deciding whether settings are needed.
   await refresh();
   if(!state?.settings.key_saved){await settingsModal('ai','尚未保存 API Key，请保存后再开始。');return;}
   if(!input.subtitle&&!state.model.ready){await settingsModal('local','内置转写模型不完整，请重新安装完整版，或添加已有转写。');return;}
   const task=await call<Task>('create_task',input);upsert(task);await queue('run',task.id);showTask(task.id);
  }
  catch(error){toast(error);}finally{starting=false;updateStart();}
}
function upsert(task: Task) {if(!state)return; const index=state.tasks.findIndex(t=>t.id===task.id);if(index<0)state.tasks.unshift(task);else state.tasks[index]=task;renderLists();if(currentTask===task.id&&['processing','results'].includes(currentPage))renderTask(task);}
async function queue(cmd: string, taskId?: string, extra: Record<string,unknown>={}) {
  if(taskId)pending.add(taskId);
  try{await invoke('enqueue',{request:{cmd,task_id:taskId,...extra}});}catch(e){if(taskId)pending.delete(taskId);throw e;}
}
const statusNames: Record<string,string>={queued:'等待处理',probing:'读取录播',transcribing:'本地转写',analyzing:'AI 分析',rendering:'生成片段',exporting:'导出中',complete:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断',cancelling:'取消中'};
function taskRow(task: Task) {
 return `<div class="task-row"><div class="task-source"><div class="task-thumb">${task.thumbnail?`<img src="${esc(asset(task.thumbnail))}" alt="">`:icon('film')}</div><div><div class="task-title" title="${esc(task.title)}">${esc(task.title)}</div><div class="task-meta"><span>${date(task.created)}</span><span>${task.duration?time(task.duration):'待读取'}</span><span title="${esc(taskTrack(task))}">${esc(taskTrack(task))}</span></div></div></div><div class="task-result">${task.clips.length?`<b>${task.clips.length}</b> 个片段`:'—'}</div><span class="task-status ${task.status==='complete'?'complete':''}">${esc(statusNames[task.status]||task.status)}</span><button class="task-action" data-task="${task.id}">${active.has(task.status)?'查看进度':'查看结果'} ${icon('chevron')}</button><button class="task-delete" data-delete-task="${task.id}" title="删除任务" aria-label="删除任务：${esc(task.title)}">删除</button></div>`;
}
function renderLists() {
 const tasks=state?.tasks||[];updateActivity(); $('taskCount').textContent=String(tasks.length);$('recentCount').textContent=String(tasks.length);
 const empty='<div class="empty-state">暂无任务</div>';
 reconcileTaskRows($('recentTasks'),tasks.slice(0,2).map(t=>({id:t.id,html:taskRow(t)})),empty);
 const query=$<HTMLInputElement>('taskSearch').value.toLowerCase();
 reconcileTaskRows($('allTasks'),tasks.filter(t=>(filter==='all'||t.status===filter)&&t.title.toLowerCase().includes(query)).map(t=>({id:t.id,html:taskRow(t)})),'<div class="empty-state">没有符合条件的任务</div>');
 const exportsHTML=tasks.flatMap(task=>task.exports.map(record=>`<div class="export-record">${icon('film')}<div><h3>${esc(filename(record.path))}</h3>${record.source_warning?'<span class="source-history-warning">历史导出 · 本次来源复核未通过</span>':''}<p>${esc(task.title)} · ${record.mode==='compilation'?'精彩合集':'独立片段'} · ${time(record.duration)} · ${date(record.created)}</p><p class="file-location">${esc(record.path)}</p></div><button class="secondary-button" data-reveal="${task.id}">打开文件夹 ${icon('folder')}</button></div>`)).join('');
 const fineExports=(state?.edits||[]).flatMap(p=>p.exports.map(r=>`<div class="export-record fine-export">${icon('film')}<div><h3>${esc(filename(r.path))}</h3><p>${esc(p.title)} · 细剪成片 · ${time(r.duration)}</p><p class="file-location">${esc(r.path)}</p></div><button class="secondary-button" data-reveal-project="${esc(p.id)}" data-reveal-export="${esc(r.id)}">打开文件夹</button></div>`)).join('');
 patchHTML($('exportRecords'),fineExports+exportsHTML||'<div class="empty-state">暂无导出记录</div>');
}
function deleteTaskModal(id:string){
 const task=state?.tasks.find(t=>t.id===id);if(!task)return;
 if(active.has(task.status)||pending.has(id)){toast('请先取消任务，等待处理停止后再删除');return;}
 showModal(`<h2 class="modal-title">删除任务？</h2><p class="modal-description">${esc(task.title)}</p><p class="settings-caption">同时移除该任务的细剪项目和导出记录。</p><label class="check-row delete-files-choice"><input id="deleteTaskFiles" type="checkbox">同时删除生成的本地文件</label><p class="settings-caption">包含转写缓存、预览和导出视频。原录播、导入的字幕和弹幕始终保留。</p><div class="modal-footer"><button class="secondary-button" data-action="close">取消</button><button class="primary-button danger-button" id="confirmDeleteTask">删除任务</button></div>`);
 const checkbox=$<HTMLInputElement>('deleteTaskFiles'),button=$<HTMLButtonElement>('confirmDeleteTask');
 button.onclick=()=>void guarded(async()=>{
  button.disabled=true;
  try{
   const removed=await call<{edit_ids:string[]}>('delete_task',{task_id:id,delete_files:checkbox.checked});
   for(const editId of removed.edit_ids){localStorage.removeItem('fine-choices:'+editId);fine.clearDrafts(editId);}
   selected.delete(id);pending.delete(id);if(currentTask===id){currentTask='';fine.p=null;}
   closeModal();await refresh();navigate('tasks');toast(checkbox.checked?'任务和生成文件已删除':'任务已删除，本地文件已保留');
  }finally{button.disabled=false;}
 });
}
function showTask(id: string) {const task=state?.tasks.find(t=>t.id===id);if(!task){toast('任务列表已变化，请重新打开任务列表');return;}currentTask=id;renderTask(task);}
function renderTask(task: Task) {
 const processing=active.has(task.status), page=processing?'processing':'results';
 if(currentPage!==page)navigate(page);
 if(processing){
  const content=$('processingContent');
  if(content.dataset.taskId!==task.id||!content.querySelector('.processing-card')){content.dataset.taskId=task.id;content.innerHTML=`<div class="processing-top"><button class="text-button" data-page="tasks">${icon('back')} 任务</button></div><section class="processing-card"><div class="processing-source">${task.thumbnail?`<img src="${esc(asset(task.thumbnail))}" alt="">`:icon('film')}<div title="${esc(task.title)}">${esc(task.title)}<small>${task.duration?time(task.duration):'读取中'}</small></div></div><div class="progress-label"><span>${esc(task.stage)}</span><b>${Math.round(task.progress)}%</b></div><div class="progress-track" role="progressbar" aria-label="任务进度" aria-valuenow="${task.progress}" aria-valuemin="0" aria-valuemax="100"><div style="width:${Math.max(0,Math.min(100,task.progress))}%"></div></div><div class="process-steps">${[['probing','读取'],['transcribing','转写'],['analyzing','分析与复核'],['exporting','导出']].map(([key,label])=>`<span class="process-step ${task.status===key?'active':''}">${label}</span>`).join('')}</div><div class="processing-bottom"><span>可切换页面，关闭程序将停止任务</span><button class="text-button" data-cancel="${task.id}">取消任务</button></div></section>`;
  }
  const amount=Math.max(0,Math.min(100,task.progress));
  content.querySelector('.progress-label span')!.textContent=task.stage;
  content.querySelector('.progress-label b')!.textContent=`${Math.round(amount)}%`;
  const track=content.querySelector<HTMLElement>('.progress-track')!;track.setAttribute('aria-valuenow',String(amount));track.firstElementChild!.setAttribute('style',`width:${amount}%`);
  content.querySelectorAll('.process-step').forEach((el,i)=>el.classList.toggle('active',['probing','transcribing','analyzing','exporting'][i]===task.status));
  patchHTML(content.querySelector<HTMLElement>('.processing-source')!,`${task.thumbnail?`<img src="${esc(asset(task.thumbnail))}" alt="">`:icon('film')}<div title="${esc(task.title)}">${esc(task.title)}<small>${task.duration?time(task.duration):'读取中'}</small></div>`);

  return;
 }
 if(!selected.has(task.id))selected.set(task.id,new Set(task.clips.map(c=>c.id)));
 const picks=selected.get(task.id)!;
 for(const id of picks)if(!task.clips.some(c=>c.id===id))picks.delete(id);
 const rejected=task.rejected_clips?.length||0;
 const reviewLabel=task.source_review_summary?(rejected?`已过滤 ${rejected} 段`:'来源已复核'):'来源复核';
 $('resultsContent').innerHTML=`<header class="result-header"><button class="icon-button" data-page="tasks" aria-label="返回任务">${icon('back')}</button><div class="result-title"><h1 title="${esc(task.title)}">${esc(task.title)}</h1><p>${time(task.duration)} · ${esc(taskTrack(task))} · ${esc(statusNames[task.status]||'处理结果')}</p></div>${task.clips.length?`<button class="primary-button" id="exportSelection" data-export="${task.id}" ${pending.has(task.id)||!picks.size?'disabled':''}>${icon('download')} 导出所选</button>`:''}</header>${task.error?`<div class="error-note">${esc(task.error)}</div>`:''}${task.status!=='complete'||!task.clips.length?`<div class="retry-bar"><span>${esc(task.stage)}</span><button class="secondary-button" data-retry="${task.id}">重新处理</button></div>`:''}<div class="result-toolbar"><span class="count">${task.clips.length} 个事件</span><span id="selectionCount">已选 ${picks.size}</span><button class="review-button" data-review-details="${task.id}">${reviewLabel} ${icon('chevron')}</button></div>${task.clips.length?`<div class="result-table"><div class="clip-columns clip-head"><label><input type="checkbox" id="selectAll" aria-label="全选片段" ${picks.size===task.clips.length?'checked':''}></label><span></span><span>片段</span><span>原录播位置</span><span>时长</span><span title="AI 推荐程度，不是准确率">评分</span><span></span><span></span></div><div class="scroll-area" id="clipRows">${[...task.clips].sort((a,b)=>b.score-a.score).map(c=>`<article class="clip-row clip-columns"><label><input type="checkbox" data-pick="${c.id}" aria-label="选择 ${esc(c.title)}" ${picks.has(c.id)?'checked':''}></label><button class="clip-thumb" data-preview="${c.id}" aria-label="预览 ${esc(c.title)}">${c.thumbnail?`<img src="${esc(asset(c.thumbnail))}" alt="" loading="lazy">`:''}${icon('play')}</button><button class="clip-name" data-preview="${c.id}" title="${esc(c.reason)}"><strong>${esc(c.title)}</strong><small>${c.unfinished?'结尾未完 · ':''}${esc(c.reason||c.category)}</small></button><span class="clip-time">${time(c.start)}–${time(c.end)}</span><span class="clip-duration">${c.end-c.start>=3600?time(c.end-c.start):time(c.end-c.start).slice(3)}</span><span class="clip-score">${Math.round(c.score)}</span><button class="row-preview" data-preview="${c.id}">预览</button><button class="fine-link" data-fine="${c.id}">细剪</button></article>`).join('')}</div></div>`:'<div class="empty-state bordered">暂无可导出片段</div>'}<footer class="result-footer"><span>${task.api_usage?.total_tokens?`${task.api_usage.total_tokens.toLocaleString()} tokens`:''}</span>${task.exports.length?`<button class="text-button" data-reveal="${task.id}">${icon('folder')} 导出文件夹</button>`:''}</footer>`;
}
function reviewDetails(id: string) {
 const task=state?.tasks.find(t=>t.id===id);if(!task)return;
 const rejected=task.rejected_clips||[], summary=task.source_review_summary;
 showModal(`<h2 class="modal-title">来源复核</h2><div class="review-summary"><span>保留 ${task.clips.length} 段</span><span>过滤 ${summary?.excluded||0} 段</span><span>待确认 ${summary?.held||0} 段</span></div>${!summary?`<p class="settings-caption">${task.prefs.exclude_playback===false?'本任务未开启来源过滤。':'尚未复核，导出前会自动检查。'}</p>`:''}${rejected.length?`<div class="review-list">${rejected.map(c=>`<div class="source-review-item"><b>${esc(c.title)}</b><span>${time(c.start)} — ${time(c.end)}</span><p>${esc(c.source_review?.reason)}</p></div>`).join('')}</div>`:'<div class="info-note">过滤以播放其他视频为主的片段，保留主播的实质评论。</div>'}<p class="settings-caption">${summary?.unreviewed?`另有 ${summary.unreviewed} 个候选未复核。`:''}此前导出的文件保留，未通过复核的片段不参与新导出。</p><div class="modal-footer"><button class="secondary-button" data-action="close">关闭</button><button class="primary-button" data-recheck="${id}" ${pending.has(id)?'disabled':''}>${pending.has(id)?'复核中…':'重新复核'}</button></div>`);
}
async function preview(id: number,compatible=false) {
 const task=state?.tasks.find(t=>t.id===currentTask),clip=task?.clips.find(c=>c.id===id);if(!task||!clip)return;
 showModal(`<div class="modal-kicker">MOMENT ${id.toString().padStart(2,'0')}</div><h2>${esc(clip.title)}</h2><div id="videoContainer" class="preview-still"><div class="preview-loading">正在打开片段…</div></div><div class="preview-caption"><span>原录播 ${time(clip.start)} — ${time(clip.end)}</span><span>${esc(clip.category)}</span></div><p class="preview-reason">${esc(clip.reason)}</p>`,true);
 const token=previewToken;
 try{const result=await call<Playback>(compatible?'preview_compatible':'preview',{task_id:task.id,clip_id:id});if(modal.open&&token===previewToken){$('videoContainer').innerHTML='<video preload="metadata"></video>';modalPlayer=new SegmentPlayer($('videoContainer').querySelector('video')!,()=>guarded(()=>preview(id,true)));modalPlayer.set(result,asset(result.path),true);}}catch(e){if(token===previewToken)$('videoContainer').innerHTML=`<div class="preview-loading">${esc(e)}</div>`;}
}
function exportModal(id: string) {
 const ids=[...(selected.get(id)||[])];if(!ids.length){toast('请至少选择一个事件');return;}
 showModal(`<h2 class="modal-title">导出原片段</h2><p class="modal-description">${ids.length} 个独立视频 · 原画面、原声音</p><div class="modal-footer"><button class="secondary-button" data-action="close">取消</button><button class="primary-button" id="confirmExport">开始导出</button></div>`);
 $('confirmExport').onclick=()=>void guarded(async()=>{if(pending.has(id))return;await queue('export',id,{clip_ids:ids,mode:'separate',subtitle:'none'});closeModal();toast('已加入导出队列');});
}
function settingsTab(tab: string) {
 modal.querySelectorAll<HTMLElement>('[data-settings-panel]').forEach(el=>el.hidden=el.dataset.settingsPanel!==tab);
 modal.querySelectorAll<HTMLElement>('[data-settings-tab]').forEach(el=>{const on=el.dataset.settingsTab===tab;el.classList.toggle('active',on);el.setAttribute('aria-selected',String(on));});
 const body=modal.querySelector('.settings-body');if(body)body.scrollTop=0;
}
async function settingsModal(initialTab='ai',reason='') {
 if(!nativeOnly())return;await refresh();const s=state!.settings;
 showModal(`<h2 class="modal-title">设置</h2><form id="settingsForm" novalidate><nav class="settings-tabs" role="tablist" aria-label="设置分类"><button type="button" role="tab" class="active" data-settings-tab="ai" aria-selected="true">AI 服务</button><button type="button" role="tab" data-settings-tab="local" aria-selected="false">本地转写</button><button type="button" role="tab" data-settings-tab="output" aria-selected="false">导出与偏好</button></nav><div class="settings-body"><section data-settings-panel="ai"><div class="modal-field"><label for="apiBase">API 地址</label><input id="apiBase" name="api_base" value="${esc(s.api_base)}" required placeholder="https://api.deepseek.com"></div><div class="modal-field"><label for="apiModel">模型名称</label><input id="apiModel" name="api_model" value="${esc(s.api_model)}" required></div><div class="modal-field"><label for="apiKey">API Key <span class="subtle">${s.key_saved?'· 已保存，留空不更改':''}</span></label><input id="apiKey" name="api_key" type="password" autocomplete="off" placeholder="${s.key_saved?'已加密保存':'输入 API Key'}"></div><div class="settings-checks"><label class="check-row"><input name="api_json_mode" type="checkbox" ${s.api_json_mode?'checked':''}>JSON 输出</label><label class="check-row"><input name="clear_key" type="checkbox">清除密钥</label></div><div class="settings-actions"><button class="secondary-button" type="button" id="testApi">保存并测试</button><span id="apiTestStatus" role="status"></span></div><p class="settings-caption">兼容 Chat Completions。来源过滤需要图片模型。AI 接收字幕、弹幕与少量候选画面；更换服务商后需重新填写密钥。</p></section><section data-settings-panel="local" hidden><div class="setting-row"><div><h3>SenseVoice · 本地模型</h3><p id="modelStatus">${state!.model.ready?'随软件附带 · 可离线使用':'内置模型不完整，请重新安装完整版'}</p></div><span class="model-bundled-status">${state!.model.ready?'已就绪':'需修复'}</span></div><div class="settings-grid"><div class="modal-field"><label for="asrThreads">CPU 线程数</label><input type="number" min="1" max="8" id="asrThreads" name="asr_threads" value="${s.asr_threads}"></div><div class="modal-field"><label for="asr_model_dir">模型目录（可选）</label><input id="asr_model_dir" name="asr_model_dir" value="${esc(s.asr_model_dir)}" placeholder="使用软件内置模型"></div></div><details><summary>外部工具路径</summary>${[['ffmpeg_path','FFmpeg',s.ffmpeg_path],['ffprobe_path','FFprobe',s.ffprobe_path]].map(([name,label,value])=>`<div class="modal-field"><label for="${name}">${label}</label><input id="${name}" name="${name}" value="${esc(value)}" placeholder="使用内置程序"></div>`).join('')}</details><button class="text-button" type="button" id="openData">${icon('folder')} 数据目录</button></section><section data-settings-panel="output" hidden><div class="modal-field"><label for="outputDir">导出文件夹</label><div class="input-action"><input id="outputDir" name="output_dir" value="${esc(s.output_dir)}" placeholder="默认：录播旁的 SliceAI 文件夹"><button class="secondary-button" type="button" id="chooseOutput">选择</button></div></div><div class="settings-grid"><div class="modal-field"><label for="chatOffset">弹幕偏移（秒）</label><input type="number" min="-600" max="600" step="0.1" id="chatOffset" name="chat_offset" value="${s.chat_offset}"></div></div><p class="settings-caption">弹幕偏移为正数时向后移动。原片段导出为 MP4；字幕在细剪方案中设置。</p></section></div><div class="modal-footer"><span id="settingsMessage" class="settings-caption" role="status"></span><button type="button" class="secondary-button" data-action="close">关闭</button><button class="primary-button" type="submit">保存</button></div></form>`);
 modal.classList.add('settings-dialog');
 settingsTab(initialTab);
 $('settingsMessage').textContent=reason;
 const settingsForm=$<HTMLFormElement>('settingsForm'),settingsToken=previewToken;let saving=false;
 const settingsActive=()=>modal.open&&previewToken===settingsToken;
 async function save() {
  const form=settingsForm;const invalid=form.querySelector<HTMLInputElement>('input:invalid');if(invalid){const tab=invalid.closest<HTMLElement>('[data-settings-panel]')?.dataset.settingsPanel;if(tab)settingsTab(tab);}if(!form.reportValidity())throw new Error('请检查设置中的必填项');
  const data=new FormData(form),values:Record<string,unknown>={};for(const [key,value] of data)values[key]=value;
  values.api_json_mode=data.has('api_json_mode');values.clear_key=data.has('clear_key');
  for(const name of ['asr_threads','chat_offset'])values[name]=Number(data.get(name));
  await call('save_settings',{values});await refresh();const key=form.querySelector<HTMLInputElement>('#apiKey');if(key)key.value='';
 }
 settingsForm.onsubmit=e=>{e.preventDefault();if(saving)return;void guarded(async()=>{saving=true;const button=settingsForm.querySelector<HTMLButtonElement>('button[type=submit]')!;button.disabled=true;try{await save();if(settingsActive())closeModal();toast('设置已保存');}finally{saving=false;button.disabled=false;}});};
 $('testApi').onclick=()=>void guarded(async()=>{if(saving)return;saving=true;const b=$<HTMLButtonElement>('testApi'),status=$('apiTestStatus');b.disabled=true;try{await save();status.textContent='正在测试…';await call('api_test');if(settingsActive())closeModal();toast('设置已保存，连接成功');}catch(e){status.textContent=String(e);throw e;}finally{saving=false;b.disabled=false;}});
 $('chooseOutput').onclick=()=>void guarded(async()=>{const path=await pick([],true);if(path)$<HTMLInputElement>('outputDir').value=path;});
 $('openData').onclick=()=>void guarded(()=>invoke('reveal',{taskId:null}));
}
function updateModel() {const el=$('modelStatus');if(el)el.textContent=state?.model.ready?'随软件附带 · 可离线使用':'内置模型不完整，请重新安装完整版';}

async function guarded(action:()=>Promise<unknown>) {try{await action();}catch(error){toast(error instanceof Error?error.message:error);}}

document.addEventListener('click',event=>{
 const target=(event.target as Element).closest<HTMLElement>('button,a');if(!target)return;
 const d=target.dataset;
 if(d.page)navigate(d.page);
 if(target.classList.contains('brand')){event.preventDefault();navigate('home');}
 if(d.task)showTask(d.task);
 if(d.openProject)void guarded(async()=>{closeModal();await fine.openProject(d.openProject!);});
 if(d.deleteTask)deleteTaskModal(d.deleteTask);
 if(d.settingsTab)settingsTab(d.settingsTab);
 if(d.reviewDetails)reviewDetails(d.reviewDetails);
 if(d.fine)void guarded(()=>fine.load(currentTask,Number(d.fine)));
 if(d.preview)void guarded(()=>preview(Number(d.preview)));
 if(d.export)exportModal(d.export);
 if(d.reveal)void guarded(()=>invoke('reveal',{taskId:d.reveal}));
 if(d.revealProject&&d.revealExport)void guarded(()=>invoke('reveal',{taskId:null,projectId:d.revealProject,exportId:d.revealExport}));
 if(d.cancel)void guarded(async()=>{target.setAttribute('disabled','');const task=await call<Task>('cancel_task',{task_id:d.cancel});upsert(task);toast('已请求取消，正在停止处理…');});
 if(d.recheck)void guarded(async()=>{if(pending.has(d.recheck!))return;await queue('recheck',d.recheck);closeModal();toast('开始复核来源，将复用已有转写和有效画面结果');renderTask(state!.tasks.find(t=>t.id===d.recheck)!);});
 if(d.retry)void guarded(async()=>{target.setAttribute('disabled','');try{const task=await call<Task>('retry_task',{task_id:d.retry});upsert(task);await queue('run',task.id);showTask(task.id);}finally{target.removeAttribute('disabled');}});
 if(d.taskFilter){filter=d.taskFilter;document.querySelectorAll('[data-task-filter]').forEach(e=>e.classList.toggle('active',e===target));renderLists();}
 if(d.action==='settings')void guarded(settingsModal);
 if(d.action==='close')closeModal();
 if(d.action==='filterInfo')showModal('<h2 class="modal-title">过滤纯播放内容</h2><p class="modal-description">结合字幕与少量候选画面，过滤以播放其他视频为主的片段。保留主播的实质评论；来源无法确认时暂不导出。</p><div class="info-note">需要支持图片输入的 AI 模型。分段发送少量缩略画面，使用独立 API 计费。</div>');
 if(d.action==='exportInfo')showModal('<h2 class="modal-title">完成后自动导出</h2><p class="modal-description">开启后，识别出的精彩片段会按你选择的形式自动保存为 MP4，并附带独立 SRT 字幕。关闭后先查看结果，再选择需要的片段导出。</p><div class="info-note">默认保存到原视频旁的 SliceAI 文件夹，也可以在设置中更改位置。</div>');
 if(d.action==='help')showModal(`<h2 class="modal-title">使用帮助</h2>${[['01','准备一次','在设置中填写自己的 API 配置。SenseVoice 转写模型已随软件附带，无需下载。'],['02','导入录播','选择本地视频；可附加 UTF-8 编码的 SRT / VTT 字幕和 XML / JSON 弹幕，使用附件旁的移除按钮可清除；多音轨录播请先选择需要处理的声音。'],['03','自动剪辑','选择内容偏好后开始。转写在本机完成，AI 根据转写定位精彩内容，并用少量画面复核内容来源。'],['04','留下精彩','导出原片段，或进入细剪，通过固定问答选择要求，自动生成预览，再检查并导出。']].map(([n,title,body])=>`<div class="help-step"><b>${n}</b><div><h3>${title}</h3><p>${body}</p></div></div>`).join('')}`);
});
$('dropzone').onclick=()=>void guarded(()=>importVideo());
$('dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();void guarded(()=>importVideo());}};
for(const kind of ['subtitle','chat'] as const){$(`${kind}Button`).onclick=()=>void guarded(()=>attachment(kind));$(`${kind}Remove`).onclick=()=>removeAttachment(kind);$(`${kind}Button`).oncontextmenu=e=>{e.preventDefault();removeAttachment(kind);};}
$('audioTrack').onchange=()=>{audioTrack=Number($<HTMLSelectElement>('audioTrack').value);};
$('startButton').onclick=()=>void guarded(startTask);
$('taskSearch').oninput=renderLists;
$('appStatus').onclick=showActivity;
$('appStatus').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showActivity();}};
$('topicChoices').onclick=e=>{const b=(e.target as Element).closest<HTMLElement>('[data-value]');if(!b)return;const value=b.dataset.value!;topics=value==='自动判断'?['自动判断']:topics.filter(v=>v!=='自动判断');if(value!=='自动判断')topics=topics.includes(value)?topics.filter(v=>v!==value):[...topics,value];if(!topics.length)topics=['自动判断'];$('topicChoices').querySelectorAll<HTMLElement>('button').forEach(el=>{el.classList.toggle('active',topics.includes(el.dataset.value!));el.setAttribute('aria-pressed',String(topics.includes(el.dataset.value!)));});};
document.addEventListener('change',e=>{const el=e.target as HTMLInputElement;const picks=selected.get(currentTask);if(!picks)return;if(el.dataset.pick){const id=Number(el.dataset.pick);if(el.checked)picks.add(id);else picks.delete(id);}if(el.id==='selectAll'){picks.clear();if(el.checked)state?.tasks.find(t=>t.id===currentTask)?.clips.forEach(c=>picks.add(c.id));document.querySelectorAll<HTMLInputElement>('[data-pick]').forEach(c=>c.checked=el.checked);}else if(el.dataset.pick){const all=$<HTMLInputElement>('selectAll');if(all)all.checked=picks.size===(state?.tasks.find(t=>t.id===currentTask)?.clips.length||0);}const count=$('selectionCount');if(count)count.textContent=`已选 ${picks.size}`;const exportButton=$<HTMLButtonElement>('exportSelection');if(exportButton)exportButton.disabled=!picks.size||pending.has(currentTask);});
document.addEventListener('keydown',e=>{if(e.key.toLowerCase()==='n'&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&!modal.open&&!['INPUT','TEXTAREA','SELECT'].includes((e.target as Element).tagName))navigate('home');});

async function init() {
 renderLists();updateStart();if(!native)return;
 await listen<State>('backend-ready',event=>applySnapshot(event.payload));
 await listen<{type:string;task?:Task;cmd?:string;task_id?:string;result?:Task;message?:string;stage?:string;progress?:number;ready?:boolean;state?:State;queue?:QueueEntry[];queue_revision?:number;project?:{id:string;status:string}}>('worker-event',event=>{
  const e=event.payload;
  if(e.state)applySnapshot(e.state);
  if(e.type==='queue'&&e.queue){applyQueue({queue:e.queue,queue_revision:e.queue_revision});return;}
  if(e.type==='edit'&&e.project){const summary=state?.edits?.find(p=>p.id===e.project!.id);if(summary)summary.status=e.project.status;updateActivity();}
  if(e.cmd?.startsWith('edit_')){if(e.type==='finished'||e.type==='error')void guarded(refresh);return;}
  if(e.type==='task'&&e.task)upsert(e.task);
  if(e.type==='model'&&e.ready)void guarded(async()=>{await refresh();updateModel();});
  if(e.type==='finished'||e.type==='error'){
   if(e.task_id)pending.delete(e.task_id);
   if(e.cmd==='install_model')void guarded(async()=>{await refresh();updateModel();});
   if(e.type==='error')toast(e.message||'处理失败，请重试');
   if(e.result?.id){upsert(e.result);if(e.result.status==='complete')toast(e.cmd==='export'?'导出处理完成':e.cmd==='recheck'?'来源复核完成':'自动切片已完成');}
  }
 });
 await getCurrentWebviewWindow().onDragDropEvent(e=>{if(e.payload.type==='over')$('dropzone').classList.add('drag-over');else $('dropzone').classList.remove('drag-over');if(e.payload.type==='drop'){const path=e.payload.paths[0];if(path){navigate('home');void guarded(()=>importVideo(path));}}});
 await refresh();
 applyQueue(await invoke<{queue:QueueEntry[];queue_revision:number}>('queue_state'));
}
void guarded(init);
