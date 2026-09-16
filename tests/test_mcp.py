import asyncio
import json
from contextlib import asynccontextmanager
from functools import wraps
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, session
from mcp.types import CallToolResult, TextContent, Tool, ListToolsResult
from openai.types.responses import ResponseFunctionToolCall

from mcp_config import permits
from mcp_manager import MCPManager, MCPError, discover_tools, format_result, safe_error, tool_name
from mcp_routes import register_mcp_routes


CONTEXT = {"chat": "Alice", "sender": "Alice", "is_group": False}


def response(text=None, calls=None):
    return SimpleNamespace(status="completed", output=[ResponseFunctionToolCall(**c) for c in calls] if calls else [SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])])


def call(alias, args, identifier="call_1"):
    return {"id": "fc_" + identifier, "call_id": identifier, "type": "function_call", "name": alias, "arguments": json.dumps(args)}


def test_config_secret_preservation_and_atomic_update(store):
    assert not store.read()["enabled"]
    ident = store.save({"name": "service", "url": "https://example.org/mcp", "headers": {"Authorization": "Bearer secret"}})
    public = store.public()
    assert "secret" not in json.dumps(public)
    assert public["servers"][0]["has_headers"]
    server = public["servers"][0]
    store.save({**server, "name": "renamed"})
    assert store.read()["servers"][0]["headers"]["Authorization"] == "Bearer secret"
    with pytest.raises(ValueError):
        store.save({**server, "url": "file:///etc/passwd"})
    assert store.read()["servers"][0]["name"] == "renamed"
    store.save({**server, "headers": {}})
    assert not store.public()["servers"][0]["has_headers"]
    store.delete(ident)
    assert store.read()["servers"] == []


@pytest.mark.parametrize("change", [
    {"enabled": "false"}, {"allowed_tools": "all"}, {"allowed_chats": [""]}, {"timeout": 0},
    {"headers": {"Authorization": "x\r\ny"}}, {"headers": {"Host": "evil"}},
    {"url": "https://user:pass@example.org/mcp"}, {"url": "https://example.org:wrong/mcp"},
])
def test_invalid_config_rejected(store, change):
    with pytest.raises(ValueError):
        store.save({"name": "test", "url": "https://example.org/mcp", **change})


def test_permission_defaults_and_groups(configured):
    assert permits(configured, CONTEXT)
    assert not permits(configured, {**CONTEXT, "chat": "Mallory"})
    assert permits(configured, {"chat": "Project", "is_group": True, "sender": "Mallory", "mentioned": True})
    assert not permits(configured, {"chat": "Project", "is_group": True, "sender": "Alice", "mentioned": False})
    assert not permits(configured, {"chat": "Other", "is_group": True, "sender": "Alice", "mentioned": True})
    assert permits(configured, {"chat": "Project", "is_group": True, "sender": "Alice", "mentioned": True})
    assert not permits({**configured, "enabled": False}, CONTEXT)


def test_real_http_discovery_and_auth(manager, configured, live_mcp):
    tools = manager.test(configured)
    assert {tool["name"] for tool in tools} == {"add", "fail"}
    assert next(t for t in tools if t["name"] == "add")["input_schema"]["required"] == ["a", "b"]
    assert live_mcp.calls == []  # Connection testing must never execute tools.
    assert any(h.get(b"authorization") == b"Bearer fixture-only" for h in live_mcp.headers)


def run_conversation(manager, create):
    config, servers = manager.eligible(CONTEXT)
    return manager.submit(lambda: manager.converse(create, "fixture-model", [{"role": "user", "content": "2+3?"}], CONTEXT, config, servers), 10)


