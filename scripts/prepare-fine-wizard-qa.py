"""Browser-only adapter: actual fine UI, isolated fake commands, no API or user-data writes."""
from pathlib import Path
root=Path(__file__).resolve().parents[1];folder=root/'.test-artifacts';folder.mkdir(exist_ok=True)
html=(root/'index.html').read_text(encoding='utf-8').replace('/src/main.ts','/.test-artifacts/fine-wizard-qa.js')
(folder/'fine-wizard-qa.html').write_text(html,encoding='utf-8')
(folder/'fine-wizard-qa.js').write_text('''
const callbacks=new Map(),listeners=[];let next=0;const requests=[];
const variant=new URLSearchParams(location.search).get('case')||'main';
let p={id:'qa-fine-'+variant,revision:0,task_id:'qa',clip_id:1,title:'带猫洗澡得皮肤病，心疼自责到哭；找宠物店退钱后发避雷帖反被网友指责',status:'idle',stage:'请选择剪辑要求',error:'',source_start:0,source_end:430,messages:[],versions:[],current_version:null,exports:[]};
function emit(payload){for(const id of listeners)callbacks.get(id)?.({payload});}
window.__TAURI_INTERNALS__={metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},transformCallback(fn){const id=++next;callbacks.set(id,fn);return id;},convertFileSrc(){return '/test-results/v0.2/qa-unavailable.mp4';},async invoke(cmd,args){
 if(cmd==='plugin:event|listen'){listeners.push(args.handler);return ++next;}if(cmd==='plugin:event|unlisten')return;
 const r=args.request;requests.push(structuredClone(r));document.body.dataset.requests=JSON.stringify(requests);
 if(cmd==='call'){
  if(r.cmd==='edit_create')return structuredClone(p);
  if(r.cmd==='edit_source')return {path:''};
  if(r.cmd==='edit_options'){if(r.revision!==p.revision)throw Error('stale');p={...p,edit_options:r.options,question_step:r.step,revision:p.revision+1};return structuredClone(p);}
  if(r.cmd==='edit_prepare'){p.status='queued';p.revision++;return structuredClone(p);}
  if(r.cmd==='edit_abandon'){p.status='idle';return structuredClone(p);}
  if(r.cmd==='edit_cancel'){p.status='idle';return structuredClone(p);}
 }
 if(cmd==='enqueue'){
  setTimeout(()=>{p.status='busy';p.stage='复核故事完整性与删减依据';p.revision++;emit({type:'edit',project:structuredClone(p)});},50);
  setTimeout(()=>{
   if(r.cmd==='edit_audio_sample')p.audio_sample={engine:'bandit-plus-dnr-11.47-speech-v1',original:{path:'original.wav'},processed:{path:'processed.wav'}};
   if(r.cmd==='edit_auto'){p.current_version='v1';p.versions=[{id:'v1',number:1,confirmed:true,summary:'保留洗澡、发现皮肤病、找店家处理和后续回应，删除重复解释。',ranges:[{start:0,end:310,reason:'保留完整事件'}],duration:310,reordered:false,subtitles:r.options.subtitles!=='none',audio_strength:0,cues:[{id:1,start:0,end:3,text:'这是待核对的字幕'}],preview:'qa-preview.mp4',caption_review:{needs_review:[1]}}];}
   p.status='idle';p.stage='预览已生成';p.revision++;emit({type:'finished',project_id:p.id,cmd:r.cmd,result:structuredClone(p)});
  },300);return;
 }
 throw Error('Unexpected QA request '+cmd+':'+r?.cmd);
}};
const {FineWorkspace}=await import('/src/fine.ts');
const navigate=page=>document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==page+'Page');
const workspace=new FineWorkspace(navigate,msg=>{document.getElementById('toast').textContent=String(msg);},async()=>{});
await workspace.load('qa',1);
document.querySelector('.design-badge').textContent='问答交互验收 · 测试数据';
''',encoding='utf-8')
print('Fine wizard browser fixture ready.')
