import { summary, type EditOptions } from './fine-wizard';

export type ExecutionStep={id:string;title:string;state:string;detail:string;percent:number|null};
export type Execution={id:string;command:string;state:string;started_at:string;finished_at?:string;active:string;steps:ExecutionStep[]};
type Snapshot={id:string;status:string;stage:string;error:string;execution?:Execution};
const esc=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const check='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"/></svg>';
export const agentSpinner=()=>`<span class="edit-agent-spinner" aria-hidden="true"><svg viewBox="0 0 24 24">${Array.from({length:12},(_,i)=>`<rect x="11" y="2" width="2" height="5" rx="1" opacity="${.12+i*.075}" transform="rotate(${i*30} 12 12)"/>`).join('')}</svg></span>`;

function row(step:ExecutionStep){
 const state=['running','done','pending','failed','cancelled','interrupted','skipped'].includes(step.state)?step.state:'pending';
 const marker=state==='running'?agentSpinner():state==='done'?check:['failed','cancelled','interrupted'].includes(state)?'!':'';
 return `<div class="edit-agent-step ${state}" data-execution-step="${esc(step.id)}"><span class="edit-agent-marker">${marker}</span><div class="edit-agent-step-body"><div class="edit-agent-step-title">${esc(step.title)}${state==='skipped'?'<small>无需重复处理</small>':''}</div><p class="edit-agent-note" data-step-note ${state!=='running'?'hidden':''}></p><div class="edit-agent-meter" data-step-meter hidden role="progressbar" aria-label="${esc(step.title)}进度" aria-valuemin="0" aria-valuemax="100"><i></i></div><span class="edit-agent-percent" data-step-percent hidden></span></div></div>`;
}

/** Preserve the active spinner and expanded requirements while percentages stream in. */
export class ExecutionPanel {
 private key='';
 render(body:HTMLElement,p:Snapshot,options:EditOptions){
  const queued=p.status==='queued'||p.stage==='等待处理';
  const execution=!queued&&p.execution?.state==='running'?p.execution:undefined;
  // Historical workers have no execution log: report only their current action.
  const steps:ExecutionStep[]=execution?.steps||[{id:'current',title:queued?'等待处理':p.stage.replace(/\s*·\s*[\d.]+%$/,'')||'正在处理',state:'running',detail:queued?'队列中的任务完成后开始。':'',percent:!queued&&p.stage.startsWith('降低背景音乐')?Number(p.stage.match(/([\d.]+)%/)?.[1]??NaN):null}];
  const active=steps.find(s=>s.state==='running');
  const completed=steps.filter(s=>s.state==='done');
  const older=completed.length>2?completed.slice(0,-2):[];
  const visible=steps.filter(s=>!older.includes(s));
  const key=JSON.stringify([p.id,execution?.id,queued,steps.map(s=>[s.id,s.title,s.state]),options]);
  if(this.key!==key||!body.querySelector('.edit-agent-run')){
   this.key=key;
   const retainedOpen=body.querySelector<HTMLDetailsElement>('.edit-agent-requirements')?.open||false;
   body.innerHTML=`<div class="edit-agent-run"><p class="edit-agent-intro">${queued?'任务已加入队列。':execution?.command==='edit_export'?'正在导出你的成片。':execution?.command==='edit_audio_sample'?'正在生成声音试听。':'正在按你的要求处理这个片段。'}</p>${older.length?`<details class="edit-agent-history"><summary>已完成 ${older.length} 个步骤</summary>${older.map(row).join('')}</details>`:''}<div class="edit-agent-steps">${visible.map(row).join('')}</div><span class="edit-agent-announcement" role="status" aria-live="polite">${esc(active?.title||'正在处理')}</span></div><details class="edit-agent-requirements" ${retainedOpen?'open':''}><summary>剪辑要求<span>查看选择</span></summary><div>${summary(options).map(s=>`<p><span>${esc(s.title)}</span>${esc(s.value)}</p>`).join('')}</div></details>`;
  }
  body.querySelectorAll<HTMLElement>('[data-execution-step]').forEach(el=>{
   const step=steps.find(s=>s.id===el.dataset.executionStep);if(!step)return;
   const note=el.querySelector<HTMLElement>('[data-step-note]')!;
   const text=step.detail&&step.detail!==step.title&&!/^降低背景音乐\s*·/.test(step.detail)?step.detail:'';
   note.hidden=step.state!=='running'||!text;if(note.textContent!==text)note.textContent=text;
   const percent=typeof step.percent==='number'&&Number.isFinite(step.percent)?Math.max(0,Math.min(100,step.percent)):null;
   const meter=el.querySelector<HTMLElement>('[data-step-meter]')!,label=el.querySelector<HTMLElement>('[data-step-percent]')!;
   meter.hidden=label.hidden=step.state!=='running'||percent===null;
   if(percent!==null){meter.setAttribute('aria-valuenow',String(percent));meter.querySelector('i')!.style.width=`${percent}%`;label.textContent=`${Math.floor(percent)}%`;}
  });
 }
}

