"""Delete one task and its edits, optionally removing only their generated files."""
from pathlib import Path
import uuid
import fine
from pipeline import ACTIVE
from path_safety import is_link


def delete_task(store, task_id, delete_files=False):
    if type(delete_files) is not bool:
        raise ValueError('删除文件选项无效。')
    task = store.get(task_id)
    projects = fine.summaries(store)
    edits = [p for p in projects if p['task_id'] == task_id]
    if task.get('status') in ACTIVE or any(p['status'] in ('busy', 'queued') for p in edits):
        raise ValueError('任务正在处理，请先取消并等待停止后再删除。')
    tasks = store.tasks()
    protected = set()

    def protect(value):
        if value:
            protected.add(Path(value).resolve())

    for t in tasks:
        for key in ('video', 'subtitle', 'chat'):
            protect(t.get(key))
    # A shared export or preview still used by another task must remain available.
    def referenced(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('path', 'subtitle', 'thumbnail', 'preview') and isinstance(item, str):
                    protect(item)
                else:
                    referenced(item)
        elif isinstance(value, list):
            for item in value:
                referenced(item)
    for t in tasks:
        if t['id'] != task_id:
            referenced(t)
    for p in projects:
        if p['task_id'] != task_id:
            referenced(p)

    files, folders = set(), set()
    def add_file(path):
        # Resolve before operating, but reject links rather than deleting their targets.
        if is_link(path):
            raise ValueError('生成文件中存在链接，未删除任务；请先移除该链接。')
        real = path.resolve()
        if real not in protected and real.is_file():
            files.add(real)

    if delete_files:
        cache_base = store.root / 'tasks'
        cache_root = cache_base.resolve()
        if is_link(cache_base) or cache_root.parent != store.root:
            raise ValueError('任务缓存目录不在安全位置，未删除任务。')
        for owner in [task_id] + [p['id'] for p in edits]:
            if str(uuid.UUID(owner)) != owner:
                raise ValueError('任务目录标识无效。')
            folder = store.root / 'tasks' / owner
            if is_link(folder) or folder.resolve().parent != cache_root:
                raise ValueError('任务目录不在安全位置，未删除任务。')
            if folder.exists():
                pending = [folder]
                while pending:
                    entry = pending.pop()
                    if is_link(entry) or not entry.resolve().is_relative_to(folder.resolve()):
                        raise ValueError('任务缓存包含外部链接，未删除任务。')
                    if entry.is_dir():
                        folders.add(entry.resolve())
                        pending.extend(entry.iterdir())
                    else:
                        add_file(entry)
        # Never recursively delete the user's export directory.
        for record in task.get('exports', []) + [r for p in edits for r in p.get('exports', [])]:
            for key in ('path', 'subtitle'):
                if record.get(key):
                    path = Path(record[key])
                    if path.suffix.lower() not in ('.mp4', '.srt'):
                        raise ValueError('导出文件类型异常，未删除任务。')
                    add_file(path)
        thumbnail = task.get('thumbnail')
        if thumbnail:
            path = Path(thumbnail)
            if path.resolve().parent == (store.root / 'imports').resolve():
                add_file(path)
        # Validation completes before the first filesystem change. On I/O failure keep
        # records so retrying is possible; missing files are treated as already removed.
        try:
            for path in files:
                path.unlink(missing_ok=True)
            for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
                if not any(folder.iterdir()):
                    folder.rmdir()
        except OSError as exc:
            raise ValueError('部分文件无法删除，任务记录已保留。请关闭占用文件的程序后重试。') from exc
    with store.db:
        for p in edits:
            store.db.execute('DELETE FROM edits WHERE id=?', (p['id'],))
        store.db.execute('DELETE FROM tasks WHERE id=?', (task_id,))
    return {'id': task_id, 'deleted_files': len(files), 'edit_ids': [p['id'] for p in edits]}
