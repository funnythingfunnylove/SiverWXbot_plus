# 天眼查网页 MCP

基于官方 Python MCP SDK（FastMCP）封装 Chrome 网页能力。部署、工具契约、迁移和限制见 [网页桥接说明](../../docs/company-query.md)。不调用天眼查官方 MCP。

后台使用 Streamable HTTP：

```sh
python integrations/tianyancha_mcp/server.py --transport streamable-http
```

其他 MCP 客户端也可使用 stdio，将 `command` 设为已安装依赖的 Python 绝对路径，`args` 设为本目录 `server.py` 的绝对路径。两种模式都需要扩展配对，不可同时占用相同桥接端口。

设计参考：[天眼一下官方 Skill](https://www.tianyancha.com/ai/skills/skill.md) 第八节（2026-09-16 查阅），仅采用主体锚定、画像、能力发现的设计。实现使用 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 的标准服务端，工具名与参数以实际 `tools/list` 为准。

当前 41 个工具，通用企业栏目目录覆盖 134 项。能力发现读取真实网页，工具结果带来源、分页和覆盖状态。目录项存在不等于已经完整读取，也不代表 VIP 账号享有全部 SVIP 权限。详见部署说明中的覆盖状态表。

开发验证：

```sh
python -m pytest tests integrations/tianyancha_mcp/tests -q
npm ci --prefix integrations/tianyancha_mcp
npm test --prefix integrations/tianyancha_mcp
```

Node/jsdom 只运行隔离的静态 DOM 测试，不是生产服务依赖。网页样本不执行网站脚本，仓库测试夹具已去除账户信息并替换企业与记录值。
