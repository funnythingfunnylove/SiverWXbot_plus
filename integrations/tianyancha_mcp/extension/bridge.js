let endpoint = 'http://127.0.0.1:18765';
let running = false, workingTab = null;
const status = document.querySelector('#status');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function request(path, token, body) {
  const response = await fetch(endpoint + path, {method: body ? 'POST' : 'GET',
    headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
    ...(body ? {body: JSON.stringify(body)} : {}), credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(5000)});
  if (!response.ok) throw new Error(`Bridge HTTP ${response.status}`);
  return response.json();
}
async function execute(job) {
  const url = new URL(job.url);
  if (url.origin !== 'https://www.tianyancha.com' ||
      !['search_companies', 'get_company'].includes(job.operation) ||
      (job.operation === 'get_company' ? !/^\/company\/\d+$/.test(url.pathname) : url.pathname !== '/search'))
    throw new Error('INVALID_JOB: unsupported operation or URL');
  if (workingTab !== null) {
    try { await chrome.tabs.get(workingTab); } catch { workingTab = null; }
  }
  if (workingTab === null) workingTab = (await chrome.tabs.create({url: job.url, active: false})).id;
  else await chrome.tabs.update(workingTab, {url: job.url});
  const deadline = Date.now() + 35000;
  let last = null;
  while (Date.now() < deadline && running) {
    const tab = await chrome.tabs.get(workingTab);
    if (tab.status === 'complete' && tab.url === job.url) {
      const results = await chrome.scripting.executeScript({target: {tabId: workingTab}, func: extractPage, args: [job]});
      last = results[0]?.result;
      if (last && (!last.error || !last.error.startsWith('SOURCE_CHANGED'))) return last;
    }
    await delay(700);
  }
  return last || {error: 'UPSTREAM_TIMEOUT: page did not become ready; inspect the working tab'};
}
document.querySelector('#disconnect').onclick = () => { running = false; status.textContent = '正在断开'; };
document.querySelector('#connect').onclick = async () => {
  if (running) return;
  const token = document.querySelector('#token').value.trim();
  let address;
  try {
    address = new URL(document.querySelector('#endpoint').value.trim());
    if (!['http:', 'https:'].includes(address.protocol) || address.username || address.password || address.search || address.hash)
      throw new Error('请输入不含凭据、参数或片段的 HTTP(S) 地址');
    if (address.protocol !== 'https:' && !['127.0.0.1', 'localhost', '[::1]'].includes(address.hostname))
      throw new Error('跨电脑连接需要 HTTPS 地址');
  } catch (error) { status.textContent = error.message; return; }
  if (token.length < 32) { status.textContent = '请输入完整配对令牌'; return; }
  document.querySelector('#connect').disabled = true;
  try {
    const allowed = await chrome.permissions.request({origins: [address.origin + '/*']});
    if (!allowed) throw new Error('未授予该后台地址的访问权限');
    endpoint = address.href.replace(/\/$/, '');
    running = true;
    while (running) {
      const {job} = await request('/job', token);
      status.textContent = job ? '正在查询天眼查…' : '已连接，等待查询';
      if (job) {
        let result;
        try { result = await execute(job); } catch (error) { result = {error: String(error)}; }
        await request('/result', token, {id: job.id, result});
      }
      await delay(750);
    }
    status.textContent = '已断开';
  } catch (error) { status.textContent = '连接中断：' + error.message; }
  finally { running = false; document.querySelector('#connect').disabled = false; }
};
