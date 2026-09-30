"""Isolated SliceAI storage. Never searches another application's files or keys."""
from __future__ import annotations
import base64
import ctypes
import json
import os
import sqlite3
from ctypes import wintypes
from pathlib import Path

DEFAULTS = {
    'api_base': 'https://api.deepseek.com', 'api_model': 'deepseek-flash',
    'api_json_mode': True, 'api_timeout': 90, 'output_dir': '',
    'ffmpeg_path': '', 'ffprobe_path': '', 'asr_threads': 2,
    'max_clips': 12, 'chat_offset': 0, 'asr_model_dir': '',
}

def protect(text: str) -> str:
    if os.name != 'nt':
        raise ValueError('密钥保存使用 Windows DPAPI，仅支持 Windows。')
    return base64.b64encode(_crypt(text.encode('utf-8'), True)).decode('ascii')

def unprotect(value: str) -> str:
    return _crypt(base64.b64decode(value), False).decode('utf-8')

def _crypt(data: bytes, encrypt: bool) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    func = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    func.restype = wintypes.BOOL
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError('Windows 无法加密或解密此密钥，请重新保存。')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)

class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'sliceai.sqlite3', timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL)')
        self.db.commit()

    def settings(self, secret=False):
        data = dict(DEFAULTS)
        rows = dict(self.db.execute('SELECT name,value FROM settings'))
        for key in DEFAULTS:
            if key in rows:
                data[key] = json.loads(rows[key])
        data['key_saved'] = bool(rows.get('api_key'))
        if secret:
            data['api_key'] = unprotect(rows['api_key']) if rows.get('api_key') else ''
        return data

    def save_settings(self, values):
        from urllib.parse import urlparse
        current = self.settings()
        next_values = {**current, **{k: v for k, v in values.items() if k in DEFAULTS}}
        parsed = urlparse(next_values['api_base'])
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('API 地址不能包含用户名、密码、查询参数或片段。')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ValueError('远程 API 必须使用 HTTPS；本地 API 可使用 HTTP。')
        if not parsed.hostname or not str(next_values['api_model']).strip():
            raise ValueError('请填写有效的 API 地址和模型名称。')
        next_values['asr_threads'] = max(1, min(8, int(next_values['asr_threads'])))
        next_values['max_clips'] = max(1, min(50, int(next_values['max_clips'])))
        next_values['api_timeout'] = max(15, min(300, int(next_values['api_timeout'])))
        next_values['chat_offset'] = max(-600, min(600, float(next_values['chat_offset'])))
        # A credential belongs to its destination; changing the endpoint requires a new key.
        changed_host = parsed.netloc != urlparse(current['api_base']).netloc
        with self.db:
            for key in DEFAULTS:
                self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',
                                (key, json.dumps(next_values[key], ensure_ascii=False)))
            if values.get('clear_key') or changed_host:
                self.db.execute("DELETE FROM settings WHERE name='api_key'")
            if values.get('api_key', '').strip():
                self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',
                                ('api_key', protect(values['api_key'].strip())))
        return self.settings()

    def put(self, task):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO tasks VALUES (?,?,?)',
                            (task['id'], task['created'], json.dumps(task, ensure_ascii=False)))

    def get(self, task_id):
        row = self.db.execute('SELECT payload FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('找不到这个任务。')
        return json.loads(row[0])

    def tasks(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM tasks ORDER BY created DESC')]

    def task_dir(self, task_id):
        # Only persisted UUID task identifiers may become path components.
        import uuid
        uuid.UUID(task_id)
        folder = self.root / 'tasks' / task_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder
