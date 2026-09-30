import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from audio_cache import checked_folder, ensure_space, estimate_bytes, record_cache
from storage import Store


class StorageTest(unittest.TestCase):
    @unittest.skipUnless(hasattr(Path,'is_junction'),'Junction-aware pathlib required')
    def test_junction_root_and_parent_are_rejected_before_creation_or_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            owner=Path(td);junction=owner/'tasks'
            source=owner/'speech-keep.wav';source.write_bytes(b'keep')
            store=SimpleNamespace(root=owner)
            editor=SimpleNamespace(store=store,folder=junction/'project',p={})
            original=Path.is_junction
            def fake_junction(path):return path == junction or original(path)
            with patch.object(Path,'is_junction',autospec=True,side_effect=fake_junction):
                with self.assertRaisesRegex(ValueError,'链接'):
                    ensure_space(editor,junction/'project'/'event-audio'/'new',10,limit_bytes=0)
                with self.assertRaisesRegex(ValueError,'链接'):
                    checked_folder(editor,junction)
            self.assertFalse(junction.exists())
            self.assertEqual(source.read_bytes(),b'keep')

    def entry(self, folder, key, identity, size=100):
        path = folder / f'speech-{key}.wav'
        path.write_bytes(b'x' * size)
        record_cache(folder, key, identity, [path])
        return path

    def test_lru_eviction_preserves_referenced_wavs_and_completed_previews(self):
        with tempfile.TemporaryDirectory() as td:
            owner = Path(td)
            folder = owner / 'audio-samples'
            folder.mkdir()
            preview = owner / 'render.mp4'
            preview.write_bytes(b'completed video')
            oldest = self.entry(folder, 'old', {'source': 'old'})
            used = self.entry(folder, 'used', {'source': 'used'})
            active = self.entry(folder, 'active', {'source': 'active'})
            editor = SimpleNamespace(folder=owner, store=None,
                                     p={'audio_sample': {'processed': {'path': str(used)}},
                                        'versions': [{'preview': str(preview)}]})
            status = ensure_space(editor, folder, 20, allocate_bytes=0, limit_bytes=200,
                                  current_identity={'source': 'active'})
            self.assertFalse(oldest.exists())
            self.assertTrue(used.exists())
            self.assertTrue(active.exists())
            self.assertEqual(preview.read_bytes(), b'completed video')
            self.assertEqual(status['removed_bytes'], 100)

    def test_capacity_limit_never_deletes_version_bound_analysis_assets(self):
        with tempfile.TemporaryDirectory() as td:
            owner = Path(td)
            folder = owner / 'event-audio'
            folder.mkdir()
            identity = {'source': str(owner/'video.mp4'), 'size': 1, 'mtime': 2,
                        'start': 0, 'end': 20, 'engine': 'approved', 'audio_track': 0}
            path = self.entry(folder, 'bound', identity)
            editor = SimpleNamespace(folder=owner, store=None,
                                     p={'versions': [{'analysis_audio': {**identity, 'strength': 1}}]})
            status = ensure_space(editor, folder, 20, allocate_bytes=0, limit_bytes=0)
            self.assertTrue(path.is_file())
            self.assertEqual(status['cache_bytes'], 100)

    def test_global_budget_cleans_other_projects_and_protects_saved_references(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'data')
            try:
                store.db.execute('CREATE TABLE edits (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                ids=[str(uuid.uuid4()) for _ in range(3)]
                files=[]
                for i,project_id in enumerate(ids):
                    owner=store.task_dir(project_id);folder=owner/'audio-samples';folder.mkdir()
                    path=self.entry(folder,str(i),{'source':str(i)})
                    payload={'id':project_id,'versions':[]}
                    if i==1:payload['audio_sample']={'processed':{'path':str(path)}}
                    store.db.execute('INSERT INTO edits VALUES (?,?)',(project_id,json.dumps(payload)))
                    files.append(path)
                store.db.commit()
                editor=SimpleNamespace(folder=store.task_dir(ids[2]),store=store,
                                       p={'id':ids[2],'versions':[]})
                result=ensure_space(editor,editor.folder/'audio-samples',10,allocate_bytes=0,
                                    limit_bytes=200,current_identity={'source':'2'})
                self.assertFalse(files[0].exists())
                self.assertTrue(files[1].exists());self.assertTrue(files[2].exists())
                self.assertEqual(result['cache_bytes'],200)
            finally:store.db.close()

    def test_forged_cache_path_cannot_delete_outside_the_owned_tree(self):
        with tempfile.TemporaryDirectory() as td:
            owner = Path(td)
            folder = owner / 'audio-samples'
            folder.mkdir()
            outside = owner / 'speech-do-not-delete.wav'
            outside.write_bytes(b'important')
            (folder/'cache-forged.json').write_text(json.dumps({'files':[str(outside)], 'identity':{}, 'used':0}), encoding='utf-8')
            editor = SimpleNamespace(folder=owner, store=None, p={})
            ensure_space(editor, folder, 20, allocate_bytes=0, limit_bytes=0)
            self.assertEqual(outside.read_bytes(), b'important')

    def test_inference_space_is_estimated_before_allocation_and_mix_is_smaller(self):
        self.assertGreater(estimate_bytes(3600), 3 * 1024 ** 3)
        self.assertLess(estimate_bytes(3600, raw_ready=True, stem_ready=True), 1024 ** 3)
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            editor = SimpleNamespace(folder=folder, store=None, p={})
            with patch('audio_cache.shutil.disk_usage', return_value=SimpleNamespace(free=100)):
                with self.assertRaisesRegex(ValueError, '空间不足'):
                    ensure_space(editor, folder, 3600)
            self.assertGreater(editor.p['audio_storage']['estimated_additional_bytes'], 3 * 1024 ** 3)
            self.assertEqual(list(folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
