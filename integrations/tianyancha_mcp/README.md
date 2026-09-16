# 天眼查网页 MCP

基于官方 Python MCP SDK（FastMCP）封装 Chrome 网页能力。部署、工具契约、迁移和限制见 [网页桥接说明](../../docs/company-query.md)。不调用天眼查官方 MCP。

后台使用 Streamable HTTP：

```sh
python integrations/tianyancha_mcp/server.py --transport streamable-http
```

其他 MCP 客户端也可使用 stdio，将 `command` 设为已安装依赖的 Python 绝对路径，`args` 设为本目录 `server.py` 的绝对路径。两种模式都需要扩展配对，不可同时占用相同桥接端口。

设计参考：[天眼一下官方 Skill](https://www.tianyancha.com/ai/skills/skill.md) 第八节（2026-09-16 查阅），仅采用主体锚定、画像、能力发现的设计。实现使用 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 的标准服务端，工具名与参数以实际 `tools/list` 为准。