export function executionIssue(p:Snapshot):'failed'|'cancelled'|'interrupted'|null{
 if(p.error||p.execution?.state==='failed')return 'failed';
 if(p.execution?.state==='cancelled'||/取消/.test(p.stage))return 'cancelled';
 if(p.execution?.state==='interrupted'||/中断/.test(p.stage))return 'interrupted';
 return null;
}

export function executionOutcome(p:Snapshot,hasPreview=false,unchanged=false){
 const state=p.error?'failed':p.execution?.state;
 const issue=executionIssue(p);
 if(p.execution?.command==='edit_export'&&issue){
  const status=issue==='failed'?'导出失败':issue==='cancelled'?'导出已取消':'导出已中断';
  return `<span class="edit-agent-outcome ${issue==='failed'?'failed':'stopped'}">${status} · ${hasPreview?'已生成成片仍可观看':'已有成果保留'}</span>`;
 }
 if(state==='failed')return '<span class="edit-agent-outcome failed">处理未完成 · 已有成果保留</span>';
 if(state==='cancelled'||state==='interrupted'||/取消|中断/.test(p.stage))return '<span class="edit-agent-outcome stopped">处理已停止 · 草稿已保留</span>';
 if(state==='done')return `<span class="edit-agent-outcome done">${check}${p.execution?.command==='edit_export'?'导出完成':unchanged?'处理结束':'处理完成'}</span>`;
 return '';
}

export type CutCandidate={id:string;start:number|null;end:number|null;text?:string;quote?:string;reason:string;kind?:string;status:string;decision?:'keep'|'remove'|'manual';block_reason?:string;effective_intervals?:{start:number;end:number}[]};
export type CutResultVersion={duration:number;source_duration?:number;removed_duration?:number;cut_ledger?:CutCandidate[];candidate_ledger?:{suggested:number;blocked:number;applied:number;candidates:CutCandidate[]};auto_review?:{suggested_removals?:number;blocked_removals?:number;applied_removals?:number;reviewed_removals?:number;protected?:unknown[]};removed?:{start:number;end:number;reason:string;text:string;candidate_ids?:string[]}[]};
const count=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)?Math.max(0,Math.floor(value)):0;

/** Counts are decisions; saved duration is the effective result, never a planned cut. */
export function cutResult(version:CutResultVersion,sourceStart:number,sourceEnd:number){
 const sourceDuration=Math.max(0,sourceEnd-sourceStart);
 const outputDuration=Number.isFinite(version.duration)?Math.max(0,version.duration):sourceDuration;
 const removedDuration=Math.max(0,sourceDuration-outputDuration);
 const ledger=version.cut_ledger??version.candidate_ledger?.candidates;
 const candidates=ledger??[];
 const applied=ledger?candidates.filter(c=>c.status==='applied').length:version.removed?.length??count(version.auto_review?.applied_removals);
 const blocked=ledger?candidates.filter(c=>c.status==='blocked').length:count(version.auto_review?.blocked_removals??version.auto_review?.protected?.length);
 const suggested=ledger?candidates.length:count(version.auto_review?.suggested_removals??version.auto_review?.reviewed_removals??applied);
 const unchanged=removedDuration<.03;
 const reasons=[...new Set(candidates.filter(c=>c.status==='blocked').map(c=>c.block_reason||c.reason).filter(Boolean))];
 const explanation=unchanged?reasons.length?reasons.slice(0,2).join('；'):blocked?'建议删点暂时无法安全定位，相关内容已保留。':candidates.some(c=>c.status==='restored')?'删减内容已恢复，当前保留完整片段。':'当前要求下没有找到可安全删减的内容。':'';
 return {sourceDuration,outputDuration,removedDuration,suggested,blocked,applied,unchanged,explanation,candidates};
}

