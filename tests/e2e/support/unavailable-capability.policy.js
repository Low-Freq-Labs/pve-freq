const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('freq/data/web/js/app.js', 'utf8');
const start = source.indexOf('function _fetchAndRender(');
const end = source.indexOf('/* Helper: stat cards HTML */', start);
for (const payload of [{implemented:false},{available:false},{capability_status:'unimplemented'},{stats:{total:5}}]) {
  test('render capability response '+JSON.stringify(payload), async () => {
    const element = {innerHTML:'',textContent:''}; let calls=0;
    const context = {document:{getElementById:()=>element}, _authFetch:()=>Promise.resolve({json:()=>Promise.resolve(payload)}), _esc:String};
    vm.createContext(context); vm.runInContext(source.slice(start,end),context);
    context._fetchAndRender('/synthetic','stats',()=>{calls++;});
    await new Promise(resolve=>setImmediate(resolve));
    const unavailable = !payload.stats;
    assert.equal(calls,unavailable?0:1);
    if(unavailable) assert.match(element.textContent,/not implemented/);
  });
}
