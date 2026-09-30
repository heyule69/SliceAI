import contextlib
import copy
import hashlib
import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import test_fine
from engine import Cancelled, check_cancel, probe
from fine import Editor, create, get, save
from pipeline import now
from service import dispatch
from storage import Store


class FineExportTest(unittest.TestCase):
    setUp = test_fine.FineTest.setUp
    tearDown = test_fine.FineTest.tearDown
    run_cmd = test_fine.FineTest.run_cmd
    plan = test_fine.FineTest.plan

    def confirmed_plan(self):
        self.plan()
        editor = Editor(self.store, {'project_id': self.p['id']})
        editor.current()['confirmed'] = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.p = editor.persist()

    def export_attempt(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            self.p = Editor(self.store, {'cmd': 'edit_export', 'project_id': self.p['id'],
                                        'revision': self.p['revision'], **kwargs}).run()
        return self.p

    def test_selected_existing_folder_gets_real_mp4_and_srt_without_subfolder(self):
        self.plan()
        self.run_cmd('edit_confirm')
        version = self.p['versions'][-1]
        preview = Path(version['preview'])
        preview_hash = hashlib.sha256(preview.read_bytes()).digest()
        chosen = self.root / '用户选择的目录 with spaces'
        chosen.mkdir()
        self.run_cmd('edit_export', export_dir=str(chosen), srt=True, version_id=version['id'])
        record = self.p['exports'][-1]
        target = Path(record['path'])
        subtitle = Path(record['subtitle'])
        self.assertEqual(target.parent, chosen.resolve())
        self.assertEqual(subtitle, target.with_suffix('.srt'))
        self.assertTrue(target.is_absolute())
        self.assertTrue(subtitle.is_file())
        self.assertIn('第3', subtitle.read_text(encoding='utf-8', errors='strict'))
        self.assertFalse(subtitle.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertEqual({p.suffix for p in chosen.iterdir()}, {'.mp4', '.srt'})
        self.assertAlmostEqual(probe(target, self.store.settings(), self.store)['duration'], 8, delta=.3)
        self.assertEqual(get(self.store, self.p['id'])['exports'][-1]['path'], str(target))
        self.assertEqual(hashlib.sha256(preview.read_bytes()).digest(), preview_hash)
        self.assertEqual(self.p['versions'][-1]['preview'], str(preview))
        self.assertFalse((self.root / 'exports').exists())

    def test_invalid_destination_is_rejected_before_render_or_audio_preparation(self):
        self.confirmed_plan()
        invalid = [None, '', ' \t ', [], True, 12, 'relative-folder', str(self.video),
                   str(self.root / 'missing'), str(self.root) + '\x00', ' ' + str(self.root)]
        with patch('fine.command') as render, patch('fine_audio.prepare') as audio:
            for value in invalid:
                with self.subTest(value=value):
                    result = self.export_attempt(export_dir=value)
                    self.assertTrue(result['error'])
                    self.assertEqual(result['execution']['state'], 'failed')
                    self.assertEqual(result['exports'], [])
            render.assert_not_called()
            audio.assert_not_called()
        self.assertFalse((self.store.task_dir(self.p['id']) / 'renders').exists())

    def test_unwritable_directory_fails_before_render_without_fallback(self):
        self.confirmed_plan()
        chosen = self.root / '不可写目录'
        chosen.mkdir()
        with patch('fine.tempfile.TemporaryFile', side_effect=PermissionError('denied')) as writable, \
                patch('fine.command') as render:
            result = self.export_attempt(export_dir=str(chosen))
        writable.assert_called_once()
        render.assert_not_called()
        self.assertIn('无法写入', result['error'])
        self.assertEqual(result['exports'], [])
        self.assertEqual(list(chosen.iterdir()), [])
        self.assertFalse((self.root / 'exports').exists())

    def test_version_switch_while_choosing_folder_is_rejected_before_preparation(self):
        self.confirmed_plan()
        original = self.p['current_version']
        self.run_cmd('edit_update', subtitles=False)
        self.assertNotEqual(self.p['current_version'], original)
        with patch('fine.tempfile.TemporaryFile') as writable, patch('fine.command') as render:
            result = self.export_attempt(export_dir=str(self.root), version_id=original)
        writable.assert_not_called()
        render.assert_not_called()
        self.assertIn('版本已变化', result['error'])
        self.assertEqual(result['exports'], [])

    def test_cancel_copy_srt_and_publish_failures_leave_no_record_or_files_and_keep_preview(self):
        import fine
        self.plan()
        self.run_cmd('edit_confirm')
        completed = copy.deepcopy(self.p['versions'])
        preview = Path(completed[-1]['preview'])
        stamp = preview.stat().st_mtime_ns
        preview_hash = hashlib.sha256(preview.read_bytes()).digest()
        chosen = self.root / '指定保存位置'
        chosen.mkdir()
        original_copy = fine.shutil.copy2
        original_write = fine.write_srt
        original_replace = Path.replace

        def cancel_copy(source, destination):
            original_copy(source, destination)
            raise Cancelled()

        def fail_srt(path, cues):
            if Path(path).parent == chosen:
                Path(path).write_text('partial', encoding='utf-8')
                raise OSError('字幕保存失败')
            return original_write(path, cues)

        def fail_publish(path, destination):
            if Path(destination).parent == chosen and Path(destination).suffix == '.srt':
                raise OSError('字幕发布失败')
            return original_replace(path, destination)

        def cancel_after_publish(store, project_id):
            check_cancel(store, project_id)
            if list(chosen.glob('*.srt')):
                raise Cancelled()

        cases = [('fine.shutil.copy2', cancel_copy, 'cancelled'),
                 ('fine.write_srt', fail_srt, 'failed'),
                 ('pathlib.Path.replace', fail_publish, 'failed'),
                 ('fine.check_cancel', cancel_after_publish, 'cancelled')]
        for target, failure, state in cases:
            with self.subTest(target=target), patch(target, failure):
                result = self.export_attempt(export_dir=str(chosen), srt=True)
                self.assertEqual(result['execution']['state'], state)
                self.assertEqual(result['exports'], [])
                self.assertEqual(get(self.store, self.p['id'])['exports'], [])
                self.assertEqual(result['versions'], completed)
                self.assertEqual(list(chosen.iterdir()), [])
                self.assertEqual(preview.stat().st_mtime_ns, stamp)
                self.assertEqual(hashlib.sha256(preview.read_bytes()).digest(), preview_hash)


class FineExportRevealTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'data')
        source = self.root / 'source.mp4'
        source.write_bytes(b'source')
        self.task = {'id': str(uuid.uuid4()), 'created': now(), 'title': '故事', 'video': str(source),
                     'clips': [{'id': 1, 'title': '事件一', 'start': 0, 'end': 2},
                               {'id': 2, 'title': '事件二', 'start': 2, 'end': 4}]}
        self.store.put(self.task)
        self.project = create(self.store, self.task['id'], 1)
        self.other = create(self.store, self.task['id'], 2)
        self.chosen = self.root / 'selected folder'
        self.chosen.mkdir()
        self.target = self.chosen / 'saved.mp4'
        self.target.write_bytes(b'export')
        self.project['exports'] = [{'id': 'saved-record', 'path': str(self.target), 'subtitle': ''}]
        with contextlib.redirect_stdout(io.StringIO()):
            save(self.store, self.project)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def reveal(self, **kwargs):
        return dispatch({'cmd': 'reveal', '_data_dir': str(self.store.root), **kwargs})

    def test_record_lookup_returns_actual_parent_and_ignores_arbitrary_request_path(self):
        result = self.reveal(project_id=self.project['id'], export_id='saved-record', path=str(self.root))
        self.assertEqual(result, {'path': str(self.chosen.resolve()), 'is_file': False})

    def test_record_ids_must_belong_to_the_requested_project(self):
        invalid = [{'project_id': self.project['id']}, {'export_id': 'saved-record'},
                   {'project_id': self.project['id'], 'export_id': 'invented'},
                   {'project_id': self.other['id'], 'export_id': 'saved-record'},
                   {'project_id': [], 'export_id': 'saved-record'}]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.reveal(**kwargs)

    def test_missing_file_or_invalid_saved_path_rejected_and_legacy_reveal_retained(self):
        self.target.unlink()
        with self.assertRaisesRegex(ValueError, '移动或删除'):
            self.reveal(project_id=self.project['id'], export_id='saved-record')
        self.project['exports'][0]['path'] = 'relative.mp4'
        with contextlib.redirect_stdout(io.StringIO()):
            save(self.store, self.project)
        with self.assertRaisesRegex(ValueError, '路径无效'):
            self.reveal(project_id=self.project['id'], export_id='saved-record')
        self.assertEqual(self.reveal(task_id=self.task['id']),
                         {'path': self.task['video'], 'is_file': True})
        self.assertEqual(self.reveal(), {'path': str(self.store.root), 'is_file': False})
        self.assertEqual(self.reveal(task_id=self.task['id'], project_id=None, export_id=None),
                         {'path': self.task['video'], 'is_file': True})
        self.assertEqual(self.reveal(project_id=None, export_id=None),
                         {'path': str(self.store.root), 'is_file': False})


if __name__ == '__main__':
    unittest.main()
