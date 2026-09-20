/* Local processing controller. Filename-derived spectral roles are explicit;
 * canvas rectangles share image-pixel coordinates across processing stages.
 * Changes lock dependent steps until the corresponding API operation succeeds.
 * Heatmap contrast affects rendering only, never the scientific arrays. */
'use strict';
const roiSpectra={revision:0,image:null,rois:{},result:null,drag:null,sg:null,sgRevision:0};
const datasetQuery=new URLSearchParams(location.search),datasetId=datasetQuery.get('dataset')||'default';
const embedded=datasetQuery.get('embedded')==='1';
let sharedReady=false,applyingShared=false;
function datasetURL(path){const url=new URL(path,location.href);url.searchParams.set('dataset',datasetId);return url.pathname+url.search;}
function sendParent(message){if(embedded)parent.postMessage({...message,dataset:datasetId},location.origin);}

let reproductionReport=null;
const lineProfile={start:null,end:null,result:null,revision:0};
let previewTimer=null, previewRunning=false, previewRevision=0;
let candidatePeaks=[];
function processingChanged(){invalidateFrom(6);publishShared();renderPeaks(candidatePeaks);for(const v of state.canvases.filter(v=>v.kind==='spectrum'))addSpectrumLabels(v.canvas.closest('.heatmap'),v.data);schedulePreview();}
function schedulePreview(){
  previewRevision++;
  clearTimeout(previewTimer);
  if(state.step!==5)return;
  $('#live-status').textContent='Preview pending; the displayed result is not current.';
  $('#live-preview').style.opacity='.4';
  previewTimer=setTimeout(runPreview,450);
}
async function runPreview(){
  if(previewRunning||state.step!==5||document.body.classList.contains('busy'))return;
  const revision=previewRevision,epoch=state.viewEpoch;
  previewRunning=true;
  $('#live-status').textContent='Updating full-resolution preview...';
  try{
    const parameters=processingParameters();
    const result=await api('/api/preview',{...imageParams('reflectance'),...parameters,colorbar_zero_titles:[...zeroColorbars].filter(k=>k.startsWith('live:')).map(k=>k.slice(5))});
    if(revision!==previewRevision||epoch!==state.viewEpoch||state.step!==5)return;
    const root=$('#live-preview');root.replaceChildren();
    [...result.images,...(result.diagnostics||[])].forEach((data,i)=>{
      if(i===3||data.title==='Estimated rolling-ball background'){const heading=el('h3',i===3?'Live Fourier space and removed signal':'Live rolling-ball background');heading.style.gridColumn='1 / -1';root.append(heading);}
      const card=el('div',undefined,'image-card');
      const bypass=(i===1&&(!parameters.fourier.enabled||parameters.fourier.mode==='none'))||(i===2&&!parameters.rolling.enabled);
      card.append(el('h4',data.title+(bypass?' (bypassed)':'')));
      if(data.available===false){card.append(el('p',data.caption,'placeholder'));root.append(card);return;}
      zeroControl(card,'live:'+data.title,()=>schedulePreview());
      const wrap=el('div',undefined,'heatmap'),img=el('img');
      img.src='data:image/png;base64,'+data.png;img.alt=data.title;
      img.style.cssText='width:calc(100% - 57px);height:auto;align-self:flex-start';
      const bar=el('div',undefined,'bar'),strip=el('div',undefined,'strip'),ticks=el('div',undefined,'ticks');
      [data.vmax,(data.vmax+data.vmin)/2,data.vmin].forEach(v=>ticks.append(el('span',v.toFixed(3))));
      bar.append(strip,ticks);wrap.append(img,bar);card.append(wrap);if(data.caption)card.append(el('p',data.caption,'hint'));root.append(card);
    });
    root.style.opacity='1';
    $('#live-status').textContent=`Current preview: ${$('#preview-pattern').value}, ${$('#preview-band').value} cm⁻¹. Invalid output pixels: ${result.invalid_pixels}.`;
  }catch(e){if(revision===previewRevision&&epoch===state.viewEpoch&&state.step===5){$('#live-preview').replaceChildren();$('#live-status').textContent=e.message;}}
  finally{previewRunning=false;if(revision!==previewRevision&&state.step===5)previewTimer=setTimeout(runPreview,100);}
}
function addNotchPair(fy,fx){
  try{
    const points=notchCenters();
    for(const pair of [[fy,fx],[-fy,-fx]]){
      if(!points.some(p=>p.every((v,i)=>Math.abs(v-pair[i])<1e-7)))points.push(pair);
    }
    $('#notches').value=points.map(p=>p.map(v=>v.toFixed(8)).join(', ')).join(';\n');
    processingChanged();
  }catch(e){notify(e.message,true);}
}
function removeNotchPair(fy,fx){
  try{const points=notchCenters().filter(p=>!matchesPair(p,fy,fx));$('#notches').value=points.map(p=>p.join(', ')).join(';\n');processingChanged();}catch(e){notify(e.message,true);}
}
function matchesPair(p,fy,fx){return Math.abs(p[0]-fy)<1e-7&&Math.abs(p[1]-fx)<1e-7||Math.abs(p[0]+fy)<1e-7&&Math.abs(p[1]+fx)<1e-7;}
function renderPeaks(peaks){
  candidatePeaks=peaks;
  let points=[];try{points=notchCenters();}catch(e){}
  const root=$('#peak-list');root.replaceChildren();
  if(!peaks.length){root.append(el('p','No candidate peaks outside the exclusion region.','hint'));return;}
  const t=el('table'),head=el('tr');
  ['Rank','(fy, fx)','Partner (-fy, -fx)','Period (pixels)','FFT amplitude','Selection / actions'].forEach(s=>head.append(el('th',s)));t.append(head);
  for(const peak of peaks){
    const row=el('tr');
    [peak.rank,`${peak.fy.toFixed(6)}, ${peak.fx.toFixed(6)}`,`${(-peak.fy).toFixed(6)}, ${(-peak.fx).toFixed(6)}`,fmt(peak.period_pixels),fmt(peak.amplitude)].forEach(v=>row.append(el('td',String(v))));
    const cell=el('td'),b=el('button','Add pair','secondary');
    b.onclick=()=>{if(!$('#fourier-enabled').checked||!['notch','combined'].includes($('#filter-mode').value)){notify('Enable Fourier filtering and select Gaussian notch to add peaks.');return;}addNotchPair(peak.fy,peak.fx);};
    const selected=points.some(p=>matchesPair(p,peak.fy,peak.fx));
    const status=el('span',selected?'Added':'Not added','hint');status.style.display='block';
    b.disabled=selected;
    const remove=el('button','Remove pair','secondary');remove.disabled=!selected;
    remove.onclick=()=>removeNotchPair(peak.fy,peak.fx);
    cell.append(status,b,remove);row.append(cell);t.append(row);
  }
  root.append(t);
}
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let fitRevision=0, fitImage=null, fitResult=null;
const stages=['raw','reflectance','fourier','rolling','absorbance','baseline'];
const stageNames=['Raw intensity','Reflectance before processing','Reflectance after Fourier','Reflectance after rolling ball','Absorbance before baseline','Absorbance after baseline'];
const titles=['Import data & inspect full spectrum','Choose center wavenumbers and baseline references','Calculate reflectance','Select the on-MS region','Fourier and flat-field correction','Calculate absorbance','Baseline correction','Calculate CNR','Timelapse','Export results'];
const state={step:1,maxStep:1,discovery:null,mapping:{},patterns:[],bands:[],qc:[],rois:{on:null,r0:null,background:null,target:null},cnr:[],cnrDirty:false,r0:[],canvases:[],mode:null,version:0,viewEpoch:0,time:null,timer:null};
$('#gold-settings-slot').append($('#gold-settings'));
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function notify(text,error=false){const n=$('#notice');n.hidden=false;n.textContent=text;n.className=error?'error':''}
async function api(path,payload){
  const r=await fetch(datasetURL(path),payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await r.json();if(!r.ok)throw Error(data.error||'Operation failed');const group={'/api/configure':'spectral','/api/normalize':'normalization','/api/process':'processing','/api/calculate':'analyte'}[path];if(group&&embedded)sendParent({type:'shared-commit',group,settings:sharedSnapshot()});return data
}
const zeroColorbars=new Set();
function zeroControl(root,key,refresh){
  const label=el('label',undefined,'check'),input=el('input');input.type='checkbox';input.checked=zeroColorbars.has(key);
  label.append(input,document.createTextNode('Set lower limit to 0 · display only'));root.append(label);
  input.onchange=async()=>{input.checked?zeroColorbars.add(key):zeroColorbars.delete(key);try{await refresh();}catch(e){notify(e.message,true);}};
}
async function busy(button,fn){if(document.body.classList.contains('busy'))return;document.body.classList.add('busy');sendParent({type:'busy',busy:true});const old=button.textContent;button.textContent='Processing…';notify('Processing locally. Large images or rolling-ball radii may take longer.');try{await fn()}catch(e){notify(e.message,true)}finally{document.body.classList.remove('busy');button.textContent=old;sendParent({type:'busy',busy:false});sendParent({type:'progress',step:state.step,maxStep:state.maxStep,cnrDirty:state.cnrDirty})}}
function unlock(n){state.maxStep=n;renderNav()}
function renderNav(){sendParent({type:'progress',step:state.step,maxStep:state.maxStep,cnrDirty:state.cnrDirty});$$('[data-go]').forEach(b=>b.disabled=+b.dataset.go>state.maxStep);const nav=$('#navigation');nav.replaceChildren();titles.forEach((t,i)=>{const b=el('button',undefined,state.step===i+1?'active':'');b.append(el('i',String(i+1)));const label=el('span',t);b.append(label);b.disabled=i+1>state.maxStep;b.onclick=()=>go(i+1);nav.append(b)})}
function invalidateFrom(n){reproductionReport=null;$('#reproduction-report').hidden=true;clearLineProfile();clearBaselineInspection();$('#baseline-preview').replaceChildren();if(n<=7){$('#processing-preview').querySelectorAll('[data-absorbance-preview]').forEach(n=>n.remove());}state.maxStep=Math.min(state.maxStep,n-1);state.cnr=[];state.rois.background=state.rois.target=null;state.cnrDirty=true;clearInterval(state.timer);state.timer=null;$('#time-player').hidden=true;renderNav()}
function go(step){if(step>state.maxStep)return;if(step===2){$('#section2-band-slot').append($('#spectral-band-editor'));$('#inline-band-editor').hidden=true;}state.step=step;$$('section[data-step]').forEach(n=>n.hidden=+n.dataset.step!==step);$('#page-title').textContent=titles[step-1];$('#preview-controls').hidden=step<3||step>8;renderNav();refreshView().catch(e=>notify(e.message,true));window.scrollTo({top:0,behavior:'smooth'})}
function fillSelect(node,values,preferred){node.replaceChildren();for(const v of values){const o=el('option',String(v));o.value=v;node.append(o)}if(values.map(String).includes(String(preferred)))node.value=preferred}
function updatePreview(){fillSelect($('#preview-pattern'),state.patterns,$('#preview-pattern').value);fillSelect($('#preview-band'),state.bands,Object.keys(state.mapping)[0]);}
function checkbox(value,checked,callback){const label=el('label',undefined,'chip');const input=el('input');input.type='checkbox';input.value=value;input.checked=checked;input.onchange=()=>callback(input.checked);label.append(input,document.createTextNode(String(value)));return label}
function involved(){return [...new Set([...Object.keys(state.mapping).map(Number),...Object.values(state.mapping).flat()])].sort((a,b)=>a-b)}
function renderMapping(){const root=$('#reference-mapping');root.replaceChildren();for(const center of Object.keys(state.mapping).map(Number).sort((a,b)=>a-b)){const row=el('div',undefined,'mapping-row');row.append(el('h3',`${center} cm⁻¹ reference`));const chips=el('div',undefined,'chips');for(const wn of state.discovery.wavenumbers){if(wn===center)continue;chips.append(checkbox(wn,state.mapping[center].includes(wn),checked=>{state.mapping[center]=checked?[...state.mapping[center],wn].sort((a,b)=>a-b):state.mapping[center].filter(v=>v!==wn);mappingChanged()}))}row.append(chips);root.append(row)}mappingChanged()}
function mappingChanged(){const oldPreview=$('#roi-spectrum-band').value;updateROISpectrumBands();if(oldPreview!==$('#roi-spectrum-band').value)loadROISpectrumImage();updateROIMarkers();invalidateFrom(3);publishShared();const wns=involved();$('#involved-bands').textContent=wns.length?`All involved wavenumbers: ${wns.join(' · ')} cm⁻¹`:'Select centers and reference bands.';renderPatterns()}
function renderPatterns(){const root=$('#pattern-options');const previous=new Set($$('input[data-pattern]:checked').map(n=>n.value));const initial=!root.children.length;root.replaceChildren();const required=involved();for(const [index,p] of state.discovery.availability.entries()){const missing=required.filter(w=>!p.wavenumbers.includes(w));const label=el('label',undefined,'pattern');const input=el('input');input.type='checkbox';input.dataset.pattern='true';input.value=p.pattern;input.disabled=missing.length>0;input.checked=!missing.length&&(previous.has(p.pattern)||(initial&&index===0));input.onchange=()=>invalidateFrom(3);label.append(input,document.createTextNode(p.pattern),el('small',missing.length?` ${missing.join(', ')}`:`${p.wavenumbers.length} wavenumber`));root.append(label)}}
function acceptDiscoveredData(d){resetROISpectrum();clearLineProfile();clearBaselineInspection();reproductionReport=null;$('#reproduction-report').hidden=true;state.cnr=[];state.r0=[];state.cnrDirty=true;state.rois={on:null,r0:null,background:null,target:null};state.discovery=d;state.mapping={};state.patterns=[];state.bands=[];state.version=d.version;$('#center-options').replaceChildren();$('#pattern-options').replaceChildren();$('#reference-mapping').replaceChildren();for(const wn of d.wavenumbers)$('#center-options').append(checkbox(wn,false,on=>{if(on)state.mapping[wn]=[];else delete state.mapping[wn];renderMapping()}));$('#discovered-bands').replaceChildren(...d.wavenumbers.map(w=>el('span',`${w} cm⁻¹`,'chip')));$('#discovery-count').textContent=`${d.files} image · ${d.availability.length}  patterns`;$('#discovery-summary').hidden=false;renderPatterns();unlock(2);$('#session-status').textContent=` ${d.wavenumbers.length} wavenumber`;notify('Wavenumbers detected. Inspect ROI spectra below, then continue to spectral configuration.');go(1);prepareROISpectrum();}
$('#data-input-kind').onchange=()=>{const folder=$('#data-input-kind').value==='folder';$('#data-folder-label').hidden=!folder;$('#data-files-label').hidden=folder;};
$('#discover').onclick=()=>busy($('#discover'),async()=>{
  const kind=$('#data-input-kind').value,files=$(kind==='folder'?'#data-folder':'#data-files').files;
  const response=await fetch(datasetURL('/api/upload-data'),{method:'POST',body:QCLUpload.data(files,kind)});
  const d=await response.json();if(!response.ok)throw Error(d.error||'Data import failed.');
  acceptDiscoveredData(d);sendParent({type:'ready'});sharedReady=true;
});

function patternRangeSelection(inputs,startText,endText){
  const start=Number(startText),end=Number(endText);
  if(!String(startText).trim()||!String(endText).trim()||!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<start)throw Error('Enter integer pattern indices with 0 ≤ start ≤ end.');
  return inputs.filter(n=>{const match=/^pattern(\d+)$/.exec(n.value);return match&&!n.disabled&&Number(match[1])>=start&&Number(match[1])<=end;});
}
$('#select-pattern-range').onclick=()=>{
  try{
    const inputs=$$('input[data-pattern]'),selected=patternRangeSelection(inputs,$('#pattern-start').value,$('#pattern-end').value);
    if(!selected.length)throw Error('No complete patterns in this range. The current selection was kept.');
    const chosen=new Set(selected);inputs.forEach(n=>n.checked=chosen.has(n));invalidateFrom(3);
    notify(`Selected ${selected.length} complete patterns in the inclusive range ${$('#pattern-start').value}–${$('#pattern-end').value}.`);
  }catch(e){notify(e.message,true);}
};
$('#unselect-patterns').onclick=()=>{$$('input[data-pattern]').forEach(n=>n.checked=false);invalidateFrom(3);notify('All patterns unselected.');};
$('#select-complete').onclick=()=>{$$('input[data-pattern]').forEach(n=>n.checked=!n.disabled);invalidateFrom(3)};
$('#configure').onclick=()=>busy($('#configure'),async()=>{const d=await api('/api/configure',{mapping:state.mapping,patterns:$$('input[data-pattern]:checked').map(n=>n.value)});Object.assign(state,{mapping:d.mapping,patterns:d.patterns,bands:d.bands,qc:d.qc,version:d.version,hasGold:null,normalizationDirty:true,cnr:[],cnrDirty:true,r0:[]});state.rois={on:null,r0:null,background:null,target:null};driftReference=null;driftROIs=null;updatePreview();unlock(3);const frames=d.qc.map(r=>r.frame);$('#time-start').value=Math.min(...frames);$('#time-end').value=Math.max(...frames);$('#session-status').textContent=`${d.patterns.length} patterns · ${d.bands.length} wavenumber`;notify('Spectral configuration confirmed. Choose whether a gold patch reference is available.');go(3)});

function activeStages(){return stages.filter(kind=>kind!=='reflectance'||state.hasGold);}
function updateSignalLabels(){
  const signal=state.hasGold?'reflectance':'raw intensity';
  stageNames[2]=`${state.hasGold?'Reflectance':'Raw intensity'} after Fourier`;
  stageNames[3]=`${state.hasGold?'Reflectance':'Raw intensity'} after rolling ball`;
  $('#processing-basis').textContent=`Processing input: ${signal}. Fourier and flat-field correction operate on the cropped ${signal}.`;
  $('#absorbance-basis').textContent=state.hasGold?'A = −log₁₀(R_corrected / R₀). R₀ is the mean corrected reflectance in the analyte-free selection for each image.':'A = −log₁₀(I_corrected / I_bg). I_bg is the mean corrected raw intensity in the analyte-free selection for each image. No reflectance normalization is applied.';
  $('#reference-summary-title').textContent=state.hasGold?'R₀ and reference-region check':'I_bg and reference-region check';
  $('#rb-height-unit').textContent=`Intensity height · ${signal}`;
  $('#comparison-description').textContent=`${state.hasGold?'Six':'Five'} stages. ${state.hasGold?'Reflectance':'Raw intensity'}, Fourier and rolling-ball images share a display range; absorbance images share another range.`;
  $('#drift-enabled').disabled=!state.hasGold;if(!state.hasGold)$('#drift-enabled').checked=false;
  const previous=$('#raw-view').value;fillSelect($('#raw-view'),state.hasGold?['full_reflectance','full_raw']:['full_raw'],previous);
  for(const option of $('#raw-view').options)option.textContent=option.value==='full_raw'?'Raw intensity':'Reflectance';
  for(const option of $('#time-kind').options){option.disabled=option.value==='reflectance'&&!state.hasGold;option.hidden=option.disabled;option.textContent=stageNames[stages.indexOf(option.value)];}
  if($('#time-kind').value==='reflectance'&&!state.hasGold)$('#time-kind').value='raw';
  $('#gold-qc').hidden=!state.hasGold;
}
function normalizationControls(){
  const choice=$('#has-gold').value;
  $('#gold-options').hidden=choice!=='yes';$('#normalize').disabled=!choice;
  $('#normalize').textContent=choice==='no'?'Skip reflectance · continue with raw intensity →':'Calculate reflectance';
}
async function refreshNormalization(epoch){
  normalizationControls();$('#normalization-preview').replaceChildren();
  await heatmap($('#normalization-preview'),'full_raw','Raw MCT intensity',null,epoch);
  if(state.hasGold&&!state.normalizationDirty)await heatmap($('#normalization-preview'),'full_reflectance','Reflectance = raw / gold reference',null,epoch);
  if(epoch!==state.viewEpoch)return;
  $('#normalization-status').textContent=state.normalizationDirty?'Choose the gold-reference option and confirm. Any previous normalization is no longer current.':state.hasGold?'Cyan crosses show the exact raw pixels used. Verify that these pixels lie on the gold patch. Each image uses its own reference mean.':'Reflectance was skipped. Subsequent steps use raw intensity.';
}
function normalizationChanged(){state.normalizationDirty=true;invalidateFrom(4);normalizationControls();if(state.step===3)refreshView().catch(e=>notify(e.message,true));}
$('#has-gold').onchange=normalizationChanged;
$('#normalize').onclick=()=>busy($('#normalize'),async()=>{
  const hasGold=$('#has-gold').value==='yes';if(!$('#has-gold').value)throw Error('Choose whether a gold patch reference is available.');
  const d=await api('/api/normalize',{has_gold:hasGold,n_pixels:+$('#reference-pixels').value,robust_z_threshold:+$('#qc-z').value,relative_threshold:+$('#qc-deviation').value});
  Object.assign(state,{hasGold:d.has_gold,normalizationDirty:false,qc:d.qc,version:d.version,cnr:[],cnrDirty:true,r0:[]});state.rois={on:null,r0:null,background:null,target:null};driftReference=null;driftROIs=null;updateSignalLabels();unlock(4);
  notify(hasGold?'Reflectance calculated. Review the selected gold pixels and both images before continuing.':'Reflectance skipped. Cropping and corrections will use raw intensity.');
  if(hasGold)await refreshView();else go(4);
});
let driftReference=null, driftROIs=null;
function captureDriftReference(){driftReference={reference_pattern:$('#preview-pattern').value,wavenumber:+$('#preview-band').value};driftROIs=null;$('#drift-reference').textContent=`Reference: ${driftReference.reference_pattern} · ${driftReference.wavenumber} cm⁻¹`;$('#drift-table').replaceChildren();}
function cropPayload(){if(!state.rois.on)throw Error('Draw an on-MS ROI first.');if(!driftReference)captureDriftReference();return {roi:state.rois.on,drift:{enabled:$('#drift-enabled').checked,...driftReference,side:$('#drift-side').value,max_shift:+$('#drift-max').value}};}
$('#preview-drift').onclick=()=>busy($('#preview-drift'),async()=>{const d=await api('/api/crop-preview',cropPayload());driftROIs=d.rois;table($('#drift-table'),d.records,['pattern','dx','dy','left_gold_x','right_gold_x']);drawAll();notify('Crop preview ready. Switch preview patterns to inspect adjusted positions.');});
for(const id of ['drift-enabled','drift-side','drift-max'])$(`#${id}`).onchange=()=>{driftROIs=null;invalidateFrom(5);$('#drift-table').replaceChildren();drawAll();};
function coords(name){const root=$(`#${name==='on'?'on':'r0'}-coordinates`);root.replaceChildren();const roi=state.rois[name];for(const key of ['x_min','x_max','y_min','y_max']){const label=el('label',key.replace('_',' ')),input=el('input');input.type='number';input.min=0;input.value=roi?roi[key]:'';input.oninput=()=>{if(!state.rois[name])state.rois[name]={x_min:0,x_max:0,y_min:0,y_max:0};state.rois[name][key]=+input.value;if(name==='on')captureDriftReference();invalidateFrom(name==='on'?5:7);drawAll()};label.append(input);root.append(label)}}
const r0ReferenceBands={};
function renderR0References(){
  fillSelect($('#r0-all-band'),state.bands,$('#r0-all-band').value||Object.keys(state.mapping)[0]);
  const root=$('#r0-reference-bands');root.replaceChildren();
  for(const pattern of state.patterns){
    if(!state.bands.includes(r0ReferenceBands[pattern]))r0ReferenceBands[pattern]=+Object.keys(state.mapping)[0];
    const label=el('label',`${pattern} · reference wavenumber`),select=el('select');
    fillSelect(select,state.bands,r0ReferenceBands[pattern]);
    select.onchange=()=>{r0ReferenceBands[pattern]=+select.value;invalidateFrom(7);refreshView().catch(e=>notify(e.message,true));};
    label.append(select);root.append(label);
  }
}
$('#r0-apply-all').onclick=()=>{const wn=+$('#r0-all-band').value;for(const pattern of state.patterns)r0ReferenceBands[pattern]=wn;invalidateFrom(7);refreshView().catch(e=>notify(e.message,true));};
function imageParams(kind){return {pattern:$('#preview-pattern').value,wavenumber:$('#preview-band').value,kind,low:$('#display-low').value,high:$('#display-high').value,version:state.version}}
async function heatmap(root,kind,title,roiName=null,epoch=state.viewEpoch){const card=el('div',undefined,'image-card');if(['absorbance','baseline'].includes(kind))card.dataset.absorbancePreview='true';card.append(el('h4',title));if(roiName==='cnr'){const metrics=el('div',undefined,'cnr-parameters');renderCNRParameters(metrics);card.append(metrics);}root.append(card);const params=imageParams(kind);const zeroKey=root.id+':'+kind;params.colorbar_zero=zeroColorbars.has(zeroKey);zeroControl(card,zeroKey,()=>refreshView());if(kind==='full_raw')params.brightest='true';if(kind==='spectrum'){params.window=String($('#inspection-window').checked);params.min_frequency=$('#candidate-min').value;}if(roiName==='cnr'&&$('#cnr-reuse-r0').checked)params.cnr_background_source='analyte_free';if(roiName==='r0'&&$('#r0-method').value!=='roi'){params.r0_method=$('#r0-method').value;params.r0_count=$('#r0-count').value;params.r0_reference_band=r0ReferenceBands[$('#preview-pattern').value];if($('#r0-restrict').checked){if(!state.rois.r0){card.append(el('p','Draw a search rectangle to preview selected pixels.','hint'));params.r0_method='roi';}else params.r0_search_roi=JSON.stringify(state.rois.r0);}}const data=await api('/api/image?'+new URLSearchParams(params));if(epoch!==state.viewEpoch)return;if(!data.available){card.append(el('div',kind==='baseline'?'Reference-only band: no baseline center configured':'Available after processing','placeholder'));return}const wrap=el('div',undefined,'heatmap'),canvas=el('canvas');canvas.width=data.width;canvas.height=data.height;wrap.append(canvas);const bar=el('div',undefined,'bar'),strip=el('div',undefined,'strip'),ticks=el('div',undefined,'ticks');[data.vmax,(data.vmax+data.vmin)/2,data.vmin].forEach(v=>ticks.append(el('span',v.toFixed(3))));bar.append(strip,ticks);wrap.append(bar);card.append(wrap);if(kind==='spectrum')card.append(el('div','fx: −0.5 → +0.5; fy: −0.5 (top) → +0.5 (bottom)','axis-hint'));const image=new Image;image.src='data:image/png;base64,'+data.png;await image.decode();if(epoch!==state.viewEpoch)return;const view={canvas,image,data,kind,roiName,titleNode:card.querySelector('h4'),metricsNode:card.querySelector('.cnr-parameters'),title};state.canvases.push(view);bindCanvas(view);draw(view);if(data.gold_pixels&&!state.normalizationDirty)card.append(el('p',data.gold_pixels.length+' normalization pixels · I_gold = '+fmt(data.i_goldref),'hint'));if(kind==='spectrum'){renderPeaks(data.peaks||[]);addSpectrumLabels(wrap,data);}if(roiName==='r0'&&data.cell_free_pixels)$('#r0-preview-status').textContent=`${data.cell_free_pixels.length} ${$('#r0-method').value} pixels from ${data.reference_wavenumber} cm⁻¹ · preview reference mean ${fmt(data.cell_free_r0)}`}
function addSpectrumLabels(wrap,data){
  // Vector annotations remain sharp when a low-resolution FFT image is enlarged.
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);
  // Canvas and vector overlay share one flex item, including colorbar-induced shrinkage.
  const canvas=wrap.querySelector('canvas'),holder=canvas.parentElement===wrap?el('div'):canvas.parentElement;holder.querySelector('svg')?.remove();
  holder.style.cssText='position:relative;flex:1;min-width:0;align-self:flex-start';
  if(canvas.parentElement===wrap){canvas.replaceWith(holder);holder.append(canvas);}canvas.style.width='100%';canvas.style.height='100%';canvas.style.position='absolute';canvas.style.inset='0';holder.style.aspectRatio='1 / 1';
  svg.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';
  svg.setAttribute('preserveAspectRatio','none');
  const scale=data.width/700,sigmaX=+$('#notch-sigma-x').value,sigmaY=+$('#notch-sigma-y').value,radius=Number.isFinite(sigmaX)&&sigmaX>0?sigmaX*data.width:0,radiusY=Number.isFinite(sigmaY)&&sigmaY>0?sigmaY*data.height:0,fontSize=11*scale;
  for(const peak of data.peaks||[]){
    const x=peak.ix+.5,y=peak.iy+.5,circle=document.createElementNS(ns,'ellipse');
    circle.setAttribute('cx',x);circle.setAttribute('cy',y);circle.setAttribute('rx',radius);circle.setAttribute('ry',radiusY);
    circle.setAttribute('fill','none');circle.setAttribute('stroke','#00eaff');circle.setAttribute('stroke-width',.8*scale);svg.append(circle);
    const text=document.createElementNS(ns,'text');
    text.setAttribute('x',Math.min(data.width-2*fontSize,x+radius+2*scale));
    text.setAttribute('y',Math.max(fontSize,y-radiusY-2*scale));
    text.setAttribute('fill','#00eaff');text.setAttribute('font-size',fontSize);text.setAttribute('font-family','Arial, sans-serif');
    text.textContent=String(peak.rank);svg.append(text);
  }
  const ellipse=(fy,fx,rx,ry,color,dashed)=>{
    const node=document.createElementNS(ns,'ellipse');
    node.setAttribute('cx',(fx-data.fx[0])*data.width+.5);node.setAttribute('cy',(fy-data.fy[0])*data.height+.5);
    node.setAttribute('rx',rx*data.width);node.setAttribute('ry',ry*data.height);
    node.setAttribute('fill','none');node.setAttribute('stroke',color);node.setAttribute('stroke-width',scale);
    if(dashed)node.setAttribute('stroke-dasharray',`${5*scale} ${3*scale}`);svg.append(node);
  };
  const mode=$('#filter-mode').value;
  if($('#fourier-enabled').checked){
    if(['lowpass','combined'].includes(mode))ellipse(0,0,+$('#cutoff-x').value,+$('#cutoff-y').value,'#7dff00',true);
    if(['notch','combined'].includes(mode)&&radius>0&&radiusY>0){try{for(const [fy,fx] of notchCenters()){ellipse(fy,fx,sigmaX,sigmaY,'#00eaff',false);ellipse(-fy,-fx,sigmaX,sigmaY,'#00eaff',false);}}catch(e){}}
  }
  holder.append(svg);
  const pad=Math.max(0,+$('#fourier-pad').value||0),w=data.width,h=data.height,paddedW=w+2*pad,paddedH=h+2*pad;
  const root=$('#padding-preview');root.replaceChildren(el('p',`Spatial padding: ${pad} pixels on each side · ${w} × ${h} → ${paddedW} × ${paddedH}. Solid rectangle: original crop; surrounding area: reflection padding.`,'hint'));
  const diagram=document.createElementNS(ns,'svg');diagram.setAttribute('viewBox',`0 0 ${paddedW} ${paddedH}`);diagram.style.cssText='display:block;width:calc(100% - 57px);aspect-ratio:1 / 1;height:auto;background:#dce6df';diagram.setAttribute('preserveAspectRatio','xMidYMid meet');
  const rect=document.createElementNS(ns,'rect');for(const [key,value] of Object.entries({x:pad,y:pad,width:w,height:h,fill:'#213a35',stroke:'#00eaff','stroke-width':Math.max(paddedW/180,1)}))rect.setAttribute(key,value);diagram.append(rect);root.append(diagram);
}
function formatDuration(seconds){
  if(!Number.isFinite(seconds))return '—';
  const total=Math.max(0,Math.round(seconds));
  return [Math.floor(total/3600),Math.floor(total%3600/60),total%60].map(v=>String(v).padStart(2,'0')).join(':');
}
// Keep selection outlines sharp and one CSS pixel wide at every image scale.
function drawROIOverlay(canvas,regions){
  const ns='http://www.w3.org/2000/svg';
  let holder=canvas.parentElement;
  if(!holder.classList.contains('roi-image-holder')){
    holder=el('div',undefined,'roi-image-holder');
    holder.style.cssText='position:relative;width:calc(100% - 57px);min-width:0;align-self:flex-start';
    canvas.replaceWith(holder);holder.append(canvas);canvas.style.width='100%';
  }
  let overlay=holder.querySelector('.roi-overlay');
  if(!overlay){overlay=document.createElementNS(ns,'svg');overlay.classList.add('roi-overlay');overlay.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible';holder.append(overlay);}
  overlay.setAttribute('viewBox',`0 0 ${canvas.width} ${canvas.height}`);
  overlay.setAttribute('preserveAspectRatio','none');overlay.replaceChildren();
  for(const {roi:r,color} of regions){
    if(!r)continue;
    const box=document.createElementNS(ns,'rect');
    for(const [key,value] of Object.entries({x:r.x_min,y:r.y_min,width:r.x_max-r.x_min,height:r.y_max-r.y_min,fill:'none',stroke:color,'stroke-width':1,'stroke-opacity':1,'stroke-dasharray':'4 3','vector-effect':'non-scaling-stroke'}))box.setAttribute(key,value);
    overlay.append(box);
  }
}

function draw(v){const ctx=v.canvas.getContext('2d');ctx.clearRect(0,0,v.canvas.width,v.canvas.height);ctx.drawImage(v.image,0,0,v.canvas.width,v.canvas.height);const pairs=v.roiName==='cnr'?[['background','#00eaff'],['target','#7dff00']]:v.roiName==='r0'&&$('#r0-method').value!=='roi'&&!$('#r0-restrict').checked?[]:v.roiName?[[v.roiName,'#00eaff']]:[];if(v.roiName)drawROIOverlay(v.canvas,pairs.map(([name,color])=>({roi:name==='background'&&$('#cnr-reuse-r0').checked?v.data.analyte_free_roi:name==='on'&&driftROIs?driftROIs[$('#preview-pattern').value]:state.rois[name],color})));if(v.roiName==='cnr')drawProfileLine(v);if(v.data.cell_free_pixels){ctx.strokeStyle='#00eaff';ctx.lineWidth=Math.max(.35,v.data.width/1200);const arm=Math.max(1.25,v.data.width/320);for(const [y,x] of v.data.cell_free_pixels){ctx.beginPath();ctx.moveTo(x+.5-arm,y+.5);ctx.lineTo(x+.5+arm,y+.5);ctx.moveTo(x+.5,y+.5-arm);ctx.lineTo(x+.5,y+.5+arm);ctx.stroke();}}if(v.data.gold_pixels)drawGoldPixels(v.canvas,v.data.gold_pixels);if(v.roiName==='cnr'){const row=state.cnr.find(r=>r.pattern===$('#preview-pattern').value&&r.wavenumber===+$('#preview-band').value&&r.stage===v.kind);v.titleNode.textContent=v.title;renderCNRParameters(v.metricsNode,row);v.metricsNode.title=row?`Background SD uses ddof=1. Status: ${row.status}`:'Calculate CNR to show parameters';}}
function drawAll(){state.canvases.forEach(draw);sendParent({type:'progress',step:state.step,maxStep:state.maxStep,cnrDirty:state.cnrDirty||!state.cnr.length});}
function bindCanvas(v){let start=null;const point=e=>{const b=v.canvas.getBoundingClientRect();return{x:Math.max(0,Math.min(v.data.width,(e.clientX-b.left)*v.data.width/b.width)),y:Math.max(0,Math.min(v.data.height,(e.clientY-b.top)*v.data.height/b.height))}};v.canvas.onpointerdown=e=>{if(document.body.classList.contains('busy'))return;if(v.roiName==='cnr'&&state.mode==='line'){selectProfilePoint(v,point(e));return;}if(v.kind==='spectrum'){if(!$('#fourier-enabled').checked||!['notch','combined'].includes($('#filter-mode').value))return;const p=point(e);const fx=v.data.fx[Math.min(v.data.width-1,Math.floor(p.x))],fy=v.data.fy[Math.min(v.data.height-1,Math.floor(p.y))];const peak=(v.data.peaks||[]).find(q=>Math.hypot(q.ix-p.x,q.iy-p.y)<8);addNotchPair(peak?peak.fy:fy,peak?peak.fx:fx);return}if(!v.roiName||(v.roiName==='r0'&&$('#r0-method').value!=='roi'&&!$('#r0-restrict').checked))return;if(v.roiName==='cnr'&&!state.mode)return;start=point(e);v.canvas.setPointerCapture(e.pointerId)};const update=e=>{if(!start)return;const p=point(e),name=v.roiName==='cnr'?state.mode:v.roiName;state.rois[name]={x_min:Math.floor(Math.min(start.x,p.x)),x_max:Math.ceil(Math.max(start.x,p.x)),y_min:Math.floor(Math.min(start.y,p.y)),y_max:Math.ceil(Math.max(start.y,p.y))};if(name==='on')captureDriftReference();if(name==='on'||name==='r0'){invalidateFrom(name==='on'?5:7);coords(name)}else{state.cnr=[];if(name==='background')state.rois.target=null;$('#cnr-table').replaceChildren();chart($('#cnr-chart'),[]);}drawAll()};v.canvas.onpointermove=update;v.canvas.onpointerup=e=>{const drawn=!!start;update(e);start=null;if(drawn&&v.roiName==='r0'&&$('#r0-restrict').checked&&$('#r0-method').value!=='roi')refreshView().catch(e=>notify(e.message,true));};v.canvas.onpointercancel=()=>start=null}
async function refreshView(){
  clearInterval(state.timer);state.timer=null;
  if(state.step===1)drawROICharts();if(state.step<3)return;
  const epoch=++state.viewEpoch;state.canvases=[];
  if(state.step===3){await refreshNormalization(epoch);return;}
  updateSignalLabels();
  if(state.step===4){
    $('#crop-preview').replaceChildren();coords('on');
    await heatmap($('#crop-preview'),$('#raw-view').value,state.hasGold?'Full image':'Full raw intensity','on',epoch);
    if(state.hasGold){table($('#qc-table'),state.qc,['pattern','wavenumber','i_goldref','reference_valid','frame_valid']);chart($('#qc-chart'),state.bands.map(wn=>({name:String(wn),values:state.qc.filter(r=>r.wavenumber===wn).map(r=>r.i_goldref)})));}
  }
  if(state.step===5){$('#spectrum-preview').replaceChildren();await heatmap($('#spectrum-preview'),'spectrum','Inspect spectrum · click to add notches',null,epoch);schedulePreview();}
  if(state.step===6){
    $('#r0-preview').replaceChildren();$('#r0-preview-status').textContent='';$('#processing-preview').replaceChildren();coords('r0');renderR0References();
    await heatmap($('#r0-preview'),'rolling',stageNames[3],'r0',epoch);
    const kinds=[state.hasGold?'reflectance':'raw','fourier','rolling',...(state.maxStep>=7?['absorbance']:[])];
    await Promise.all(kinds.map(kind=>heatmap($('#processing-preview'),kind,stageNames[stages.indexOf(kind)],null,epoch)));
  }
  if(state.step===7){table($('#baseline-mapping'),Object.entries(state.mapping).map(([center,refs])=>({center,reference_bands:refs.join(', ')})),['center','reference_bands']);$('#baseline-preview').replaceChildren();await Promise.all((state.maxStep>=8?['absorbance','baseline']:['absorbance']).map(kind=>heatmap($('#baseline-preview'),kind,stageNames[stages.indexOf(kind)],null,epoch)));if(epoch===state.viewEpoch&&state.maxStep>=8)await prepareBaselineInspection();}
  if(state.step===9)updateTimeBands();
  if(state.step===8){$('#six-stages').replaceChildren();await Promise.all(activeStages().map(kind=>heatmap($('#six-stages'),kind,stageNames[stages.indexOf(kind)],'cnr',epoch)));showCNR();table($('#r0-table'),state.r0,['pattern','wavenumber','method','reference_wavenumber','pixel_count','r0','reference_mean_absorbance']);if(epoch===state.viewEpoch)await refreshLineProfile();}
}

function drawGoldPixels(canvas,pixels){
  if(state.normalizationDirty)return;
  if(!canvas.parentElement.classList.contains('roi-image-holder'))drawROIOverlay(canvas,[]);
  const svg=canvas.parentElement.querySelector('.roi-overlay'),ns='http://www.w3.org/2000/svg';
  svg.querySelector('.gold-pixels')?.remove();const group=document.createElementNS(ns,'g');group.classList.add('gold-pixels');
  const arm=3*canvas.width/(canvas.clientWidth||canvas.width);
  for(const [y,x] of pixels){const cross=document.createElementNS(ns,'path');cross.setAttribute('d',`M ${x+.5-arm} ${y+.5} h ${2*arm} M ${x+.5} ${y+.5-arm} v ${2*arm}`);cross.setAttribute('stroke','#00eaff');cross.setAttribute('stroke-width','1');cross.setAttribute('vector-effect','non-scaling-stroke');cross.setAttribute('fill','none');group.append(cross);}
  svg.append(group);
}
$('#confirm-crop').onclick=()=>busy($('#confirm-crop'),async()=>{if(!state.rois.on)throw Error('Please first Select the on-MS region.');const d=await api('/api/crop',cropPayload());state.version=d.version;state.rois.r0=state.rois.background=state.rois.target=null;unlock(5);notify('Per-pattern on-MS crops confirmed.');go(5)});
function filterMode(){const mode=$('#filter-mode').value;$$('[data-filter]').forEach(n=>n.hidden=n.dataset.filter!==mode&&mode!=='combined')}
$('#filter-mode').onchange=()=>{filterMode();processingChanged()};
$('#clear-notches').onclick=()=>{$('#notches').value='';processingChanged()};
function notchCenters(){const text=$('#notches').value.trim();if(!text)return[];return text.split(/[;\n]+/).filter(s=>s.trim()).map(s=>{const pair=s.split(',').map(v=>Number(v.trim()));if(pair.length!==2||pair.some(v=>!Number.isFinite(v)))throw Error('Use fy, fx pairs separated by semicolons.');return pair})}
function showBatchProgress(p){
  const percent=p.total?100*p.completed/p.total:0;
  $('#batch-progress').hidden=false;$('#batch-bar').value=percent;
  const seconds=Math.floor(p.elapsed_seconds||0), elapsed=`${Math.floor(seconds/60)}m ${seconds%60}s`;
  $('#batch-detail').textContent=`${p.status} · ${p.pattern?`${p.pattern} · ${p.wavenumber} cm⁻¹`:'Waiting to start'} · Completed ${p.completed}/${p.total} ${p.unit||'files'} (${percent.toFixed(1)}%) · Elapsed ${elapsed}`;
}
$('#process').onclick=()=>busy($('#process'),async()=>{
  const {fourier,rolling}=processingParameters();
  showBatchProgress({status:'starting',completed:0,total:state.patterns.length*state.bands.length,elapsed_seconds:0});
  let active=true;
  const poll=async()=>{try{const p=await api('/api/process-progress');if(active)showBatchProgress(p);}catch(e){}finally{if(active)setTimeout(poll,500);}};
  const request=api('/api/process',{fourier,rolling});
  setTimeout(()=>{if(active)poll();},300);
  try{
    const d=await request;state.version=d.version;state.rois.r0=state.rois.background=state.rois.target=null;state.r0=[];unlock(6);notify(`Completed ${d.summary.length} images processed with the selected settings.`);go(6);
  }finally{active=false;try{showBatchProgress(await api('/api/process-progress'));}catch(e){}}
});
function r0Mode(){const extreme=$('#r0-method').value!=='roi';$('#r0-roi-controls').hidden=extreme&&!$('#r0-restrict').checked;$('#r0-extreme-controls').hidden=!extreme;invalidateFrom(7);if(state.step===6)refreshView().catch(e=>notify(e.message,true))}
$('#r0-method').onchange=r0Mode;$('#r0-restrict').onchange=r0Mode;
$('#r0-count').onchange=()=>{invalidateFrom(7);if(state.step===6)refreshView().catch(e=>notify(e.message,true))};
$('#calculate').onclick=()=>busy($('#calculate'),async()=>{const method=$('#r0-method').value;if(method==='roi'&&!state.rois.r0)throw Error('Select a analyte-free ROI first.');const payload={method};if(method==='roi')payload.roi=state.rois.r0;else{payload.count=+$('#r0-count').value;if($('#r0-restrict').checked){if(!state.rois.r0)throw Error('Draw a search rectangle first.');payload.search_roi=state.rois.r0;}payload.reference_bands=Object.fromEntries(state.patterns.map(p=>[p,r0ReferenceBands[p]]));}const d=await api('/api/calculate',payload);state.version=d.version;state.r0=d.r0;state.cnr=[];state.rois.background=state.rois.target=null;state.mode=null;state.cnrDirty=false;unlock(7);clearBaselineInspection();$('#baseline-preview').replaceChildren();notify('Absorbance calculated. Review the preview, then continue to baseline correction.');await refreshView()});
$('#calculate-baseline').onclick=()=>busy($('#calculate-baseline'),async()=>{const d=await api('/api/baseline',{});state.version=d.version;state.cnr=[];state.rois.background=state.rois.target=null;state.cnrDirty=false;state.mode=null;unlock(8);notify('Baseline correction complete. Inspect the images and pixel fits below.');await refreshView();});
$('#cnr-reuse-r0').onchange=()=>{
  state.cnrDirty=true;state.cnr=[];state.rois.background=state.rois.target=null;state.mode=null;
  $('#cnr-background').disabled=$('#cnr-reuse-r0').checked;
  $('#cnr-instruction').textContent=$('#cnr-reuse-r0').checked?'Using the saved Section 6 selection for each pattern. Select a target ROI.':'Select background: draw a new analyte-free rectangle, then select target.';
  showCNR();refreshView().catch(e=>notify(e.message,true));
};
$('#cnr-background').onclick=()=>{state.cnrDirty=true;state.mode='background';state.rois.background=state.rois.target=null;state.cnr=[];showCNR();$('#cnr-instruction').textContent='Select background: drag a rectangle on any stage.';drawAll()};
$('#cnr-target').onclick=()=>{if(!$('#cnr-reuse-r0').checked&&!state.rois.background){notify('Select the background first.',true);return}state.cnrDirty=true;state.mode='target';state.rois.target=null;state.cnr=[];showCNR();$('#cnr-instruction').textContent='Select target ROI: it must not overlap the background.';drawAll()};
$('#calculate-cnr').onclick=()=>busy($('#calculate-cnr'),async()=>{if((!$('#cnr-reuse-r0').checked&&!state.rois.background)||!state.rois.target)throw Error('Select background, then target ROI.');const d=await api('/api/cnr',{background_source:$('#cnr-reuse-r0').checked?'analyte_free':'manual',background:state.rois.background,target:state.rois.target,low:+$('#display-low').value,high:+$('#display-high').value});state.cnr=d.records;state.cnrDirty=false;state.mode=null;unlock(10);await refreshView();notify('CNR calculated using the selected background source and target ROI across all stages.')});
function fmt(v){if(v===null||v===undefined)return'—';if(typeof v==='number')return Number(v.toPrecision(6)).toString();return String(v)}
function table(root,rows,keys){root.replaceChildren();if(!rows.length){root.append(el('p','No results yet','hint'));return}const t=el('table'),head=el('thead'),tr=el('tr');keys.forEach(k=>tr.append(el('th',k)));head.append(tr);const body=el('tbody');rows.forEach(r=>{const row=el('tr');keys.forEach(k=>row.append(el('td',fmt(r[k]))));body.append(row)});t.append(head,body);root.append(t)}
function chart(canvas,series,labels=[]){const ctx=canvas.getContext('2d'),ratio=devicePixelRatio||1,w=canvas.clientWidth||600,h=240;canvas.width=w*ratio;canvas.height=h*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);const finite=series.flatMap(s=>s.values).filter(v=>v!==null&&Number.isFinite(v));if(!finite.length){ctx.fillStyle='#829389';ctx.fillText('The trend appears after calculation',20,35);return}const low=Math.min(...finite),high=Math.max(...finite),span=high-low||1,p={l:55,r:20,t:30,b:48},colors=['#157e69','#b6803b','#6473a1','#995477'];ctx.font='10px sans-serif';for(let i=0;i<4;i++){const y=p.t+(h-p.t-p.b)*i/3;ctx.strokeStyle='#e4eae5';ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(w-p.r,y);ctx.stroke();ctx.fillStyle='#708477';ctx.fillText(fmt(high-span*i/3).slice(0,7),4,y+3)}series.forEach((s,index)=>{const color=colors[index%colors.length],n=s.values.length;ctx.strokeStyle=color;ctx.lineWidth=1.8;ctx.beginPath();let connect=false;s.values.forEach((v,i)=>{if(v===null||!Number.isFinite(v)){connect=false;return}const x=p.l+(w-p.l-p.r)*i/Math.max(1,n-1),y=p.t+(h-p.t-p.b)*(high-v)/span;if(connect)ctx.lineTo(x,y);else ctx.moveTo(x,y);connect=true});ctx.stroke();ctx.fillStyle=color;ctx.fillText(s.name,p.l+index*110,15)});labels.forEach((s,i)=>{ctx.fillStyle='#708477';ctx.fillText(s,p.l+(w-p.l-p.r)*i/Math.max(1,labels.length-1)-15,h-15)})}
function cnrNumber(value,digits=2){return typeof value==='number'&&Number.isFinite(value)?(digits===0?value.toFixed(0):value.toExponential(digits)):'—';}
function cnrSymbol(label){
  const symbols={'A_s':'<i>A</i><sub>s</sub>','A_bg':'<i>A</i><sub>bg</sub>','sigma_bg':'σ<sub>bg</sub>','A_s − A_bg':'<i>A</i><sub>s</sub> − <i>A</i><sub>bg</sub>','|A_s − A_bg|':'|<i>A</i><sub>s</sub> − <i>A</i><sub>bg</sub>|'};
  return symbols[label];
}
function renderCNRParameters(node,row){
  node.replaceChildren();
  node.append(el('div',`Unadjusted CNR: ${cnrNumber(row?.cnr_unadjusted,0)} · CNR: ${cnrNumber(row?.cnr,0)} · Percentiles: ${row?`${row.contrast_low_percentile}–${row.contrast_high_percentile}`:'—'}`));
  const line=el('div');node.append(line);
  const values=[['A_s',row?.target_mean,2],['A_bg',row?.background_mean,2],['sigma_bg',row?.background_std,2],['|A_s − A_bg|',row?.signed_contrast==null?null:Math.abs(row.signed_contrast),2]];
  values.forEach(([label,value,digits],i)=>{if(i)line.append(document.createTextNode(' · '));const symbol=el('span');symbol.innerHTML=cnrSymbol(label);line.append(symbol,document.createTextNode(': '+cnrNumber(value,digits)));});
}
function showCNR(){
  if(state.cnrDirty){reproductionReport=null;$('#reproduction-report').hidden=true;}
  const rows=state.cnr.filter(r=>r.pattern===$('#preview-pattern').value&&r.wavenumber===+$('#preview-band').value&&activeStages().includes(r.stage));
  const details=rows.map(r=>({
    Stage:stageNames[stages.indexOf(r.stage)],CNR:cnrNumber(r.cnr,0),
    'Unadjusted CNR':cnrNumber(r.cnr_unadjusted,0),'Percentiles':`${r.contrast_low_percentile}–${r.contrast_high_percentile}`,
    'Clip minimum':r.contrast_vmin,'Clip maximum':r.contrast_vmax,
    'A_s':cnrNumber(r.target_mean),'A_bg':cnrNumber(r.background_mean),
    'sigma_bg':cnrNumber(r.background_std),
    'A_s − A_bg':cnrNumber(r.signed_contrast),
    '|A_s − A_bg|':cnrNumber(r.signed_contrast===null?null:Math.abs(r.signed_contrast)),
    'Target pixels':r.target_pixels,'Background pixels':r.background_pixels,
    'Excluded target pixels':r.excluded_target_pixels,'Excluded background pixels':r.excluded_background_pixels,
    Status:r.status
  }));
  table($('#cnr-table'),details,details.length?Object.keys(details[0]):[]);
  $('#cnr-table').querySelectorAll('th').forEach(th=>{const symbol=cnrSymbol(th.textContent);if(symbol)th.innerHTML=symbol;});
  for(const metric of ['cnr'])chart($('#'+metric+'-chart'),rows.length?[{name:metric.toUpperCase(),values:rows.map(r=>r[metric])}]:[],rows.map(r=>stageNames[stages.indexOf(r.stage)]));
}

