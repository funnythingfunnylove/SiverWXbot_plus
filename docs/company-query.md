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

## 企业与 VIP 查询工具

当前注册 **41 个 MCP 工具**。通用工具目录包含七大类 **134 个企业栏目**；这是查询适配目录，不代表每家公司、每个账号都能读取全部栏目，更不代表所有栏目均已实网验收。新增工具需在后台重新“测试连接并获取工具”，勾选授权后保存。

生产运行仍只需 Python MCP 依赖和扩展；Node/jsdom 仅用于开发测试。升级时重启独立 MCP 服务，在 `chrome://extensions` 重新加载扩展（0.3.0），关闭旧桥接页后重新打开并配对，再重启更新后的机器人后台。

### 常用工具

| 工具 | 用途 |
| --- | --- |
| `search_companies(query, limit)` | 搜索第一页候选，取得准确企业 ID |
| `get_company_basic_profile(company_id)` | 工商字段与统一社会信用代码 |
| `get_company_capabilities(company_id, group)` | 实际打开指定类别网页，逐栏返回可见、受限或未观察到；只做发现，不算完成背调 |
| `get_company_section(company_id, section, page, limit, offset, view)` | 读取目录中的任一中文栏目，例如“历史行政处罚”“债券信息”“财务数据” |
| `get_company_ownership_chain(company_id, page, limit, offset)` | 股东穿透的单层展开，返回原始持股比例、股东链接、下一层企业 ID；继续调用下一层并记录循环与未展开节点 |
| `get_company_section_detail(company_id, section, row_index, page)` | 读取该页第 row_index 条记录的“详情”弹窗，序号从 1 起；没有支持的详情控件明确返回不可用 |
| `get_company_annual_report(company_id, year, offset)` | 读取企业年报，按 `next_offset` 继续文档；“企业选择不公示”保持原文 |
| `get_company_judicial_case_detail(company_id, case_id, offset)` | 从案件/开庭记录返回的案件链接取 case_id，再读取详情 |
| `get_person_companies(person_id, company_id, section, page, limit, offset)` | 从主要人员链接取得两种 ID，读取担任/曾担任法定代表人、股东、高管及任职企业；不得按同名猜测人员身份 |
| `tyc_get_access_status()` | 桥接心跳及适配器目录数量；不证明网站已登录或具备全部权限 |

另有 31 个常用企业维度专用工具，与通用工具共用提取、分页和覆盖状态逻辑：

- `get_company_shareholders`：股东信息。
- `get_company_people`：主要人员。
- `get_company_investments`：对外投资。
- `get_company_controlled_entities`：控制企业。
- `get_company_actual_controller`：实际控制人。
- `get_company_beneficial_owners`：最终受益人。
- `get_company_relationships`：疑似关系。
- `get_company_changes`：变更记录。
- `get_company_legal_cases`：司法案件。
- `get_company_hearings`：开庭公告。
- `get_company_judgments`：裁判文书。
- `get_company_enforcements`：被执行人。
- `get_company_dishonest_enforcements`：失信被执行人。
- `get_company_consumption_restrictions`：限制消费令。
- `get_company_final_enforcement_cases`：终本案件。
- `get_company_equity_freezes`：股权冻结。
- `get_company_administrative_penalties`：行政处罚。
- `get_company_abnormal_operations`：经营异常。
- `get_company_tax_arrears`：欠税公告。
- `get_company_guarantees`：对外担保。
- `get_company_equity_pledges`：股权出质。
- `get_company_mortgages`：动产抵押。
- `get_company_bonds`：债券信息。
- `get_company_financials`：财务数据。
- `get_company_annual_reports`：企业年报。
- `get_company_licenses`：行政许可。
- `get_company_qualifications`：资质证书。
- `get_company_bids`：招投标。
- `get_company_news`：新闻舆情。
- `get_company_suppliers`：供应商。
- `get_company_customers`：客户。

`group` 可选：`basic`、`legal`、`risk`、`business`、`development`、`intellectual_property`、`history`。完整 `section` 枚举通过 MCP 参数 Schema 提供。

### 分页、切换子栏目和证据

