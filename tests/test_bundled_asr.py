import contextlib,io,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from storage import Store
from pipeline import model_dir,model_ready
from service import install_model


class BundledAsrTest(unittest.TestCase):
    def test_clean_profile_uses_packaged_model_without_network_or_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'new-profile');bundle=Path(temp)/'worker/models/sensevoice-int8'
            try:
                with patch('pipeline.sys.frozen',True,create=True),patch('pipeline.resource_dir',return_value=bundle.parent.parent),patch('pipeline.model_files_ready',side_effect=lambda p:p==bundle),patch('urllib.request.urlopen',side_effect=AssertionError('Network forbidden')),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(model_dir(store,store.settings()),bundle)
                    self.assertTrue(model_ready(store,store.settings()))
                    self.assertTrue(install_model(store)['ready'])
                self.assertFalse((store.root/'models').exists())
            finally:store.db.close()

    def test_custom_path_is_preserved_and_legacy_is_only_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'profile');bundle=Path(temp)/'worker/models/sensevoice-int8';legacy=store.root/'models/sensevoice-int8'
            try:
                with patch('pipeline.sys.frozen',True,create=True),patch('pipeline.resource_dir',return_value=bundle.parent.parent):
                    with patch('pipeline.model_files_ready',side_effect=lambda p:p in (bundle,legacy)):
                        self.assertEqual(model_dir(store,store.settings()),bundle)
                    with patch('pipeline.model_files_ready',side_effect=lambda p:p==legacy):
                        self.assertEqual(model_dir(store,store.settings()),legacy)
                    custom=Path(temp)/'custom'
                    self.assertEqual(model_dir(store,{'asr_model_dir':str(custom)}),custom.resolve())
                    with patch('pipeline.model_files_ready',return_value=False),patch('urllib.request.urlopen',side_effect=AssertionError('Network forbidden')):
                        with self.assertRaisesRegex(ValueError,'内置转写模型不完整'):install_model(store)
            finally:store.db.close()

if __name__=='__main__':unittest.main()
