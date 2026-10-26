const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = readFileSync(path.join(__dirname,'../assets/js/admin-audit.js'),'utf8');
function setup() {
  const elements = {'#auditDownload':{}, '#auditError':{}}, calls=[], links=[];
  const context = vm.createContext({LIVE:true, VIEWS:{admin:{}}, bind:{admin:{}}, App:{start(){}},
    URLSearchParams, $:key=>elements[key], toast(){}, setTimeout(fn){fn();},
    URL:{createObjectURL(){return 'blob:test';},revokeObjectURL(){}},
    document:{body:{appendChild(){}},createElement(){const link={click(){link.clicked=true;},remove(){}};links.push(link);return link;}},
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,blob:async()=>({}),headers:{get:()=> 'attachment; filename="audit-log-test.csv"'}};}});
  vm.runInContext(source,context);
  return {context,elements,calls,links};
}
test('CSV request contains every active filter and initiates a file download',async()=>{
  const {context,calls,links,elements}=setup();
  await vm.runInContext(`auditFilters={category:'LOGIN',success:'0',sponsor_id:'900001',start_date:'2026-10-01',end_date:'2026-10-02'};downloadAuditCsv()`,context);
  const query=new URL(calls[0].url,'http://localhost').searchParams;
  assert.deepEqual(Object.fromEntries(query),{category:'LOGIN',success:'0',sponsor_id:'900001',start_date:'2026-10-01',end_date:'2026-10-02'});
  assert.equal(calls[0].options.credentials,'same-origin');
  assert.equal(links[0].download,'audit-log-test.csv');assert.equal(links[0].clicked,true);
  assert.equal(elements['#auditDownload'].disabled,false);
});
test('export waits until current filters finish loading',async()=>{
  const {context,calls}=setup();
  await vm.runInContext('auditLoading=true; downloadAuditCsv()',context);
  assert.equal(calls.length,0);
});
test('server errors are displayed instead of being downloaded as CSV',async()=>{
  const {context,elements,links}=setup();
  context.fetch=async()=>({ok:false,json:async()=>({error:'Please sign in.'})});
  await vm.runInContext('downloadAuditCsv()',context);
  assert.equal(elements['#auditError'].textContent,'Please sign in.');
  assert.equal(links.length,0);assert.equal(elements['#auditDownload'].disabled,false);
});
test('empty filters are omitted but failed-result filter is preserved',()=>{
  const {context}=setup();
  assert.equal(vm.runInContext("auditQuery({category:'',success:'0',start_date:''})",context),'success=0');
});
