(() => {
  const el = id => document.getElementById('skills-' + id);
  const base = new URL('./api/skills', location.href);
  let editing = null, importing = null, busy = false;
  async function discardImport() {
    if (importing) { await request('/import/'+importing, 'DELETE'); importing=null; }
  }
  async function request(suffix = '', method = 'GET', data) {
    const multipart = data instanceof FormData;
    const response = await fetch(base.href + suffix, {method, credentials:'same-origin', headers:{'X-Skill-Request':'1', ...(multipart ? {} : {'Content-Type':'application/json'})}, ...(data === undefined ? {} : {body:multipart ? data : JSON.stringify(data)})});
    const result = await response.json();
    if (!response.ok || result.status !== 'success') throw new Error(result.message || '请求失败');
    return result;
  }
  async function action(fn) {
    if (busy) return; busy = true;
    document.querySelectorAll('#tab-skills button, #tab-skills input[type="file"]').forEach(b=>b.disabled=true);
    try { await fn(); } catch(e) { el('message').textContent=e.message; }
    finally { busy=false; document.querySelectorAll('#tab-skills button, #tab-skills input[type="file"]').forEach(b=>b.disabled=false); }
  }
  function edit(s = {}) {
    editing=s.id || null; importing=s.import_token || null;
    el('files').textContent=(s.package?`目录：config/skills/${s.package}/\n入口：${s.entry}\n\n`:'')+((s.files || []).map(f=>`${f.path} (${f.size} 字节)`).join('\n') || '保存后将创建独立技能文件夹及 SKILL.md。');
    for (const k of ['name','description','content']) el(k).value=s[k] || '';
    el('enabled').checked=!!s.enabled; el('editor').hidden=false;
  }
  async function load() {
    const {skills}=await request(); el('list').replaceChildren();
    for (const s of skills) {
      const row=document.createElement('div'); row.style.cssText='padding:12px 0;border-bottom:1px solid var(--border)';
      const label=document.createElement('p'); label.textContent=`${s.name} · ${s.enabled ? '已启用' : '已停用'} — ${s.description}`; row.append(label);
      for (const [name, fn] of [['编辑',()=>action(async()=>{await discardImport();edit(s);})], [s.enabled?'停用':'启用',()=>action(async()=>{await request('','POST',{id:s.id,enabled:!s.enabled}); await load();el('message').textContent='状态已更新，下次对话生效。';})], ['删除',()=>{if(confirm(`删除 ${s.name}？`)) action(async()=>{await request('/'+s.id,'DELETE');if(editing===s.id) el('editor').hidden=true;await load();});}]]) {
        const b=document.createElement('button');b.type='button';b.className='btn btn-load';b.textContent=name;b.onclick=fn;row.append(b);
      }
      el('list').append(row);
    }
    if (!skills.length) el('list').textContent='尚未添加 Skill。';
  }
  el('add').onclick=()=>action(async()=>{await discardImport();edit();});
  el('cancel').onclick=()=>action(async()=>{await discardImport();el('editor').hidden=true;});
  el('save').onclick=()=>action(async()=>{await request('','POST',{...(editing?{id:editing}:{}),...(importing?{import_token:importing}:{}),name:el('name').value,description:el('description').value,content:el('content').value,enabled:el('enabled').checked});importing=null;el('editor').hidden=true;await load();el('message').textContent='已保存，下次对话生效。';});
  el('official').onclick=()=>action(async()=>{el('message').textContent='正在读取官方 Skill…';const r=await request('/official-tianyancha','POST',{});await discardImport();edit(r.skill);el('message').textContent='已读取官方原文，请检查并保存。官方 MCP 需在 MCP 工具页配置天眼 AI 密钥。';});
  for (const id of ['file', 'editor-file']) {
    el(id).onchange=()=>action(async()=>{
      try {
        const f=el(id).files[0];if(!f)return;
        const zip=/\.zip$/i.test(f.name);
        if(!zip && !/\.md$/i.test(f.name))throw new Error('请选择 .md 文件或 .zip 技能压缩包');
        if(f.size>(zip?10*1024*1024:240000))throw new Error(zip?'ZIP 压缩包不能超过 10 MiB':'Markdown 文件不能超过 240000 字节');
        el('message').textContent='正在读取 Skill…';
        const data=new FormData();data.append('file',f);
        const r=await request('/import','POST',data);await discardImport();edit(r.skill);
        el('message').textContent=`已读取 ${r.source}，请检查名称、适用场景和正文后保存。`+(r.attachments?`包内另有 ${r.attachments} 个文件，保存时会保留完整目录及全部附件。`:'');
      } finally { el(id).value=''; }
    });
  }
  action(load);
})();
