(() => {
  'use strict';
  const el = id => document.getElementById('company-' + id);
  const root = document.getElementById('tab-company');
  const base = new URL('./api/company/', location.href);
  let busy = false;
  const message = (text, setup = false) => { el(setup ? 'setup-message' : 'message').textContent = text; };
  async function request(path, data) {
    const response = await fetch(new URL(path, base), {
      method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-Company-Request': '1'},
      ...(data === undefined ? {} : {body: JSON.stringify(data)}), signal: AbortSignal.timeout(55000)
    });
    let value;
    try { value = await response.json(); } catch { throw new Error('后台未返回有效数据，请检查登录状态和网络'); }
    if (!response.ok || value.status !== 'success') throw new Error(value.message || '请求失败');
    return value;
  }
  async function action(work, setup = false) {
    if (busy) return;
    busy = true;
    root.querySelectorAll('button').forEach(b => b.disabled = true);
    try { await work(); } catch (error) { message(error.name === 'TimeoutError' ? '查询等待超时，请检查连接后重试' : error.message, setup); }
    finally { busy = false; root.querySelectorAll('button').forEach(b => b.disabled = false); }
  }
  async function refresh() {
    const state = await request('status');
    el('connection').textContent = state.busy ? '正在等待浏览器查询结果' : (state.connected ? '浏览器已连接' : '浏览器未连接');
  }
  function sourceLink(url, label) {
    try {
      const parsed = new URL(url);
      if (parsed.origin !== 'https://www.tianyancha.com' || !/^\/company\/\d+$/.test(parsed.pathname)) return null;
      const a = document.createElement('a'); a.href = parsed.href; a.textContent = label; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
    } catch { return null; }
  }
  function clearPair() { el('pair-token').value = ''; el('pair-box').hidden = true; }
  const labels = {name:'企业名称',credit_code:'统一社会信用代码',registration_status:'登记状态',established_date:'成立日期',registered_capital_raw:'注册资本',paid_capital_raw:'实缴资本',registered_address:'注册地址',registration_authority:'登记机关',business_scope:'经营范围',legal_representative_raw:'法定代表人（页面原文）'};
  async function detail(id) {
    el('detail-card').hidden = true;
    message('正在读取企业工商信息…');
    const {result} = await request('detail', {company_id: id});
    el('detail-title').textContent = result.data?.name || '企业详情';
    el('detail').replaceChildren();
    for (const [key, label] of Object.entries(labels)) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = result.data?.[key] || '未取得'; el('detail').append(dt, dd);
    }
    el('detail-note').textContent = `采集时间：${result.source?.fetched_at || '未知'}；页面更新日期：${result.source?.source_updated_at || '未提供'}。缺失字段不表示不存在。`;
    el('source').replaceChildren();
    const link = sourceLink(result.source?.url, '在天眼查查看原始资料'); if (link) el('source').append(link);
    el('detail-card').hidden = false;
    message(result.status === 'partial' ? '已取得部分工商字段，请核对原始页面。' : '企业详情已加载。');
  }
  el('search').onclick = () => action(async () => {
    const keyword = el('keyword').value.trim();
    if (!keyword) throw new Error('请输入企业名称或关键词');
    el('results').replaceChildren(); el('detail-card').hidden = true;
    message('正在查询天眼查，请稍候…');
    const {result} = await request('search', {keyword});
    const candidates = result.data?.candidates || [];
    for (const company of candidates) {
      const row = document.createElement('div'); row.className = 'company-result';
      const name = document.createElement('strong'); name.textContent = company.name;
      const controls = document.createElement('div'); controls.className = 'company-actions';
      const button = document.createElement('button'); button.type = 'button'; button.textContent = '查看工商信息';
      button.onclick = () => action(() => detail(company.company_id)); controls.append(button);
      const link = sourceLink(company.source_url, '天眼查原页'); if (link) controls.append(link);
      row.append(name, controls); el('results').append(row);
    }
    message(candidates.length ? `已显示 ${candidates.length} 个候选。仅查询第一页，可能包含关联企业，请查看详情确认。` : '未找到相关企业。');
  });
  el('keyword').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); el('search').click(); } });
  el('refresh').onclick = () => action(refresh);
  el('pair').onclick = () => action(async () => {
    clearPair(); const result = await request('pair', {});
    el('bridge-url').value = new URL('bridge', base).href;
    el('pair-token').value = result.token; el('pair-box').hidden = false;
    message('新令牌已生成，旧连接已失效。请将地址和令牌填入 Chrome 扩展后连接。', true);
    await refresh();
  }, true);
  el('disconnect').onclick = () => action(async () => { await request('disconnect', {}); clearPair(); await refresh(); message('浏览器配对已撤销。', true); }, true);
  el('copy-token').onclick = () => action(async () => {
    try { await navigator.clipboard.writeText(el('pair-token').value); message('令牌已复制。', true); }
    catch { el('pair-token').focus(); el('pair-token').select(); message('请按 Ctrl+C（Mac 为 ⌘C）复制所选令牌。', true); }
  }, true);
  el('hide-token').onclick = clearPair;
  document.querySelector('[data-tab="tab-company"]').addEventListener('click', () => action(refresh));
})();
