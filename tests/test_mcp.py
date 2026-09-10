import asyncio
import json
from contextlib import asynccontextmanager
from functools import wraps
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, session
from mcp.types import CallToolResult, TextContent, Tool, ListToolsResult
from openai.types.chat import ChatCompletionMessage

from mcp_config import permits
from mcp_manager import MCPManager, MCPError, discover_tools, format_result, safe_error, tool_name
from mcp_routes import register_mcp_routes


CONTEXT = {"chat": "Alice", "sender": "Alice", "is_group": False}


def response(text=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=ChatCompletionMessage(role="assistant", content=text, tool_calls=calls))])


def call(alias, args, identifier="call_1"):
    return {"id": identifier, "type": "function", "function": {"name": alias, "arguments": json.dumps(args)}}


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
    assert not permits(configured, {"chat": "Project", "is_group": True, "sender": "Mallory"})
    assert permits(configured, {"chat": "Project", "is_group": True, "sender": "Alice"})
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
        outputs = [m for m in kwargs["messages"] if m["role"] == "tool"]
        assert len(outputs) == 2
        assert "5" in outputs[-1]["content"]
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
        output = json.loads(kwargs["messages"][-1]["content"])
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
        assert all(json.loads(m["content"])["is_error"] for m in kwargs["messages"] if m["role"] == "tool")
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
