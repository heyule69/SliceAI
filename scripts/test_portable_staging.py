"""Protect the installer and existing runtime while staging test builds."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('stage_portable_test', Path(__file__).with_name('stage-portable.py'))
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)
COMPONENTS = {'asr': True, 'audio': True, 'alignment': True}


class PortableStagingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.executable = self.root / 'src-tauri/target/release/sliceai.exe'
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b'current-test-client')
        self.source = self.root / 'src-tauri/resources/worker'
        self.source.mkdir(parents=True)
        (self.source / 'sliceai-worker.exe').write_bytes(b'current-worker')
        self.target = self.executable.parent / 'worker'
        self.target.mkdir()
        (self.target / 'old-runtime.dll').write_bytes(b'previous-runtime')
        self.installer = self.root / 'release/SliceAI_0.2.0_x64-setup.exe'
        self.installer.parent.mkdir()
        self.installer.write_bytes(b'approved-installer')
        self.manifest = self.installer.with_name('SHA256.json')
        self.original_manifest = json.dumps({self.installer.name: hashlib.sha256(self.installer.read_bytes()).hexdigest()}) + '\n'
        self.manifest.write_text(self.original_manifest, encoding='utf-8')

    def assert_installer_unchanged(self):
        self.assertEqual(self.installer.read_bytes(), b'approved-installer')
        self.assertEqual(self.manifest.read_text(encoding='utf-8'), self.original_manifest)

    def test_staging_without_bundled_installer_replaces_stale_runtime_and_keeps_release(self):
        # No target/release/bundle installer exists in this fixture.
        with patch.object(portable.release, 'verify_workers', return_value=COMPONENTS):
            result = portable.stage(self.root)
        self.assertEqual(Path(result['test_client']), self.executable.resolve())
        self.assertEqual((self.target / 'sliceai-worker.exe').read_bytes(), b'current-worker')
        self.assertFalse((self.target / 'old-runtime.dll').exists())
        self.assertEqual((Path(result['previous_worker']) / 'old-runtime.dll').read_bytes(), b'previous-runtime')
        self.assert_installer_unchanged()

    def test_rejected_copied_runtime_keeps_existing_test_client_and_installer(self):
        with patch.object(portable.release, 'verify_workers', side_effect=[COMPONENTS, ValueError('checksum mismatch')]):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                portable.stage(self.root)
        self.assertEqual((self.target / 'old-runtime.dll').read_bytes(), b'previous-runtime')
        self.assertFalse((self.target / 'sliceai-worker.exe').exists())
        self.assert_installer_unchanged()


if __name__ == '__main__':
    unittest.main()
