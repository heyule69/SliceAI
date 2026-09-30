"""Find audible laughter candidates locally, independently of ASR word matches."""
import csv,json,subprocess,urllib.request,sys
from pathlib import Path
import numpy as np
import onnxruntime as ort
root=Path(__file__).resolve().parents[1];assets=root/'.test-artifacts/audio-comparison/yamnet';assets.mkdir(exist_ok=True)
for name in ['yamnet.onnx','yamnet_class_map.csv','LICENSE']:
    dest=assets/name
    if not dest.exists():
        print('Downloading '+name,flush=True)
        with urllib.request.urlopen('https://huggingface.co/audiomagic/yamnet-onnx/resolve/main/'+name,timeout=60) as response:
            data=response.read()
        if name.endswith(('.csv','LICENSE')):dest.write_text(data.decode('utf-8'),encoding='utf-8')
        else:dest.write_bytes(data)
labels=list(csv.DictReader((assets/'yamnet_class_map.csv').open(encoding='utf-8',newline='')))
laugh=[int(r['index']) for r in labels if any(s in r['display_name'].lower() for s in ['laugh','giggle','snicker','chuckle','chortle'])]
opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
model=ort.InferenceSession(str(assets/'yamnet.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
ffmpeg=root/'src-tauri/resources/worker/bin/ffmpeg.exe'
video=next(Path('D:/Download/BaiduNetdisk').glob('2026-08-28*.mp4'))
results=[]
starts=list(range(700,3100,30))+list(range(7800,8700,30))+list(range(14000,15100,30)) if '--broad' in sys.argv else [2280,7340,7740,13480,14070,11570,17180,2170,15000,16000,19000]
for start in starts:
    raw=subprocess.check_output([str(ffmpeg),'-v','error','-ss',str(start),'-i',str(video),'-t','45','-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'],creationflags=0x08000000)
    scores=model.run(['output_0'],{model.get_inputs()[0].name:np.frombuffer(raw,dtype=np.float32)})[0]
    values=scores[:,laugh].max(axis=1);frame=int(values.argmax());top=np.argsort(scores[frame])[-6:][::-1]
    row={'window_start':start,'peak_time':round(start+frame*.48,2),'laughter_score':round(float(values[frame]),4),'top':[{labels[i]['display_name']:round(float(scores[frame,i]),4)} for i in top]}
    results.append(row)
    if row['laughter_score']>.15 or len(results)%20==0:print(json.dumps(row,ensure_ascii=False),flush=True)
path=root/'test-results/v0.2/audio-comparison'/('laughter-candidates-broad.json' if '--broad' in sys.argv else 'laughter-candidates.json');path.write_text(json.dumps(sorted(results,key=lambda r:-r['laughter_score']),ensure_ascii=False,indent=2),encoding='utf-8')
