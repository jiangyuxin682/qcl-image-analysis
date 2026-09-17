'use strict';
const $=s=>document.querySelector(s),datasets=[];
let active=null,desiredStep=1,shared=null,info=[],revision=0;
const selections=new Map();
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
async function api(url,payload){const r=await fetch(url,payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function tell(d,message){d.frame.contentWindow.postMessage(message,location.origin);}
function tabs(){
  const root=$('#dataset-tabs');root.replaceChildren();
  for(const d of datasets){const b=el('button',`${d.name} · ${d.maxStep||1}/8`);b.className=d.id===active?'secondary active':'secondary';b.disabled=datasets.some(x=>x.busy);b.onclick=()=>select(d.id);root.append(b);}
  const b=el('button','Final comparison');b.className=active==='comparison'?'secondary active':'secondary';b.disabled=datasets.length<2||datasets.some(d=>d.busy);b.onclick=()=>select('comparison');root.append(b);
  $('#add-folder').disabled=datasets.some(d=>d.busy);
}
function select(id){active=id;revision++;datasets.forEach(d=>d.frame.hidden=d.id!==id);$('#comparison').hidden=id!=='comparison';tabs();if(id==='comparison')loadComparison();else tell(datasets.find(d=>d.id===id),{type:'section',step:desiredStep});}
$('#add-folder').onclick=async()=>{
  $('#add-folder').disabled=true;
  try{const d=await api('/api/datasets',{path:$('#folder-path').value,name:$('#folder-name').value});
    const frame=el('iframe');frame.title=d.name;frame.hidden=true;
    const item={...d,frame,maxStep:1,step:1,busy:false,cnrDirty:true};datasets.push(item);
    frame.src='/?'+new URLSearchParams({dataset:d.id,embedded:'1',path:d.path});$('#dataset-frames').append(frame);
    $('#folder-path').value='';$('#folder-name').value='';$('#import-folders').open=false;
    select(d.id);$('#multi-status').textContent=`Added ${d.name}. Use Add a folder to create another dataset tab.`;
  }catch(e){$('#multi-status').textContent=e.message;}finally{tabs();}
};
window.addEventListener('message',e=>{
  if(e.origin!==location.origin)return;const d=datasets.find(d=>d.frame.contentWindow===e.source&&d.id===e.data.dataset);if(!d)return;
  if(e.data.type==='ready'){if(shared)tell(d,{type:'shared',settings:shared});else tell(d,{type:'request-shared'});if(d.id===active)tell(d,{type:'section',step:desiredStep});}
  if(e.data.type==='shared'){
    shared=e.data.settings;datasets.filter(x=>x!==d).forEach(x=>tell(x,{type:'shared',settings:shared}));
    revision++;$('#comparison-grid').replaceChildren();
  }
  if(e.data.type==='busy')d.busy=e.data.busy;
  if(e.data.type==='progress'){d.maxStep=e.data.maxStep;d.step=e.data.step;d.cnrDirty=e.data.cnrDirty;if(d.id===active)desiredStep=d.step;}
  tabs();
});
function fill(node,values,value){node.replaceChildren();values.forEach(v=>{const o=el('option',String(v));o.value=v;node.append(o);});if(values.map(String).includes(String(value)))node.value=value;}
function commonBands(){const stage=$('#compare-stage').value;return info.reduce((a,d)=>{const bands=stage==='baseline'?Object.keys(d.mapping).map(Number):d.bands;return a===null?bands:a.filter(v=>bands.includes(v));},null)||[];}
function stable(value){if(Array.isArray(value))return value.map(stable);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])]));return value;}
function signature(d){return JSON.stringify(stable({mapping:d.mapping,parameters:d.parameters,r0:{method:d.r0_selection.method,count:d.r0_selection.count}}));}
async function loadComparison(){
  const current=++revision;$('#comparison-grid').replaceChildren();$('#compare-export').disabled=true;
  try{
    info=await api('/api/comparison-info?'+new URLSearchParams({ids:datasets.map(d=>d.id).join(',')}));if(current!==revision)return;
    const incomplete=datasets.filter(d=>d.maxStep<8||d.cnrDirty||!info.find(i=>i.id===d.id)?.cnr.length);
    if(incomplete.length){$('#compare-status').textContent='Finish processing and calculate CNR for: '+incomplete.map(d=>d.name).join(', ');return;}
    if(new Set(info.map(signature)).size!==1){$('#compare-status').textContent='Shared processing settings differ. Reconfigure/process/calculate the affected datasets before comparison.';return;}
    if(new Set(info.filter(d=>d.has_gold).map(d=>JSON.stringify(stable({n_pixels:d.n_pixels,qc:d.qc_settings})))).size>1){$('#compare-status').textContent='Gold-reference settings differ. Recalculate reflectance and subsequent steps for the affected datasets.';return;}
    const reflectanceOption=$('#compare-stage option[value="reflectance"]');reflectanceOption.disabled=reflectanceOption.hidden=info.some(d=>!d.has_gold);
    if(reflectanceOption.disabled&&$('#compare-stage').value==='reflectance')$('#compare-stage').value='raw';
    fill($('#compare-band'),commonBands(),$('#compare-band').value);if(!$('#compare-band').value){$('#compare-status').textContent='No common wavenumber for this stage.';return;}
    $('#compare-export').disabled=false;$('#compare-status').textContent='Each image has its own color scale. CNR uses each folder’s independently selected target and background ROIs.';
    const kind=$('#compare-stage').value,wn=+$('#compare-band').value;
    for(const d of info){
      const card=el('div');card.className='card';card.append(el('h3',d.name));card.append(el('p',d.has_gold?'Processing basis: gold-normalized reflectance':'Processing basis: raw intensity · reflectance skipped'));const options=el('div');options.className='dataset-options';
      const choice=selections.get(d.id)||{pattern:d.patterns[0]};choice.low=d.cnr[0]?.contrast_low_percentile??0;choice.high=d.cnr[0]?.contrast_high_percentile??100;selections.set(d.id,choice);
      const label=el('label','Pattern'),select=el('select');fill(select,d.patterns,choice.pattern);choice.pattern=select.value;label.append(select);options.append(label);
      for(const key of ['low','high']){const l=el('label',`${key==='low'?'Lower':'Upper'} display / CNR percentile`),input=el('input');input.type='number';input.min=0;input.max=100;input.value=choice[key];input.onchange=async()=>{
        const dataset=datasets.find(x=>x.id===d.id),range={low:choice.low,high:choice.high,[key]:Number(input.value)};
        dataset.busy=true;tabs();$('#compare-export').disabled=true;document.querySelectorAll('#comparison input, #comparison select, #comparison button').forEach(n=>n.disabled=true);
        try{const result=await api('/api/cnr?'+new URLSearchParams({dataset:d.id}),{...d.cnr_rois,...range});tell(dataset,{type:'cnr-contrast',...range,records:result.records});}
        catch(e){$('#compare-status').textContent=e.message;input.value=choice[key];}
        finally{dataset.busy=false;tabs();document.querySelectorAll('#comparison input, #comparison select, #comparison button').forEach(n=>n.disabled=false);await loadComparison();}
      };l.append(input);options.append(l);}
      select.onchange=()=>{choice.pattern=select.value;loadComparison();};card.append(options);
      choice.zero??={};const zeroLabel=el('label'),zeroInput=el('input');zeroInput.type='checkbox';zeroInput.checked=!!choice.zero[kind];zeroLabel.append(zeroInput,document.createTextNode('Set lower limit to 0 · display only'));card.append(zeroLabel);zeroInput.onchange=()=>{choice.zero[kind]=zeroInput.checked;loadComparison();};
      card.append(el('h4',$('#compare-stage').selectedOptions[0].textContent));const metrics=el('p');metrics.className='cnr-parameters';const row=d.cnr.find(r=>r.pattern===choice.pattern&&r.wavenumber===wn&&r.stage===kind);
      const number=(v,digits=2)=>typeof v==='number'&&Number.isFinite(v)?digits===0?v.toFixed(0):v.toExponential(2):'—';
      metrics.innerHTML=`<div>Unadjusted CNR: ${number(row?.cnr_unadjusted,0)} · CNR: ${number(row?.cnr,0)} · Percentiles: ${row?.contrast_low_percentile}–${row?.contrast_high_percentile}</div><div><i>A</i><sub>s</sub>: ${number(row?.target_mean)} · <i>A</i><sub>bg</sub>: ${number(row?.background_mean)} · σ<sub>bg</sub>: ${number(row?.background_std)} · |<i>A</i><sub>s</sub> − <i>A</i><sub>bg</sub>|: ${number(row?.signed_contrast==null?null:Math.abs(row.signed_contrast))}</div>`;card.append(metrics);$('#comparison-grid').append(card);
      const data=await api('/api/image?'+new URLSearchParams({dataset:d.id,pattern:choice.pattern,wavenumber:wn,kind,low:choice.low,high:choice.high,colorbar_zero:!!choice.zero[kind]}));if(current!==revision)return;
      if(!data.available){card.append(el('p','Stage unavailable'));continue;}
      const wrap=el('div');wrap.className='heatmap';const img=el('img');img.alt=`${d.name} ${choice.pattern} ${wn} ${kind}`;img.src='data:image/png;base64,'+data.png;const bar=el('div');bar.className='bar';const strip=el('div');strip.className='strip';const ticks=el('div');ticks.className='ticks';[data.vmax,(data.vmin+data.vmax)/2,data.vmin].forEach(v=>ticks.append(el('span',v.toFixed(3))));bar.append(strip,ticks);
      const holder=el('div');holder.style.cssText='position:relative;width:calc(100% - 60px);align-self:start';img.style.width='100%';img.style.display='block';holder.append(img);
      const ns='http://www.w3.org/2000/svg',overlay=document.createElementNS(ns,'svg');overlay.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);overlay.setAttribute('preserveAspectRatio','none');overlay.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';
      for(const [name,color] of [['background','#00eaff'],['target','#7dff00']]){const roi=d.cnr_rois?.[name];if(!roi)continue;const box=document.createElementNS(ns,'rect');for(const [key,value] of Object.entries({x:roi.x_min,y:roi.y_min,width:roi.x_max-roi.x_min,height:roi.y_max-roi.y_min,fill:'none',stroke:color,'stroke-width':1,'stroke-opacity':1,'stroke-dasharray':'4 3','vector-effect':'non-scaling-stroke'}))box.setAttribute(key,value);overlay.append(box);}holder.append(overlay);wrap.append(holder,bar);card.append(wrap);
      card.append(el('p',`Target pixels: ${row?.target_pixels??0} · Background pixels: ${row?.background_pixels??0} · ${row?.status||'unavailable'}`));
    }
  }catch(e){if(current===revision)$('#compare-status').textContent=e.message;}
}
$('#compare-stage').onchange=loadComparison;$('#compare-band').onchange=loadComparison;$('#compare-refresh').onclick=loadComparison;
$('#compare-export').onclick=async()=>{try{const r=await fetch('/api/comparison-export?'+new URLSearchParams({ids:datasets.map(d=>d.id).join(',')}));if(!r.ok)throw Error((await r.json()).error);const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download='qcl-folder-comparison.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(e){$('#compare-status').textContent=e.message;}};
tabs();
