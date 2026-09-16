const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function harness(result) {
 const calls=[];
 const context={URL,AbortSignal,Date,setTimeout:fn=>fn(),extractPage:function extractPage(){},extractSection:function extractSection(){},
   document:{querySelector:()=>({})},
   chrome:{tabs:{create:async ({url})=>{calls.push(url);return {id:1};},get:async()=>({status:'complete',url:calls[0]}),update:async()=>{}},
     scripting:{executeScript:async args=>{calls.push(args.func.name);return [{result}];}}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension/bridge.js'),'utf8')+'\nrunning=true;globalThis.run=execute;',context);
 return {calls,run:context.run};
}
test('routes company, document and person reads to the section extractor',async()=>{
 for(const [operation,url] of [
  ['get_section','https://www.tianyancha.com/company/123/sifa'],
  ['get_capabilities','https://www.tianyancha.com/company/123/past'],
  ['get_document','https://www.tianyancha.com/annualReport/123/2025'],
  ['get_person_section','https://www.tianyancha.com/human/456-c123']]){
  const h=harness({status:'partial'});const r=await h.run({operation,url});assert.equal(r.status,'partial');assert.equal(h.calls[1],'extractSection');
 }
});
test('rejects arbitrary origins, operations, credential URLs and unknown paths',async()=>{
 for(const [operation,url] of [['get_section','https://evil.test/company/123'],['delete','https://www.tianyancha.com/company/123'],
  ['get_section','https://www.tianyancha.com/payvip'],['get_document','https://www.tianyancha.com/company/123'],
  ['get_section','https://secret@www.tianyancha.com/company/123']]){
  const h=harness({});await assert.rejects(h.run({operation,url}),/INVALID_JOB/);assert.equal(h.calls.length,0);
 }
});
test('returns restricted result as coverage state rather than empty successful records',async()=>{
 const h=harness({status:'permission_denied',coverage:{complete:false}});
 const r=await h.run({operation:'get_section',url:'https://www.tianyancha.com/company/123'});
 assert.equal(r.status,'permission_denied');assert.equal(r.coverage.complete,false);
});
