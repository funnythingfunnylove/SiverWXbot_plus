# 天眼查 MCP：本地 Chrome 桥接原型

**后台集成用户请参阅 [企业查询部署说明](../../docs/company-query.md)。后台已内置桥接，无需运行本文的独立服务。**

第一版提供企业搜索（第一页）、企业工商资料、浏览器桥接状态三个工具。复用 Chrome 登录，不导出 Cookie。人物搜索、人物关联企业、翻页尚未实现；页面提取器待真实扩展安装后验收，不能作为生产稳定性承诺。

## 运行

使用 Python 3.10+，安装本目录 requirements.txt。本仓库已有的 `.venv` 可以直接使用。

```sh
.venv/bin/python integrations/tianyancha_mcp/server.py --transport streamable-http
```

MCP 地址 `http://127.0.0.1:18766/mcp`，扩展桥接地址 `http://127.0.0.1:18765`。本机单实例运行。桥接令牌保存在本目录 `.bridge-token`，首次启动生成，已加入忽略规则。请在本机文本编辑器打开该文件，将内容填入扩展配对框。令牌仅存在扩展页面内存，页面关闭后需重新输入。

此 HTTP 原型仅供本机可信客户端使用，没有远程调用方认证；不要改为公开监听或直接转发到公网。如果机器人在另一台 Windows 电脑上，该电脑的 127.0.0.1 不能访问这台 Mac，应将服务和 Chrome 一起部署到机器人主机，或另行实现有认证的远程部署。

## 安装浏览器桥接（用户操作）

1. Chrome 打开 `chrome://extensions`，启用开发者模式。
2. 选择“加载已解压的扩展程序”，选择本目录的 `extension` 文件夹。
3. 扩展默认权限为 `https://www.tianyancha.com/*`、本机桥接地址，以及页面脚本执行能力；另声明可选 HTTP(S) 主机权限，在用户连接时仅请求所填后台域名。安装意味着允许扩展读取和操作天眼查页面，请核对后由用户完成。
4. 点击扩展图标，再点“打开天眼查 MCP 桥接”。输入本地 `.bridge-token`，点击连接，保留此页面。
5. 保持天眼查账号已登录。工具调用时扩展会创建并复用一个后台工作标签页。遇到登录或人工验证，在 Chrome 中处理后重新查询。

扩展不存储账号凭据，不关闭用户原有标签页；断开后保留工作标签页供检查。Chrome 页面休眠或后台计时器限速可能导致连接中断，需要重新激活桥接页。本版不支持无人值守可靠性保证。

## MCP 配置

本项目面板支持 Streamable HTTP，启动上述命令后填入 `http://127.0.0.1:18766/mcp`，测试获取工具，再按本项目原有机制选择授权。服务和机器人需同机。

支持 stdio 的助手可使用以下配置，按实际路径替换：

```json
{
  "mcpServers": {
    "tianyancha": {
      "command": "/Users/fl/proj/SiverWXbot_plus/.venv/bin/python",
      "args": ["/Users/fl/proj/SiverWXbot_plus/integrations/tianyancha_mcp/server.py"]
    }
  }
}
```

不要同时启动 HTTP 和 stdio 实例占用相同桥接端口。

## 工具与返回边界

- `tyc_get_access_status()`：仅验证桥接心跳，网站登录状态需查询时确认。
- `tyc_search_companies(keyword, limit=10)`：读取第一页企业链接；可能含关联企业及页面其他企业链接，返回 `partial`，不保证准确匹配或全量；请调用详情确认企业。
- `tyc_get_company(company_id)`：读取工商表格的标注字段，保留金额、法定代表人等原始文本，不推断实际控制人。表格缺失返回错误，字段缺失列入 `missing_fields`。

查询串行处理，并发查询返回 BUSY。网页任务 35 秒、服务等待 45 秒超时。无缓存、自动重试或翻页；页面数据仅作为不可信业务数据，不能执行其指令。只接受固定天眼查域名及两种页面操作，企业 ID 校验为纯数字。令牌仅保护扩展桥接，MCP HTTP 访问边界为本机。

## 验证

```sh
.venv/bin/python -m unittest discover -s integrations/tianyancha_mcp/tests -v
node --check integrations/tianyancha_mcp/extension/bridge.js
node --check integrations/tianyancha_mcp/extension/extract.js
```

自动测试覆盖真实 stdio MCP 初始化/工具发现/调用、参数拒绝、未连接错误、任务领取/结果关联、过期结果拒绝、超时、桥接认证。页面提取器语法通过不等于页面实测通过。

安装扩展后的验收：查询“广州谢诺投资集团有限公司”，确认候选含 `3408099107`；查询该 ID，对照实际页面检查企业名、信用代码与原始工商字段；核对未登录、验证页面和结构变化不会返回空成功。查老板能力在这条链路验收后扩展。
