/* Local processing controller. Filename-derived spectral roles are explicit;
 * canvas rectangles share image-pixel coordinates across processing stages.
 * Changes lock dependent steps until the corresponding API operation succeeds.
 * Heatmap contrast affects rendering only, never the scientific arrays. */
'use strict';
let previewTimer=null, previewRunning=false, previewRevision=0;
let candidatePeaks=[];
function processingChanged(){invalidateFrom(5);renderPeaks(candidatePeaks);for(const v of state.canvases.filter(v=>v.kind==='spectrum'))addSpectrumLabels(v.canvas.closest('.heatmap'),v.data);schedulePreview();}
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
      if(i===3||data.title==='Estimated rolling-ball background'){const heading=el('h3',i===3?'Live Fourier space and removed signal':'Live rolling-ball background');heading.style.gridColumn='1 / -1';root.append(heading);}
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
let rawRevision=0, rawImage=null, rawSpectrum=null, rawRunning=false, rawPending=false, rawNeedsImage=false;
const stages=['raw','reflectance','fourier','rolling','absorbance','baseline'];
const stageNames=['Raw intensity','Reflectance before processing','Reflectance after Fourier','Reflectance after rolling ball','Absorbance before baseline','Absorbance after baseline'];
const titles=['Import data','Centers and baseline references','Select the on-MS region','Fourier and flat-field correction','Calculate absorbance','Baseline correction','Comparison, CNR'];
const state={step:1,maxStep:1,discovery:null,mapping:{},patterns:[],bands:[],qc:[],rois:{on:null,r0:null,background:null,target:null},cnr:[],cnrDirty:false,r0:[],canvases:[],mode:null,version:0,viewEpoch:0,time:null,timer:null};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function notify(text,error=false){const n=$('#notice');n.hidden=false;n.textContent=text;n.className=error?'error':''}
async function api(path,payload){const r=await fetch(path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await r.json();if(!r.ok)throw Error(data.error||'Operation failed');return data}
async function busy(button,fn){if(document.body.classList.contains('busy'))return;document.body.classList.add('busy');const old=button.textContent;button.textContent='Processing…';notify('Processing locally. Large images or rolling-ball radii may take longer.');try{await fn()}catch(e){notify(e.message,true)}finally{document.body.classList.remove('busy');button.textContent=old}}
function unlock(n){state.maxStep=n;renderNav()}
function renderNav(){$$('[data-go]').forEach(b=>b.disabled=+b.dataset.go>state.maxStep);const nav=$('#navigation');nav.replaceChildren();titles.forEach((t,i)=>{const b=el('button',undefined,state.step===i+1?'active':'');b.append(el('i',String(i+1)));const label=el('span',t);b.append(label);b.disabled=i+1>state.maxStep;b.onclick=()=>go(i+1);nav.append(b)})}
function invalidateFrom(n){clearBaselineInspection();$('#baseline-preview').replaceChildren();if(n<=6){$('#processing-preview').querySelectorAll('[data-absorbance-preview]').forEach(n=>n.remove());}state.maxStep=Math.min(state.maxStep,n-1);state.cnr=[];state.rois.background=state.rois.target=null;clearInterval(state.timer);state.timer=null;$('#time-player').hidden=true;renderNav()}
function go(step){if(step>state.maxStep)return;state.step=step;$$('section[data-step]').forEach(n=>n.hidden=+n.dataset.step!==step);$('#page-title').textContent=titles[step-1];$('#preview-controls').hidden=step<3;renderNav();refreshView().catch(e=>notify(e.message,true));window.scrollTo({top:0,behavior:'smooth'})}
function fillSelect(node,values,preferred){node.replaceChildren();for(const v of values){const o=el('option',String(v));o.value=v;node.append(o)}if(values.map(String).includes(String(preferred)))node.value=preferred}
function updatePreview(){fillSelect($('#preview-pattern'),state.patterns,$('#preview-pattern').value);fillSelect($('#preview-band'),state.bands,Object.keys(state.mapping)[0]);}
function checkbox(value,checked,callback){const label=el('label',undefined,'chip');const input=el('input');input.type='checkbox';input.value=value;input.checked=checked;input.onchange=()=>callback(input.checked);label.append(input,document.createTextNode(String(value)));return label}
function involved(){return [...new Set([...Object.keys(state.mapping).map(Number),...Object.values(state.mapping).flat()])].sort((a,b)=>a-b)}
function renderMapping(){const root=$('#reference-mapping');root.replaceChildren();for(const center of Object.keys(state.mapping).map(Number).sort((a,b)=>a-b)){const row=el('div',undefined,'mapping-row');row.append(el('h3',`${center} cm⁻¹ reference`));const chips=el('div',undefined,'chips');for(const wn of state.discovery.wavenumbers){if(wn===center)continue;chips.append(checkbox(wn,state.mapping[center].includes(wn),checked=>{state.mapping[center]=checked?[...state.mapping[center],wn].sort((a,b)=>a-b):state.mapping[center].filter(v=>v!==wn);mappingChanged()}))}row.append(chips);root.append(row)}mappingChanged()}
function mappingChanged(){invalidateFrom(3);const wns=involved();$('#involved-bands').textContent=wns.length?`All involved wavenumbers: ${wns.join(' · ')} cm⁻¹`:'Select centers and reference bands.';renderPatterns()}
function renderPatterns(){const root=$('#pattern-options');const previous=new Set($$('input[data-pattern]:checked').map(n=>n.value));const initial=!root.children.length;root.replaceChildren();const required=involved();for(const [index,p] of state.discovery.availability.entries()){const missing=required.filter(w=>!p.wavenumbers.includes(w));const label=el('label',undefined,'pattern');const input=el('input');input.type='checkbox';input.dataset.pattern='true';input.value=p.pattern;input.disabled=missing.length>0;input.checked=!missing.length&&(previous.has(p.pattern)||(initial&&index===0));input.onchange=()=>invalidateFrom(3);label.append(input,document.createTextNode(p.pattern),el('small',missing.length?` ${missing.join(', ')}`:`${p.wavenumbers.length} wavenumber`));root.append(label)}}
$('#discover').onclick=()=>busy($('#discover'),async()=>{resetRawInspector();const d=await api('/api/discover',{path:$('#input-path').value});state.discovery=d;state.mapping={};state.patterns=[];state.bands=[];state.version=d.version;$('#center-options').replaceChildren();$('#pattern-options').replaceChildren();$('#reference-mapping').replaceChildren();for(const wn of d.wavenumbers)$('#center-options').append(checkbox(wn,false,on=>{if(on)state.mapping[wn]=[];else delete state.mapping[wn];renderMapping()}));$('#discovered-bands').replaceChildren(...d.wavenumbers.map(w=>el('span',`${w} cm⁻¹`,'chip')));$('#discovery-count').textContent=`${d.files} image · ${d.availability.length}  patterns`;$('#discovery-summary').hidden=false;renderPatterns();unlock(2);localStorage.setItem('qclProcessingPath',$('#input-path').value);$('#session-status').textContent=` ${d.wavenumbers.length} wavenumber`;notify('Wavenumbers detected. Inspect a raw pixel spectrum below, then continue to spectral configuration.');go(1);prepareRawInspector()});
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
$('#configure').onclick=()=>busy($('#configure'),async()=>{const d=await api('/api/configure',{mapping:state.mapping,patterns:$$('input[data-pattern]:checked').map(n=>n.value),n_pixels:+$('#reference-pixels').value,robust_z_threshold:+$('#qc-z').value,relative_threshold:+$('#qc-deviation').value});Object.assign(state,{mapping:d.mapping,patterns:d.patterns,bands:d.bands,qc:d.qc,version:d.version,cnr:[],cnrDirty:false,r0:[]});state.rois={on:null,r0:null,background:null,target:null};driftReference=null;driftROIs=null;state.cnrDirty=false;updatePreview();unlock(3);const frames=d.qc.map(r=>r.frame);$('#time-start').value=Math.min(...frames);$('#time-end').value=Math.max(...frames);$('#session-status').textContent=`${d.patterns.length} patterns · ${d.bands.length} wavenumber`;notify('Configuration confirmed. All involved bands were normalized independently.');go(3)});
let driftReference=null, driftROIs=null;
function captureDriftReference(){driftReference={reference_pattern:$('#preview-pattern').value,wavenumber:+$('#preview-band').value};driftROIs=null;$('#drift-reference').textContent=`Reference: ${driftReference.reference_pattern} · ${driftReference.wavenumber} cm⁻¹`;$('#drift-table').replaceChildren();}
function cropPayload(){if(!state.rois.on)throw Error('Draw an on-MS ROI first.');if(!driftReference)captureDriftReference();return {roi:state.rois.on,drift:{enabled:$('#drift-enabled').checked,...driftReference,side:$('#drift-side').value,max_shift:+$('#drift-max').value}};}
$('#preview-drift').onclick=()=>busy($('#preview-drift'),async()=>{const d=await api('/api/crop-preview',cropPayload());driftROIs=d.rois;table($('#drift-table'),d.records,['pattern','dx','dy','left_gold_x','right_gold_x']);drawAll();notify('Crop preview ready. Switch preview patterns to inspect adjusted positions.');});
for(const id of ['drift-enabled','drift-side','drift-max'])$(`#${id}`).onchange=()=>{driftROIs=null;invalidateFrom(4);$('#drift-table').replaceChildren();drawAll();};
function coords(name){const root=$(`#${name==='on'?'on':'r0'}-coordinates`);root.replaceChildren();const roi=state.rois[name];for(const key of ['x_min','x_max','y_min','y_max']){const label=el('label',key.replace('_',' ')),input=el('input');input.type='number';input.min=0;input.value=roi?roi[key]:'';input.oninput=()=>{if(!state.rois[name])state.rois[name]={x_min:0,x_max:0,y_min:0,y_max:0};state.rois[name][key]=+input.value;if(name==='on')captureDriftReference();invalidateFrom(name==='on'?4:6);drawAll()};label.append(input);root.append(label)}}
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
async function heatmap(root,kind,title,roiName=null,epoch=state.viewEpoch){const card=el('div',undefined,'image-card');if(['absorbance','baseline'].includes(kind))card.dataset.absorbancePreview='true';card.append(el('h4',title));if(roiName==='cnr'){const metrics=el('div',undefined,'cnr-parameters');renderCNRParameters(metrics);card.append(metrics);}root.append(card);const params=imageParams(kind);if(kind==='full_raw')params.brightest='true';if(kind==='spectrum'){params.window=String($('#inspection-window').checked);params.min_frequency=$('#candidate-min').value;}if(roiName==='r0'&&$('#r0-method').value!=='roi'){params.r0_method=$('#r0-method').value;params.r0_count=$('#r0-count').value;params.r0_reference_band=r0ReferenceBands[$('#preview-pattern').value];if($('#r0-restrict').checked){if(!state.rois.r0){card.append(el('p','Draw a search rectangle to preview selected pixels.','hint'));params.r0_method='roi';}else params.r0_search_roi=JSON.stringify(state.rois.r0);}}const data=await api('/api/image?'+new URLSearchParams(params));if(epoch!==state.viewEpoch)return;if(!data.available){card.append(el('div',kind==='baseline'?'Reference-only band: no baseline center configured':'Available after processing','placeholder'));return}const wrap=el('div',undefined,'heatmap'),canvas=el('canvas');canvas.width=data.width;canvas.height=data.height;wrap.append(canvas);const bar=el('div',undefined,'bar'),strip=el('div',undefined,'strip'),ticks=el('div',undefined,'ticks');[data.vmax,(data.vmax+data.vmin)/2,data.vmin].forEach(v=>ticks.append(el('span',Number(v.toPrecision(4)).toString())));bar.append(strip,ticks);wrap.append(bar);card.append(wrap);if(kind==='spectrum')card.append(el('div','fx: −0.5 → +0.5; fy: −0.5 (top) → +0.5 (bottom)','axis-hint'));const image=new Image;image.src='data:image/png;base64,'+data.png;await image.decode();if(epoch!==state.viewEpoch)return;const view={canvas,image,data,kind,roiName,titleNode:card.querySelector('h4'),metricsNode:card.querySelector('.cnr-parameters'),title};state.canvases.push(view);bindCanvas(view);draw(view);if(kind==='spectrum'){renderPeaks(data.peaks||[]);addSpectrumLabels(wrap,data);}if(roiName==='r0'&&data.cell_free_pixels)$('#r0-preview-status').textContent=`${data.cell_free_pixels.length} ${$('#r0-method').value} pixels from ${data.reference_wavenumber} cm⁻¹ · preview R₀ ${fmt(data.cell_free_r0)}`}
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
function draw(v){const ctx=v.canvas.getContext('2d');ctx.clearRect(0,0,v.canvas.width,v.canvas.height);ctx.drawImage(v.image,0,0,v.canvas.width,v.canvas.height);const pairs=v.roiName==='cnr'?[['background','#00eaff'],['target','#7dff00']]:v.roiName==='r0'&&$('#r0-method').value!=='roi'&&!$('#r0-restrict').checked?[]:v.roiName?[[v.roiName,'#00eaff']]:[];for(const [name,color] of pairs){const r=name==='on'&&driftROIs?driftROIs[$('#preview-pattern').value]:state.rois[name];if(!r)continue;ctx.strokeStyle=color;ctx.lineWidth=Math.max(v.data.width/400,.6);ctx.strokeRect(r.x_min,r.y_min,r.x_max-r.x_min,r.y_max-r.y_min)}if(v.data.cell_free_pixels){ctx.strokeStyle='#00eaff';ctx.lineWidth=Math.max(.35,v.data.width/1200);const arm=Math.max(1.25,v.data.width/320);for(const [y,x] of v.data.cell_free_pixels){ctx.beginPath();ctx.moveTo(x+.5-arm,y+.5);ctx.lineTo(x+.5+arm,y+.5);ctx.moveTo(x+.5,y+.5-arm);ctx.lineTo(x+.5,y+.5+arm);ctx.stroke();}}if(v.roiName==='cnr'){const row=state.cnr.find(r=>r.pattern===$('#preview-pattern').value&&r.wavenumber===+$('#preview-band').value&&r.stage===v.kind);v.titleNode.textContent=v.title;renderCNRParameters(v.metricsNode,row);v.metricsNode.title=row?`Background SD uses ddof=1. Status: ${row.status}`:'Calculate CNR to show parameters';}}
function drawAll(){state.canvases.forEach(draw)}
function bindCanvas(v){let start=null;const point=e=>{const b=v.canvas.getBoundingClientRect();return{x:Math.max(0,Math.min(v.data.width,(e.clientX-b.left)*v.data.width/b.width)),y:Math.max(0,Math.min(v.data.height,(e.clientY-b.top)*v.data.height/b.height))}};v.canvas.onpointerdown=e=>{if(document.body.classList.contains('busy'))return;if(v.kind==='spectrum'){if(!$('#fourier-enabled').checked||!['notch','combined'].includes($('#filter-mode').value))return;const p=point(e);const fx=v.data.fx[Math.min(v.data.width-1,Math.floor(p.x))],fy=v.data.fy[Math.min(v.data.height-1,Math.floor(p.y))];const peak=(v.data.peaks||[]).find(q=>Math.hypot(q.ix-p.x,q.iy-p.y)<8);addNotchPair(peak?peak.fy:fy,peak?peak.fx:fx);return}if(!v.roiName||(v.roiName==='r0'&&$('#r0-method').value!=='roi'&&!$('#r0-restrict').checked))return;if(v.roiName==='cnr'&&!state.mode)return;start=point(e);v.canvas.setPointerCapture(e.pointerId)};const update=e=>{if(!start)return;const p=point(e),name=v.roiName==='cnr'?state.mode:v.roiName;state.rois[name]={x_min:Math.floor(Math.min(start.x,p.x)),x_max:Math.ceil(Math.max(start.x,p.x)),y_min:Math.floor(Math.min(start.y,p.y)),y_max:Math.ceil(Math.max(start.y,p.y))};if(name==='on')captureDriftReference();if(name==='on'||name==='r0'){invalidateFrom(name==='on'?4:6);coords(name)}else{state.cnr=[];if(name==='background')state.rois.target=null;$('#cnr-table').replaceChildren();chart($('#cnr-chart'),[]);}drawAll()};v.canvas.onpointermove=update;v.canvas.onpointerup=e=>{const drawn=!!start;update(e);start=null;if(drawn&&v.roiName==='r0'&&$('#r0-restrict').checked&&$('#r0-method').value!=='roi')refreshView().catch(e=>notify(e.message,true));};v.canvas.onpointercancel=()=>start=null}
async function refreshView(){clearInterval(state.timer);state.timer=null;if(state.step===1&&rawSpectrum)drawRawSpectrum(rawSpectrum);if(state.step<3)return;const epoch=++state.viewEpoch;state.canvases=[];if(state.step===3){$('#crop-preview').replaceChildren();coords('on');await heatmap($('#crop-preview'),$('#raw-view').value,'Full image','on',epoch);table($('#qc-table'),state.qc,['pattern','wavenumber','i_goldref','reference_valid','frame_valid']);chart($('#qc-chart'),state.bands.map(wn=>({name:String(wn),values:state.qc.filter(r=>r.wavenumber===wn).map(r=>r.i_goldref)})))}if(state.step===4){$('#spectrum-preview').replaceChildren();await heatmap($('#spectrum-preview'),'spectrum','Inspect spectrum · click to add notches',null,epoch);schedulePreview()}if(state.step===5){$('#r0-preview').replaceChildren();$('#r0-preview-status').textContent='';$('#processing-preview').replaceChildren();coords('r0');renderR0References();await heatmap($('#r0-preview'),'rolling','Reflectance after rolling ball','r0',epoch);await Promise.all((state.maxStep>=6?['reflectance','fourier','rolling','absorbance']:['reflectance','fourier','rolling']).map(kind=>heatmap($('#processing-preview'),kind,stageNames[stages.indexOf(kind)],null,epoch)));}if(state.step===6){table($('#baseline-mapping'),Object.entries(state.mapping).map(([center,refs])=>({center,reference_bands:refs.join(', ')})),['center','reference_bands']);$('#baseline-preview').replaceChildren();await Promise.all((state.maxStep>=7?['absorbance','baseline']:['absorbance']).map(kind=>heatmap($('#baseline-preview'),kind,stageNames[stages.indexOf(kind)],null,epoch)));if(epoch===state.viewEpoch&&state.maxStep>=7)await prepareBaselineInspection();}if(state.step===7){updateTimeBands();$('#six-stages').replaceChildren();await Promise.all(stages.map((kind,i)=>heatmap($('#six-stages'),kind,stageNames[i],'cnr',epoch)));showCNR();table($('#r0-table'),state.r0,['pattern','wavenumber','method','reference_wavenumber','pixel_count','r0','reference_mean_absorbance'])}}
$('#confirm-crop').onclick=()=>busy($('#confirm-crop'),async()=>{if(!state.rois.on)throw Error('Please first Select the on-MS region.');const d=await api('/api/crop',cropPayload());state.version=d.version;state.rois.r0=state.rois.background=state.rois.target=null;unlock(4);notify('Per-pattern on-MS crops confirmed.');go(4)});
function filterMode(){const mode=$('#filter-mode').value;$$('[data-filter]').forEach(n=>n.hidden=n.dataset.filter!==mode&&mode!=='combined')}
$('#filter-mode').onchange=()=>{filterMode();processingChanged()};
$('#clear-notches').onclick=()=>{$('#notches').value='';processingChanged()};
function notchCenters(){const text=$('#notches').value.trim();if(!text)return[];return text.split(/[;\n]+/).filter(s=>s.trim()).map(s=>{const pair=s.split(',').map(v=>Number(v.trim()));if(pair.length!==2||pair.some(v=>!Number.isFinite(v)))throw Error('Use fy, fx pairs separated by semicolons.');return pair})}
function showBatchProgress(p){
  const percent=p.total?100*p.completed/p.total:0;
  $('#batch-progress').hidden=false;$('#batch-bar').value=percent;
  const seconds=Math.floor(p.elapsed_seconds||0), elapsed=`${Math.floor(seconds/60)}m ${seconds%60}s`;
  $('#batch-detail').textContent=`${p.status} · ${p.pattern?`${p.pattern} · ${p.wavenumber} cm⁻¹`:'Waiting to start'} · Completed ${p.completed}/${p.total} files (${percent.toFixed(1)}%) · Elapsed ${elapsed}`;
}
$('#process').onclick=()=>busy($('#process'),async()=>{
  const {fourier,rolling}=processingParameters();
  showBatchProgress({status:'starting',completed:0,total:state.patterns.length*state.bands.length,elapsed_seconds:0});
  let active=true;
  const poll=async()=>{try{const p=await api('/api/process-progress');if(active)showBatchProgress(p);}catch(e){}finally{if(active)setTimeout(poll,500);}};
  const request=api('/api/process',{fourier,rolling});
  setTimeout(()=>{if(active)poll();},300);
  try{
    const d=await request;state.version=d.version;state.rois.r0=state.rois.background=state.rois.target=null;state.r0=[];unlock(5);notify(`Completed ${d.summary.length} images processed with the selected settings.`);go(5);
  }finally{active=false;try{showBatchProgress(await api('/api/process-progress'));}catch(e){}}
});
function r0Mode(){const extreme=$('#r0-method').value!=='roi';$('#r0-roi-controls').hidden=extreme&&!$('#r0-restrict').checked;$('#r0-extreme-controls').hidden=!extreme;invalidateFrom(6);if(state.step===5)refreshView().catch(e=>notify(e.message,true))}
$('#r0-method').onchange=r0Mode;$('#r0-restrict').onchange=r0Mode;
$('#r0-count').onchange=()=>{invalidateFrom(6);if(state.step===5)refreshView().catch(e=>notify(e.message,true))};
$('#calculate').onclick=()=>busy($('#calculate'),async()=>{const method=$('#r0-method').value;if(method==='roi'&&!state.rois.r0)throw Error('Select a cell-free ROI first.');const payload={method};if(method==='roi')payload.roi=state.rois.r0;else{payload.count=+$('#r0-count').value;if($('#r0-restrict').checked){if(!state.rois.r0)throw Error('Draw a search rectangle first.');payload.search_roi=state.rois.r0;}payload.reference_bands=Object.fromEntries(state.patterns.map(p=>[p,r0ReferenceBands[p]]));}const d=await api('/api/calculate',payload);state.version=d.version;state.r0=d.r0;state.cnr=[];state.rois.background=state.rois.target=null;state.mode=null;state.cnrDirty=false;unlock(6);clearBaselineInspection();$('#baseline-preview').replaceChildren();notify('Absorbance calculated. Review the preview, then continue to baseline correction.');await refreshView()});
$('#calculate-baseline').onclick=()=>busy($('#calculate-baseline'),async()=>{const d=await api('/api/baseline',{});state.version=d.version;state.cnr=[];state.rois.background=state.rois.target=null;state.cnrDirty=false;state.mode=null;unlock(7);notify('Baseline correction complete. Inspect the images and pixel fits below.');await refreshView();});
$('#cnr-background').onclick=()=>{state.cnrDirty=true;state.mode='background';state.rois.background=state.rois.target=null;state.cnr=[];showCNR();$('#cnr-instruction').textContent='Select background: drag a rectangle on any stage.';drawAll()};
$('#cnr-target').onclick=()=>{if(!state.rois.background){notify('Select the background first.',true);return}state.cnrDirty=true;state.mode='target';state.rois.target=null;state.cnr=[];showCNR();$('#cnr-instruction').textContent='Select target ROI: it must not overlap the background.';drawAll()};
$('#calculate-cnr').onclick=()=>busy($('#calculate-cnr'),async()=>{if(!state.rois.background||!state.rois.target)throw Error('Select background, then target ROI.');const d=await api('/api/cnr',{background:state.rois.background,target:state.rois.target});state.cnr=d.records;state.cnrDirty=false;state.mode=null;drawAll();showCNR();notify('The same ROIs were used to calculate CNR for all patterns, bands, and stages.')});
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
  const values=[['CNR',row?.cnr,0],['A_s',row?.target_mean,2],['A_bg',row?.background_mean,2],['sigma_bg',row?.background_std,2],['|A_s − A_bg|',row?.signed_contrast==null?null:Math.abs(row.signed_contrast),2]];
  values.forEach(([label,value,digits],i)=>{if(i)node.append(document.createTextNode(' · '));const symbol=el('span');if(cnrSymbol(label))symbol.innerHTML=cnrSymbol(label);else symbol.textContent=label;node.append(symbol,document.createTextNode(': '+cnrNumber(value,digits)));});
}
function showCNR(){
  const rows=state.cnr.filter(r=>r.pattern===$('#preview-pattern').value&&r.wavenumber===+$('#preview-band').value);
  const details=rows.map(r=>({
    Stage:stageNames[stages.indexOf(r.stage)],CNR:cnrNumber(r.cnr,0),
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
  for(const metric of ['cnr'])chart($('#'+metric+'-chart'),rows.length?[{name:metric.toUpperCase(),values:rows.map(r=>r[metric])}]:[],['Raw','R before','Fourier','Rolling','A before','A baseline']);
}

function updateTimeBands(){
  const bands=$('#time-kind').value==='baseline'?Object.keys(state.mapping).map(Number).sort((a,b)=>a-b):state.bands;
  fillSelect($('#time-band'),bands,$('#time-band').value||$('#preview-band').value);
}
async function buildTime(){
  return busy($('#build-time'),async()=>{
    $('#time-band').disabled=true;$('#time-kind').disabled=true;
    try{
const frameIndex=+$('#time-slider').value;$('#time-player').hidden=true;clearInterval(state.timer);state.timer=null;state.time=await api('/api/timelapse',{wavenumber:+$('#time-band').value,kind:$('#time-kind').value,start:+$('#time-start').value,end:+$('#time-end').value,skip_invalid:$('#time-skip').checked,low:+$('#time-low').value,high:+$('#time-high').value});updateVideoTitle();$('#time-extrema').textContent=state.time.extrema_label;$('#time-ticks').replaceChildren(...[state.time.vmax,(state.time.vmax+state.time.vmin)/2,state.time.vmin].map(v=>el('span',v.toFixed(4))));$('#time-player').hidden=false;$('#time-slider').max=state.time.frames.length-1;$('#time-slider').value=Math.min(frameIndex,state.time.frames.length-1);renderFrame();notify(`Built ${state.time.frames.length} frames. All frames use the same color scale.`)
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
  const response=await fetch('/api/export-video',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({video_id:video.video_id,fps,labels:video.frames.map((_,i)=>frameLabel(video,i))})});
  if(!response.ok){const error=await response.json();throw Error(error.error||'Video export failed.');}
  const url=URL.createObjectURL(await response.blob()),link=el('a');link.href=url;link.download=`qcl_${video.wavenumber}_${video.kind}_${fps}fps.mp4`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);notify('Current video exported as MP4, including title, FPS, color scale, and timestamps.');
});
for(const id of ['preview-pattern','preview-band','raw-view','inspection-window'])$(`#${id}`).onchange=()=>refreshView().catch(e=>notify(e.message,true));
$('#refresh-view').onclick=()=>refreshView().catch(e=>notify(e.message,true));
$$('[data-go]').forEach(b=>b.onclick=()=>go(+b.dataset.go));
$$('section[data-step="4"] input, section[data-step="4"] textarea, #rb-polarity').forEach(n=>{if(!['inspection-window','candidate-min'].includes(n.id))n.addEventListener('input',processingChanged)});$('#candidate-min').oninput=()=>refreshView().catch(e=>notify(e.message,true));
for(const id of ['reference-pixels','qc-z','qc-deviation'])$(`#${id}`).onchange=()=>invalidateFrom(3);
$('#input-path').value=localStorage.getItem('qclProcessingPath')||'';
renderNav();filterMode();r0Mode();

// Do not export an older CNR measurement after its visible ROIs are edited.
$('#download').onclick=e=>{if(state.cnrDirty||((state.rois.background||state.rois.target)&&!state.cnr.length)){e.preventDefault();notify('The ROI changed. Recalculate CNR before exporting.',true)}};

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
      const data=await api('/api/image?'+new URLSearchParams({pattern,wavenumber,kind:'absorbance',low:$('#display-low').value,high:$('#display-high').value}));
      if(revision!==fitRevision)return;
      const img=new Image();img.src='data:image/png;base64,'+data.png;await img.decode();if(revision!==fitRevision)return;
      canvas.width=data.width;canvas.height=data.height;fitImage=img;
      for(const [axis,size] of [['x',data.width],['y',data.height]]){const input=$('#fit-'+axis);input.max=size-1;input.value=Math.max(0,Math.min(size-1,Number(input.value)||0));}
      $('#fit-image-ticks').replaceChildren(...[data.vmax,(data.vmin+data.vmax)/2,data.vmin].map(v=>el('span',fmt(v))));
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

function resetRawInspector(){
  rawRevision++;rawPending=false;rawNeedsImage=false;rawImage=null;rawSpectrum=null;
  $('#raw-inspector').hidden=true;$('#raw-spectrum-table').replaceChildren();$('#raw-spectrum-status').textContent='';
  const c=$('#raw-pixel-image');c.getContext('2d').clearRect(0,0,c.width,c.height);drawRawSpectrum(null);
}
function rawBands(){
  const item=state.discovery.availability.find(p=>p.pattern===$('#raw-pattern').value);
  fillSelect($('#raw-band'),item?item.wavenumbers:[],$('#raw-band').value);
}
function prepareRawInspector(){
  fillSelect($('#raw-pattern'),state.discovery.availability.map(p=>p.pattern));rawBands();
  $('#raw-x').value=0;$('#raw-y').value=0;$('#raw-inspector').hidden=false;requestRawInspection(true);
}
function drawRawPixel(){
  if(!rawImage)return;const c=$('#raw-pixel-image'),ctx=c.getContext('2d');
  ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(rawImage,0,0,c.width,c.height);
  const x=+$('#raw-x').value+.5,y=+$('#raw-y').value+.5,arm=Math.max(1,c.width/80);
  ctx.strokeStyle='#00eaff';ctx.lineWidth=Math.max(.4,c.width/600);ctx.beginPath();ctx.moveTo(x-arm,y);ctx.lineTo(x+arm,y);ctx.moveTo(x,y-arm);ctx.lineTo(x,y+arm);ctx.stroke();
}
function requestRawInspection(loadImage=false){
  rawRevision++;rawPending=true;rawNeedsImage=rawNeedsImage||loadImage;
  if(loadImage){rawImage=null;const c=$('#raw-pixel-image');c.getContext('2d').clearRect(0,0,c.width,c.height);$('#raw-image-ticks').replaceChildren();}
  rawSpectrum=null;drawRawSpectrum(null);$('#raw-spectrum-table').replaceChildren();$('#raw-spectrum-status').textContent='Loading raw spectrum…';runRawInspection();
}
async function runRawInspection(){
  if(rawRunning||!rawPending)return;
  rawRunning=true;rawPending=false;
  const revision=rawRevision,loadImage=rawNeedsImage||!rawImage;rawNeedsImage=false;
  try{
    const pattern=$('#raw-pattern').value,wavenumber=+$('#raw-band').value;
    if(loadImage){
      const d=await api('/api/raw-inspection',{pattern,wavenumber,mode:'image'});if(revision!==rawRevision)return;
      const img=new Image();img.src='data:image/png;base64,'+d.png;await img.decode();if(revision!==rawRevision)return;
      rawImage=img;const c=$('#raw-pixel-image');c.width=d.width;c.height=d.height;
      for(const [axis,size] of [['x',d.width],['y',d.height]]){const input=$('#raw-'+axis);input.max=size-1;input.value=Math.max(0,Math.min(size-1,Number(input.value)||0));}
      $('#raw-image-title').textContent=`${pattern} · ${wavenumber} cm⁻¹ · raw signal`;
      $('#raw-image-ticks').replaceChildren(...[d.vmax,(d.vmin+d.vmax)/2,d.vmin].map(v=>el('span',fmt(v))));
    }
    drawRawPixel();
    const d=await api('/api/raw-inspection',{pattern,wavenumber,x:+$('#raw-x').value,y:+$('#raw-y').value});if(revision!==rawRevision)return;
    rawSpectrum=d;drawRawSpectrum(d);table($('#raw-spectrum-table'),d.points,['wavenumber','raw_signal']);
    $('#raw-spectrum-status').textContent=`${d.pattern} · pixel (${d.x}, ${d.y}) · ${d.points.length} measured bands. ${d.missing_wavenumbers.length?'Not available in this pattern: '+d.missing_wavenumbers.join(', ')+' cm⁻¹.':''}`;
  }catch(e){if(revision===rawRevision)$('#raw-spectrum-status').textContent=e.message;}
  finally{rawRunning=false;if(rawPending)runRawInspection();}
}
function drawRawSpectrum(d){
  const c=$('#raw-spectrum-chart'),ctx=c.getContext('2d'),ratio=devicePixelRatio||1,w=c.clientWidth||600,h=340;
  c.width=w*ratio;c.height=h*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);if(!d)return;
  const points=d.points,p={l:80,r:22,t:35,b:50},xs=points.map(v=>v.wavenumber),ys=points.map(v=>v.raw_signal);
  const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),ym=(ymax-ymin||Math.max(Math.abs(ymin)*.1,1))*.1;
  const x=v=>p.l+(xmax===xmin?.5:(v-xmin)/(xmax-xmin))*(w-p.l-p.r),y=v=>p.t+(ymax+ym-v)/(ymax-ymin+2*ym)*(h-p.t-p.b);
  ctx.font='11px sans-serif';ctx.fillStyle='#435b50';ctx.fillText('Raw signal',p.l,18);
  for(let i=0;i<=4;i++){const v=ymin-ym+(ymax-ymin+2*ym)*i/4;ctx.strokeStyle='#e4eae5';ctx.beginPath();ctx.moveTo(p.l,y(v));ctx.lineTo(w-p.r,y(v));ctx.stroke();ctx.fillText(v.toExponential(2),2,y(v)+4);}
  ctx.textAlign='center';for(let i=0;i<=(xmin===xmax?0:4);i++){const v=xmin+(xmax-xmin)*i/4;ctx.fillText(fmt(v),x(v),h-28);}ctx.fillText('Wavenumber (cm⁻¹)',(p.l+w-p.r)/2,h-7);ctx.textAlign='left';
  ctx.strokeStyle='#157e69';ctx.lineWidth=1.5;ctx.beginPath();points.forEach((v,i)=>i?ctx.lineTo(x(v.wavenumber),y(v.raw_signal)):ctx.moveTo(x(v.wavenumber),y(v.raw_signal)));ctx.stroke();
  for(const v of points){ctx.fillStyle=v.wavenumber===d.wavenumber?'#c57522':'#157e69';ctx.beginPath();ctx.arc(x(v.wavenumber),y(v.raw_signal),v.wavenumber===d.wavenumber?5:3,0,2*Math.PI);ctx.fill();}
}
$('#raw-pattern').onchange=()=>{rawBands();requestRawInspection(true);};
$('#raw-band').onchange=()=>requestRawInspection(true);
$('#raw-inspect').onclick=()=>requestRawInspection();
for(const axis of ['x','y'])$('#raw-'+axis).onchange=()=>requestRawInspection();
$('#raw-pixel-image').onpointerdown=e=>{
  if(!rawImage||document.body.classList.contains('busy'))return;const c=e.currentTarget,b=c.getBoundingClientRect();
  $('#raw-x').value=Math.max(0,Math.min(c.width-1,Math.floor((e.clientX-b.left)*c.width/b.width)));
  $('#raw-y').value=Math.max(0,Math.min(c.height-1,Math.floor((e.clientY-b.top)*c.height/b.height)));
  requestRawInspection();
};
window.addEventListener('resize',()=>{if(rawSpectrum&&state.step===1)drawRawSpectrum(rawSpectrum);});
