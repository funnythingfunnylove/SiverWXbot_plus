/* MCP settings are independent from the legacy dashboard config form. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const root = el('tab-mcp');
  const apiBase = new URL('./api/mcp/', window.location.href);
  let servers = [], editingId = null, editingKind = 'service', busy = false, revision = 0;
  const status = (text, bad = false, id = 'mcp-status') => {
    el(id).textContent = text;
    el(id).style.color = bad ? '#d93025' : 'var(--primary)';
  };
  const lines = id => el(id).value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  async function request(path, method = 'GET', data) {
    const response = await fetch(new URL(path, apiBase), {
      method, credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-MCP-Request': '1'},
      body: data === undefined ? undefined : JSON.stringify(data)
    });
    let result;
    try { result = await response.json(); } catch (_) { throw new Error('服务返回异常，请检查登录状态和连接'); }
    if (!response.ok || result.status !== 'success') throw new Error(result.message || '请求失败');
    return result;
  }
  async function action(work) {
    if (busy) return;
    busy = true;
    root.querySelectorAll('button').forEach(b => b.disabled = true);
    try { await work(); } catch (error) { status(error.message, true); }
    finally { busy = false; root.querySelectorAll('button').forEach(b => b.disabled = false); }
  }
  function selectedTools() {
    return [...el('mcp-tools').querySelectorAll('input:checked')].map(input => input.value);
  }
  function renderTools(tools, selected = []) {
    const container = el('mcp-tools');
    container.replaceChildren();
    const known = new Set(tools.map(t => t.name));
    const all = [...tools, ...selected.filter(name => !known.has(name)).map(name => ({name, description: '已保存的选择；请获取工具列表以核对当前是否可用。'}))];
    if (!all.length) { container.textContent = '尚无工具，请先测试连接。'; return; }
    all.forEach((tool, index) => {
      const row = document.createElement('div');
      row.style.cssText = 'padding:8px 0;border-bottom:1px solid var(--border);overflow-wrap:anywhere;';
      const input = document.createElement('input');
      input.type = 'checkbox'; input.value = tool.name; input.checked = selected.includes(tool.name);
      input.id = `mcp-tool-${index}`;
      const label = document.createElement('label');
      label.htmlFor = input.id; label.textContent = ` ${tool.name}${tool.read_only ? ' · 服务标记只读' : ''}`;
      const description = document.createElement('div');
      description.className = 'cfg-hint'; description.textContent = tool.description || '未提供说明';
      row.append(input, label, description);
      if (tool.input_schema) {
        const details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
        summary.textContent = '查看参数'; pre.textContent = JSON.stringify(tool.input_schema, null, 2);
        details.append(summary, pre); row.append(details);
      }
      container.append(row);
    });
  }
  function edit(server = {}) {
    revision++;
    editingId = server.id || null;
    editingKind = server.kind || 'service';
    const personal = editingKind === 'hrzh_person';
    el('mcp-person-fields').hidden = !personal;
    el('mcp-service-fields').hidden = personal;
    el('mcp-service-permissions').hidden = personal;
    el('mcp-person-chat').value = (server.allowed_chats || [])[0] || '';
    el('mcp-person-key').value = '';
    el('mcp-person-hint').textContent = server.has_headers ? '已保存 Key，留空保留，填写新 Key 替换。仅用于此用户的私聊。' : 'Key 保存在本机，不回显、不发送给模型。一个微信用户只绑定一个个人 Key。';
    el('mcp-editor').hidden = false;
    el('mcp-editor-title').textContent = personal ? '配置项目管理用户' : (editingId ? '编辑 MCP 服务' : '添加 MCP 服务');
    for (const [field, value] of Object.entries({name: server.name || '', url: server.url || '', headers: '', timeout: server.timeout || 20,
      chats: (server.allowed_chats || []).join('\n'), groups: (server.allowed_groups || []).join('\n')})) el(`mcp-${field}`).value = value;
    el('mcp-clear-headers').checked = false;
    el('mcp-server-enabled').checked = !!server.enabled;
    el('mcp-secret-hint').textContent = server.has_headers ? '已保存认证请求头。留空保留，输入新 JSON 替换，或勾选清除。' : '尚未保存认证请求头；没有认证要求可留空。';
    renderTools([], server.allowed_tools || []);
    status('', false, 'mcp-test-status');
    el('mcp-name').focus();
  }
  function draft() {
    const result = {id: editingId, kind: editingKind, name: el('mcp-name').value, url: el('mcp-url').value,
      timeout: Number(el('mcp-timeout').value), enabled: el('mcp-server-enabled').checked,
      allowed_tools: selectedTools(), allowed_chats: lines('mcp-chats'), allowed_groups: lines('mcp-groups')};
    if (editingKind === 'hrzh_person') {
      result.chat = el('mcp-person-chat').value.trim();
      result.allowed_chats = result.chat ? [result.chat] : [];
      result.allowed_groups = [];
      if (el('mcp-person-key').value) result.key = el('mcp-person-key').value;
      return result;
    }
    const text = el('mcp-headers').value.trim();
    if (el('mcp-clear-headers').checked) result.headers = {};
    else if (text) {
      try { result.headers = JSON.parse(text); } catch (_) { throw new Error('认证请求头不是有效 JSON'); }
    }
    return result;
  }
  async function load() {
    const {config} = await request('config');
    servers = config.servers;
    el('mcp-enabled').checked = config.enabled;
    el('mcp-rounds').value = config.max_rounds;
    el('mcp-total-timeout').value = config.total_timeout;
    const list = el('mcp-servers'); list.replaceChildren();
    if (!servers.length) list.textContent = '还没有 MCP 服务。添加后可测试连接、选择工具。';
    for (const server of servers) {
      const row = document.createElement('div'); row.style.cssText = 'display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:12px 0;border-bottom:1px solid var(--border);';
      const text = document.createElement('span'); text.style.cssText = 'flex:1;min-width:160px;overflow-wrap:anywhere;';
      text.textContent = `${server.name} · ${server.enabled ? '已启用' : '已停用'} · ${server.allowed_tools.length} 个工具 · ${server.allowed_chats.length} 个私聊 / ${server.allowed_groups.length} 个群`;
      if (server.kind === 'hrzh_person') text.textContent = `${server.name} · 项目管理用户：${server.allowed_chats[0]} · ${server.enabled ? '已启用' : '已停用'} · ${server.allowed_tools.length} 个工具 · ${server.has_headers ? 'Key 已配置' : '未配置 Key'}`;
      const change = document.createElement('button'); change.type = 'button'; change.className = 'btn btn-load'; change.textContent = '编辑'; change.onclick = () => edit(server);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn btn-load'; remove.textContent = '删除';
      remove.onclick = () => {
        if (window.confirm(`删除 MCP 服务“${server.name}”？`)) action(async () => {
          await request(`servers/${encodeURIComponent(server.id)}`, 'DELETE');
          if (editingId === server.id) { el('mcp-editor').hidden = true; revision++; }
          await load(); status('服务已删除。');
        });
      };
      row.append(text, change, remove); list.append(row);
    }
  }
  el('mcp-add-person').onclick = () => edit({kind: 'hrzh_person', name: '项目管理系统'});
  el('mcp-add').onclick = () => edit();
  el('mcp-cancel').onclick = () => { el('mcp-editor').hidden = true; el('mcp-headers').value = ''; el('mcp-person-key').value = ''; revision++; };
  el('mcp-editor').addEventListener('input', () => revision++);
  el('mcp-save-settings').onclick = () => action(async () => {
    await request('settings', 'POST', {enabled: el('mcp-enabled').checked, max_rounds: Number(el('mcp-rounds').value), total_timeout: Number(el('mcp-total-timeout').value)});
    status('MCP 总设置已保存，下次对话生效。');
  });
  el('mcp-test').onclick = () => action(async () => {
    const data = draft(), currentRevision = revision;
    status('正在连接服务并获取工具…', false, 'mcp-test-status');
    try {
      const result = await request('test', 'POST', data);
      if (currentRevision !== revision) { status('配置已变更，请重新测试。', true, 'mcp-test-status'); return; }
      const names = new Set(result.tools.map(t => t.name));
      renderTools(result.tools, editingKind === 'hrzh_person' ? data.allowed_tools.filter(n => names.has(n)) : data.allowed_tools);
      if (result.identity) {
        const who = result.identity;
        status(`验证成功 · 人员：${who.person_id} · 类别：${who.category || '未提供'} · 权限：${who.access || '未提供'}
服务目录 ${who.catalog_count} 个工具，此 Key 可用 ${result.tools.length} 个。勾选所需工具后保存。`, false, 'mcp-test-status');
        return;
      }
      status(`连接成功，发现 ${result.tools.length} 个工具。勾选所需工具后保存服务。`, false, 'mcp-test-status');
    } catch (error) { status(error.message, true, 'mcp-test-status'); throw error; }
  });
  el('mcp-save-server').onclick = () => action(async () => {
    const data = draft();
    if (data.enabled && (!data.allowed_tools.length || !(data.allowed_chats.length || data.allowed_groups.length))) {
      throw new Error('启用服务前，请选择工具并填写至少一个完整的授权会话。');
    }
    await request('servers', 'POST', data);
    el('mcp-headers').value = ''; el('mcp-person-key').value = ''; el('mcp-editor').hidden = true; revision++;
    await load(); status('MCP 服务已保存。请确认总开关已启用，并在授权会话中测试。');
  });
  action(load);
})();
