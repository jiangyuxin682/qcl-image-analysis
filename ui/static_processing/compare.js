'use strict';
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)],datasets=[];
let active=null,desiredStep=1,shared=null,info=[],revision=0,importing=false;
const selections=new Map();
let automaticColorLimits=true;
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
async function api(url,payload){const r=await fetch(url,payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function tell(d,message){d.frame.contentWindow.postMessage(message,location.origin);}
function tabs(){
  const root=$('#dataset-tabs');root.replaceChildren();
  for(const d of datasets){const b=el('button',`${d.name} · ${d.step||1}/10`);b.className=d.id===active?'secondary active':'secondary';b.disabled=importing||datasets.some(x=>x.busy);b.onclick=()=>select(d.id);root.append(b);}
  const b=el('button','Final comparison');b.className=active==='comparison'?'secondary active':'secondary';b.disabled=importing||datasets.length<2||datasets.some(d=>d.busy);b.onclick=()=>select('comparison');root.append(b);
  $('#add-folder').disabled=importing||datasets.some(d=>d.busy);
  $$('#import-folders input, #import-folders select').forEach(n=>n.disabled=importing||datasets.some(d=>d.busy));
}
function select(id){active=id;revision++;datasets.forEach(d=>d.frame.hidden=d.id!==id);$('#comparison').hidden=id!=='comparison';tabs();if(id==='comparison')loadComparison();else tell(datasets.find(d=>d.id===id),{type:'section',step:desiredStep});}
function addDatasetTab(d){
  const frame=el('iframe');frame.title=d.name;frame.hidden=true;
  datasets.push({...d,frame,maxStep:1,step:1,busy:false,cnrDirty:true});
  frame.src='/?'+new URLSearchParams({dataset:d.id,embedded:'1',load:'1'});$('#dataset-frames').append(frame);
  select(d.id);
}
$('#folder-input-kind').onchange=()=>{
  const kind=$('#folder-input-kind').value;
  $('#folder-picker-label').hidden=kind!=='folder';$('#folder-files-label').hidden=kind!=='files';$('#folder-zip-label').hidden=kind!=='zip';
};
let localComparisonFolder='';
$('#folder-picker').onclick=async()=>{
  $('#folder-picker').disabled=true;
  try{const path=await QCLUpload.chooseFolder();if(path){localComparisonFolder=path;$('#folder-picker-path').textContent=path;$('#folder-picker-path').title=path;}}
  catch(e){$('#multi-status').textContent=e.message;}
  finally{$('#folder-picker').disabled=false;}
};
$('#add-folder').onclick=async()=>{
  importing=true;tabs();
  try{
    const kind=$('#folder-input-kind').value,name=$('#folder-name').value;
    if(kind==='zip'){
      const files=[...$('#folder-zip').files];if(!files.length)throw Error('Choose a processing ZIP first.');
      for(const file of files){
        if(file.size>1024**3)throw Error('Project ZIP exceeds the 1 GiB upload limit.');
        $('#multi-status').textContent=`Reproducing ${file.name}… Saved processing is being recalculated and verified.`;
        const response=await fetch('/api/datasets/reproduce?'+new URLSearchParams({name:name||file.name.replace(/\.zip$/i,'')}),{method:'POST',headers:{'Content-Type':'application/zip'},body:file});
        const result=await response.json();if(!response.ok)throw Error(result.error||'ZIP import failed.');
        result.datasets.forEach(addDatasetTab);
      }
    }else{
      $('#multi-status').textContent='Importing selected spectral files…';
      if(kind==='folder'&&!localComparisonFolder)throw Error('Choose a local data folder first.');
      const response=kind==='folder'
        ?await fetch('/api/datasets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:localComparisonFolder,name})})
        :await fetch('/api/datasets/upload-csv',{method:'POST',body:QCLUpload.stream($('#folder-files').files,name)});
      const result=await response.json();if(!response.ok)throw Error(result.error||'Data import failed.');addDatasetTab(result);
    }
    $('#folder-name').value='';$('#import-folders').open=false;
    $('#multi-status').textContent='Datasets imported. ZIP tabs retain saved settings; if shared groups differ, turn off their sharing switches or explicitly reconfigure before Final comparison.';
  }catch(e){$('#multi-status').textContent=e.message;}finally{importing=false;tabs();}
};
const sharing={spectral:true,normalization:true,processing:true,analyte:true};
const groupFields={spectral:[],normalization:['has-gold','reference-pixels','qc-z','qc-deviation'],processing:['fourier-enabled','filter-mode','notches','notch-sigma-x','notch-sigma-y','notch-strength','protect-radius','fourier-pad','cutoff-x','cutoff-y','rolling-enabled','rb-radius','rb-height','rb-polarity','rb-sigma','rb-pad'],analyte:['r0-method','r0-count']};
const firstCommitted={};
function groupSettings(settings,group){
  return group==='spectral'?{mapping:settings.mapping,fields:{}}:{fields:Object.fromEntries(groupFields[group].filter(id=>id in settings.fields).map(id=>[id,settings.fields[id]]))};
}
function mergeSettings(base,patch){return {...base,...patch,fields:{...base?.fields,...patch.fields}};}
function enabledSettings(settings){let result={fields:{}};for(const group of Object.keys(sharing))if(sharing[group])result=mergeSettings(result,groupSettings(settings,group));return result;}
function broadcastPolicy(){datasets.forEach(d=>tell(d,{type:'sharing-policy',sharing,multiple:datasets.length>1}));}
window.addEventListener('message',e=>{
  if(e.origin!==location.origin)return;const d=datasets.find(d=>d.frame.contentWindow===e.source&&d.id===e.data.dataset);if(!d)return;
  if(e.data.type==='ready'){
    broadcastPolicy();
    if(e.data.reproduced){
      d.settings=e.data.settings;d.committed={};
      for(const group of Object.keys(sharing)){
        d.committed[group]=groupSettings(d.settings,group);
        if(!firstCommitted[group]){
          firstCommitted[group]=d.id;
          if(sharing[group]){
            shared=mergeSettings(shared,d.committed[group]);
            datasets.filter(x=>x!==d&&!x.reproduced&&!x.committed?.[group]).forEach(x=>tell(x,{type:'shared',settings:d.committed[group]}));
          }
        }
      }
      if(!shared)shared=enabledSettings(d.settings);
      // Imported calculations remain valid; never silently replace their recipe.
    }else{
      if(shared)tell(d,{type:'shared',settings:enabledSettings(shared)});
      tell(d,{type:'request-shared'});
    }
    if(d.id===active)tell(d,{type:'section',step:desiredStep});
  }
  if(e.data.type==='shared'){
    d.settings=e.data.settings;
    shared=mergeSettings(shared,enabledSettings(d.settings));
    datasets.filter(x=>x!==d).forEach(x=>tell(x,{type:'shared',settings:enabledSettings(shared)}));
    revision++;$('#comparison-grid').replaceChildren();
  }
  if(e.data.type==='shared-commit'){
    d.settings=e.data.settings;d.committed??={};d.committed[e.data.group]=groupSettings(d.settings,e.data.group);
    firstCommitted[e.data.group]??=d.id;
  }
  if(e.data.type==='sharing-toggle'&&e.data.group in sharing){
    const group=e.data.group;sharing[group]=!!e.data.enabled;
    if(sharing[group]){
      const source=datasets.find(x=>x.id===firstCommitted[group]);
      const settings=source?.committed?.[group]||groupSettings(datasets.find(x=>x.settings)?.settings||{mapping:{},fields:{}},group);
      shared=mergeSettings(shared,settings);
      datasets.forEach(x=>tell(x,{type:'shared',settings}));
    }
    broadcastPolicy();revision++;$('#comparison-grid').replaceChildren();
  }
  if(e.data.type==='busy')d.busy=e.data.busy;
  if(e.data.type==='progress'){d.maxStep=e.data.maxStep;d.step=e.data.step;d.cnrDirty=e.data.cnrDirty;if(d.id===active)desiredStep=d.step;}
  tabs();
});
function fill(node,values,value){node.replaceChildren();values.forEach(v=>{const o=el('option',String(v));o.value=v;node.append(o);});if(values.map(String).includes(String(value)))node.value=value;}
function commonBands(){const stage=$('#compare-stage').value;return info.reduce((a,d)=>{const bands=stage==='baseline'?Object.keys(d.mapping).map(Number):d.bands;return a===null?bands:a.filter(v=>bands.includes(v));},null)||[];}
function stable(value){if(Array.isArray(value))return value.map(stable);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])]));return value;}
function signature(d){return JSON.stringify(stable({mapping:sharing.spectral?d.mapping:null,parameters:sharing.processing?d.parameters:null,normalization:sharing.normalization?{has_gold:d.has_gold,...(d.has_gold?{n_pixels:d.n_pixels,qc:d.qc_settings}:{})}:null,r0:sharing.analyte?{method:d.r0_selection.method,count:d.r0_selection.count}:null}));}
function comparisonColorRange(records){
  const finite=records.filter(r=>r.available&&Number.isFinite(r.data_min)&&Number.isFinite(r.data_max));
  if(!finite.length)throw Error('No finite values in the selected images.');
  const min=Math.min(...finite.map(r=>r.data_min)),max=Math.max(...finite.map(r=>r.data_max));
  return {min,max:max>min?max:min+Math.max(1e-12,Math.abs(min)*1e-12)};
}
async function sharedColorRange(kind,wn,current){
  const enabled=$('#compare-shared-scale').checked;
  for(const id of ['compare-color-min','compare-color-max','compare-color-auto'])$('#'+id).disabled=!enabled;
  if(!enabled)return null;
  if(automaticColorLimits){
    const records=await Promise.all(info.map(d=>{
      const selected=selections.get(d.id)?.pattern,pattern=d.patterns.includes(selected)?selected:d.patterns[0];
      return api('/api/image?'+new URLSearchParams({dataset:d.id,pattern,wavenumber:wn,kind,stats_only:true}));
    }));
    if(current!==revision)return null;
    const range=comparisonColorRange(records);
    $('#compare-color-min').value=String(range.min);$('#compare-color-max').value=String(range.max);
  }
  const minText=$('#compare-color-min').value,maxText=$('#compare-color-max').value;
  const min=Number(minText),max=Number(maxText);
  if(!minText.trim()||!maxText.trim()||!Number.isFinite(min)||!Number.isFinite(max)||min>=max)throw Error('Enter finite colorbar limits with minimum < maximum.');
  return {display_min:min,display_max:max};
}
async function loadComparison(){
  const current=++revision;$('#comparison-grid').replaceChildren();$('#compare-export').disabled=true;
  try{
    info=await api('/api/comparison-info?'+new URLSearchParams({ids:datasets.map(d=>d.id).join(',')}));if(current!==revision)return;
    const incomplete=datasets.filter(d=>d.maxStep<8||d.cnrDirty||!info.find(i=>i.id===d.id)?.cnr.length);
    if(incomplete.length){$('#compare-status').textContent='Finish processing and calculate CNR for: '+incomplete.map(d=>d.name).join(', ');return;}
    if(new Set(info.map(signature)).size!==1){$('#compare-status').textContent='Shared processing settings differ. Turn off sharing for the differing groups, or reconfigure and recalculate those datasets before comparison.';return;}

    const reflectanceOption=$('#compare-stage option[value="reflectance"]');reflectanceOption.disabled=reflectanceOption.hidden=info.some(d=>!d.has_gold);
    if(reflectanceOption.disabled&&$('#compare-stage').value==='reflectance')$('#compare-stage').value='raw';
    fill($('#compare-band'),commonBands(),$('#compare-band').value);if(!$('#compare-band').value){$('#compare-status').textContent='No common wavenumber for this stage.';return;}
    $('#compare-export').disabled=false;$('#compare-status').textContent='Each image has its own color scale. CNR uses each folder’s independently selected target and background ROIs.';
    const kind=$('#compare-stage').value,wn=+$('#compare-band').value;
    const colorRange=await sharedColorRange(kind,wn,current);if(current!==revision)return;
    if(colorRange)$('#compare-status').textContent=`Same-stage shared colorbar: ${colorRange.display_min} to ${colorRange.display_max}. CNR retains each image’s independent calculation.`;
    for(const d of info){
      const card=el('div');card.className='card';card.append(el('h3',d.name));card.append(el('p',d.has_gold?'Processing basis: gold-normalized reflectance':'Processing basis: raw intensity · reflectance skipped'));const options=el('div');options.className='dataset-options';
      const choice=selections.get(d.id)||{pattern:d.patterns[0]};choice.low=d.cnr[0]?.contrast_low_percentile??0;choice.high=d.cnr[0]?.contrast_high_percentile??100;selections.set(d.id,choice);
      const label=el('label','Pattern'),select=el('select');fill(select,d.patterns,choice.pattern);choice.pattern=select.value;label.append(select);options.append(label);
      for(const key of ['low','high']){const l=el('label',`${key==='low'?'Lower':'Upper'} display / CNR percentile`),input=el('input');input.type='number';input.min=0;input.max=100;input.value=choice[key];input.disabled=!!colorRange;input.onchange=async()=>{
        const dataset=datasets.find(x=>x.id===d.id),range={low:choice.low,high:choice.high,[key]:Number(input.value)};
        dataset.busy=true;tabs();$('#compare-export').disabled=true;document.querySelectorAll('#comparison input, #comparison select, #comparison button').forEach(n=>n.disabled=true);
        try{const result=await api('/api/cnr?'+new URLSearchParams({dataset:d.id}),{...d.cnr_rois,...range});tell(dataset,{type:'cnr-contrast',...range,records:result.records});}
        catch(e){$('#compare-status').textContent=e.message;input.value=choice[key];}
        finally{dataset.busy=false;tabs();document.querySelectorAll('#comparison input, #comparison select, #comparison button').forEach(n=>n.disabled=false);await loadComparison();}
      };l.append(input);options.append(l);}
      select.onchange=()=>{choice.pattern=select.value;loadComparison();};card.append(options);
      choice.zero??={};const zeroLabel=el('label'),zeroInput=el('input');zeroInput.type='checkbox';zeroInput.checked=!colorRange&&!!choice.zero[kind];zeroInput.disabled=!!colorRange;zeroLabel.append(zeroInput,document.createTextNode('Set lower limit to 0 · display only'));card.append(zeroLabel);zeroInput.onchange=()=>{choice.zero[kind]=zeroInput.checked;loadComparison();};
      card.append(el('h4',$('#compare-stage').selectedOptions[0].textContent));const metrics=el('p');metrics.className='cnr-parameters';const row=d.cnr.find(r=>r.pattern===choice.pattern&&r.wavenumber===wn&&r.stage===kind);
      const number=(v,digits=2)=>typeof v==='number'&&Number.isFinite(v)?digits===0?v.toFixed(0):v.toExponential(2):'—';
      metrics.innerHTML=`<div>Unadjusted CNR: ${number(row?.cnr_unadjusted,0)} · CNR: ${number(row?.cnr,0)} · Percentiles: ${row?.contrast_low_percentile}–${row?.contrast_high_percentile}</div><div><i>A</i><sub>s</sub>: ${number(row?.target_mean)} · <i>A</i><sub>bg</sub>: ${number(row?.background_mean)} · σ<sub>bg</sub>: ${number(row?.background_std)} · |<i>A</i><sub>s</sub> − <i>A</i><sub>bg</sub>|: ${number(row?.signed_contrast==null?null:Math.abs(row.signed_contrast))}</div>`;card.append(metrics);$('#comparison-grid').append(card);
      const data=await api('/api/image?'+new URLSearchParams({dataset:d.id,pattern:choice.pattern,wavenumber:wn,kind,cmap:$('#compare-cmap').value,cnr_background_source:d.cnr_rois?.background_source||'manual',low:choice.low,high:choice.high,colorbar_zero:!colorRange&&!!choice.zero[kind],...(colorRange||{})}));if(current!==revision)return;
      if(!data.available){card.append(el('p','Stage unavailable'));continue;}
      const wrap=el('div');wrap.className='heatmap';const img=el('img');img.alt=`${d.name} ${choice.pattern} ${wn} ${kind}`;img.src='data:image/png;base64,'+data.png;const bar=el('div');bar.className='bar';const strip=el('div');strip.className='strip';QCLImages.setColorbar(strip,$('#compare-cmap').value);const ticks=el('div');ticks.className='ticks';[data.vmax,(data.vmin+data.vmax)/2,data.vmin].forEach(v=>ticks.append(el('span',v.toFixed(3))));bar.append(strip,ticks);
      const holder=el('div');holder.style.cssText='position:relative;width:calc(100% - 60px);align-self:start';img.style.width='100%';img.style.display='block';holder.append(img);
      const ns='http://www.w3.org/2000/svg',overlay=document.createElementNS(ns,'svg');overlay.classList.add('roi-overlay');overlay.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);overlay.setAttribute('preserveAspectRatio','none');overlay.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';
      for(const [name,color] of [['background','#00eaff'],['target','#7dff00']]){const roi=d.cnr_rois?.[name];if(!roi)continue;const box=document.createElementNS(ns,'rect');for(const [key,value] of Object.entries({x:roi.x_min,y:roi.y_min,width:roi.x_max-roi.x_min,height:roi.y_max-roi.y_min,fill:'none',stroke:color,'stroke-width':1,'stroke-opacity':1,'stroke-dasharray':'4 3','vector-effect':'non-scaling-stroke'}))box.setAttribute(key,value);overlay.append(box);}if(data.cell_free_pixels){const path=document.createElementNS(ns,'path'),arm=Math.max(1.25,data.width/320);path.setAttribute('d',data.cell_free_pixels.map(([y,x])=>`M${x+.5-arm} ${y+.5}h${2*arm}M${x+.5} ${y+.5-arm}v${2*arm}`).join(''));path.setAttribute('stroke','#00eaff');path.setAttribute('stroke-width',Math.max(.35,data.width/1200));path.setAttribute('fill','none');overlay.append(path);}holder.append(overlay);wrap.append(holder,bar);card.append(wrap);QCLPixelAxes.attach(img,{width:data.width,height:data.height});
      card.append(el('p',`Target pixels: ${row?.target_pixels??0} · Background pixels: ${row?.background_pixels??0} · ${row?.status||'unavailable'}`));
      const profile=attachComparisonProfile({card,img,overlay,data,dataset:d,choice,kind,wn,current});
      const download=el('button','Download current image · PNG');download.className='secondary';card.append(download);
      download.onclick=async()=>{
        download.disabled=true;card.downloadInProgress=true;document.body.classList.add('busy');
        try{
          await img.decode();await profile.ensureReady();
          if(current!==revision)throw Error('Comparison changed. Download the refreshed image.');
          const stage=$('#compare-stage').selectedOptions[0].textContent;
          await QCLImages.download(img,data,`${d.name} · ${choice.pattern} · ${wn} cm⁻¹ · ${stage}`,
            `${d.name}_${choice.pattern}_${wn}_${kind==='baseline'?'Abs_baseline_corrected':kind}`,card,
            {profileStatus:profile.status.textContent,information:[
              d.has_gold?'Processing basis: gold-normalized reflectance':'Processing basis: raw intensity',
              `Target pixels: ${row?.target_pixels??0} · Background pixels: ${row?.background_pixels??0} · Excluded background pixels: ${row?.excluded_background_pixels??0} · Status: ${row?.status||'unavailable'}`,
              `Color map: ${$('#compare-cmap').selectedOptions[0].textContent} · ${colorRange?'Same-stage shared colorbar limits':'Independent image colorbar limits'}`]});
        }catch(e){$('#compare-status').textContent=e.message;}
        finally{download.disabled=false;card.downloadInProgress=false;document.body.classList.remove('busy');}
      };
    }
  }catch(e){if(current===revision)$('#compare-status').textContent=e.message;}
}
$('#compare-stage').onchange=$('#compare-band').onchange=()=>{automaticColorLimits=true;loadComparison();};$('#compare-refresh').onclick=loadComparison;
$('#compare-cmap').onchange=loadComparison;
$('#compare-shared-scale').onchange=()=>{automaticColorLimits=true;loadComparison();};
for(const id of ['compare-color-min','compare-color-max'])$('#'+id).onchange=()=>{automaticColorLimits=false;loadComparison();};
$('#compare-color-auto').onclick=()=>{automaticColorLimits=true;loadComparison();};
$('#compare-export').onclick=async()=>{try{const r=await fetch('/api/comparison-export?'+new URLSearchParams({ids:datasets.map(d=>d.id).join(',')}));if(!r.ok)throw Error((await r.json()).error);const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download=QCLUpload.zipName($('#compare-zip-name').value,'qcl-folder-comparison');a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(e){$('#compare-status').textContent=e.message;}};
tabs();


function attachComparisonProfile({card,img,overlay,data,dataset,choice,kind,wn,current}){
  let ready=false;
  const line=choice.line??={direction:'horizontal',start:null,end:null,selecting:false,revision:0};
  const controls=el('div');controls.className='toolbar';
  const label=el('label','Line direction'),direction=el('select');
  for(const value of ['horizontal','vertical']){const option=el('option',value==='horizontal'?'Horizontal':'Vertical');option.value=value;direction.append(option);}direction.value=line.direction;label.append(direction);
  const select=el('button','Select line start / end'),clear=el('button','Clear line');select.className=clear.className='secondary';
  const status=el('p');status.className='hint';status.setAttribute('role','status');
  controls.append(label,select,clear);card.append(controls,status);
  img.draggable=false;img.style.cursor='crosshair';img.style.touchAction='none';
  const valid=p=>!p||(p.x>=0&&p.y>=0&&p.x<data.width&&p.y<data.height);
  if(!valid(line.start)||!valid(line.end)){line.start=line.end=null;line.selecting=false;line.revision++;}
  function draw(){QCLLine.drawLine(overlay,line.start,line.end,data.width);}
  function clearLine(){ready=false;line.revision++;line.start=line.end=null;line.selecting=false;card.querySelector('.line-profile-plot')?.remove();draw();status.textContent='Choose Horizontal or Vertical, then select two points. Positions and profiles are independent for each folder; values are unaffected by display contrast.';}
  async function refresh(){
    ready=false;const token=++line.revision;
    if(!line.start||!line.end)return;
    status.textContent='Calculating line profile…';card.querySelector('.line-profile-plot')?.remove();
    try{
      const result=await api('/api/line-profile?'+new URLSearchParams({dataset:dataset.id}),{pattern:choice.pattern,wavenumber:wn,start:line.start,end:line.end});
      if(token!==line.revision||current!==revision)return;
      QCLLine.renderPlot(card,kind,dataset.name+' '+kind,dataset.has_gold,result);ready=true;
      status.textContent=`Start (${result.start.x}, ${result.start.y}) → End (${result.end.x}, ${result.end.y}) · ${result.distance.at(-1).toFixed(2)} pixels · Actual stage values; invalid samples appear as gaps.`;
    }catch(e){if(token===line.revision&&current===revision)status.textContent=e.message;}
  }
  select.onclick=()=>{clearLine();line.selecting=true;status.textContent='Click the start point on this image.';};
  clear.onclick=clearLine;
  direction.onchange=()=>{line.direction=direction.value;clearLine();};
  img.onpointerdown=e=>{
    if(card.downloadInProgress||!line.selecting||e.button!==0||current!==revision||datasets.some(d=>d.busy))return;
    e.preventDefault();e=QCLImages.eventPoint(e,img);const rect=img.getBoundingClientRect();
    let point={x:Math.max(0,Math.min(data.width-1,Math.floor((e.clientX-rect.left)*data.width/rect.width))),y:Math.max(0,Math.min(data.height-1,Math.floor((e.clientY-rect.top)*data.height/rect.height)))};
    if(!line.start){line.start=point;status.textContent=`Start (${point.x}, ${point.y}). Click the end point; it snaps ${line.direction}ly.`;}
    else{
      point=QCLLine.snapEnd(line.start,point,line.direction);
      if(point.x===line.start.x&&point.y===line.start.y){status.textContent='Choose a different end position along the selected direction.';return;}
      line.end=point;line.selecting=false;refresh();
    }
    draw();
  };
  draw();
  if(line.end)refresh();
  else status.textContent=line.start?'Click the end point on this image.':'Choose Horizontal or Vertical, then select two points. Each folder has its own line.';
  return {status,ensureReady:async()=>{if(line.end&&!ready){await refresh();if(!ready)throw Error('Line profile is not ready. Please retry the download.');}}};
}