function updateTimeBands(){
  const bands=$('#time-kind').value==='baseline'?Object.keys(state.mapping).map(Number).sort((a,b)=>a-b):state.bands;
  fillSelect($('#time-band'),bands,$('#time-band').value||$('#preview-band').value);
}
async function buildTime(){
  return busy($('#build-time'),async()=>{
    $('#time-band').disabled=true;$('#time-kind').disabled=true;
    try{
const frameIndex=+$('#time-slider').value;$('#time-player').hidden=true;clearInterval(state.timer);state.timer=null;state.time=await api('/api/timelapse',{wavenumber:+$('#time-band').value,kind:$('#time-kind').value,start:+$('#time-start').value,end:+$('#time-end').value,skip_invalid:$('#time-skip').checked,colorbar_zero:zeroColorbars.has('time'),low:+$('#time-low').value,high:+$('#time-high').value});updateVideoTitle();$('#time-extrema').textContent=state.time.extrema_label;$('#time-ticks').replaceChildren(...[state.time.vmax,(state.time.vmax+state.time.vmin)/2,state.time.vmin].map(v=>el('span',v.toFixed(3))));$('#time-player').hidden=false;$('#time-slider').max=state.time.frames.length-1;$('#time-slider').value=Math.min(frameIndex,state.time.frames.length-1);renderFrame();notify(`Built ${state.time.frames.length} frames. All frames use the same color scale.`)
    }finally{$('#time-band').disabled=false;$('#time-kind').disabled=false;}
  });
}
$('#build-time').onclick=buildTime;
$('#time-band').onchange=buildTime;
$('#time-kind').onchange=()=>{updateTimeBands();buildTime();};
function playbackFPS(){const value=+$('#time-fps').value;return Number.isFinite(value)?Math.min(20,Math.max(1,value)):4;}
function updateVideoTitle(){if(state.time)$('#time-settings').textContent=`${state.time.wavenumber} cm⁻¹ · ${stageNames[stages.indexOf(state.time.kind)]} · Contrast: ${state.time.low}–${state.time.high} percentiles · FPS: ${playbackFPS()}`;}
function frameLabel(video,i){const f=video.frames[i];return `${video.wavenumber} cm⁻¹ · ${f.pattern} · ${i+1}/${video.frames.length} · elapsed ${formatDuration(f.elapsed_seconds)} · ${new Date(f.timestamp*1000).toLocaleString()} · dt median ${formatDuration(video.median_interval_seconds)}`;}
function renderFrame(){const i=+$('#time-slider').value;$('#time-image').src='data:image/png;base64,'+state.time.frames[i].png;$('#time-label').textContent=frameLabel(state.time,i);updateVideoTitle();}
function startPlayback(){clearInterval(state.timer);state.timer=setInterval(()=>{$('#time-slider').value=(+$('#time-slider').value+1)%state.time.frames.length;renderFrame();},1000/playbackFPS());}
$('#time-slider').oninput=()=>{if(state.time)renderFrame();};
$('#time-play').onclick=()=>{if(state.timer){clearInterval(state.timer);state.timer=null;}else if(state.time)startPlayback();};
$('#time-fps').oninput=()=>{updateVideoTitle();if(state.timer)startPlayback();};
$('#export-video').onclick=()=>busy($('#export-video'),async()=>{
  if(!state.time)throw Error('Build a video first.');
  const video=state.time,fps=playbackFPS();
  notify('Encoding all frames of the current video with title and timestamps...');
  const response=await fetch(datasetURL('/api/export-video'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({video_id:video.video_id,fps,labels:video.frames.map((_,i)=>frameLabel(video,i))})});
  if(!response.ok){const error=await response.json();throw Error(error.error||'Video export failed.');}
  const url=URL.createObjectURL(await response.blob()),link=el('a');link.href=url;link.download=`qcl_${video.wavenumber}_${video.kind}_${fps}fps.mp4`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);notify('Current video exported as MP4, including title, FPS, color scale, and timestamps.');
});
for(const id of ['preview-pattern','preview-band','raw-view','inspection-window'])$(`#${id}`).onchange=()=>refreshView().catch(e=>notify(e.message,true));
$('#refresh-view').onclick=()=>refreshView().catch(e=>notify(e.message,true));
zeroControl($('#roi-spectrum-image').parentElement.parentElement,'roi-raw',async()=>{
  const zero=zeroColorbars.has('roi-raw');
  try{
    if(roiSpectra.image&&$('#roi-spectrum-band').value){
      const revision=roiSpectra.revision;
      const d=await api('/api/raw-inspection',{pattern:$('#roi-spectrum-pattern').value,wavenumber:+$('#roi-spectrum-band').value,mode:'image',colorbar_zero:zero});
      const img=new Image();img.src='data:image/png;base64,'+d.png;await img.decode();
      if(revision===roiSpectra.revision&&zero===zeroColorbars.has('roi-raw')){roiSpectra.image=img;$('#roi-spectrum-ticks').replaceChildren(...[d.vmax,(d.vmin+d.vmax)/2,d.vmin].map(v=>el('span',v.toFixed(3))));drawROISpectrumImage();}
    }
  }catch(e){notify(e.message,true);}
});
zeroControl($('#fit-image').parentElement.parentElement,'fit',()=>fitImage?inspectBaseline(true):null);
zeroControl($('#time-colorbar').parentElement,'time',()=>state.time&&state.step===9?buildTime():null);
for(const id of ['display-low','display-high'])$('#'+id).addEventListener('input',()=>{
  if(!state.cnr.length)return;
  state.cnr=[];state.cnrDirty=true;showCNR();drawAll();
  notify('Contrast changed. Refresh images and recalculate CNR before export.');
});
$$('[data-go]').forEach(b=>b.onclick=()=>go(+b.dataset.go));
$$('section[data-step="5"] input, section[data-step="5"] textarea, #rb-polarity').forEach(n=>{if(!['inspection-window','candidate-min'].includes(n.id))n.addEventListener('input',processingChanged)});$('#candidate-min').oninput=()=>refreshView().catch(e=>notify(e.message,true));
for(const id of ['reference-pixels','qc-z','qc-deviation'])$(`#${id}`).onchange=normalizationChanged;

