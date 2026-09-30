"""Pinned build-time assets. No user-profile access or runtime downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(__file__).resolve().parent / 'model-assets'


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8', errors='strict'))
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path} is not UTF-8; no file was converted.') from exc


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def filename(name):
    if not isinstance(name, str) or not name or Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError(f'Unsafe asset filename: {name!r}')
    return name


def checked(path, info):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != info['bytes']:
        raise ValueError(f'Missing or wrong-sized asset: {path}')
    if checksum(path) != info['sha256']:
        raise ValueError(f'Asset checksum mismatch: {path}')
    return path


def download(url, target, maximum):
    if not url.startswith('https://'):
        raise ValueError('Model sources must use HTTPS.')
    target = Path(target)
    temporary = target.with_suffix(target.suffix + '.partial')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'SliceAI-model-assets/1'})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open('wb') as stream:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > maximum:
                    raise ValueError(f'Download exceeded the pinned size limit: {url}')
                stream.write(block)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def extract_member(archive, member_name, target, info):
    # Never extract arbitrary paths, directories, links or an upstream source tree.
    with tarfile.open(archive, 'r:*') as bundle:
        try:
            member = bundle.getmember(member_name)
        except KeyError as exc:
            raise ValueError(f'Missing pinned archive member: {member_name}') from exc
        if not member.isfile() or member.size != info['bytes']:
            raise ValueError(f'Unexpected archive member: {member_name}')
        with bundle.extractfile(member) as stream, Path(target).open('wb') as output:
            shutil.copyfileobj(stream, output, 1024 * 1024)
    checked(target, info)


def builtin(info, target):
    # Git may convert checkout newlines. Reproduce accepted BandIt config bytes.
    source = CATALOG / filename(info['builtin'])
    try:
        text = source.read_text(encoding='utf-8', errors='strict')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{source} is not UTF-8; no file was converted.') from exc
    if text.startswith('\ufeff'):
        raise ValueError(f'{source} contains a BOM; expected UTF-8 without BOM.')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if info.get('newline') == 'crlf':
        text = text.replace('\n', '\r\n')
    Path(target).write_bytes(text.encode('utf-8'))
    checked(target, info)


def verify(catalog, destination):
    destination = Path(destination).resolve()
    for name, info in catalog['files'].items():
        checked(destination / filename(name), info)
    manifest = read_json(destination / 'manifest.json')
    for key, value in catalog['manifest'].items():
        if manifest.get(key) != value:
            raise ValueError(f'Asset manifest differs from the pinned version: {key}')
    return catalog['manifest']


def prepare(catalog, destination, source_dir=None, fetch=False, verify_only=False, dry_run=False):
    destination = Path(destination).resolve()
    source_dir = Path(source_dir).resolve() if source_dir else None
    if verify_only and (source_dir or fetch):
        raise ValueError('--verify-only cannot be combined with asset preparation.')
    plan = {'model': catalog['manifest']['model'], 'destination': str(destination),
            'files': [{'name': name, 'bytes': info['bytes'], 'sha256': info['sha256'],
                       'source': str(source_dir / name) if source_dir and 'builtin' not in info
                       else info.get('source', catalog.get('archive', {}).get('url', 'bundled text asset'))}
                      for name, info in catalog['files'].items()],
            'downloads_requested': fetch, 'dry_run': dry_run}
    if dry_run:
        return plan
    if verify_only or not (source_dir or fetch):
        try:
            verify(catalog, destination)
        except (OSError, ValueError) as exc:
            raise ValueError(f'{exc}\nPrepare with --download, or explicitly supply --source-dir for offline import.') from exc
        return {**plan, 'verified': True}
    stage_parent = ROOT / 'build' / 'model-staging'
    stage_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='assets-', dir=stage_parent) as temporary:
        stage = Path(temporary).resolve()
        if not stage.is_relative_to(stage_parent.resolve()):
            raise ValueError('Unsafe asset staging directory.')
        archive = None
        for name, info in catalog['files'].items():
            filename(name)
            target = stage / name
            if 'builtin' in info:
                builtin(info, target)
            elif source_dir:
                source = checked(source_dir / name, info)
                shutil.copyfile(source, target)
            elif 'member' in info:
                if archive is None:
                    archive = stage / 'model.tar.bz2'
                    download(catalog['archive']['url'], archive, catalog['archive']['max_bytes'])
                extract_member(archive, info['member'], target, info)
            else:
                download(info['source'], target, info['bytes'])
                checked(target, info)
        destination.mkdir(parents=True, exist_ok=True)
        for name in catalog['files']:
            target = destination / name
            temporary_target = target.with_suffix(target.suffix + '.partial')
            try:
                shutil.copyfile(stage / name, temporary_target)
                temporary_target.replace(target)
            finally:
                temporary_target.unlink(missing_ok=True)
        manifest_path = destination / 'manifest.json'
        temporary_manifest = manifest_path.with_suffix('.partial')
        try:
            temporary_manifest.write_text(json.dumps(catalog['manifest'], ensure_ascii=False, indent=2) + '\n',
                                          encoding='utf-8', newline='\n')
            temporary_manifest.replace(manifest_path)
        finally:
            temporary_manifest.unlink(missing_ok=True)
    verify(catalog, destination)
    return {**plan, 'verified': True}


def main(kind, argv=None):
    catalog = read_json(CATALOG / (kind + '.json'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('legacy_source', nargs='?', help='Explicit offline asset directory (compatibility).')
    parser.add_argument('--source-dir', type=Path, help='Import exact pinned weights from this directory; no network.')
    parser.add_argument('--destination', type=Path, default=ROOT / catalog['destination'])
    parser.add_argument('--download', action='store_true', help='Fetch pinned upstream assets now (large download).')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Print the plan without reading weights or writing files.')
    args = parser.parse_args(argv)
    if args.legacy_source and args.source_dir:
        parser.error('Supply only one offline source directory.')
    if args.download and (args.legacy_source or args.source_dir):
        parser.error('Choose public download or offline import, not both.')
    try:
        result = prepare(catalog, args.destination, args.source_dir or args.legacy_source,
                         args.download, args.verify_only, args.dry_run)
    except (OSError, ValueError, tarfile.TarError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit('Use prepare-asr-model.py or prepare-audio-model.py.')
