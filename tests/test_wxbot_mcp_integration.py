import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from conftest import serve
from windows_stubs import install


@pytest.fixture(scope="module")
def modules(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.chdir(tmp_path_factory.mktemp("wxbot-import"))
    install()
    core = importlib.import_module("wxbot_core")
    web = importlib.import_module("web_server")
    web.app.template_folder = str(Path(__file__).resolve().parents[1] / "templates")
    web.app.static_folder = str(Path(__file__).resolve().parents[1] / "templates" / "static")
    core.WXBotConfig()
    yield core, web
    patch.undo()


@pytest.fixture
def live_model():
    requests = []
    state = SimpleNamespace(fail_after_tool=False)
    async def completion(request):
        payload = await request.json()
        requests.append(payload)
        outputs = [m for m in payload["messages"] if m["role"] == "tool"]
        if not payload.get("tools"):
            message = {"role": "assistant", "content": "普通聊天回复"}
        elif not outputs:
            name = next(t["function"]["name"] for t in payload["tools"] if " / add:" in t["function"]["description"])
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "addition", "type": "function", "function": {"name": name, "arguments": '{"a":2,"b":3}'}}]}
        else:
            if state.fail_after_tool:
                return JSONResponse({"error": {"message": "fixture failure", "type": "server_error"}}, status_code=500)
            assert "5" in outputs[-1]["content"]
            message = {"role": "assistant", "content": "查询结果：2 + 3 = 5"}
        return JSONResponse({"id": "fixture-completion", "object": "chat.completion", "created": 1, "model": "fixture",
                             "choices": [{"index": 0, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop", "message": message}]})
    app = Starlette(routes=[Route("/v1/chat/completions", completion, methods=["POST"])])
    server, thread, sock, port = serve(app)
    state.url = f"http://127.0.0.1:{port}/v1"
    state.requests = requests
    yield state
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()


@pytest.mark.parametrize("is_group", [False, True])
def test_bot_message_to_mcp_to_wechat_send(modules, manager, configured, live_mcp, live_model, monkeypatch, is_group):
    core, _ = modules
    monkeypatch.setattr(core, "get_mcp_manager", lambda: manager)
    bot = core.WXBot()
    config = bot.config
    config.listen_list = ["Alice", "Bob"]
    config.group = ["Project"]
    config.group_switch = True
    config.group_reply_at_msg = False
    config.group_reply_quote = False
    config.api_sdk = core.OPENAI_SDK_NAME
    config.api_key = "fixture-model-key"
    config.base_url = live_model.url
    config.model1 = "fixture"
    config.memory_switch = False
    config.reply_delay_switch = False
    config.chat_keyword_switch = config.group_keyword_switch = False
    bot.api = core.OpenAIAPI(config)
    sent = []
    chat = SimpleNamespace(who="Project" if is_group else "Alice", chat_type="group" if is_group else "friend", SendMsg=lambda msg, **kwargs: sent.append(msg) or True)
    message = SimpleNamespace(sender="Alice", content="计算2加3", type="text", attr="friend")
    try:
        bot.process_message(chat, message)
        assert sent == ["查询结果：2 + 3 = 5"]
        assert live_mcp.calls == [(2, 3)]
        assert len(live_model.requests) == 2
        # Unauthorized sender/chat retains the original model path without tools.
        message.sender = "Bob"
        if not is_group:
            chat.who = "Bob"
        bot.process_message(chat, message)
        assert sent[-1] == "普通聊天回复"
        assert live_mcp.calls == [(2, 3)]
        assert "tools" not in live_model.requests[-1]
    finally:
        bot.api.client.close()


def test_actual_flask_dashboard_registration(modules):
    _, web = modules
    with web.app.test_client() as client:
        assert client.get("/api/mcp/config").status_code == 401
        with client.session_transaction() as sess:
            sess["logged_in"] = True
            sess["username"] = "fixture"
        result = client.get("/dashboard")
        assert result.status_code == 200
        assert b"tab-mcp" in result.data and b"mcp_panel.js" in result.data
        assert client.get("/static/mcp_panel.js").status_code == 200
        assert client.get("/api/mcp/config").status_code == 200


def test_model_failure_after_execution_never_replays(modules, manager, configured, live_mcp, live_model, monkeypatch):
    core, _ = modules
    monkeypatch.setattr(core, "get_mcp_manager", lambda: manager)
    live_model.fail_after_tool = True
    config = SimpleNamespace(model1="fixture", api_key="fixture-only", base_url=live_model.url, prompt="Reply using tools")
    api = core.OpenAIAPI(config)
    try:
        def forbidden(*args, **kwargs):
            pytest.fail("MCP must not enter legacy Responses fallback")
        monkeypatch.setattr(api, "_try_responses_api", forbidden)
        text = api.chat("2+3?", conversation={"chat": "Alice", "sender": "Alice", "is_group": False})
        assert "未完成" in text and "500" in text
        assert live_mcp.calls == [(2, 3)]
        assert len(live_model.requests) == 2  # SDK retries are disabled in the loop.
    finally:
        api.client.close()
