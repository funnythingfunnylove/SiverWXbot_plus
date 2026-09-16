import json
import io
import zipfile
from functools import wraps
import pytest
from flask import Flask, session, jsonify
from skill_manager import SkillStore, register_skill_routes
from mcp_config import MCPConfigStore, TYC_URL


def test_official_key_fixed_endpoint_preserved_redacted(tmp_path):
    store=MCPConfigStore(str(tmp_path/'mcp.json'))
    ident=store.save({'kind':'tianyancha','name':'天眼查','key':'test-secret','url':'https://wrong.test'})
    saved=store.read()['servers'][0]
    assert saved['url']==TYC_URL
    assert saved['headers']=={'Authorization':'test-secret'}
    public=store.public()['servers'][0]
    assert 'test-secret' not in json.dumps(public)
    store.save(public)
    assert store.read()['servers'][0]['headers']==saved['headers']
    with pytest.raises(ValueError): store.save({'kind':'tianyancha','name':'x','key':'bad\nkey'})


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
