import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from mcp_config import MCPConfigStore
from mcp_manager import MCPManager


@pytest.fixture(autouse=True)
def local_network_only(monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def store(tmp_path):
    return MCPConfigStore(str(tmp_path / "mcp.json"))


@pytest.fixture
def manager(store):
    instance = MCPManager(store)
    yield instance
    instance.close()


def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    return server, thread, sock, port


@pytest.fixture
def live_mcp():
    state = SimpleNamespace(calls=[], headers=[])
    mcp = FastMCP("Local MCP integration test", stateless_http=True, json_response=True)

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        state.calls.append((a, b))
        return a + b

    @mcp.tool()
    def fail() -> str:
        """Return a tool error."""
        raise RuntimeError("intentional tool failure")

    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            state.headers.append(dict(scope["headers"]))
        await inner(scope, receive, send)

    server, thread, sock, port = serve(app)
    state.url = f"http://127.0.0.1:{port}/mcp"
    yield state
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()


@pytest.fixture
def configured(store, live_mcp):
    data = {"name": "test", "url": live_mcp.url, "headers": {"Authorization": "Bearer fixture-only"},
            "enabled": True, "allowed_tools": ["add", "fail"], "allowed_chats": ["Alice"],
            "allowed_groups": ["Project"], "group_senders": ["Alice"]}
    data["id"] = store.save(data)
    store.settings({"enabled": True})
    return store.read()["servers"][0]