renderNav();filterMode();r0Mode();

// Do not export an older CNR measurement after its visible ROIs are edited.
$('#download').onclick=e=>{if(state.maxStep<10||state.cnrDirty||((state.rois.background||state.rois.target)&&!state.cnr.length)){e.preventDefault();notify('ROI or contrast settings changed. Recalculate CNR before exporting.',true)}};

function processingParameters(){const mode=$('#filter-mode').value;const fourier={enabled:$('#fourier-enabled').checked,mode,centers:$('#fourier-enabled').checked&&['notch','combined'].includes(mode)?notchCenters():[],sigma_x:+$('#notch-sigma-x').value,sigma_y:+$('#notch-sigma-y').value,strength:+$('#notch-strength').value,protect_radius:+$('#protect-radius').value,cutoff_x:+$('#cutoff-x').value,cutoff_y:+$('#cutoff-y').value,pad_pixels:+$('#fourier-pad').value,preserve_mean:true};const rolling={enabled:$('#rolling-enabled').checked,radius:+$('#rb-radius').value,kernel_height:+$('#rb-height').value,feature_polarity:$('#rb-polarity').value,smooth_sigma:+$('#rb-sigma').value,pad_pixels:+$('#rb-pad').value,min_background:1e-6,reference_level:null};return {fourier,rolling};}

