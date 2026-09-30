"""Reject links and Windows reparse points without requiring Python 3.12."""
import stat


def is_link(path):
    if path.is_symlink():
        return True
    junction = getattr(path, 'is_junction', None)
    if junction and junction():
        return True
    try:
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))
