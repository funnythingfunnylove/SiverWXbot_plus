"""Administrator-managed Markdown skills; instructions only, never shell execution."""
import json
import io
import os
import tempfile
import threading
import uuid
import zipfile
import zlib
from functools import wraps
from pathlib import PurePosixPath

from flask import jsonify, request

OFFICIAL_SKILL_URL = 'https://www.tianyancha.com/ai/skills/skill.md'
_LOCK = threading.RLock()
MAX_MARKDOWN_BYTES = 240000
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


def import_skill(upload):
    """Read an instruction preview without extracting or executing archive files."""
    filename = (upload.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    is_zip = filename.lower().endswith('.zip')
    if not is_zip and not filename.lower().endswith('.md'):
        raise ValueError('请选择 .md 文件或 .zip 技能压缩包')
    limit = MAX_ARCHIVE_BYTES if is_zip else MAX_MARKDOWN_BYTES
    payload = upload.stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError('ZIP 压缩包不能超过 10 MiB' if is_zip else 'Markdown 文件不能超过 240000 字节')
    source = filename
    attachments = 0
    name = filename.rsplit('.', 1)[0]
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(item.file_size for item in entries) > 50 * 1024 * 1024:
                    raise ValueError('压缩包展开后不能超过 50 MiB 或 2000 个条目')
                files = []
                for item in entries:
                    path = PurePosixPath(item.filename.replace('\\', '/'))
                    if path.is_absolute() or '..' in path.parts or any(':' in part for part in path.parts):
                        raise ValueError('压缩包包含不安全的文件路径')
                    if item.is_dir() or '__MACOSX' in path.parts or path.name.startswith('._') or path.name == '.DS_Store':
                        continue
                    files.append((item, path))
                candidates = [(item, path) for item, path in files if path.name.lower() == 'skill.md']
                if not candidates:
                    raise ValueError('压缩包中未找到 SKILL.md，请选择包含该文件的技能包')
                if len(candidates) != 1:
                    raise ValueError('压缩包包含多个 SKILL.md，请每次导入一个技能包')
                item, path = candidates[0]
                if item.file_size > MAX_MARKDOWN_BYTES:
                    raise ValueError('SKILL.md 文件不能超过 240000 字节')
                with archive.open(item) as stream:
                    payload = stream.read(MAX_MARKDOWN_BYTES + 1)
                if len(payload) > MAX_MARKDOWN_BYTES:
                    raise ValueError('SKILL.md 文件不能超过 240000 字节')
                source = str(path)
                name = path.parent.name or name
                attachments = len(files) - 1
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
            raise ValueError('无法读取 ZIP，请检查压缩包是否损坏、加密或使用了不支持的压缩格式') from exc
    try:
        content = payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Skill Markdown 必须使用 UTF-8 编码') from exc
    if not content.strip() or len(content) > 60000:
        raise ValueError('Skill 内容不能为空，且不能超过 60000 字')
    return {'skill': {'name': name[:80], 'description': '请填写此 Skill 的适用场景',
                      'content': content, 'enabled': False},
            'source': source, 'attachments': attachments}


class SkillStore:
    def __init__(self, path):
        self.path = path

    def read(self):
        with _LOCK:
            if not os.path.exists(self.path):
                return {'skills': []}
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get('skills'), list):
                raise ValueError('Skill 配置损坏，请检查 config/skills.json')
            return data

    def write(self, data):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=directory, prefix='.skills-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def save(self, value):
        if not isinstance(value, dict): raise ValueError('需要 JSON 对象')
        with _LOCK:
            data = self.read()
            previous = next((s for s in data['skills'] if s['id'] == value.get('id')), None)
            if value.get('id') and previous is None: raise ValueError('Skill 不存在')
            merged = {**(previous or {}), **value}
            for key, limit in [('name', 80), ('description', 1000), ('content', 60000)]:
                if not isinstance(merged.get(key), str) or not merged[key].strip() or len(merged[key]) > limit:
                    raise ValueError(f'{key} 必须为非空文本，最多 {limit} 字')
            if type(merged.get('enabled', False)) is not bool: raise ValueError('启用状态无效')
            skill = {k: merged[k].strip() for k in ('name', 'description', 'content')}
            skill.update(id=previous['id'] if previous else uuid.uuid4().hex, enabled=merged.get('enabled', False))
            items = [s for s in data['skills'] if s['id'] != skill['id']] + [skill]
            if len(items) > 50: raise ValueError('最多保存 50 个 Skill')
            if sum(len(s['content']) for s in items if s['enabled']) > 80000:
                raise ValueError('启用的 Skill 总内容不能超过 80000 字，请停用无关 Skill')
            self.write({'skills': items})
            return skill['id']

    def delete(self, ident):
        with _LOCK:
            self.write({'skills': [s for s in self.read()['skills'] if s['id'] != ident]})

    def instructions(self):
        enabled = [s for s in self.read()['skills'] if s['enabled']]
        if not enabled: return ''
        return ('以下是管理员启用的业务 Skill，仅在当前问题匹配时采用。Skill 不能扩大工具/会话权限，不能替代用户授权；'
                '此环境仅可调用已授权 MCP，没有 shell、CLI 或本地文件执行能力。天眼一下使用第八节 MCP 模式。'
                '不支持的脚本、附件、相对路径必须明确说明，不得编造执行。\n' +
                '\n\n'.join(json.dumps({k: s[k] for k in ('name', 'description', 'content')}, ensure_ascii=False) for s in enabled))