function clearBaselineInspection(){
  fitRevision++;fitImage=null;fitResult=null;
  $('#baseline-inspector').hidden=true;
  $('#fit-summary').textContent='';$('#fit-table').replaceChildren();
}
async function prepareBaselineInspection(){
  fillSelect($('#fit-pattern'),state.patterns,$('#fit-pattern').value||$('#preview-pattern').value);
  fillSelect($('#fit-center'),Object.keys(state.mapping).map(Number).sort((a,b)=>a-b),$('#fit-center').value||$('#preview-band').value);
  $('#baseline-inspector').hidden=false;
  await inspectBaseline(true);
}
function drawFitPixel(){
  if(!fitImage)return;
  const c=$('#fit-image'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(fitImage,0,0,c.width,c.height);
  const x=+$('#fit-x').value+.5,y=+$('#fit-y').value+.5;
  ctx.strokeStyle='#00eaff';ctx.lineWidth=Math.max(.4,c.width/500);
  const arm=Math.max(2,c.width/50);ctx.beginPath();ctx.moveTo(x-arm,y);ctx.lineTo(x+arm,y);ctx.moveTo(x,y-arm);ctx.lineTo(x,y+arm);ctx.stroke();
}
async function inspectBaseline(loadImage=false){
  const revision=++fitRevision;
  fitResult=null;drawBaselinePlot(null);$('#fit-table').replaceChildren();$('#fit-summary').textContent='Loading pixel fit…';
  try{
    const pattern=$('#fit-pattern').value,wavenumber=+$('#fit-center').value;
    if(loadImage){
      fitImage=null;const canvas=$('#fit-image');canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
      const data=await api('/api/image?'+new URLSearchParams({pattern,wavenumber,kind:'absorbance',colorbar_zero:zeroColorbars.has('fit'),low:$('#display-low').value,high:$('#display-high').value}));
      if(revision!==fitRevision)return;
      const img=new Image();img.src='data:image/png;base64,'+data.png;await img.decode();if(revision!==fitRevision)return;
      canvas.width=data.width;canvas.height=data.height;fitImage=img;
      for(const [axis,size] of [['x',data.width],['y',data.height]]){const input=$('#fit-'+axis);input.max=size-1;input.value=Math.max(0,Math.min(size-1,Number(input.value)||0));}
      $('#fit-image-ticks').replaceChildren(...[data.vmax,(data.vmin+data.vmax)/2,data.vmin].map(v=>el('span',v.toFixed(3))));
    }
    const d=await api('/api/baseline-pixel',{pattern,wavenumber,x:+$('#fit-x').value,y:+$('#fit-y').value});
    if(revision!==fitRevision)return;
    fitResult=d;drawFitPixel();drawBaselinePlot(d);
    $('#fit-summary').textContent=`${d.pattern} · ${d.wavenumber} cm⁻¹ · pixel (${d.x}, ${d.y}) · ${d.method}. ${d.valid?`A corrected = ${fmt(d.before)} − (${fmt(d.baseline)}) = ${fmt(d.after)}. Baseline(ν) = ${fmt(d.baseline)} + (${fmt(d.slope)}) × (ν − ${d.wavenumber}).`:d.status}`;
    table($('#fit-table'),d.references.map(r=>({...r,residual:r.absorbance===null||r.fitted===null?null:r.absorbance-r.fitted})),['wavenumber','absorbance','fitted','residual']);
  }catch(e){if(revision===fitRevision){$('#fit-summary').textContent=e.message;drawBaselinePlot(null);}}
}
function drawBaselinePlot(d){
  const canvas=$('#fit-chart'),ctx=canvas.getContext('2d'),ratio=devicePixelRatio||1,w=canvas.clientWidth||600,h=340;
  canvas.width=w*ratio;canvas.height=h*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);
  if(!d)return;
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const points=d.references.map(r=>[r.wavenumber,r.absorbance]);
  const values=[...points.map(p=>p[1]),d.before,d.after,...d.references.map(r=>r.fitted)].filter(finite);
  if(!values.length){ctx.fillText('No finite absorbance values at this pixel.',25,50);return;}
  const pad={l:72,r:22,t:68,b:50},xmin=Math.min(...points.map(p=>p[0])),xmax=Math.max(...points.map(p=>p[0]));
  const ymin=Math.min(...values),ymax=Math.max(...values),margin=(ymax-ymin||Math.max(Math.abs(ymin)*.1,.01))*.12;
  const lo=ymin-margin,hi=ymax+margin;
  const x=v=>pad.l+(v-xmin)/(xmax-xmin)*(w-pad.l-pad.r),y=v=>pad.t+(hi-v)/(hi-lo)*(h-pad.t-pad.b);
  ctx.font='11px sans-serif';ctx.fillStyle='#435b50';ctx.fillText('Absorbance',pad.l,51);
  for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,py=y(v);ctx.strokeStyle='#e4eae5';ctx.beginPath();ctx.moveTo(pad.l,py);ctx.lineTo(w-pad.r,py);ctx.stroke();ctx.fillText(v.toPrecision(3),5,py+4);}
  const ticks=[...new Set([...points.map(p=>p[0]),d.wavenumber])].sort((a,b)=>a-b);
  ctx.textAlign='center';for(const wn of ticks)ctx.fillText(String(wn),x(wn),h-pad.b+20);ctx.fillText('Wavenumber (cm⁻¹)',(pad.l+w-pad.r)/2,h-7);ctx.textAlign='left';
  if(finite(d.baseline)&&finite(d.slope)){ctx.strokeStyle='#157e69';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x(xmin),y(d.baseline+d.slope*(xmin-d.wavenumber)));ctx.lineTo(x(xmax),y(d.baseline+d.slope*(xmax-d.wavenumber)));ctx.stroke();}
  function dot(wn,v,color,square=false){if(!finite(v))return;ctx.fillStyle=color;ctx.beginPath();if(square)ctx.rect(x(wn)-4,y(v)-4,8,8);else ctx.arc(x(wn),y(v),4,0,Math.PI*2);ctx.fill();}
  for(const [wn,v] of points)dot(wn,v,'#6473a1');
  dot(d.wavenumber,d.before,'#c57522');dot(d.wavenumber,d.baseline,'#157e69',true);dot(d.wavenumber,d.after,'#aa477b');
  const legend=[['#6473a1','Reference points'],['#157e69','Baseline fit'],['#c57522','Center before'],['#aa477b','Center after']];
  legend.forEach(([color,label],i)=>{const lx=pad.l+(i%2)*(w-pad.l-pad.r)/2,ly=15+Math.floor(i/2)*18;ctx.fillStyle=color;ctx.fillRect(lx,ly-7,8,8);ctx.fillStyle='#435b50';ctx.fillText(label,lx+13,ly);});
}
$('#inspect-fit').onclick=()=>inspectBaseline(!fitImage);
for(const id of ['fit-pattern','fit-center'])$('#'+id).onchange=()=>inspectBaseline(true);
for(const id of ['fit-x','fit-y'])$('#'+id).oninput=()=>inspectBaseline(!fitImage);
$('#fit-image').onpointerdown=e=>{
  if(!fitImage||document.body.classList.contains('busy'))return;
  const c=e.currentTarget,b=c.getBoundingClientRect();
  $('#fit-x').value=Math.max(0,Math.min(c.width-1,Math.floor((e.clientX-b.left)*c.width/b.width)));
  $('#fit-y').value=Math.max(0,Math.min(c.height-1,Math.floor((e.clientY-b.top)*c.height/b.height)));
  inspectBaseline();
};
window.addEventListener('resize',()=>{if(fitResult&&!$('#baseline-inspector').hidden)drawBaselinePlot(fitResult);});

