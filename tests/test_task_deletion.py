import contextlib, io, json, tempfile, unittest, uuid, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from storage import Store
import fine
from task_deletion import delete_task


class DeletionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'data')
        self.source = self.root / '原录播.mp4'; self.source.write_bytes(b'original')
        self.subtitle = self.root / '导入.srt'; self.subtitle.write_text('原文', encoding='utf-8')
        self.task = {'id':str(uuid.uuid4()), 'created':'2026-09-29', 'status':'complete',
            'video':str(self.source),'subtitle':str(self.subtitle),'chat':'','title':'录播',
            'clips':[{'id':1,'start':2,'end':8,'title':'事件'}], 'exports':[]}
        self.export = self.root / '共用导出目录' / '成片.mp4'
        self.export.parent.mkdir(); self.export.write_bytes(b'export')
        self.other = self.export.parent / '其他文件.mp4'; self.other.write_bytes(b'keep')
        self.task['exports']=[{'path':str(self.export), 'subtitle':''}]
        self.store.put(self.task)
        self.project = fine.create(self.store,self.task['id'],1)
        self.cache = self.store.task_dir(self.task['id']) / 'transcript.json'
        self.cache.write_text('[]',encoding='utf-8')
        self.preview = self.store.task_dir(self.project['id']) / 'preview.mp4'
        self.preview.write_bytes(b'preview')

    def tearDown(self):
        self.store.db.close(); self.tmp.cleanup()

    def test_records_only_keeps_all_files(self):
        delete_task(self.store,self.task['id'])
        self.assertEqual(self.store.tasks(),[]);self.assertEqual(fine.summaries(self.store),[])
        for p in (self.source,self.subtitle,self.export,self.other,self.preview,self.cache):self.assertTrue(p.is_file())

    def test_delete_generated_files_preserves_inputs_and_neighbors(self):
        # Even a mistakenly recorded imported source cannot become a deletion target.
        self.task['exports'] += [{'path':str(self.source),'subtitle':str(self.subtitle)}]
        self.store.put(self.task)
        delete_task(self.store,self.task['id'],True)
        for p in (self.source,self.subtitle,self.other):self.assertTrue(p.is_file())
        for p in (self.export,self.preview,self.cache):self.assertFalse(p.exists())
        self.assertTrue(self.export.parent.is_dir())

    def test_shared_files_preserved(self):
        another={**self.task,'id':str(uuid.uuid4())};self.store.put(another)
        delete_task(self.store,self.task['id'],True)
        self.assertTrue(self.export.is_file());self.assertEqual(len(self.store.tasks()),1)

    def test_active_task_or_edit_cannot_be_deleted(self):
        self.task['status']='transcribing';self.store.put(self.task)
        with self.assertRaisesRegex(ValueError,'正在处理'):delete_task(self.store,self.task['id'],True)
        self.task['status']='complete';self.store.put(self.task)
        self.project['status']='queued'
        with contextlib.redirect_stdout(io.StringIO()):fine.save(self.store,self.project)
        with self.assertRaisesRegex(ValueError,'正在处理'):delete_task(self.store,self.task['id'],True)
        self.assertTrue(self.preview.exists())

    def test_failure_preserves_records_for_retry(self):
        from unittest.mock import patch
        with patch.object(Path,'unlink',side_effect=PermissionError('in use')):
            with self.assertRaisesRegex(ValueError,'记录已保留'):delete_task(self.store,self.task['id'],True)
        self.assertEqual(len(self.store.tasks()),1);self.assertEqual(len(fine.summaries(self.store)),1)
        delete_task(self.store,self.task['id'],True)

    def test_imported_file_inside_cache_still_protected(self):
        self.task['subtitle']=str(self.cache);self.store.put(self.task)
        delete_task(self.store,self.task['id'],True)
        self.assertTrue(self.cache.exists())


if __name__=='__main__':unittest.main()