export function cutSummaryHtml(version:CutResultVersion,sourceStart:number,sourceEnd:number){
 const result=cutResult(version,sourceStart,sourceEnd);
 return `<div class="fine-cut-summary ${result.unchanged?'unchanged':''}" role="status"><strong>${result.unchanged?'未产生有效精简':`实际精简 ${result.removedDuration.toFixed(2)} 秒`}</strong><div class="fine-cut-counts"><span>候选 ${result.suggested} 处</span><span>已阻止 ${result.blocked} 处</span><span>实际应用 ${result.applied} 处</span></div>${result.explanation?`<p>${esc(result.explanation)}</p>`:''}</div>`;
}

const locatedInterval=(interval:{start:number|null;end:number|null})=>typeof interval.start==='number'&&Number.isFinite(interval.start)&&typeof interval.end==='number'&&Number.isFinite(interval.end)&&interval.end>interval.start;

export function restorableCandidate(version:CutResultVersion,id:string){
 const candidate=(version.cut_ledger??version.candidate_ledger?.candidates??[]).find(c=>c.id===id);
 return candidate?.status==='applied'&&locatedInterval(candidate)&&(!candidate.effective_intervals||candidate.effective_intervals.some(locatedInterval))?candidate:null;
}

export function cutLedgerHtml(version:CutResultVersion,sourceStart:number,busy=false){
 const candidates=version.cut_ledger??version.candidate_ledger?.candidates;
 if(!candidates?.length)return '';
 const time=(n:number)=>`${Math.floor(n/60).toString().padStart(2,'0')}:${(n%60).toFixed(2).padStart(5,'0')}`;
 return `<details class="fine-deletions fine-cut-ledger"><summary>查看删点与保留原因 · ${candidates.length} 处</summary><p class="fine-cut-note">时间相对粗剪片段；点击时间可查看原声。</p>${candidates.map(c=>{
  const intervals=c.status==='applied'&&c.effective_intervals?c.effective_intervals.filter(locatedInterval):locatedInterval(c)?[c]:[];
  const retained=c.status==='suggested'&&(c.decision==='keep'||(!c.decision&&!busy&&!!c.reason));
  const label=c.status==='applied'?(c.decision==='manual'?'手动应用':'已应用'):c.status==='blocked'||retained?'已保留':c.status==='restored'?'已恢复':'待处理';
  const times=intervals.map(interval=>`<button class="text-button" data-fine-action="seek-source" data-seconds="${interval.start}">${time(Math.max(0,interval.start!-sourceStart))} — ${time(Math.max(0,interval.end!-sourceStart))}</button>`).join('');
  return `<article class="fine-cut-item ${c.status==='applied'?'applied':c.status==='blocked'?'blocked':'retained'}"><div class="fine-cut-item-head">${times||'<span class="fine-cut-unlocated">暂时无法定位</span>'}<span class="fine-cut-label">${label}</span></div><p>${esc(c.reason)}</p>${c.text||c.quote?`<blockquote>${esc(c.text||c.quote)}</blockquote>`:''}${c.status==='blocked'&&c.block_reason?`<small>保留原因：${esc(c.block_reason)}</small>`:''}${restorableCandidate(version,c.id)?`<button class="secondary-button" data-fine-action="restore-candidate" data-candidate="${esc(c.id)}" ${busy?'disabled':''}>恢复这段</button>`:''}</article>`;
 }).join('')}</details>`;
}
