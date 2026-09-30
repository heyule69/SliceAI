"""Bundle an offline CPU audio worker, isolated from ASR dependencies."""
import json,shutil,subprocess,sys,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','sliceai-audio',
      '--distpath',str(root/'build/audio-dist'),'--workpath',str(root/'build/audio-pyinstaller'),
      '--specpath',str(root/'build')]
for name in ('clearvoice','librosa','numba','pytorch_lightning','torchmetrics','cv2','torchvision','matplotlib','pandas','sklearn','IPython','tensorboard','triton','pytest','tensorflow'):
    args+=['--exclude-module',name]
args+=[str(root/'backend/audio_worker.py')]
if '--stage-only' not in sys.argv:subprocess.run(args,cwd=root,check=True)
destination=root/'src-tauri/resources/worker/audio'
if destination.exists():
    if not destination.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe bundle destination')
    backup=root/'build'/('audio-previous-'+uuid.uuid4().hex[:8])
    try:destination.rename(backup)
    except PermissionError:
        # A dev file watcher may hold the directory open on Windows. Preserve a
        # full backup, then replace files individually without stale old weights.
        shutil.copytree(destination,backup)
        for path in destination.rglob('*'):
            if path.is_file():
                if not path.resolve().is_relative_to(destination.resolve()):raise ValueError('Unsafe bundle file')
                path.unlink()
shutil.copytree(root/'build/audio-dist/sliceai-audio',destination,dirs_exist_ok=True)
model=root/'audio-model/BandItPlus';target=destination/'model';target.mkdir(exist_ok=True)
manifest=json.loads((model/'manifest.json').read_text(encoding='utf-8'))
for name in ('manifest.json',manifest['config'],manifest['file']):
    if (model/name).is_file():shutil.copy2(model/name,target/name)
(destination/'THIRD-PARTY-NOTICES.txt').write_text(
    'BandIt Plus: BandIt (Apache-2.0) / MSST implementation (MIT).\n'
    'https://github.com/ZFTurbo/Music-Source-Separation-Training\n'
    'See licenses/ for source attribution, modifications and full license texts.\n'
    'Model source and SHA256: model/manifest.json\n'
    'PyTorch 2.6.0 CPU / torchaudio 2.6.0: BSD-style licenses, https://pytorch.org/\n'
    'NumPy, SciPy, spafe, SoundFile and their dependencies retain upstream licenses in _internal.\n'
    'This worker loads only local verified weights and runs on CPU. No model download occurs at runtime.\n',encoding='utf-8')
licenses=destination/'licenses';licenses.mkdir(exist_ok=True)
for name in ('LICENSE-MIT.txt','LICENSE-Apache-2.0.txt','NOTICE.txt'):
    shutil.copy2(root/'backend/bandit'/name,licenses/name)
print(destination)
