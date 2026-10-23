"""Optional Authenticode step for the Windows installer.

This does not create, download, or embed a certificate. With no PFX configured
the installer stays unsigned and the command exits 0. --require fails closed
instead of skipping. A configured PFX that cannot actually be used exits 1
and never reports the file as signed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTALLER = ROOT / 'src-tauri/target/release/bundle/nsis/SliceAI_0.2.0_x64-setup.exe'
TIMESTAMP_URL = 'http://timestamp.digicert.com'


def sign_installer(installer, *, require=False, pfx=None, password=None, signtool=None, dry_run=False, env=None):
    """Return a status dict. Raise ValueError when signing was required or was configured but cannot finish."""
    installer = Path(installer)
    source = env if env is not None else os.environ
    if pfx is None:
        raw = source.get('SLICEAI_SIGN_PFX', '').strip()
        pfx = Path(raw) if raw else None
    password_provided = password is not None or 'SLICEAI_SIGN_PASSWORD' in source
    if password is None:
        password = source.get('SLICEAI_SIGN_PASSWORD', '')
    unsigned = {
        'signed': False,
        'attempted': False,
        'installer': str(installer),
        'smartscreen': '未签名的安装包在其他 Windows 电脑上可能被 SmartScreen 拦截，并显示未知发布者。',
    }
    if pfx is None:
        if require:
            raise ValueError('这次发布要求代码签名，但没有配置证书。设置 SLICEAI_SIGN_PFX 指向已有的 PFX；本脚本不会生成证书。')
        unsigned['reason'] = '未配置证书，安装包保持未签名。'
        return unsigned
    if not pfx.is_file():
        raise ValueError(f'已配置的证书文件不存在，安装包未签名：{pfx}')
    if not dry_run and not installer.is_file():
        raise ValueError(f'找不到要签名的安装包：{installer}')
    tool = signtool or shutil.which('signtool')
    if dry_run:
        return {
            'signed': False,
            'attempted': False,
            'dry_run': True,
            'installer': str(installer),
            'certificate_present': True,
            'password_configured': password_provided,
            'signtool': tool,
            'reason': '仅显示计划，没有签名。',
        }
    if not tool:
        raise ValueError('已配置证书，但找不到 signtool.exe。安装包未签名。请安装 Windows SDK，或把 signtool 加入 PATH。')
    if not password_provided:
        raise ValueError('已配置 PFX，但没有 SLICEAI_SIGN_PASSWORD。为避免 signtool 交互等待，安装包未签名。')
    command = [tool, 'sign', '/fd', 'SHA256', '/td', 'SHA256', '/tr', TIMESTAMP_URL,
               '/f', str(pfx), '/p', password, str(installer)]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or '').strip()
        if password:
            detail = detail.replace(password, '***')
        raise ValueError('signtool 签名失败，安装包未标记为已签名。' + (detail[:500] if detail else ''))
    return {'signed': True, 'attempted': True, 'installer': str(installer), 'signtool': tool,
            'timestamp_url': TIMESTAMP_URL}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, default=DEFAULT_INSTALLER)
    parser.add_argument('--require', action='store_true', help='Fail when no certificate is configured or signing cannot finish.')
    parser.add_argument('--dry-run', action='store_true', help='Show whether a certificate is configured. Do not sign.')
    args = parser.parse_args(argv)
    try:
        result = sign_installer(args.installer, require=args.require, dry_run=args.dry_run)
    except ValueError as exc:
        code = 2 if args.require and '没有配置证书' in str(exc) else 1
        parser.exit(code, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
