const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../extension/extract.js'), 'utf8');
function extract(job, {text = '', title = '', anchors = [], heading = '', tables = []} = {}) {
  const context = {URL, location: {href: job.url}, document: {title, body: {innerText: text},
    querySelector: () => ({innerText: heading}),
    querySelectorAll: selector => selector === 'a[href]' ? anchors : tables}, job};
  vm.createContext(context);
  return JSON.parse(JSON.stringify(vm.runInContext(source + '\nextractPage(job)', context)));
}
const search = {operation: 'search_companies', url: 'https://www.tianyancha.com/search?key=test', limit: 1};
test('search deduplicates, limits and reports partial with source', () => {
  const result = extract(search, {text: '为您找到 12 条相关结果', anchors: [
    {href: 'https://www.tianyancha.com/company/123', innerText: '测试公司'},
    {href: 'https://www.tianyancha.com/company/123', innerText: '重复'},
    {href: 'https://www.tianyancha.com/company/456', innerText: '另一家'}]});
  assert.equal(result.status, 'partial');
  assert.equal(result.data.candidates.length, 1);
  assert.equal(result.data.candidates[0].company_id, '123');
  assert.equal(result.source.access_method, 'browser');
  assert.equal(result.pagination.reported_total, 12);
  assert.equal(result.pagination.complete, false);
});
test('explicit empty results differ from a changed page', () => {
  assert.deepEqual(extract(search, {text: '为您找到 0 条相关结果'}).data.candidates, []);
  assert.match(extract(search, {text: '未知页面'}).error, /SOURCE_CHANGED/);
});
test('login, human verification and rate limiting fail explicitly', () => {
  for (const [text, code] of [['请先登录', 'AUTH_REQUIRED'], ['安全验证', 'HUMAN_VERIFICATION_REQUIRED'],
    ['访问过于频繁', 'RATE_LIMITED']]) assert.match(extract(search, {text}).error, new RegExp(code));
});
test('company profile retains raw fields and identifies missing fields', () => {
  const table = {innerText: '统一社会信用代码 登记机关', rows: [
    {cells: [{innerText: '统一社会信用代码'}, {innerText: 'TEST123'}]},
    {cells: [{innerText: '注册资本'}, {innerText: '100万元'}]}]};
  const result = extract({operation: 'get_company', company_id: '123', url: 'https://www.tianyancha.com/company/123'},
    {text: '工商信息', heading: '测试公司', tables: [table]});
  assert.equal(result.data.credit_code, 'TEST123');
  assert.equal(result.data.registered_capital_raw, '100万元');
  assert.equal(result.status, 'partial');
  assert.ok(result.missing_fields.includes('legal_representative_raw'));
  assert.equal(result.data.actual_controller, undefined);
});
