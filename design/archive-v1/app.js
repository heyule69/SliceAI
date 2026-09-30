'use strict';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const formatTime = (seconds) => {
  const n = Math.max(0, Math.round(seconds));
  return [Math.floor(n / 3600), Math.floor(n / 60) % 60, n % 60].map(v => String(v).padStart(2, '0')).join(':');
};
const shortTime = seconds => seconds >= 3600 ? formatTime(seconds) : formatTime(seconds).slice(3);
const durationText = seconds => `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
const totalDuration = 8326;
const categories = {fun:'搞笑整活', story:'故事分享', interaction:'弹幕互动'};
const clips = [
  {id:1, title:'以为关了麦，其实全听见了', category:'fun', start:1376, end:1478, recommended:true,
    reason:'从“偷偷吐槽”到发现没关麦，反转完整，弹幕反应集中。保留前面的铺垫，笑点才成立。', evidence:'弹幕密度明显上升',
    lines:[
      [1364,'刚才点外卖的时候，发生了一件很离谱的事。','前文'],
      [1376,'我不是说去拿一下外卖嘛，然后就跟你们说等我一下。','铺垫'],
      [1388,'我还特意看了一眼，觉得自己操作得特别专业。',''],
      [1396,'我以为我关麦了，结果只是把耳机摘了。','反转'],
      [1408,'然后我在那边跟我的猫说：今天这群人怎么这么能聊啊。',''],
      [1424,'回来一看，满屏都是“我们都听见了”。',''],
      [1442,'你们听我解释！我说的是猫，猫特别能聊。','笑点'],
      [1462,'好好好，今天的外卖钱算精神损失费，行了吧。','收尾'],
      [1485,'对了，说起这家店，我上次还点过……','后文']
    ], chat:['哈哈哈哈哈哈','原来摘耳机就是关麦','我们都听见了！！','猫：这个锅我不背','好专业的操作','已录屏，勿念']},
  {id:2,title:'第一次直播，紧张到忘了自己的名字',category:'story',start:2494,end:2702,recommended:true,
    reason:'从开播前的准备讲到第一次自我介绍，故事有完整起承转合，也保留了主播真实的紧张和自嘲。',evidence:'多位观众分享相似经历',
    lines:[[2483,'你们有没有那种，一紧张就脑袋空白的时候？','前文'],[2494,'我第一次直播，提前写了整整三页自我介绍。','铺垫'],[2520,'对着镜子练了好几遍，连挥手的角度都想好了。',''],[2550,'真的点下开播之后，我看见进来了一个人。',''],[2574,'然后我说：大家好，我是……我是谁来着？','反转'],[2612,'不是忘词，我是真的连自己的名字都忘了。',''],[2650,'那个人发了一句：别急，我们也是第一次见你。',''],[2690,'所以那句话，我到现在都记得。','收尾'],[2710,'后来就慢慢习惯了。','后文']],chat:['我面试的时候也这样','原来你也会紧张','那个观众好温柔','第一次见面也很好呀','还好你坚持下来了','从第一天看到现在']},
  {id:3,title:'“你几点睡？”“看你几点下播。”',category:'interaction',start:3812,end:3898,recommended:false,
    reason:'由一条弹幕引出的完整对话，主播与观众互相接梗。结尾自然落在“那我们都早点睡”的回应。',evidence:'观众连续接梗',
    lines:[[3800,'现在几点了，让我看一眼。','前文'],[3812,'有人问我每天几点睡觉。这个问题问得好。','铺垫'],[3826,'我还想问你们呢，你们每天几点睡？',''],[3840,'什么叫“看你几点下播”？怎么责任到我身上了？','笑点'],[3856,'那我说我在等你们睡，你们又在等我下播。',''],[3874,'这不是死循环吗，朋友们。',''],[3888,'好，那我们今天都早点睡。说好了。','收尾'],[3910,'最后再聊一个话题吧。','后文']],chat:['看你几点下播','互相等，互相熬','这就是双向奔赴吗','昨天也是这么说的','好的最后亿个话题','你先下，我就睡']},
  {id:4,title:'关于那只总抢镜的猫',category:'story',start:4925,end:5090,recommended:false,
    reason:'从猫咪抢镜讲到领养时的相遇，日常小事自然转入温暖故事，适合保留较长片段。',evidence:'温暖互动集中出现',
    lines:[[4910,'等一下，它又来了。','前文'],[4925,'这只猫每次都知道我什么时候在直播。','铺垫'],[4950,'平时叫它，它理都不理。一开麦，它就来挡屏幕。',''],[4978,'当初遇见它的时候，它也是这样，自己走过来的。',''],[5004,'我本来只是想下楼买瓶水，结果带回来一个室友。',''],[5036,'那天雨特别大，它就在便利店门口等着。',''],[5072,'现在倒好，整个家都是它的，我才是借住的。','收尾'],[5100,'来，跟大家打个招呼。','后文']],chat:['真正的主播出现了','想看猫猫','买水送猫','它选中了你','好温柔的故事','猫：租金交一下']},
  {id:5,title:'一场失败得很成功的厨艺展示',category:'fun',start:6198,end:6326,recommended:true,
    reason:'用轻松的自嘲讲述做饭翻车，事件交代清晰，最后的外卖订单形成回扣。',evidence:'笑声类弹幕集中',
    lines:[[6184,'最近确实有在研究做饭。','前文'],[6198,'昨天我严格按照教程做的，每一步都一样。','铺垫'],[6220,'教程说小火慢煎，我也小火慢煎。',''],[6242,'区别就是，人家做的是煎蛋，我做的是锅底保护膜。','笑点'],[6264,'我试着给它翻个面，连锅一起翻了。',''],[6290,'最后打开外卖软件的时候，我觉得自己终于学会了一道菜。',''],[6312,'这道菜叫：承认自己的极限。','收尾'],[6340,'下次还是先学煮面吧。','后文']],chat:['锅底保护膜哈哈哈','建议申请专利','厨房还好吗','锅：我做错了什么','外卖才是你的舒适区','承认极限也是进步']},
  {id:6,title:'长大以后，还可以做幼稚的事吗',category:'interaction',start:7510,end:7728,recommended:false,
    reason:'回应观众关于成长的疑问，表达独立完整，语气真诚，适合作为聊天录播的温柔结尾。',evidence:'观众产生共鸣',
    lines:[[7495,'我看到一条弹幕，想认真回答一下。','前文'],[7510,'你说，长大以后还喜欢这些，会不会很幼稚。','铺垫'],[7542,'我觉得长大，不是把喜欢的东西一件件丢掉。',''],[7578,'而是终于可以自己决定，什么东西值得留下来。','观点'],[7612,'可以认真工作，也可以回家之后抱着玩偶看动画。',''],[7650,'开心又不是什么需要考试才能获得的资格。',''],[7704,'所以你就大大方方地喜欢吧。','收尾'],[7740,'好，今天真的要说晚安了。','后文']],chat:['突然被安慰了','说得好温柔','喜欢不分年龄','我也还在看动画','谢谢你','今天也有好好被治愈']}
];
clips.forEach(clip => {clip.originalStart=clip.start;clip.originalEnd=clip.end;});
let currentId=1, filter='all', timeSorted=false, tab='transcript', currentTime=1396, zoom=1, speed=1, playing=false, timer=null;
const selected = new Set([1,2,5]);
let preferences={mode:'转写 + 弹幕',length:'完整片段',topics:new Set(['搞笑整活','弹幕互动']),instruction:''};
const activeClip=()=>clips.find(c=>c.id===currentId);
const recommendationOrder=[1,2,5,3,6,4];
const visibleClips=()=>clips.filter(c=>filter==='all'||c.category===filter).sort((a,b)=>timeSorted?a.start-b.start:recommendationOrder.indexOf(a.id)-recommendationOrder.indexOf(b.id));
let toastTimer;
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),3300);}
function updateSelection(){
  ['#exportCount','#selectedCount','#railCount'].forEach(s=>$(s).textContent=selected.size);
  const visible=visibleClips();
  $('#selectAll').checked=visible.length>0&&visible.every(c=>selected.has(c.id));
  $('#selectAll').indeterminate=visible.some(c=>selected.has(c.id))&&!$('#selectAll').checked;
  const saved=selected.has(currentId);
  $('#bookmarkButton').classList.toggle('selected',saved);
  $('#bookmarkButton').innerHTML=icon(saved?'check':'plus')+`<span>${saved?'已选中':'加入导出'}</span>`;
  $('#bookmarkButton').setAttribute('aria-label',saved?'取消选择当前片段':'选择当前片段');
}
function renderClips(){
  const visible=visibleClips();
  $('#resultCount').textContent=visible.length;
  $('#clipList').innerHTML=visible.map(c=>`<article class="clip-card ${c.id===currentId?'active':''}" tabindex="0" role="button" aria-label="预览：${escapeHTML(c.title)}" aria-pressed="${c.id===currentId}" data-id="${c.id}"><div class="clip-thumbnail"><img src="assets/stream-room.png" alt="" loading="lazy"><span class="thumb-order">${String(c.id).padStart(2,'0')}</span><span class="thumb-time">${shortTime(c.end-c.start)}</span></div><div><h3>${escapeHTML(c.title)}</h3><div class="clip-time">${formatTime(c.start)} — ${formatTime(c.end)}</div><div class="clip-meta"><span class="tag">${categories[c.category]}</span>${c.recommended?'<span class="recommended">推荐保留</span>':''}</div></div><label class="clip-check"><input type="checkbox" aria-label="选择片段：${escapeHTML(c.title)}" data-select="${c.id}" ${selected.has(c.id)?'checked':''}></label></article>`).join('')||'<div class="empty-state">这个分类暂时没有候选片段</div>';
  $$('.clip-card').forEach(card=>{
    card.addEventListener('click',e=>{if(!e.target.closest('.clip-check'))selectClip(Number(card.dataset.id));});
    card.addEventListener('keydown',e=>{if(e.target===card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();selectClip(Number(card.dataset.id));}});
  });
  $$('[data-select]').forEach(input=>input.addEventListener('change',()=>{const id=Number(input.dataset.select);input.checked?selected.add(id):selected.delete(id);updateSelection();}));
  updateSelection();
}
function selectClip(id){
  stopPlayback();currentId=id;const c=activeClip();currentTime=c.start;
  $('#transcriptSearch').value='';
  $('#clipOrdinal').textContent=`${String(id).padStart(2,'0')} / 06`;
  $('#detailTitle').textContent=c.title;$('#detailCategory').textContent=categories[c.category];
  $('#detailReason').textContent=c.reason;$('#reactionEvidence').textContent=c.evidence;
  renderClips();updateTrimUI();renderInspector();renderTimeline();updatePlayhead();
}
function updateTrimUI(){const c=activeClip();$('#startInput').value=formatTime(c.start);$('#endInput').value=formatTime(c.end);$('#endTime').textContent=formatTime(c.end);$('#trimDuration').textContent=shortTime(c.end-c.start);$('#detailDuration').textContent=durationText(c.end-c.start);}
function parseTime(value){const match=value.trim().match(/^(\d{1,2}):([0-5]\d):([0-5]\d)$/);return match?Number(match[1])*3600+Number(match[2])*60+Number(match[3]):NaN;}
function applyTrim(){
  const start=parseTime($('#startInput').value),end=parseTime($('#endInput').value);
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||end>totalDuration){toast('请输入有效的 时:分:秒；出点需晚于入点，且不能超出录播时长。');updateTrimUI();return;}
  stopPlayback();const c=activeClip();c.start=start;c.end=end;currentTime=Math.max(start,Math.min(currentTime,end));updateTrimUI();renderClips();renderTimeline();renderInspector();updatePlayhead();toast('剪辑区间已调整 · 仅保存在本次设计稿会话');
}
function highlight(text,query){if(!query)return escapeHTML(text);const parts=text.split(query);return parts.map(escapeHTML).join(`<mark>${escapeHTML(query)}</mark>`);}
function renderInspector(){
  const c=activeClip(),query=$('#transcriptSearch').value.trim();
  const content=$('#inspectorContent');
  $('#transcriptSearch').placeholder=tab==='chat'?'搜索弹幕内容':tab==='reason'?'搜索推荐依据':'搜索转写内容';
  $('#transcriptSearch').setAttribute('aria-label',$('#transcriptSearch').placeholder);
  $('#inspectorLabel').innerHTML=tab==='transcript'?'<span class="status-dot"></span>本地 ASR · 示例转写':tab==='chat'?'<span class="status-dot"></span>导入弹幕 · 示例数据':'<span class="status-dot"></span>API 分析 · 示例结果';
  $('#inspectorExtra').textContent=tab==='reason'?'可追溯到原文':'跟随片段';
  if(tab==='transcript'){
    const matching=c.lines.filter(line=>line[1].includes(query));
    content.innerHTML=matching.map((line)=>`${line[2]==='后文'?'<div class="context-divider">片段结束 · 后续内容</div>':''}<button class="transcript-row ${line[0]<=currentTime&&(c.lines[c.lines.indexOf(line)+1]?.[0]??Infinity)>currentTime?'current':''}" data-seek="${line[0]}"><div class="sentence-meta"><span class="sentence-time">${formatTime(line[0])}</span><span>主播</span><span class="sentence-role">${line[2]}</span></div><div class="sentence-text">${highlight(line[1],query)}</div></button>`).join('')||'<div class="empty-state">没有找到匹配的转写</div>';
  }else if(tab==='chat'){
    content.innerHTML='<div class="context-divider">精彩时刻附近的观众反应</div>'+c.chat.map((text,i)=>({text,i})).filter(item=>item.text.includes(query)).map(({text,i})=>`<button class="chat-row" data-seek="${Math.min(c.end,c.start+35+i*7)}"><div class="chat-meta"><span>观众 ${String(i+1).padStart(2,'0')}</span><span class="mono">${formatTime(Math.min(c.end,c.start+35+i*7))}</span></div><p>${highlight(text,query)}</p></button>`).join('');
    if(!c.chat.some(text=>text.includes(query)))content.innerHTML='<div class="empty-state">没有找到匹配的弹幕</div>';
  }else{
    const blocks=[['为什么值得剪',c.reason],['转写依据',c.lines.filter(l=>['反转','笑点','观点'].includes(l[2])).map(l=>`${formatTime(l[0])}「${l[1]}」`).join('；')||`${formatTime(c.lines[1][0])}「${c.lines[1][1]}」`],['弹幕依据',`${c.evidence}。例如「${c.chat[1]}」「${c.chat[3]}」。`],['边界建议',`建议从 ${formatTime(c.originalStart)} 的铺垫开始，保留到 ${formatTime(c.originalEnd)}。你可以在预览区调整首尾。`]];
    const matching=blocks.filter(b=>b.join('').includes(query));
    content.innerHTML=`<div class="reason-content"><h3>让每个推荐都有依据</h3>${matching.map(([title,text])=>`<div class="reason-block"><b>${escapeHTML(title)}</b><p>${highlight(text,query)}</p></div>`).join('')||'<div class="empty-state">没有找到匹配的依据</div>'}<p class="reason-note">以上为人工编写的示例结果，用于评审交互与信息布局；本设计稿未调用 AI 服务。</p></div>`;
  }
  $$('[data-seek]').forEach(row=>row.addEventListener('click',()=>{stopPlayback();currentTime=Number(row.dataset.seek);updatePlayhead();renderInspector();}));
}
function setTab(value){tab=value;$$('.inspector-tab').forEach(button=>{const active=button.dataset.tab===tab;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));});$('#transcriptSearch').value='';renderInspector();}
function renderTimeline(){
  $('#tracks').style.width=`${zoom*100}%`;$('#zoomLabel').textContent=`${Math.round(zoom*100)}%`;
  $('#ruler').innerHTML=Array.from({length:9},(_,i)=>`<span>${formatTime(totalDuration*i/8).slice(0,5)}</span>`).join('');
  $('#clipTrack').innerHTML=clips.map(c=>`<button class="timeline-clip ${c.id===currentId?'active':''}" style="left:${c.start/totalDuration*100}%;width:${(c.end-c.start)/totalDuration*100}%" data-timeline="${c.id}" title="${escapeHTML(c.title)} · ${formatTime(c.start)}" aria-label="定位片段：${escapeHTML(c.title)}">${String(c.id).padStart(2,'0')}</button>`).join('');
  $$('[data-timeline]').forEach(button=>button.addEventListener('click',()=>selectClip(Number(button.dataset.timeline))));
  let seed=42;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  $('#heatmap').innerHTML=Array.from({length:300},(_,i)=>{const t=i/300*totalDuration;const peak=clips.reduce((max,c)=>Math.max(max,Math.exp(-Math.pow((t-(c.originalStart+45))/110,2))*29),0);const h=3+random()*7+peak*(.5+random()*.5);return `<rect x="${i*4}" y="${42-h}" width="2.4" height="${h}" rx=".7" fill="${peak>10?'#86a89b':'#506a60'}"/>`;}).join('');
  updatePlayhead();
}
function updatePlayhead(){
  $('#currentTime').textContent=formatTime(currentTime);$('#playhead').style.left=`${currentTime/totalDuration*100}%`;$('#playheadLabel').textContent=formatTime(currentTime).slice(currentTime>=3600?0:3);
  const lines=activeClip().lines;const line=[...lines].reverse().find(l=>l[0]<=currentTime)||lines[0];$('#subtitle').textContent=currentTime<lines[0][0]||currentTime>lines[lines.length-1][0]+15?'当前位置暂无示例转写':line[1];
  $$('.transcript-row').forEach(row=>row.classList.toggle('current',Number(row.dataset.seek)===line[0]));
}
function stopPlayback(){playing=false;clearInterval(timer);timer=null;$('#playButton').innerHTML=icon('play');$('#playButton').classList.remove('playing');$('#playButton').setAttribute('aria-label','演示播放');}
function togglePlayback(){
  if(playing){stopPlayback();return;}
  const c=activeClip();if(currentTime>=c.end||currentTime<c.start)currentTime=c.start;
  playing=true;$('#playButton').innerHTML=icon('pause');$('#playButton').classList.add('playing');$('#playButton').setAttribute('aria-label','暂停演示');toast('演示播放：静态画面 + 转写时间轴，无视频或音频');
  timer=setInterval(()=>{currentTime=Math.min(activeClip().end,currentTime+speed*.25);updatePlayhead();if(currentTime>=activeClip().end)stopPlayback();},250);
}
function showModal(html){stopPlayback();$('#modalContent').innerHTML=html;$('#modal').showModal();}
const heading=(kicker,title,description)=>`<div class="modal-kicker">${kicker}</div><h2 class="modal-title">${title}</h2><p class="modal-description">${description}</p>`;
function openAnalysis(){
  showModal(heading('FIND YOUR MOMENTS','想留下什么样的片段？','先选择内容偏好，再让 AI 从转写和弹幕中寻找值得保留的瞬间。')+`<div class="field-group"><span class="field-label">分析来源</span><div class="modal-choices" id="modeChoices">${['转写 + 弹幕','仅转写','仅弹幕'].map(x=>`<button class="choice ${preferences.mode===x?'active':''}" data-value="${x}">${x}</button>`).join('')}</div></div><div class="field-group"><span class="field-label">内容偏好 · 可多选</span><div class="modal-choices" id="topicChoices">${['搞笑整活','弹幕互动','故事分享','观点金句'].map(x=>`<button class="choice ${preferences.topics.has(x)?'active':''}" data-value="${x}">${x}</button>`).join('')}</div></div><div class="field-group"><label for="lengthSelect">成片形式</label><select id="lengthSelect">${['短片 · 30–60 秒','完整片段 · 1–5 分钟','精彩合集 · 5–10 分钟','自定义时长'].map(x=>`<option ${x.includes(preferences.length)?'selected':''}>${x}</option>`).join('')}</select></div><div class="field-group" id="customLength" hidden><label for="customSeconds">每段最长时长（秒）</label><input id="customSeconds" type="number" min="10" max="1800" value="120"></div><div class="field-group"><label for="instruction">补充要求 <span class="subtle">可选</span></label><textarea id="instruction" placeholder="例如：多找主播跟弹幕互怼的片段，保留前面的铺垫。">${escapeHTML(preferences.instruction)}</textarea></div><div class="info-note">ASR 在本地完成；精彩片段分析使用你单独配置的 API。<br>当前为设计稿，保存偏好不会启动转写或发送内容。</div><div class="modal-footer"><button class="button" data-close>取消</button><button class="button primary" id="savePreferences">保存分析偏好</button></div>`);
  singleChoice('#modeChoices');$$('#topicChoices .choice').forEach(button=>button.onclick=()=>button.classList.toggle('active'));
  $('#lengthSelect').onchange=()=>$('#customLength').hidden=$('#lengthSelect').value!=='自定义时长';
  $('#savePreferences').onclick=()=>{if(!$('#customLength').hidden&&!$('#customSeconds').checkValidity()){$('#customSeconds').reportValidity();return;}preferences={mode:$('#modeChoices .active').dataset.value,length:$('#lengthSelect').value.split(' · ')[0],topics:new Set($$('#topicChoices .active').map(b=>b.dataset.value)),instruction:$('#instruction').value};$('#modal').close();toast('分析偏好已保存到本次会话 · 示例结果保持不变');};bindClose();
}
function singleChoice(container){$$(container+' .choice').forEach(button=>button.onclick=()=>{$$(container+' .choice').forEach(b=>b.classList.remove('active'));button.classList.add('active');});}
function bindClose(){$$('[data-close]').forEach(button=>button.onclick=()=>$('#modal').close());}
function openExport(){
  const chosen=clips.filter(c=>selected.has(c.id)),duration=chosen.reduce((sum,c)=>sum+c.end-c.start,0);
  showModal(heading('READY TO CUT','把精彩片段留下来','选择成片形式。客户端将使用本地 FFmpeg 完成剪辑，原始录播保持不变。')+`<div class="modal-choices" id="exportChoices"><button class="choice active" data-value="separate">每段单独导出</button><button class="choice" data-value="compilation">合并成精彩合集</button></div><div class="field-group"><label for="exportAspect">画面比例</label><select id="exportAspect"><option value="original">原始画幅 · 16:9</option><option value="portrait">竖屏 · 9:16（需确认裁切构图）</option><option value="square">方形 · 1:1（需确认裁切构图）</option></select></div><div class="field-group"><label for="exportSubtitle">字幕</label><select id="exportSubtitle"><option value="sidecar">独立 SRT 字幕</option><option value="burn">烧录到画面</option><option value="none">不导出字幕</option></select></div><div class="modal-summary"><span>已选 <b>${chosen.length}</b> 个片段</span><span>总时长 <b>${durationText(duration)}</b></span></div><div class="info-note">当前为 HTML 设计稿，可下载 JSON 剪辑清单。视频渲染、字幕导出与竖屏构图尚未接入。</div><div class="modal-footer"><button class="button" data-close>返回调整</button><button class="button primary" id="downloadPlan" ${chosen.length?'':'disabled'}>${icon('export')}下载剪辑清单</button></div>`);
  singleChoice('#exportChoices');$('#downloadPlan').onclick=()=>{const result={format:'sliceai-design-plan',version:1,demo:true,source:'雨夜杂谈（示例，不关联真实视频）',mode:$('#exportChoices .active').dataset.value,aspect:$('#exportAspect').value,subtitle:$('#exportSubtitle').value,clips:chosen.map(c=>({id:c.id,title:c.title,start:c.start,end:c.end,reason:c.reason}))};const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='SliceAI-示例剪辑清单.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1500);$('#modal').close();toast('已下载剪辑清单 · 未生成视频文件');};bindClose();
}
function openImport(){
  showModal(heading('A NEW RECORDING','从一场录播开始','添加视频，可以同时带上已有的字幕和弹幕。没有字幕时，客户端会使用本地 ASR 转写。')+`<div class="local-file">${icon('folder')}<label><h3>选择一场录播的素材</h3><p>视频 / SRT 字幕 / XML 弹幕 / JSON 数据</p><input type="file" id="importFiles" multiple accept=".mp4,.mkv,.flv,.mov,.srt,.vtt,.xml,.json"></label></div><div id="importFileList" class="field-group"></div><div class="info-note">SliceAI 使用独立的配置与工作目录，不读取其他项目的 API Key。<br>设计稿仅展示你选择的文件名，不读取文件内容，不会上传或启动分析。</div><div class="modal-footer"><button class="button" data-close>取消</button><button class="button primary" id="importPreview" disabled>确认素材选择</button></div>`);
  $('#importFiles').onchange=()=>{const files=[...$('#importFiles').files];$('#importFileList').innerHTML=files.map(f=>`<div class="asset-row">${icon('file')}<div><h3>${escapeHTML(f.name)}</h3><p>${(f.size/1024/1024).toFixed(2)} MB · 本地文件</p></div></div>`).join('');$('#importPreview').disabled=!files.length;};
  $('#importPreview').onclick=()=>{toast('已预览素材选择流程 · 真实导入将在客户端中实现');$('#modal').close();};bindClose();
}
function openSettings(){
  showModal(heading('YOUR WORKSPACE','独立、轻量的本地工作区','转写在本地运行，内容分析调用 API。以下为客户端设置的设计预览。')+`<div class="setting-row"><div><h3>语音转写</h3><p>本地 ASR · 按需启动，完成后释放模型</p></div><span class="setting-value">SenseVoice · 拟选</span></div><div class="setting-row"><div><h3>精彩片段分析</h3><p>独立配置供应商、模型与 API Key</p></div><span class="setting-value">API 模式</span></div><div class="setting-row"><div><h3>后台任务</h3><p>顺序处理长录播，限制同时运行的任务数</p></div><span class="setting-value">低内存优先</span></div><div class="setting-row"><div><h3>项目数据</h3><p>工程、缓存与配置由 SliceAI 独立管理</p></div><span class="setting-value">完全独立</span></div><div class="info-note">本设计稿没有 API 连接，也不收集或保存密钥。模型名称为方案候选，尚未安装。</div><div class="modal-footer"><button class="button primary" data-close>知道了</button></div>`);bindClose();
}
function openLibrary(){
  showModal(heading('SOURCE MATERIAL','这场录播的素材','以下为设计稿中的示例项目，展示视频、转写和弹幕的组织方式。')+`<div class="asset-row">${icon('play')}<div><h3>雨夜杂谈_2026-09-28.mp4</h3><p>02:18:46 · 1920 × 1080</p></div><span class="asset-badge">示例</span></div><div class="asset-row">${icon('file')}<div><h3>雨夜杂谈_转写.srt</h3><p>本地 ASR 转写 · 时间戳已对齐</p></div><span class="asset-badge">示例</span></div><div class="asset-row">${icon('message')}<div><h3>雨夜杂谈_弹幕.xml</h3><p>与录播关联 · 作为内容分析的辅助依据</p></div><span class="asset-badge">示例</span></div><div class="modal-footer"><button class="button" data-close>关闭</button><button class="button primary" id="libraryImport">${icon('plus')}导入其他素材</button></div>`);$('#libraryImport').onclick=()=>{$('#modal').close();openImport();};bindClose();
}
function openHelp(){showModal(heading('A QUICK TOUR','试一试这个工作台','这是一份可以操作的 HTML 设计稿。示例转写和候选由人工编写，预览使用 AI 生成的静态图片。')+`<ul class="help-list"><li><span>切换片段</span><span>点击左侧候选 / 时间轴</span></li><li><span>选择导出内容</span><span>候选复选框 / 预览区“已选中”</span></li><li><span>定位原文</span><span>点击右侧转写时间戳</span></li><li><span>模拟播放 / 暂停</span><kbd>Space</kbd></li><li><span>搜索原文</span><kbd>/</kbd></li><li><span>关闭弹窗</span><kbd>Esc</kbd></li><li><span>微调剪辑区间</span><span>修改入点、出点后按 Enter</span></li></ul><div class="modal-footer"><button class="button primary" data-close>开始体验</button></div>`);bindClose();}

const actions={workspace:()=>{filter='all';$$('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter==='all'));renderClips();$('.workspace').scrollIntoView({behavior:'smooth'});},library:openLibrary,export:openExport,settings:openSettings,import:openImport,analysis:openAnalysis,help:openHelp,fullscreen:async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('#videoWrap').requestFullscreen();}catch{toast('当前浏览器不支持全屏预览');}}};
$$('[data-action]').forEach(button=>button.addEventListener('click',()=>actions[button.dataset.action]()));
$('.brand').addEventListener('click',event=>{event.preventDefault();actions.workspace();});
$$('[data-filter]').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;$$('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));renderClips();}));
$('#sortButton').onclick=()=>{timeSorted=!timeSorted;$('#listLabel').textContent=timeSorted?'按录播时间':'按推荐顺序';$('#sortButton').innerHTML=(timeSorted?'切换为推荐排序':'切换为时间排序')+' <span>↕</span>';renderClips();};
$('#selectAll').onchange=()=>{visibleClips().forEach(c=>$('#selectAll').checked?selected.add(c.id):selected.delete(c.id));renderClips();};
$('#bookmarkButton').onclick=()=>{selected.has(currentId)?selected.delete(currentId):selected.add(currentId);renderClips();};
$('#seeEvidence').onclick=()=>setTab('reason');
$$('.inspector-tab').forEach(button=>button.onclick=()=>setTab(button.dataset.tab));
$('#transcriptSearch').addEventListener('input',renderInspector);
$('#startInput').addEventListener('change',applyTrim);$('#endInput').addEventListener('change',applyTrim);
[$('#startInput'),$('#endInput')].forEach(input=>input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();applyTrim();input.blur();}}));
$('#resetTrim').onclick=()=>{const c=activeClip();c.start=c.originalStart;c.end=c.originalEnd;selectClip(c.id);toast('已恢复推荐区间');};
$('#playButton').onclick=togglePlayback;
$('#previousClip').onclick=()=>selectClip(currentId===1?clips.length:currentId-1);
$('#nextClip').onclick=()=>selectClip(currentId===clips.length?1:currentId+1);
$('#speedButton').onclick=()=>{const speeds=[1,1.5,2];speed=speeds[(speeds.indexOf(speed)+1)%speeds.length];$('#speedButton').textContent=`${speed}×`;};
$('#zoomIn').onclick=()=>{zoom=Math.min(4,zoom+.5);renderTimeline();};
$('#zoomOut').onclick=()=>{zoom=Math.max(1,zoom-.5);renderTimeline();};
$('#fitTimeline').onclick=()=>{zoom=1;renderTimeline();$('#timelineScroll').scrollLeft=0;};
$('#tracks').addEventListener('click',event=>{if(event.target.closest('.timeline-clip'))return;const rect=$('#tracks').getBoundingClientRect();currentTime=Math.max(0,Math.min(totalDuration,(event.clientX-rect.left)/rect.width*totalDuration));stopPlayback();updatePlayhead();if(currentTime<activeClip().start||currentTime>activeClip().end)toast('已定位整场时间 · 设计稿仅提供候选片段的示例转写');renderInspector();});
document.addEventListener('keydown',event=>{if($('#modal').open||event.target.closest('input,textarea,select,button,[role=button]'))return;if(event.code==='Space'){event.preventDefault();togglePlayback();}else if(event.key==='/'){event.preventDefault();$('#transcriptSearch').focus();}});
$('#modal').addEventListener('click',event=>{if(event.target===$('#modal')){const r=$('#modal').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('#modal').close();}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPlayback();});
renderClips();updateTrimUI();renderInspector();renderTimeline();
