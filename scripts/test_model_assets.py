"""Small fixtures test the downloader without downloading model weights."""
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import model_assets as assets


class ModelAssetsTest(unittest.TestCase):
    def info(self, data, **values):
        return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), **values}

    def catalog(self, data=b'weights'):
        return {'manifest': {'model': 'test model', 'version': 'pinned'},
                'files': {'model.onnx': self.info(data, source='https://example.com/pinned') }}

    def test_dry_run_has_no_io_or_profile_dependency(self):
        with patch('model_assets.urllib.request.urlopen', side_effect=AssertionError('network')):
            result = assets.prepare(self.catalog(), Path('missing-assets'), fetch=True, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertFalse(Path('missing-assets').exists())

    def test_download_is_verified_and_published(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'assets'
            with patch('model_assets.urllib.request.urlopen', return_value=io.BytesIO(b'weights')):
                result = assets.prepare(self.catalog(), destination, fetch=True)
            self.assertTrue(result['verified'])
            self.assertEqual((destination / 'model.onnx').read_bytes(), b'weights')
            assets.verify(self.catalog(), destination)

    def test_wrong_hash_never_replaces_previous_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            (destination / 'model.onnx').write_bytes(b'previous')
            with patch('model_assets.urllib.request.urlopen', return_value=io.BytesIO(b'invalid')):
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    assets.prepare(self.catalog(), destination, fetch=True)
            self.assertEqual((destination / 'model.onnx').read_bytes(), b'previous')

    def test_oversized_download_cleans_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'asset'
            with patch('model_assets.urllib.request.urlopen', return_value=io.BytesIO(b'too long')):
                with self.assertRaisesRegex(ValueError, 'size limit'):
                    assets.download('https://example.com/pinned', target, 2)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.partial').exists())

    def test_offline_import_never_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            source, destination = Path(temp) / 'source', Path(temp) / 'destination'
            source.mkdir(); (source / 'model.onnx').write_bytes(b'weights')
            with patch('model_assets.urllib.request.urlopen', side_effect=AssertionError('network')):
                assets.prepare(self.catalog(), destination, source_dir=source)
            assets.verify(self.catalog(), destination)

    def test_archive_links_and_unsafe_names_are_rejected(self):
        with self.assertRaises(ValueError):
            assets.filename('../outside')
        with tempfile.TemporaryDirectory() as temp:
            archive, output = Path(temp) / 'archive.tar', Path(temp) / 'output'
            with tarfile.open(archive, 'w') as tar:
                member = tarfile.TarInfo('model.onnx'); member.type = tarfile.SYMTYPE; member.linkname = '../outside'
                tar.addfile(member)
            with self.assertRaisesRegex(ValueError, 'archive member'):
                assets.extract_member(archive, 'model.onnx', output, self.info(b'weights'))
            self.assertFalse(output.exists())

    def test_builtin_config_reproduces_pinned_bytes(self):
        catalog = assets.read_json(assets.CATALOG / 'bandit-plus.json')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'config.json'
            assets.builtin(catalog['files']['config.json'], target)
            self.assertEqual(assets.checksum(target), catalog['manifest']['config_sha256'])


if __name__ == '__main__':
    unittest.main()
