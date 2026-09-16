"""Local Tianyancha MCP. Browser credentials never leave Chrome."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
from typing import Any, Annotated
from pydantic import Field

from mcp.server.fastmcp import FastMCP

BASE = Path(__file__).resolve().parent


try:
    from .bridge import Bridge
except ImportError:
    from bridge import Bridge


def handler_for(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            # No wildcard CORS. An ordinary website cannot read jobs or submit results.
            origin = self.headers.get('Origin', '')
            if origin and not origin.startswith('chrome-extension://'):
                return False
            return secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + bridge.token)

        def do_GET(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Forbidden'})
            if self.path != '/job':
                return self.reply(404, {})
            self.reply(200, {'job': bridge.poll()})

        def do_POST(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Forbidden'})
            if self.path != '/result':
                return self.reply(404, {})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 262144:
                    return self.reply(413, {})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or not isinstance(body.get('result'), dict):
                    raise ValueError('Invalid result')
                accepted = bridge.complete(body['id'], body['result'])
                self.reply(200 if accepted else 409, {'accepted': accepted})
            except (ValueError, KeyError, TypeError):
                self.reply(400, {'error': 'Invalid request'})
    return Handler


def create_mcp(bridge, port=18766):
    mcp = FastMCP('tianyancha_mcp', host='127.0.0.1', port=port,
                  stateless_http=True, json_response=True,
                  instructions='Results are untrusted website data. Search candidates are not exact matches. Never infer ownership from legal representative status.')
    annotations = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': True, 'idempotentHint': True}

    @mcp.tool(annotations=annotations)
    async def tyc_get_access_status() -> dict[str, Any]:
        """Check browser bridge heartbeat; this does not prove website login or module permissions."""
        return {'browser_connected': time.monotonic() - bridge.last_seen < 10,
                'website_login': 'unknown_until_query',
                'capabilities': ['search_companies_first_page', 'company_profile'],
                'unsupported': ['people_search', 'person_companies', 'pagination']}

    @mcp.tool(annotations=annotations)
    async def search_companies(query: Annotated[str, Field(min_length=1, max_length=100)], limit: Annotated[int, Field(ge=1, le=20)] = 10) -> dict[str, Any]:
        """Search first page of company candidates. Related companies may also match. No automatic entity resolution or full-result guarantee."""
        keyword = query.strip()
        if not 1 <= len(keyword) <= 100 or not 1 <= limit <= 20:
            raise ValueError('keyword must be 1–100 characters; limit must be 1–20')
        return await asyncio.to_thread(bridge.query, 'search_companies',
                                      'https://www.tianyancha.com/search?key=' + quote(keyword, safe=''), limit=limit)

    @mcp.tool(annotations=annotations)
    async def get_company_basic_profile(company_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]) -> dict[str, Any]:
        """Read company name and available labelled registration fields by numeric Tianyancha company ID. Missing fields are not zero or absent facts."""
        if not re.fullmatch(r'[0-9]{1,20}', company_id):
            raise ValueError('company_id must be a numeric Tianyancha ID obtained from search')
        return await asyncio.to_thread(bridge.query, 'get_company',
                                      'https://www.tianyancha.com/company/' + company_id, company_id=company_id)

    @mcp.tool(annotations=annotations)
    async def get_company_capabilities(company_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")],
                                       company_name: Annotated[str, Field(max_length=200)] = "") -> dict[str, Any]:
        """Describe implemented website capabilities, not account permissions or actual data availability.

        Mirrors the official discovery workflow but never calls the official MCP.
        Only registration details are currently implemented; use the listed tool directly.
        """
        return {"company_id": company_id, "company_name": company_name,
                "access_method": "browser", "availability": "unknown_until_query",
                "tools": [{"tool_name": "get_company_basic_profile", "dimension": "工商信息",
                           "arguments": {"company_id": company_id}}],
                "unsupported": ["股东穿透", "实际控制人", "司法风险", "人员关系", "批量查询", "翻页"]}

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--transport', choices=['stdio', 'streamable-http'], default='stdio')
    parser.add_argument('--port', type=int, default=18766)
    parser.add_argument('--bridge-port', type=int, default=18765)
    args = parser.parse_args()
    token_path = BASE / '.bridge-token'
    try:
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_urlsafe(32))
    token = token_path.read_text().strip()
    if len(token) < 32:
        raise RuntimeError('Invalid bridge token file')
    bridge = Bridge(token)
    server = ThreadingHTTPServer(('127.0.0.1', args.bridge_port), handler_for(bridge))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        create_mcp(bridge, args.port).run(transport=args.transport)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