def test_real_tool_loop_and_duplicate_suppression(manager, configured, live_mcp):
    requests = []
    alias = tool_name(configured["id"], "add")
    async def create(**kwargs):
        requests.append(kwargs)
        if len(requests) <= 2:
            return response(calls=[call(alias, {"a": 2, "b": 3}, f"call_{len(requests)}")])
        outputs = [m for m in kwargs["input"] if m.get("type") == "function_call_output"]
        assert len(outputs) == 2
        assert "5" in outputs[-1]["output"]
        return response("结果是 5")
    assert run_conversation(manager, create) == "结果是 5"
    assert live_mcp.calls == [(2, 3)]
    assert "fixture-only" not in json.dumps(requests, ensure_ascii=False)


@pytest.mark.parametrize("kind", ["unlisted", "invalid", "revoked"])
def test_unauthorized_or_invalid_tool_never_executes(manager, store, configured, live_mcp, kind):
    index = 0
    async def create(**kwargs):
        nonlocal index
        index += 1
        if index == 1:
            if kind == "revoked":
                store.settings({"enabled": False})
            return response(calls=[call("unlisted" if kind == "unlisted" else tool_name(configured["id"], "add"), {"a": "bad" if kind == "invalid" else 2, "b": 3})])
        output = json.loads(kwargs["input"][-1]["output"])
        assert output["is_error"]
        return response("不能执行")
    assert run_conversation(manager, create) == "不能执行"
    assert live_mcp.calls == []


def test_unrelated_chat_uses_ordinary_model(manager, configured):
    assert manager.reply(None, "model", [], {**CONTEXT, "chat": "someone else"}) is None


def test_tool_error_blocks_further_server_calls(manager, configured, live_mcp):
    index = 0
    async def create(**kwargs):
        nonlocal index
        index += 1
        if index == 1:
            return response(calls=[call(tool_name(configured["id"], "fail"), {}), call(tool_name(configured["id"], "add"), {"a": 2, "b": 3}, "call_2")])
        assert all(json.loads(m["output"])["is_error"] for m in kwargs["input"] if m.get("type") == "function_call_output")
        return response("工具执行失败，未执行后续操作")
    assert "失败" in run_conversation(manager, create)
    assert live_mcp.calls == []


def test_round_limit_requires_final_text(manager, store, configured, live_mcp):
    store.settings({"enabled": True, "max_rounds": 1})
    choices = []
    async def create(**kwargs):
        choices.append(kwargs["tool_choice"])
        return response(calls=[call(tool_name(configured["id"], "add"), {"a": 2, "b": 3})])
    assert "上限" in run_conversation(manager, create)
    assert choices == ["auto", "none"]
    assert live_mcp.calls == [(2, 3)]


def test_result_size_and_nontext_are_explicit():
    from mcp.types import ImageContent
    result = CallToolResult(content=[TextContent(type="text", text="x" * 20000), ImageContent(type="image", data="AA==", mimeType="image/png")])
    formatted = json.loads(format_result(result))
    assert formatted["truncated"] and len(formatted["content"]) <= 12000
    assert "AA==" not in json.dumps(formatted)


def test_timeout_closes_session_same_task(store):
    events = []
    @asynccontextmanager
    async def connector(server):
        task = asyncio.current_task()
        events.append("open")
        try:
            yield SimpleNamespace()
        finally:
            assert asyncio.current_task() is task
            events.append("close")
    manager = MCPManager(store, connector=connector)
    async def work():
        async with connector({}):
            await asyncio.sleep(10)
    try:
        with pytest.raises(TimeoutError):
            manager.submit(work, .05)
        assert events == ["open", "close"]
    finally:
        manager.close()


def test_pagination_and_name_collisions():
    class Paged:
        async def list_tools(self, cursor=None):
            return ListToolsResult(tools=[Tool(name="a" if cursor is None else "b", inputSchema={"type": "object"})], nextCursor="next" if cursor is None else None)
    assert [t.name for t in asyncio.run(discover_tools(Paged()))] == ["a", "b"]
    assert tool_name("one", "lookup") != tool_name("two", "lookup")


