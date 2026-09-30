"""Build a self-contained, on-demand worker without a resident Python server."""
import shutil
import subprocess
import sys
from pathlib import Path
from model_assets import CATALOG, read_json, verify

ROOT=Path(__file__).resolve().parents[1]
def main():
    model=ROOT/'asr-model/SenseVoice'
    verify(read_json(CATALOG/'sensevoice.json'), model)
    for name in ('ffmpeg','ffprobe'):
        if not shutil.which(name):raise SystemExit(f'{name} must be available in PATH before packaging.')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir',
        '--name','sliceai-worker','--distpath',str(ROOT/'build/worker-dist'),
        '--workpath',str(ROOT/'build/pyinstaller'),'--specpath',str(ROOT/'build'),
        '--collect-all','sherpa_onnx','--collect-all','sherpa_onnx_core',
        str(ROOT/'backend/service.py')],cwd=ROOT,check=True)
    destination=ROOT/'src-tauri/resources/worker'
    shutil.copytree(ROOT/'build/worker-dist/sliceai-worker',destination,dirs_exist_ok=True)
    shutil.copytree(model,destination/'models/sensevoice-int8',dirs_exist_ok=True)
    binaries=destination/'bin';binaries.mkdir(parents=True,exist_ok=True)
    for name in ('ffmpeg','ffprobe'):
        source=shutil.which(name)
        if not source:raise SystemExit(f'{name} must be available in PATH before packaging.')
        target=binaries/(name+'.exe')
        if Path(source).resolve()!=target.resolve():shutil.copy2(source,target)
        for path in (Path(source).parent.parent/'LICENSE',Path(source).parent.parent/'LICENSE.txt'):
            if path.is_file():shutil.copy2(path,binaries/'FFmpeg-LICENSE.txt');break
    (destination/'THIRD-PARTY-NOTICES.txt').write_text(
        'SliceAI third-party components\n\n'
        'FFmpeg / FFprobe: GPL v3 build from https://www.gyan.dev/ffmpeg/builds/\n'
        'Upstream source: https://ffmpeg.org/download.html\n'
        'Exact installed build configuration: bin/ffmpeg.exe -buildconf\n'
        'FFmpeg is run as a separate executable. See bin/FFmpeg-LICENSE.txt.\n\n'
        'sherpa-onnx: Apache-2.0, https://github.com/k2-fsa/sherpa-onnx\n'
        'NumPy: BSD-3-Clause, https://numpy.org/\n'
        'Python: PSF License, https://www.python.org/\n'
        'ONNX Runtime: MIT, https://github.com/microsoft/onnxruntime\n'
        'PyInstaller: GPL with bootloader exception, https://pyinstaller.org/\n'
        'SenseVoice Small INT8: bundled for offline use; FunAudioLLM / Alibaba Group, ONNX export by sherpa-onnx.\n'
        'Model license, Silero VAD license, source URLs and hashes: models/sensevoice-int8/.\n',encoding='utf-8')
    print(f'Worker ready: {destination}')

if __name__=='__main__':main()
