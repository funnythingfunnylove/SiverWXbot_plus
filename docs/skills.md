# Skill 管理与天眼查官方 MCP

更新后重启原有 `web_server.py`，无需额外服务或 Chrome 扩展。旧的企业查询页面、桥接接口和扩展下载已移除，可卸载此前的 Tianyancha MCP Local Bridge 扩展并关闭桥接页面。旧配对令牌不再使用。

## 天眼查接入

1. 后台「MCP 工具」点击“添加天眼查官方 MCP”。
2. 填入天眼 AI 密钥，不需要手工填写地址或 JSON 请求头。
3. 测试连接并获取工具，勾选实际要开放的工具，填写授权私聊窗口或群聊名称。
4. 启用服务并保存，打开 MCP 总开关。
5. 在授权对话中请求查询企业工商信息。群聊仍需 @ 机器人。

官方标准地址为 `https://mcp.tianyancha.com/mcp`，使用 Streamable HTTP，密钥以 `Authorization: YOUR_API_KEY` 传递。编辑留空保留密钥；密钥保存在原有 config/mcp.json，GET 接口不回显、不发送给模型。连接测试仅发现工具，不主动消耗业务查询额度；实际调用计费和权限以官方账号为准。无真实密钥时无法验收真实官方查询。

官方资料：https://www.tianyancha.com/ai/developer-docs#quick-start

## Skill 管理

后台新增「Skill 管理」，支持新增、Markdown 文件或 ZIP 技能包导入、编辑、删除和单项启停。在列表或“添加 Skill”的编辑器中均可选择导入文件。ZIP 包支持根目录或任意技能子文件夹中的 `SKILL.md`（不区分大小写），每个包需有且只有一个技能入口；自动忽略 macOS 压缩生成的 `__MACOSX`、`._*` 和 `.DS_Store` 元数据。导入后打开编辑器并列出包内文件，检查名称、填写适用场景并保存，默认不自动启用。上传暂存于 `config/skills/.imports/`，取消导入会删除暂存文件；超过一天的未保存导入在下次上传时清理。ZIP 最大 10 MiB，展开大小上限 50 MiB、最多 2000 个条目；Markdown 需为 UTF-8 编码，最大 240000 字节、60000 字。缺失入口、多个入口、非法路径、无法读取的加密或损坏文件会提示错误。

“导入天眼一下官方 Skill”从 https://www.tianyancha.com/ai/skills/skill.md 获取原文并打开编辑器，检查后保存，默认不自动启用。已存在同名 Skill 时请编辑旧项，避免重复启用。

Skill 索引与兼容正文存储于 `config/skills.json`，完整技能文件保存在 `config/skills/<技能ID>/<版本ID>/`，保留压缩包内的相对路径与二进制内容。手动新增和 Markdown 导入也创建独立文件夹。保存编辑时生成新版本目录，索引写入成功后清理旧版本；切换启用状态与编辑正文均保留附件，删除技能会清理其文件夹。旧版纯正文记录在首次读取时自动迁移为独立文件夹，保持原 ID 和启用状态。修改后下一次对话生效，不用重启。启用的 Skill 内容被加入 OpenAI 兼容 Responses 对话上下文，包括有会话上下文的图片对话；适用范围为所有通过该适配器的助手会话，助手按描述匹配当前问题。当前采用有上限的完整注入，不是按需文件检索；最多保存 50 项，单项正文 60000 字，启用正文总计 80000 字，较长内容会增加模型输入费用。停用后下一次请求不再注入，正在执行的对话不受影响。

当前不接入 Dify/Coze/DusAPI 的外部工作流，不自动执行 Skill 附带脚本、不安装依赖。ZIP 导入保存全部普通文件，包括 `references/`、`scripts/`、`assets/` 等目录中的资源，并拒绝符号链接、特殊文件、重复路径及跨平台不安全路径。启用后，在正文之外加载 UTF-8 的 Markdown、TXT、JSON、YAML、CSV、TOML、XML 文本附件，所有启用技能的附件内容合计最多 80000 字，单文件最多 240000 字节；超限文件、脚本及二进制资源仍保存在技能目录中，文件名会提供给助手，但内容不会注入。助手会获知入口路径和已加载附件的相对路径，不会把未加载内容视为已读取。天眼一下官方 Skill 含 CLI 与 MCP 两种方式，本助手没有 shell 执行能力，因此使用官方第八节 MCP 模式，工具名称与参数以动态发现结果为准。

Skill 不会启用 MCP 总开关，不会改变服务工具白名单、私聊或群聊授权；无法调用未授权的工具。不得把密钥写进 Skill，因为启用的正文会发给模型。天眼查 MCP 和 Skill 需要分别配置：MCP 提供数据能力，Skill 提供调用步骤和答复要求。

## 部署

```powershell
git pull --ff-only origin main
python -m pip install -r requirements.txt
python web_server.py
```

使用 exe 时需要重新打包新增 skill_manager.py 和更新的 templates。旧的 integrations/tianyancha_mcp 资源无需继续包含。
