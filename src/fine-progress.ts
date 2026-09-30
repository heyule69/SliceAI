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

export function executionOutcome(p:Snapshot,hasPreview=false){
 const state=p.error?'failed':p.execution?.state;
 const issue=executionIssue(p);
 if(p.execution?.command==='edit_export'&&issue){
  const status=issue==='failed'?'导出失败':issue==='cancelled'?'导出已取消':'导出已中断';
  return `<span class="edit-agent-outcome ${issue==='failed'?'failed':'stopped'}">${status} · ${hasPreview?'已生成成片仍可观看':'已有成果保留'}</span>`;
 }
 if(state==='failed')return '<span class="edit-agent-outcome failed">处理未完成 · 已有成果保留</span>';
 if(state==='cancelled'||state==='interrupted'||/取消|中断/.test(p.stage))return '<span class="edit-agent-outcome stopped">处理已停止 · 草稿已保留</span>';
 if(state==='done')return `<span class="edit-agent-outcome done">${check}${p.execution?.command==='edit_export'?'导出完成':'处理完成'}</span>`;
 return '';
}
