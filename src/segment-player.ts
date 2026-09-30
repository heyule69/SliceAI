/** A relative timeline over an existing media file; never creates a render job. */
export type Playback = {path:string; start:number; end:number; kind?:string};
const time=(s:number)=>{const n=Math.max(0,Math.floor(s));return `${n>=3600?Math.floor(n/3600)+':':''}${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};

export class SegmentPlayer {
 private start=0;private end=0;private key='';private frame=0;private ready=false;private target=0;private autoplay=false;
 private abort=new AbortController();
 private controls:HTMLDivElement;private status:HTMLDivElement;private play:HTMLButtonElement;private seekbar:HTMLInputElement;private clock:HTMLElement;private mute:HTMLButtonElement;
 constructor(readonly video:HTMLVideoElement,private compatible?:()=>void){
  const root=video.parentElement!;root.classList.add('segment-player');video.controls=false;video.preload='metadata';video.playsInline=true;
  this.status=document.createElement('div');this.status.className='segment-status';this.status.setAttribute('role','status');root.append(this.status);
  this.controls=document.createElement('div');this.controls.className='segment-controls';
  this.controls.innerHTML='<input class="segment-seek" type="range" min="0" max="1" step="0.01" value="0" aria-label="片段播放进度"><div><button class="segment-play" type="button" aria-label="播放片段">▶</button><span class="segment-clock">00:00 / 00:00</span><span class="segment-spacer"></span><button class="segment-mute" type="button" aria-label="静音">声音</button><input class="segment-volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="音量"><button class="segment-fullscreen" type="button" aria-label="全屏播放">⛶</button></div>';
  root.append(this.controls);this.play=this.controls.querySelector('.segment-play')!;this.seekbar=this.controls.querySelector('.segment-seek')!;this.clock=this.controls.querySelector('.segment-clock')!;this.mute=this.controls.querySelector('.segment-mute')!;
  const on=(element:EventTarget,event:string,fn:EventListener)=>element.addEventListener(event,fn,{signal:this.abort.signal});
  on(this.play,'click',()=>void this.toggle());on(video,'click',()=>void this.toggle());
  on(this.seekbar,'input',()=>this.seek(Number(this.seekbar.value)));
  on(this.mute,'click',()=>{video.muted=!video.muted;});
  on(this.controls.querySelector('.segment-volume')!,'input',e=>{video.volume=Number((e.target as HTMLInputElement).value);video.muted=false;});
  on(this.controls.querySelector('.segment-fullscreen')!,'click',()=>{void (document.fullscreenElement?document.exitFullscreen():root.requestFullscreen()).catch(()=>this.message('无法进入全屏'));});
  on(root,'keydown',e=>{const k=e as KeyboardEvent;if((k.target as HTMLElement).tagName==='INPUT')return;if(k.code==='Space'){k.preventDefault();void this.toggle();}else if(k.code==='ArrowRight'||k.code==='ArrowLeft'){k.preventDefault();this.seek(this.currentTime+(k.code==='ArrowRight'?5:-5));}});
  on(video,'loadedmetadata',()=>{if(this.end>video.duration+.3){this.message('片段范围超出视频，请重新定位原素材');return;}this.seek(this.target);});
  on(video,'seeked',()=>{this.ready=true;this.status.hidden=true;video.style.visibility='';this.update();if(this.autoplay){this.autoplay=false;void this.toggle();}});
  on(video,'loadeddata',()=>{if(!video.seeking&&Math.abs(video.currentTime-(this.start+this.target))<.1){this.ready=true;this.status.hidden=true;video.style.visibility='';this.update();}});
  on(video,'play',()=>this.tick());on(video,'pause',()=>{if(this.frame)cancelAnimationFrame(this.frame);this.frame=0;this.update();});
  on(video,'timeupdate',()=>this.boundary());on(video,'seeking',()=>{if(video.currentTime<this.start-.01||video.currentTime>this.end+.01)this.seek(this.currentTime);});
  on(video,'volumechange',()=>{this.mute.textContent=video.muted?'已静音':'声音';this.mute.setAttribute('aria-label',video.muted?'取消静音':'静音');});
  on(video,'error',()=>{this.message('此视频无法直接播放');if(this.compatible){const button=document.createElement('button');button.type='button';button.className='secondary-button';button.textContent='生成可播放副本';button.onclick=()=>{button.disabled=true;this.compatible?.();};this.status.append(button);}});
 }
 get currentTime(){return Math.max(0,Math.min(this.end-this.start,this.video.currentTime-this.start));}
 set(source:Playback,url:string,autoplay=false){
  const key=JSON.stringify([url,source.start,source.end]);if(this.key===key)return;
  this.video.pause();this.key=key;this.start=source.start;this.end=source.end;this.target=0;this.autoplay=autoplay;this.ready=false;
  this.video.style.visibility='hidden';this.message('正在打开片段…');this.seekbar.max=String(this.end-this.start);this.seekbar.value='0';this.clock.textContent=`00:00 / ${time(this.end-this.start)}`;
  this.video.src=url+`#t=${this.start},${this.end}`;this.video.load();
 }
 seek(relative:number){
  this.target=Math.max(0,Math.min(this.end-this.start,relative));
  if(this.video.readyState){this.video.currentTime=this.start+this.target;this.update();}
 }
 message(text:string){this.status.textContent=text;this.status.hidden=false;}
 private async toggle(){if(!this.video.paused){this.video.pause();return;}if(!this.ready)return;if(this.currentTime>=this.end-this.start-.05)this.seek(0);try{await this.video.play();}catch{this.message('无法播放，请重新打开片段');}}
 private boundary(){if(this.video.currentTime>=this.end){this.video.pause();if(this.video.currentTime>this.end+.001)this.video.currentTime=this.end;}else if(this.video.currentTime<this.start-.01)this.seek(0);this.update();}
 private tick(){this.boundary();if(!this.video.paused)this.frame=requestAnimationFrame(()=>this.tick());}
 private update(){this.seekbar.value=String(this.currentTime);this.clock.textContent=`${time(this.currentTime)} / ${time(this.end-this.start)}`;this.play.textContent=this.video.paused?'▶':'Ⅱ';this.play.setAttribute('aria-label',this.video.paused?'播放片段':'暂停片段');}
 destroy(){this.video.pause();if(this.frame)cancelAnimationFrame(this.frame);this.abort.abort();this.video.removeAttribute('src');this.video.load();this.controls.remove();this.status.remove();}
}
