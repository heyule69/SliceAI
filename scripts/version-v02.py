from pathlib import Path
import json
root=Path(__file__).resolve().parents[1]
for name in ('package.json','package-lock.json','src-tauri/tauri.conf.json','src-tauri/Cargo.toml','scripts/package-release.py'):
    p=root/name;s=p.read_text(encoding='utf-8');s=s.replace('0.1.2','0.2.0');p.write_text(s,encoding='utf-8')
p=root/'src/fine.ts';s=p.read_text(encoding='utf-8').replace('v?.audio_strength||.6','v?.audio_strength||1');p.write_text(s,encoding='utf-8')
