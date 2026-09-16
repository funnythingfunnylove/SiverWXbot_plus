"""Panel API tests, runnable on macOS/Linux without importing the Windows bot."""
from functools import wraps
from io import BytesIO
from pathlib import Path
import threading
import time
import unittest
from zipfile import ZipFile

from flask import Flask, jsonify, session
from company_routes import register_company_routes
from integrations.tianyancha_mcp.bridge import Bridge

ROOT = Path(__file__).resolve().parents[3]

class PanelTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder=str(ROOT / 'templates'))
        self.app.secret_key = 'test-only'
        def login_required(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not session.get('logged_in'):
                    return jsonify(status='error', message='未登录'), 401
                return fn(*args, **kwargs)
            return wrapped
        self.bridge = Bridge('x' * 40, timeout=2)
        register_company_routes(self.app, login_required, bridge=self.bridge)
        self.client = self.app.test_client()
        self.headers = {'X-Company-Request': '1'}

    def login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def test_login_csrf_payload_and_validation(self):
        self.assertEqual(self.client.get('/api/company/status').status_code, 401)
        self.assertEqual(self.client.get('/api/company/extension').status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/company/pair', json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/company/search', json=[], headers=self.headers).status_code, 400)
        for body in ({'keyword': ''}, {'keyword': 42}, {'keyword': 'a' * 101}):
            self.assertEqual(self.client.post('/api/company/search', json=body, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/company/detail', json={'company_id':'../1'}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/company/search', json={'keyword':'测试'}, headers=self.headers).status_code, 503)

    def test_pair_rotate_revoke_and_origin(self):
        self.login()
        result = self.client.post('/api/company/pair', json={}, headers=self.headers)
        self.assertEqual(result.headers['Cache-Control'], 'no-store')
        token = result.json['token']
        auth = {'Authorization': 'Bearer ' + token}
        self.assertEqual(self.client.get('/api/company/bridge/job', headers=auth).status_code, 200)
        self.assertTrue(self.client.get('/api/company/status').json['connected'])
        self.assertNotIn(token, self.client.get('/api/company/status').text)
        self.assertEqual(self.client.get('/api/company/bridge/job', headers={**auth, 'Origin':'https://attacker.test'}).status_code, 403)
        self.assertEqual(self.client.get('/api/company/bridge/job', headers={**auth, 'Origin':'chrome-extension://'+'a'*32}).status_code, 200)
        self.client.post('/api/company/disconnect', json={}, headers=self.headers)
        self.assertEqual(self.client.get('/api/company/bridge/job', headers=auth).status_code, 403)
        self.assertFalse(self.client.get('/api/company/status').json['connected'])

    def test_search_bridge_roundtrip_and_busy(self):
        self.login()
        token = self.bridge.token
        auth = {'Authorization': 'Bearer ' + token}
        self.client.get('/api/company/bridge/job', headers=auth)
        output = []
        # A separate authenticated request waits while the bridge supplies the result.
        def query():
            with self.app.test_client() as c:
                with c.session_transaction() as s: s['logged_in'] = True
                output.append(c.post('/api/company/search', json={'keyword':'企业 & 公司'}, headers=self.headers))
        thread = threading.Thread(target=query)
        thread.start()
        for _ in range(100):
            job = self.client.get('/api/company/bridge/job', headers=auth).json['job']
            if job: break
            time.sleep(.005)
        self.assertIsNotNone(job)
        self.assertIn('%26', job['url'])
        self.assertEqual(self.client.post('/api/company/pair', json={}, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post('/api/company/detail', json={'company_id':'123'}, headers=self.headers).status_code, 409)
        result = {'status':'partial', 'source':{'url':job['url']}, 'data':{'candidates':[]}}
        response = self.client.post('/api/company/bridge/result', json={'id':job['id'],'result':result}, headers=auth)
        self.assertEqual(response.status_code, 200)
        thread.join(3)
        self.assertEqual(output[0].status_code, 200)
        self.assertEqual(output[0].json['result'], result)
        self.assertEqual(self.client.post('/api/company/bridge/result', json={'id':job['id'],'result':result}, headers=auth).status_code, 409)

    def test_extension_download_and_template(self):
        self.login()
        response = self.client.get('/api/company/extension')
        self.assertEqual(response.status_code, 200)
        with ZipFile(BytesIO(response.data)) as archive:
            self.assertEqual(len(archive.namelist()), 5)
            self.assertIn('tianyancha-bridge/manifest.json', archive.namelist())
            self.assertFalse(any('token' in name for name in archive.namelist()))
        with self.app.test_request_context():
            from flask import render_template
            html = render_template('company_panel.html')
            self.assertIn('tab-company', html)
            self.assertIn('/api/company/extension', html)

if __name__ == '__main__': unittest.main()
