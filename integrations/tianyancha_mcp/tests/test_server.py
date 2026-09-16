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
                self.assertTrue({'get_company_guarantees', 'get_company_ownership_chain', 'get_company_section', 'get_company_capabilities', 'get_company_enforcements', 'get_company_financials'} <= {t.name for t in tools.tools})
                self.assertGreater(len(tools.tools), 30)
                status = await session.call_tool('tyc_get_access_status', {})
                self.assertFalse(status.isError)
                self.assertFalse(status.structuredContent['browser_connected'])
                invalid = await session.call_tool('get_company_basic_profile', {'company_id': '../evil'})
                self.assertTrue(invalid.isError)
                disconnected = await session.call_tool('get_company_basic_profile', {'company_id': '123'})
                self.assertTrue(disconnected.isError)


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_convenience_tools_route_only_to_website_sections(self):
        class RecordingBridge:
            last_seen = 0
            def __init__(self): self.calls=[]
            def query(self, operation, url, **kwargs):
                self.calls.append((operation, url, kwargs))
                return {'status':'partial', 'source': {'url':url}, 'tables': []}
        bridge=RecordingBridge()
        server=module.create_mcp(bridge)
        tools=await server.list_tools()
        self.assertTrue(all(t.outputSchema and t.annotations.readOnlyHint for t in tools))
        for name, label in module.TOOLS.items():
            await server.call_tool(name, {'company_id':'123'})
            operation,url,args=bridge.calls[-1]
            self.assertEqual(operation,'get_section')
            self.assertEqual(url,module.company_url('123',module.SECTIONS[label]['group']))
            self.assertEqual(args['section'],label)
        for group in module.GROUPS:
            await server.call_tool('get_company_capabilities',{'company_id':'123','group':group})
            self.assertEqual(bridge.calls[-1][0],'get_capabilities')
        for tool,args in [
            ('get_company_annual_report',{'company_id':'123','year':2025}),
            ('get_company_judicial_case_detail',{'company_id':'123','case_id':'a'*32}),
            ('get_person_companies',{'company_id':'123','person_id':'789'}),
        ]:
            await server.call_tool(tool,args)
            self.assertTrue(bridge.calls[-1][1].startswith('https://www.tianyancha.com/'))
        count=len(bridge.calls)
        for tool,args in [
            ('get_company_section',{'company_id':'123','section':'arbitrary URL'}),
            ('get_company_shareholders',{'company_id':'123','page':0}),
            ('get_company_bonds',{'company_id':'123','view':'身为出质人'}),
            ('get_company_judicial_case_detail',{'company_id':'123','case_id':'../x'}),
            ('get_person_companies',{'company_id':'123','person_id':'../x'}),
        ]:
            with self.assertRaises(Exception):
                await server.call_tool(tool,args)
        self.assertEqual(len(bridge.calls),count)

    async def test_ownership_edges_do_not_infer_controller(self):
        class OwnershipBridge:
            last_seen=0
            def query(self,*args,**kwargs):
                return {'status':'partial','tables':[{'headers':['股东名称','持股比例'],
                    'rows':[{'cells':['Corporate owner','100%'],'links':[{'company_id':'456','url':'https://www.tianyancha.com/company/456'}]}]}]}
        mcp=module.create_mcp(OwnershipBridge())
        _,data=await mcp.call_tool('get_company_ownership_chain',{'company_id':'123'})
        self.assertEqual(data['next_company_ids'],['456'])
        self.assertFalse(data['penetration_complete'])
        self.assertEqual(data['ownership_edges'][0]['holding_ratio_raw'],'100%')
        self.assertNotIn('actual_controller',data)


if __name__ == '__main__': unittest.main()
