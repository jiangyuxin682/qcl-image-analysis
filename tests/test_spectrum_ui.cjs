const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('ui/static_processing/app.js','utf8');
function setup(){
  const nodes=new Map();
  const $=key=>{if(!nodes.has(key))nodes.set(key,{value:'',checked:false,options:[],type:key.includes('enabled')?'checkbox':'text',append(o){this.options.push(o);}});return nodes.get(key);};
  const result={pattern:'pattern2',wavenumber:1658,analyte_roi:{x_min:1,x_max:3,y_min:2,y_max:4},background_roi:{x_min:4,x_max:6,y_min:1,y_max:3},points:[{wavenumber:1658,I:1,I_bg:2,ratio:.5,absorbance:.301,status:'valid'}]};
  const calls=[];
  const c={$,roiSpectra:{result},state:{mapping:{1658:[1601,1702]},discovery:{availability:[{pattern:'pattern2',wavenumbers:[1658]}]}},zeroColorbars:new Set(),
    api:async(path,payload)=>{calls.push({path,payload});return {saved:true};},
    fillSelect(node,values,selected){node.options=values.map(v=>({value:v}));node.value=selected||values[0];},updateROISpectrumBands(){},
    el:(tag,text)=>({value:text}),loadROISpectrumImage:async()=>{c.roiSpectra.result=null;},updateROIMarkers(){},drawROICharts(){},drawROISpectrumImage(){},table(node,rows){c.rows=rows;}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('let spectrumSave='),source.indexOf('async function updateROISmoothing(')),c);
  return {c,calls,result};
}
test('saved spectrum sends full-image selection and independent spectral controls',async()=>{
  const {c,calls,result}=setup();
  c.$('#roi-fourier-enabled').checked=true;c.$('#roi-sg-enabled').checked=true;c.$('#roi-fourier-mode').value='combined';
  c.$('#roi-notch-centers').value='.1, .3';c.$('#roi-notch-width').value='.02';c.$('#roi-fourier-cutoff').value='.2';
  c.$('#roi-sg-window').value='11';c.$('#roi-sg-order').value='2';
  const pending=c.saveSpectrumProject();c.state.mapping[1658]=[];await pending;
  assert.equal(calls[0].path,'/api/save-spectrum');
  assert.equal(calls[0].payload.selection.pattern,result.pattern);
  assert.deepEqual([...calls[0].payload.filters.notch_centers],[.1,.3]);
  assert.deepEqual([...calls[0].payload.view.mapping[1658]],[1601,1702]);
});
test('restored spectrum restores ROI, disabled control states, filtered values and preview band',async()=>{
  const {c,result}=setup();const saved={result,filtered:{absorbance_filtered:[.3]},settings:{filters:{fourier_enabled:true,sg_enabled:false,fourier_mode:'notch',notch_centers:[.2],cutoff:.1,window:11,order:2},view:{mapping:{1658:[1650,1660]},marker_center:'all',colorbar_zero:true}}};
  await c.restoreSpectrumProject(saved);
  assert.equal(c.$('#roi-spectrum-pattern').value,'pattern2');assert.equal(c.$('#roi-spectrum-band').value,1658);
  assert.equal(c.$('#roi-sg-window').disabled,true);assert.equal(c.$('#roi-fourier-cutoff').disabled,true);assert.equal(c.$('#roi-notch-centers').disabled,false);
  assert.equal(c.roiSpectra.rois.analyte_roi,result.analyte_roi);assert.equal(c.rows[0].absorbance_filtered,.3);
  assert.equal(c.zeroColorbars.has('roi-raw'),true);assert.equal(c.$('#roi-spectrum-export').disabled,false);
});
