// Self-contained: injected into the isolated world of a Tianyancha tab.
function extractPage(job) {
  const text = document.body?.innerText || '';
  const title = document.title;
  if (/安全验证|访问验证|请输入验证码|拖动滑块/.test(title + '\n' + text.slice(0, 2000)))
    return {error: 'HUMAN_VERIFICATION_REQUIRED: complete verification in Chrome'};
  if (/访问过于频繁|操作过于频繁/.test(text.slice(0, 2000)))
    return {error: 'RATE_LIMITED: wait before querying again'};
  if (/登录后查看|登录后可查看|请先登录/.test(text.slice(0, 2500)))
    return {error: 'AUTH_REQUIRED: sign in to Tianyancha in Chrome'};
  const source = {provider: 'tianyancha', access_method: 'browser', url: location.href,
    fetched_at: new Date().toISOString(), source_updated_at: null};
  if (job.operation === 'search_companies') {
    const seen = new Set();
    const candidates = [...document.querySelectorAll('a[href]')].flatMap(a => {
      const url = new URL(a.href, location.href);
      const match = url.hostname === 'www.tianyancha.com' && url.pathname.match(/^\/company\/(\d+)$/);
      const name = a.innerText.trim();
      if (!match || !name || seen.has(match[1])) return [];
      seen.add(match[1]);
      return [{company_id: match[1], name, source_url: url.href}];
    });
    const count = text.match(/为您找到\s*([\d,]+)\s*条相关结果/);
    const empty = /没有找到相关|未找到相关|为您找到\s*0\s*条相关结果/.test(text);
    if (!count && !empty) return {error: 'SOURCE_CHANGED: search result marker missing'};
    if (!candidates.length && !empty) return {error: 'SOURCE_CHANGED: result links missing'};
    return {status: 'partial', data: {candidates: empty ? [] : candidates.slice(0, job.limit)}, source,
      pagination: {page: 1, returned_count: empty ? 0 : Math.min(candidates.length, job.limit),
        reported_total: count ? Number(count[1].replaceAll(',', '')) : 0,
        complete: empty, has_more: empty ? false : null},
      warnings: ['Only first-page company links are extracted; verify candidates with company details.']};
  }
  const heading = document.querySelector('h1')?.innerText.trim();
  if (!heading || !text.includes('工商信息')) return {error: 'SOURCE_CHANGED: company profile markers missing'};
  const labels = {'企业名称':'name', '统一社会信用代码':'credit_code', '登记状态':'registration_status',
    '成立日期':'established_date', '注册资本':'registered_capital_raw', '实缴资本':'paid_capital_raw',
    '注册地址':'registered_address', '登记机关':'registration_authority', '经营范围':'business_scope',
    '法定代表人':'legal_representative_raw'};
  const data = {company_id: job.company_id, heading_raw: heading};
  // Only read the registration table, never infer from unrelated relationship tables.
  const table = [...document.querySelectorAll('table')].find(t => t.innerText.includes('统一社会信用代码') && t.innerText.includes('登记机关'));
  if (!table) return {error: 'SOURCE_CHANGED: registration table missing'};
  for (const row of table.rows) {
    const cells = [...row.cells];
    for (let i = 0; i < cells.length - 1; i++) {
      const label = cells[i].innerText.replace(/[\s\uE000-\uF8FF]/g, '');
      if (labels[label] && !data[labels[label]]) data[labels[label]] = cells[i + 1].innerText.trim().slice(0, 5000);
    }
  }
  if (!data.credit_code) return {error: 'SOURCE_CHANGED: credit code missing from registration table'};
  const updated = text.match(/(\d{4}-\d{2}-\d{2})更新/);
  source.source_updated_at = updated?.[1] || null;
  const missing_fields = Object.values(labels).filter(k => !data[k]);
  return {status: missing_fields.length ? 'partial' : 'ok', data, source, missing_fields};
}
