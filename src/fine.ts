import './fine-progress.css';
import { ExecutionPanel, executionOutcome, executionIssue, type Execution } from './fine-progress';
import { SegmentPlayer, type Playback } from './segment-player';
import { invoke, convertFileSrc, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';
import { defaults, questions, summary, type EditOptions } from './fine-wizard';
import { sameView, SubtitleDrafts, cueFingerprint, type ViewTicket, type QueueEntry } from './workspace-state';

type Cue={id:number;start:number;end:number;text:string};
type Range={start:number;end:number;reason:string};
type Version={id:string;number:number;confirmed:boolean;summary:string;ranges:Range[];duration:number;reordered:boolean;subtitles:boolean;audio_strength:number;audio_engine?:string|null;cues:Cue[];preview:string;caption_review?:{needs_review:number[]};removed?:{start:number;end:number;reason:string;text:string}[]};
type Project={execution?:Execution;source_preview?:{path:string};edit_options?:EditOptions;question_step?:number;id:string;revision:number;task_id:string;clip_id:number;title:string;status:string;stage:string;error:string;source_start:number;source_end:number;messages:{role:string;content:string}[];versions:Version[];current_version:string|null;audio_sample?:{engine?:string;original:{path:string};processed:{path:string}};exports:{path:string;version_id:string}[]};
const AUDIO_ENGINE='bandit-plus-dnr-11.47-speech-v1';
const esc=(s:unknown)=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const $=<T extends HTMLElement=HTMLElement>(id:string)=>document.getElementById(id) as T;
const stamp=(n:number)=>`${Math.floor(n/60).toString().padStart(2,'0')}:${(n%60).toFixed(2).padStart(5,'0')}`;
const call=<T>(cmd:string,values:Record<string,unknown>)=>invoke<T>('call',{request:{cmd,...values}});

export class FineWorkspace {
 executionPanel=new ExecutionPanel();
 p:Project|null=null;tab='plan';mode='source';source='';sourceInfo:Playback|null=null;player:SegmentPlayer|null=null;sourceError='';pending=false;draft='';cues:Cue[]|null=null;sourceToken=0;answers:EditOptions=defaults();step=0;wizard=true;saving=false;
 private draftWarning=false;
 private drafts=new SubtitleDrafts(localStorage,()=>{if(!this.draftWarning){this.draftWarning=true;this.toast('本地字幕草稿无法写入磁盘；当前窗口仍保留修改，请点击保存字幕。');}});
 private cueSaves=new Map<string,{projectId:string;versionId:string;baseline:Cue[];submitted:Cue[]}>();
 private dialogTicket:ViewTicket|null=null;
 private queueEntries:QueueEntry[]=[];
 constructor(private navigate:(page:string)=>void,private toast:(msg:unknown)=>void,private refresh:()=>Promise<void>,private activity:()=>void=()=>{}){
  document.addEventListener('click',e=>{const el=(e.target as Element).closest<HTMLElement>('[data-fine-action]');if(el)void this.guard(()=>this.action(el.dataset.fineAction!,el));});
  document.addEventListener('keydown',e=>{
   if(!this.wizard||!this.p||$('finePage').hidden||this.pending||this.saving||['busy','queued'].includes(this.p.status)||this.step>=5)return;
   const target=e.target as HTMLElement;if(target.closest('textarea,input[type="number"],dialog')||e.ctrlKey||e.altKey||e.metaKey)return;
   if(/^[1-3]$/.test(e.key)){const choice=$('fineQuestionBody').querySelectorAll<HTMLInputElement>('input[name="fine-question"]')[Number(e.key)-1];if(choice){e.preventDefault();choice.click();}}
  });
  if(isTauri())void listen<{type:string;project?:Project;project_id?:string;cmd?:string;result?:Project;message?:string}>('worker-event',e=>this.receive(e.payload));
  window.addEventListener('beforeunload',()=>this.persistCues());
 }
 private ticket():ViewTicket{return {projectId:this.p!.id,generation:this.sourceToken};}
 private active(ticket:ViewTicket){return sameView(ticket,this.p?.id,this.sourceToken);}
 private accept(project:Project){
  if(project.id!==this.p?.id||project.revision<this.p.revision)return false;
  this.persistCues();
  if(project.current_version!==this.p.current_version)this.cues=null;
  this.p=project;
  this.completeCueSave(project);
  this.activity();return true;
 }
 private receive(event:{type:string;project?:Project;project_id?:string;cmd?:string;result?:Project;message?:string}){
  if(event.project)this.completeCueSave(event.project);if(event.result)this.completeCueSave(event.result);
  if(event.type==='edit'&&event.project&&this.accept(event.project)){
   if(event.project.status==='busy')this.pending=false;
   if(!['busy','queued'].includes(event.project.status)&&executionIssue(event.project)){this.wizard=false;if(event.project.execution?.command==='edit_export'&&this.current()?.preview)this.mode='preview';}
   this.render();
  }
  if(event.project_id!==this.p?.id||!['finished','error'].includes(event.type))return;
  if(event.result&&!this.accept(event.result))return;
  this.pending=false;
  if(event.type==='error'&&!event.result&&this.p)this.p={...this.p,status:'interrupted',stage:'处理已中断，可以重试',error:event.message||'处理失败，请重试。',execution:this.p.execution?{...this.p.execution,state:'failed'}:undefined};
  if(event.type==='error'||event.result?.error||/取消|中断/.test(event.result?.stage||'')||event.cmd==='edit_auto'&&event.result?.current_version)this.wizard=false;
  if(this.current()?.preview&&(event.cmd==='edit_export'||event.result&&['edit_auto','edit_confirm','edit_preview','edit_restore'].includes(event.cmd||'')&&!executionIssue(event.result)))this.mode='preview';
  if(event.cmd==='edit_source_preview'&&event.result&&!event.result.error){this.source=event.result.source_preview?.path||'';this.sourceInfo={path:this.source,start:0,end:event.result.source_end-event.result.source_start};}
  this.activity();this.render();
  if(event.message)this.toast(event.message);if(event.result?.error)this.toast(event.result.error);
  if(event.cmd==='edit_export')void this.refresh();
 }
 private completeCueSave(project:Project){
  const saved=this.cueSaves.get(project.id),current=project.versions.find(v=>v.id===project.current_version);
  if(saved&&current&&current.id!==saved.versionId&&cueFingerprint(current.cues)===cueFingerprint(saved.submitted)){
   this.drafts.removeSubmitted(saved.projectId,saved.versionId,saved.baseline,saved.submitted);this.cueSaves.delete(project.id);
  }
 }
 updateQueue(entries:QueueEntry[]){this.queueEntries=entries;this.render();}
 clearDrafts(projectId:string){this.drafts.removeProject(projectId);}
 leave(){this.persistCues();++this.sourceToken;$<HTMLVideoElement>('fineVideo')?.pause();this.closeOwnDialog();}
 private closeOwnDialog(){if(this.dialogTicket){$<HTMLDialogElement>('modal').close();this.dialogTicket=null;}}
 async guard(fn:()=>Promise<unknown>){try{await fn();}catch(e){this.toast(e instanceof Error?e.message:e);}}
 current(){return this.p?.versions.find(v=>v.id===this.p?.current_version);}
 rememberChoices(){if(this.p){try{localStorage.setItem('fine-choices:'+this.p.id,JSON.stringify({options:this.answers,step:this.step}));}catch{this.toast('问答选择暂时无法在本机缓存，保存后仍可恢复。');}}}
 async saveChoices(step:number){
  if(!this.p)return false;const ticket=this.ticket(),project=this.p,options=structuredClone(this.answers);
  this.saving=true;this.renderQuestions(false);
  try{const saved=await call<Project>('edit_options',{project_id:project.id,revision:project.revision,options,step});if(!this.active(ticket))return false;this.accept(saved);this.step=step;this.rememberChoices();return true;}
  finally{if(this.active(ticket)){this.saving=false;this.renderQuestions(false);}}
 }
 renderQuestions(busy:boolean){
  if(!this.p||!$('fineQuestionBody'))return;const p=this.p,v=this.current();
  const body=$('fineQuestionBody'),footer=$('fineQuestionFooter');
  if(busy){
   this.executionPanel.render(body,p,this.answers);
   const queued=this.queueEntries.find(q=>q.project_id===p.id&&q.status==='queued');
   footer.innerHTML=`<span class="question-footnote">${queued?`排队第 ${queued.position} 项`:p.status==='queued'?'等待处理':'处理中'} · 可以切换页面</span>`;return;
  }

  if(!this.wizard){
   body.innerHTML=`<div class="question-result">${executionOutcome(p,!!v?.preview)}<span class="question-kicker">${v?.preview?'预览已生成':'剪辑进度'}</span><h3>${v?`${stamp(p.source_end-p.source_start)} → ${stamp(v.duration)}`:'按你的选择处理'}</h3>${p.error?`<p class="error-note" role="alert">${esc(p.error)}</p>`:`<p>${esc(v?.summary||p.stage)}</p>`}${v?.caption_review?.needs_review.length?`<button class="question-check-link" data-fine-action="tab" data-tab="subtitles">${v.caption_review.needs_review.length} 条字幕识别有差异 · 查看</button>`:''}${v?.preview&&executionIssue(p)&&p.execution?.command!=='edit_export'?'<button class="text-button" data-fine-action="retry">重试本次处理</button>':''}<div class="question-receipt">${summary(this.answers).map(r=>`<span>${esc(r.value)}</span>`).join('')}</div></div>`;
   const issue=executionIssue(p),exportIssue=issue&&p.execution?.command==='edit_export';
   const action=v?.preview?'preview':issue?(exportIssue?'export':'retry'):'confirm';
   const label=v?.preview?'查看成片':issue?(exportIssue?'重新导出':'重新处理'):'生成预览';
   footer.innerHTML=`<button class="secondary-button" data-fine-action="question-edit">调整要求</button><button class="primary-button" data-fine-action="${action}" ${!v&&!issue?'disabled':''}>${label}</button>`;return;
  }
  if(this.step===5){
   body.innerHTML=`<span class="question-kicker">全部选好了</span><h3>按这些要求开始细剪</h3><div class="question-summary">${summary(this.answers).map((row,i)=>`<button data-fine-action="question-edit" data-step="${Math.min(i,4)}"><span>${esc(row.title)}</span><b>${esc(row.value)}</b><small>修改 ›</small></button>`).join('')}</div><p class="question-note">自动生成预览，原片保留。</p>`;
   footer.innerHTML=`<button class="secondary-button" data-fine-action="question-prev" ${this.saving?'disabled':''}>上一步</button><button class="primary-button" data-fine-action="question-start" ${this.saving?'disabled':''}>开始细剪</button>`;return;
  }
  const q=questions[this.step],value=this.answers[q.key],sample=p.audio_sample?.engine===AUDIO_ENGINE?p.audio_sample:null;
  body.innerHTML=`<div class="question-progress"><span>问题 ${this.step+1} / ${questions.length}</span><span>${q.multi?'可多选':'单选'}</span></div><div class="question-steps" aria-hidden="true">${questions.map((_,i)=>`<i class="${i<=this.step?'done':''}"></i>`).join('')}</div><fieldset class="question-fieldset" ${this.saving?'disabled':''}><legend>${esc(q.title)}</legend><p class="question-hint">${esc(q.hint)}</p><div class="question-options">${q.options.map((o,i)=>{const checked=Array.isArray(value)?value.includes(o[0]):value===o[0];return `<label class="question-option ${checked?'selected':''}"><input type="${q.multi?'checkbox':'radio'}" name="fine-question" value="${o[0]}" ${checked?'checked':''}><span><b>${esc(o[1])}${o.length>3?'<em>推荐</em>':''}</b><small>${esc(o[2])}</small></span><kbd>${i+1}</kbd></label>`;}).join('')}</div>${q.multi?'<button class="text-button question-keep" data-fine-action="question-all">这一项全部保留</button>':''}</fieldset>${this.step===4?`<label class="question-normalize"><input type="checkbox" id="questionNormalize" ${this.answers.normalize?'checked':''} ${this.saving?'disabled':''}> 均衡音量</label>${this.answers.music==='reduce'?`<details class="question-audition"><summary>试听效果（可选）</summary><button class="secondary-button" data-fine-action="question-sample">${sample?'重新':'生成 20 秒'}试听</button>${sample?`<label>原声<audio controls preload="none" src="${esc(convertFileSrc(sample.original.path))}"></audio></label><label>处理后<audio controls preload="none" src="${esc(convertFileSrc(sample.processed.path))}"></audio></label>`:''}</details>`:''}`:''}`;
  body.querySelectorAll<HTMLInputElement>('input[name="fine-question"]').forEach(input=>input.onchange=()=>{
   if(q.multi){const selected=this.answers[q.key as 'cleanup'|'speech'];this.answers[q.key as 'cleanup'|'speech']=input.checked?[...selected,input.value]:selected.filter(x=>x!==input.value);}
   else Object.assign(this.answers,{[q.key]:input.value});
   this.rememberChoices();this.renderQuestions(false);body.querySelector<HTMLInputElement>(`input[value="${input.value}"]`)?.focus();
  });
  $('questionNormalize')?.addEventListener('change',e=>{this.answers.normalize=(e.target as HTMLInputElement).checked;this.rememberChoices();});
  footer.innerHTML=`<button class="secondary-button" data-fine-action="question-prev" ${this.step===0||this.saving?'disabled':''}>上一步</button><span>${this.saving?'保存中…':''}</span><button class="primary-button" data-fine-action="question-next" ${this.saving?'disabled':''}>${this.step===4?'查看选择':'下一步'}</button>`;
 }
 async load(taskId:string,clipId:number){await this.loadRequest('edit_create',{task_id:taskId,clip_id:clipId});}
 async openProject(projectId:string){await this.loadRequest('edit_get',{project_id:projectId});}
 private async loadRequest(cmd:string,request:Record<string,unknown>){
  this.persistCues();this.rememberChoices();this.closeOwnDialog();const token=++this.sourceToken;
  this.player?.destroy();this.player=null;this.p=null;this.cues=null;this.pending=false;this.saving=false;
  this.navigate('fine');$('finePage').innerHTML='<div class="fine-empty" role="status">正在打开细剪项目…</div>';
  const project=await call<Project>(cmd,request);if(token!==this.sourceToken)return;this.p=project;this.sourceInfo=null;this.sourceError='';this.tab='plan';this.mode=this.current()?.preview?'preview':'source';this.draft='';this.source='';
  this.answers=structuredClone(this.p.edit_options||defaults());this.step=this.p.question_step||0;this.wizard=!this.p.current_version&&!executionIssue(this.p);
  try{const local=JSON.parse(localStorage.getItem('fine-choices:'+this.p.id)||'null');if(local){this.answers=local.options;this.step=local.step;}}catch{/* Saved server choices remain available. */}
  this.activity();this.render();
  try{const src=await call<Playback>('edit_source',{project_id:project.id});if(sameView({projectId:project.id,generation:token},this.p?.id,this.sourceToken)){this.source=src.path;this.sourceInfo=src;this.video();}}catch(e){if(sameView({projectId:project.id,generation:token},this.p?.id,this.sourceToken)){this.sourceError=String(e);this.render();if(this.mode==='source')this.toast(e);}}

 }
 async queue(cmd:string,extra:Record<string,unknown>={}){
  if(!this.p||this.pending||['busy','queued'].includes(this.p.status))return;
  this.persistCues();const ticket=this.ticket(),project=this.p,values=structuredClone(extra);
  this.pending=true;this.p={...this.p,status:'queued',stage:'等待处理',error:''};this.activity();this.render();
  try{
   const prepared=await call<Project>('edit_prepare',{project_id:project.id,revision:project.revision});
   if(this.active(ticket))this.accept(prepared);
   await invoke('enqueue',{request:{cmd,project_id:project.id,revision:prepared.revision,...values}});
  }catch(e){
   // Cleanup belongs to the operation's project even if another project is now open.
   try{const abandoned=await call<Project>('edit_abandon',{project_id:project.id});if(this.active(ticket))this.accept(abandoned);}
   finally{if(this.active(ticket)){this.pending=false;this.activity();this.render();}}
   throw e;
  }
 }
 video(){
  const video=$<HTMLVideoElement>('fineVideo');if(!video||!this.p)return;
  const v=this.current(),info=this.mode==='source'?this.sourceInfo:(v?.preview?{path:v.preview,start:0,end:v.duration}:null);
  $('fineSourceStatus').hidden=!!info;
  if(!info)return;
  this.player??=new SegmentPlayer(video,()=>this.guard(()=>this.queue(this.mode==='source'?'edit_source_preview':'edit_preview')));
  this.player.set(info,convertFileSrc(info.path));
 }
 render(){
  if(!this.p)return;const root=$('finePage');if(root.hidden)return;
  this.persistCues();
  const p=this.p,v=this.current(),busy=this.pending||['busy','queued'].includes(p.status);
  if(this.mode==='preview'&&!v?.preview)this.mode='source';
  if(!$('fineVideo'))root.innerHTML=`<div class="fine-shell"><header class="fine-toolbar"><button class="secondary-button" data-fine-action="back">← 返回事件</button><h2 id="fineTitle"></h2><button class="text-button" data-fine-action="relocate">定位素材</button><button class="primary-button" id="fineConfirm" data-fine-action="confirm">确认并预览</button><button class="secondary-button" id="fineExport" data-fine-action="export">导出成片</button></header><div class="fine-work"><section class="fine-viewer"><div class="fine-screen"><span id="fineSourceStatus" role="status"></span><video id="fineVideo" preload="metadata"></video></div><div class="fine-tabs" id="fineTabs"></div><div class="fine-detail scroll-area" id="fineDetail"></div></section><section class="fine-chat fine-questions"><div class="fine-chat-heading"><b id="fineQuestionHeading">剪辑要求</b><button class="text-button" id="fineCancel" data-fine-action="cancel" hidden>取消</button></div><div class="fine-question-body scroll-area" id="fineQuestionBody"></div><div class="fine-question-footer" id="fineQuestionFooter"></div></section></div></div>`;
  $('fineSourceStatus').hidden=this.mode!=='source'||!!this.source;
  $('fineSourceStatus').textContent=this.sourceError||'正在打开片段…';
  $('fineTitle').textContent=p.title;$('fineTitle').title=p.title;
  $<HTMLButtonElement>('fineExport').disabled=busy||!v?.confirmed;
  $<HTMLButtonElement>('fineConfirm').disabled=busy||!v;
  $('fineConfirm').hidden=!v;
  $('fineConfirm').textContent=v?.preview?'查看成片':v?.confirmed?'生成预览':'确认并预览';
  $('fineConfirm').dataset.fineAction=v?.preview?'preview':'confirm';
  $('fineExport').textContent=!busy&&p.execution?.command==='edit_export'&&executionIssue(p)?'重新导出':'导出成片';
  $('fineCancel').hidden=!busy;
  $('fineQuestionHeading').textContent=busy?'正在处理':(!this.wizard?'剪辑结果':'剪辑要求');
  $('fineTabs').innerHTML=`<button data-fine-action="source" class="${this.mode==='source'?'active':''}">粗剪片段</button><button data-fine-action="preview" class="${this.mode==='preview'?'active':''}" ${!v?.preview?'disabled':''}>成片</button><span></span>${[['plan','方案'],['subtitles','字幕'],['audio','声音'],['versions','版本']].map(([key,label])=>`<button data-fine-action="tab" data-tab="${key}" class="${this.tab===key?'active':''}">${label}</button>`).join('')}`;
  this.renderQuestions(busy);
  const detail=$('fineDetail');
  if(this.tab==='plan')detail.innerHTML=v?`<div class="fine-plan-top"><b>方案 ${v.number} · ${stamp(v.duration)}</b><span>${v.reordered?'含内容重排':'保留原顺序'} · ${v.confirmed?'已确认':'待确认'}</span></div><p class="fine-summary">${esc(v.summary)}</p><div class="fine-ranges">${v.ranges.map((r,i)=>`<div><button class="text-button" data-fine-action="seek-source" data-seconds="${r.start}">${i+1}. ${stamp(r.start-p.source_start)} — ${stamp(r.end-p.source_start)}</button><span>${esc(r.reason)}</span></div>`).join('')}</div>${v.removed?.length?`<details class="fine-deletions"><summary>查看删减 · ${v.removed.length} 处</summary>${v.removed.map((r,i)=>`<div><button class="text-button" data-fine-action="seek-source" data-seconds="${r.start}">${stamp(r.start-p.source_start)} — ${stamp(r.end-p.source_start)}</button><p>${esc(r.reason)}</p><small>${esc(r.text)}</small><button class="secondary-button" data-fine-action="restore-cut" data-index="${i}" ${busy?'disabled':''}>恢复这段</button></div>`).join('')}</details>`:''}<div class="fine-plan-actions"><label><input type="checkbox" id="fineSubs" ${v.subtitles?'checked':''} ${busy?'disabled':''}> 添加字幕</label><button class="text-button" data-fine-action="trim" ${busy?'disabled':''}>微调区间</button></div>`:'<div class="fine-empty">选择右侧剪辑要求，即可自动生成预览。</div>';
  else if(this.tab==='versions')detail.innerHTML=p.versions.slice().reverse().map(x=>`<div class="fine-version"><span>版本 ${x.number} · ${stamp(x.duration)} · ${x.confirmed?'已确认':'草稿'}</span><button class="secondary-button" data-fine-action="restore" data-version="${x.id}" ${busy||x.id===v?.id?'disabled':''}>${x.id===v?.id?'当前':'切换'}</button></div>`).join('')||'<div class="fine-empty">暂无方案版本</div>';
  else if(this.tab==='subtitles'){
   if(v&&!this.cues)this.cues=this.drafts.read(p.id,v.id,v.cues)||structuredClone(v.cues);
   detail.innerHTML=v?`<div class="fine-sub-toolbar"><span>${this.cues?.length||0} 条${v.caption_review?.needs_review.length?' · '+v.caption_review.needs_review.length+' 条待核对':''}</span><button class="secondary-button" data-fine-action="save-cues" ${busy?'disabled':''}>保存字幕</button></div><p class="fine-draft-status" id="fineDraftStatus" role="status">${this.draftStatus()}</p><div id="fineCues" data-project="${esc(p.id)}" data-version="${esc(v.id)}">${(this.cues||[]).map((c,i)=>`<div class="fine-cue ${v.caption_review?.needs_review.includes(c.id)?'needs-check':''}" data-index="${i}">${v.caption_review?.needs_review.includes(c.id)?'<small>两次识别有差异，请试听核对</small>':''}<div><button class="text-button" data-fine-action="seek-cue" data-seconds="${c.start}">▶</button><input aria-label="第 ${i+1} 条开始秒数" data-cue-start ${busy?'disabled':''} type="number" min="0" step="0.01" value="${c.start.toFixed(2)}"> — <input aria-label="第 ${i+1} 条结束秒数" data-cue-end ${busy?'disabled':''} type="number" min="0" step="0.01" value="${c.end.toFixed(2)}"><button data-fine-action="split-cue" ${busy?'disabled':''} data-index="${i}">拆分</button><button data-fine-action="merge-cue" ${busy?'disabled':''} data-index="${i}">合并</button><button data-fine-action="delete-cue" ${busy?'disabled':''} data-index="${i}" aria-label="删除第 ${i+1} 条字幕">×</button></div><textarea data-cue-text ${busy?'disabled':''} aria-label="第 ${i+1} 条字幕">${esc(c.text)}</textarea></div>`).join('')}</div>`:'<div class="fine-empty">生成方案后可以编辑字幕。</div>';
   $('fineCues')?.addEventListener('input',()=>this.collectCues());
  }else if(this.tab==='audio'){
   const sample=p.audio_sample?.engine===AUDIO_ENGINE?p.audio_sample:null;
   detail.innerHTML=`<div class="fine-plan-top"><b>降低背景音乐</b><span>本地处理 · 试听可选</span></div><p class="fine-summary">直接应用到方案，或先试听效果。</p><button class="secondary-button" data-fine-action="sample" ${busy?'disabled':''}>生成 20 秒试听</button>${sample?`<div class="fine-audio"><label>原声<audio controls preload="none" src="${esc(convertFileSrc(sample.original.path))}"></audio></label><label>处理后<audio controls preload="none" src="${esc(convertFileSrc(sample.processed.path))}"></audio></label></div>`:''}<div class="fine-plan-actions"><label>强度 <input id="fineStrength" type="range" min="0" max="1" step="0.1" value="${v?.audio_engine===AUDIO_ENGINE&&v.audio_strength?v.audio_strength:1}"></label><button class="primary-button" data-fine-action="apply-audio" ${busy||!v?'disabled':''}>应用到方案</button></div><button class="text-button" data-fine-action="original-audio" ${busy||!v?.audio_strength?'disabled':''}>恢复原声</button>`;
  }
  $('fineSubs')?.addEventListener('change',()=>void this.guard(()=>this.queue('edit_update',{subtitles:$<HTMLInputElement>('fineSubs').checked})));
  this.video();
 }
 collectCues(){
  const version=this.current(),container=$('fineCues');
  if(!this.cues||!this.p||!version||container?.dataset.project!==this.p.id||container.dataset.version!==version.id)return;
  container.querySelectorAll<HTMLElement>('.fine-cue').forEach(row=>{const i=Number(row.dataset.index);this.cues![i]={id:i+1,start:Number(row.querySelector<HTMLInputElement>('[data-cue-start]')!.value),end:Number(row.querySelector<HTMLInputElement>('[data-cue-end]')!.value),text:row.querySelector<HTMLTextAreaElement>('[data-cue-text]')!.value};});
  this.drafts.write(this.p.id,version.id,version.cues,this.cues);const status=$('fineDraftStatus');if(status)status.textContent=this.draftStatus();
 }
 private draftStatus(){const version=this.current();return this.cues&&version&&cueFingerprint(this.cues)!==cueFingerprint(version.cues)?this.draftWarning?'草稿暂存于当前窗口，请保存字幕后再关闭。':'本地草稿已自动保存；点击保存字幕应用到方案。':'字幕已保存到方案。';}
 private persistCues(){const version=this.current();if(this.p&&version&&this.cues)this.drafts.write(this.p.id,version.id,version.cues,this.cues);}

 async action(action:string,el:HTMLElement){
  if(!this.p)return;const p=this.p,v=this.current(),ticket=this.ticket();
  if(action==='back'){this.rememberChoices();this.navigate('results');return;}
  if(['export-confirm','trim-save'].includes(action)&&(!this.dialogTicket||!this.active(this.dialogTicket))){this.closeOwnDialog();this.toast('项目已变化，请重新打开操作。');return;}
  if(action==='tab'){this.tab=el.dataset.tab!;this.render();return;}
  if(action==='source'||action==='preview'){this.mode=action;this.render();return;}
  if(action==='cancel'){await call('edit_cancel',{project_id:p.id});return;}
  if(action==='seek-source'||action==='seek-cue'){
   let t=Number(el.dataset.seconds);
   if(action==='seek-source')this.mode='source';
   else if(!v?.preview){let offset=0;for(const r of v?.ranges||[]){if(t<offset+r.end-r.start){t=r.start+t-offset;break;}offset+=r.end-r.start;}this.mode='source';}
   else this.mode='preview';
   if(this.mode==='source')t=Math.max(0,Math.min(p.source_end-p.source_start,t-p.source_start));
   this.render();this.player?.seek(t);return;
  }
  if(this.pending||['busy','queued'].includes(p.status))return;
  if(action==='retry'){const cmd=p.execution?.command||'edit_auto';await this.queue(['edit_auto','edit_preview','edit_confirm','edit_export','edit_audio_sample','edit_source_preview'].includes(cmd)?cmd:'edit_auto',cmd==='edit_auto'?{options:this.answers}:{});return;}
  if(action==='question-prev'||action==='question-next'){
   if(this.saving)return;const next=Math.max(0,Math.min(5,this.step+(action==='question-next'?1:-1)));
   if(await this.saveChoices(next))this.render();return;
  }
  if(action==='question-edit'){this.wizard=true;this.step=Number(el.dataset.step||0);this.rememberChoices();this.render();return;}
  if(action==='question-start'){if(!await this.saveChoices(5))return;this.persistCues();this.wizard=false;this.mode='source';this.cues=null;await this.queue('edit_auto',{options:this.answers});return;}
  if(action==='question-all'){const q=questions[this.step];if(q.multi){this.answers[q.key as 'cleanup'|'speech']=[];this.rememberChoices();this.render();}return;}
  if(action==='question-sample'){if(!await this.saveChoices(this.step))return;await this.queue('edit_audio_sample',{start:p.source_start});return;}
  if(action==='confirm'){this.mode='preview';await this.queue(v?.confirmed?'edit_preview':'edit_confirm');return;}
  if(action==='restore'){this.persistCues();this.cues=null;await this.queue('edit_restore',{version_id:el.dataset.version});return;}
  if(action==='save-cues'&&v&&this.cues){this.collectCues();this.cueSaves.set(p.id,{projectId:p.id,versionId:v.id,baseline:structuredClone(v.cues),submitted:structuredClone(this.cues)});await this.queue('edit_update',{cues:this.cues});return;}
  if(action==='restore-cut'&&v){
   const removed=v.removed?.[Number(el.dataset.index)];if(!removed)return;
   const ranges:Range[]=[];
   for(const r of [...v.ranges,{start:removed.start,end:removed.end,reason:'恢复原内容'}].sort((a,b)=>a.start-b.start)){
    const last=ranges.at(-1);if(last&&r.start<=last.end+.001)last.end=Math.max(last.end,r.end);else ranges.push({...r});
   }
   this.persistCues();this.cues=null;await this.queue('edit_update',{ranges});return;
  }
  if(action==='split-cue'||action==='merge-cue'||action==='delete-cue'){
   this.collectCues();const i=Number(el.dataset.index),c=this.cues?.[i];if(!c)return;
   if(action==='delete-cue')this.cues!.splice(i,1);
   else if(action==='merge-cue'){const n=this.cues?.[i+1];if(n)this.cues!.splice(i,2,{...c,end:n.end,text:c.text+n.text});}
   else {const field=document.querySelectorAll<HTMLTextAreaElement>('[data-cue-text]')[i];const cursor=field.selectionStart;const pos=cursor>0&&cursor<c.text.length?cursor:Math.ceil(c.text.length/2);if(pos>=c.text.length)return;const mid=c.start+(c.end-c.start)*pos/c.text.length;this.cues!.splice(i,1,{...c,end:mid,text:c.text.slice(0,pos)},{...c,start:mid,text:c.text.slice(pos)});}
   this.cues=this.cues!.map((cue,index)=>({...cue,id:index+1}));this.persistCues();this.render();return;
  }
  if(action==='sample'){await this.queue('edit_audio_sample',{start:this.mode==='source'?Math.min(p.source_end-1,Math.max(p.source_start,p.source_start+(this.player?.currentTime||0))):p.source_start});return;}
  if(action==='apply-audio'||action==='original-audio'){await this.queue('edit_update',{audio_strength:action==='original-audio'?0:Number($<HTMLInputElement>('fineStrength').value)});return;}
  if(action==='relocate'){
   const path=await open({multiple:false,filters:[{name:'录播视频',extensions:['mp4','mkv','flv','mov','webm','ts']}]});
   if(typeof path!=='string'||!this.active(ticket))return;
   await call('relocate',{task_id:p.task_id,path});
   if(this.active(ticket)){this.source='';this.sourceInfo=null;this.mode='source';this.sourceError='';this.player?.destroy();this.player=null;this.render();}
   const src=await call<Playback>('edit_source',{project_id:p.id});
   if(this.active(ticket)){this.source=src.path;this.sourceInfo=src;this.render();}
   await this.refresh();return;
  }
  if(action==='export'){
   this.dialogTicket=ticket;
   const dialog=$<HTMLDialogElement>('modal');$('modalContent').innerHTML='<h2 class="modal-title">导出细剪成片</h2><label class="check-row"><input id="fineSrt" type="checkbox">另存 SRT 字幕</label><div class="modal-footer"><button class="primary-button" data-fine-action="export-confirm">开始导出</button></div>';dialog.showModal();return;
  }
  if(action==='export-confirm'){const srt=$<HTMLInputElement>('fineSrt').checked;this.closeOwnDialog();await this.queue('edit_export',{srt});return;}
  if(action==='trim'&&v){
   this.dialogTicket=ticket;
   const dialog=$<HTMLDialogElement>('modal');$('modalContent').innerHTML=`<h2 class="modal-title">微调保留区间</h2><p class="settings-caption">秒数相对原片段；保存后重新确认方案。</p><div class="trim-rows">${v.ranges.map((r,i)=>`<div class="trim-row"><label>${i+1}<input data-trim-start type="number" min="0" step="0.01" value="${(r.start-p.source_start).toFixed(2)}" aria-label="区间 ${i+1} 开始"></label><span>—</span><input data-trim-end type="number" step="0.01" value="${(r.end-p.source_start).toFixed(2)}" aria-label="区间 ${i+1} 结束"></div>`).join('')}</div><div class="modal-footer"><button class="primary-button" data-fine-action="trim-save">保存区间</button></div>`;dialog.showModal();return;
  }
  if(action==='trim-save'&&v){const ranges=[...document.querySelectorAll('.trim-row')].map((row,i)=>({...v.ranges[i],start:Number(row.querySelector<HTMLInputElement>('[data-trim-start]')!.value)+p.source_start,end:Number(row.querySelector<HTMLInputElement>('[data-trim-end]')!.value)+p.source_start}));this.persistCues();this.cues=null;this.closeOwnDialog();await this.queue('edit_update',{ranges});}
 }
}