def test_error_redaction():
    import httpx
    error = httpx.HTTPStatusError("Bearer secret", request=httpx.Request("GET", "https://example.org/?secret=123"), response=httpx.Response(401))
    assert "401" in safe_error(error)
    assert "secret" not in safe_error(error)


def test_discovery_403_reports_mcp_stage(store):
    import httpx
    @asynccontextmanager
    async def denied(server):
        raise httpx.HTTPStatusError('private response', request=httpx.Request('POST', 'https://example.org/mcp'), response=httpx.Response(403))
        yield
    manager = MCPManager(store, connector=denied)
    try:
        with pytest.raises(MCPError, match='MCP 连接/工具发现阶段.*403') as caught:
            manager.test({'timeout': 5})
        assert 'private response' not in str(caught.value)
    finally:
        manager.close()


def test_panel_routes_auth_crud_test_and_csrf(manager, live_mcp):
    app = Flask(__name__)
    app.secret_key = "fixture-only"
    def login_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("logged_in"):
                return jsonify(status="error"), 401
            return fn(*args, **kwargs)
        return wrapper
    register_mcp_routes(app, login_required, manager)
    client = app.test_client()
    assert client.get("/api/mcp/config").status_code == 401
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    data = {"name": "test", "url": live_mcp.url, "headers": {"Authorization": "Bearer secret"}}
    assert client.post("/api/mcp/servers", json=data).status_code == 403
    headers = {"X-MCP-Request": "1"}
    result = client.post("/api/mcp/servers", json=data, headers=headers)
    assert result.status_code == 200
    ident = result.json["id"]
    assert "secret" not in client.get("/api/mcp/config").get_data(as_text=True)
    result = client.post("/api/mcp/test", json=data, headers=headers)
    assert result.status_code == 200
    assert len(result.json["tools"]) == 2 and live_mcp.calls == []
    assert client.delete(f"/api/mcp/servers/{ident}", headers=headers).status_code == 200
    assert client.get("/api/mcp/config").json["config"]["servers"] == []


def person(chat="Alice", key="fixture-alice", **extra):
    return dict(kind="hrzh_person", name="项目管理", chat=chat, key=key,
                enabled=True, allowed_tools=["add"], **extra)


def test_person_config_isolated_and_redacted(store):
    from mcp_config import HRZH_URL
    ident = store.save(person(url="https://ignored.example", allowed_groups=["Project"]))
    saved = store.read()["servers"][0]
    assert saved["url"] == HRZH_URL and saved["allowed_groups"] == []
    assert saved["allowed_chats"] == ["Alice"]
    assert "fixture-alice" not in json.dumps(store.public())
    update = {**store.public()["servers"][0], "chat": "Alice"}
    store.save(update)
    assert store.read()["servers"][0]["headers"] == saved["headers"]
    store.save({**update, "key": "fixture-new"})
    assert store.read()["servers"][0]["headers"] == {"Authorization": "Bearer fixture-new"}
    with pytest.raises(ValueError, match="已配置"):
        store.save(person())
    with pytest.raises(ValueError):
        store.save(person(key="bad\nkey"))
    with pytest.raises(ValueError):
        store.save({**update, "kind": "service"})
    assert store.read()["servers"][0]["id"] == ident


@pytest.mark.parametrize("state", ["enabled", "disabled", "empty"])
def test_person_prevents_shared_private_fallback(store, manager, state):
    from mcp_config import HRZH_URL
    shared = store.save(dict(name="shared", url=HRZH_URL, enabled=True,
                             allowed_chats=["Alice", "Bob"], allowed_groups=["Project"],
                             allowed_tools=["add"], headers={"Authorization": "Bearer shared"}))
    data = person()
    if state == "disabled":
        data["enabled"] = False
    if state == "empty":
        data["allowed_tools"] = []
    personal = store.save(data)
    store.settings({"enabled": True})
    assert [s["id"] for s in manager.eligible(CONTEXT)[1]] == ([personal] if state == "enabled" else [])
    assert [s["id"] for s in manager.eligible({**CONTEXT, "chat": "Bob"})[1]] == [shared]
    assert [s["id"] for s in manager.eligible(dict(chat="Project", is_group=True, mentioned=True))[1]] == [shared]


