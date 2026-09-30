"""Collect a local portable build and installer after `npm run bundle`."""
import hashlib
import json
import shutil
from pathlib import Path

root=Path(__file__).resolve().parents[1]
build=root/'src-tauri/target/release'
release=root/'release';portable=release/'SliceAI-0.2.0'
portable.mkdir(parents=True,exist_ok=True)
shutil.copy2(build/'sliceai.exe',portable/'SliceAI.exe')
shutil.copytree(build/'worker',portable/'worker',dirs_exist_ok=True)
shutil.copy2(root/'README.md',release/'README.md')
installer=build/'bundle/nsis/SliceAI_0.2.0_x64-setup.exe'
shutil.copy2(installer,release/installer.name)
files=[release/installer.name,portable/'SliceAI.exe']
checksums={str(p.relative_to(release)):hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in files}
(release/'SHA256.json').write_text(json.dumps(checksums,indent=2),encoding='utf-8')
print(json.dumps({'installer':str(release/installer.name),'portable':str(portable/'SliceAI.exe'),
                  'installer_mb':round(installer.stat().st_size/1024**2,2)},ensure_ascii=False))
