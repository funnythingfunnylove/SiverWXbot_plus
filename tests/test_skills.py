import json
import io
import zipfile
from functools import wraps
import pytest
from flask import Flask, session, jsonify
from skill_manager import SkillStore, register_skill_routes
from mcp_config import MCPConfigStore, TYC_URL


def test_browser_endpoint_drops_official_credentials(tmp_path):
    store = MCPConfigStore(str(tmp_path/'mcp.json'))
    store.save({'kind': 'tianyancha', 'name': '天眼查', 'key': 'old-secret', 'url': 'https://wrong.test'})
    saved = store.read()['servers'][0]
    assert saved['url'] == TYC_URL
    assert saved['headers'] == {}
    assert 'old-secret' not in (tmp_path/'mcp.json').read_text()
    with pytest.raises(ValueError):
        store.save({'name': 'official', 'url': 'https://mcp.tianyancha.com/mcp'})


def test_legacy_official_config_disabled_on_read(tmp_path):
    path = tmp_path/'mcp.json'
    path.write_text(json.dumps({'enabled': True, 'servers': [
        {'id': 'legacy', 'kind': 'tianyancha', 'url': 'https://mcp.tianyancha.com/mcp',
         'enabled': True, 'headers': {'Authorization': 'old-secret'}, 'allowed_tools': ['search_companies']}]}))
    server = MCPConfigStore(str(path)).read()['servers'][0]
    assert server['url'] == TYC_URL
    assert not server['enabled'] and not server['headers'] and not server['allowed_tools']
    assert server['migration_notice']


def test_skill_toggle_and_validation(tmp_path):
    store=SkillStore(str(tmp_path/'skills.json'))
    ident=store.save({'name':'test','description':'test queries','content':'Answer with evidence','enabled':False})
    assert store.instructions()==''
    store.save({'id':ident,'enabled':True})
    assert 'Answer with evidence' in store.instructions()
    store.save({'id':ident,'enabled':False})
    assert store.instructions()==''
    with pytest.raises(ValueError): store.save({'id':'../x','enabled':True})
    with pytest.raises(ValueError): store.save({'name':'x','description':'x','content':'a'*60001})
    store.delete(ident)
    assert store.read()=={'skills':[]}


def test_skill_api_auth_csrf_and_roundtrip(tmp_path):
    app=Flask(__name__);app.secret_key='test'
    def guard(fn):
        @wraps(fn)
        def inner(*a,**k):
            if not session.get('logged_in'):return jsonify(status='error'),401
            return fn(*a,**k)
        return inner
    register_skill_routes(app,guard,SkillStore(str(tmp_path/'skills.json')))
    c=app.test_client()
    assert c.get('/api/skills').status_code==401
    with c.session_transaction() as s:s['logged_in']=True
    assert c.post('/api/skills',json={}).status_code==403
    h={'X-Skill-Request':'1'}
    r=c.post('/api/skills',json={'name':'demo','description':'demo','content':'# Demo','enabled':True},headers=h)
    assert r.status_code==200
    assert c.get('/api/skills').json['skills'][0]['enabled']
    assert c.post('/api/skills',json=[],headers=h).status_code==400
    assert c.delete('/api/skills/'+r.json['id'],headers=h).status_code==200


