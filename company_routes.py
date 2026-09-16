"""Panel enterprise lookup and authenticated Chrome bridge, no Windows imports."""
from functools import wraps
from io import BytesIO
from pathlib import Path
import re
import secrets
import time
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

from flask import jsonify, make_response, request, send_file
from integrations.tianyancha_mcp.bridge import Bridge

ERRORS = {
    'BROWSER_DISCONNECTED': ('浏览器未连接，请先在 Chrome 扩展中配对连接', 503),
    'BUSY': ('已有查询正在进行，请稍后重试', 409),
    'UPSTREAM_TIMEOUT': ('查询超时，请检查天眼查工作标签页，然后重新查询', 504),
    'HUMAN_VERIFICATION_REQUIRED': ('天眼查要求人工验证，请在 Chrome 完成后重试', 409),
    'AUTH_REQUIRED': ('请在已连接的 Chrome 中登录天眼查后重试', 409),
    'RATE_LIMITED': ('天眼查访问频繁，请稍后再试', 429),
    'PERMISSION_DENIED': ('当前天眼查账号无权查看这项信息', 403),
    'SOURCE_CHANGED': ('未能识别页面内容，请检查工作标签页或更新扩展', 502),
}


def register_company_routes(app, login_required, extension_dir=None, bridge=None):
    bridge = bridge or Bridge(secrets.token_urlsafe(32))
    app.extensions['company_bridge'] = bridge
    extension_dir = Path(extension_dir or Path(__file__).parent / 'integrations/tianyancha_mcp/extension')

    def no_store(response):
        response = make_response(response)
        response.headers['Cache-Control'] = 'no-store'
        return response

    def admin(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if request.method == 'POST' and (
                request.headers.get('X-Company-Request') != '1' or not request.is_json
            ):
                return no_store((jsonify(status='error', message='请从管理面板操作'), 403))
            if request.content_length and request.content_length > 8192:
                return no_store((jsonify(status='error', message='请求过大'), 413))
            try:
                return no_store(fn(*args, **kwargs))
            except ValueError as exc:
                return no_store((jsonify(status='error', message=str(exc)), 400))
            except RuntimeError as exc:
                code = str(exc).split(':', 1)[0]
                message, status = ERRORS.get(code, ('浏览器查询失败，请检查工作标签页后重试', 502))
                return no_store((jsonify(status='error', code=code if code in ERRORS else 'QUERY_FAILED', message=message), status))
        return login_required(wrapped)

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('需要 JSON 对象')
        return data

    @app.get('/api/company/status')
    @admin
    def company_status():
        with bridge.lock:
            connected = time.monotonic() - bridge.last_seen < 10
            busy = bridge.pending is not None
        return jsonify(status='success', connected=connected, busy=busy,
                       website_login='unknown_until_query', capabilities=['company_search', 'company_detail'])

    @app.post('/api/company/pair')
    @admin
    def company_pair():
        if not bridge.serial.acquire(blocking=False):
            raise RuntimeError('BUSY')
        try:
            with bridge.lock:
                bridge.token = secrets.token_urlsafe(32)
                bridge.last_seen = 0
                token = bridge.token
        finally:
            bridge.serial.release()
        return jsonify(status='success', token=token)

    @app.post('/api/company/disconnect')
    @admin
    def company_disconnect():
        if not bridge.serial.acquire(blocking=False):
            raise RuntimeError('BUSY')
        try:
            with bridge.lock:
                bridge.token = secrets.token_urlsafe(32)
                bridge.last_seen = 0
        finally:
            bridge.serial.release()
        return jsonify(status='success')

    @app.get('/api/company/extension')
    @admin
    def company_extension():
        files = ['manifest.json', 'popup.html', 'bridge.html', 'bridge.js', 'extract.js']
        if not all((extension_dir / name).is_file() for name in files):
            return jsonify(status='error', message='扩展资源缺失，请部署完整源码或重新打包'), 503
        output = BytesIO()
        with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
            for name in files:
                archive.write(extension_dir / name, 'tianyancha-bridge/' + name)
        output.seek(0)
        return send_file(output, mimetype='application/zip', as_attachment=True,
                         download_name='tianyancha-bridge.zip')

    @app.post('/api/company/search')
    @admin
    def company_search():
        data = body()
        keyword = data.get('keyword')
        if not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 100:
            raise ValueError('请输入 1–100 字的企业名称或关键词')
        result = bridge.query('search_companies',
                              'https://www.tianyancha.com/search?key=' + quote(keyword.strip(), safe=''), limit=20)
        return jsonify(status='success', result=result)

    @app.post('/api/company/detail')
    @admin
    def company_detail():
        company_id = body().get('company_id')
        if not isinstance(company_id, str) or not re.fullmatch(r'[0-9]{1,20}', company_id):
            raise ValueError('企业 ID 格式不正确，请从搜索结果选择企业')
        result = bridge.query('get_company', 'https://www.tianyancha.com/company/' + company_id,
                              company_id=company_id)
        return jsonify(status='success', result=result)

    def bridge_auth(fn):
        @wraps(fn)
        def wrapped():
            origin = request.headers.get('Origin', '')
            auth = request.headers.get('Authorization', '')
            with bridge.lock:
                authorized = secrets.compare_digest(auth, 'Bearer ' + bridge.token)
            if not authorized or (origin and not re.fullmatch(r'chrome-extension://[a-p]{32}', origin)):
                return no_store((jsonify(error='Forbidden'), 403))
            if request.content_length and request.content_length > 262144:
                return no_store((jsonify(error='Too large'), 413))
            return no_store(fn())
        return wrapped

    @app.get('/api/company/bridge/job')
    @bridge_auth
    def company_bridge_job():
        return jsonify(job=bridge.poll())

    @app.post('/api/company/bridge/result')
    @bridge_auth
    def company_bridge_result():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('id'), str) or not isinstance(data.get('result'), dict):
            return jsonify(error='Invalid result'), 400
        accepted = bridge.complete(data['id'], data['result'])
        return jsonify(accepted=accepted), 200 if accepted else 409

    return bridge
