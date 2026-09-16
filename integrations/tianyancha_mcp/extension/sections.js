// Runs in Chrome's isolated world. Reads rendered DOM only; no cookies, private APIs,
// framework stores or official MCP. Side effects are limited to scrolling/pagination.
function extractSection(job) {
  const clean = value => String(value || '').replace(/[\uE000-\uF8FF]/g, '').replace(/\s+/g, ' ').trim();
  const visible = el => !!el && !el.closest('[hidden],[aria-hidden="true"]') &&
    getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden' && !!el.getClientRects().length;
  const txt = el => clean(el?.innerText || '');
  const source = {provider: 'tianyancha', access_method: 'browser', url: location.href,
    fetched_at: new Date().toISOString(), source_updated_at: null};
  const body = document.body?.innerText || '';
  const error = (code, message) => ({error: `${code}: ${message}`});
  if (location.origin !== 'https://www.tianyancha.com' || location.href.split('#')[0] !== job.url)
    return error('SOURCE_CHANGED', 'page URL does not match the requested entity');
  if (/安全验证|访问验证|请输入验证码|拖动滑块/.test(document.title + body.slice(0, 2000)))
    return error('HUMAN_VERIFICATION_REQUIRED', 'complete verification in Chrome');
  if (/访问过于频繁|操作过于频繁/.test(body.slice(0, 2000)))
    return error('RATE_LIMITED', 'wait before querying again');
  const heading = txt(document.querySelector('h1'));
  const result = (status, extra = {}) => ({schema_version: 2, status, company_id: job.company_id, company_name: job.person_id ? null : heading,
    ...(job.person_id ? {person_id: job.person_id, person_name: heading} : {}),
    dimension: job.section || null, view: job.view || 'default', source, coverage: {scope: 'current_website_view', complete: false,
      risk_conclusion_allowed: false}, ...extra});
  const pending = message => ({pending: true, message});
  const current = globalThis.__tycReadJob;
  const state = current?.id === job.id ? current : (globalThis.__tycReadJob = {id: job.id, ticks: 0, page: 1});
  state.ticks++;
  const headings = [...document.querySelectorAll('h3,[role="heading"][aria-level="3"]')].filter(visible);
  const sectionRoot = label => {
    const h = headings.find(h => txt(h).replace(/\s*(s?vip)\s*$/i, '') === label);
    // Observed current website component boundary. Fail closed on redesign rather
    // than using the entire body and attributing other sections to this dimension.
    if (job.operation === 'get_person_section') {
      let root = h?.parentElement;
      for (let i = 0; root && i < 5; i++, root = root.parentElement) {
        if (root.querySelectorAll('h3').length > 1) break;
        if (root.querySelector('table') || gate(root)) return root;
      }
      return null;
    }
    return h?.closest('.dim-section') || null;
  };
  const counts = label => {
    const found = [...document.querySelectorAll('a,span')].filter(visible).map(txt)
      .map(t => t.match(new RegExp('^' + label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*([0-9,]+)(?:\\s|$)')))
      .filter(Boolean).map(m => Number(m[1].replaceAll(',', '')));
    return found.length && found.every(n => n === found[0]) ? found[0] : null;
  };
  const gate = root => {
    const text = txt(root);
    if (/登录后|登录查看|请先登录|扫码登录/.test(text)) return 'auth_required';
    if (/立即支付|超级会员套餐|开通.{0,8}会员.{0,8}查看|升级.{0,8}会员|购买后查看/.test(text)) return 'permission_denied';
    return null;
  };
  const linksOf = root => [...root.querySelectorAll('a[href]')].filter(visible).flatMap(a => {
    try {
      const url = new URL(a.getAttribute('href'), location.href);
      if (url.origin !== location.origin || !/^\/(company\/\d+|human\/\d+-c\d+|annualReport\/\d+\/\d{4}|judicialcase\/detail\/\d+\/[a-zA-Z0-9-]+)(?:[/?#]|$)/.test(url.pathname)) return [];
      const label = txt(a);
      if (!label) return [];
      return [{label, url: url.href, company_id: url.pathname.match(/^\/company\/(\d+)/)?.[1] || null,
        person_id: url.pathname.match(/^\/human\/(\d+)-c/)?.[1] || null}];
    } catch { return []; }
  });
  const tableData = root => [...root.querySelectorAll('table')].filter(t => visible(t) && !t.parentElement.closest('table'))
    .map(table => {
      const rows = [...table.rows].filter(visible);
      const headerRow = rows.find(r => r.querySelector('th'));
      const headers = headerRow ? [...headerRow.cells].map(txt) : [];
      const records = rows.filter(r => r.closest('table') === table && r !== headerRow && [...r.cells].some(c => c.tagName === 'TD'));
      return {headers, records};
    });
  let cellsTruncated = false;
  const serialize = (tables, limit, offset = 0) => {
    let remaining = limit, skip = offset;
    return tables.map(({headers, records}) => {
      const start = Math.min(skip, records.length); skip -= start;
      const selected = records.slice(start, start + remaining); remaining -= selected.length;
      return {headers, rows: selected.map(row => ({cells: [...row.cells].map(c => { const value = txt(c); if(value.length > 2500) cellsTruncated = true; return value.slice(0, 2500); }), links: linksOf(row).slice(0, 12)}))};
    });
  };
  if (job.operation === 'get_document') {
    const main = document.querySelector('main') || document.querySelector('#page-root') || document.body;
    const documentText = txt(main);
    const blocked = gate(main);
    if (blocked) return result(blocked, {message: 'Document requires login or additional membership; not an empty result.'});
    const tables = tableData(main);
    const markers = job.document_kind === 'annual_report' ? /企业资产状况|资产总额|企业基本信息/ : /案件详情|案件信息|案件进程|诉讼参与人|案件概况/;
    if (!markers.test(documentText)) return state.ticks < 12 ? pending('Waiting for document') : result('source_changed', {message: 'Expected document markers not found.'});
    const offset = job.offset || 0, max = 6500;
    return result('partial', {document_kind: job.document_kind, text: documentText.slice(offset, offset + max),
      next_offset: documentText.length > offset + max ? offset + max : null,
      tables: serialize(tables, 10), links: linksOf(main).slice(0, 30),
      warnings: ['Website document only; undisclosed or redacted amounts must not be interpreted as zero.']});
  }
  if (!heading) return pending('Waiting for company identity');
  if (job.operation === 'get_capabilities') {
    if (!headings.length && state.ticks < 12) { window.scrollTo(0, 650); return pending('Waiting for category sections'); }
    return result('partial', {group: job.group, dimensions: job.sections.map(label => {
      const root = sectionRoot(label), count = counts(label);
      return {dimension: label, reported_count: count, status: root ? (gate(root) || 'available') :
        (count === 0 ? 'reported_zero' : 'not_observed'), checked: false,
        note: 'Discovery only; query this dimension for evidence and pagination.'};
    }), warnings: ['Availability is observed for this category only, not a complete due diligence report.']});
  }
  const root = sectionRoot(job.section);
  if (!root) {
    if (state.ticks < 12) {
      const nav = [...document.querySelectorAll('a')].find(a => visible(a) &&
        txt(a).replace(/[\s\d,]+$/g, '') === job.section && new URL(a.href, location.href).pathname === location.pathname);
      if (nav && !state.scrolled) { nav.scrollIntoView({block:'center'}); nav.click(); state.scrolled = true; }
      else window.scrollTo(0, 650);
      return pending('Waiting for requested section');
    }
    const count = counts(job.section);
    return result(count === 0 ? 'reported_zero' : 'not_disclosed', {reported_count: count,
      message: count === 0 ? 'Website explicitly reports zero; no independent no-risk conclusion.' :
        'No readable section or explicit zero found. This is not evidence of no records.'});
  }
  if (!state.scrolled) { root.scrollIntoView({block: 'center'}); state.scrolled = true; return pending('Loading section'); }
  if (job.view && !state.viewSelected) {
    const normalize = t => t.replace(/[（]/g, '(').replace(/[）]/g, ')').replace(/\s*\d+\s*$/, '').trim();
    const targets = [...root.querySelectorAll('span,a,button,div')].filter(n => visible(n) &&
      !n.closest('table,h3') && !n.querySelector('h3,table') && normalize(txt(n)) === job.view &&
      (!n.hasAttribute('href') || new URL(n.href, location.href).pathname === location.pathname));
    const target = targets.find(n => !targets.some(other => other !== n && n.contains(other)));
    if (!target) return result('view_unavailable', {message: 'Requested tab is not visible; no default-tab substitute returned.'});
    const selected = n => /(?:active|selected|checked)/i.test(n.className || '') || n.getAttribute('aria-selected') === 'true';
    if (selected(target) || selected(target.parentElement)) state.viewSelected = true;
    else if (!state.viewClicked) {
      state.viewClicked = true; state.viewBefore = txt(root); target.click(); return pending('Switching selected section tab');
    } else if (txt(root) !== state.viewBefore && (selected(target) || selected(target.parentElement))) state.viewSelected = true;
    else return pending('Waiting for verified selected tab');
  }
  const blocked = gate(root);
  if (blocked) return result(blocked, {reported_count: counts(job.section), message: 'Section is restricted; not no records.'});
  const raw = txt(root);
  const tables = tableData(root);
  const rowCount = tables.reduce((n,t) => n + t.records.length, 0);
  const links = linksOf(root);
  let paginator = root.querySelector('[class*="pagination"],[class*="Pagination"]');
  if (!paginator) {
    // Semantic fallback for hashed CSS modules: a bounded, visible numeric pager,
    // never table cells or a category navigation containing headings.
    const candidates = [...root.querySelectorAll('nav,ul,div')].filter(n => visible(n) &&
      !n.closest('table') && !n.querySelector('table,h3') && txt(n).length < 180 &&
      n.querySelectorAll('li,a,button').length >= 2 &&
      [...n.querySelectorAll('li,a,button')].filter(c => /^\d+$/.test(txt(c))).length >= 2);
    paginator = candidates.find(n => !candidates.some(other => other !== n && n.contains(other)));
  }
  const pageNodes = paginator ? [...paginator.querySelectorAll('li,a,button')].filter(visible) : [];
  const active = pageNodes.find(n => n.getAttribute('aria-current') === 'page' || /(?:^|[ _-])active(?:$|[ _-])/.test(n.className || ''));
  const currentPage = active && /^\d+$/.test(txt(active)) ? Number(txt(active)) : (paginator ? null : 1);
  const fingerprint = tables.map(t => t.records.map(txt).join('|')).join('||');
  if (paginator && currentPage === null) return result('page_unavailable', {message: 'Cannot verify active page; no rows returned.'});
  if (state.switching) {
    if (fingerprint === state.switching.fingerprint || currentPage !== state.switching.target)
      return pending('Waiting for changed rows and selected page');
    state.page = currentPage; state.switching = null;
  }
  if (currentPage !== (job.page || 1)) {
    const enabled = n => n.getAttribute('aria-disabled') !== 'true' && !/disabled/.test(n.className || '') && !n.disabled;
    let target = pageNodes.find(n => txt(n) === String(job.page) && enabled(n));
    let targetPage = job.page;
    if (!target && currentPage < job.page) {
      target = pageNodes.find(n => enabled(n) && (/next|下一页/i.test((n.className || '') + (n.getAttribute('aria-label') || '') + (n.getAttribute('title') || ''))));
      targetPage = currentPage + 1;
    }
    if (!target) return result('page_unavailable', {message: 'Requested page is not available in this section; returned no substitute page.', requested_page: job.page});
    state.switching = {fingerprint, target: targetPage};
    target.click();
    return pending('Switching section page');
  }
  if (job.operation === 'get_section_detail') {
    if (!state.detailClicked) {
      const rows = tables.flatMap(t => t.records);
      const row = rows[job.row_index - 1];
      const details = row && [...row.querySelectorAll('a,button,span')].find(n => visible(n) && /^(查看)?详情$/.test(txt(n)) && (!n.hasAttribute('href') || /^(#|javascript:)/.test(n.getAttribute('href'))));
      if (!details) return result('detail_unavailable', {message: 'No supported detail action for this row; use returned case/annual-report links where provided.'});
      state.detailClicked = true; details.click(); return pending('Opening detail dialog');
    }
    const dialog = [...document.querySelectorAll('[role="dialog"],[class*="modal-content"],[class*="modalContent"]')].find(visible);
    if (!dialog) return pending('Waiting for detail dialog');
    const restriction = gate(dialog);
    if (restriction) return result(restriction, {message: 'Detail is restricted.'});
    const detail = txt(dialog);
    if (!detail || /加载中/.test(detail)) return pending('Waiting for detail content');
    return result('partial', {row_index: job.row_index, page: currentPage, detail: detail.slice(0, 8500),
      truncated: detail.length > 8500, tables: serialize(tableData(dialog), 10), links: linksOf(dialog).slice(0,20)});
  }
  const reported = counts(job.section);
  if (!rowCount && /暂无(?:相关)?(?:数据|信息|记录)|未查询到|暂无记录/.test(raw))
    return result('no_records', {reported_count: reported, evidence: raw.slice(0,800), tables: [],
      coverage: {scope: 'current_website_section', complete: true, risk_conclusion_allowed: false}});
  // Headings and marketing/graph labels alone are not data.
  if (!rowCount && !links.length) return state.ticks < 12 ? pending('Waiting for records') :
    result('source_changed', {message: 'Section exists but no supported table/link data was found; inspect the page.', evidence: raw.slice(0,1500)});
  let limit = job.limit || 10;
  const offset = job.offset || 0;
  let serialized = serialize(tables, limit, offset);
  while (JSON.stringify(serialized).length > 7000 && limit > 1) {
    limit--; serialized = serialize(tables, limit, offset);
  }
  const recordCount = rowCount || links.length;
  const moreInPage = recordCount > offset + limit;
  const hasNextPage = pageNodes.some(n => /^\d+$/.test(txt(n)) && Number(txt(n)) > currentPage) ||
    pageNodes.some(n => /next/i.test((n.className || '') + (n.getAttribute('aria-label') || '')) &&
      n.getAttribute('aria-disabled') !== 'true' && !/disabled/.test(n.className || ''));
  const partial = cellsTruncated || moreInPage || hasNextPage || currentPage > 1 || offset > 0 || reported === null || reported > recordCount || tables.length > 1;
  return result(partial ? 'partial' : 'ok', {reported_count: reported, tables: serialized, cells_truncated: cellsTruncated,
    links: !rowCount ? links.slice(offset, offset + limit) : [],
    pagination: {page: currentPage, limit, offset, rows_on_page: recordCount,
      next_offset: moreInPage ? offset + limit : null, has_more_pages: hasNextPage,
      next_page: hasNextPage ? currentPage + 1 : null, complete: !partial},
    coverage: {scope: 'current_website_section', complete: !partial, risk_conclusion_allowed: false},
    warnings: ['Only the selected visible tab/filter is read. Unqueried history, related entities and hidden subtabs are not covered.',
      'Website relationships and controllers are provider statements; representative/beneficiary status alone does not establish ownership.']});
}
