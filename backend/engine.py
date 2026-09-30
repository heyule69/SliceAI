from __future__ import annotations
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

class Cancelled(Exception):
    pass

def emit(event):
    print(json.dumps({'event':event},ensure_ascii=False),flush=True)

def check_cancel(store, task_id=None):
    if (store.root/'STOP').exists() or (task_id and (store.task_dir(task_id)/'cancel').exists()):
        raise Cancelled('任务已取消')

def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,
                       creationflags=CREATE_FLAGS,timeout=15)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

def command(args, store, task_id=None, on_line=None, timeout=None):
    """Drain output concurrently; cancellation terminates FFmpeg/ASR descendants too."""
    check_cancel(store,task_id)
    proc=subprocess.Popen([str(a) for a in args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL,creationflags=CREATE_FLAGS,
                          env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1'})
    lines=queue.Queue(maxsize=200)
    def reader():
        try:
            for line in proc.stdout:
                lines.put(line.decode('utf-8',errors='replace').rstrip())
        finally:
            lines.put(None)
    threading.Thread(target=reader,daemon=True).start()
    tail=[]; started=time.monotonic()
    try:
        while True:
            check_cancel(store,task_id)
            if timeout and time.monotonic()-started>timeout:
                raise ValueError('外部工具运行超时。')
            try:
                line=lines.get(timeout=.15)
            except queue.Empty:
                continue
            if line is None:
                break
            tail.append(line)
            tail=tail[-25:]
            if on_line:
                on_line(line)
        code=proc.wait(timeout=15)
        if code:
            raise ValueError('外部工具执行失败：'+ '\n'.join(tail)[-1600:])
        return '\n'.join(tail)
    except BaseException:
        kill_tree(proc)
        raise
    finally:
        if proc.stdout:
            proc.stdout.close()

def resource_dir():
    return Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent

def tool_path(settings,name):
    override=settings.get(name+'_path','').strip()
    if override:
        path=Path(override)
        if not path.is_file():
            raise ValueError(f'{name} 路径不存在，请在设置中更正。')
        return str(path.resolve())
    for folder in (resource_dir()/'bin',resource_dir()/'_internal'/'bin'):
        path=folder/(name+'.exe' if os.name=='nt' else name)
        if path.is_file():
            return str(path)
    path=shutil.which(name)
    if path:
        return path
    raise ValueError(f'未找到 {name}，请在设置中选择可执行文件。')

def probe(path,settings,store):
    path=Path(path).resolve()
    if not path.is_file():
        raise ValueError('录播文件不存在，可能已被移动或删除。')
    exe=tool_path(settings,'ffprobe')
    proc=subprocess.run([exe,'-v','error','-show_entries','format=duration:stream=codec_type,width,height,duration','-of','json',str(path)],
                        capture_output=True,creationflags=CREATE_FLAGS,timeout=45)
    if proc.returncode:
        raise ValueError('无法读取录播，请检查格式和文件是否完整。')
    info=json.loads(proc.stdout.decode('utf-8',errors='strict'))
    video=next((s for s in info.get('streams',[]) if s.get('codec_type')=='video'),None)
    if not video:
        raise ValueError('选择的文件没有视频轨道。')
    duration=float(info.get('format',{}).get('duration',video.get('duration',0)))
    if not math.isfinite(duration) or duration<=0:
        raise ValueError('无法确定录播时长，请先修复录播时间戳。')
    return {'path':str(path),'name':path.stem,'duration':duration,'width':video.get('width',0),
            'height':video.get('height',0),'size':path.stat().st_size,
            'audio':any(s.get('codec_type')=='audio' for s in info.get('streams',[]))}

def chat_api(settings,messages,store,task_id=None,on_usage=None):
    if not settings.get('api_key'):
        raise ValueError('请先在设置中保存 SliceAI 独立的 API Key。')
    base=settings['api_base'].rstrip('/')
    url=base if base.endswith('/chat/completions') else base+'/chat/completions'
    payload={'model':settings['api_model'],'messages':messages,'temperature':.25,'max_tokens':4096,'stream':False}
    # DeepSeek currently defaults to thinking; explicitly use economical non-thinking analysis.
    from urllib.parse import urlparse
    if urlparse(url).hostname=='api.deepseek.com':
        payload['thinking']={'type':'disabled'}
    if settings.get('api_json_mode'):
        payload['response_format']={'type':'json_object'}
    data=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    def request():
        req=urllib.request.Request(url,data=data,headers={'Authorization':'Bearer '+settings['api_key'],
                                                          'Content-Type':'application/json','User-Agent':'SliceAI/0.1'})
        # Never forward an Authorization header through a redirect to another endpoint.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):
                return None
        opener=urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req,timeout=settings['api_timeout']) as response:
                body=response.read(2*1024*1024+1)
                if len(body)>2*1024*1024:
                    raise ValueError('API 响应超出大小限制。')
            parsed=json.loads(body.decode('utf-8'))
            choice=parsed['choices'][0]
            if choice.get('finish_reason')=='length':
                raise ValueError('API 输出被长度限制截断，请使用支持更长输出的模型。')
            content=choice['message'].get('content')
            if not isinstance(content,str) or not content.strip():
                raise ValueError('API 没有返回文本内容，请检查模型是否支持 Chat Completions。')
            return content,parsed.get('usage') or {}
        except urllib.error.HTTPError as exc:
            # Do not reflect provider bodies; they can contain credentials or uploaded text.
            labels={401:'API Key 无效或已过期',403:'API 没有访问权限',429:'API 限流或额度不足',400:'请求参数不兼容，可尝试关闭 JSON 模式',404:'API 地址或模型名称不存在'}
            raise ValueError(f'API HTTP {exc.code}：'+labels.get(exc.code,'服务请求失败，请稍后重试')) from None
        except (urllib.error.URLError,TimeoutError):
            raise ValueError('API 网络请求失败或超时，请检查网络、API 地址和超时设置。') from None
        except (KeyError,IndexError,TypeError,json.JSONDecodeError):
            raise ValueError('API 返回格式不兼容，需要 OpenAI 兼容的 Chat Completions 接口。') from None
    results=queue.Queue()
    def execute():
        try:
            results.put((True,request()))
        except Exception as exc:
            results.put((False,exc))
    threading.Thread(target=execute,daemon=True).start()
    while True:
        check_cancel(store,task_id)
        try:
            ok,value=results.get(timeout=.15)
            if ok:
                content,usage=value
                if on_usage:on_usage(usage)
                return content
            raise value
        except queue.Empty:
            continue

def decode_json(content):
    text=content.strip()
    if text.startswith('```'):
        text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I)
        text=re.sub(r'\s*```$','',text)
    try:
        value=json.loads(text)
    except json.JSONDecodeError:
        raise ValueError('模型未返回有效 JSON，请更换模型或开启 JSON 模式后重试。') from None
    if not isinstance(value,dict):
        raise ValueError('模型返回结果必须是 JSON 对象。')
    return value

def thumbnail(source,output,at,settings,store,task_id=None):
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    command([tool_path(settings,'ffmpeg'),'-hide_banner','-v','error','-nostdin','-y','-ss',str(max(0,at)),
             '-i',source,'-frames:v','1','-vf','scale=480:-2','-threads','1',str(output)],store,task_id,timeout=60)
    return str(output)