const sharedGroups={
  spectral:[],
  normalization:['has-gold','reference-pixels','qc-z','qc-deviation'],
  processing:['fourier-enabled','filter-mode','notches','notch-sigma-x','notch-sigma-y','notch-strength','protect-radius','fourier-pad','cutoff-x','cutoff-y','rolling-enabled','rb-radius','rb-height','rb-polarity','rb-sigma','rb-pad'],
  analyte:['r0-method','r0-count']
};
const sharedFieldIds=Object.values(sharedGroups).flat();
const sharing={spectral:true,normalization:true,processing:true,analyte:true};
for(const [group,step,label] of [
  ['spectral',2,'Use the same center and reference wavenumbers for all folders'],
  ['normalization',3,'Use the same normalization parameters for all folders'],
  ['processing',5,'Use the same Fourier and rolling-ball parameters for all folders'],
  ['analyte',6,'Use the same analyte-free selection method and pixel count for all folders']
]){
  const card=el('div',undefined,'card');card.dataset.sharing=group;card.hidden=true;
  const control=el('label',undefined,'check'),input=el('input');input.type='checkbox';input.checked=true;input.id='share-'+group;
  input.onchange=()=>sendParent({type:'sharing-toggle',group,enabled:input.checked});
  control.append(input,document.createTextNode(label));card.append(control,el('p','Shared across all folder tabs. Re-enabling uses the first folder that completed this section. Spatial regions remain independent.','hint'));
  document.querySelector(`section[data-step="${step}"] .intro`).after(card);
}
function updateSharing(message){
  Object.assign(sharing,message.sharing);
  for(const group of Object.keys(sharing)){
    $('#share-'+group).checked=sharing[group];
    document.querySelector(`[data-sharing="${group}"]`).hidden=!message.multiple;
  }
}
function sharedSnapshot(){return {mapping:state.mapping,fields:Object.fromEntries(sharedFieldIds.map(id=>{const n=$('#'+id);return [id,n.type==='checkbox'?n.checked:n.value];}))};}
function publishShared(){if(sharedReady&&!applyingShared)sendParent({type:'shared',settings:sharedSnapshot()});}
for(const id of sharedFieldIds)$('#'+id).addEventListener('change',publishShared);
for(const id of sharedFieldIds)if(!['r0-method','r0-count','reference-pixels','qc-z','qc-deviation'].includes(id))$('#'+id).addEventListener('input',publishShared);
function applyShared(settings){
  if(!state.discovery)return;
  applyingShared=true;
  try{
    const previous=sharedSnapshot();let from=Infinity;
    if(settings.mapping&&JSON.stringify(previous.mapping)!==JSON.stringify(settings.mapping))from=3;
    for(const [id,value] of Object.entries(settings.fields||{})){
      if(!sharedFieldIds.includes(id)||previous.fields[id]===value)continue;
      const n=$('#'+id);if(n.type==='checkbox')n.checked=value;else n.value=value;
      from=Math.min(from,sharedGroups.normalization.includes(id)?4:id.startsWith('r0-')?7:6);
    }
    if(settings.mapping)state.mapping=JSON.parse(JSON.stringify(settings.mapping));
    if(from===3){$('#center-options').replaceChildren();for(const wn of state.discovery.wavenumbers)$('#center-options').append(checkbox(wn,!!state.mapping[wn],on=>{if(on)state.mapping[wn]=[];else delete state.mapping[wn];renderMapping();}));renderMapping();}
    else if(Number.isFinite(from))invalidateFrom(from);
    if(from<=4){state.normalizationDirty=true;normalizationControls();}
    filterMode();const extreme=$('#r0-method').value!=='roi';$('#r0-roi-controls').hidden=extreme&&!$('#r0-restrict').checked;$('#r0-extreme-controls').hidden=!extreme;
    if(Number.isFinite(from)){go(Math.min(state.step,state.maxStep));notify('Shared settings updated. Recompute the affected steps for this folder.');}
  }finally{applyingShared=false;}
}
window.addEventListener('message',event=>{
  if(!embedded||event.origin!==location.origin||event.source!==parent)return;
  if(event.data.type==='sharing-policy')updateSharing(event.data);
  if(event.data.type==='shared')applyShared(event.data.settings);
  if(event.data.type==='section')go(Math.min(event.data.step,state.maxStep));
  if(event.data.type==='cnr-contrast'){
    $('#display-low').value=event.data.low;$('#display-high').value=event.data.high;
    state.cnr=event.data.records;state.cnrDirty=false;
    refreshView().catch(e=>notify(e.message,true));
  }
  if(event.data.type==='request-shared')sendParent({type:'shared',settings:sharedSnapshot()});
});
function updateExportName(){
  const name=QCLUpload.zipName($('#export-zip-name').value);
  $('#download').href=datasetURL('/api/export?'+new URLSearchParams({filename:name}));
  $('#download').download=name;
}
$('#export-zip-name').oninput=updateExportName;
updateExportName();
if(embedded){
  $('#multi-folder-option').hidden=true;$('#reproduce-import').hidden=true;
  if(datasetQuery.get('load')==='1'){
    api('/api/bootstrap').then(result=>{
      if(result.kind==='reproduced'){
        restoreReproducedState(result.state);
        sendParent({type:'ready',reproduced:true,settings:sharedSnapshot()});
      }else{acceptDiscoveredData(result.state);sendParent({type:'ready'});}
      sharedReady=true;
    }).catch(e=>notify(e.message,true));
  }
}

