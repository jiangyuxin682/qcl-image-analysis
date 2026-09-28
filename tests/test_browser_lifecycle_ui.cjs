const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('ui/static_processing/lifecycle.js', 'utf8');
function setup(iframe=false) {
  const events={}, beacons=[], panels=[];
  let interval, closeCount=0, fail=false, requests=0;
  const window={addEventListener:(name,fn)=>events[name]=fn,close:()=>closeCount++};
  window.self=window;window.top=iframe?{}:window;
  const context={window,crypto:{randomUUID:()=>String(Math.random())},
    navigator:{sendBeacon:(url,blob)=>beacons.push({url,blob})},Blob,
    fetch:async()=>{requests++;if(fail)throw Error('offline');return {ok:true,json:async()=>({enabled:true,stopping:false})};},
    AbortSignal:{timeout:()=>null},setInterval:fn=>{interval=fn;return 1;},clearInterval:()=>{},
    document:{createElement:()=>({setAttribute(){},style:{}}),body:{append:p=>panels.push(p)}}};
  vm.runInNewContext(code,context);
  return {events,beacons,panels,poll:()=>interval(),fail:()=>fail=true,
    get requests(){return requests;},get closes(){return closeCount;}};
}
(async()=>{
  const frame=setup(true);assert.equal(frame.requests,0);
  const page=setup();await new Promise(setImmediate);
  page.events.pagehide();assert.equal(page.beacons.length,1);
  const payload=JSON.parse(await page.beacons[0].blob.text());assert.equal(payload.leaving,true);
  page.fail();await page.poll();await page.poll();assert.equal(page.closes,0);
  await page.poll();assert.equal(page.closes,1);assert.equal(page.panels.length,1);
  console.log('Browser lifecycle checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
