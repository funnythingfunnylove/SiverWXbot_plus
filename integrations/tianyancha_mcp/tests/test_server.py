import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location('tyc_server', BASE / 'server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BridgeTests(unittest.TestCase):
    def test_roundtrip_and_stale_results(self):
        bridge = module.Bridge('x' * 40, timeout=2)
        bridge.poll()
        output = []
        url = 'https://www.tianyancha.com/company/123'
        thread = threading.Thread(target=lambda: output.append(bridge.query('get_company', url)))
        thread.start()
        for _ in range(100):
            job = bridge.poll()
            if job: break
            time.sleep(.005)
        self.assertIsNotNone(job)
        self.assertIsNone(bridge.poll())
        self.assertFalse(bridge.complete('wrong-id', {}))
        self.assertTrue(bridge.complete(job['id'], {'source': {'url': url}, 'data': {}}))
        thread.join(2)
        self.assertEqual(output[0]['source']['url'], url)
        self.assertFalse(bridge.complete(job['id'], {}))

    def test_disconnected_and_timeout(self):
        bridge = module.Bridge('x' * 40, timeout=.01)
        with self.assertRaisesRegex(RuntimeError, 'BROWSER_DISCONNECTED'):
            bridge.query('get_company', 'url')
        bridge.poll()
        with self.assertRaisesRegex(RuntimeError, 'UPSTREAM_TIMEOUT'):
            bridge.query('get_company', 'url')
        self.assertIsNone(bridge.pending)

    def test_bridge_rejects_web_origin_and_bad_token(self):
        bridge = module.Bridge('x' * 40)
        server = ThreadingHTTPServer(('127.0.0.1', 0), module.handler_for(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/job'
            for headers in ({}, {'Authorization': 'Bearer ' + bridge.token, 'Origin': 'https://example.com'}):
                with self.assertRaises(HTTPError) as ctx: urlopen(Request(url, headers=headers))
                self.assertEqual(ctx.exception.code, 403)
            with urlopen(Request(url, headers={'Authorization': 'Bearer ' + bridge.token})) as response:
                self.assertEqual(json.load(response), {'job': None})
        finally:
            server.shutdown()
            server.server_close()

class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_client(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async with stdio_client(StdioServerParameters(command=sys.executable,
                args=[str(BASE / 'server.py'), '--bridge-port', '0'])) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual({t.name for t in tools.tools}, {'tyc_get_access_status', 'search_companies', 'get_company_basic_profile', 'get_company_capabilities'})
                status = await session.call_tool('tyc_get_access_status', {})
                self.assertFalse(status.isError)
                self.assertFalse(status.structuredContent['browser_connected'])
                invalid = await session.call_tool('get_company_basic_profile', {'company_id': '../evil'})
                self.assertTrue(invalid.isError)
                disconnected = await session.call_tool('get_company_basic_profile', {'company_id': '123'})
                self.assertTrue(disconnected.isError)

if __name__ == '__main__': unittest.main()
