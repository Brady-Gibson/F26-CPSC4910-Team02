const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function setup(){
 const context=vm.createContext({TextDecoder,document:{body:{dataset:{importRole:'sponsor'}}},VIEWS:{sponsor:{}},bind:{sponsor:{}},App:{start(){}}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../assets/js/bulk-import.js'),'utf8'),context);
 return context;
}
function fileFromChunks(chunks){return{stream(){return new ReadableStream({start(c){chunks.forEach(b=>c.enqueue(b));c.close();}});}};}
test('streams split UTF-8 characters and preserves empty fields, physical lines, and CRLF',async()=>{
 const c=setup(),bytes=new TextEncoder().encode('\ufeffD||Zoë|Driver|zoe@example.com||\r\n\nS||Last|User|last@example.com');
 const file=fileFromChunks([...bytes].map(b=>Uint8Array.of(b)));
 const rows=[];for await(const row of c.importFileLines(file))rows.push(JSON.parse(JSON.stringify(row)));
 assert.deepEqual(rows,[{number:1,text:'D||Zoë|Driver|zoe@example.com||'},{number:2,text:''},{number:3,text:'S||Last|User|last@example.com'}]);
});
test('empty file and terminal newline do not invent records',async()=>{
 const c=setup();for(const [text,count] of [['',0],['D||A|B|a@example.com\n',1]]){
  const rows=[];for await(const r of c.importFileLines(new Blob([text])))rows.push(r);assert.equal(rows.length,count);
 }
});
test('invalid UTF-8 stops instead of corrupting identity fields',async()=>{
 const c=setup();await assert.rejects(async()=>{for await(const r of c.importFileLines(fileFromChunks([Uint8Array.of(255)]))){};});
});
test('report CSV escapes quotes, newlines, and spreadsheet formulas',()=>{
 const c=setup();assert.equal(c.importCsvCell('=1+1'),'"\'=1+1"');assert.equal(c.importCsvCell('a,"b"\nc'),'"a,""b""\nc"');
});
test('large files are consumed incrementally without reading the entire file',async()=>{
 const c=setup();let read=0;
 const file={stream(){return new ReadableStream({pull(controller){read++;controller.enqueue(new TextEncoder().encode('D||A|B|a@example.com\n'));if(read===2000)controller.close();}});}};
 let count=0;for await(const row of c.importFileLines(file)){count++;if(count===1)assert.ok(read<2000);}
 assert.equal(count,2000);
});
