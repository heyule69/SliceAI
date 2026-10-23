import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from engine import command
from runtime_check import audio_locations, component_gap, venv_python


class RuntimeCheckTest(unittest.TestCase):
    def test_gap_names_the_missing_interpreter_script_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix, model = audio_locations(root)
            message = component_gap(prefix, model, '声音处理')
            self.assertIn(prefix[0], message)
            self.assertIn(prefix[1], message)
            self.assertIn(str(model / 'manifest.json'), message)
            self.assertIn('缺少声音处理环境', message)
            python = Path(prefix[0])
            python.parent.mkdir(parents=True)
            python.write_bytes(b'python')
            script = Path(prefix[1])
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_bytes(b'worker')
            model.mkdir(parents=True)
            (model / 'manifest.json').write_text('{}', encoding='utf-8')
            self.assertEqual(component_gap(prefix, model, '声音处理'), '')

    def test_venv_layout_follows_the_current_platform(self):
        path = venv_python(Path('/opt/sliceai'), '.alignment-venv')
        if sys.platform == 'win32':
            self.assertEqual(path, Path('/opt/sliceai/.alignment-venv/Scripts/python.exe'))
        else:
            self.assertEqual(path, Path('/opt/sliceai/.alignment-venv/bin/python'))

    def test_missing_program_names_the_path(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / 'sliceai-missing-worker'
            store = SimpleNamespace(root=Path(temp), task_dir=lambda _task: Path(temp))
            with self.assertRaises(ValueError) as caught:
                command([str(missing)], store, None)
            self.assertIn(str(missing), str(caught.exception))
            self.assertIn('sliceai-missing-worker', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