- `page` 是网站页码，`limit` 为本次最多返回的记录数（1–20），`offset` 是当前网站页中的偏移。按 `pagination.next_offset` 读完当前页，再用 `next_page` 进入下一页；较大记录会自动降低本次返回数量。
- 分页必须同时确认选中页码和记录已变化。无法定位页码、详情或指定子栏目时返回不可用，不用第一页或默认栏目冒充目标结果。单次任务限 35 秒，跨很多页可能超时。
- `view` 可选择已确认的只读子栏目，例如股权出质的“身为出质人”“身为质权人”、对外投资的“对外投资(间接)”、最终受益人的“受益机构”；具体选项从能力目录读取。不能用此参数点击任意按钮。默认只覆盖当前可见子栏目/筛选条件。
- 返回原始 `headers` / `cells`、企业/人员/案件/年报链接、`source.url` 和抓取时间。金额和单位不擅自换算；债权人/债务人、出质人/质权人、原告/被告/第三方必须按表头判读。表头复杂或单元格过长时应查看原网页/详情。
- 企业股东逐层穿透不自动推断实控人；实控人、受益所有人和法定代表人是不同概念。网站提供的“疑似关系”仍为疑似关系。
- 返回内容超过机器人文本预算时保留独立 `coverage_metadata`，告知截断与分页位置，不把截断结果当作全量。

### 覆盖状态

| status | 含义与回答方式 |
| --- | --- |
| `ok` | 该网页栏目当前视图的已知记录已读完；不表示整家企业背调完成 |
| `partial` | 还有分页、页内记录、其他表、未确认总数、文档片段或截断 |
| `no_records` | 栏目正文明确显示暂无记录，仅可描述网站此栏目未显示记录 |
| `reported_zero` | 网站有明确的 0 计数，但没有正文记录可供核对；保留此证据层级 |
| `auth_required` | 登录已失效或该栏目要求登录 |
| `permission_denied` | 当前账号仍需额外会员权限；VIP 不保证全部 SVIP 栏目可读 |
| `not_disclosed` / `not_observed` | 没有可读栏目或没有观察到，不能解释为零 |
| `source_changed` | 栏目结构、标识或支持的数据结构不匹配 |
| `page_unavailable` / `view_unavailable` / `detail_unavailable` | 指定页码、子栏目或详情暂不可读取 |

每个返回带 `coverage`，`risk_conclusion_allowed` 始终为 false：单项查询不能自动给出“没有风险”的结论。背调答复必须列出已查询、部分查询、受限、未披露及未查询的维度，当前信息与历史信息分别核对。超时、验证码和频率限制明确失败，不自动重试、不绕过验证、不回退到官方 API/MCP。

### 网页核验范围

2026-09-16 使用已登录账户以抚州市城市建设集团有限公司实网观察了工商、股东、人员、控制企业、实际控制人、受益人、司法案件、开庭公告、股权出质、经营栏目、2025 年报和人员任职页。股权出质的 Chrome 保存页面已用于离线提取器验证，仓库只保存脱敏的最小结构测试样本。

本次观察记录见 [企业样本核验](tianyancha-fuzhou-validation.md)。未给该企业显示的债券/财务独立栏目，无法据此实测有记录时的结构。图谱画布、站外文件下载、导出、付费升级，以及与当前 DOM 不兼容的详情样式没有冒充支持；返回可定位链接或明确的未覆盖状态。尚未在用户安装的扩展中完成新增工具的全链路实网调用验收。

## 从官方接入迁移

原 `kind=tianyancha` 的官方配置读取后变为本地地址、停用、清空工具白名单和请求头；保存配置后移除磁盘中的旧 Key。读取时不会修改原文件。需完成网页配对、重新发现工具、核对授权并保存。手动添加的官方地址也会停用，服务配置与连接层拒绝该官方域名。

原 Skill 管理、ZIP 包附件、其他 MCP 服务、私聊和群聊权限保持可用。官方 Skill 原文可以导入作业务参考，但助手的运行约束只允许网页桥接已发现并授权的工具。

## 验证与限制

```sh
python -m pytest tests integrations/tianyancha_mcp/tests -q
npm ci --prefix integrations/tianyancha_mcp
npm test --prefix integrations/tianyancha_mcp
node --check integrations/tianyancha_mcp/extension/bridge.js
```

自动测试覆盖 MCP 传输、所有专用工具路由、Schema 验证、任务关联、认证、断连和超时、旧配置停用、权限与空结果区分、分页内容确认、子栏目、详情、嵌套表格及脱敏实网 DOM 样本。真实扩展需在升级后验收：搜索目标企业、核对主体、逐项读取栏目、对照页码和记录，检查登录过期/验证页面。Chrome 桥接页休眠或标签页受限可能使任务超时，不保证无人值守持续可用。
