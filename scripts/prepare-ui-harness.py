"""Generate a browser-only Tauri adapter for visual QA; never included in the app build."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'.test-artifacts'
target.mkdir(exist_ok=True)
html=(ROOT/'index.html').read_text(encoding='utf-8').replace(
    '<script type="module" src="/src/main.ts"></script>',
    '<script type="module" src="/.test-artifacts/ui-harness.js"></script>')
(target/'ui-harness.html').write_text(html,encoding='utf-8')
(target/'ui-harness.js').write_text('''
const result = await (await fetch('/.test-artifacts/release-smoke/result.json')).json();
const callbacks = new Map(), listeners = new Map(); let id = 0;
const state = {tasks:[result], model:{ready:true,path:'QA model'},data_dir:'QA data',tools:{},settings:{
 api_base:'http://127.0.0.1:9999/v1',api_model:'mock-ui-only',api_json_mode:true,key_saved:true,
 output_dir:'',asr_threads:2,max_clips:12,chat_offset:0,asr_model_dir:'',ffmpeg_path:'',ffprobe_path:''}};
window.isTauri = true;
window.__TAURI_INTERNALS__ = {
 metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},
 transformCallback(fn){const key=++id;callbacks.set(key,fn);return key;},
 convertFileSrc(path){return '/@fs/'+path.replaceAll('\\\\','/');},
 async invoke(cmd,args){
  if(cmd==='plugin:event|listen'){listeners.set(args.event,args.handler);return ++id;}
  if(cmd==='plugin:event|unlisten')return;
  if(cmd==='plugin:dialog|open')return result.video;
  if(cmd==='call'){
   const r=args.request;
   if(r.cmd==='state')return structuredClone(state);
   if(r.cmd==='save_settings'){Object.assign(state.settings,r.values);return state.settings;}
   if(r.cmd==='api_test')return {ok:true};
   if(r.cmd==='probe')return {...result.media,thumbnail:result.thumbnail};
   if(r.cmd==='preview')return {path:result.exports[0].path};
   if(r.cmd==='create_task')return {...structuredClone(result),status:'queued',progress:0,stage:'界面验收：等待处理'};
  }
  if(cmd==='enqueue'){
   for(const [delay,status,progress,stage] of [[100,'transcribing',20,'界面验收：本地转写'],[700,'analyzing',55,'界面验收：AI 分析'],[1400,'complete',100,'处理完成']]){
    setTimeout(()=>{const task={...structuredClone(result),status,progress,stage};state.tasks=[task];callbacks.get(listeners.get('worker-event'))?.({payload:{type:status==='complete'?'finished':'task',cmd:args.request.cmd,task_id:task.id,task,result:task}});},delay);
   }
   return;
  }
  if(cmd==='reveal')return;
  throw new Error('Unsupported QA call: '+cmd);
 }
};
await import('/src/main.ts');
document.querySelector('.design-badge').textContent='界面验收 · 测试数据';
''',encoding='utf-8')
print(target/'ui-harness.html')
