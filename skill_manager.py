"""Administrator-managed Markdown skills; instructions only, never shell execution."""
import json
import os
import tempfile
import threading
import uuid
from functools import wraps

from flask import jsonify, request

OFFICIAL_SKILL_URL = 'https://www.tianyancha.com/ai/skills/skill.md'
_LOCK = threading.RLock()


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
            if request.content_length and request.content_length > 400000:
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
