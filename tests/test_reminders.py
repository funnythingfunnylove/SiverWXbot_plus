import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from mcp_manager import MCPManager, tool_name
from reminder_store import LOCAL_TZ, ReminderSession, ReminderStore

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=LOCAL_TZ)


@pytest.fixture
def reminders(tmp_path):
    return ReminderStore(str(tmp_path / "reminders.sqlite3"))


def create(reminders, owner="Alice", repeat="once"):
    return reminders.create(owner, "开会", "2026-09-15 10:10", repeat=repeat, now=NOW)


def test_persistent_reminder_and_concurrent_single_claim(reminders):
    item = create(reminders)
    other = ReminderStore(reminders.path)
    assert other.list("Alice")[0]["id"] == item["id"]
    assert create(other)["id"] == item["id"]
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda s: s.claim_due(NOW + timedelta(minutes=10)), [reminders, other]))
    assert sum(len(c) for c in claims) == 1
    # Simulate restart after a send with unknown outcome: never automatically replay.
    reopened = ReminderStore(reminders.path)
    assert reopened.claim_due(NOW + timedelta(minutes=11)) == []
    assert reopened.list("Alice")[0]["last_status"] == "unknown"


def test_owner_isolation_and_cancellation_after_claim(reminders):
    item = create(reminders)
    assert reminders.list("Bob") == []
    assert not reminders.cancel("Bob", item["id"])["cancelled"]
    due = reminders.claim_due(NOW + timedelta(minutes=10))[0]
    assert reminders.cancel("Alice", item["id"])["cancelled"]
    assert not reminders.can_deliver(item["id"])
    reminders.finish(due, "blocked")
    assert reminders.list("Alice")[0]["status"] == "cancelled"


@pytest.mark.parametrize("repeat,days", [("daily", 1), ("weekly", 7)])
def test_repeat_advances_and_failed_send_not_retried(reminders, repeat, days):
    create(reminders, repeat=repeat)
    due = reminders.claim_due(NOW + timedelta(minutes=10))[0]
    reminders.finish(due, "unknown")
    assert reminders.claim_due(NOW + timedelta(minutes=11)) == []
    assert len(reminders.claim_due(NOW + timedelta(days=days, minutes=10))) == 1


def test_offline_grace_and_no_catchup_flood(reminders):
    create(reminders)
    create(reminders, "Bob", "daily")
    assert reminders.claim_due(NOW + timedelta(days=3)) == []
    assert reminders.list("Alice")[0]["status"] == "missed"
    assert reminders.list("Bob")[0]["next_time"] == "2026-09-18 10:10"
    assert len(reminders.claim_due(NOW + timedelta(days=3, minutes=10))) == 1


@pytest.mark.parametrize("run_at", ["昨天", "2026-09-15 09:00", "2028-09-15 10:10"])
def test_invalid_time_never_creates(reminders, run_at):
    with pytest.raises(ValueError):
        reminders.create("Alice", "开会", run_at, now=NOW)
    assert reminders.list("Alice") == []


def test_query_requires_personal_key_and_no_recipient_argument(reminders):
    session = ReminderSession(reminders, "Alice", lambda: False)
    result = asyncio.run(session.call_tool("reminder_create", {
        "body": "查项目", "run_at": "2026-09-15 10:10", "mode": "mcp_query"}))
    assert result.isError
    assert reminders.list("Alice") == []


