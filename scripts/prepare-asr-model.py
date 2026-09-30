"""Stage existing SliceAI ASR assets for packaging; no model downloads at runtime."""
import hashlib,json,os,shutil,sys,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=Path(sys.argv[1]) if len(sys.argv)>1 else Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop/models/sensevoice-int8'
dest=root/'asr-model/SenseVoice';dest.mkdir(parents=True,exist_ok=True)
files={}
for name,minimum in [('model.int8.onnx',50_000_000),('tokens.txt',1000),('silero_vad.onnx',100_000)]:
    path=source/name
    if not path.is_file() or path.stat().st_size<minimum:raise SystemExit(f'Missing or incomplete ASR asset: {path}')
    shutil.copy2(path,dest/name)
    with path.open('rb') as stream:files[name]={'bytes':path.stat().st_size,'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}
licenses={'SenseVoice-MODEL-LICENSE.txt':'https://raw.githubusercontent.com/modelscope/FunASR/main/MODEL_LICENSE',
          'Silero-LICENSE.txt':'https://raw.githubusercontent.com/snakers4/silero-vad/master/LICENSE'}
for name,url in licenses.items():
    with urllib.request.urlopen(url,timeout=30) as response:text=response.read().decode('utf-8-sig',errors='strict')
    (dest/name).write_text(text,encoding='utf-8')
manifest={'model':'SenseVoice Small INT8 (sherpa-onnx 2024-07-17 export)','author':'FunAudioLLM / Alibaba Group; ONNX export by sherpa-onnx',
    'model_source':'https://huggingface.co/FunAudioLLM/SenseVoiceSmall',
    'onnx_source':'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2',
    'vad_source':'https://github.com/snakers4/silero-vad','licenses':licenses,'files':files}
(dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'bundled_asr_mib':round(sum(f['bytes'] for f in files.values())/1024**2,1)}))