@pytest.mark.parametrize("identity", [[], {}, {"person_id": "1"}, {"person_id": None, "tools": ["add"]}])
def test_person_invalid_identity_fails_closed(identity):
    from mcp_manager import personal_tools
    async def listing(**kwargs):
        return ListToolsResult(tools=[Tool(name="add", inputSchema={"type": "object"})])
    async def calling(*args):
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(identity))])
    with pytest.raises(MCPError):
        asyncio.run(personal_tools(SimpleNamespace(list_tools=listing, call_tool=calling), {"kind": "hrzh_person"}))


def test_person_keys_and_permissions_in_conversation(store):
    events = []
    @asynccontextmanager
    async def connector(server):
        key = server["headers"]["Authorization"]
        async def listing(**kwargs):
            return ListToolsResult(tools=[Tool(name=n, inputSchema={"type": "object"}) for n in ["add", "private"]])
        async def calling(name, arguments):
            events.append((key, name))
            if name == "weekly_identity":
                return CallToolResult(content=[], structuredContent={
                    "key_id": "not-public", "person_id": key[-1], "category": "staff",
                    "access": "read", "tools": ["add", "not-discovered"] if key.endswith("A") else ["private"]})
            return CallToolResult(content=[TextContent(type="text", text="ok")])
        yield SimpleNamespace(list_tools=listing, call_tool=calling)
    manager = MCPManager(store, connector=connector)
    try:
        for chat, key in [("Alice", "fixture-A"), ("Bob", "fixture-B")]:
            data = person(chat, key)
            data["allowed_tools"] = ["add", "private"]
            store.save(data)
        store.settings({"enabled": True})
        for chat, expected in [("Alice", "add"), ("Bob", "private")]:
            context = {**CONTEXT, "chat": chat}
            config, servers = manager.eligible(context)
            checked = manager.test_person(servers[0])
            assert [t["name"] for t in checked["tools"]] == [expected]
            assert "key_id" not in json.dumps(checked)
            count = 0
            async def create(**kwargs):
                nonlocal count
                count += 1
                assert [t["name"] for t in kwargs["tools"]] == [tool_name(servers[0]["id"], expected)]
                assert "fixture-" not in json.dumps(kwargs)
                return response(calls=[call(tool_name(servers[0]["id"], expected), {})]) if count == 1 else response("完成")
            assert manager.submit(lambda: manager.converse(create, "model", [], context, config, servers), 10) == "完成"
        assert ("Bearer fixture-A", "private") not in events
        assert ("Bearer fixture-B", "add") not in events
        assert ("Bearer fixture-A", "add") in events
        assert ("Bearer fixture-B", "private") in events
    finally:
        manager.close()


