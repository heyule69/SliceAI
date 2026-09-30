"""Real streamer laughter regression audition for the accepted BandIt family."""
import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'test-results/v0.2/audio-comparison/笑声';out.mkdir(exist_ok=True)
python=str(root/'.audio-venv/Scripts/python.exe');ffmpeg=str(root/'src-tauri/resources/worker/bin/ffmpeg.exe')
source=next(Path('D:/Download/BaiduNetdisk').glob('2026-08-28*.mp4'))
raw=root/'test-results/v0.2/audio/笑声-原声.wav'
def run(args):subprocess.run(args,check=True,creationflags=0x08000000)
run([ffmpeg,'-v','error','-y','-ss','3025','-i',str(source),'-t','25','-vn','-ac','1','-ar','48000','-c:a','pcm_f32le',str(raw)])
run([ffmpeg,'-v','error','-y','-ss','3036','-i',str(source),'-frames:v','1','-update','1',str(out/'source-frame.jpg')])
for model in ['bandit-plus','bandit-v2']:
    run([python,'-X','utf8',str(root/'scripts/run-audio-comparison.py'),model,'笑声'])
import numpy as np
import soundfile as sf
tracks={'01-原声':sf.read(raw,dtype='float32')[0]}
for model,number,stem in [('bandit-plus','04','effects'),('bandit-v2','05','sfx')]:
    speech,sr=sf.read(out/(model+'-speech.wav'),dtype='float32')
    effects,er=sf.read(out/(model+'-'+stem+'.wav'),dtype='float32')
    assert sr==er==48000 and len(speech)==len(effects)==1200000
    tracks[number+'-'+model]=speech
    tracks[number+'-'+model+'-保留音效']=speech+effects
rows=[]
for name,audio in tracks.items():
    assert len(audio)==1200000 and np.isfinite(audio).all()
    assert np.abs(audio).max()<1,('Peak exceeds PCM range',name)
    wav=out/(name+'.wav');mp3=out/(name+'.mp3')
    sf.write(wav,audio,48000,subtype='PCM_24')
    run([ffmpeg,'-v','error','-y','-i',str(wav),'-c:a','libmp3lame','-b:a','192k',str(mp3)])
    rows.append({'name':name,'duration':25,'samples':len(audio),'peak':float(np.abs(audio).max())})
(out/'report.json').write_text(json.dumps({'source':source.name,'start':3025,'duration':25,'laughter_around':[9.9,14],'tracks':rows,'normalization':'none','variants':'speech only and speech plus effects; both exclude music stem'},ensure_ascii=False,indent=2),encoding='utf-8')
(out.parent/'selection.json').write_text(json.dumps({'accepted_by_user':['BandIt Plus','BandIt v2'],'scope':'User accepted models 04 and 05 after the chat sample audition; use BandIt family for future integration. Laughter audition pending.','previous_model':'MossFormer2_SE_48K','app_integration':'pending'},ensure_ascii=False,indent=2),encoding='utf-8')
print('Laughter audition ready: '+str(out),flush=True)