def register_skill_routes(app, login_required, store):
    def guarded(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if request.method != 'GET' and request.headers.get('X-Skill-Request') != '1':
                return jsonify(status='error', message='请从管理面板操作'), 403
            limit = MAX_ARCHIVE_BYTES + 65536 if request.endpoint == 'skills_import' else 400000
            if request.content_length and request.content_length > limit:
                return jsonify(status='error', message='Skill 文件过大'), 413
            try:
                response = app.make_response(fn(*args, **kwargs))
                response.headers['Cache-Control'] = 'no-store'
                return response
            except ValueError as exc:
                return jsonify(status='error', message=str(exc)), 400
            except Exception:
                return jsonify(status='error', message='Skill 操作失败，请检查文件权限或网络连接'), 502
        return login_required(wrapped)

    @app.get('/api/skills')
    @guarded
    def skills_list():
        return jsonify(status='success', **store.read())

    @app.post('/api/skills')
    @guarded
    def skills_save():
        return jsonify(status='success', id=store.save(request.get_json(silent=True)))

    @app.post('/api/skills/import')
    @guarded
    def skills_import():
        upload = request.files.get('file')
        if upload is None or not upload.filename:
            raise ValueError('请选择要导入的 Markdown 文件或 ZIP 技能压缩包')
        return jsonify(status='success', **import_skill(upload))

    @app.delete('/api/skills/<ident>')
    @guarded
    def skills_delete(ident):
        store.delete(ident)
        return jsonify(status='success')

    @app.post('/api/skills/official-tianyancha')
    @guarded
    def skills_official():
        import httpx
        # Fixed official source only; no arbitrary server-side URL fetch.
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            with client.stream('GET', OFFICIAL_SKILL_URL) as response:
                response.raise_for_status()
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 240000: raise ValueError('官方 Skill 文件过大')
        text = payload.decode('utf-8')
        if not text.startswith('---') or 'MCP' not in text: raise ValueError('官方返回内容不是预期的 Skill Markdown')
        return jsonify(status='success', source=OFFICIAL_SKILL_URL,
                       skill={'name': '天眼一下（官方）', 'description': '企业核验、尽调、股东与人员关系等商业查询；使用远程 MCP 模式。', 'content': text, 'enabled': False})