def test_person_real_http_identity_and_route(store):
    from conftest import serve
    from mcp.server.fastmcp import FastMCP, Context
    from mcp_manager import connect_server
    service = FastMCP("personal fixture", stateless_http=True, json_response=True)
    seen = []
    @service.tool()
    def weekly_identity(ctx: Context) -> dict:
        auth = ctx.request_context.request.headers.get("authorization")
        seen.append(auth)
        return {"person_id": auth[-1], "access": "read", "category": "staff",
                "key_id": "hidden-fixture-id", "tools": ["add"] if auth.endswith("A") else []}
    @service.tool()
    def add() -> int:
        return 3
    server, thread, sock, port = serve(service.streamable_http_app())
    @asynccontextmanager
    async def redirect_fixture(config):
        # Only tests redirect the fixed production endpoint; retain actual headers/SDK.
        async with connect_server({**config, "url": f"http://127.0.0.1:{port}/mcp"}) as session:
            yield session
    manager = MCPManager(store, connector=redirect_fixture)
    app = Flask(__name__)
    register_mcp_routes(app, lambda f: f, manager)
    client = app.test_client()
    try:
        for user in ("A", "B"):
            data = person(user, "fixture-" + user)
            result = client.post("/api/mcp/test", json=data, headers={"X-MCP-Request": "1"})
            assert result.status_code == 200, result.json
            assert result.json["identity"]["person_id"] == user
            assert [t["name"] for t in result.json["tools"]] == (["add"] if user == "A" else [])
            assert "fixture-" not in result.text and "key_id" not in result.text
            assert client.post("/api/mcp/servers", json=data, headers={"X-MCP-Request": "1"}).status_code == 200
        assert seen == ["Bearer fixture-A", "Bearer fixture-B"]
        assert "fixture-" not in client.get("/api/mcp/config").text
    finally:
        manager.close()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()



# Exercise the actual HTTP MCP transport with a simulated browser worker.
import asyncio
import threading
import time

from conftest import serve
from integrations.tianyancha_mcp.bridge import Bridge
from integrations.tianyancha_mcp.server import create_mcp
from mcp_manager import connect_server


def test_http_company_roundtrip():
    bridge = Bridge('fixture-token', timeout=2)
    app = create_mcp(bridge).streamable_http_app()
    server, thread, sock, port = serve(app)
    done = threading.Event()
    jobs = []

    def browser():
        while not done.is_set():
            job = bridge.poll()
            if job:
                jobs.append(job)
                bridge.complete(job['id'], {'status': 'ok', 'data': {'company_id': job['company_id'],
                    'credit_code': 'fixture-credit'}, 'source': {'url': job['url'], 'access_method': 'browser'}})
            done.wait(.005)

    worker = threading.Thread(target=browser)
    worker.start()

    async def run():
        async with connect_server({'url': f'http://127.0.0.1:{port}/mcp', 'headers': {}, 'timeout': 5}) as session:
            listed = await session.list_tools()
            assert all(t.annotations.readOnlyHint for t in listed.tools)
            assert all(t.outputSchema for t in listed.tools)
            capabilities = await session.call_tool('get_company_capabilities', {'company_id': '123'})
            assert capabilities.structuredContent['tools'][0]['tool_name'] == 'get_company_basic_profile'
            assert jobs == []  # Capability discovery does not browse or claim account access.
            result = await session.call_tool('get_company_basic_profile', {'company_id': '123'})
            assert not result.isError
            assert result.structuredContent['data']['credit_code'] == 'fixture-credit'
            assert jobs[0]['url'] == 'https://www.tianyancha.com/company/123'
            invalid = await session.call_tool('search_companies', {'query': 'test', 'limit': 21})
            assert invalid.isError
            assert len(jobs) == 1

    try:
        asyncio.run(run())
    finally:
        done.set()
        worker.join(3)
        server.should_exit = True
        thread.join(5)
        sock.close()


def test_busy_and_wrong_source():
    bridge = Bridge('fixture-token', timeout=2)
    bridge.poll()
    failures = []

    def query():
        try:
            bridge.query('get_company', 'https://www.tianyancha.com/company/123')
        except RuntimeError as exc:
            failures.append(str(exc))

    worker = threading.Thread(target=query)
    worker.start()
    try:
        job = None
        for _ in range(200):
            job = bridge.poll()
            if job:
                break
            time.sleep(.005)
        assert job
        import pytest
        with pytest.raises(RuntimeError, match='BUSY'):
            bridge.query('get_company', 'https://www.tianyancha.com/company/456')
        bridge.complete(job['id'], {'source': {'url': 'https://www.tianyancha.com/company/456'}})
    finally:
        worker.join(3)
    assert failures and 'SOURCE_CHANGED' in failures[0]
