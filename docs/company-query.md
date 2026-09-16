# 天眼查网页桥接 MCP

调用链：微信助手 → 现有 MCP 客户端与会话白名单 → 本地 FastMCP 服务 → Chrome 扩展 → 天眼查网页。

不调用天眼查官方 MCP 或官方 CLI，不需要天眼 AI API Key。Cookie 保留在 Chrome；网页可见内容受当前账号登录和会员权限限制。扩展不会处理验证码，需要在浏览器中人工完成。

## 启动和配对

在运行机器人的电脑上安装 Python 3.10+、Chrome，并在项目根目录运行：

```powershell
python -m pip install -r integrations/tianyancha_mcp/requirements.txt
python integrations/tianyancha_mcp/server.py --transport streamable-http
```

保持此进程运行。默认 MCP 地址为 `http://127.0.0.1:18766/mcp`，浏览器任务桥接为 `http://127.0.0.1:18765`。两者都只监听本机。服务与 Chrome、机器人部署在同一台电脑；不会随 `web_server.py` 自动启动。

1. Chrome 打开 `chrome://extensions`，打开开发者模式，加载已解压扩展 `integrations/tianyancha_mcp/extension`。
2. 登录天眼查网站。点击扩展图标，打开桥接页面。
3. 从本机文件 `integrations/tianyancha_mcp/.bridge-token` 读取首次启动生成的配对令牌，填入扩展并点击连接。保留桥接页，关闭后需重新配对。令牌不要填写到 Skill 或聊天中。
4. 重启更新后的 `web_server.py`。后台「MCP 工具」点击“添加天眼查网页 MCP”，测试连接并获取工具。
5. 勾选所需工具，填写授权私聊或群聊，启用服务、保存并打开 MCP 总开关。建议单次超时 60 秒。
6. 在授权会话中查询企业；群聊需 @ 机器人。先搜索候选，再用返回的企业 ID 核验工商资料。

连接测试只做 MCP 初始化和工具发现，不证明扩展在线或网页登录有效。`tyc_get_access_status` 检查扩展心跳，实际查询才能检查页面可访问性。

支持 `--port` 和 `--bridge-port` 自定义端口。此时使用后台“添加 MCP 服务”填写对应 MCP 地址，并在扩展中修改桥接地址。默认 MCP 端口仅供本机可信程序使用，不带远程身份认证，不应转发到公网。

## 工具契约

参考天眼一下官方 Skill 第八节的“主体搜索 → 基础画像 → 能力发现”流程，实现标准 MCP `tools/list`、`tools/call`、输入 Schema、结构化返回及只读注解。工具来自本地 SDK 注册，不转发官方 MCP。

| 工具 | 参数 | 结果与边界 |
| --- | --- | --- |
| `search_companies` | `query`，`limit=10`（1–20） | 第一页候选，保留 `company_id`、名称、来源链接；候选可能包含关联企业，必须核验 |
| `get_company_basic_profile` | `company_id`（搜索返回的数字 ID） | 工商表格可见字段，原始金额、法定代表人；缺失字段明确列出 |
| `get_company_capabilities` | `company_id`，可选 `company_name` | 返回已实现的工商工具，说明尚不支持的维度；不是实际账号权限检查 |
| `tyc_get_access_status` | 无 | 桥接心跳、已实现与未实现能力；登录状态为待查询确认 |

目前没有翻页、人物搜索、司法风险、股东穿透、实控人推断、批量查询或代理 `call_tool`。这不是官方完整工具集的兼容实现。官方工具的 `query` 与基础画像命名供接口设计参考，网页提取结果保留自己的字段和来源结构，不伪装成官方 API 返回。

来源含网页 URL 和抓取时间；分页未覆盖返回 `partial`，不可把未查询到视作“不存在风险”。网页任务串行处理，并发返回 `BUSY`；单次页面等待 35 秒、桥接等待 45 秒。不自动重试查询。遇到登录、验证码、频率限制或页面结构变化会明确失败，不绕过验证，也不回退到官方接口。

## 从官方接入迁移

原 `kind=tianyancha` 的官方配置读取后变为本地地址、停用、清空工具白名单和请求头；保存配置后移除磁盘中的旧 Key。读取时不会修改原文件。需完成网页配对、重新发现工具、核对授权并保存。手动添加的官方地址也会停用，服务配置与连接层拒绝该官方域名。

原 Skill 管理、ZIP 包附件、其他 MCP 服务、私聊和群聊权限保持可用。官方 Skill 原文可以导入作业务参考，但助手的运行约束只允许网页桥接已发现并授权的工具。

## 验证与限制

```sh
python -m pytest tests integrations/tianyancha_mcp/tests -q
node --test integrations/tianyancha_mcp/tests/extract.test.js
node --check integrations/tianyancha_mcp/extension/bridge.js
```

自动测试覆盖 MCP 传输、工具发现和调用、任务关联、认证、断连和超时、旧配置停用以及模拟 DOM 提取。真实网站页面结构需要在安装扩展后验收：搜索目标企业、核对候选 ID、对照工商字段和信用代码，检查登录过期/验证页面。Chrome 桥接页休眠或标签页受限可能使任务超时，不保证无人值守持续可用。
