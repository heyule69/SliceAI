from pathlib import Path
root=Path(__file__).resolve().parents[1];folder=root/'.test-artifacts'
folder.mkdir(parents=True,exist_ok=True)
html=(root/'index.html').read_text(encoding='utf-8').replace('/src/main.ts','/.test-artifacts/desktop-fixes-qa.js')
(folder/'desktop-fixes-qa.html').write_text(html,encoding='utf-8')
(folder/'desktop-fixes-qa.js').write_text('''
const handlers=new Map(),callbacks=new Map();let next=0;
const fail=new URLSearchParams(location.search).has('fail');
const task={id:'qa-progress',title:'2026-08-28_21-32-17_小小霖le_即将流落街头_录播',created:new Date().toISOString(),status:'transcribing',stage:'已转写录播 00:23:00 / 05:29:46 · 耗时 00:00:40',progress:11,duration:19786,thumbnail:'',clips:[],exports:[],prefs:{output:'separate'},error:''};
const state={tasks:[task],model:{ready:true,path:'bundled/models/sensevoice-int8'},data_dir:'QA',tools:{},settings:{api_base:'https://api.deepseek.com',api_model:'deepseek-flash',key_saved:true,api_json_mode:true,asr_threads:2,asr_model_dir:'',ffmpeg_path:'',ffprobe_path:'',output_dir:'',chat_offset:0,max_clips:12}};
window.isTauri=true;
window.__TAURI_INTERNALS__={metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},transformCallback(fn){const id=++next;callbacks.set(id,fn);return id;},convertFileSrc(path){return path;},async invoke(cmd,args){
 if(cmd==='plugin:event|listen'){const list=handlers.get(args.event)||[];list.push(args.handler);handlers.set(args.event,list);return ++next;}
 if(cmd==='plugin:event|unlisten')return;
 if(cmd==='call'){
  const r=args.request;
  if(r.cmd==='state')return structuredClone(state);
  if(r.cmd==='save_settings'){if(fail)throw Error('测试：保存失败');Object.assign(state.settings,r.values);document.body.dataset.saved='true';return state.settings;}
  if(r.cmd==='api_test')return {ok:true};
 }
 throw Error('Unexpected QA command '+cmd);
}};
// Reproduce a worker update between mouse-down and mouse-up, without synthetic clicks.
document.addEventListener('pointerdown',e=>{
 const button=e.target.closest('[data-task]');if(!button)return;
 for(let i=0;i<20;i++){
  task.progress=12+i/10;task.stage='进度更新 '+i;
  if(i===10)task.status='analyzing';
  for(const id of handlers.get('worker-event')||[])callbacks.get(id)?.({payload:{type:'task',task:structuredClone(task)}});
 }
 document.body.dataset.buttonPreserved=String(button.isConnected);
});
await import('/src/main.ts');
''',encoding='utf-8')
print('Desktop fixes QA fixture ready.')
