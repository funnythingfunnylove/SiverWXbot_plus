"""Local UI verification only: real Flask/MCP HTTP, no real WeChat or model.

Run from the repository: python tests/panel_preview.py
All generated credentials/configuration go to a temporary directory.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from windows_stubs import install

for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(key, None)
os.chdir(tempfile.mkdtemp(prefix="siver-mcp-preview-"))
install()
import wxbot_core
import web_server
from conftest import serve
from mcp.server.fastmcp import FastMCP

wxbot_core.WXBotConfig()
web_server.app.template_folder = str(ROOT / "templates")
web_server.app.static_folder = str(ROOT / "templates" / "static")
mcp = FastMCP("Panel preview", stateless_http=True, json_response=True)

@mcp.tool(annotations={"readOnlyHint": True})
def add(a: int, b: int) -> int:
    """计算两个整数的和，用于验证工具调用链路。"""
    return a + b

server, thread, sock, port = serve(mcp.streamable_http_app())
print(f"PREVIEW_MCP_URL=http://127.0.0.1:{port}/mcp", flush=True)
try:
    web_server.app.run(host="127.0.0.1", port=18765, threaded=True, use_reloader=False)
finally:
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()
