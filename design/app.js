'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const icon=name=>`<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=seconds=>[Math.floor(seconds/3600),Math.floor(seconds/60)%60,Math.floor(seconds%60)].map(v=>String(v).padStart(2,'0')).join(':');
const shortTime=seconds=>seconds>=3600?time(seconds):time(seconds).slice(3);
const minutes=seconds=>`${Math.floor(seconds/60)} 分 ${seconds%60} 秒`;
const image='assets/stream-room.png';
const baseClips=[
  {id:1,title:'以为关了麦，其实全听见了',type:'搞笑整活',start:1376,end:1478,quote:'我以为我关麦了，结果只是把耳机摘了。',reason:'偷偷吐槽被观众听见，完整保留铺垫、反转和主播的后续反应。'},
  {id:2,title:'第一次直播，忘了自己的名字',type:'聊天故事',start:2494,end:2670,quote:'大家好，我是……我是谁来着？',reason:'从开播前的准备，讲到第一位观众的安慰，一段有始有终的小故事。'},
  {id:3,title:'“看你几点下播，我就几点睡”',type:'弹幕互动',start:3812,end:3898,quote:'我等你们睡，你们等我下播，这不就死循环了吗？',reason:'观众和主播互相接梗，保留完整对话，让笑点自然落地。'},
  {id:4,title:'我只是去买水，却带回来一只猫',type:'聊天故事',start:4925,end:5090,quote:'它自己走过来的。现在倒好，整个家都是它的。',reason:'从猫咪抢镜聊到雨天的相遇，日常里藏着一段温暖的回忆。'},
  {id:5,title:'我的厨艺，外卖软件最了解',type:'搞笑整活',start:6198,end:6326,quote:'这道菜叫，承认自己的极限。',reason:'一场做饭翻车，以最后的外卖订单收尾，前后呼应又好笑。'},
  {id:6,title:'长大，不是把喜欢的东西丢掉',type:'弹幕互动',start:7510,end:7688,quote:'开心又不是什么需要考试才能获得的资格。',reason:'认真回应观众的疑问，保留独立完整的观点，适合温柔的结尾。'}
];
const initialPrefs={duration:'smart',topics:['自动判断'],output:'separate',autoExport:true};
let prefs={...initialPrefs,topics:[...initialPrefs.topics]},source=null,subtitleFile=null,chatFile=null,page='home',taskFilter='all',resultFilter='all',currentTaskId='demo-1',activeJob=null,jobTimer=null,toastTimer;
const selected=new Set();
const downloads=[];
const tasks=[
  {id:'demo-1',title:'今晚不打游戏，聊点有的没的',duration:'02:18:46',date:'09 月 28 日',status:'complete',clips:baseClips.map(c=>({...c})),prefs:{...initialPrefs},autoExport:false},
  {id:'demo-2',title:'周末闲聊 · 和你们分享一点小事',duration:'01:42:08',date:'09 月 27 日',status:'complete',clips:baseClips.slice(0,4).map(c=>({...c})),prefs:{...initialPrefs},autoExport:false}
];
const dropzoneInitial=$('#dropzoneContent').innerHTML;
const currentTask=()=>tasks.find(t=>t.id===currentTaskId);
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4200);}
function bindPageButtons(root=document){root.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>navigate(button.dataset.page));}
function navigate(next){page=next;['home','tasks','processing','results','exports'].forEach(name=>$('#'+name+'Page').hidden=name!==next);$$('.sidebar [data-page]').forEach(button=>button.classList.toggle('active',button.dataset.page===next||(button.dataset.page==='tasks'&&['processing','results'].includes(next))));$('#pageBreadcrumb').textContent={home:'新建切片',tasks:'全部任务',processing:'正在自动切片',results:'精彩片段',exports:'导出记录'}[next];if(next==='tasks')renderTasks();if(next==='exports')renderExports();window.scrollTo({top:0,behavior:'instant'});}
function taskHTML(task,index){
  const total=task.clips.reduce((sum,c)=>sum+c.end-c.start,0);
  return `<div class="task-row"><div class="task-source"><div class="task-thumb ${index%2?'variant':''}"><img src="${image}" alt="" loading="lazy"><span class="thumb-play">${icon('play')}</span></div><div style="min-width:0"><h3 class="task-title" title="${esc(task.title)}">${esc(task.title)}</h3><div class="task-meta"><span>${task.duration}</span><i>·</i><span>${task.date}</span><span class="tiny-tag">示例录播</span></div></div></div><div class="task-result">${task.status==='complete'?`${task.clips.length} 个片段`:'—'}<small>${task.status==='complete'?`共 ${minutes(total)}`:task.status==='processing'?'自动处理中':'尚未生成片段'}</small></div><span class="task-status ${task.status==='cancelled'?'cancelled':''}">${{complete:'已完成',processing:'演示处理中',cancelled:'已取消'}[task.status]}</span><button class="task-action" data-task="${task.id}">${task.status==='processing'?'查看进度':task.status==='cancelled'?'重新开始':'查看结果'}${icon('arrow')}</button></div>`;
}
function bindTaskButtons(){ $$('[data-task]').forEach(button=>button.onclick=()=>{const t=tasks.find(item=>item.id===button.dataset.task);if(t.status==='complete')openResults(t.id);else if(t.status==='processing')navigate('processing');else{chooseDemo();navigate('home');toast('已准备示例录播，可以重新开始');}});}
function renderTasks(){
  $('#recentTasks').innerHTML=tasks.slice(0,2).map(taskHTML).join('');$('#recentCount').textContent=tasks.length;$('#taskCount').textContent=tasks.length;
  const query=$('#taskSearch').value.trim();const filtered=tasks.filter(t=>(taskFilter==='all'||t.status===taskFilter)&&t.title.includes(query));
  $('#allTasks').innerHTML=filtered.map(taskHTML).join('')||'<div class="table-empty">没有符合条件的任务</div>';bindTaskButtons();
}
function updateSource(){
  if(!source){$('#dropzoneContent').innerHTML=dropzoneInitial;$('#startButton').disabled=true;return;}
  $('#dropzoneContent').innerHTML=`<div class="selected-source">${source.demo?`<img class="source-preview" src="${image}" alt="示例录播画面">`:`<div class="source-preview-icon">${icon('film')}</div>`}<h3 title="${esc(source.name)}">${esc(source.name)}</h3><p>${source.demo?'02:18:46 · 1920 × 1080':`${(source.size/1024/1024).toFixed(1)} MB · 本地素材`}</p><span class="demo-tag">${source.demo?'示例素材':'仅预览文件信息'}</span><div class="replace-note">${source.demo?'点击可换成你自己的录播':'点击更换视频'}</div></div>`;
  $('#startButton').disabled=false;$('#startHint').textContent=source.demo?'设计稿将演示自动处理流程，不调用模型或 API':'设计稿支持选择素材；真实处理将在客户端接入';
}
function chooseDemo(){source={name:'今晚不打游戏，聊点有的没的.mp4',demo:true};updateSource();}
function acceptVideo(file){if(!file)return;if(!/\.(mp4|mkv|flv|mov|webm)$/i.test(file.name)){toast('请选择 MP4、MKV、FLV、MOV 或 WebM 视频文件');return;}source={name:file.name,size:file.size,demo:false};updateSource();}
function showModal(html,wide=false){$('#modal').classList.toggle('preview-dialog',wide);$('#modalContent').innerHTML=html;$('#modal').showModal();$$('[data-close]').forEach(b=>b.onclick=()=>$('#modal').close());}
const modalHeading=(kicker,title,description)=>`<div class="modal-kicker">${kicker}</div><h2 class="modal-title">${title}</h2><p class="modal-description">${description}</p>`;
function start(){
  if(activeJob){navigate('processing');toast('已有一个演示任务正在进行');return;}
  if(!source)return;
  if(!source.demo){showModal(modalHeading('DESIGN PREVIEW','素材已选好，先体验自动流程','当前是 HTML 交互设计稿，还没有接入本地 ASR、API 或视频导出。你的文件不会被读取或上传。')+`<div class="info-note">点击下方按钮将使用内置示例录播演示处理与结果。示例精彩片段与你选择的视频无关。</div><div class="modal-footer"><button class="secondary-button" data-close>返回</button><button class="primary-button" id="runExample">体验示例流程 ${icon('arrow')}</button></div>`);$('#runExample').onclick=()=>{$('#modal').close();runDemo();};}else runDemo();
}
function demoClips(settings){
  const chosen=baseClips.filter(c=>settings.topics.includes('自动判断')||settings.topics.includes(c.type)).map(c=>({...c}));
  if(settings.duration==='short')chosen.forEach((c,i)=>c.end=c.start+[48,55,42,59,51,46][i%6]);
  if(settings.duration==='medium')chosen.forEach(c=>c.end=Math.min(c.end,c.start+180));
  return chosen;
}
function runDemo(){
  const settings={...prefs,topics:[...prefs.topics],autoExport:$('#autoExport').checked};
  const id=`example-${Date.now()}`;
  const task={id,title:'今晚不打游戏，聊点有的没的',duration:'02:18:46',date:'刚刚',status:'processing',clips:[],prefs:settings,autoExport:settings.autoExport,progress:0};
  tasks.unshift(task);activeJob=task;
  $('#processingContent').innerHTML=`<div class="processing-top"><button class="text-button" data-page="home">${icon('back')}返回首页</button><span class="design-badge">演示任务 · 不运行真实分析</span></div><div class="processing-card"><div class="processing-intro"><div class="processing-illustration process-spinner">${icon('wave')}</div><h1>正在替你找到那些好片段。</h1><p>从漫长录播里，找到笑点、故事和有趣的互动。<br>你可以离开这个页面，任务会继续进行。</p></div><div class="processing-source"><img src="${image}" alt="示例录播画面"><div>${esc(task.title)}<small>02:18:46 · 示例录播 · ${settings.output==='compilation'?'生成精彩合集':'每段单独导出'}</small></div></div><div class="progress-area"><div class="progress-label"><span id="progressText">正在准备示例素材</span><b id="progressPercent">0%</b></div><div class="progress-track" role="progressbar" aria-label="演示处理进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div id="progressFill"></div></div><div class="process-steps">${[['读取录播','准备素材'],['本地转写','整理语音内容'],['发现精彩','分析话题与反应'],[settings.autoExport?'剪辑并导出':'生成切片','保留完整上下文']].map(([label,detail],i)=>`<div class="process-step" data-stage="${i}"><div class="step-check">${i+1}</div>${label}<small>${detail}</small></div>`).join('')}</div></div><div class="processing-bottom"><span>${settings.autoExport?'已开启自动导出 · 此处仅演示完成状态':'关闭自动导出 · 完成后可预览并导出'}</span><button class="text-button" id="cancelJob">取消任务</button></div></div><p class="processing-note">这是约 12 秒的流程演示，不代表真实处理速度。<br>不会加载 ASR 模型、发送 API 请求或生成视频文件。</p>`;
  bindPageButtons($('#processingContent'));$('#cancelJob').onclick=cancelJob;renderTasks();navigate('processing');
  const started=Date.now();
  jobTimer=setInterval(()=>{
    const progress=Math.min(100,Math.floor((Date.now()-started)/120));task.progress=progress;
    const stage=Math.min(3,Math.floor(progress/25));
    $('#progressPercent').textContent=`${progress}%`;$('#progressFill').style.width=`${progress}%`;$('.progress-track').setAttribute('aria-valuenow',String(progress));
    $('#progressText').textContent=['读取录播与补充素材','本地转写与语句整理','寻找精彩内容，补全前后语境',settings.autoExport?'自动剪辑与导出流程演示':'生成精彩片段'][stage];
    $$('[data-stage]').forEach((el,i)=>{el.classList.toggle('active',i===stage);el.classList.toggle('done',i<stage);el.querySelector('.step-check').innerHTML=i<stage?icon('check'):String(i+1);});
    if(progress>=100){clearInterval(jobTimer);jobTimer=null;task.status='complete';task.clips=demoClips(settings);activeJob=null;renderTasks();if(page==='processing')openResults(id);else toast('自动切片演示已完成，可在全部任务中查看结果');}
  },300);
}
function cancelJob(){if(!activeJob)return;clearInterval(jobTimer);jobTimer=null;activeJob.status='cancelled';activeJob=null;renderTasks();navigate('tasks');toast('演示任务已取消');}
function openResults(id){currentTaskId=id;resultFilter='全部';selected.clear();currentTask().clips.forEach(c=>selected.add(c.id));renderResults();navigate('results');}
function renderResults(){
  const task=currentTask();const total=task.clips.reduce((sum,c)=>sum+c.end-c.start,0);
  $('#resultsContent').innerHTML=`<button class="text-button result-back" data-page="tasks">${icon('back')}全部任务</button><header class="result-heading"><div><div class="eyebrow">${icon('check')} AUTOMATICALLY FOUND</div><h1>这场录播，找到了 <em>${task.clips.length}</em> 个精彩片段。</h1><p>已经选好开头和结尾，预览一下，或者直接带走。<span>示例结果</span></p></div><button class="primary-button" id="exportSelected">${icon('download')}<span>导出全部片段</span></button></header><div class="result-summary">${icon('film')}<div>${esc(task.title)}<small>${task.duration} 原录播 → ${minutes(total)} 精彩内容 · ${task.prefs.output==='compilation'?'精彩合集':'独立片段'}</small></div><span class="summary-tag">${task.autoExport?'已演示自动导出流程':'转写 + 弹幕联合分析'}</span></div><div class="result-toolbar"><div class="result-filters">${['全部','搞笑整活','聊天故事','弹幕互动'].map(x=>`<button class="result-filter ${resultFilter===x?'active':''}" data-result-filter="${x}">${x}</button>`).join('')}</div><label><input type="checkbox" id="pickAll" checked>全选当前列表</label></div><div class="result-grid" id="resultGrid"></div><div class="result-bottom"><span>${icon('shield')}这里展示预设示例，尚未调用模型或生成视频。</span><button class="text-button" data-page="home">再剪一场 ${icon('arrow')}</button></div>`;
  bindPageButtons($('#resultsContent'));$('#exportSelected').onclick=()=>openExport([...selected]);
  $$('[data-result-filter]').forEach(button=>button.onclick=()=>{resultFilter=button.dataset.resultFilter;$$('[data-result-filter]').forEach(b=>b.classList.toggle('active',b===button));renderResultCards();});
  $('#pickAll').onchange=()=>{const checked=$('#pickAll').checked;visibleResults().forEach(c=>checked?selected.add(c.id):selected.delete(c.id));renderResultCards();};renderResultCards();
}
const visibleResults=()=>currentTask().clips.filter(c=>resultFilter==='全部'||c.type===resultFilter);
function renderResultCards(){
  $('#resultGrid').innerHTML=visibleResults().map((c)=>`<article class="result-card"><div class="result-image"><button data-preview="${c.id}" aria-label="预览片段：${esc(c.title)}"><img src="${image}" alt="示例录播静态画面" loading="lazy"><span class="result-play">${icon('play')}</span><span class="result-duration">${shortTime(c.end-c.start)}</span></button><label class="result-pick"><input type="checkbox" data-pick="${c.id}" aria-label="选择片段：${esc(c.title)}" ${selected.has(c.id)?'checked':''}></label></div><div class="result-body"><div class="result-kicker"><b>${c.type}</b><span>片段 ${String(c.id).padStart(2,'0')}</span></div><h2>${esc(c.title)}</h2><p>${esc(c.reason)}</p><div class="result-card-bottom"><span>${time(c.start)} – ${time(c.end)}</span><button data-export-one="${c.id}">${icon('download')}导出</button></div></div></article>`).join('')||'<div class="empty-state"><h2>这个分类没有示例片段</h2><p>切换到“全部”查看其他精彩内容。</p></div>';
  $$('[data-preview]').forEach(b=>b.onclick=()=>previewClip(Number(b.dataset.preview)));$$('[data-export-one]').forEach(b=>b.onclick=()=>openExport([Number(b.dataset.exportOne)]));$$('[data-pick]').forEach(input=>input.onchange=()=>{const id=Number(input.dataset.pick);input.checked?selected.add(id):selected.delete(id);updateResultSelection();});updateResultSelection();
}
function updateResultSelection(){const visible=visibleResults();$('#pickAll').checked=visible.length>0&&visible.every(c=>selected.has(c.id));$('#pickAll').indeterminate=visible.some(c=>selected.has(c.id))&&!$('#pickAll').checked;$('#exportSelected').disabled=selected.size===0;$('#exportSelected span').textContent=selected.size===currentTask().clips.length?'导出全部片段':`导出选中 ${selected.size} 段`;}
function previewClip(id){const c=currentTask().clips.find(c=>c.id===id);showModal(`<div class="modal-kicker">${c.type} / ${shortTime(c.end-c.start)}</div><h2 class="modal-title">${esc(c.title)}</h2><div class="preview-still"><img src="${image}" alt="示例录播静态画面"><span class="preview-static-label">静态示例 · 非真实视频</span><blockquote>${esc(c.quote)}</blockquote></div><div class="preview-caption"><span>原录播 ${time(c.start)} — ${time(c.end)}</span><span>自动保留完整上下文</span></div><p class="preview-reason"><b>为什么选中这段</b><br>${esc(c.reason)}</p><div class="modal-footer"><button class="secondary-button" data-close>返回结果</button><button class="primary-button" id="previewExport">${icon('download')}导出这个片段</button></div>`,true);$('#previewExport').onclick=()=>{$('#modal').close();openExport([id]);};}
function openExport(ids){
  const task=currentTask();const chosen=task.clips.filter(c=>ids.includes(c.id));
  showModal(modalHeading('YOUR MOMENTS, READY','导出精彩片段','精彩部分已自动定位，按你的偏好保存成独立视频或合集。')+`<div class="modal-field"><label for="exportMode">成片形式</label><select id="exportMode"><option value="separate" ${task.prefs.output==='separate'?'selected':''}>每段单独保存</option><option value="compilation" ${task.prefs.output==='compilation'?'selected':''}>合并为精彩合集</option></select></div><div class="modal-field"><label for="exportSubtitle">字幕</label><select id="exportSubtitle"><option value="srt">独立 SRT 字幕</option><option value="burn">烧录到画面</option><option value="none">不带字幕</option></select></div><div class="export-summary"><span>已选 <b>${chosen.length}</b> 个片段</span><span>共 <b>${minutes(chosen.reduce((s,c)=>s+c.end-c.start,0))}</b></span></div><div class="info-note">当前是 HTML 设计稿，只能下载示例 JSON 剪辑清单。视频和字幕的实际导出将在 Windows 客户端中接入。</div><div class="modal-footer"><button class="secondary-button" data-close>返回</button><button class="primary-button" id="downloadManifest">${icon('download')}下载示例清单</button></div>`);
  $('#downloadManifest').onclick=()=>{const plan={format:'sliceai-auto-clip-design',version:2,demo:true,source:'内置示例录播，与导入的真实文件无关',mode:$('#exportMode').value,subtitle:$('#exportSubtitle').value,clips:chosen.map(c=>({title:c.title,start:c.start,end:c.end,reason:c.reason}))};downloadJSON(plan);downloads.unshift({id:Date.now(),name:task.title,count:chosen.length,plan});$('#modal').close();toast('示例剪辑清单已下载 · 未生成视频文件');};
}
function downloadJSON(data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='SliceAI-自动切片示例.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}
function renderExports(){
  $('#exportRecords').innerHTML=downloads.length?downloads.map(d=>`<div class="export-record">${icon('file')}<div><h3>${esc(d.name)}</h3><p>${d.count} 个片段 · JSON 示例清单 · 不是视频文件</p></div><button class="secondary-button" data-download="${d.id}">${icon('download')}再次下载</button></div>`).join(''):`<div class="empty-state"><div class="empty-icon">${icon('download')}</div><h2>还没有导出记录</h2><p>在任务结果中导出精彩片段。设计稿会下载 JSON 示例清单，并记录在本次会话里。</p><button class="primary-button" data-page="tasks">查看任务 ${icon('arrow')}</button></div>`;
  bindPageButtons($('#exportRecords'));$$('[data-download]').forEach(b=>b.onclick=()=>downloadJSON(downloads.find(d=>String(d.id)===b.dataset.download).plan));
}
function settings(){showModal(modalHeading('LOCAL FIRST, ALWAYS','模型与工作空间','SliceAI 独立管理模型、配置和任务，不依赖录播软件运行。')+`<div class="setting-row"><div><h3>本地 ASR 转写</h3><p>模型按需启动，完成后释放；已有字幕时跳过转写。</p></div><span class="setting-value">本地模型</span></div><div class="setting-row"><div><h3>精彩内容分析</h3><p>使用独立配置的供应商、模型与 API Key。</p></div><span class="setting-value">API</span></div><div class="setting-row"><div><h3>自动剪辑与导出</h3><p>本地 FFmpeg 处理，保留原视频，按任务生成片段。</p></div><span class="setting-value">本地运行</span></div><div class="setting-row"><div><h3>资源使用</h3><p>长录播分块处理，限制并行任务，缩略图按需加载。</p></div><span class="setting-value">低内存优先</span></div><div class="info-note">设计稿没有安装模型、运行 FFmpeg 或调用 API，也不收集密钥。不会读取或修改 BilibiliLive 的文件与配置。</div><div class="modal-footer"><button class="primary-button" data-close>知道了</button></div>`);}
function help(){showModal(modalHeading('ONE RECORDING. A FEW GREAT MOMENTS.','导入之后，交给自动切片','首页只做必要的选择，不需要进入剪辑面板。')+`<div class="help-step"><b>01</b><div><h3>导入一段长录播</h3><p>可以附带已有的字幕或弹幕。没有字幕时，使用本地模型转写。</p></div></div><div class="help-step"><b>02</b><div><h3>自动寻找并剪出精彩部分</h3><p>通过转写理解内容，可结合弹幕反应，自动保留铺垫和结尾。</p></div></div><div class="help-step"><b>03</b><div><h3>拿到独立片段或精彩合集</h3><p>开启自动导出即可一站完成，也可以先在结果页看看，再一键导出。</p></div></div><div class="info-note">点击“试试示例录播”可以走完演示。生成进度、片段和画面都是示例；真实 ASR、API 和视频处理尚未接入。</div><div class="modal-footer"><button class="primary-button" data-close>开始体验</button></div>`);}
function exportInfo(){showModal(modalHeading('SET IT, THEN LEAVE IT','不必一直守着进度条','开启后，客户端完成精彩定位就会继续剪辑和导出，无需逐段确认。')+`<div class="setting-row"><div><h3>保存位置</h3><p>默认在原录播目录中新建 SliceAI 文件夹。</p></div>${icon('folder')}</div><div class="setting-row"><div><h3>原录播</h3><p>原文件保持不变，新视频独立保存。</p></div>${icon('shield')}</div><div class="info-note">此处是预期产品行为。HTML 演示不会写入视频目录或生成视频文件。</div><div class="modal-footer"><button class="primary-button" data-close>知道了</button></div>`);}

bindPageButtons();$('.brand').onclick=e=>{e.preventDefault();navigate('home');};
$$('[data-action]').forEach(button=>button.onclick=()=>({settings,help,exportInfo})[button.dataset.action]());
$('#demoButton').onclick=()=>{chooseDemo();toast('已添加示例录播，点击“开始自动切片”体验完整流程');};
$('#dropzone').onclick=()=>$('#videoFile').click();$('#dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('#videoFile').click();}};
$('#videoFile').onchange=()=>acceptVideo($('#videoFile').files[0]);
$('#dropzone').addEventListener('dragover',e=>{e.preventDefault();$('#dropzone').classList.add('dragging');});$('#dropzone').addEventListener('dragleave',()=>$('#dropzone').classList.remove('dragging'));$('#dropzone').addEventListener('drop',e=>{e.preventDefault();$('#dropzone').classList.remove('dragging');const file=[...e.dataTransfer.files].find(f=>/\.(mp4|mkv|flv|mov|webm)$/i.test(f.name));if(file)acceptVideo(file);else toast('拖入的文件中没有支持的视频格式');});
$('#subtitleButton').onclick=()=>$('#subtitleFile').click();$('#chatButton').onclick=()=>$('#chatFile').click();
$('#subtitleFile').onchange=()=>{const file=$('#subtitleFile').files[0];if(!file)return;if(!/\.(srt|vtt)$/i.test(file.name)){toast('请选择 SRT 或 VTT 字幕');return;}subtitleFile=file;$('#subtitleName').textContent=file.name;$('#subtitleButton').classList.add('attached');toast('已选择字幕 · 设计稿只读取文件名');};
$('#chatFile').onchange=()=>{const file=$('#chatFile').files[0];if(!file)return;if(!/\.(xml|json)$/i.test(file.name)){toast('请选择 XML 或 JSON 弹幕');return;}chatFile=file;$('#chatName').textContent=file.name;$('#chatButton').classList.add('attached');toast('已选择弹幕 · 设计稿只读取文件名');};
$$('#durationChoices .segment').forEach(button=>button.onclick=()=>{prefs.duration=button.dataset.value;$$('#durationChoices .segment').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});$('#durationHint').textContent={short:'适合快速分享的短片，单段控制在 30–60 秒。',medium:'给铺垫和互动多一点空间，单段 1–3 分钟。',smart:'优先保留完整语意，让故事有头有尾。'}[prefs.duration];});
$$('#topicChoices .topic').forEach(button=>button.onclick=()=>{const value=button.dataset.value;if(value==='自动判断')prefs.topics=['自动判断'];else{prefs.topics=prefs.topics.filter(x=>x!=='自动判断');prefs.topics.includes(value)?prefs.topics=prefs.topics.filter(x=>x!==value):prefs.topics.push(value);if(!prefs.topics.length)prefs.topics=['自动判断'];}$$('#topicChoices .topic').forEach(b=>{const active=prefs.topics.includes(b.dataset.value);b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));b.innerHTML=esc(b.dataset.value)+(active?icon('check'):'');});});
$$('#outputChoices .output-option').forEach(button=>button.onclick=()=>{prefs.output=button.dataset.value;$$('#outputChoices .output-option').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});});
$('#startButton').onclick=start;$('#taskSearch').addEventListener('input',renderTasks);
$$('[data-task-filter]').forEach(button=>button.onclick=()=>{taskFilter=button.dataset.taskFilter;$$('[data-task-filter]').forEach(b=>b.classList.toggle('active',b===button));renderTasks();});
document.addEventListener('keydown',e=>{if($('#modal').open||e.target.closest('input,textarea,select,button,[role=button]'))return;if(e.key.toLowerCase()==='n'){e.preventDefault();navigate('home');}});
$('#modal').addEventListener('click',e=>{if(e.target!==$('#modal'))return;const r=$('#modal').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('#modal').close();});
$$('.segment,.topic,.output-option').forEach(b=>b.setAttribute('aria-pressed',String(b.classList.contains('active'))));
renderTasks();
