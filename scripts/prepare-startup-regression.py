"""Browser-only integration fixture for the real start button, without API calls."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
(root/'.test-artifacts').mkdir(parents=True,exist_ok=True)
html=(root/'index.html').read_text(encoding='utf-8').replace('/src/main.ts','/.test-artifacts/startup-regression.js')
(root/'.test-artifacts/startup-regression.html').write_text(html,encoding='utf-8')
(root/'.test-artifacts/startup-regression.js').write_text('''
const scenario=new URLSearchParams(location.search).get('case')||'stale-key';
const callbacks=new Map();let callbackId=0,reads=0,created=0,queued=0;
const settings={api_base:'https://api.deepseek.com',api_model:'deepseek-flash',api_json_mode:true,key_saved:true,output_dir:'',asr_threads:2,max_clips:12,chat_offset:0,asr_model_dir:'',ffmpeg_path:'',ffprobe_path:''};
const task={id:'qa-task',title:'启动回归测试',video:'QA.mp4',duration:60,created:new Date().toISOString(),status:'queued',stage:'等待处理',progress:0,error:'',thumbnail:'',clips:[],exports:[],prefs:{output:'separate'}};
function state(){reads++;document.body.dataset.stateReads=String(reads);return {settings:{...settings,key_saved:!(scenario==='missing-key'||scenario==='stale-key'&&reads===1)},tasks:created?[task]:[],edits:[],model:{ready:!(scenario==='missing-asr'||scenario==='stale-asr'&&reads===1),path:'QA'},data_dir:'QA',tools:{}};}
window.isTauri=true;
window.__TAURI_INTERNALS__={metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},transformCallback(fn){const n=++callbackId;callbacks.set(n,fn);return n;},convertFileSrc(path){return path;},async invoke(cmd,args){
 if(cmd==='plugin:event|listen')return ++callbackId;
 if(cmd==='plugin:event|unlisten')return;
 if(cmd==='plugin:dialog|open')return scenario==='with-subtitle'?'QA.srt':'QA.mp4';
 if(cmd==='call'){
  const req=args.request;
  if(req.cmd==='state'){await new Promise(resolve=>setTimeout(resolve,80));const result=state();if(scenario==='with-subtitle')result.model.ready=false;return result;}
  if(req.cmd==='probe')return {path:'QA.mp4',name:'启动回归测试',duration:60,width:1280,height:720,size:1024,thumbnail:''};
  if(req.cmd==='create_task'){created++;document.body.dataset.created=String(created);return structuredClone(task);}
  throw Error('Unexpected test call: '+req.cmd);
 }
 if(cmd==='enqueue'){queued++;document.body.dataset.queued=String(queued);return;}
 throw Error('Unexpected test invoke: '+cmd);
}};
await import('/src/main.ts');
''',encoding='utf-8')
print('Startup regression fixture ready')
