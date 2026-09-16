const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(path.join(__dirname, '../extension/sections.js'), 'utf8');
const url = 'https://www.tianyancha.com/company/123/jingxian';
function fixture(html, args={}) {
  const dom = new JSDOM(`<h1>Fixture Company</h1>${html}`, {url, runScripts:'outside-only'});
  const w = dom.window;
  Object.defineProperty(w.HTMLElement.prototype, 'innerText', {get() {return this.textContent;}});
  w.HTMLElement.prototype.getClientRects = function(){return [{}];};
  w.HTMLElement.prototype.scrollIntoView = function(){};
  w.scrollTo = function(){};
  w.eval(script);
  const job = {id:'fixture', operation:'get_section', section:'股权出质', url, company_id:'123', page:1, limit:10, ...args};
  return {w, job, read:()=>JSON.parse(JSON.stringify(w.extractSection(job))),
    settle:()=> {let r;for(let i=0;i<15;i++){r=w.extractSection(job);if(!r.pending) break;}return JSON.parse(JSON.stringify(r));}};
}
const table = `<table><tr><th>序号</th><th>出质人</th><th>质权人</th><th>出质股权数额</th></tr>
<tr><td>1</td><td><a href='/company/123'>Fixture Company</a></td><td><a href='/company/456'>Lender</a></td><td>400万元</td></tr></table>`;
const section = (body) => `<div class='dim-section'><h3>股权出质</h3>${body}</div>`;
test('scopes records and gates to selected dimension, never another section',()=>{
 const f=fixture(`<span>股权出质1</span>${section(table)}<div class='dim-section'><h3>协同股东</h3>超级会员套餐 立即支付</div>`);
 const r=f.settle();assert.equal(r.status,'ok');assert.equal(r.tables[0].rows[0].cells[3],'400万元');
 assert.equal(r.tables[0].rows[0].links[1].company_id,'456');assert.equal(r.coverage.risk_conclusion_allowed,false);
});
test('missing dimensions and explicit zero stay distinct from verified empty section',()=>{
 assert.equal(fixture(table).settle().status,'not_disclosed');
 assert.equal(fixture('<span>股权出质0</span>').settle().status,'reported_zero');
 assert.equal(fixture(section('暂无相关数据')).settle().status,'no_records');
});
test('login and membership are not no-records even if navigation has a zero',()=>{
 for(const [body,expected] of [['登录后查看更多信息','auth_required'],['超级会员套餐 立即支付','permission_denied']]){
  assert.equal(fixture(`<span>股权出质0</span>${section(body)}`).settle().status,expected);
 }
});
test('detail page cannot be attributed to wrong entity',()=>{
 const f=fixture(section(table),{url:'https://www.tianyancha.com/company/999/jingxian'});
 assert.match(f.read().error,/SOURCE_CHANGED/);
});
test('pagination waits for active page AND changed rows',()=>{
 const f=fixture(section(table+`<ul class='pagination'><li class='active'>1</li><li>2</li></ul>`),{page:2});
 assert.equal(f.read().pending,true);assert.equal(f.read().pending,true);
 const nodes=f.w.document.querySelectorAll('li');nodes[0].className='';nodes[1].className='active';
 assert.equal(f.read().pending,true);
 f.w.document.querySelector('td').textContent='2';
 const r=f.read();assert.equal(r.pagination.page,2);assert.equal(r.tables[0].rows[0].cells[0],'2');assert.equal(r.coverage.complete,false);
});
test('unknown current page never returns page one as requested later page',()=>{
 assert.equal(fixture(section(table+`<ul class='pagination'><li>1</li><li>2</li></ul>`),{page:2}).settle().status,'page_unavailable');
});
test('page local slicing exposes next_offset without losing rows',()=>{
 const f=fixture(section(table.replace('</table>',`<tr><td>2</td><td>Second</td><td>Lender</td><td>20万</td></tr></table>`)),{limit:1});
 const r=f.settle();assert.equal(r.pagination.next_offset,1);assert.equal(r.tables[0].rows.length,1);
});
test('capability discovery observes gates and leaves coverage unchecked',()=>{
 const r=fixture(section('超级会员套餐'),{operation:'get_capabilities',group:'risk',sections:['股权出质','对外担保']}).settle();
 assert.equal(r.dimensions[0].status,'permission_denied');assert.equal(r.dimensions[0].checked,false);
 assert.equal(r.dimensions[1].status,'not_observed');
});
test('details click only an existing detail control, never export or external link',()=>{
 const f=fixture(section(table.replace('400万元','400万元<span>详情</span><button>导出</button>')),{operation:'get_section_detail',row_index:1});
 let exported=false;f.w.document.querySelector('button').onclick=()=>exported=true;
 f.w.document.querySelector('td span').onclick=()=>{
  const d=f.w.document.createElement('div');d.setAttribute('role','dialog');d.textContent='股权出质登记 400万元';f.w.document.body.append(d);
 };
 const r=f.settle();assert.equal(r.detail,'股权出质登记 400万元');assert.equal(exported,false);
});
test('risk markers and disclosure boundaries preserved',()=>{
 const f=fixture('安全验证');assert.match(f.read().error,/HUMAN_VERIFICATION_REQUIRED/);
 const d=fixture('企业资产状况 企业选择不公示', {operation:'get_document',document_kind:'annual_report'}).settle();
 assert.equal(d.status,'partial');assert.match(d.text,/不公示/);assert.equal(d.coverage.complete,false);
});
test('browser-saved current website markup extracts a pledge row',()=>{
 const html=fs.readFileSync(path.join(__dirname,'fixtures/pledge-section.html'),'utf8');
 const r=fixture(html).settle();assert.equal(r.reported_count,1);assert.equal(r.tables[0].rows.length,1);
 assert.ok(r.tables[0].headers.includes('出质股权数额'));assert.equal(r.tables[0].rows[0].cells[5],'400万元');
});
test('person section respects precise person/company context and separate roles',()=>{
 const f=fixture(`<div><h3>担任高管</h3>${table}</div><div><h3>担任股东</h3>暂无相关数据</div>`,
  {operation:'get_person_section',person_id:'789',section:'担任高管'});
 const r=f.settle();assert.equal(r.person_id,'789');assert.equal(r.company_name,null);assert.equal(r.tables[0].rows.length,1);
});
test('large rows return partial with explicit truncation',()=>{
 const r=fixture(`<span>股权出质1</span>${section(table.replace('400万元','x'.repeat(4000)))}`).settle();
 assert.equal(r.cells_truncated,true);assert.equal(r.coverage.complete,false);assert.equal(r.status,'partial');
});
test('nested change table rows are not counted twice',()=>{
 const r=fixture(section(table.replace('400万元','<table><tr><td>before</td><td>after</td></tr></table>'))).settle();
 assert.equal(r.tables[0].rows.length,1);assert.equal(r.pagination.rows_on_page,1);
});
test('explicit tab never silently falls back to default',()=>{
 const r=fixture(section(table),{view:'身为出质人'}).settle();assert.equal(r.status,'view_unavailable');
 const f=fixture(section(`<span class='tab'>身为出质人2</span>${table}`),{view:'身为出质人'});
 const tab=f.w.document.querySelector('.tab');tab.onclick=()=>{tab.className='tab active';f.w.document.querySelector('td').textContent='2';};
 const selected=f.settle();assert.equal(selected.view,'身为出质人');assert.equal(selected.tables[0].rows[0].cells[0],'2');
});
