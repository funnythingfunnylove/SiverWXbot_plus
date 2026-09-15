"""Persistent private-chat reminders and atomic occurrence claims.

Times use UTC+08:00 explicitly, independent of the Windows system timezone.
Claim before sending: an interrupted/ambiguous delivery is never replayed.
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=8))
TIME_FORMAT = "%Y-%m-%d %H:%M"


def local_now():
    return datetime.now(LOCAL_TZ)


def display_time(stamp):
    return datetime.fromtimestamp(stamp, LOCAL_TZ).strftime(TIME_FORMAT)


def next_occurrence(stamp, repeat, now):
    step = 86400 if repeat == "daily" else 7 * 86400
    return stamp + (max(0, int((now - stamp) // step)) + 1) * step


class ReminderStore:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL,
                    mode TEXT NOT NULL, repeat TEXT NOT NULL, next_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL,
                    last_status TEXT, last_at REAL
                );
                CREATE TABLE IF NOT EXISTS reminder_runs (
                    id TEXT PRIMARY KEY, reminder_id TEXT NOT NULL, scheduled_at REAL NOT NULL,
                    status TEXT NOT NULL, UNIQUE(reminder_id, scheduled_at)
                );
                CREATE INDEX IF NOT EXISTS reminder_due ON reminders(status, next_at);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, owner, body, run_at, repeat="once", mode="text", now=None):
        now = now or local_now()
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("缺少私聊用户")
        if not isinstance(body, str) or not body.strip() or len(body) > 2000:
            raise ValueError("提醒内容须为 1～2000 字")
        if repeat not in ("once", "daily", "weekly") or mode not in ("text", "mcp_query"):
            raise ValueError("提醒类型或重复方式无效")
        try:
            due = datetime.strptime(run_at, TIME_FORMAT).replace(tzinfo=LOCAL_TZ)
        except (ValueError, TypeError):
            raise ValueError("时间须为 YYYY-MM-DD HH:MM，使用北京时间 UTC+08:00")
        if not now < due <= now + timedelta(days=366):
            raise ValueError("首次提醒时间须在未来 366 天内，请重新确认时间")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            # Repeated delivery of the same create request must not duplicate a task.
            old = db.execute("""SELECT * FROM reminders WHERE owner=? AND body=? AND mode=?
                AND repeat=? AND next_at=? AND status='active'""",
                (owner, body.strip(), mode, repeat, due.timestamp())).fetchone()
            if old:
                return self.public(old)
            if db.execute("SELECT count(*) FROM reminders WHERE owner=? AND status='active'", (owner,)).fetchone()[0] >= 50:
                raise ValueError("每位用户最多 50 个有效提醒，请先取消不用的提醒")
            if db.execute("SELECT count(*) FROM reminders WHERE status='active'").fetchone()[0] >= 1000:
                raise ValueError("机器人有效提醒已达 1000 个上限")
            ident = uuid.uuid4().hex[:12]
            db.execute("""INSERT INTO reminders(id,owner,body,mode,repeat,next_at,created_at)
                VALUES(?,?,?,?,?,?,?)""", (ident, owner, body.strip(), mode, repeat, due.timestamp(), now.timestamp()))
            return self.public(db.execute("SELECT * FROM reminders WHERE id=?", (ident,)).fetchone())

    @staticmethod
    def public(row):
        item = dict(row)
        item["next_time"] = display_time(item.pop("next_at"))
        item["timezone"] = "UTC+08:00"
        item.pop("created_at", None)
        item.pop("owner", None)
        return item

    def list(self, owner, offset=0, limit=100):
        with self.db() as db:
            rows = db.execute("""SELECT * FROM reminders WHERE owner=?
                ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, next_at DESC LIMIT ? OFFSET ?""", (owner, limit, offset)).fetchall()
            return [self.public(r) for r in rows]

    def cancel(self, owner, reminder_id):
        with self.db() as db:
            changed = db.execute("""UPDATE reminders SET status='cancelled' WHERE id=? AND owner=?
                AND status IN ('active','claimed')""", (reminder_id, owner)).rowcount
            return {"cancelled": bool(changed), "message": "已取消；已经发送到微信的消息无法撤回" if changed else "未找到本人可取消的提醒"}

    def claim_due(self, now=None, limit=5):
        stamp = (now or local_now()).timestamp()
        claimed = []
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT * FROM reminders WHERE status='active' AND next_at<=?
                ORDER BY next_at LIMIT 100""", (stamp,)).fetchall()
            for row in rows:
                if len(claimed) >= limit:
                    break
                # No flood of obsolete reminders after an outage. Allow 1 hour grace.
                if stamp - row["next_at"] > 3600:
                    if row["repeat"] == "once":
                        db.execute("UPDATE reminders SET status='missed',last_status='missed' WHERE id=?", (row["id"],))
                    else:
                        db.execute("UPDATE reminders SET next_at=?,last_status='missed' WHERE id=?",
                                   (next_occurrence(row["next_at"], row["repeat"], stamp), row["id"]))
                    continue
                run_id = uuid.uuid4().hex
                db.execute("INSERT INTO reminder_runs VALUES(?,?,?,'unknown')", (run_id, row["id"], row["next_at"]))
                db.execute("""UPDATE reminders SET status=?,next_at=?,last_status='unknown',last_at=? WHERE id=?""",
                           ("claimed" if row["repeat"] == "once" else "active",
                            row["next_at"] if row["repeat"] == "once" else next_occurrence(row["next_at"], row["repeat"], stamp),
                            stamp, row["id"]))
                claimed.append({**dict(row), "run_id": run_id})
        return claimed

    def can_deliver(self, reminder_id):
        with self.db() as db:
            row = db.execute("SELECT status FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            return bool(row and row["status"] in ("active", "claimed"))

    def finish(self, item, status):
        with self.db() as db:
            db.execute("UPDATE reminder_runs SET status=? WHERE id=?", (status, item["run_id"]))
            db.execute("""UPDATE reminders SET last_status=?,
                status=CASE WHEN status='claimed' THEN ? ELSE status END WHERE id=?""",
                (status, "completed" if status == "sent" else status, item["id"]))


def reminder_tools():
    from mcp.types import Tool
    return [
        Tool(name="reminder_create", description=(
            "仅在用户本次明确要求未来主动提醒时创建本人私聊提醒。时间不清楚先询问，不猜测。"
            "run_at 是北京时间首次触发时间。每天/每周按首次时间重复，weekly 是每周同一天。"
            "text 为固定提醒；mcp_query 到点使用本人 Key 查询后发送，只能查询，不能修改业务数据。"
            "只按成功返回的 ID 和时间确认已创建。"), inputSchema={
                "type": "object", "properties": {
                    "body": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "run_at": {"type": "string", "description": "YYYY-MM-DD HH:MM，北京时间 UTC+08:00"},
                    "repeat": {"type": "string", "enum": ["once", "daily", "weekly"]},
                    "mode": {"type": "string", "enum": ["text", "mcp_query"]}},
                "required": ["body", "run_at", "repeat", "mode"], "additionalProperties": False}),
        Tool(name="reminder_list", description="分页查看当前私聊用户的提醒及发送状态，next_offset 非空时可继续查询。unknown 表示结果未确认，missed 表示过期未补发。",
             inputSchema={"type": "object", "properties": {"offset": {"type": "integer", "minimum": 0, "maximum": 100000}},
                          "additionalProperties": False}),
        Tool(name="reminder_cancel", description="取消本人提醒，先查看列表取得准确 ID。不能取消其他人的提醒。",
             inputSchema={"type": "object", "properties": {"reminder_id": {"type": "string"}},
                          "required": ["reminder_id"], "additionalProperties": False}),
    ]


class ReminderSession:
    def __init__(self, store, owner, may_query):
        self.store, self.owner, self.may_query = store, owner, may_query

    async def call_tool(self, name, arguments):
        from mcp.types import CallToolResult, TextContent
        try:
            if name == "reminder_create":
                if arguments.get("mode") == "mcp_query" and not self.may_query():
                    raise ValueError("请先在 MCP 面板为本人配置并启用个人 Key、选择查询工具并开启 MCP 总开关")
                result = self.store.create(self.owner, **arguments)
            elif name == "reminder_list":
                offset = arguments.get("offset", 0)
                rows = self.store.list(self.owner, offset=offset, limit=21)
                for row in rows:
                    if len(row["body"]) > 160:
                        row["body"] = row["body"][:160] + "…"
                result = {"reminders": rows[:20], "next_offset": offset + 20 if len(rows) > 20 else None}
            elif name == "reminder_cancel":
                result = self.store.cancel(self.owner, **arguments)
            else:
                raise ValueError("未知提醒工具")
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))])
        except ValueError as exc:
            return CallToolResult(isError=True, content=[TextContent(type="text", text=str(exc))])