def test_official_import_returns_preview_without_enabling(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import httpx
    class Response:
        def raise_for_status(self): pass
        def iter_bytes(self): yield '---\nname: 天眼一下\n---\n## MCP 模式'.encode()
    class Client:
        def __init__(self, **kwargs): assert kwargs['follow_redirects'] is False
        def __enter__(self): return self
        def __exit__(self,*args): pass
        @contextmanager
        def stream(self, method, url):
            assert url == 'https://www.tianyancha.com/ai/skills/skill.md'
            yield Response()
    monkeypatch.setattr(httpx,'Client',Client)
    app=Flask(__name__)
    store=SkillStore(str(tmp_path/'skills.json'))
    register_skill_routes(app,lambda fn:fn,store)
    result=app.test_client().post('/api/skills/official-tianyancha',json={},headers={'X-Skill-Request':'1'})
    assert result.status_code==200
    assert result.json['skill']['enabled'] is False
    assert 'MCP 模式' in result.json['skill']['content']
    assert store.read()['skills']==[]


def skill_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def skill_import_client(tmp_path):
    app = Flask(__name__)
    store = SkillStore(str(tmp_path / 'skills.json'))
    register_skill_routes(app, lambda fn: fn, store)
    return app.test_client(), store


@pytest.mark.parametrize('entry', ['SKILL.md', 'demo/SKILL.md', 'repo/skills/demo/skill.md'])
def test_zip_import_preview_and_save(skill_import_client, entry):
    client, store = skill_import_client
    content = '---\nname: demo\n---\n# 中文技能\n使用 MCP。'
    payload = skill_zip([(entry, content), ('demo/references/guide.md', '# Guide'),
                         ('__MACOSX/demo/._SKILL.md', 'metadata')])
    result = client.post('/api/skills/import', data={'file': (io.BytesIO(payload), 'demo.zip')},
                         headers={'X-Skill-Request': '1'})
    assert result.status_code == 200
    assert result.json['source'] == entry
    assert result.json['attachments'] == 1
    skill = result.json['skill']
    assert skill['content'] == content
    assert skill['name'] == 'demo'
    assert skill['enabled'] is False
    assert store.read() == {'skills': []}
    skill['description'] = '测试适用场景'
    assert client.post('/api/skills', json=skill, headers={'X-Skill-Request': '1'}).status_code == 200
    assert store.read()['skills'][0]['content'] == content
    assert store.instructions() == ''


def test_markdown_import_and_request_guard(skill_import_client):
    client, _ = skill_import_client
    assert client.post('/api/skills/import').status_code == 403
    headers = {'X-Skill-Request': '1'}
    assert client.post('/api/skills/import', headers=headers).status_code == 400
    result = client.post('/api/skills/import', headers=headers,
                         data={'file': (io.BytesIO(b'\xef\xbb\xbf# Markdown'), 'notes.md')})
    assert result.status_code == 200
    assert result.json['skill']['content'] == '# Markdown'
    assert result.json['skill']['name'] == 'notes'
    assert result.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('filename,payload,message', [
    ('bad.zip', b'not zip', '无法读取 ZIP'),
    ('missing.zip', skill_zip([('README.md', 'hello')]), '未找到 SKILL.md'),
    ('many.zip', skill_zip([('a/SKILL.md', 'a'), ('b/SKILL.md', 'b')]), '多个 SKILL.md'),
    ('unsafe.zip', skill_zip([('../SKILL.md', 'hello')]), '不安全'),
    ('unsafe.zip', skill_zip([('C:\\SKILL.md', 'hello')]), '不安全'),
    ('empty.zip', skill_zip([('SKILL.md', ' ')]), '不能为空'),
    ('large.zip', skill_zip([('SKILL.md', 'a' * 240001)]), '240000'),
    ('long.zip', skill_zip([('SKILL.md', 'a' * 60001)]), '60000'),
    ('utf8.zip', skill_zip([('SKILL.md', b'\xff')]), 'UTF-8'),
    ('many-files.zip', skill_zip([(str(i), '') for i in range(2001)]), '2000'),
    ('text.md', b'\xff', 'UTF-8'),
    ('text.md', b'a' * 240001, '240000'),
    ('text.txt', b'hello', '.md'),
])
def test_import_invalid_files(skill_import_client, filename, payload, message):
    client, store = skill_import_client
    result = client.post('/api/skills/import', headers={'X-Skill-Request': '1'},
                         data={'file': (io.BytesIO(payload), filename)})
    assert result.status_code == 400
    assert message in result.json['message']
    assert store.read() == {'skills': []}


def test_zip_request_size_limit(skill_import_client):
    client, _ = skill_import_client
    result = client.post('/api/skills/import', headers={'X-Skill-Request': '1'},
                         data={'file': (io.BytesIO(b'x' * (11 * 1024 * 1024)), 'large.zip')})
    assert result.status_code == 413


def test_package_files_survive_save_edit_toggle_and_restart(skill_import_client):
    client, store = skill_import_client
    h = {'X-Skill-Request': '1'}
    binary = bytes(range(256))
    payload = skill_zip([('demo/SKILL.md', '# Demo\nRead references/guide.md'),
                         ('demo/references/guide.md', 'REFERENCE_MARKER'),
                         ('demo/assets/image.bin', binary),
                         ('demo/scripts/run.py', 'print("SCRIPT_MARKER")'),
                         ('demo/empty/', '')])
    preview = client.post('/api/skills/import', headers=h,
                          data={'file': (io.BytesIO(payload), 'demo.zip')}).json['skill']
    token = preview['import_token']
    assert (store.staging / token / 'package/demo/assets/image.bin').read_bytes() == binary
    assert len(preview['files']) == 4
    response = client.post('/api/skills', headers=h, json=preview)
    assert response.status_code == 200
    ident = response.json['id']
    assert not (store.staging / token).exists()
    restarted = SkillStore(store.path)
    skill = restarted.read()['skills'][0]
    original = restarted.package_dir(skill)
    assert (original / 'demo/assets/image.bin').read_bytes() == binary
    assert (original / 'demo/empty').is_dir()
    restarted.save({'id': ident, 'content': '# Edited', 'enabled': True})
    skill = restarted.read()['skills'][0]
    folder = restarted.package_dir(skill)
    assert not original.exists()
    assert (folder / skill['entry']).read_text() == '# Edited'
    assert (folder / 'demo/assets/image.bin').read_bytes() == binary
    assert (folder / 'demo/scripts/run.py').read_text() == 'print("SCRIPT_MARKER")'
    instructions = restarted.instructions()
    assert 'REFERENCE_MARKER' in instructions
    assert 'demo/assets/image.bin' in instructions
    assert 'SCRIPT_MARKER' not in instructions
    restarted.save({'id': ident, 'enabled': False})
    assert restarted.instructions() == ''
    assert len(restarted.read()['skills'][0]['files']) == 4
    restarted.delete(ident)
    assert not folder.parent.exists()


def test_cancel_and_invalid_package_cleanup(skill_import_client):
    client, store = skill_import_client
    h = {'X-Skill-Request': '1'}
    response = client.post('/api/skills/import', headers=h,
                           data={'file': (io.BytesIO(skill_zip([('SKILL.md', '# Demo')])), 'demo.zip')})
    skill = response.json['skill']
    token = skill['import_token']
    assert client.delete('/api/skills/import/' + token, headers=h).status_code == 200
    assert not (store.staging / token).exists()
    assert client.post('/api/skills', json=skill, headers=h).status_code == 400
    assert client.post('/api/skills/import', headers=h,
                       data={'file': (io.BytesIO(b'bad'), 'demo.zip')}).status_code == 400
    assert list(store.staging.iterdir()) == []


def test_legacy_folder_migration_and_failed_save_preserves_package(tmp_path, monkeypatch):
    store = SkillStore(str(tmp_path / 'skills.json'))
    ident = 'a' * 32
    store.write({'skills': [{'id': ident, 'name': 'Legacy', 'description': 'Demo',
                             'content': '# Original', 'enabled': True}]})
    skill = store.read()['skills'][0]
    folder = store.package_dir(skill)
    assert (folder / 'SKILL.md').read_text() == '# Original'
    assert skill['enabled'] is True
    def fail_write(data):
        raise OSError('disk full')
    monkeypatch.setattr(store, 'write', fail_write)
    with pytest.raises(OSError):
        store.save({'id': ident, 'content': '# Changed'})
    assert store.read()['skills'][0]['content'] == '# Original'
    assert (folder / 'SKILL.md').read_text() == '# Original'
    assert list(folder.parent.iterdir()) == [folder]


@pytest.mark.parametrize('entries', [
    [('SKILL.md', '# Demo'), ('assets/a', 'a'), ('assets/A', 'b')],
    [('SKILL.md', '# Demo'), ('assets', 'file'), ('assets/a', 'conflict')],
    [('SKILL.md', '# Demo'), ('assets/CON.txt', 'reserved')],
    [('SKILL.md', '# Demo'), ('assets/a', 'a'), ('Assets/b', 'b')],
])
def test_package_path_conflicts(skill_import_client, entries):
    client, store = skill_import_client
    result = client.post('/api/skills/import', headers={'X-Skill-Request': '1'},
                         data={'file': (io.BytesIO(skill_zip(entries)), 'demo.zip')})
    assert result.status_code == 400
    assert list(store.staging.iterdir()) == []


def test_reference_budget_preserves_unloaded_files(skill_import_client):
    client, store = skill_import_client
    payload = skill_zip([('SKILL.md', '# Demo'), ('references/a.txt', 'a' * 50000),
                         ('references/b.md', 'b' * 40000), ('references/c.txt', b'\xff')])
    skill = client.post('/api/skills/import', headers={'X-Skill-Request': '1'},
                        data={'file': (io.BytesIO(payload), 'demo.zip')}).json['skill']
    skill['enabled'] = True
    store.save(skill)
    instructions = store.instructions()
    assert 'a' * 50000 in instructions
    assert 'b' * 40000 not in instructions
    saved = store.read()['skills'][0]
    assert (store.package_dir(saved) / 'references/b.md').stat().st_size == 40000
    assert (store.package_dir(saved) / 'references/c.txt').read_bytes() == b'\xff'


def test_package_symlink_rejected(skill_import_client):
    client, store = skill_import_client
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('SKILL.md', '# Demo')
        link = zipfile.ZipInfo('references/link')
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, '/etc/passwd')
    result = client.post('/api/skills/import', headers={'X-Skill-Request': '1'},
                         data={'file': (io.BytesIO(buf.getvalue()), 'demo.zip')})
    assert result.status_code == 400
    assert '符号链接' in result.json['message']
    assert list(store.staging.iterdir()) == []
