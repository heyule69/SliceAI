"""Exercise real packaged inference cancellation through the desktop audio wrapper."""
import json,subprocess,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from engine import Cancelled
from audio_processing import process_audio
audio=ROOT/'src-tauri/resources/worker/audio'
with tempfile.TemporaryDirectory() as temp:
    store=SimpleNamespace(root=Path(temp)/'data',task_dir=lambda task_id:Path(temp)/'data'/task_id)
    folder=Path(temp)/'renders';folder.mkdir()
    triggered=[]
    def cancel_after_progress(stage):
        triggered.append(stage);raise Cancelled('test cancellation')
    editor=SimpleNamespace(settings={'ffmpeg_path':str(ROOT/'src-tauri/resources/worker/bin/ffmpeg.exe')},
        store=store,p={'id':'cancel-audio'},persist=cancel_after_progress)
    started=time.monotonic()
    try:
        with patch('audio_processing.locations',return_value=([str(audio/'sliceai-audio.exe')],audio/'model')):
            process_audio(editor,ROOT/'test-results/v0.2/audio/笑声-原声.wav',folder,1,0,20)
        raise AssertionError('Did not cancel')
    except Cancelled:pass
    assert triggered and list(folder.glob('original-*.wav'))
    assert not list(folder.glob('processed-*.wav'))
    assert not list(folder.glob('*.partial.wav'))
    state=subprocess.run([str(ROOT/'src-tauri/resources/worker/sliceai-worker.exe')],
        input=json.dumps({'cmd':'state','_data_dir':str(Path(temp)/'smoke-data')}).encode('utf-8'),
        capture_output=True,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    result=json.loads(state.stdout.decode('utf-8'))
    assert 'result' in result and result['result']['tools']['ffmpeg']
    report={'cancelled_after_inference_started':True,'elapsed_seconds':round(time.monotonic()-started,2),
        'raw_cache_preserved':True,'partial_and_final_processed_absent':True,'bundled_service_state':True}
(ROOT/'test-results/v0.2/audio-comparison/cancellation-regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
