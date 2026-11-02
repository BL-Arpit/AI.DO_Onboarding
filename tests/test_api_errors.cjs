const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
function apiFor(status,body){
 const context={FormData:class {},fetch:async()=>({status,ok:status>=200&&status<300,text:async()=>body})};
 vm.createContext(context);
 vm.runInContext(source.slice(0,source.indexOf('async function guard'))+'\nglobalThis.callApi=api;',context);
 return context.callApi;
}
test('JSON origin error is displayed',async()=>{
 await assert.rejects(apiFor(403,'{"detail":"Origin not allowed. Set APP_URL."}')('/login'),/Origin not allowed\. Set APP_URL/);
});
test('legacy plain-text error is displayed without a JSON parsing error',async()=>{
 await assert.rejects(apiFor(403,'Origin not allowed')('/login'),error=>error.message==='Origin not allowed');
});
test('HTML proxy error gives a useful server message',async()=>{
 await assert.rejects(apiFor(502,'<html>Bad gateway</html>')('/login'),/Server error \(502\)/);
});
test('malformed success is reported explicitly',async()=>{
 await assert.rejects(apiFor(200,'Not JSON')('/login'),/unexpected response/);
});
test('successful JSON is returned',async()=>{
 const result=await apiFor(200,'{"ok":true}')('/login');assert.equal(result.ok,true);
});
