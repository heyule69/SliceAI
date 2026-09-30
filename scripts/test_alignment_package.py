"""Tiny offline fixtures cover bundle integrity before any release replacement."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('build_alignment_test', 'build-alignment.py')
release = load('package_release_test', 'package-release.py')


class AlignmentPackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalog = self.model_catalog('qwen3-forced-aligner-cpu-v1', 'model.safetensors')

    def model_catalog(self, engine, filename):
        data = b'fixture-weights'
        info = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        manifest = {'engine': engine, 'model': 'fixture-model', 'revision': 'pinned-fixture', 'files': {filename: info}}
        return {'destination': 'alignment-model/fixture', 'manifest': manifest, 'files': {filename: info}}

    def model(self, folder, catalog):
        folder.mkdir(parents=True)
        for name in catalog['files']:
            (folder / name).write_bytes(b'fixture-weights')
        (folder / 'manifest.json').write_text(json.dumps(catalog['manifest']) + '\n', encoding='utf-8')

    def bundle(self, folder):
        self.model(folder / 'model', self.catalog)
        (folder / 'sliceai-alignment.exe').write_bytes(b'fixture-executable')
        (folder / 'THIRD-PARTY-NOTICES.txt').write_text('Fixture notices\n', encoding='utf-8')
        (folder / 'licenses').mkdir()
        for name in ('licenses/LICENSE-Apache-2.0.txt', 'model/LICENSE-Apache-2.0.txt'):
            (folder / name).write_text('Apache License\nVersion 2.0\n', encoding='utf-8')
        for name in ('qwen_asr/inference/assets/korean_dict_jieba.dict', 'qwen_asr-0.0.6.dist-info/METADATA',
                     'transformers-4.57.6.dist-info/METADATA', 'safetensors-0.8.0.dist-info/METADATA', 'torch-2.6.0+cpu.dist-info/METADATA'):
            path = folder / '_internal' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Fixture asset\n', encoding='utf-8')
        builder.write_bundle_manifest(folder, self.catalog, builder.RUNTIME)
        return folder

    def test_missing_frozen_worker_reports_not_built(self):
        with self.assertRaisesRegex(ValueError, 'has not been built'):
            builder.verify_bundle(self.root / 'missing', self.catalog)

    def test_complete_bundle_is_verified_without_network(self):
        folder = self.bundle(self.root / 'alignment')
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            self.assertTrue(builder.verify_bundle(folder, self.catalog)['verified'])

    def test_weight_corruption_and_missing_license_are_rejected(self):
        folder = self.bundle(self.root / 'alignment')
        (folder / 'model/model.safetensors').write_bytes(b'corrupt-weights')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            builder.verify_bundle(folder, self.catalog)
        (folder / 'model/model.safetensors').write_bytes(b'fixture-weights')
        (folder / 'licenses/LICENSE-Apache-2.0.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'missing.*LICENSE'):
            builder.verify_bundle(folder, self.catalog)

    def test_runtime_damage_stale_files_and_wrong_runtime_are_rejected(self):
        folder = self.bundle(self.root / 'alignment')
        (folder / 'sliceai-alignment.exe').write_bytes(b'changed-executable')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            builder.verify_bundle(folder, self.catalog)
        (folder / 'sliceai-alignment.exe').write_bytes(b'fixture-executable')
        (folder / 'stale-model.bin').write_bytes(b'old')
        with self.assertRaisesRegex(ValueError, 'unlisted'):
            builder.verify_bundle(folder, self.catalog)
        (folder / 'stale-model.bin').unlink()
        manifest = json.loads((folder / 'bundle-manifest.json').read_text(encoding='utf-8'))
        manifest['runtime']['torch'] = '2.6.0+cu124'
        (folder / 'bundle-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'pinned CPU'):
            builder.verify_bundle(folder, self.catalog)

    def test_non_utf8_license_is_reported_without_conversion(self):
        folder = self.bundle(self.root / 'alignment')
        license_path = folder / 'licenses/LICENSE-Apache-2.0.txt'
        original = b'\xff\xfeLicense'
        license_path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'not UTF-8; no file was converted'):
            builder.verify_bundle(folder, self.catalog)
        self.assertEqual(license_path.read_bytes(), original)

    def test_bundle_paths_cannot_escape_the_worker(self):
        for name in ('../outside', '/outside', 'model\\outside', 'C:\\outside'):
            with self.assertRaises(ValueError):
                builder.bundle_path(self.root, name)

    def source_build(self):
        build = self.root / 'src-tauri/target/release'
        worker = build / 'worker'
        for name in ('sliceai-worker.exe', 'bin/ffmpeg.exe', 'bin/ffprobe.exe', 'THIRD-PARTY-NOTICES.txt'):
            path = worker / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        (build / 'sliceai.exe').write_bytes(b'fixture-app')
        installer = build / 'bundle/nsis/SliceAI_0.2.0_x64-setup.exe'
        installer.parent.mkdir(parents=True)
        installer.write_bytes(b'fixture-installer')
        (self.root / 'README.md').write_text('Fixture\n', encoding='utf-8')
        old = self.root / 'release/previous.txt'
        old.parent.mkdir()
        old.write_text('Keep previous release\n', encoding='utf-8')
        return worker, old

    def test_release_requires_alignment_without_modifying_previous_release(self):
        worker, old = self.source_build()
        with patch.object(release, 'verify'):
            self.assertFalse(release.verify_workers(worker)['alignment'])
            with self.assertRaisesRegex(ValueError, 'Alignment worker has not been built'):
                release.package(self.root, require_alignment=True)
        self.assertEqual(old.read_text(encoding='utf-8'), 'Keep previous release\n')
        self.assertFalse((self.root / 'build/release-staging').exists())

    def test_release_copies_model_manifest_licenses_and_runtime_checksums(self):
        worker, old = self.source_build()
        self.bundle(worker / 'alignment')
        catalog_file = self.root / 'alignment-catalog.json'
        catalog_file.write_text(json.dumps(self.catalog), encoding='utf-8')
        with patch.object(release, 'verify'), patch.object(release, 'alignment_builder', return_value=builder), patch.object(builder, 'CATALOG_FILE', catalog_file):
            result = release.package(self.root, require_alignment=True)
        self.assertTrue(result['components']['alignment'])
        self.assertFalse(old.exists())
        self.assertEqual((Path(result['previous_release']) / 'previous.txt').read_text(encoding='utf-8'), 'Keep previous release\n')
        checksums = json.loads((self.root / 'release/SHA256.json').read_text(encoding='utf-8'))
        prefix = 'SliceAI-0.2.0/worker/alignment/'
        for name in ('model/manifest.json', 'model/model.safetensors', 'model/LICENSE-Apache-2.0.txt', 'sliceai-alignment.exe'):
            self.assertIn(prefix + name, checksums)
            self.assertEqual(checksums[prefix + name], hashlib.sha256((self.root / 'release' / (prefix + name)).read_bytes()).hexdigest())

    def test_damaged_copy_never_replaces_previous_release(self):
        worker, old = self.source_build()
        self.bundle(worker / 'alignment')
        catalog_file = self.root / 'alignment-catalog.json'
        catalog_file.write_text(json.dumps(self.catalog), encoding='utf-8')
        original_copytree = release.shutil.copytree
        def damaged_copy(source, destination, *args, **kwargs):
            result = original_copytree(source, destination, *args, **kwargs)
            if Path(destination).name == 'worker':
                (Path(destination) / 'alignment/model/model.safetensors').write_bytes(b'corrupt-weights')
            return result
        with patch.object(release, 'verify'), patch.object(release, 'alignment_builder', return_value=builder), patch.object(builder, 'CATALOG_FILE', catalog_file), patch.object(release.shutil, 'copytree', side_effect=damaged_copy):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                release.package(self.root, require_alignment=True)
        self.assertEqual(old.read_text(encoding='utf-8'), 'Keep previous release\n')


if __name__ == '__main__':
    unittest.main()
