const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/app.js'),'utf8');
function setup(){
  const nodes=new Map(),plots=[],tables=[];
  const $=id=>{if(!nodes.has(id))nodes.set(id,{value:id==='#preview-band'?'1658':'median_crop',hidden:false,textContent:'',replaceChildren(){}});return nodes.get(id)};
  const c={$,state:{step:6,maxStep:7,viewEpoch:1,hasGold:true,normalizationDirty:false},URLSearchParams,window:{addEventListener(){}},setTimeout,clearTimeout,table:(node,rows)=>tables.push(rows)};
  vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('let signalTrendData='),source.indexOf('function activeStages(')),c);
  c.trendPlot=(...args)=>plots.push(args);
  return {c,plots,tables,$};
}
const data={wavenumber:1658,has_gold:true,records:[{pattern:'pattern0',frame:0,r0:.4,median_crop:.5,median_full:.9,median_corrected:.6,i_goldref:120}]};
test('reference and median plots follow the selected band and median stage',async()=>{
  const {c,plots,$}=setup();let url;c.api=async path=>{url=path;return data;};
  await c.refreshSignalTrends();
  assert.match(url,/wavenumber=1658/);
  assert.match($('#r0-trend-title').textContent,/1658/);
  assert.equal(plots[1][2],'median_crop');
  $('#median-trend-stage').value='median_full';$('#median-trend-stage').onchange();
  assert.equal(plots.at(-1)[2],'median_full');
  c.clearSignalTrends(7);c.state.maxStep=6;c.renderSignalTrends();
  assert.equal(plots.at(-2)[1].length,0);
  assert.match($('#reference-trend-status').textContent,/Calculate absorbance/);
});
test('an upstream edit discards a pending trend response',async()=>{
  const {c,plots}=setup();let resolve;c.api=()=>new Promise(r=>resolve=r);
  const pending=c.refreshSignalTrends();c.clearSignalTrends(7);const count=plots.length;
  resolve(data);await pending;assert.equal(plots.length,count);
});
test('gold chart is shown only for committed normalization; no-gold labels use intensity',async()=>{
  const {c,$}=setup();c.api=async()=>data;c.state.step=3;
  await c.refreshSignalTrends();assert.equal($('#gold-trends').hidden,false);
  c.state.normalizationDirty=true;await c.refreshSignalTrends();assert.equal($('#gold-trends').hidden,true);
  c.state.normalizationDirty=false;c.state.hasGold=false;c.state.step=6;
  c.api=async()=>({...data,has_gold:false});await c.refreshSignalTrends();
  assert.match($('#r0-trend-title').textContent,/I_bg/);assert.match($('#median-trend-title').textContent,/Median I/);
});