// Independent full-raw ROI spectroscopy; selections never modify processing state.
function clearROISpectrumResult(){
  roiSpectra.result=null;roiSpectra.sg=null;roiSpectra.sgRevision++;$('#roi-sg-status').textContent='';$('#roi-spectrum-export').disabled=true;
  $('#roi-spectrum-table').replaceChildren();drawROICharts();
}
function resetROISpectrum(){
  roiSpectra.revision++;roiSpectra.image=null;roiSpectra.rois={};roiSpectra.drag=null;
  clearROISpectrumResult();$('#roi-spectrum-panel').hidden=true;
}
function prepareROISpectrum(){
  resetROISpectrum();$('#roi-spectrum-panel').hidden=false;
  fillSelect($('#roi-spectrum-pattern'),state.discovery.availability.map(p=>p.pattern));
  updateROISpectrumBands();updateROIMarkers();loadROISpectrumImage();
}
function updateROISpectrumBands(){
  const p=state.discovery.availability.find(p=>p.pattern===$('#roi-spectrum-pattern').value);
  const select=$('#roi-spectrum-band'),centers=Object.keys(state.mapping).map(Number).filter(wn=>p?.wavenumbers.includes(wn)).sort((a,b)=>a-b);
  fillSelect(select,centers,select.value);select.disabled=!centers.length;
}
async function loadROISpectrumImage(){
  const revision=++roiSpectra.revision;roiSpectra.image=null;roiSpectra.drag=null;clearROISpectrumResult();
  $('#roi-spectrum-calculate').disabled=true;$('#roi-spectrum-status').textContent='Loading raw image…';
  const c=$('#roi-spectrum-image');c.getContext('2d').clearRect(0,0,c.width,c.height);$('#roi-spectrum-ticks').replaceChildren();drawROIOverlay(c,[]);
  if(!$('#roi-spectrum-band').value){$('#roi-spectrum-status').textContent='Select a center wavenumber available in this pattern using Assign centers and baseline bands.';return;}
  try{
    const d=await api('/api/raw-inspection',{pattern:$('#roi-spectrum-pattern').value,wavenumber:+$('#roi-spectrum-band').value,mode:'image',colorbar_zero:zeroColorbars.has('roi-raw')});
    const img=new Image();img.src='data:image/png;base64,'+d.png;await img.decode();if(revision!==roiSpectra.revision)return;
    c.width=d.width;c.height=d.height;roiSpectra.image=img;
    for(const [key,r] of Object.entries(roiSpectra.rois))if(r.x_max>d.width||r.y_max>d.height)delete roiSpectra.rois[key];
    $('#roi-spectrum-ticks').replaceChildren(...[d.vmax,(d.vmin+d.vmax)/2,d.vmin].map(v=>el('span',v.toFixed(3))));
    $('#roi-spectrum-status').textContent='Draw both regions, then calculate spectra.';drawROISpectrumImage();
  }catch(e){if(revision===roiSpectra.revision)$('#roi-spectrum-status').textContent=e.message;}
}
function drawROISpectrumImage(){
  const c=$('#roi-spectrum-image'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);
  if(roiSpectra.image)ctx.drawImage(roiSpectra.image,0,0,c.width,c.height);
  drawROIOverlay(c,Object.entries(roiSpectra.rois).map(([name,roi])=>({roi,color:name==='analyte_roi'?'#00eaff':'#39ff70'})));
  $('#roi-spectrum-coordinates').textContent=Object.entries(roiSpectra.rois).map(([n,r])=>`${n==='analyte_roi'?'Analyte':'Analyte-free'}: x [${r.x_min}, ${r.x_max}), y [${r.y_min}, ${r.y_max}) · ${(r.x_max-r.x_min)*(r.y_max-r.y_min)} pixels`).join(' | ');
  $('#roi-spectrum-calculate').disabled=!(roiSpectra.image&&roiSpectra.rois.analyte_roi&&roiSpectra.rois.background_roi);
}
function roiSpectrumPoint(e){
  const c=$('#roi-spectrum-image'),b=c.getBoundingClientRect();
  return [Math.max(0,Math.min(c.width-1,Math.floor((e.clientX-b.left)*c.width/b.width))),Math.max(0,Math.min(c.height-1,Math.floor((e.clientY-b.top)*c.height/b.height)))];
}
$('#roi-spectrum-image').onpointerdown=e=>{
  if(!roiSpectra.image||document.body.classList.contains('busy')||e.button!==0)return;
  e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);
  roiSpectra.drag={start:roiSpectrumPoint(e),name:$('#roi-spectrum-region').value};
  roiSpectra.revision++;clearROISpectrumResult();updateROISpectrumDrag(e);
};
function updateROISpectrumDrag(e){
  if(!roiSpectra.drag)return;const [x,y]=roiSpectrumPoint(e),{start:[sx,sy],name}=roiSpectra.drag;
  roiSpectra.rois[name]={x_min:Math.min(x,sx),x_max:Math.max(x,sx)+1,y_min:Math.min(y,sy),y_max:Math.max(y,sy)+1};drawROISpectrumImage();
  $('#roi-spectrum-status').textContent='Selection changed. Calculate spectra to update the result.';
}
$('#roi-spectrum-image').onpointermove=updateROISpectrumDrag;
$('#roi-spectrum-image').onpointerup=e=>{if(!roiSpectra.drag)return;updateROISpectrumDrag(e);roiSpectra.drag=null;if(!roiSpectra.rois.background_roi)$('#roi-spectrum-region').value='background_roi';};
$('#roi-spectrum-image').onpointercancel=()=>{roiSpectra.drag=null;};
$('#roi-spectrum-pattern').onchange=()=>{roiSpectra.rois={};updateROISpectrumBands();loadROISpectrumImage();};
$('#roi-spectrum-band').onchange=loadROISpectrumImage;
$('#roi-spectrum-calculate').onclick=async()=>{
  const revision=++roiSpectra.revision;clearROISpectrumResult();$('#roi-spectrum-calculate').disabled=true;$('#roi-spectrum-status').textContent='Reading spectral images…';
  try{
    const d=await api('/api/raw-roi-spectrum',{pattern:$('#roi-spectrum-pattern').value,wavenumber:+$('#roi-spectrum-band').value,...roiSpectra.rois});
    if(revision!==roiSpectra.revision)return;roiSpectra.result=d;drawROICharts();table($('#roi-spectrum-table'),d.points,['wavenumber','I','I_bg','ratio','absorbance','status']);$('#roi-spectrum-export').disabled=false;updateROISmoothing();
    $('#roi-spectrum-status').textContent=`${d.pattern} · ${d.points.length} measured bands · ${d.analyte_pixels} analyte pixels · ${d.background_pixels} background pixels · ${d.points.filter(p=>p.status!=='valid').length} invalid bands.${d.missing_wavenumbers.length?' Missing bands: '+d.missing_wavenumbers.join(', ')+' cm⁻¹.':''}`;
  }catch(e){if(revision===roiSpectra.revision)$('#roi-spectrum-status').textContent=e.message;}
  finally{if(revision===roiSpectra.revision)drawROISpectrumImage();}
};
function drawROICharts(){
  drawROIFourierDiagnostics();
  for(const [id,series,title] of [['roi-signal-chart',[['I','#147eab'],['I_bg','#17804b']],'Mean raw signal: I (blue), I_bg (green)'],['roi-absorbance-chart',roiSpectra.sg?[['absorbance','#b0b0b0'],['absorbance_filtered','#000000']]:[['absorbance','#000000']],'Absorbance: −log₁₀(I / I_bg)'+(roiSpectra.sg?' · filtered (black), raw (gray)':'')]]){
    const c=$('#'+id),ctx=c.getContext('2d'),w=c.clientWidth||600,h=280,dpr=devicePixelRatio||1;
    c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
    ctx.font='11px sans-serif';ctx.fillStyle='#435b50';ctx.fillText(title,70,18);
    const points=roiSpectra.result?.points.map((p,i)=>({...p,absorbance_filtered:roiSpectra.sg?.absorbance_filtered[i],absorbance_fourier:roiSpectra.sg?.absorbance_fourier?.[i],absorbance_sg:roiSpectra.sg?.absorbance_sg?.[i]}));if(!points?.length)continue;
    const values=points.flatMap(p=>series.map(([k])=>p[k])).filter(Number.isFinite);if(!values.length){ctx.fillText('No valid values',70,70);continue;}
    const xmin=points[0].wavenumber,xmax=points[points.length-1].wavenumber,ymin=Math.min(...values),ymax=Math.max(...values),pad=(ymax-ymin||Math.max(Math.abs(ymin)*.1,1))*.1;
    const x=v=>70+(xmax===xmin?.5:(v-xmin)/(xmax-xmin))*(w-90),y=v=>35+(ymax+pad-v)/(ymax-ymin+2*pad)*(h-80);
    for(let i=0;i<=4;i++){const v=ymin-pad+(ymax-ymin+2*pad)*i/4;ctx.fillStyle='#435b50';ctx.fillText(v.toExponential(2),2,y(v)+4);ctx.strokeStyle='#e4eae5';ctx.beginPath();ctx.moveTo(70,y(v));ctx.lineTo(w-20,y(v));ctx.stroke();}
    const markerGroups=id==='roi-absorbance-chart'?roiMarkerGroups():[],markedBands=markerGroups.flatMap(g=>[+g.center,...g.refs]).filter(wn=>wn>=xmin&&wn<=xmax);
    ctx.textAlign='center';for(let i=0;i<=(xmin===xmax?0:4);i++){const v=xmin+(xmax-xmin)*i/4;if(!markedBands.some(wn=>Math.abs(x(wn)-x(v))<32))ctx.fillText(String(Math.round(v)),x(v),h-25);}ctx.fillText('Wavenumber (cm⁻¹)',w/2,h-5);ctx.textAlign='left';
    for(const [key,color] of series){ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.5;ctx.beginPath();let connected=false;for(const p of points){if(!Number.isFinite(p[key])){connected=false;continue;}if(connected)ctx.lineTo(x(p.wavenumber),y(p[key]));else ctx.moveTo(x(p.wavenumber),y(p[key]));connected=true;}ctx.stroke();}
    if(id==='roi-absorbance-chart'){
      for(const {center,refs,color} of markerGroups){
        ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1;
        for(const wn of new Set([+center,...refs])){
          if(wn<xmin||wn>xmax)continue;
          const px=x(wn);ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(px,35);ctx.lineTo(px,h-45);ctx.stroke();ctx.setLineDash([]);
          ctx.beginPath();ctx.moveTo(px,h-45);ctx.lineTo(px,h-40);ctx.stroke();
          ctx.textAlign=px>w-40?'right':px<85?'left':'center';ctx.fillText(String(wn),px,h-25);ctx.textAlign='left';
        }
      }
    }
  }
}
$('#roi-spectrum-export').onclick=()=>{
  const d=roiSpectra.result;if(!d)return;
  const metadata={pattern:d.pattern,preview_wavenumber:d.wavenumber,analyte_pixels:d.analyte_pixels,background_pixels:d.background_pixels,fourier_enabled:!!roiSpectra.sg?.fourier_enabled,fourier_cutoff:roiSpectra.sg?.cutoff??'',fourier_mode:roiSpectra.sg?.fourier_mode??'',notch_centers:JSON.stringify(roiSpectra.sg?.notch_centers??[]),notch_width:roiSpectra.sg?.notch_width??'',sg_enabled:!!roiSpectra.sg?.sg_enabled,sg_window:roiSpectra.sg?.window??'',sg_order:roiSpectra.sg?.order??'',center_reference_mapping:JSON.stringify(state.mapping)};
  for(const name of ['analyte_roi','background_roi'])for(const [key,value] of Object.entries(d[name]))metadata[name+'_'+key]=value;
  const keys=['wavenumber','I','I_bg','ratio','absorbance','absorbance_fourier','absorbance_sg','absorbance_filtered','status',...Object.keys(metadata)];
  const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';
  const csv=[keys.map(quote).join(','),...d.points.map((p,i)=>keys.map(k=>quote(({...p,absorbance_filtered:roiSpectra.sg?.absorbance_filtered[i],absorbance_fourier:roiSpectra.sg?.absorbance_fourier?.[i],absorbance_sg:roiSpectra.sg?.absorbance_sg?.[i],...metadata})[k])).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=`${d.pattern}-roi-absorbance-spectrum.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
window.addEventListener('resize',()=>{if(!$('#roi-spectrum-panel').hidden)drawROICharts();});

$('#assign-spectrum-bands').onclick=()=>{
  $('#inline-band-slot').append($('#spectral-band-editor'));$('#inline-band-editor').hidden=false;
};
$('#finish-spectrum-bands').onclick=()=>{$('#inline-band-editor').hidden=true;drawROICharts();};
function roiMarkerGroups(){
  const palette=['#d05d00','#1765bf','#17804b','#a33b8b','#876324','#008b8b'],selected=$('#roi-marker-center').value;
  return Object.entries(state.mapping).sort((a,b)=>+a[0]-b[0]).map(([center,refs],i)=>({center,refs,color:palette[i%palette.length]})).filter(g=>selected==='all'||selected===g.center);
}
function updateROIMarkers(){
  const select=$('#roi-marker-center'),previous=select.value;
  fillSelect(select,['all',...Object.keys(state.mapping).sort((a,b)=>a-b)],previous);
  select.options[0].textContent='All centers';
  for(const o of [...select.options].slice(1))o.textContent=o.value+' cm⁻¹';
  const legend=$('#roi-marker-status');legend.replaceChildren(el('span','Vertical dashed lines: each center and its baseline references share one color. '));
  for(const {center,refs,color} of roiMarkerGroups()){const label=el('span',`${center} → ${refs.join(', ')||'no references selected'} cm⁻¹`);label.style.color=color;label.style.marginRight='16px';legend.append(label);}
  drawROICharts();
}
$('#roi-marker-center').onchange=updateROIMarkers;
async function updateROISmoothing(){
  const revision=++roiSpectra.sgRevision,sg=$('#roi-sg-enabled').checked,fourier=$('#roi-fourier-enabled').checked;
  $('#roi-sg-window').disabled=$('#roi-sg-order').disabled=!sg;const mode=$('#roi-fourier-mode').value;$('#roi-fourier-mode').disabled=!fourier;$('#roi-fourier-cutoff').disabled=!fourier||mode==='notch';$('#roi-notch-centers').disabled=$('#roi-notch-width').disabled=!fourier||mode==='lowpass';
  roiSpectra.sg=null;drawROICharts();const d=roiSpectra.result;
  if(!sg&&!fourier||!d){$('#roi-sg-status').textContent=(sg||fourier)?'Calculate a spectrum first.':'';if(d)$('#roi-spectrum-export').disabled=false;return;}
  $('#roi-spectrum-export').disabled=true;$('#roi-sg-status').textContent='Applying spectral filters…';
  try{
    const result=await api('/api/roi-spectrum-filter',{wavenumbers:d.points.map(p=>p.wavenumber),absorbance:d.points.map(p=>p.absorbance),sg_enabled:sg,fourier_enabled:fourier,fourier_mode:mode,notch_centers:$('#roi-notch-centers').value.trim().split(/[,;\s]+/).filter(Boolean).map(Number),notch_width:+$('#roi-notch-width').value,cutoff:+$('#roi-fourier-cutoff').value,window:+$('#roi-sg-window').value,order:+$('#roi-sg-order').value});
    if(revision!==roiSpectra.sgRevision||d!==roiSpectra.result)return;
    roiSpectra.sg=result;drawROICharts();
    table($('#roi-spectrum-table'),d.points.map((p,i)=>({...p,absorbance_fourier:result.absorbance_fourier?.[i],absorbance_sg:result.absorbance_sg?.[i],absorbance_filtered:result.absorbance_filtered[i]})),['wavenumber','I','I_bg','ratio','absorbance','absorbance_fourier','absorbance_sg','absorbance_filtered','status']);
    $('#roi-sg-status').textContent=[fourier?`Fourier ${result.fourier_mode}: ${result.cutoff!=null?'cutoff '+result.cutoff+' · ':''}${result.notch_centers?.length?'notches '+result.notch_centers.join(', ')+' (width '+result.notch_width+') · ':''}${result.removed_bins} FFT bins removed`:null,sg?`SG window ${result.window}, order ${result.order}`:null].filter(Boolean).join(' → ')+'. Raw absorbance is retained in gray; final output is black.';
  }catch(e){if(revision===roiSpectra.sgRevision)$('#roi-sg-status').textContent=e.message+' Showing raw absorbance.';}
  finally{if(revision===roiSpectra.sgRevision)$('#roi-spectrum-export').disabled=false;}
}
for(const id of ['roi-sg-enabled','roi-sg-window','roi-sg-order','roi-fourier-enabled','roi-fourier-cutoff','roi-fourier-mode','roi-notch-centers','roi-notch-width'])$('#'+id).onchange=()=>{
  if(roiSpectra.result)table($('#roi-spectrum-table'),roiSpectra.result.points,['wavenumber','I','I_bg','ratio','absorbance','status']);
  updateROISmoothing();
};
function drawROIFourierDiagnostics(){
  const d=roiSpectra.sg,p=roiSpectra.result?.points;$('#roi-fourier-diagnostics').hidden=!d?.fourier_enabled;
  if(!d?.fourier_enabled||!p)return;
  for(const [id,xs,series,title,xTitle] of [
    ['roi-fourier-comparison',p.map(v=>v.wavenumber),[[p.map(v=>v.absorbance),'#aaaaaa'],[d.absorbance_fourier,'#000000']],'Fourier step · before (gray), after (black), before SG','Wavenumber (cm⁻¹)'],
    ['roi-fft-chart',d.frequency,[[d.fft_before,'#aaaaaa'],[d.fft_after,'#000000'],[d.fft_removed,'#d05d00']],'Fourier amplitude · before (gray), retained (black), removed (orange)','Frequency (cycles/band)'],
    ['roi-removed-chart',p.map(v=>v.wavenumber),[[d.fourier_removed,'#d05d00']],'Component removed by Fourier: raw − Fourier output','Wavenumber (cm⁻¹)']]){
    const c=$('#'+id),ctx=c.getContext('2d'),w=c.clientWidth||600,h=280,dpr=devicePixelRatio||1;c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);
    const values=series.flatMap(([v])=>v),lo=Math.min(...values),hi=Math.max(...values),pad=(hi-lo||1)*.05,xmin=xs[0],xmax=xs.at(-1);
    const x=v=>80+(v-xmin)/(xmax-xmin)*(w-105),y=v=>35+(hi+pad-v)/(hi-lo+2*pad)*200;
    ctx.font='11px sans-serif';ctx.fillStyle='#435b50';ctx.fillText(title,80,18);
    for(let i=0;i<=4;i++){const v=lo-pad+(hi-lo+2*pad)*i/4;ctx.fillText(v.toExponential(2),2,y(v)+4);ctx.strokeStyle='#e4eae5';ctx.beginPath();ctx.moveTo(80,y(v));ctx.lineTo(w-25,y(v));ctx.stroke();}
    ctx.textAlign='center';for(let i=0;i<=4;i++){const v=xmin+(xmax-xmin)*i/4;ctx.fillText(id==='roi-fft-chart'?v.toFixed(3):String(Math.round(v)),x(v),255);}ctx.fillText(xTitle,w/2,275);ctx.textAlign='left';
    for(const [values,color] of series){ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();values.forEach((v,i)=>i?ctx.lineTo(x(xs[i]),y(v)):ctx.moveTo(x(xs[i]),y(v)));ctx.stroke();}
    if(id==='roi-fft-chart'){
      for(const [lo,hi] of d.rejected_ranges||[]){ctx.fillStyle='rgba(208,93,0,0.08)';ctx.fillRect(x(Math.max(xmin,lo)),35,Math.max(0,x(Math.min(xmax,hi))-x(Math.max(xmin,lo))),200);}
      for(const [frequency,label] of [...(d.cutoff!=null?[[d.cutoff,`Cutoff ${d.cutoff}`]]:[]),...(d.notch_centers||[]).map(v=>[v,`Notch ${v}`])]){
        const px=x(frequency);ctx.strokeStyle='#d05d00';ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(px,35);ctx.lineTo(px,235);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#d05d00';ctx.textAlign=px>w-130?'right':'left';ctx.fillText(label,px,31);ctx.textAlign='left';
      }
    }
  }
}

// Section 8 line inspection is independent of CNR regions and statistics.
function clearLineProfile(){
  lineProfile.revision++;lineProfile.start=lineProfile.end=lineProfile.result=null;
  if(state.mode==='line')state.mode=null;
  $$('.line-profile-plot').forEach(n=>n.remove());
  $('#profile-status').textContent='Select two points to inspect the same line across all stages. Position is distance from the start in pixels; values use bilinear interpolation without display clipping.';
}
$('#profile-select').onclick=()=>{clearLineProfile();state.mode='line';$('#profile-status').textContent='Click the start point on any stage image.';drawAll();};
$('#profile-clear').onclick=()=>{clearLineProfile();drawAll();};
$('#profile-direction').onchange=()=>{clearLineProfile();drawAll();};
function selectProfilePoint(view,point){
  const p={x:Math.min(view.data.width-1,Math.floor(point.x)),y:Math.min(view.data.height-1,Math.floor(point.y))};
  if(!lineProfile.start){lineProfile.start=p;$('#profile-status').textContent=`Start (${p.x}, ${p.y}). Click the end point on any stage image.`;}
  else{
    Object.assign(p,QCLLine.snapEnd(lineProfile.start,p,$('#profile-direction').value));
    if(p.x===lineProfile.start.x&&p.y===lineProfile.start.y){$('#profile-status').textContent='Choose an end point different from the start.';return;}
    lineProfile.end=p;state.mode=null;refreshLineProfile();
  }
  drawAll();
}
function drawProfileLine(view){
  const overlay=view.canvas.parentElement.querySelector('.roi-overlay');
  if(overlay)QCLLine.drawLine(overlay,lineProfile.start,lineProfile.end,view.data.width);
}
async function refreshLineProfile(){
  const revision=++lineProfile.revision,epoch=state.viewEpoch;
  if(!lineProfile.start||!lineProfile.end||state.step!==8)return;
  lineProfile.result=null;$$('.line-profile-plot').forEach(n=>n.remove());
  $('#profile-status').textContent='Calculating line profiles…';
  try{
    const result=await api('/api/line-profile',{pattern:$('#preview-pattern').value,wavenumber:+$('#preview-band').value,start:lineProfile.start,end:lineProfile.end});
    if(revision!==lineProfile.revision||epoch!==state.viewEpoch||state.step!==8)return;
    lineProfile.result=result;
    for(const view of state.canvases.filter(v=>v.roiName==='cnr'))renderLineProfile(view,result);
    $('#profile-status').textContent=`Start (${result.start.x}, ${result.start.y}) → End (${result.end.x}, ${result.end.y}) · ${result.distance.at(-1).toFixed(2)} pixels · ${result.distance.length} samples · Bilinear interpolation of actual stage values; invalid samples appear as gaps.`;
  }catch(e){if(revision===lineProfile.revision&&epoch===state.viewEpoch)$('#profile-status').textContent=e.message;}
}
function renderLineProfile(view,result){
  QCLLine.renderPlot(view.canvas.closest('.image-card'),view.kind,view.title,state.hasGold,result);
}


function restoreReproducedState(d){
  resetROISpectrum();clearLineProfile();clearBaselineInspection();zeroColorbars.clear();
  state.discovery=d.discovery;state.mapping=d.mapping;state.patterns=d.patterns;state.bands=d.bands;
  $('#center-options').replaceChildren();$('#pattern-options').replaceChildren();
  for(const wn of d.discovery.wavenumbers)$('#center-options').append(checkbox(wn,!!d.mapping[wn],on=>{if(on)state.mapping[wn]=[];else delete state.mapping[wn];renderMapping();}));
  renderMapping();
  $$('input[data-pattern]').forEach(n=>n.checked=d.patterns.includes(n.value));
  const fields={'has-gold':d.has_gold?'yes':'no','reference-pixels':d.n_pixels||100,'qc-z':d.qc_settings.robust_z_threshold??5,'qc-deviation':d.qc_settings.min_relative_deviation??.1,
    'r0-method':d.r0_selection.method,'r0-count':d.r0_selection.count??100};
  const f=d.parameters.fourier,r=d.parameters.rolling;
  Object.assign(fields,{'fourier-enabled':f.enabled,'filter-mode':f.mode,'notches':f.centers.map(p=>p.join(', ')).join(';\n'),'notch-sigma-x':f.sigma_x,'notch-sigma-y':f.sigma_y,'notch-strength':f.strength,'protect-radius':f.protect_radius,'cutoff-x':f.cutoff_x,'cutoff-y':f.cutoff_y,'fourier-pad':f.pad_pixels,'rolling-enabled':r.enabled,'rb-radius':r.radius,'rb-height':r.kernel_height,'rb-polarity':r.feature_polarity,'rb-sigma':r.smooth_sigma,'rb-pad':r.pad_pixels});
  const drift=d.drift.settings||{};
  Object.assign(fields,{'drift-enabled':!!drift.enabled,'drift-side':drift.side||'both','drift-max':drift.max_shift??20,'r0-restrict':!!d.r0_selection.search_roi,'cnr-reuse-r0':d.cnr_rois?.background_source==='analyte_free'});
  for(const [id,value] of Object.entries(fields)){const n=$('#'+id);if(n.type==='checkbox')n.checked=value;else n.value=value;}
  Object.keys(r0ReferenceBands).forEach(p=>delete r0ReferenceBands[p]);Object.assign(r0ReferenceBands,d.r0_selection.reference_bands||{});
  driftReference=drift.enabled?{reference_pattern:drift.reference_pattern,wavenumber:drift.wavenumber}:null;driftROIs=drift.enabled?d.on_rois:null;
  Object.assign(state,{version:d.version,hasGold:d.has_gold,normalizationDirty:false,qc:d.qc,r0:d.r0,cnr:d.cnr,cnrDirty:false,mode:null,time:null,
    rois:{on:d.on_roi,r0:d.r0_roi||d.r0_selection.search_roi||null,background:d.cnr_rois?.background||null,target:d.cnr_rois?.target||null}});
  const contrast=d.cnr[0];$('#display-low').value=contrast?.contrast_low_percentile??0;$('#display-high').value=contrast?.contrast_high_percentile??100;
  $('#cnr-background').disabled=$('#cnr-reuse-r0').checked;
  $('#r0-roi-controls').hidden=d.r0_selection.method!=='roi'&&!d.r0_selection.search_roi;$('#r0-extreme-controls').hidden=d.r0_selection.method==='roi';
  $('#time-player').hidden=true;const frames=d.qc.map(q=>q.frame);$('#time-start').value=Math.min(...frames);$('#time-end').value=Math.max(...frames);
  $('#discovery-summary').hidden=false;$('#discovered-bands').replaceChildren(...d.bands.map(w=>el('span',`${w} cm⁻¹`,'chip')));$('#discovery-count').textContent=`${d.discovery.files} full raw images restored from project ZIP`;
  updatePreview();filterMode();normalizationControls();updateSignalLabels();
  reproductionReport=d.report;$('#reproduction-report').hidden=!d.report;
  const labels={exact:'Exactly reproduced',within_tolerance:'Reproduced within tolerance',mismatch:'Differences detected'};
  if(d.report){
  $('#reproduction-summary').textContent=`${labels[d.report.status]} · ${d.report.summary.exact} exact checks · ${d.report.summary.within_tolerance} within tolerance · ${d.report.summary.mismatch} mismatches. Tolerances: rtol ${d.report.rtol}, atol ${d.report.atol}.`;
  $('#reproduction-environment').textContent=d.report.environment_differences.length?'Environment differs: '+d.report.environment_differences.join(', ')+'. See the report for saved and current versions.':'Python, numerical packages and processing source fingerprints match the saved environment.';
  table($('#reproduction-checks'),d.report.checks,['item','status','max_abs_error','max_rel_error','reason']);
  }
  $('#session-status').textContent='Reproduced project';unlock(d.cnr.length?10:8);go(d.cnr.length?10:8);
  notify(d.report?labels[d.report.status]+'. Saved selections were reused and numerical processing was rerun.':'Processed dataset restored.',d.report?.status==='mismatch');
}
$('#reproduce').onclick=()=>busy($('#reproduce'),async()=>{
  const file=$('#reproduce-file').files[0];if(!file)throw Error('Choose a processing project ZIP first.');
  if(file.size>1024**3)throw Error('Project ZIP exceeds the 1 GiB upload limit.');
  let active=true;showBatchProgress({status:'Uploading project',unit:'steps',completed:0,total:7});
  const poll=async()=>{try{const p=await api('/api/process-progress');if(active)showBatchProgress(p);}catch(e){}finally{if(active)setTimeout(poll,500);}};
  const request=fetch(datasetURL('/api/reproduce'),{method:'POST',headers:{'Content-Type':'application/zip'},body:file});setTimeout(poll,500);
  try{const response=await request;const d=await response.json();if(!response.ok)throw Error(d.error||'Reproduction failed.');restoreReproducedState(d);}
  finally{active=false;try{showBatchProgress(await api('/api/process-progress'));}catch(e){}}
});
$('#download-reproduction-report').onclick=()=>{
  if(!reproductionReport)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(reproductionReport,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='reproduction_report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
};
