"""MCP settings kept separate from the legacy bot config; secrets never leave GET APIs."""
import copy
import json
import os
import re
import tempfile
import threading
import uuid
from urllib.parse import urlsplit


DEFAULTS = {"enabled": False, "max_rounds": 6, "total_timeout": 120, "servers": []}
TYC_URL = "https://mcp.tianyancha.com/mcp"
HRZH_URL = "https://hrzh.cc/mcp"


def string_list(value, label):
    if not isinstance(value, list) or len(value) > 300:
        raise ValueError(f"{label}必须是列表，最多 300 项")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 256 for v in value):
        raise ValueError(f"{label}包含无效名称")
    return list(dict.fromkeys(v.strip() for v in value))


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}必须为 {low}～{high} 的整数")
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label}必须为布尔值")
    return value


def validate_server(data, previous=None):
    if not isinstance(data, dict):
        raise ValueError("服务配置必须是 JSON 对象")
    previous = previous or {}
    kind = data.get("kind", previous.get("kind", "service"))
    if kind not in ("service", "hrzh_person", "tianyancha"):
        raise ValueError("未知 MCP 服务类型")
    if previous and kind != previous.get("kind", "service"):
        raise ValueError("不能修改服务类型，请添加新配置")
    personal = kind == "hrzh_person"
    if kind == "tianyancha":
        data = dict(data)
        data["url"] = TYC_URL
        key = data.get("key")
        if key is not None:
            if not isinstance(key, str) or not re.fullmatch(r"[!-~]{1,8192}", key):
                raise ValueError("天眼 AI 密钥必须是非空单行文本")
            data["headers"] = {"Authorization": key}
        else:
            data["headers"] = previous.get("headers", {})
        if not data["headers"].get("Authorization"):
            raise ValueError("请填写天眼 AI 密钥")
    if personal:
        data = dict(data)
        data["url"] = HRZH_URL
        chat = data.get("chat", "")
        if not isinstance(chat, str) or not chat.strip() or len(chat) > 256:
            raise ValueError("请填写准确的微信私聊窗口名称")
        key = data.get("key")
        if key is not None:
            if not isinstance(key, str) or not re.fullmatch(r"[!-~]{1,8192}", key):
                raise ValueError("Key 不能为空且必须是单行文本；只填写 Key，不带 Bearer 前缀")
            data["headers"] = {"Authorization": "Bearer " + key}
        else:
            data["headers"] = previous.get("headers", {})
        if not data["headers"].get("Authorization"):
            raise ValueError("请填写用户 Key")
        data["allowed_chats"] = [chat.strip()]
        data["allowed_groups"] = []
    name = data.get("name", "")
    url = data.get("url", "")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError("服务名称不能为空且不能超过 80 字")
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("MCP 地址无效")
    parsed = urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("请填写 HTTP(S) MCP 地址；凭据请放入请求头")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("MCP 地址端口无效") from exc
    headers = data.get("headers", previous.get("headers", {}))
    if not isinstance(headers, dict) or len(headers) > 20:
        raise ValueError("请求头必须是 JSON 对象，最多 20 项")
    for key, value in headers.items():
        if not isinstance(key, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
            raise ValueError("请求头名称无效")
        if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("请求头值必须是单行 ASCII 文本")
        if key.lower() in {"host", "content-length", "connection", "transfer-encoding", "mcp-session-id", "mcp-protocol-version"}:
            raise ValueError("不能覆盖 HTTP/MCP 协议请求头")
    result = {
        "kind": kind,
        "id": previous.get("id", uuid.uuid4().hex),
        "name": name.strip(), "url": url.strip(), "headers": headers,
        "enabled": boolean(data.get("enabled", False), "启用状态"),
        "timeout": integer(data.get("timeout", 20), 5, 60, "服务超时"),
        "allowed_tools": string_list(data.get("allowed_tools", []), "工具名单"),
        "allowed_chats": string_list(data.get("allowed_chats", []), "私聊名单"),
        "allowed_groups": string_list(data.get("allowed_groups", []), "群聊名单"),
    }
    return result


def permits(server, context):
    if not server.get("enabled") or not context:
        return False
    if context.get("is_group"):
        return (context.get("chat") in server.get("allowed_groups", [])
                and context.get("mentioned") is True)
    return context.get("chat") in server.get("allowed_chats", [])


class MCPConfigStore:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()

    def read(self):
        with self._lock:
            if not os.path.exists(self.path):
                return copy.deepcopy(DEFAULTS)
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("servers"), list):
                raise ValueError("MCP 配置文件损坏，请检查 config/mcp.json")
            return {**copy.deepcopy(DEFAULTS), **data}

    def public(self):
        data = self.read()
        for server in data["servers"]:
            server["has_headers"] = bool(server.pop("headers", {}))
        return data

    def _write(self, data):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".mcp-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def settings(self, data):
        if not isinstance(data, dict):
            raise ValueError("设置必须是 JSON 对象")
        with self._lock:
            current = self.read()
            current.update(
                enabled=boolean(data.get("enabled", False), "总开关"),
                max_rounds=integer(data.get("max_rounds", 6), 1, 8, "最大调用轮数"),
                total_timeout=integer(data.get("total_timeout", 120), 20, 300, "对话超时"),
            )
            self._write(current)

    def draft(self, data):
        if not isinstance(data, dict):
            raise ValueError("服务配置必须是 JSON 对象")
        previous = None
        if data.get("id"):
            previous = next((s for s in self.read()["servers"] if s["id"] == data["id"]), None)
            if previous is None:
                raise ValueError("服务不存在，请刷新列表")
        return validate_server(data, previous)

    def save(self, data):
        with self._lock:
            server = self.draft(data)
            current = self.read()
            servers = current["servers"]
            if server["kind"] == "hrzh_person" and any(
                s.get("kind") == "hrzh_person" and s["id"] != server["id"]
                and s["allowed_chats"] == server["allowed_chats"] for s in servers
            ):
                raise ValueError("该微信用户已配置个人 Key，请编辑已有用户")
            for index, old in enumerate(servers):
                if old["id"] == server["id"]:
                    servers[index] = server
                    break
            else:
                if len(servers) >= 100:
                    raise ValueError("最多添加 100 个 MCP 服务或用户")
                servers.append(server)
            self._write(current)
            return server["id"]

    def delete(self, server_id):
        with self._lock:
            current = self.read()
            current["servers"] = [s for s in current["servers"] if s["id"] != server_id]
            self._write(current)
