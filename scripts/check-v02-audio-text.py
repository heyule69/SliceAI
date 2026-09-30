import json,os,re,subprocess
from pathlib import Path
from difflib import SequenceMatcher
import numpy as np
import sherpa_onnx
root=Path(__file__).resolve().parents[1];folder=root/'test-results/v0.2/audio'
model=Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop/models/sensevoice-int8'
rec=sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(model/'model.int8.onnx'),tokens=str(model/'tokens.txt'),num_threads=2,use_itn=True,language='auto',provider='cpu')
ffmpeg=root/'src-tauri/resources/worker/bin/ffmpeg.exe';rows=[]
for original in folder.glob('*-原声.wav'):
    texts=[];rms=[]
    for path in (original,original.with_name(original.name.replace('-原声','-处理'))):
        raw=subprocess.check_output([str(ffmpeg),'-v','error','-i',str(path),'-f','f32le','-ar','16000','-ac','1','pipe:1'],creationflags=0x08000000)
        samples=np.frombuffer(raw,dtype=np.float32);stream=rec.create_stream();stream.accept_waveform(16000,samples);rec.decode_stream(stream)
        texts.append(re.sub(r'<\|[^>]+\|>','',stream.result.text));rms.append(float(np.sqrt(np.mean(samples**2))))
    row={'sample':original.stem,'original_text':texts[0],'processed_text':texts[1],
         'asr_text_similarity':round(SequenceMatcher(None,*texts).ratio(),3),
         'total_audio_rms_change_db':round(20*np.log10(max(rms[1],1e-9)/max(rms[0],1e-9)),2),
         'note':'ASR相似度和总能量不是主观音质或单独背景音乐抑制率，不替代试听。'}
    rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
(folder/'text-comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
