"""The signing hook must not invent a certificate or claim an unsigned file is signed."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util

spec = importlib.util.spec_from_file_location('sign_installer', Path(__file__).with_name('sign-installer.py'))
sign_installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign_installer)


class SignInstallerTest(unittest.TestCase):
    def test_missing_certificate_skips_without_creating_one(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / 'SliceAI_0.2.0_x64-setup.exe'
            installer.write_bytes(b'unsigned-installer')
            before = installer.read_bytes()
            result = sign_installer.sign_installer(installer, env={})
            self.assertFalse(result['signed'])
            self.assertIn('SmartScreen', result['smartscreen'])
            self.assertEqual(installer.read_bytes(), before)
            self.assertEqual(list(Path(temp).iterdir()), [installer])

    def test_require_fails_when_no_certificate_is_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / 'setup.exe'
            installer.write_bytes(b'unsigned-installer')
            with self.assertRaisesRegex(ValueError, '不会生成证书'):
                sign_installer.sign_installer(installer, require=True, env={})
            self.assertEqual(installer.read_bytes(), b'unsigned-installer')

    def test_configured_but_missing_pfx_does_not_report_signed(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / 'setup.exe'
            installer.write_bytes(b'unsigned-installer')
            missing = Path(temp) / 'missing.pfx'
            with self.assertRaisesRegex(ValueError, '不存在'):
                sign_installer.sign_installer(installer, pfx=missing, password='secret', env={})
            self.assertEqual(installer.read_bytes(), b'unsigned-installer')

    def test_signtool_missing_leaves_the_installer_unsigned(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / 'setup.exe'
            installer.write_bytes(b'unsigned-installer')
            pfx = Path(temp) / 'publisher.pfx'
            pfx.write_bytes(b'not-a-real-certificate')
            with patch.object(sign_installer.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(ValueError, 'signtool'):
                    sign_installer.sign_installer(installer, pfx=pfx, password='secret', env={})
            self.assertEqual(installer.read_bytes(), b'unsigned-installer')

    def test_successful_signtool_invocation_redacts_the_password(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / 'setup.exe'
            installer.write_bytes(b'unsigned-installer')
            pfx = Path(temp) / 'publisher.pfx'
            pfx.write_bytes(b'pfx-bytes')

            def fake_run(command, capture_output, text):
                self.assertNotIn('shell', command)
                self.assertIn(str(pfx), command)
                self.assertIn('s3cret-value', command)
                return subprocess.CompletedProcess(command, 1, stdout='', stderr='bad password s3cret-value')

            with patch.object(sign_installer.subprocess, 'run', side_effect=fake_run):
                with self.assertRaisesRegex(ValueError, r'\*\*\*') as caught:
                    sign_installer.sign_installer(installer, pfx=pfx, password='s3cret-value', signtool='signtool')
            self.assertNotIn('s3cret-value', str(caught.exception))
            self.assertEqual(installer.read_bytes(), b'unsigned-installer')

            def ok_run(command, capture_output, text):
                return subprocess.CompletedProcess(command, 0, stdout='Done', stderr='')

            with patch.object(sign_installer.subprocess, 'run', side_effect=ok_run):
                result = sign_installer.sign_installer(installer, pfx=pfx, password='s3cret-value', signtool='signtool')
            self.assertTrue(result['signed'])
            self.assertNotIn('s3cret-value', json.dumps(result))

    def test_cli_without_certificate_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / 'setup.exe'
            installer.write_bytes(b'unsigned-installer')
            with patch.dict(os.environ, {}, clear=True):
                result = sign_installer.main(['--installer', str(installer)])
            self.assertFalse(result['signed'])


if __name__ == '__main__':
    unittest.main()
