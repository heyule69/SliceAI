import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from path_safety import is_link


class LinkCompatibilityTest(unittest.TestCase):
    def test_old_pathlib_detects_windows_junction_from_native_attributes(self):
        # Python 3.11 has no is_junction; lstat still exposes reparse attributes.
        old_path = SimpleNamespace(is_symlink=lambda: False,
                                   lstat=lambda: SimpleNamespace(st_file_attributes=0x410))
        self.assertTrue(is_link(old_path))
        old_path.lstat = lambda: SimpleNamespace(st_file_attributes=0x10)
        self.assertFalse(is_link(old_path))

    def test_ordinary_and_missing_paths_are_safe_without_junction_api(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(is_link(Path(temp)))
            self.assertFalse(is_link(Path(temp) / 'not-created-yet'))

    def test_io_failure_is_not_treated_as_permission_to_delete(self):
        def denied():
            raise PermissionError('cannot inspect native path')
        path = SimpleNamespace(is_symlink=lambda: False, lstat=denied)
        with self.assertRaises(PermissionError):
            is_link(path)
