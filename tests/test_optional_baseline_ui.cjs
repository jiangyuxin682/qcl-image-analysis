const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('ui/static_processing/app.js','utf8');
function setup(){
  const nodes=new Map();
  const $=s=>{if(!nodes.has(s))nodes.set(s,{value:'',dataset:{},options:[],replaceChildren(){}});return nodes.get(s);};
  const c={$,state:{mapping:{1775:[]},baseline_enabled:{1775:false},hasGold:false},
    stages:['raw','reflectance','fourier','rolling','absorbance','baseline'],stageNames:['Raw','Reflectance','Fourier','Rolling','Absorbance before baseline','Absorbance after baseline'],
    fillSelect:(node,values,preferred)=>{node.options=values.map(value=>({value}));node.value=String(values.map(String).includes(String(preferred))?preferred:values[0]??'');}};
  vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('function baselineCenters('),source.indexOf('function chooseCenter(')),c);
  vm.runInContext(source.slice(source.indexOf('function activeStages('),source.indexOf('function normalizationControls(')),c);
  vm.runInContext(source.slice(source.indexOf('function updateTimeBands('),source.indexOf('async function buildTime(')),c);
  c.$('#preview-band').value='1775';c.state.bands=[1775];
  return c;
}
test('all-skipped centers route from Section 6 to CNR and omit the after-baseline image',()=>{
  const c=setup();c.updateSignalLabels();
  assert.equal(c.$('#continue-absorbance').dataset.go,'8');
  assert.equal(c.activeStages().includes('baseline'),false);
  assert.match(c.$('#absorbance-basis').innerHTML,/I<sub>corrected<\/sub>/);
  assert.match(c.$('#absorbance-basis').innerHTML,/I<sub>bg<\/sub>/);
  c.state.hasGold=true;c.updateSignalLabels();
  assert.match(c.$('#absorbance-basis').innerHTML,/R<sub>corrected<\/sub>/);
});
test('mixed centers keep Section 7 and baseline only for enabled bands',()=>{
  const c=setup();c.state.mapping[1658]=[1601,1702];c.state.baseline_enabled[1658]=true;
  c.updateSignalLabels();assert.equal(c.$('#continue-absorbance').dataset.go,'7');
  assert.equal(c.activeStages().includes('baseline'),false);
  c.$('#preview-band').value='1658';assert.equal(c.activeStages().includes('baseline'),true);
  c.$('#time-kind').value='baseline';c.updateTimeBands();assert.equal(c.$('#time-band').value,'1658');
});
test('timelapse defaults to absorbance when no center has baseline enabled',()=>{
  const c=setup();c.$('#time-kind').value='baseline';c.updateTimeBands();
  assert.equal(c.$('#time-kind').value,'absorbance');assert.equal(c.$('#time-band').value,'1775');
  assert.equal(c.$('#time-kind option[value="baseline"]').disabled,true);
});
