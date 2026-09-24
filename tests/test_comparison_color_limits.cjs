const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('ui/static_processing/compare.js','utf8');
function setup(){
  const nodes={'compare-shared-scale':{checked:true},'compare-color-min':{value:''},'compare-color-max':{value:''},'compare-color-auto':{}};
  const requests=[];
  const c={automaticColorLimits:true,revision:1,URLSearchParams,$:s=>nodes[s.slice(1)],
    info:[{id:'a',patterns:['pattern0','pattern1']},{id:'b',patterns:['pattern2']}],selections:new Map([['a',{pattern:'pattern1'}]]),
    api:async url=>{const q=new URLSearchParams(url.split('?')[1]);requests.push(q);return {available:true,data_min:q.get('dataset')==='a'?-.2:-.1,data_max:q.get('dataset')==='a'?.6:.8};}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function comparisonColorRange('),source.indexOf('async function loadComparison(')),c);
  return {c,requests};
}
test('shared extrema use only the same selected stage and band in each folder',async()=>{
  const {c,requests}=setup(),range=await c.sharedColorRange('baseline',1658,1);
  assert.equal(range.display_min,-.2);assert.equal(range.display_max,.8);
  assert.equal(requests.length,2);
  for(const q of requests){assert.equal(q.get('kind'),'baseline');assert.equal(q.get('wavenumber'),'1658');assert.equal(q.get('stats_only'),'true');}
  assert.equal(requests[0].get('pattern'),'pattern1');assert.equal(requests[1].get('pattern'),'pattern2');
});
test('manual range, invalid values, automatic reset and independent mode',async()=>{
  const {c,requests}=setup();c.automaticColorLimits=false;c.$('#compare-color-min').value='0';c.$('#compare-color-max').value='1';
  assert.equal((await c.sharedColorRange('baseline',1658,1)).display_max,1);assert.equal(requests.length,0);
  c.$('#compare-color-max').value='-1';await assert.rejects(c.sharedColorRange('baseline',1658,1),/minimum < maximum/);
  c.automaticColorLimits=true;assert.equal((await c.sharedColorRange('baseline',1658,1)).display_max,.8);
  c.$('#compare-shared-scale').checked=false;assert.equal(await c.sharedColorRange('baseline',1658,1),null);assert.equal(c.$('#compare-color-min').disabled,true);
});
test('stale extrema cannot replace a newer comparison',async()=>{
  const {c}=setup();c.api=async()=>{c.revision=2;return {available:true,data_min:-5,data_max:8};};
  assert.equal(await c.sharedColorRange('baseline',1658,1),null);assert.equal(c.$('#compare-color-min').value,'');
});
