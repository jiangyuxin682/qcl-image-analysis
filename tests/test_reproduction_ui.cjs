const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/app.js'),'utf8');
function setup(){
  const nodes=new Map(),checks=new Set(['fourier-enabled','rolling-enabled','drift-enabled','r0-restrict','cnr-reuse-r0']);
  const $=s=>{if(!nodes.has(s))nodes.set(s,{type:checks.has(s.slice(1))?'checkbox':'text',value:'',replaceChildren(){},append(){}});return nodes.get(s)};
  const c={$, $$:()=>[],state:{},r0ReferenceBands:{old:1},driftReference:null,driftROIs:null,reproductionReport:null,zeroColorbars:new Set(['old']),
    resetROISpectrum(){},clearLineProfile(){},clearBaselineInspection(){},renderMapping(){c.state.cnrDirty=true},checkbox(){},el(){},
    updatePreview(){},filterMode(){},normalizationControls(){},updateSignalLabels(){},table(){},notify(){},
    unlock:n=>c.state.maxStep=n,go:n=>c.state.step=n};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function restoreReproducedState('),source.indexOf("$('#reproduce').onclick=")),c);
  return c;
}
function restored(){return {discovery:{wavenumbers:[1601,1658,1702],files:3},mapping:{1658:[1601,1702]},patterns:['pattern0'],bands:[1601,1658,1702],
  has_gold:false,n_pixels:0,qc_settings:{},r0_selection:{method:'brightest',count:5,reference_bands:{pattern0:1601},search_roi:{x_min:0,x_max:4,y_min:0,y_max:4}},
  parameters:{fourier:{enabled:false,mode:'none',centers:[],sigma_x:.01,sigma_y:.02,strength:.9,protect_radius:.02,cutoff_x:.1,cutoff_y:.1,pad_pixels:0},rolling:{enabled:true,radius:3,kernel_height:.05,feature_polarity:'dark',smooth_sigma:1,pad_pixels:0}},
  drift:{settings:{}},on_rois:{},on_roi:{x_min:0,x_max:10,y_min:0,y_max:10},r0_roi:null,r0:[],version:9,qc:[{frame:0}],
  cnr:[{contrast_low_percentile:5,contrast_high_percentile:95}],cnr_rois:{background_source:'analyte_free',background:null,target:{x_min:6,x_max:8,y_min:6,y_max:8}},
  path:'/temporary/inputs',report:{status:'exact',summary:{exact:50,within_tolerance:0,mismatch:0},rtol:1e-10,atol:1e-12,environment_differences:[],checks:[]}};}
test('import restores numerical controls, CNR source and report without carrying old browser settings',()=>{
  const c=setup(),d=restored();c.restoreReproducedState(d);
  assert.equal(c.state.step,10);assert.equal(c.state.maxStep,10);assert.equal(c.state.cnrDirty,false);
  assert.equal(c.$('#fourier-enabled').checked,false);assert.equal(c.$('#rolling-enabled').checked,true);
  assert.equal(c.$('#cnr-reuse-r0').checked,true);assert.equal(c.$('#cnr-background').disabled,true);
  assert.equal(c.$('#display-low').value,5);assert.equal(c.$('#r0-count').value,5);
  assert.equal(c.$('#has-gold').value,'no');assert.equal(c.r0ReferenceBands.old,undefined);
  assert.equal(c.r0ReferenceBands.pattern0,1601);assert.equal(c.zeroColorbars.size,0);
  assert.equal(c.$('#reproduction-report').hidden,false);assert.equal(c.reproductionReport,d.report);
});
test('package without CNR opens Section 8 to finish quantification',()=>{
  const c=setup(),d=restored();d.cnr=[];d.cnr_rois=null;c.restoreReproducedState(d);
  assert.equal(c.state.step,8);assert.equal(c.state.maxStep,8);
});
test('export is blocked after upstream settings invalidate later stages',()=>{
  const c=setup();c.state={maxStep:5,cnrDirty:false,rois:{},cnr:[]};
  vm.runInContext(source.split('\n').find(s=>s.startsWith("$('#download').onclick=")),c);
  let prevented=false;c.$('#download').onclick({preventDefault:()=>prevented=true});assert.equal(prevented,true);
});
