/* Local processing controller. Filename-derived spectral roles are explicit;
 * canvas rectangles share image-pixel coordinates across processing stages.
 * Changes lock dependent steps until the corresponding API operation succeeds.
 * Heatmap contrast affects rendering only, never the scientific arrays. */
'use strict';
let previewTimer=null, previewRunning=false, previewRevision=0;
let candidatePeaks=[];
function processingChanged(){invalidateFrom(5);renderPeaks(candidatePeaks);schedulePreview();}
function schedulePreview(){
  previewRevision++;
  clearTimeout(previewTimer);
  if(state.step!==4)return;
  $('#live-status').textContent='Preview pending; the displayed result is not current.';
  $('#live-preview').style.opacity='.4';
  previewTimer=setTimeout(runPreview,450);
}
async function runPreview(){
  if(previewRunning||state.step!==4||document.body.classList.contains('busy'))return;
  const revision=previewRevision,epoch=state.viewEpoch;
  previewRunning=true;
  $('#live-status').textContent='Updating full-resolution preview...';
  try{
    const parameters=processingParameters();
    const result=await api('/api/preview',{...imageParams('reflectance'),...parameters});
    if(revision!==previewRevision||epoch!==state.viewEpoch||state.step!==4)return;
    const root=$('#live-preview');root.replaceChildren();
    [...result.images,...(result.diagnostics||[])].forEach((data,i)=>{
      if(i===3||i===6){const heading=el('h3',i===3?'Live Fourier space':'Live rolling-ball background');heading.style.gridColumn='1 / -1';root.append(heading);}
      const card=el('div',undefined,'image-card');
      const bypass=(i===1&&(!parameters.fourier.enabled||parameters.fourier.mode==='none'))||(i===2&&!parameters.rolling.enabled);
      card.append(el('h4',data.title+(bypass?' (bypassed)':'')));
      if(data.available===false){card.append(el('p',data.caption,'placeholder'));root.append(card);return;}
      const wrap=el('div',undefined,'heatmap'),img=el('img');
      img.src='data:image/png;base64,'+data.png;img.alt=data.title;
      img.style.cssText='width:calc(100% - 57px);height:auto;align-self:flex-start';
      const bar=el('div',undefined,'bar'),strip=el('div',undefined,'strip'),ticks=el('div',undefined,'ticks');
      [data.vmax,(data.vmax+data.vmin)/2,data.vmin].forEach(v=>ticks.append(el('span',fmt(v))));
      bar.append(strip,ticks);wrap.append(img,bar);card.append(wrap);if(data.caption)card.append(el('p',data.caption,'hint'));root.append(card);
    });
    root.style.opacity='1';
    $('#live-status').textContent=`Current preview: ${$('#preview-pattern').value}, ${$('#preview-band').value} cm⁻¹. Invalid output pixels: ${result.invalid_pixels}.`;
  }catch(e){if(revision===previewRevision&&epoch===state.viewEpoch&&state.step===4){$('#live-preview').replaceChildren();$('#live-status').textContent=e.message;}}
  finally{previewRunning=false;if(revision!==previewRevision&&state.step===4)previewTimer=setTimeout(runPreview,100);}
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
    b.onclick=()=>{if(!$('#fourier-enabled').checked||$('#filter-mode').value!=='notch'){notify('Enable Fourier filtering and select Gaussian notch to add peaks.');return;}addNotchPair(peak.fy,peak.fx);};
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
const stages=['raw','reflectance','fourier','rolling','absorbance','baseline'];
const stageNames=['Raw intensity','Reflectance before processing','Reflectance after Fourier','Reflectance after rolling ball','Absorbance before baseline','Absorbance after baseline'];
const titles=['Import data','Centers and baseline references','Select the on-MS region','Fourier and flat-field correction','Select cell-free region','Processing comparison and CNR'];
const state={step:1,maxStep:1,discovery:null,mapping:{},patterns:[],bands:[],qc:[],rois:{on:null,r0:null,background:null,target:null},cnr:[],cnrDirty:false,r0:[],canvases:[],mode:null,version:0,viewEpoch:0,time:null,timer:null};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function notify(text,error=false){const n=$('#notice');n.hidden=false;n.textContent=text;n.className=error?'error':''}
async function api(path,payload){const r=await fetch(path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await r.json();if(!r.ok)throw Error(data.error||'Operation failed');return data}
async function busy(button,fn){if(document.body.classList.contains('busy'))return;document.body.classList.add('busy');const old=button.textContent;button.textContent='Processing…';notify('Processing locally. Large images or rolling-ball radii may take longer.');try{await fn()}catch(e){notify(e.message,true)}finally{document.body.classList.remove('busy');button.textContent=old}}
function unlock(n){state.maxStep=n;renderNav()}
function renderNav(){const nav=$('#navigation');nav.replaceChildren();titles.forEach((t,i)=>{const b=el('button',undefined,state.step===i+1?'active':'');b.append(el('i',String(i+1)));const label=el('span',t);b.append(label);b.disabled=i+1>state.maxStep;b.onclick=()=>go(i+1);nav.append(b)})}
function invalidateFrom(n){state.maxStep=Math.min(state.maxStep,n-1);state.cnr=[];state.rois.background=state.rois.target=null;clearInterval(state.timer);state.timer=null;$('#time-player').hidden=true;renderNav()}
function go(step){if(step>state.maxStep)return;state.step=step;$$('section[data-step]').forEach(n=>n.hidden=+n.dataset.step!==step);$('#page-title').textContent=titles[step-1];$('#preview-controls').hidden=step<3;renderNav();refreshView().catch(e=>notify(e.message,true));window.scrollTo({top:0,behavior:'smooth'})}
function fillSelect(node,values,preferred){node.replaceChildren();for(const v of values){const o=el('option',String(v));o.value=v;node.append(o)}if(values.map(String).includes(String(preferred)))node.value=preferred}
function updatePreview(){fillSelect($('#preview-pattern'),state.patterns,$('#preview-pattern').value);fillSelect($('#preview-band'),state.bands,Object.keys(state.mapping)[0]);}
function checkbox(value,checked,callback){const label=el('label',undefined,'chip');const input=el('input');input.type='checkbox';input.value=value;input.checked=checked;input.onchange=()=>callback(input.checked);label.append(input,document.createTextNode(String(value)));return label}
function involved(){return [...new Set([...Object.keys(state.mapping).map(Number),...Object.values(state.mapping).flat()])].sort((a,b)=>a-b)}
function renderMapping(){const root=$('#reference-mapping');root.replaceChildren();for(const center of Object.keys(state.mapping).map(Number).sort((a,b)=>a-b)){const row=el('div',undefined,'mapping-row');row.append(el('h3',`${center} cm⁻¹ reference`));const chips=el('div',undefined,'chips');for(const wn of state.discovery.wavenumbers){if(wn===center)continue;chips.append(checkbox(wn,state.mapping[center].includes(wn),checked=>{state.mapping[center]=checked?[...state.mapping[center],wn].sort((a,b)=>a-b):state.mapping[center].filter(v=>v!==wn);mappingChanged()}))}row.append(chips);root.append(row)}mappingChanged()}
function mappingChanged(){invalidateFrom(3);const wns=involved();$('#involved-bands').textContent=wns.length?`All involved wavenumbers: ${wns.join(' · ')} cm⁻¹`:'Select centers and reference bands.';renderPatterns()}
function renderPatterns(){const root=$('#pattern-options');const previous=new Set($$('input[data-pattern]:checked').map(n=>n.value));const initial=!root.children.length;root.replaceChildren();const required=involved();for(const [index,p] of state.discovery.availability.entries()){const missing=required.filter(w=>!p.wavenumbers.includes(w));const label=el('label',undefined,'pattern');const input=el('input');input.type='checkbox';input.dataset.pattern='true';input.value=p.pattern;input.disabled=missing.length>0;input.checked=!missing.length&&(previous.has(p.pattern)||(initial&&index===0));input.onchange=()=>invalidateFrom(3);label.append(input,document.createTextNode(p.pattern),el('small',missing.length?` ${missing.join(', ')}`:`${p.wavenumbers.length} wavenumber`));root.append(label)}}
$('#discover').onclick=()=>busy($('#discover'),async()=>{const d=await api('/api/discover',{path:$('#input-path').value});state.discovery=d;state.mapping={};state.patterns=[];state.bands=[];state.version=d.version;$('#center-options').replaceChildren();$('#pattern-options').replaceChildren();$('#reference-mapping').replaceChildren();for(const wn of d.wavenumbers)$('#center-options').append(checkbox(wn,false,on=>{if(on)state.mapping[wn]=[];else delete state.mapping[wn];renderMapping()}));$('#discovered-bands').replaceChildren(...d.wavenumbers.map(w=>el('span',`${w} cm⁻¹`,'chip')));$('#discovery-count').textContent=`${d.files} image · ${d.availability.length}  patterns`;$('#discovery-summary').hidden=false;renderPatterns();unlock(2);localStorage.setItem('qclProcessingPath',$('#input-path').value);$('#session-status').textContent=` ${d.wavenumbers.length} wavenumber`;notify('Wavenumbers were detected from filenames. Select centers and their baseline references.');go(2)});
$('#select-complete').onclick=()=>{$$('input[data-pattern]').forEach(n=>n.checked=!n.disabled);invalidateFrom(3)};
$('#configure').onclick=()=>busy($('#configure'),async()=>{const d=await api('/api/configure',{mapping:state.mapping,patterns:$$('input[data-pattern]:checked').map(n=>n.value),n_pixels:+$('#reference-pixels').value,robust_z_threshold:+$('#qc-z').value,relative_threshold:+$('#qc-deviation').value});Object.assign(state,{mapping:d.mapping,patterns:d.patterns,bands:d.bands,qc:d.qc,version:d.version,cnr:[],cnrDirty:false,r0:[]});state.rois={on:null,r0:null,background:null,target:null};state.cnrDirty=false;updatePreview();unlock(3);const frames=d.qc.map(r=>r.frame);$('#time-start').value=Math.min(...frames);$('#time-end').value=Math.max(...frames);$('#session-status').textContent=`${d.patterns.length} patterns · ${d.bands.length} wavenumber`;notify('Configuration confirmed. All involved bands were normalized independently.');go(3)});
function coords(name){const root=$(`#${name==='on'?'on':'r0'}-coordinates`);root.replaceChildren();const roi=state.rois[name];for(const key of ['x_min','x_max','y_min','y_max']){const label=el('label',key.replace('_',' ')),input=el('input');input.type='number';input.min=0;input.value=roi?roi[key]:'';input.oninput=()=>{if(!state.rois[name])state.rois[name]={x_min:0,x_max:0,y_min:0,y_max:0};state.rois[name][key]=+input.value;invalidateFrom(name==='on'?4:6);drawAll()};label.append(input);root.append(label)}}
const r0ReferenceBands={};
function renderR0References(){
  fillSelect($('#r0-all-band'),state.bands,$('#r0-all-band').value||Object.keys(state.mapping)[0]);
  const root=$('#r0-reference-bands');root.replaceChildren();
  for(const pattern of state.patterns){
    if(!state.bands.includes(r0ReferenceBands[pattern]))r0ReferenceBands[pattern]=+Object.keys(state.mapping)[0];
    const label=el('label',`${pattern} · reference wavenumber`),select=el('select');
    fillSelect(select,state.bands,r0ReferenceBands[pattern]);
    select.onchange=()=>{r0ReferenceBands[pattern]=+select.value;invalidateFrom(6);refreshView().catch(e=>notify(e.message,true));};
    label.append(select);root.append(label);
  }
}
$('#r0-apply-all').onclick=()=>{const wn=+$('#r0-all-band').value;for(const pattern of state.patterns)r0ReferenceBands[pattern]=wn;invalidateFrom(6);refreshView().catch(e=>notify(e.message,true));};
function imageParams(kind){return {pattern:$('#preview-pattern').value,wavenumber:$('#preview-band').value,kind,low:$('#display-low').value,high:$('#display-high').value,version:state.version}}
async function heatmap(root,kind,title,roiName=null,epoch=state.viewEpoch){const card=el('div',undefined,'image-card');card.append(el('h4',title));root.append(card);const params=imageParams(kind);if(kind==='full_raw')params.brightest='true';if(kind==='spectrum'){params.window=String($('#inspection-window').checked);params.min_frequency=$('#candidate-min').value;}if(roiName==='r0'&&$('#r0-method').value!=='roi'){params.r0_method=$('#r0-method').value;params.r0_count=$('#r0-count').value;params.r0_reference_band=r0ReferenceBands[$('#preview-pattern').value];}const data=await api('/api/image?'+new URLSearchParams(params));if(epoch!==state.viewEpoch)return;if(!data.available){card.append(el('div',kind==='baseline'?'Reference-only band: no baseline center configured':'Available after processing','placeholder'));return}const wrap=el('div',undefined,'heatmap'),canvas=el('canvas');canvas.width=data.width;canvas.height=data.height;wrap.append(canvas);const bar=el('div',undefined,'bar'),strip=el('div',undefined,'strip'),ticks=el('div',undefined,'ticks');[data.vmax,(data.vmax+data.vmin)/2,data.vmin].forEach(v=>ticks.append(el('span',Number(v.toPrecision(4)).toString())));bar.append(strip,ticks);wrap.append(bar);card.append(wrap);if(kind==='spectrum')card.append(el('div','fx: −0.5 → +0.5; fy: −0.5 (top) → +0.5 (bottom)','axis-hint'));const image=new Image;image.src='data:image/png;base64,'+data.png;await image.decode();if(epoch!==state.viewEpoch)return;const view={canvas,image,data,kind,roiName,titleNode:card.querySelector('h4'),title};state.canvases.push(view);bindCanvas(view);draw(view);if(kind==='spectrum')renderPeaks(data.peaks||[]);if(roiName==='r0'&&data.cell_free_pixels)$('#r0-preview-status').textContent=`${data.cell_free_pixels.length} ${$('#r0-method').value} pixels from ${data.reference_wavenumber} cm⁻¹ · preview R₀ ${fmt(data.cell_free_r0)}`}
function draw(v){const ctx=v.canvas.getContext('2d');ctx.clearRect(0,0,v.canvas.width,v.canvas.height);ctx.drawImage(v.image,0,0,v.canvas.width,v.canvas.height);const pairs=v.roiName==='cnr'?[['background','#00eaff'],['target','#7dff00']]:v.roiName==='r0'&&$('#r0-method').value!=='roi'?[]:v.roiName?[[v.roiName,'#00eaff']]:[];for(const [name,color] of pairs){const r=state.rois[name];if(!r)continue;ctx.strokeStyle=color;ctx.lineWidth=Math.max(v.data.width/400,.6);ctx.strokeRect(r.x_min,r.y_min,r.x_max-r.x_min,r.y_max-r.y_min)}if(v.data.cell_free_pixels){ctx.strokeStyle='#00eaff';ctx.lineWidth=Math.max(.35,v.data.width/1200);const arm=Math.max(1.25,v.data.width/320);for(const [y,x] of v.data.cell_free_pixels){ctx.beginPath();ctx.moveTo(x+.5-arm,y+.5);ctx.lineTo(x+.5+arm,y+.5);ctx.moveTo(x+.5,y+.5-arm);ctx.lineTo(x+.5,y+.5+arm);ctx.stroke();}}if(v.kind==='spectrum'){ctx.fillStyle='#00eaff';ctx.font=`${Math.max(8,v.data.width/35)}px sans-serif`;for(const peak of v.data.peaks||[])ctx.fillText(String(peak.rank),peak.ix,peak.iy);}if(v.roiName==='cnr'){const row=state.cnr.find(r=>r.pattern===$('#preview-pattern').value&&r.wavenumber===+$('#preview-band').value&&r.stage===v.kind);v.titleNode.textContent=v.title+(row?` · CNR ${row.cnr===null?'':row.cnr.toFixed(3)}`:'')}}
function drawAll(){state.canvases.forEach(draw)}
function bindCanvas(v){let start=null;const point=e=>{const b=v.canvas.getBoundingClientRect();return{x:Math.max(0,Math.min(v.data.width,(e.clientX-b.left)*v.data.width/b.width)),y:Math.max(0,Math.min(v.data.height,(e.clientY-b.top)*v.data.height/b.height))}};v.canvas.onpointerdown=e=>{if(document.body.classList.contains('busy'))return;if(v.kind==='spectrum'){if(!$('#fourier-enabled').checked||$('#filter-mode').value!=='notch')return;const p=point(e);const fx=v.data.fx[Math.min(v.data.width-1,Math.floor(p.x))],fy=v.data.fy[Math.min(v.data.height-1,Math.floor(p.y))];const peak=(v.data.peaks||[]).find(q=>Math.hypot(q.ix-p.x,q.iy-p.y)<8);addNotchPair(peak?peak.fy:fy,peak?peak.fx:fx);return}if(!v.roiName||(v.roiName==='r0'&&$('#r0-method').value!=='roi'))return;if(v.roiName==='cnr'&&!state.mode)return;start=point(e);v.canvas.setPointerCapture(e.pointerId)};const update=e=>{if(!start)return;const p=point(e),name=v.roiName==='cnr'?state.mode:v.roiName;state.rois[name]={x_min:Math.floor(Math.min(start.x,p.x)),x_max:Math.ceil(Math.max(start.x,p.x)),y_min:Math.floor(Math.min(start.y,p.y)),y_max:Math.ceil(Math.max(start.y,p.y))};if(name==='on'||name==='r0'){invalidateFrom(name==='on'?4:6);coords(name)}else{state.cnr=[];if(name==='background')state.rois.target=null;$('#cnr-table').replaceChildren();chart($('#cnr-chart'),[])}drawAll()};v.canvas.onpointermove=update;v.canvas.onpointerup=e=>{update(e);start=null};v.canvas.onpointercancel=()=>start=null}
async function refreshView(){clearInterval(state.timer);state.timer=null;if(state.step<3)return;const epoch=++state.viewEpoch;state.canvases=[];if(state.step===3){$('#crop-preview').replaceChildren();coords('on');await heatmap($('#crop-preview'),$('#raw-view').value,'Full image','on',epoch);table($('#qc-table'),state.qc,['pattern','wavenumber','i_goldref','reference_valid','frame_valid']);chart($('#qc-chart'),state.bands.map(wn=>({name:String(wn),values:state.qc.filter(r=>r.wavenumber===wn).map(r=>r.i_goldref)})))}if(state.step===4){$('#spectrum-preview').replaceChildren();await heatmap($('#spectrum-preview'),'spectrum','Inspect spectrum · click to add notches',null,epoch);schedulePreview()}if(state.step===5){$('#r0-preview').replaceChildren();$('#r0-preview-status').textContent='';$('#processing-preview').replaceChildren();coords('r0');renderR0References();await heatmap($('#r0-preview'),'rolling','Reflectance after rolling ball','r0',epoch);await Promise.all(['reflectance','fourier','rolling'].map((kind,i)=>heatmap($('#processing-preview'),kind,['Before processing','Fourier after','Rolling ball after'][i],null,epoch)))}if(state.step===6){updateTimeBands();$('#six-stages').replaceChildren();await Promise.all(stages.map((kind,i)=>heatmap($('#six-stages'),kind,stageNames[i],'cnr',epoch)));showCNR();table($('#r0-table'),state.r0,['pattern','wavenumber','method','reference_wavenumber','pixel_count','r0','reference_mean_absorbance'])}}
$('#confirm-crop').onclick=()=>busy($('#confirm-crop'),async()=>{if(!state.rois.on)throw Error('Please first Select the on-MS region.');const d=await api('/api/crop',{roi:state.rois.on});state.version=d.version;state.rois.r0=state.rois.background=state.rois.target=null;unlock(4);notify('Shared on-MS crop confirmed.');go(4)});
function filterMode(){const mode=$('#filter-mode').value;$$('[data-filter]').forEach(n=>n.hidden=n.dataset.filter!==mode)}
$('#filter-mode').onchange=()=>{filterMode();processingChanged()};
$('#clear-notches').onclick=()=>{$('#notches').value='';processingChanged()};
function notchCenters(){const text=$('#notches').value.trim();if(!text)return[];return text.split(/[;\n]+/).filter(s=>s.trim()).map(s=>{const pair=s.split(',').map(v=>Number(v.trim()));if(pair.length!==2||pair.some(v=>!Number.isFinite(v)))throw Error('Use fy, fx pairs separated by semicolons.');return pair})}
$('#process').onclick=()=>busy($('#process'),async()=>{const {fourier,rolling}=processingParameters();const d=await api('/api/process',{fourier,rolling});state.version=d.version;state.rois.r0=state.rois.background=state.rois.target=null;state.r0=[];unlock(5);notify(`Completed  ${d.summary.length} images processed with the selected settings.`);go(5)});
function r0Mode(){const extreme=$('#r0-method').value!=='roi';$('#r0-roi-controls').hidden=extreme;$('#r0-extreme-controls').hidden=!extreme;invalidateFrom(6);if(state.step===5)refreshView().catch(e=>notify(e.message,true))}
$('#r0-method').onchange=r0Mode;
$('#r0-count').onchange=()=>{invalidateFrom(6);if(state.step===5)refreshView().catch(e=>notify(e.message,true))};
$('#calculate').onclick=()=>busy($('#calculate'),async()=>{const method=$('#r0-method').value;if(method==='roi'&&!state.rois.r0)throw Error('Select a cell-free ROI first.');const payload={method};if(method==='roi')payload.roi=state.rois.r0;else{payload.count=+$('#r0-count').value;payload.reference_bands=Object.fromEntries(state.patterns.map(p=>[p,r0ReferenceBands[p]]));}const d=await api('/api/calculate',payload);state.version=d.version;state.r0=d.r0;state.cnr=[];state.rois.background=state.rois.target=null;state.mode=null;state.cnrDirty=false;unlock(6);notify('Absorbance and configured baseline corrections are complete.');go(6)});
$('#cnr-background').onclick=()=>{state.cnrDirty=true;state.mode='background';state.rois.background=state.rois.target=null;state.cnr=[];showCNR();$('#cnr-instruction').textContent='Select background: drag a rectangle on any stage.';drawAll()};
$('#cnr-target').onclick=()=>{if(!state.rois.background){notify('Select the background first.',true);return}state.cnrDirty=true;state.mode='target';state.rois.target=null;state.cnr=[];showCNR();$('#cnr-instruction').textContent='Select target ROI: it must not overlap the background.';drawAll()};
$('#calculate-cnr').onclick=()=>busy($('#calculate-cnr'),async()=>{if(!state.rois.background||!state.rois.target)throw Error('Select background, then target ROI.');const d=await api('/api/cnr',{background:state.rois.background,target:state.rois.target});state.cnr=d.records;state.cnrDirty=false;state.mode=null;drawAll();showCNR();notify('The same ROIs were used to calculate CNR for all patterns, bands, and stages.')});
function fmt(v){if(v===null||v===undefined)return'—';if(typeof v==='number')return Number(v.toPrecision(6)).toString();return String(v)}
function table(root,rows,keys){root.replaceChildren();if(!rows.length){root.append(el('p','No results yet','hint'));return}const t=el('table'),head=el('thead'),tr=el('tr');keys.forEach(k=>tr.append(el('th',k)));head.append(tr);const body=el('tbody');rows.forEach(r=>{const row=el('tr');keys.forEach(k=>row.append(el('td',fmt(r[k]))));body.append(row)});t.append(head,body);root.append(t)}
function chart(canvas,series,labels=[]){const ctx=canvas.getContext('2d'),ratio=devicePixelRatio||1,w=canvas.clientWidth||600,h=240;canvas.width=w*ratio;canvas.height=h*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);const finite=series.flatMap(s=>s.values).filter(v=>v!==null&&Number.isFinite(v));if(!finite.length){ctx.fillStyle='#829389';ctx.fillText('The trend appears after calculation',20,35);return}const low=Math.min(...finite),high=Math.max(...finite),span=high-low||1,p={l:55,r:20,t:30,b:48},colors=['#157e69','#b6803b','#6473a1','#995477'];ctx.font='10px sans-serif';for(let i=0;i<4;i++){const y=p.t+(h-p.t-p.b)*i/3;ctx.strokeStyle='#e4eae5';ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(w-p.r,y);ctx.stroke();ctx.fillStyle='#708477';ctx.fillText(fmt(high-span*i/3).slice(0,7),4,y+3)}series.forEach((s,index)=>{const color=colors[index%colors.length],n=s.values.length;ctx.strokeStyle=color;ctx.lineWidth=1.8;ctx.beginPath();let connect=false;s.values.forEach((v,i)=>{if(v===null||!Number.isFinite(v)){connect=false;return}const x=p.l+(w-p.l-p.r)*i/Math.max(1,n-1),y=p.t+(h-p.t-p.b)*(high-v)/span;if(connect)ctx.lineTo(x,y);else ctx.moveTo(x,y);connect=true});ctx.stroke();ctx.fillStyle=color;ctx.fillText(s.name,p.l+index*110,15)});labels.forEach((s,i)=>{ctx.fillStyle='#708477';ctx.fillText(s,p.l+(w-p.l-p.r)*i/Math.max(1,labels.length-1)-15,h-15)})}
function showCNR(){const rows=state.cnr.filter(r=>r.pattern===$('#preview-pattern').value&&r.wavenumber===+$('#preview-band').value);table($('#cnr-table'),rows,['stage','cnr','target_mean','background_mean','background_std','target_pixels','background_pixels','status']);chart($('#cnr-chart'),rows.length?[{name:'CNR',values:rows.map(r=>r.cnr)}]:[],['Raw','R before','Fourier','Rolling','A before','A baseline'])}
function updateTimeBands(){
  const bands=$('#time-kind').value==='baseline'?Object.keys(state.mapping).map(Number).sort((a,b)=>a-b):state.bands;
  fillSelect($('#time-band'),bands,$('#time-band').value||$('#preview-band').value);
}
async function buildTime(){
  return busy($('#build-time'),async()=>{
    $('#time-band').disabled=true;$('#time-kind').disabled=true;
    try{
const frameIndex=+$('#time-slider').value;$('#time-player').hidden=true;clearInterval(state.timer);state.timer=null;state.time=await api('/api/timelapse',{wavenumber:+$('#time-band').value,kind:$('#time-kind').value,start:+$('#time-start').value,end:+$('#time-end').value,skip_invalid:$('#time-skip').checked,low:+$('#time-low').value,high:+$('#time-high').value});$('#time-settings').textContent=`${state.time.wavenumber} cm⁻¹ · ${state.time.kind==='baseline'?'Absorbance after baseline':'Absorbance before baseline'} · Contrast: ${state.time.low}–${state.time.high} percentiles`;$('#time-ticks').replaceChildren(...[state.time.vmax,(state.time.vmax+state.time.vmin)/2,state.time.vmin].map(v=>el('span',fmt(v))));$('#time-player').hidden=false;$('#time-slider').max=state.time.frames.length-1;$('#time-slider').value=Math.min(frameIndex,state.time.frames.length-1);renderFrame();notify(`Built ${state.time.frames.length} frames. All frames use the same color scale.`)
    }finally{$('#time-band').disabled=false;$('#time-kind').disabled=false;}
  });
}
$('#build-time').onclick=buildTime;
$('#time-band').onchange=buildTime;
$('#time-kind').onchange=()=>{updateTimeBands();buildTime();};
function renderFrame(){const i=+$('#time-slider').value,f=state.time.frames[i];$('#time-image').src='data:image/png;base64,'+f.png;$('#time-label').textContent=`${state.time.wavenumber} cm⁻¹ · ${f.pattern} · ${i+1}/${state.time.frames.length} · elapsed  ${f.elapsed_seconds.toFixed(1)} s · ${new Date(f.timestamp*1000).toLocaleString()} · dt median  ${state.time.median_interval_seconds.toFixed(1)} s`}
$('#time-slider').oninput=()=>{if(state.time)renderFrame()};$('#time-play').onclick=()=>{if(state.timer){clearInterval(state.timer);state.timer=null;return}if(!state.time)return;state.timer=setInterval(()=>{$('#time-slider').value=(+$('#time-slider').value+1)%state.time.frames.length;renderFrame()},1000/Math.max(1,+$('#time-fps').value))};
for(const id of ['preview-pattern','preview-band','raw-view','inspection-window'])$(`#${id}`).onchange=()=>refreshView().catch(e=>notify(e.message,true));
$('#refresh-view').onclick=()=>refreshView().catch(e=>notify(e.message,true));
$$('[data-go]').forEach(b=>b.onclick=()=>go(+b.dataset.go));
$$('section[data-step="4"] input, section[data-step="4"] textarea, #rb-polarity').forEach(n=>{if(!['inspection-window','candidate-min'].includes(n.id))n.addEventListener('input',processingChanged)});$('#candidate-min').oninput=()=>refreshView().catch(e=>notify(e.message,true));
for(const id of ['reference-pixels','qc-z','qc-deviation'])$(`#${id}`).onchange=()=>invalidateFrom(3);
$('#input-path').value=localStorage.getItem('qclProcessingPath')||'';
renderNav();filterMode();r0Mode();

// Do not export an older CNR measurement after its visible ROIs are edited.
$('#download').onclick=e=>{if(state.cnrDirty||((state.rois.background||state.rois.target)&&!state.cnr.length)){e.preventDefault();notify('The ROI changed. Recalculate CNR before exporting.',true)}};

function processingParameters(){const mode=$('#filter-mode').value;const fourier={enabled:$('#fourier-enabled').checked,mode,centers:$('#fourier-enabled').checked&&mode==='notch'?notchCenters():[],sigma:+$('#notch-sigma').value,strength:+$('#notch-strength').value,protect_radius:+$('#protect-radius').value,cutoff_x:+$('#cutoff-x').value,cutoff_y:+$('#cutoff-y').value,pad_pixels:+$('#fourier-pad').value,preserve_mean:true};const rolling={enabled:$('#rolling-enabled').checked,radius:+$('#rb-radius').value,kernel_height:+$('#rb-height').value,feature_polarity:$('#rb-polarity').value,smooth_sigma:+$('#rb-sigma').value,pad_pixels:+$('#rb-pad').value,min_background:1e-6,reference_level:null};return {fourier,rolling};}