def test_scheduled_query_only_personal_read_tools(store):
    from test_mcp import response, call
    events = []
    @asynccontextmanager
    async def connector(server):
        assert server["headers"]["Authorization"] == "Bearer fixture-person"
        async def listing(**kw):
            return ListToolsResult(tools=[
                Tool(name="read", inputSchema={"type": "object"}, annotations=ToolAnnotations(readOnlyHint=True)),
                Tool(name="write", inputSchema={"type": "object"}, annotations=ToolAnnotations(readOnlyHint=False)),
            ])
        async def calling(name, arguments):
            events.append(name)
            if name == "weekly_identity":
                return CallToolResult(content=[], structuredContent={"person_id": "A", "tools": ["read", "write"]})
            return CallToolResult(content=[TextContent(type="text", text="项目正常")])
        yield SimpleNamespace(list_tools=listing, call_tool=calling)
    ident = store.save({"kind": "hrzh_person", "name": "项目", "chat": "Alice", "key": "fixture-person",
                       "enabled": True, "allowed_tools": ["read", "write"]})
    store.save({"name": "other", "url": "https://other.example/mcp", "enabled": True,
                "allowed_chats": ["Alice"], "allowed_tools": ["write"]})
    store.settings({"enabled": True})
    manager = MCPManager(store, connector=connector)
    context = {"chat": "Alice", "is_group": False, "reminder_run": True, "reminders": True}
    config, servers = manager.eligible(context)
    assert len(servers) == 1
    count = 0
    async def model(**kwargs):
        nonlocal count
        count += 1
        assert [t["name"] for t in kwargs["tools"]] == [tool_name(ident, "read")]
        return response(calls=[call(tool_name(ident, "read"), {})]) if count == 1 else response("项目正常")
    try:
        assert manager.submit(lambda: manager.converse(model, "model", [], context, config, servers), 10) == "项目正常"
        assert events == ["weekly_identity", "read"]
        async def no_query(**kwargs):
            return response("编造的结果")
        assert "未获得有效工具结果" in manager.submit(
            lambda: manager.converse(no_query, "model", [], context, config, servers), 10)
    finally:
        manager.close()


def test_group_never_has_reminder_tools(manager):
    assert not manager.reminder_access({"chat": "Project", "is_group": True, "reminders": True})
    assert not manager.reminder_access({"chat": "Alice"})


def test_external_outage_does_not_prevent_cancelling_local_reminder(store, monkeypatch):
    from test_mcp import response, call
    import reminder_store
    monkeypatch.setattr(reminder_store, "local_now", lambda: NOW)
    @asynccontextmanager
    async def unavailable(server):
        raise RuntimeError("fixture outage")
        yield
    manager = MCPManager(store, connector=unavailable)
    item = create(manager.reminders)
    store.save({"name": "down", "url": "https://down.example/mcp", "enabled": True,
                "allowed_chats": ["Alice"], "allowed_tools": ["read"]})
    store.settings({"enabled": True})
    context = {"chat": "Alice", "is_group": False, "reminders": True}
    config, servers = manager.eligible(context)
    count = 0
    async def model(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return response(calls=[call("reminder_cancel", {"reminder_id": item["id"]})])
        assert "已取消" in kwargs["input"][-1]["output"]
        return response("已取消提醒")
    try:
        result = manager.submit(lambda: manager.converse(model, "model", [], context, config, servers), 10)
        assert "已取消" in result and "外部 MCP 暂不可用" in result
        assert manager.reminders.list("Alice")[0]["status"] == "cancelled"
    finally:
        manager.close()


def test_model_cannot_choose_another_recipient(manager):
    from test_mcp import response, call
    context = {"chat": "Alice", "is_group": False, "reminders": True}
    config, servers = manager.eligible(context)
    count = 0
    async def model(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return response(calls=[call("reminder_create", {
                "body": "开会", "run_at": "2026-09-15 10:10", "repeat": "once", "mode": "text", "owner": "Bob"})])
        assert json.loads(kwargs["input"][-1]["output"])["is_error"]
        return response("不能为别人创建")
    assert manager.submit(lambda: manager.converse(model, "model", [], context, config, servers), 10) == "不能为别人创建"
    assert manager.reminders.list("Alice") == manager.reminders.list("Bob") == []


def test_list_paginates_without_losing_cancellation_ids(reminders):
    for i in range(25):
        reminders.create("Alice", "正文" * 500 + str(i), "2026-09-15 10:10", now=NOW)
    session = ReminderSession(reminders, "Alice", lambda: False)
    first = asyncio.run(session.call_tool("reminder_list", {}))
    page = json.loads(first.content[0].text)
    assert len(page["reminders"]) == 20 and page["next_offset"] == 20
    assert len(first.content[0].text) < 12000
    second = json.loads(asyncio.run(session.call_tool("reminder_list", {"offset": 20})).content[0].text)
    assert len(second["reminders"]) == 5 and second["next_offset"] is None
    assert len({r["id"] for r in page["reminders"] + second["reminders"]}) == 25
